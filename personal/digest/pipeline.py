from datetime import timedelta
from .common import ROOT, yesterday, today, write_json, read_json, fingerprint
from .arxiv import Client, collect, metadata, extract_fulltext
from .codex import Codex
from .store import Store

def prepare(config, days=None):
    store=Store();store.pull()
    bootstrap=days is None and not store.data.get('bootstrap_complete',False)
    if store.data.get('profile'):config={**config,'research_lines':store.data['profile']['research_lines']}
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
        if len({p['id'] for p in batch})!=len(batch):
            results={}
            for p in batch:results[p['version_id']]=model.screen([p])[p['id']]
        else:results=None
        if results is None:
            screened=model.screen(batch);results={p['version_id']:screened[p['id']] for p in batch}
        for p in batch:
            p.update(results[p['version_id']])
            if p['event']=='revision':
                prior=store.data['papers'].get(p['id'],{})
                p['high_related']=bool(prior.get('high_related') or p['high_related'])
                if not (p['high_related'] or store.data['states'].get(p['id'],{}).get('favorite')):
                    p['exclude_from_digest']=True
                    continue
                if p['relevance']=='unrelated':p['relevance']='extension'
            if p['relevance']!='unrelated' and not store.data['states'].get(p['id'],{}).get('disliked'):
                try:
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
        print(f'摘要筛选进度 {min(start+size,len(papers))}/{len(papers)}',flush=True)
    digests=[]
    for day in days:
        ds=str(day)
        digest={'day':ds,'papers':[p for p in papers if p['announcement_date']==ds and not p.get('exclude_from_digest')],
                'warnings':[w for w in warnings if ds in w],
                'model':config.get('model'),'reasoning_effort':config.get('reasoning_effort'),
                'research_profile_hash':fingerprint(config['research_lines'])}
        write_json(ROOT/'runtime'/'digests'/(ds+'.json'),digest)
        store.data['digests'][ds]={'prepared':True,'published':False}
        store.save();digests.append(digest)
    if bootstrap:
        store.data['bootstrap_complete']=True
        store.save()
    return digests,model.calls
