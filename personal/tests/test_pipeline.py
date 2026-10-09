import unittest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
from digest.arxiv import parse_recent,parse_feed,parse_metadata,valid_id,metadata,collect
from digest.emailing import notifications,render
from digest.common import yesterday

class AnnouncementTests(unittest.TestCase):
    def test_crosslist_resolves_lowercase_hyphenated_primary_category(self):
        from unittest.mock import Mock
        client=Mock()
        listing=b'<h3>Wed, 7 Oct 2026 (showing 1 of 1 entries)</h3><dl><dt><a href="/abs/2610.00001">x</a></dt></dl>'
        client.get.side_effect=[listing,b'<feed xmlns="http://www.w3.org/2005/Atom"/>',listing]
        paper={'id':'2610.00001','version_id':'2610.00001v1','primary_category':'cond-mat.mes-hall'}
        with patch('digest.arxiv.metadata',return_value=[paper]), patch('digest.arxiv.read_json',return_value=[]):
            rows,_,_=collect(client,['math.QA'],['2026-10-07'])
        self.assertEqual(rows[0]['announcement_date'],'2026-10-07')
        self.assertIn('cond-mat.mes-hall/recent',client.get.call_args.args[0])
        for invalid in ['../secret','math.QA?redirect=x','math.QA/other']:
            with self.assertRaises(ValueError):collect(client,[invalid],[])
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
    def test_authentication_failure_does_not_block_a_later_delivery(self):
        import tempfile, smtplib
        from pathlib import Path
        from digest.emailing import deliver
        from digest.common import read_json
        config={'site_url':'https://example.com/','email_to':'recipient@example.com'}
        digest={'day':'2026-10-07','papers':[self.paper()]}
        env={'SMTP_HOST':'smtp.example.com','SMTP_USER':'sender@example.com','SMTP_PASSWORD':'test-fixture','SMTP_FROM':'sender@example.com'}
        with tempfile.TemporaryDirectory() as directory, patch('digest.emailing.ROOT',Path(directory)), patch.dict('os.environ',env), patch('digest.emailing.smtplib.SMTP_SSL') as factory:
            server=factory.return_value.__enter__.return_value
            server.login.side_effect=smtplib.SMTPAuthenticationError(535,b'authentication failed')
            with self.assertRaises(smtplib.SMTPAuthenticationError):deliver(digest,config,{},allow_early=True)
            self.assertFalse((Path(directory)/'runtime'/'mail-ledger.json').exists())
            server.send_message.assert_not_called()
            server.login.side_effect=None;server.send_message.return_value={}
            self.assertEqual(deliver(digest,config,{},allow_early=True),'sent')
            self.assertEqual(read_json(Path(directory)/'runtime'/'mail-ledger.json')[digest['day']]['state'],'sent')
            self.assertEqual(deliver(digest,config,{},allow_early=True),'already_sent')
            server.send_message.assert_called_once()
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

class RevisionDiscoveryTests(unittest.TestCase):
    def test_unseen_high_relevance_revision_is_read_and_low_relevance_is_excluded(self):
        import tempfile
        from pathlib import Path
        from datetime import date
        from unittest.mock import Mock
        from digest.pipeline import prepare
        store=Mock();store.data={'papers':{},'states':{},'digests':{},'profile':None}
        events=[{'id':aid,'version_id':aid+'v2','day':'2026-10-07'} for aid in ['2609.00001','2609.00002']]
        model=Mock();model.calls=[]
        model.screen.return_value={e['id']:{'id':e['id'],'relevance':'extension','high_related':i==0,'reason':'test','research_lines':[]} for i,e in enumerate(events)}
        model.card.return_value={'main_results':['source-grounded fixture']}
        source={'text':'fixture','references_text':'[1] fixture','pages_total':1,'pages_read':[1],'full_text':True}
        with tempfile.TemporaryDirectory() as directory, patch('digest.pipeline.ROOT',Path(directory)), patch('digest.pipeline.Store',return_value=store), patch('digest.pipeline.Client'), patch('digest.pipeline.collect',return_value=([],events,[])), patch('digest.pipeline.metadata',return_value=[dict(e) for e in events]), patch('digest.pipeline.Codex',return_value=model), patch('digest.pipeline.extract_fulltext',return_value=source) as extract:
            digests,_=prepare({'research_lines':['test'],'categories':['math.QA'],'batch_size':12},[date(2026,10,7)])
            self.assertEqual([p['id'] for p in digests[0]['papers']],['2609.00001'])
            self.assertEqual(extract.call_count,1)
            self.assertEqual(len(model.screen.call_args.args[0]),2)

class DigestReuseTests(unittest.TestCase):
    def test_backfill_reuses_completed_version_but_profile_change_invalidates(self):
        import tempfile
        from pathlib import Path
        from datetime import date
        from unittest.mock import Mock
        from digest.pipeline import prepare
        store=Mock();store.data={'papers':{},'states':{},'digests':{},'profile':None}
        paper={'id':'2610.00001','version_id':'2610.00001v1','announcement_date':'2026-10-07','event':'new','title':'Fixture','abstract':'Fixture abstract','authors':['Author'],'categories':['math.QA'],'primary_category':'math.QA'}
        model=Mock();model.calls=[]
        model.screen.side_effect=lambda papers:{p['id']:{'id':p['id'],'relevance':'extension','high_related':False,'reason':'fixture','research_lines':['test']} for p in papers}
        model.card.return_value={'main_results':['fixture result']}
        source={'text':'fixture','references_text':'[1] fixture','pages_total':1,'pages_read':[1],'full_text':True}
        config={'research_lines':['test'],'categories':['math.QA'],'batch_size':12}
        with tempfile.TemporaryDirectory() as directory, patch('digest.pipeline.ROOT',Path(directory)), patch('digest.pipeline.Store',return_value=store), patch('digest.pipeline.Client'), patch('digest.pipeline.collect',side_effect=lambda *a:([dict(paper)],[],[])), patch('digest.pipeline.Codex',return_value=model), patch('digest.pipeline.extract_fulltext',return_value=source) as extract:
            prepare(config,[date(2026,10,7)])
            model.screen.reset_mock();model.card.reset_mock();extract.reset_mock()
            result,_=prepare({**config,'batch_size':1},[date(2026,10,6),date(2026,10,7)])
            model.screen.assert_not_called();model.card.assert_not_called();extract.assert_not_called()
            self.assertEqual(result[1]['papers'][0]['analysis_status'],'complete')
            prepare({**config,'research_lines':['new direction']},[date(2026,10,7)])
            model.screen.assert_called_once();model.card.assert_called_once()

    def test_incomplete_card_retries_without_screening_abstract_again(self):
        import tempfile
        from pathlib import Path
        from datetime import date
        from unittest.mock import Mock
        from digest.pipeline import prepare
        store=Mock();store.data={'papers':{},'states':{},'digests':{},'profile':None}
        paper={'id':'2610.00001','version_id':'2610.00001v1','announcement_date':'2026-10-07','event':'new'}
        model=Mock();model.calls=[]
        model.screen.return_value={paper['id']:{'id':paper['id'],'relevance':'extension','high_related':False,'reason':'fixture','research_lines':[]}}
        model.card.side_effect=[RuntimeError('temporary failure'),{'main_results':['fixture result']}]
        source={'text':'fixture','references_text':'','pages_total':1,'pages_read':[1],'full_text':True}
        with tempfile.TemporaryDirectory() as directory, patch('digest.pipeline.ROOT',Path(directory)), patch('digest.pipeline.Store',return_value=store), patch('digest.pipeline.Client'), patch('digest.pipeline.collect',side_effect=lambda *a:([dict(paper)],[],[])), patch('digest.pipeline.Codex',return_value=model), patch('digest.pipeline.extract_fulltext',return_value=source):
            config={'research_lines':['test'],'categories':['math.QA']}
            first,_=prepare(config,[date(2026,10,7)])
            self.assertEqual(first[0]['papers'][0]['analysis_status'],'needs_retry')
            second,_=prepare(config,[date(2026,10,7)])
            self.assertEqual(second[0]['papers'][0]['analysis_status'],'complete')
            model.screen.assert_called_once();self.assertEqual(model.card.call_count,2)

if __name__=='__main__':unittest.main()
