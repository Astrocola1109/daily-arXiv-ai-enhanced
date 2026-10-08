import argparse, fcntl, getpass, json, os, sys
from datetime import date
from .common import ROOT, load_config, load_env, write_json, read_json, yesterday
from .store import Store

def setup():
    path=ROOT/'.env'
    if path.exists():raise RuntimeError('.env already exists; edit it locally instead of overwriting credentials')
    print('输入只保存到本机 personal/.env，不写入 GitHub。秘密字段不会回显。')
    values={}
    for key in ['SUPABASE_URL','SUPABASE_ANON_KEY','SUPABASE_SERVICE_ROLE_KEY','OWNER_USER_ID',
                'SMTP_HOST','SMTP_PORT','SMTP_USER','SMTP_PASSWORD','SMTP_FROM']:
        values[key]=getpass.getpass(key+': ') if 'KEY' in key or 'PASSWORD' in key else input(key+': ').strip()
        if '\n' in values[key]:raise RuntimeError('Invalid newline')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        f.write('\n'.join(k+'='+v for k,v in values.items())+'\n')
    print('本地凭据已保存。请运行 doctor 检查，数据库用户密码由你在服务端设置。')

def main():
    parser=argparse.ArgumentParser(description='Private arXiv digest: local GPT-5.6 Sol / High runner')
    parser.add_argument('command',choices=['setup','doctor','collect','prepare','publish','send','run','propose-interests','accept-interests','sync-profile'])
    parser.add_argument('--date',type=date.fromisoformat)
    parser.add_argument('--allow-early',action='store_true',help='Explicit manual email test before 09:00')
    args=parser.parse_args()
    if args.command=='setup':setup();return
    config=load_config();store=Store()
    if args.command=='doctor':
        import shutil,subprocess
        binary=os.environ.get('CODEX_BIN') or shutil.which('codex')
        status={'codex_found':bool(binary),'database_configured':store.remote_configured,
                'smtp_configured':all(os.environ.get(k) for k in ['SMTP_HOST','SMTP_USER','SMTP_PASSWORD','SMTP_FROM']),
                'model':config['model'],'reasoning_effort':config['reasoning_effort']}
        if binary:
            result=subprocess.run([binary,'login','status'],capture_output=True,text=True)
            status['chatgpt_login']='ChatGPT' in result.stdout+result.stderr
        print(json.dumps(status,ensure_ascii=False,indent=2));return
    if args.command=='sync-profile':store.push_profile({'research_lines':config['research_lines']});print('研究方向已同步');return
    if args.command=='propose-interests':
        from .interests import propose
        result=propose(config);print('已生成待确认建议：',len(result['suggestions']));return
    if args.command=='accept-interests':
        from .interests import accept
        accept(config);print('已明确接受本地建议并更新方向');return
    runtime=ROOT/'runtime';runtime.mkdir(exist_ok=True,mode=0o700)
    with (runtime/'pipeline.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another digest job is running')
        if args.command=='collect':
            from .arxiv import Client,collect
            day=args.date or yesterday();papers,revisions,warnings=collect(Client(),config['categories'],[day])
            write_json(runtime/'collected'/f'{day}.json',{'papers':papers,'revisions':revisions,'warnings':warnings})
            print(json.dumps({'papers':len(papers),'revisions':len(revisions),'coverage_warnings':len(warnings)}));return
        if args.command in {'prepare','run'}:
            from .pipeline import prepare
            digests,usage=prepare(config,[args.date] if args.date else None)
            write_json(runtime/'last-usage.json',usage)
            if args.command=='prepare':print('分析完成，结果保存在本机；尚未发送邮件。');return
        else:
            day=str(args.date or yesterday());digest=read_json(runtime/'digests'/(day+'.json'))
            if digest is None:raise RuntimeError('No prepared digest for '+day)
            digests=[digest]
        store=Store();store.pull()
        for digest in digests:
            store.publish(digest)
            store.data['digests'].setdefault(digest['day'],{})['published']=True;store.save()
        if args.command in {'send','run'}:
            from .emailing import deliver
            # Backfill is available on the site; only the latest day's digest is emailed.
            print(deliver(digests[-1],config,store.data['states'],args.allow_early))
        else:print('已上传私有日报。')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('ERROR: '+str(exc),file=sys.stderr);sys.exit(1)
