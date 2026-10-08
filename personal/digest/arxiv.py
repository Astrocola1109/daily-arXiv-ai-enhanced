"""Use dated announcements, never API submission timestamps, for calendar selection."""
import re, time, json, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, date
from pathlib import Path
from bs4 import BeautifulSoup
from pypdf import PdfReader
from .common import ROOT, BJ, today, read_json, write_json, fingerprint

ATOM = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom', 'dc': 'http://purl.org/dc/elements/1.1/'}
ID = re.compile(r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$')

def valid_id(aid):
    if not ID.fullmatch(aid): raise ValueError('Invalid arXiv identifier')
    return aid

def base_id(aid): return re.sub(r'v\d+$', '', valid_id(aid))

class Client:
    def __init__(self, cache=None):
        self.cache = Path(cache or ROOT / 'runtime' / 'http')
        self.cache.mkdir(parents=True, exist_ok=True)
        self.last = 0

    def get(self, url, permanent=False):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'arxiv.org', 'export.arxiv.org', 'rss.arxiv.org'}:
            raise ValueError('Only official arXiv HTTPS endpoints are allowed')
        key = fingerprint([url, 'immutable' if permanent else today().isoformat()])
        path = self.cache / key
        if path.exists(): return path.read_bytes()
        for attempt in range(3):
            time.sleep(max(0, 3.1 - (time.monotonic() - self.last)))
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'PersonalResearchDigest/1.0 (single-user; cached requests)'})
                with urllib.request.urlopen(req, timeout=90) as response:
                    data = response.read(30_000_001)
                    if len(data) > 30_000_000: raise RuntimeError('Source exceeds 30 MB download limit')
                    if urllib.parse.urlsplit(response.url).hostname not in {'arxiv.org', 'export.arxiv.org', 'rss.arxiv.org'}:
                        raise RuntimeError('Unexpected redirect')
                path.write_bytes(data)
                return data
            except Exception:
                if attempt == 2: raise
                time.sleep(2 ** attempt * 3)
            finally: self.last = time.monotonic()

def parse_recent(raw, category):
    soup = BeautifulSoup(raw, 'html.parser')
    result = []
    dated_headings = 0
    for heading in soup.find_all('h3'):
        text = heading.get_text(' ', strip=True)
        match = re.search(r'([A-Z][a-z]{2}, \d{1,2} [A-Z][a-z]{2} \d{4})', text)
        if not match: continue
        dated_headings += 1
        counts = re.search(r'showing\s+(\d+)\s+of\s+(\d+)\s+entries', text)
        if counts and int(counts[1]) < int(counts[2]):
            raise RuntimeError(f'{category}: announcement listing is truncated; pagination required')
        day = datetime.strptime(match[1], '%a, %d %b %Y').date().isoformat()
        listing = heading.find_next('dl')
        if listing is None: continue
        for dt in listing.find_all('dt'):
            link = dt.find('a', href=re.compile(r'^/abs/'))
            if not link: continue
            aid = base_id(link['href'].removeprefix('/abs/'))
            result.append({'id': aid, 'day': day, 'category': category, 'cross': 'cross-list' in dt.get_text()})
    if not dated_headings and not re.search(r'no (?:new )?(?:articles|entries|updates|submissions)', soup.get_text(), re.I):
        raise RuntimeError(f'{category}: announcement page was not recognized; refusing to treat it as an empty day')
    return result

def parse_feed(raw):
    root = ET.fromstring(raw)
    entries = []
    for e in root.findall('a:entry', ATOM):
        aid = e.findtext('a:id', '', ATOM).removeprefix('oai:arXiv.org:')
        if not ID.fullmatch(aid): raise RuntimeError('Unexpected feed identifier')
        timestamp = e.findtext('a:published', '', ATOM)
        # RSS published is the announcement date; API published is NOT.
        day = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).astimezone(BJ).date().isoformat()
        entries.append({'id': base_id(aid), 'version_id': aid, 'day': day,
                        'kind': e.findtext('x:announce_type', '', ATOM),
                        'categories': [c.get('term') for c in e.findall('a:category', ATOM)]})
    return entries

def parse_metadata(raw):
    root = ET.fromstring(raw)
    result = []
    for e in root.findall('a:entry', ATOM):
        aid = e.findtext('a:id', '', ATOM).split('/abs/')[-1]
        valid_id(aid)
        pc = e.find('x:primary_category', ATOM)
        result.append({'id': base_id(aid), 'version_id': aid,
            'title': ' '.join(e.findtext('a:title', '', ATOM).split()),
            'abstract': e.findtext('a:summary', '', ATOM).strip(),
            'authors': [a.findtext('a:name', '', ATOM) for a in e.findall('a:author', ATOM)],
            'primary_category': pc.get('term') if pc is not None else '',
            'categories': [c.get('term') for c in e.findall('a:category', ATOM)],
            'submitted_at': e.findtext('a:published', '', ATOM),
            'updated_at': e.findtext('a:updated', '', ATOM),
            'url': 'https://arxiv.org/abs/' + aid})
    return result

def metadata(client, ids):
    output = []
    for start in range(0, len(ids), 75):
        batch = ids[start:start+75]
        url = 'https://export.arxiv.org/api/query?' + urllib.parse.urlencode({'id_list': ','.join(batch), 'max_results': len(batch)})
        output += parse_metadata(client.get(url))
    if len(output)!=len(ids) or {p['id'] for p in output} != {base_id(x) for x in ids}:
        raise RuntimeError('arXiv metadata response is incomplete; retry required')
    expected={x for x in ids if re.search(r'v\d+$',x)}
    pinned_bases={base_id(x) for x in expected}
    if any(p['id'] in pinned_bases and p['version_id'] not in expected for p in output) or not expected.issubset({p['version_id'] for p in output}):
        raise RuntimeError('arXiv returned a different version than requested')
    return output

def collect(client, categories, days):
    wanted = {str(d) for d in days}
    listings = {}; candidates = {}; feed_events = {}; warnings = []
    for cat in categories:
        if not re.fullmatch(r'[a-z-]+(?:\.[A-Z]{2})?', cat): raise ValueError('Invalid category')
        listing = parse_recent(client.get('https://arxiv.org/list/' + cat + '/recent?show=2000'), cat)
        listings[cat] = listing
        for p in listing:
            if p['day'] in wanted: candidates.setdefault(p['id'], set()).add(p['day'])
        feed = parse_feed(client.get('https://rss.arxiv.org/atom/' + cat))
        # Keep every observed feed for exact revision announcements and catch-up.
        for day in {p['day'] for p in feed}:
            path = ROOT / 'runtime' / 'feeds' / (cat + '-' + day + '.json')
            write_json(path, [p for p in feed if p['day'] == day])
        for day in wanted:
            saved = read_json(ROOT / 'runtime' / 'feeds' / (cat + '-' + day + '.json'), [])
            if not saved and date.fromisoformat(day).weekday() < 5:
                warnings.append(cat + ' ' + day + '：未存档当日修订公告；新论文仍从日期目录回溯。')
            for event in saved:
                feed_events[(event['version_id'], day)] = event
                if event['kind'] in {'new', 'cross'}: candidates.setdefault(event['id'], set()).add(day)
    # Explicit v1 keeps a later revision from contaminating a historical new-paper card.
    papers = metadata(client, [aid + 'v1' for aid in sorted(candidates)]) if candidates else []
    for cat in sorted({p['primary_category'] for p in papers} - set(listings)):
        if not re.fullmatch(r'[a-z-]+(?:\.[A-Z]{2})?', cat): raise RuntimeError('Unknown primary category')
        listings[cat] = parse_recent(client.get('https://arxiv.org/list/' + cat + '/recent?show=2000'), cat)
    first_dates = {p['id']: p['day'] for entries in listings.values() for p in entries if not p['cross']}
    output = []
    for p in papers:
        day = first_dates.get(p['id'])
        if day in wanted:
            p.update(announcement_date=day, event='new', date_evidence='primary-category dated listing')
            output.append(p)
        elif day is None:
            # Do not drop uncertain cross-lists; label them, never call them new.
            p.update(announcement_date=max(candidates[p['id']]), event='cross_uncertain', date_evidence='cross-list only; first announcement unverified')
            output.append(p)
    revisions = [p for p in feed_events.values() if p['kind'] in {'replace', 'replace-cross'}]
    return output, revisions, sorted(set(warnings))

def extract_fulltext(client, version_id, max_chars=480000):
    valid_id(version_id)
    if not re.search(r'v\d+$', version_id): raise ValueError('Full text must use a pinned version')
    path = ROOT / 'runtime' / 'papers' / (version_id.replace('/', '_') + '.pdf')
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists(): path.write_bytes(client.get('https://arxiv.org/pdf/' + version_id, permanent=True))
    reader = PdfReader(path)
    pages = [(i+1, page.extract_text() or '') for i, page in enumerate(reader.pages)]
    if sum(len(s.strip()) for _, s in pages) < 500: raise RuntimeError('PDF text extraction failed; manual reading required')
    text = '\n'.join(f'\n[PDF page {i}]\n{s}' for i, s in pages)
    refs = re.search(r'(?im)^\s*(?:\d+\.?\s+)?(?:references|bibliography)\s*$', text)
    references = text[refs.start():] if refs else ''
    complete = len(text) <= max_chars
    selected = pages
    if not complete:
        # Preserve introduction, theorem/conditions context, conclusion and bibliography.
        selected_numbers = set(range(1, min(9, len(pages)+1))) | set(range(max(1,len(pages)-7),len(pages)+1))
        for number, s in pages:
            if re.search(r'(?im)(?:main theorem|theorem\s+[A-Z\d]|conclusion|main result)', s):
                selected_numbers.update([max(1,number-1),number,min(len(pages),number+1)])
        selected = [(i,s) for i,s in pages if i in selected_numbers]
        text = '\n'.join(f'\n[PDF page {i}]\n{s}' for i,s in selected)
    if len(text) > max_chars:
        raise RuntimeError(f'{version_id}: selected source still exceeds {max_chars} characters; increase budget or split explicitly')
    return {'text': text, 'references_text': references, 'pages_total': len(pages),
            'pages_read': [i for i,_ in selected], 'full_text': complete, 'version_id': version_id}
