"""Finish the authorized initial test and backfill, with one local coordinator."""
import fcntl, os, subprocess, sys
from collections import Counter
from datetime import datetime
from .common import ROOT, BJ, read_json, write_json

TEST_DAY='2026-10-07'
SMOKE_KEYS={'a554a838ccd826731640','c9d5963a8ebbbdef6407'}
STATUS=ROOT/'runtime'/'initial-status.json'

def status(stage, **fields):
    value=read_json(STATUS,{})
    value.update(stage=stage,updated_at=datetime.now(BJ).isoformat(),**fields)
    write_json(STATUS,value)
    print('Initial setup:',stage,flush=True)

def digest(day):
    return read_json(ROOT/'runtime'/'digests'/(day+'.json'))

def incomplete(value):
    return [p['version_id'] for p in value['papers'] if p.get('analysis_status')=='needs_retry']

def run(*args):
    result=subprocess.run([sys.executable,'-m','digest',*args],cwd=ROOT)
    if result.returncode:raise RuntimeError('Digest command failed: '+' '.join(args))

def test_report(value, observed_timeouts):
    measurements=[]
    for path in (ROOT/'runtime'/'model').glob('*.usage.json'):
        if path.name.removesuffix('.usage.json') not in SMOKE_KEYS:
            measurements.append(read_json(path))
    tokens=Counter()
    for call in measurements:
        for usage in call.get('usage',[]):
            for key,number in usage.items():
                if isinstance(number,(int,float)):tokens[key]+=number
    report={
        'announcement_day_beijing':TEST_DAY,
        'generated_at':datetime.now(BJ).isoformat(),
        'papers_in_digest':len(value['papers']),
        'relevance':dict(Counter(p['relevance'] for p in value['papers'])),
        'events':dict(Counter(p['event'] for p in value['papers'])),
        'analysis_status':dict(Counter(p.get('analysis_status') for p in value['papers'])),
        'pending_fulltext':incomplete(value),
        'model':'gpt-5.6-sol','reasoning_effort':'high',
        'recorded_model_steps_excluding_two_smoke_calls':len(measurements),
        'reported_tokens':dict(tokens),
        'sum_recorded_model_step_elapsed_seconds':round(sum(c['elapsed_seconds'] for c in measurements),2),
        'observed_timeout_papers':observed_timeouts,
        'coverage_warnings':value.get('warnings',[]),
        'measurement_limits':[
            '累计模型步骤耗时含等待，不是纯推理时间，也不是含抓取和系统休眠的整日墙钟耗时。',
            '先前超时调用没有完整用量记录；已记录的token是下限，不代表账户全部消耗。',
            'cached_input_tokens属于input_tokens中的缓存部分；各字段不能简单相加。',
            '本流程使用ChatGPT订阅登录；没有启用付费API回退。订阅周额度百分比无法由token直接换算。',
            '卡片完成表示分析流程完成，不表示数学陈述经过独立人工核查。'
        ]}
    write_json(ROOT/'runtime'/'full-day-test-report.json',report)
    write_json(ROOT.parents[1]/'arxiv-full-day-test.json',report)

def main():
    runtime=ROOT/'runtime';runtime.mkdir(exist_ok=True)
    with (runtime/'bootstrap.lock').open('a+') as coordinator:
        try:fcntl.flock(coordinator,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Initial coordinator is already running')
        if read_json(STATUS,{}).get('stage')=='complete':
            print('Initial setup already complete.');return
        # This assertion exists only for this coordinator's lifetime.
        awake=subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            status('waiting_for_existing_pipeline')
            with (runtime/'pipeline.lock').open('a+') as pipeline:
                fcntl.flock(pipeline,fcntl.LOCK_EX)
                fcntl.flock(pipeline,fcntl.LOCK_UN)
            prior=digest(TEST_DAY)
            library=read_json(runtime/'library.json',{})
            timeouts=[p['version_id'] for p in library.get('papers',{}).values() if p.get('analysis_status')=='needs_retry']
            if prior is None or incomplete(prior):
                status('finishing_test_and_retrying_incomplete_cards')
                run('prepare','--date',TEST_DAY)
            result=digest(TEST_DAY)
            status('publishing_test')
            run('publish','--date',TEST_DAY)
            # Freeze the test measurement before backfill adds more calls.
            if not (runtime/'full-day-test-report.json').exists():test_report(result,timeouts)
            library=read_json(runtime/'library.json',{})
            if not library.get('bootstrap_complete'):
                status('preparing_seven_day_backfill')
                run('prepare')
            library=read_json(runtime/'library.json',{})
            days=sorted(library.get('digests',{}))
            for day in days:
                value=digest(day)
                if incomplete(value):
                    status('retrying_backfill_cards',day=day)
                    run('prepare','--date',day)
                status('publishing_backfill',day=day)
                run('publish','--date',day)
            pending={day:incomplete(digest(day)) for day in days if incomplete(digest(day))}
            if pending:
                status('needs_attention',pending_fulltext=pending,published_days=days)
                return
            mail=read_json(runtime/'smtp-integration-test.json',{})
            if days and mail.get('recipient_confirmed_received') and datetime.now(BJ).hour>=9:
                status('sending_latest_backfill_digest')
                run('send','--date',days[-1])
            status('complete',published_days=days,pending_fulltext={})
        except Exception as exc:
            status('failed',error=str(exc))
            raise
        finally:
            awake.terminate();awake.wait()

if __name__=='__main__':main()
