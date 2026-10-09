import json, unittest
from unittest.mock import patch, MagicMock
from digest.store import Store

class DatabaseEncodingTests(unittest.TestCase):
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
