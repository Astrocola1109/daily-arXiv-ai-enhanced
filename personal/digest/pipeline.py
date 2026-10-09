from datetime import timedelta
from .common import ROOT, yesterday, today, write_json, read_json, fingerprint
from .arxiv import Client, collect, metadata, extract_fulltext
from .codex import Codex, SCREENING_POLICY
from .store import Store

SCREEN_FIELDS=('relevance','reason','research_lines','high_related')
SOURCE_FIELDS=('title','abstract','authors','primary_category','categories')

def cached_papers(profile_hash):
    result={}
    paths=list((ROOT/'runtime'/'digests').glob('*.json'))+list((ROOT/'runtime'/'checkpoints').glob('*.json'))
    for path in sorted(paths,key=lambda p:p.stat().st_mtime):
        digest=read_json(path,{})
        if digest.get('research_profile_hash')!=profile_hash:continue
        for paper in digest.get('papers',[]):
            if all(key in paper for key in SCREEN_FIELDS):
                prior=result.get(paper['version_id'])
                if prior is None or paper.get('screening_policy')==SCREENING_POLICY or paper.get('analysis_status')=='complete':
                    result[paper['version_id']]=paper
    return result

def prepare(config, days=None):
    store=Store();store.pull()
    plan=read_json(ROOT/'runtime'/'initial-plan.json',{})
    bootstrap=days is None and not store.data.get('bootstrap_complete',False) and not plan.get('backfill_paused',False)
    if store.data.get('profile'):config={**config,'research_lines':store.data['profile']['research_lines']}
    profile_hash=fingerprint(config['research_lines'])
    cached=cached_papers(profile_hash)
    if days is None:
        days=[yesterday()-timedelta(days=i) for i in reversed(range(7))] if bootstrap else [yesterday()]
    client=Client();papers,revisions,warnings=collect(client,config['categories'],days)
    revision_events={}
    for event in revisions:
        # Unknown older papers may be highly relevant: screen their revision
        # abstracts before deciding whether they qualify for a reminder.
        # Retain events on retries too; model caching handles duplicate work.
        revision_events[event['version_id']]=event
    if revision_events:
        for p in metadata(client,list(revision_events)):
            e=revision_events[p['version_id']]
            p.update(announcement_date=e['day'],event='revision',date_evidence='archived arXiv RSS revision announcement')
            papers.append(p)
    model=Codex(config)
    size=max(1,min(30,config.get('batch_size',12)))
    # Batches use unique base identifiers; a same-day revision is classified separately.
    for start in range(0,len(papers),size):
        batch=papers[start:start+size]
        reusable={p['version_id']:cached[p['version_id']] for p in batch
                  if p['version_id'] in cached and all(p.get(k)==cached[p['version_id']].get(k) for k in SOURCE_FIELDS)}
        results={v:{**{k:old[k] for k in SCREEN_FIELDS},'abstract_short':old.get('abstract_short','')}
                 for v,old in reusable.items() if old['relevance']!='extension' or
                 (old.get('screening_policy')==SCREENING_POLICY and old.get('abstract_short'))}
        pending=[p for p in batch if p['version_id'] not in results]
        if len({p['id'] for p in pending})!=len(pending):
            for p in pending:results[p['version_id']]=model.screen([p])[p['id']]
        elif pending:
            screened=model.screen(pending)
            results.update({p['version_id']:screened[p['id']] for p in pending})
        for p in batch:
            p.update(results[p['version_id']])
            p['screening_policy']=SCREENING_POLICY
            if p['event']=='revision':
                prior=store.data['papers'].get(p['id'],{})
                p['high_related']=bool(prior.get('high_related') or p['high_related'])
                if not (p['high_related'] or store.data['states'].get(p['id'],{}).get('favorite')):
                    p['exclude_from_digest']=True
                    continue
                if p['relevance']=='unrelated':p['relevance']='extension'
            if p['relevance']=='extension':
                # Extension recommendations use only the abstract, never a PDF/model card call.
                p['analysis_status']='summary_only'
                p['card']={'abstract_zh':p.get('abstract_short') or p['abstract'], 'connection':p['reason'],
                           'limitations':['仅依据原摘要生成简述，未据此核验正文。']}
                p['source_coverage']={'abstract_only':True}
                p.pop('references_text',None);p.pop('analysis_error',None)
            elif p['relevance']=='direct' and not store.data['states'].get(p['id'],{}).get('disliked'):
                try:
                    old=reusable.get(p['version_id'],{})
                    if old.get('analysis_status')=='complete' and old.get('card') and old.get('source_coverage'):
                        for key in ('card','source_coverage','references_text'):p[key]=old.get(key,'')
                    else:
                        source=extract_fulltext(client,p['version_id'],config.get('max_source_chars',480000))
                        p['card']=model.card(p,source)
                        p['source_coverage']={k:v for k,v in source.items() if k not in {'text','references_text'}}
                        p['references_text']=source['references_text']
                    p['analysis_status']='complete'
                except Exception as exc:
                    p['analysis_status']='needs_retry';p['analysis_error']=str(exc)
                    p['card']={'limitations':['深读未完成；当前推荐仅依据摘要。']}
            else:p['analysis_status']='abstract_only'
            prior=store.data['papers'].get(p['id'])
            if prior is None or int(p['version_id'].rsplit('v',1)[-1])>=int(prior['version_id'].rsplit('v',1)[-1]):
                store.data['papers'][p['id']]=p
            store.save()
        write_json(ROOT/'runtime'/'checkpoints'/('processing-'+profile_hash+'.json'),
                   {'research_profile_hash':profile_hash,'papers':papers[:start+size]})
        print(f'摘要筛选进度 {min(start+size,len(papers))}/{len(papers)}',flush=True)
    digests=[]
    for day in days:
        ds=str(day)
        digest={'day':ds,'papers':[p for p in papers if p['announcement_date']==ds and not p.get('exclude_from_digest')],
                'warnings':[w for w in warnings if ds in w],
                'model':config.get('model'),'reasoning_effort':config.get('reasoning_effort'),
                'research_profile_hash':profile_hash,'screening_policy':SCREENING_POLICY}
        write_json(ROOT/'runtime'/'digests'/(ds+'.json'),digest)
        store.data['digests'][ds]={'prepared':True,'published':False}
        store.save();digests.append(digest)
    if bootstrap:
        store.data['bootstrap_complete']=True
        store.save()
    return digests,model.calls
