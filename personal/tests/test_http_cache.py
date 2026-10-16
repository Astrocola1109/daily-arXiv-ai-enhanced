import tempfile,unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from digest.arxiv import Client,dated_listing
from digest.common import fingerprint,read_json

class CacheRecoveryTests(unittest.TestCase):
 def test_closed_day_uses_validated_snapshot_without_poisoning_current_cache(self):
  with tempfile.TemporaryDirectory() as tmp,patch('digest.arxiv.today',return_value=date(2026,10,16)):
   client=Client(tmp);url='https://arxiv.org/list/math.OA/recent?show=2000'
   old=client.cache/fingerprint([url,'2026-10-15'])
   old.write_bytes(b'<dl><h3>Wed, 14 Oct 2026 (showing 1 of 1 entries)</h3><dt><a href="/abs/2610.00001">paper</a></dt></dl>')
   with patch.object(client,'get',side_effect=AssertionError('network')):
    rows=dated_listing(client,'math.OA',['2026-10-14'])
   self.assertEqual(rows[0]['day'],'2026-10-14')
   self.assertFalse((client.cache/fingerprint([url,'2026-10-16'])).exists())
   with patch.object(client,'get',return_value=old.read_bytes()) as get:
    dated_listing(client,'math.OA',['2026-10-15'])
    get.assert_called_once() # Snapshot cannot establish a different day's absence.
 def test_pinned_metadata_adopts_exact_legacy_url_only(self):
  with tempfile.TemporaryDirectory() as tmp,patch('digest.arxiv.today',return_value=date(2026,10,16)):
   client=Client(tmp);url='https://export.arxiv.org/api/query?id_list=2610.00001v1&max_results=1'
   (client.cache/fingerprint([url,'2026-10-15'])).write_bytes(b'cached XML')
   with patch('digest.arxiv.urllib.request.urlopen',side_effect=AssertionError('network')):
    self.assertEqual(client.get(url,permanent=True),b'cached XML')
   self.assertTrue((client.cache/fingerprint([url,'immutable'])).exists())
 def test_429_honors_long_retry_after_and_does_not_hammer(self):
  with tempfile.TemporaryDirectory() as tmp,patch('digest.arxiv.time.sleep'),patch('digest.arxiv.time.time',return_value=1000):
   client=Client(tmp);url='https://arxiv.org/list/math.OA/recent?show=2000'
   error=HTTPError(url,429,'limited',{'Retry-After':'3600'},None)
   with patch('digest.arxiv.urllib.request.urlopen',side_effect=error) as request:
    with self.assertRaisesRegex(RuntimeError,'429'):client.get(url)
    with self.assertRaisesRegex(RuntimeError,'cooldown'):client.get(url)
    self.assertEqual(request.call_count,1)
   self.assertEqual(read_json(client.cache/'rate-limits.json')['arxiv.org'],4600)
