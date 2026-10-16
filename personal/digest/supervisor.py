"""launchd worker: bounded, persisted recovery; no seven-day bootstrap."""
import fcntl, os, smtplib, ssl, subprocess, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from email.message import EmailMessage
from .common import ROOT, BJ, read_json, write_json, load_config

MAX_ATTEMPTS=3
COOLDOWN_SECONDS=600
LEGACY_LOCK=Path('/Users/astrocola/Desktop/ArXiv日报/pending-recovery.lock')

def now(): return datetime.now(BJ)
def locked(path):
    if not path.exists(): return False
    with path.open() as f:
        try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return True
        fcntl.flock(f,fcntl.LOCK_UN)
    return False

def state_path(day):return ROOT/'runtime/daily-runs'/(day+'.json')
def finished(day):
    return (read_json(ROOT/'runtime/mail-ledger.json',{}).get(day,{}).get('state')=='sent'
            or read_json(state_path(day),{}).get('stage') in ('complete','already_sent'))

def targets(clock, records):
    # Only today's due date plus days actually attempted before; never infer a backfill.
    days=set(records)
    for path in (ROOT/'runtime/daily-runs').glob('*.json'):
        if not finished(path.stem):days.add(path.stem)
    if (clock.hour,clock.minute)>=(7,0):days.add(str(clock.date()-timedelta(days=1)))
    return sorted((d for d in days if d<str(clock.date())),reverse=True)

def eligible(day, record, clock):
    if finished(day) or record.get('phase')=='needs_attention':return False
    mail=read_json(ROOT/'runtime/mail-ledger.json',{}).get(day,{})
    if mail and mail.get('state')!='sent':return False
    if read_json(state_path(day),{}).get('stage')=='needs_attention':return False
    return record.get('attempts',0)<MAX_ATTEMPTS and clock.timestamp()>=record.get('next_attempt_at',0)

def alert(day, record, config):
    if record.get('alert_attempted'):return
    record['alert_attempted']=now().isoformat()  # persisted BEFORE SMTP; never blindly resend
    save_record(day,record)
    msg=EmailMessage();msg['Subject']='【需处理】Aster 日报 '+day+' 未完成'
    msg['From']=os.environ['SMTP_FROM'];msg['To']=config['email_to']
    msg.set_content('论文日期 '+day+' 的日报尚未完成。自动恢复已停止，避免重复消耗或重复发信。\n'
                    '请在 Codex 日报对话查看故障通知。已完成的缓存保留，七天回补未启动。')
    try:
        with smtplib.SMTP_SSL(os.environ['SMTP_HOST'],int(os.environ.get('SMTP_PORT','465')),context=ssl.create_default_context(),timeout=45) as smtp:
            smtp.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD']);refused=smtp.send_message(msg)
            if refused:raise RuntimeError('Alert recipient rejected')
        record['alert_smtp_accepted']=True
    except Exception as exc:record['alert_error_type']=type(exc).__name__
    save_record(day,record)

def save_record(day,record):
    path=ROOT/'runtime/supervisor-records.json';records=read_json(path,{})
    records[day]=record;write_json(path,records)

def run_day(day,record):
    record={**record,'attempts':record.get('attempts',0)+1,'phase':'running','started_at':now().isoformat()}
    for key in ('pid','exit_code','ended_at','next_attempt_at'):record.pop(key,None)
    save_record(day,record)
    prior=read_json(state_path(day),{})
    if prior.get('stage') in ('preparing','publishing','sending','retrying_cards','waiting_for_mail_time'):
        record['previous_run_interrupted']=True;save_record(day,record)
    with (ROOT/'runtime/daily.log').open('a') as log:
        proc=subprocess.Popen([sys.executable,'-u','-m','digest.daily','--date',day],cwd=ROOT,
                              stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        record['pid']=proc.pid;save_record(day,record)
        while proc.poll() is None:
            write_json(ROOT/'runtime/supervisor-status.json',{'stage':'running','day':day,'pid':proc.pid,'checked_at':now().isoformat()})
            time.sleep(30)
    record['exit_code']=proc.returncode;record['ended_at']=now().isoformat()
    current=read_json(state_path(day),{})
    if finished(day):record['phase']='complete'
    elif (current.get('stage')=='needs_attention' or
          read_json(ROOT/'runtime/mail-ledger.json',{}).get(day,{}).get('state')=='sending' or
          record['attempts']>=MAX_ATTEMPTS):record['phase']='needs_attention'
    else:
        record['phase']='retry_wait';record['next_attempt_at']=now().timestamp()+COOLDOWN_SECONDS
    if current.get('stage') not in ('complete','already_sent','failed','needs_attention'):
        write_json(state_path(day),{'day':day,'stage':'failed','updated_at':now().isoformat(),
                                  'error':'Child exited without terminal status','exit_code':proc.returncode})
    save_record(day,record);return record

def retry_due(records):
    times=[r['next_attempt_at'] for day,r in records.items()
           if r.get('phase')=='retry_wait' and r.get('attempts',0)<MAX_ATTEMPTS
           and not finished(day)]
    return min(times) if times else None

def supervise(config):
    runtime=ROOT/'runtime'
    while True:
        records=read_json(runtime/'supervisor-records.json',{})
        for day in targets(now(),records):
            record=records.get(day,{})
            if finished(day):continue
            if locked(LEGACY_LOCK) or any(locked(runtime/(n+'.lock')) for n in ('daily','pipeline','bootstrap')):return
            if eligible(day,record,now()):record=run_day(day,record)
            else:
                if record.get('attempts',0)>=MAX_ATTEMPTS or read_json(state_path(day),{}).get('stage')=='needs_attention' or read_json(runtime/'mail-ledger.json',{}).get(day,{}).get('state')=='sending':
                    record['phase']='needs_attention';save_record(day,record)
            if record.get('phase')=='needs_attention':alert(day,record,config)
        due=retry_due(read_json(runtime/'supervisor-records.json',{}))
        if due is None:break
        # Keep this bounded recovery session awake through its cooldown. Without
        # this, an unattended Mac may fall asleep before the next launchd tick.
        write_json(runtime/'supervisor-status.json',{'stage':'waiting_for_retry','retry_at':due,'checked_at':now().isoformat()})
        time.sleep(min(30,max(1,due-now().timestamp())))
    write_json(runtime/'supervisor-status.json',{'stage':'idle','checked_at':now().isoformat()})

def main():
    os.umask(0o077);runtime=ROOT/'runtime';runtime.mkdir(exist_ok=True)
    with (runtime/'supervisor.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        if locked(LEGACY_LOCK) or any(locked(runtime/(n+'.lock')) for n in ('daily','pipeline','bootstrap')):
            write_json(runtime/'supervisor-status.json',{'stage':'external_task_running','checked_at':now().isoformat()});return
        config=load_config()
        awake=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:supervise(config)
        finally:awake.terminate();awake.wait()

if __name__=='__main__':main()
