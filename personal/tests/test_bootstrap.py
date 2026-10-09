import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from digest.common import read_json, write_json
from digest.bootstrap import test_report, SMOKE_KEYS

class PriorityDaysTests(unittest.TestCase):
    def test_only_requested_days_prepared_and_sent_without_backfill(self):
        from datetime import datetime
        from digest.bootstrap import finish_priority_days
        from digest.common import BJ
        from digest.codex import SCREENING_POLICY
        days=['2026-10-07','2026-10-08'];values={days[0]:{'papers':[],'screening_policy':SCREENING_POLICY}}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'runtime').mkdir()
            write_json(root/'runtime'/'full-day-test-report.json',{})
            write_json(root/'runtime'/'smtp-integration-test.json',{'recipient_confirmed_received':True})
            def run(*args):
                if args[0]=='prepare':values[args[2]]={'papers':[]}
            with patch('digest.bootstrap.ROOT',root),patch('digest.bootstrap.digest',side_effect=values.get),patch('digest.bootstrap.run',side_effect=run) as runner,patch('digest.bootstrap.status') as status,patch('digest.bootstrap.datetime') as clock:
                clock.now.return_value=datetime(2026,10,9,12,tzinfo=BJ)
                finish_priority_days(days)
            self.assertEqual([c.args for c in runner.call_args_list],[('publish','--date',days[0]),('send','--date',days[0]),('prepare','--date',days[1]),('publish','--date',days[1]),('send','--date',days[1])])
            self.assertEqual(status.call_args.args,('complete',))
            self.assertTrue(status.call_args.kwargs['backfill_paused'])

class MeasurementTests(unittest.TestCase):
    def test_report_excludes_smoke_calls_and_keeps_cached_tokens_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'outputs'/'repo'/'personal'
            model=root/'runtime'/'model';model.mkdir(parents=True)
            for key in SMOKE_KEYS:
                write_json(model/(key+'.usage.json'),{'elapsed_seconds':999,'usage':[{'input_tokens':999}],'exit_code':0})
            write_json(model/'actual.usage.json',{'elapsed_seconds':10,'usage':[{'input_tokens':100,'cached_input_tokens':20,'output_tokens':10}],'exit_code':0})
            value={'papers':[{'event':'new','relevance':'direct','analysis_status':'complete'}],'warnings':[]}
            with patch('digest.bootstrap.ROOT',root):test_report(value,['2610.00001v1'])
            result=read_json(root.parents[1]/'arxiv-full-day-test.json')
            self.assertEqual(result['recorded_model_steps_excluding_two_smoke_calls'],1)
            self.assertEqual(result['reported_tokens']['input_tokens'],100)
            self.assertEqual(result['reported_tokens']['cached_input_tokens'],20)
            self.assertEqual(result['sum_recorded_model_step_elapsed_seconds'],10)
            self.assertEqual(result['observed_timeout_papers'],['2610.00001v1'])

if __name__=='__main__':unittest.main()
