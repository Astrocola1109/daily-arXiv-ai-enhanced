import json, os, urllib.request, urllib.parse
from .common import ROOT, read_json, write_json

def database_text(value):
    """Postgres jsonb rejects NUL; preserve its position as a replacement glyph.

    PDF extraction can produce NUL characters. Keep local source caches intact
    and normalize only the outgoing database representation.
    """
    if isinstance(value,str):return value.replace('\x00','\ufffd')
    if isinstance(value,list):return [database_text(item) for item in value]
    if isinstance(value,dict):return {database_text(k):database_text(v) for k,v in value.items()}
    return value

class Store:
    def __init__(self):
        self.path=ROOT/'runtime'/'library.json'
        self.data=read_json(self.path, {'papers':{},'states':{},'digests':{},'profile':None})

    def save(self): write_json(self.path,self.data)

    @property
    def remote_configured(self):
        return all(os.environ.get(k) for k in ('SUPABASE_URL','SUPABASE_SERVICE_ROLE_KEY','OWNER_USER_ID'))

    def request(self, table, query='', body=None, method='GET'):
        base=os.environ['SUPABASE_URL'].rstrip('/')
        if not base.startswith('https://') or not urllib.parse.urlsplit(base).hostname.endswith('.supabase.co'):
            raise ValueError('Expected your Supabase project HTTPS URL')
        key=os.environ['SUPABASE_SERVICE_ROLE_KEY']
        headers={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json',
                 'Prefer':'resolution=merge-duplicates,return=representation'}
        req=urllib.request.Request(base+'/rest/v1/'+table+query,
                                   data=None if body is None else json.dumps(database_text(body),ensure_ascii=False).encode(),
                                   headers=headers,method=method)
        with urllib.request.urlopen(req,timeout=45) as r:
            raw=r.read()
        return json.loads(raw) if raw else None

    def pull(self):
        if not self.remote_configured: return
        owner=os.environ['OWNER_USER_ID']
        states=[]
        while True:
            batch=self.request('reading_states','?user_id=eq.'+owner+'&select=*&order=paper_id&limit=500&offset='+str(len(states)))
            states.extend(batch)
            if len(batch)<500:break
        self.data['states']={s['paper_id']:s for s in states}
        profiles=self.request('research_profiles','?user_id=eq.'+owner+'&select=profile')
        if profiles:self.data['profile']=profiles[0]['profile']
        self.save()

    def publish(self, digest):
        if not self.remote_configured:raise RuntimeError('Private database is not configured; report retained locally')
        owner=os.environ['OWNER_USER_ID']
        for start in range(0,len(digest['papers']),50):
            rows=[{'user_id':owner,'paper_id':p['id'],'version_id':p['version_id'],
                   'announcement_date':p['announcement_date'],'payload':p}
                  for p in digest['papers'][start:start+50]]
            if rows:self.request('papers','?on_conflict=user_id,version_id',rows,'POST')
        payload={k:v for k,v in digest.items() if k!='papers'}
        payload['version_ids']=[p['version_id'] for p in digest['papers']]
        self.request('digests','?on_conflict=user_id,day',{'user_id':owner,'day':digest['day'],'payload':payload},'POST')

    def push_profile(self, profile):
        if not self.remote_configured:raise RuntimeError('Private database is not configured')
        self.request('research_profiles','?on_conflict=user_id',{'user_id':os.environ['OWNER_USER_ID'],'profile':profile},'POST')
        self.data['profile']=profile
        self.save()
