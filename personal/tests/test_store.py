import json, unittest, urllib.error
from unittest.mock import patch, MagicMock
from digest.store import Store

class DatabaseEncodingTests(unittest.TestCase):
    def test_upsert_recovers_from_handshake_timeout(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b'[]'
        env={'SUPABASE_URL':'https://fixture.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'fixture'}
        with patch.dict('os.environ',env),patch('digest.store.time.sleep') as sleep,patch('digest.store.urllib.request.urlopen',side_effect=[urllib.error.URLError(TimeoutError('handshake timed out')),response]) as request:
            self.assertEqual(Store().request('digests','?on_conflict=user_id,day',{'day':'2026-10-10'},'POST'),[])
        self.assertEqual(request.call_count,2);sleep.assert_called_once_with(2)

    def test_timeout_retries_are_bounded(self):
        env={'SUPABASE_URL':'https://fixture.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'fixture'}
        with patch.dict('os.environ',env),patch('digest.store.time.sleep'),patch('digest.store.urllib.request.urlopen',side_effect=TimeoutError('timeout')) as request:
            with self.assertRaises(TimeoutError):Store().request('digests')
        self.assertEqual(request.call_count,3)

    def test_validation_errors_and_plain_posts_are_not_retried(self):
        env={'SUPABASE_URL':'https://fixture.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'fixture'}
        for query,error in [('?on_conflict=user_id',urllib.error.HTTPError('https://fixture.supabase.co',400,'bad data',{},None)),('',TimeoutError('timeout'))]:
            with patch.dict('os.environ',env),patch('digest.store.time.sleep') as sleep,patch('digest.store.urllib.request.urlopen',side_effect=error) as request:
                with self.assertRaises((urllib.error.HTTPError,TimeoutError)):Store().request('digests',query,{},'POST')
            self.assertEqual(request.call_count,1);sleep.assert_not_called()

    def test_pdf_nul_is_replaced_in_request_without_mutating_source(self):
        payload={'payload':{'references_text':'A\x00B','card':['中文 α'], 'pages':3}}
        response=MagicMock();response.__enter__.return_value.read.return_value=b'[]'
        env={'SUPABASE_URL':'https://fixture.supabase.co','SUPABASE_SERVICE_ROLE_KEY':'fixture'}
        with patch.dict('os.environ',env),patch('digest.store.urllib.request.urlopen',return_value=response) as request:
            Store().request('papers',body=payload,method='POST')
        sent=json.loads(request.call_args.args[0].data)
        self.assertEqual(sent['payload']['references_text'],'A\ufffdB')
        self.assertEqual(sent['payload']['card'],['中文 α'])
        self.assertEqual(payload['payload']['references_text'],'A\x00B')

if __name__=='__main__':unittest.main()
