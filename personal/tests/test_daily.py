import tempfile, unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from digest.common import BJ, write_json, read_json
from digest.daily import process_day

class DailyTests(unittest.TestCase):
    def exercise(self, start, already_sent=False, pending=False, quiet=False):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name);day='2026-10-09';clock=[start];commands=[];sleeps=[]
        if already_sent:write_json(root/'runtime/mail-ledger.json',{day:{'state':'sent'}})
        def run(command, selected_day):
            self.assertEqual(selected_day,day);commands.append(command)
            if command=='prepare':
                write_json(root/'runtime/digests'/(day+'.json'),{'papers':[{'version_id':'x','analysis_status':'needs_retry' if pending else 'complete'}]})
            if command=='send' and not quiet:
                self.assertGreaterEqual(clock[0].hour,9)
                write_json(root/'runtime/mail-ledger.json',{day:{'state':'sent'}})
        def sleep(seconds):
            self.assertLessEqual(seconds,30);sleeps.append(seconds);clock[0]+=timedelta(seconds=seconds)
        with patch('digest.daily.ROOT',root),patch('digest.daily.run',side_effect=run),patch('digest.daily.now',side_effect=lambda:clock[0]),patch('digest.daily.time.sleep',side_effect=sleep):
            process_day(day)
        return commands,sleeps,read_json(root/'runtime/daily-status.json')

    def test_waits_until_nine_and_only_processes_requested_day(self):
        commands,sleeps,result=self.exercise(datetime(2026,10,10,8,59,30,tzinfo=BJ))
        self.assertEqual(commands,['prepare','publish','send']);self.assertEqual(sleeps,[30])
        self.assertEqual(result['mail'],'sent')

    def test_late_run_sends_immediately(self):
        commands,sleeps,result=self.exercise(datetime(2026,10,10,15,tzinfo=BJ))
        self.assertEqual(commands,['prepare','publish','send']);self.assertEqual(sleeps,[])

    def test_sent_day_has_no_model_or_mail_repeat(self):
        commands,_,result=self.exercise(datetime(2026,10,10,15,tzinfo=BJ),already_sent=True)
        self.assertEqual(commands,[]);self.assertEqual(result['stage'],'already_sent')

    def test_incomplete_cards_retry_once_without_sending(self):
        commands,_,result=self.exercise(datetime(2026,10,10,15,tzinfo=BJ),pending=True)
        self.assertEqual(commands,['prepare','prepare','publish']);self.assertEqual(result['stage'],'needs_attention')

    def test_no_notification_is_recorded_as_quiet(self):
        _,_,result=self.exercise(datetime(2026,10,10,15,tzinfo=BJ),quiet=True)
        self.assertEqual(result['mail'],'quiet')

if __name__=='__main__':unittest.main()
