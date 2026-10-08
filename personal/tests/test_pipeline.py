import unittest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
from digest.arxiv import parse_recent,parse_feed,parse_metadata,valid_id,metadata
from digest.emailing import notifications,render
from digest.common import yesterday

class AnnouncementTests(unittest.TestCase):
    def test_listing_uses_heading_and_distinguishes_crosslist(self):
        raw='<h3>Wed, 7 Oct 2026 (showing 2 of 2 entries)</h3><dl><dt><a href="/abs/2610.00001">x</a></dt><dd>one</dd><dt><a href="/abs/2609.00002">x</a> (cross-list from math.CO)</dt><dd>old</dd></dl>'
        rows=parse_recent(raw,'math.QA')
        self.assertEqual([r['day'] for r in rows],['2026-10-07']*2)
        self.assertFalse(rows[0]['cross']);self.assertTrue(rows[1]['cross'])
    def test_rss_has_announcement_date_and_revision_type(self):
        raw='''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"><entry><id>oai:arXiv.org:2609.00001v2</id><published>2026-10-07T00:00:00-04:00</published><arxiv:announce_type>replace</arxiv:announce_type></entry></feed>'''
        row=parse_feed(raw)[0]
        self.assertEqual(row['day'],'2026-10-07');self.assertEqual(row['kind'],'replace');self.assertEqual(row['version_id'],'2609.00001v2')
    def test_bad_id_is_rejected(self):
        for aid in ['../secret','2610.12345;curl x','https://evil.test']:
            with self.assertRaises(ValueError):valid_id(aid)
    def test_unrecognized_or_truncated_list_is_not_an_empty_day(self):
        for raw in ['<html>Temporarily unavailable</html>', '<h3>Wed, 7 Oct 2026 (showing 2000 of 2001 entries)</h3><dl></dl>']:
            with self.assertRaises(RuntimeError):parse_recent(raw,'math.QA')
    def test_metadata_keeps_two_announced_versions_of_same_paper(self):
        from unittest.mock import Mock
        rows=[{'id':'2610.00001','version_id':'2610.00001v2'}, {'id':'2610.00001','version_id':'2610.00001v3'}]
        with patch('digest.arxiv.parse_metadata',return_value=rows):
            self.assertEqual(metadata(Mock(),['2610.00001v2','2610.00001v3']),rows)
        with patch('digest.arxiv.parse_metadata',return_value=rows[:1]):
            with self.assertRaises(RuntimeError):metadata(Mock(),['2610.00001v2','2610.00001v3'])
    def test_beijing_day_at_utc_boundary(self):
        with patch('digest.common.datetime') as clock:
            clock.now.return_value=datetime(2026,10,8,0,5,tzinfo=ZoneInfo('Asia/Shanghai'))
            self.assertEqual(str(yesterday()),'2026-10-07')

class NotificationTests(unittest.TestCase):
    def paper(self,kind='extension',event='new',high=False):
        return {'id':'2610.00001','version_id':'2610.00001v1','title':'A <script>','authors':['Author'],
                'reason':'方法相关','relevance':kind,'event':event,'high_related':high}
    def test_extension_only_still_sends(self):
        self.assertIsNotNone(render({'day':'2026-10-07','papers':[self.paper()]},'https://example.com/',{}))
    def test_revision_must_be_favorite_or_high(self):
        p=self.paper(event='revision')
        self.assertEqual(notifications([p],{}),[])
        self.assertEqual(len(notifications([p],{p['id']:{'favorite':True}})),1)
        p['high_related']=True;self.assertEqual(len(notifications([p],{})),1)
    def test_unrelated_and_disliked_are_quiet(self):
        p=self.paper('unrelated');self.assertIsNone(render({'day':'x','papers':[p]},'https://example.com/',{}))
        p=self.paper();self.assertEqual(notifications([p],{p['id']:{'disliked':True}}),[])
    def test_email_escapes_source_text(self):
        result=render({'day':'x','papers':[self.paper()]},'https://example.com/',{})
        self.assertNotIn('<script>',result[2]);self.assertIn('&lt;script&gt;',result[2])

if __name__=='__main__':unittest.main()
