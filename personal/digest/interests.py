"""Manual proposal only. Sources must be explicitly listed in local configuration."""
from pathlib import Path
from pypdf import PdfReader
from .common import ROOT, write_json, read_json
from .codex import Codex, obj, STR, STRINGS
from .store import Store

def propose(config):
    store=Store();store.pull()
    if store.data.get('profile'):
        config={**config,'research_lines':store.data['profile']['research_lines']}
    files=[]
    for directory in config.get('context_directories',[]):
        path=Path(directory).expanduser().resolve()
        files.extend(p for p in path.rglob('*') if p.is_file() and p.suffix.lower() in {'.pdf','.tex','.txt','.md'})
    files.extend(Path(p).expanduser().resolve() for p in config.get('chat_exports',[]))
    snippets=[]
    for p in sorted(set(files)):
        if p.suffix.lower()=='.pdf':
            reader=PdfReader(p);content='\n'.join((page.extract_text() or '') for page in reader.pages[:2])
        else:content=p.read_text(errors='replace')[:5000]
        snippets.append({'filename':p.name,'excerpt':content[:5000]})
    if not snippets:raise RuntimeError('No designated source paths. Set context_directories or chat_exports locally; no automatic disk/chat scan is performed.')
    if sum(len(s['excerpt']) for s in snippets)>180000:
        raise RuntimeError('Selected context exceeds 180,000 characters; narrow the designated directories or exports')
    proposal=Codex(config).run('依据材料提出新增研究兴趣；每项附文件证据和不确定性。已有方向不删除、不降级。只提出建议，不修改当前配置。',
        {'current':config['research_lines'],'sources':snippets},obj({'suggestions':{'type':'array','items':obj({'direction':STR,'evidence':STRINGS,'uncertainty':STR})}}))
    write_json(ROOT/'runtime'/'interest-proposal.json',proposal)
    if store.remote_configured:
        import os
        store.request('research_profiles','?user_id=eq.'+os.environ['OWNER_USER_ID'],{'proposal':proposal},'PATCH')
    return proposal

def accept(config):
    store=Store();store.pull()
    if store.data.get('profile'):
        config={**config,'research_lines':store.data['profile']['research_lines']}
    proposal=read_json(ROOT/'runtime'/'interest-proposal.json')
    if not proposal:raise RuntimeError('No proposal to accept')
    merged=list(config['research_lines'])
    for s in proposal['suggestions']:
        if s['direction'] not in merged:merged.append(s['direction'])
    new={**config,'research_lines':merged}
    write_json(ROOT/'config.local.json',new)
    if store.remote_configured:store.push_profile({'research_lines':merged})
    return merged
