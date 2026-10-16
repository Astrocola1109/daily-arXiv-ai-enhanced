import tempfile,unittest,fcntl
from pathlib import Path
from datetime import datetime
from unittest.mock import patch,Mock
from digest.common import BJ,write_json,read_json
from digest import supervisor as s

class SupervisorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.patch=patch.object(s,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
  self.clock=datetime(2026,10,16,12,tzinfo=BJ)
 def test_only_today_and_previously_attempted_dates_no_backfill(self):
  write_json(self.root/'runtime/daily-runs/2026-10-14.json',{'stage':'failed'})
  write_json(self.root/'runtime/daily-runs/2026-10-13.json',{'stage':'complete','mail':'quiet'})
  self.assertEqual(s.targets(self.clock,{}),['2026-10-15','2026-10-14'])
  self.assertEqual(s.targets(self.clock.replace(hour=6),{}),['2026-10-14'])
 def test_sent_uncertain_and_card_exhaustion_are_not_retried(self):
  for state in ('sent','sending'):
   write_json(self.root/'runtime/mail-ledger.json',{'2026-10-15':{'state':state}})
   self.assertFalse(s.eligible('2026-10-15',{},self.clock))
  write_json(self.root/'runtime/mail-ledger.json',{})
  write_json(self.root/'runtime/daily-runs/2026-10-15.json',{'stage':'needs_attention'})
  self.assertFalse(s.eligible('2026-10-15',{},self.clock))
 def test_retry_budget_and_cooldown_survive_restarts(self):
  s.save_record('2026-10-15',{'attempts':2,'next_attempt_at':self.clock.timestamp()+600})
  r=read_json(self.root/'runtime/supervisor-records.json')['2026-10-15']
  self.assertFalse(s.eligible('2026-10-15',r,self.clock))
  self.assertTrue(s.eligible('2026-10-15',r,self.clock.replace(hour=13)))
  r['attempts']=3;self.assertFalse(s.eligible('2026-10-15',r,self.clock.replace(hour=13)))
 def test_abrupt_exit_changes_stale_preparing_to_failed(self):
  write_json(self.root/'runtime/daily-runs/2026-10-15.json',{'stage':'preparing'})
  proc=Mock();proc.pid=123;proc.poll.return_value=-15;proc.returncode=-15
  with patch.object(s.subprocess,'Popen',return_value=proc),patch.object(s,'now',return_value=self.clock):
   record=s.run_day('2026-10-15',{})
  self.assertEqual(record['phase'],'retry_wait');self.assertTrue(record['previous_run_interrupted'])
  self.assertEqual(read_json(s.state_path('2026-10-15'))['exit_code'],-15)
 def test_live_lock_is_not_treated_as_stale(self):
  p=self.root/'lock';p.touch()
  with p.open() as f:
   fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);self.assertTrue(s.locked(p))
  self.assertFalse(s.locked(p))
 def test_alert_failure_is_not_repeated(self):
  import os
  record={}
  with patch.dict(os.environ,{'SMTP_FROM':'a@example.com','SMTP_HOST':'example.com','SMTP_USER':'a','SMTP_PASSWORD':'fixture'}),patch.object(s.smtplib,'SMTP_SSL',side_effect=OSError('offline')) as smtp:
   s.alert('2026-10-15',record,{'email_to':'b@example.com'})
   s.alert('2026-10-15',record,{'email_to':'b@example.com'})
   smtp.assert_called_once()
  self.assertIn('alert_attempted',read_json(self.root/'runtime/supervisor-records.json')['2026-10-15'])
 def test_bounded_recovery_waits_in_process_until_due(self):
  clock=[self.clock]
  s.save_record('2026-10-15',{'attempts':2,'phase':'retry_wait','next_attempt_at':self.clock.timestamp()+60})
  def sleep(seconds):
   from datetime import timedelta
   clock[0]+=timedelta(seconds=seconds)
  def complete(day,record):
   self.assertGreaterEqual(clock[0].timestamp(),self.clock.timestamp()+60)
   write_json(s.state_path(day),{'stage':'complete','mail':'sent'})
   record={**record,'phase':'complete','attempts':3};s.save_record(day,record);return record
  with patch.object(s,'now',side_effect=lambda:clock[0]),patch.object(s.time,'sleep',side_effect=sleep) as wait,patch.object(s,'run_day',side_effect=complete) as run,patch.object(s,'locked',return_value=False):
   s.supervise({})
  self.assertEqual(wait.call_count,2);run.assert_called_once()
  self.assertEqual(read_json(self.root/'runtime/supervisor-status.json')['stage'],'idle')
 def test_recovery_wait_does_not_extend_exhausted_budget(self):
  self.assertIsNone(s.retry_due({'2026-10-15':{'attempts':3,'phase':'retry_wait','next_attempt_at':0}}))
 def test_supervisor_releases_awake_assertion_on_failure(self):
  awake=Mock()
  with patch.object(s,'locked',return_value=False),patch.object(s,'load_config',return_value={}),patch.object(s.subprocess,'Popen',return_value=awake),patch.object(s,'supervise',side_effect=RuntimeError('fixture')):
   with self.assertRaisesRegex(RuntimeError,'fixture'):s.main()
  awake.terminate.assert_called_once();awake.wait.assert_called_once()

class TimeoutEvidenceTests(unittest.TestCase):
 def test_timeout_retains_partial_diagnostics_without_fake_usage(self):
  from digest.codex import Codex
  import subprocess,os
  with tempfile.TemporaryDirectory() as directory, patch('digest.codex.ROOT',Path(directory)), patch.dict(os.environ,{'CODEX_BIN':'/fixture/codex'}):
   model=Codex({'codex_timeout_seconds':1})
   login=Mock(returncode=0,stdout='ChatGPT',stderr='')
   timeout=subprocess.TimeoutExpired('fixture',1,output=b'partial output',stderr=b'connection lost')
   with patch('digest.codex.subprocess.run',side_effect=[login,timeout]):
    with self.assertRaisesRegex(RuntimeError,'timed out'):model.run('fixture',{}, {})
   self.assertEqual(len(list(model.root.glob('*.failure.json'))),1)
   self.assertEqual(list(model.root.glob('*.usage.json')),[])
   self.assertIn('connection lost',next(model.root.glob('*.error.log')).read_text())
