import html, os, smtplib, ssl, uuid
from datetime import datetime
from email.message import EmailMessage
from .common import ROOT, BJ, read_json, write_json

def notifications(papers, states):
    return [p for p in papers if p.get('relevance') in {'direct','extension'}
            and not states.get(p['id'],{}).get('disliked',False)
            and (p.get('event')!='revision' or p.get('high_related') or states.get(p['id'],{}).get('favorite',False))]

def render(digest, site_url, states):
    papers=notifications(digest['papers'],states)
    if not papers:return None
    subject='研究日报 · '+digest['day']+' · '+str(len(papers))+' 篇'
    body=['<h1>研究日报 · '+html.escape(digest['day'])+'</h1>']
    lines=[subject]
    for label,predicate in [('重点论文',lambda p:p['event']!='revision' and p['relevance']=='direct'),
                            ('拓展论文',lambda p:p['event']!='revision' and p['relevance']=='extension'),
                            ('修订版',lambda p:p['event']=='revision')]:
        group=[p for p in papers if predicate(p)]
        if not group:continue
        body.append('<h2>'+label+'</h2>')
        for p in group:
            url=site_url+'#paper='+p['version_id']
            body.append('<p><strong>'+html.escape(p['title'])+'</strong><br>'+html.escape(', '.join(p['authors']))+
                        '<br>'+html.escape(p.get('reason',''))+'<br><a href="'+html.escape(url,quote=True)+'">登录阅读详细卡片</a></p>')
            lines.append(p['title']+'\n'+p.get('reason','')+'\n'+url)
    body.append('<p>详细卡片与个人阅读状态需要登录查看。</p>')
    return subject,'\n\n'.join(lines),'\n'.join(body)

def deliver(digest, config, states, allow_early=False):
    rendered=render(digest,config['site_url'],states)
    if not rendered:return 'quiet'
    if not allow_early and datetime.now(BJ).hour<9:raise RuntimeError('日报已准备好；北京时间09:00以后再发送。')
    ledger_path=ROOT/'runtime'/'mail-ledger.json';ledger=read_json(ledger_path,{})
    day=digest['day']
    if day in ledger:
        if ledger[day]['state']=='sent':return 'already_sent'
        raise RuntimeError('Previous SMTP outcome is uncertain. Check mailbox before clearing mail-ledger entry; no automatic duplicate.')
    for k in ('SMTP_HOST','SMTP_USER','SMTP_PASSWORD','SMTP_FROM'):
        if not os.environ.get(k):raise RuntimeError(k+' is not configured; email was not sent')
    msg=EmailMessage();msg['Subject']=rendered[0];msg['From']=os.environ['SMTP_FROM'];msg['To']=config['email_to']
    msg['Message-ID']='<'+str(uuid.uuid4())+'@personal-arxiv-digest>'
    msg.set_content(rendered[1]);msg.add_alternative(rendered[2],subtype='html')
    ledger[day]={'state':'sending','message_id':msg['Message-ID']};write_json(ledger_path,ledger)
    with smtplib.SMTP_SSL(os.environ['SMTP_HOST'],int(os.environ.get('SMTP_PORT','465')),
                          context=ssl.create_default_context(),timeout=45) as server:
        server.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
        refused=server.send_message(msg)
        if refused:raise RuntimeError('SMTP recipient rejected; inspect local mail ledger')
    ledger[day]['state']='sent';write_json(ledger_path,ledger)
    return 'sent'
