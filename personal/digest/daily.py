"""One local daily run: yesterday's papers, publish, then mail at/after 09:00 BJ."""
import argparse
import fcntl
import os
import subprocess
import sys
import time
from datetime import date, datetime, time as daytime, timedelta
from .common import ROOT, BJ, read_json, write_json, yesterday


def now():
    return datetime.now(BJ)


def status(day, stage, **fields):
    value={'day':day,'stage':stage,'updated_at':now().isoformat(),**fields}
    write_json(ROOT/'runtime'/'daily-status.json',value)
    write_json(ROOT/'runtime'/'daily-runs'/(day+'.json'),value)
    print('Daily digest:',day,stage,flush=True)


def run(command, day):
    result=subprocess.run([sys.executable,'-m','digest',command,'--date',day],cwd=ROOT)
    if result.returncode:
        raise RuntimeError('Digest command failed: '+command+' --date '+day)


def process_day(day):
    # The explicit day prevents accidental activation of the initial seven-day backfill.
    if read_json(ROOT/'runtime'/'mail-ledger.json',{}).get(day,{}).get('state')=='sent':
        status(day,'already_sent');return
    status(day,'preparing')
    run('prepare',day)
    path=ROOT/'runtime'/'digests'/(day+'.json')
    value=read_json(path)
    pending=[p['version_id'] for p in value['papers'] if p.get('analysis_status')=='needs_retry']
    if pending:
        status(day,'retrying_cards',pending_fulltext=pending)
        run('prepare',day)
        value=read_json(path)
        pending=[p['version_id'] for p in value['papers'] if p.get('analysis_status')=='needs_retry']
    status(day,'publishing')
    run('publish',day)
    if pending:
        status(day,'needs_attention',pending_fulltext=pending)
        return
    due=datetime.combine(date.fromisoformat(day)+timedelta(days=1),daytime(9),tzinfo=BJ)
    if now()<due:
        status(day,'waiting_for_mail_time',send_not_before=due.isoformat())
        while now()<due:
            time.sleep(min(30,max(0,(due-now()).total_seconds())))
    status(day,'sending')
    run('send',day)
    sent=read_json(ROOT/'runtime'/'mail-ledger.json',{}).get(day,{}).get('state')=='sent'
    status(day,'complete',mail='sent' if sent else 'quiet',papers=len(value['papers']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date',type=date.fromisoformat)
    args=parser.parse_args();day=str(args.date or yesterday())
    runtime=ROOT/'runtime';runtime.mkdir(exist_ok=True)
    with (runtime/'daily.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another daily coordinator is running; no duplicate started.');return
        awake=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            # Wait for any explicitly started/manual work, without a competing pipeline.
            for name in ('bootstrap','pipeline'):
                with (runtime/(name+'.lock')).open('a+') as existing:
                    fcntl.flock(existing,fcntl.LOCK_EX)
                    fcntl.flock(existing,fcntl.LOCK_UN)
            process_day(day)
        except Exception as exc:
            status(day,'failed',error=str(exc))
            raise
        finally:
            awake.terminate();awake.wait()


if __name__=='__main__':main()
