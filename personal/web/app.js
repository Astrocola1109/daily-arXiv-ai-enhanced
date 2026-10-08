import {createClient} from '@supabase/supabase-js';
import renderMathInElement from 'katex/contrib/auto-render';
import 'katex/dist/katex.css';
import './style.css';
import {escapeHtml as e, safeArxivUrl, filterPapers} from './utils.mjs';

const root=document.querySelector('#app');
const demo=new URLSearchParams(location.search).has('demo') && ['localhost','127.0.0.1'].includes(location.hostname);
let client, user, papers=[], states={}, digests=[], selectedDay='', active='direct', query='', profile=null, busy=false;
const labels={direct:'重点论文',extension:'拓展论文',revision:'修订版',other:'其余论文',favorite:'我的收藏',read:'已读',disliked:'不感兴趣',all:'全部论文'};
const mark='<span class="mark" aria-hidden="true">✳</span><span class="wordmark">aster<span>论文日报</span></span>';

function math(){ renderMathInElement(root,{delimiters:[{left:'$$',right:'$$',display:true},{left:'\\[',right:'\\]',display:true},{left:'$',right:'$',display:false},{left:'\\(',right:'\\)',display:false}],throwOnError:false,trust:false,strict:'ignore'}); }
function message(text, error=false){const box=document.querySelector('#status');if(box){box.textContent=text;box.classList.toggle('error',error);}}
function login(reason=''){
  papers=[];states={};profile=null;user=null;
  root.innerHTML=`<main class="login"><div class="brand">${mark}</div><div class="login-grid"><section><p class="eyebrow">YOUR PRIVATE RESEARCH READING ROOM</p><h1>留给<br>值得读的论文。</h1><p class="intro">每日文献，与你的研究相遇。<br>从重要结果，到下一步值得追问的问题。</p><div class="login-note"><span>01 / 重点阅读</span><span>02 / 方法拓展</span><span>03 / 持续跟进</span></div></section><section class="login-card"><p class="eyebrow">个人研究空间</p><h2>欢迎回来</h2><p>登录后查看日报、收藏与阅读记录。</p><form id="login-form"><label>邮箱<input name="email" type="email" autocomplete="username" required placeholder="你的登录邮箱"></label><label>密码<input name="password" type="password" autocomplete="current-password" required placeholder="网站登录密码"></label><button class="primary" ${client?'':'disabled'}>进入阅读室 <span>↗</span></button></form><p id="status" role="status" class="small">${e(reason || (!client?'网站正在配置私有数据服务，暂未开放登录。':'仅已授权的个人账户可以读取数据。'))}</p></section></div><footer>ASTER · DAILY RESEARCH DIGEST <span>慢一点读，深一点想。</span></footer></main>`;
  document.querySelector('#login-form').onsubmit=async event=>{
    event.preventDefault();if(!client)return;
    const form=new FormData(event.target);const btn=event.target.querySelector('button');btn.disabled=true;
    message('正在登录…');
    const {error}=await client.auth.signInWithPassword({email:form.get('email'),password:form.get('password')});
    if(error){message('登录失败，请检查账户和网站登录密码。',true);btn.disabled=false;}
    event.target.querySelector('[name=password]').value='';
  };
}

async function fetchAll(table, build=q=>q){
  let rows=[];
  for(let start=0;;start+=500){
    const {data,error}=await build(client.from(table).select('*')).range(start,start+499);
    if(error)throw error;
    rows.push(...data);if(data.length<500)return rows;
  }
}

async function load(){
  if(!user)return;
  const {data:allowed,error}=await client.rpc('is_digest_owner');
  if(error || !allowed){await client.auth.signOut();login('这个账户没有阅读权限。');return;}
  digests=await fetchAll('digests',q=>q.order('day',{ascending:false}));
  const found=await fetchAll('research_profiles');profile=found[0]??null;
  const reading=await fetchAll('reading_states');states=Object.fromEntries(reading.map(s=>[s.paper_id,s]));
  selectedDay=digests.some(d=>d.day===selectedDay)?selectedDay:(digests[0]?.day??'');
  await loadDay();
}
async function loadDay(){
  if(demo){shell();return;}
  const crossDay=['favorite','read','disliked'].includes(active);
  let ids=crossDay?Object.entries(states).filter(([,s])=>s[active==='favorite'?'favorite':active==='read'?'is_read':'disliked']).map(([id])=>id):null;
  let rows=[];
  if(crossDay){
    for(let i=0;i<ids.length;i+=80)rows.push(...await fetchAll('papers',q=>q.in('paper_id',ids.slice(i,i+80)).order('announcement_date',{ascending:false})));
    const newest=new Map();for(const r of rows){const old=newest.get(r.paper_id);if(!old || Number(r.version_id.split('v').pop())>Number(old.version_id.split('v').pop()))newest.set(r.paper_id,r);}rows=[...newest.values()];
  }else if(selectedDay){rows=await fetchAll('papers',q=>q.eq('announcement_date',selectedDay).order('version_id'));}
  papers=rows.map(r=>r.payload);shell();
  const id=new URLSearchParams(location.hash.slice(1)).get('paper');
  if(id){let p=papers.find(p=>p.version_id===id);if(!p){const {data}=await client.from('papers').select('payload').eq('version_id',id).maybeSingle();p=data?.payload;}if(p)details(p);}
}
function stats(){return ['direct','extension','revision'].map(tab=>`<div><strong>${filterPapers(papers,states,tab).length.toString().padStart(2,'0')}</strong><span>${labels[tab]}</span></div>`).join('');}
function shell(){
  const current=digests.find(d=>d.day===selectedDay);
  root.innerHTML=`<div class="layout"><aside><a class="brand" href="#">${mark}</a><div class="private-tag">● 私人阅读室${demo?' · 本地演示':''}</div><p class="nav-heading">每日阅读</p><nav>${['direct','extension','revision','other'].map(tab=>`<button data-tab="${tab}" class="nav-item ${active===tab?'active':''}">${labels[tab]}<span>↗</span></button>`).join('')}</nav><p class="nav-heading">我的文献</p><nav>${['favorite','read','disliked'].map(tab=>`<button data-tab="${tab}" class="nav-item ${active===tab?'active':''}">${labels[tab]}</button>`).join('')}</nav><div class="aside-bottom"><button id="interests">研究兴趣与更新</button><button id="refresh">刷新同步状态</button><button id="logout">退出登录</button><p>每一次阅读，<br>都让问题更清楚一点。</p></div></aside><main class="reading"><header><span class="eyebrow">DAILY RESEARCH / 研究日报</span><span class="status-dot">${demo?'示例内容':'私人空间'}</span></header><section class="heading"><div><p class="eyebrow">${selectedDay?e(selectedDay.replaceAll('-',' / ')):'等待第一份日报'}</p><h1>今天，读什么。</h1><p>追踪研究的进展，也留意方法的交汇。</p></div><div class="counts">${stats()}</div></section><section class="toolbar"><label class="search">⌕ <input id="search" placeholder="搜索标题、作者或分类" value="${e(query)}"></label><select id="day" aria-label="选择公告日期">${digests.map(d=>`<option ${selectedDay===d.day?'selected':''}>${e(d.day)}</option>`).join('')}</select></section><div id="status" role="status" class="small"></div>${current?.payload?.warnings?.length?`<details class="coverage"><summary>本日公告覆盖说明 · ${current.payload.warnings.length} 项</summary><ul>${current.payload.warnings.map(w=>`<li>${e(w)}</li>`).join('')}</ul></details>`:''}<div class="section-title"><h2>${labels[active]}</h2><span id="count"></span></div><section id="papers"></section><footer>ASTER · RESEARCH IN PROGRESS <span>论文观点以原文为准 · 推测与读取范围见卡片</span></footer></main></div><dialog id="detail"></dialog><dialog id="profile"></dialog>`;
  document.querySelectorAll('[data-tab]').forEach(btn=>btn.onclick=async()=>{active=btn.dataset.tab;try{await loadDay();}catch{message('读取失败，请重试。',true);}});
  document.querySelector('#search').oninput=event=>{query=event.target.value;cards();};
  document.querySelector('#day').onchange=async event=>{selectedDay=event.target.value;await loadDay();};
  document.querySelector('#refresh').onclick=async()=>{if(demo)return;try{await load();message('阅读状态已同步。');}catch{message('同步失败，请检查网络。',true);}};
  document.querySelector('#logout').onclick=async()=>{if(demo){location.search='';return;}await client.auth.signOut();login();};
  document.querySelector('#interests').onclick=interests;
  cards();
}
function actions(p){const s=states[p.id]??{};return `<div class="actions">${[['favorite','☆ 收藏','★ 已收藏'],['is_read','标记已读','✓ 已读'],['disliked','不感兴趣','取消不感兴趣']].map(([flag,no,yes])=>`<button data-flag="${flag}" data-paper="${e(p.id)}" aria-pressed="${!!s[flag]}">${s[flag]?yes:no}</button>`).join('')}</div>`;}
function cards(){
  const filtered=filterPapers(papers,states,active,query);document.querySelector('#count').textContent=`${filtered.length} 篇`;
  document.querySelector('#papers').innerHTML=filtered.length?filtered.map((p,i)=>`<article class="paper"><div class="paper-meta"><span>${String(i+1).padStart(2,'0')}</span><span>${e((p.categories??[]).slice(0,3).join(' / '))}</span>${p.event==='revision'?'<b>修订版</b>':''}${p.event==='cross_uncertain'?'<b>首次公告待核实</b>':''}${p.analysis_status==='needs_retry'?'<b>深读待补全</b>':''}</div><h3><a href="${safeArxivUrl(p.version_id)}" target="_blank" rel="noopener noreferrer">${e(p.title)}</a></h3><p class="authors">${e((p.authors??[]).join(' · '))}</p>${p.relevance!=='unrelated'?`<p class="reason">${e(p.reason)}</p><div class="paper-bottom"><button class="read-card" data-card="${e(p.version_id)}">阅读研究卡片 <span>↗</span></button>${actions(p)}</div>`:`<a class="small" href="${safeArxivUrl(p.version_id)}" target="_blank" rel="noopener noreferrer">arXiv 原文 ↗</a>`}</article>`).join(''):'<div class="empty"><span>✳</span><h3>这里暂时没有论文</h3><p>可以切换栏目、日期，或调整搜索词。</p></div>';
  document.querySelectorAll('[data-card]').forEach(b=>b.onclick=()=>details(papers.find(p=>p.version_id===b.dataset.card)));
  bindActions();math();
}
function bindActions(){
  document.querySelectorAll('[data-flag]').forEach(b=>b.onclick=async()=>{
    const id=b.dataset.paper,flag=b.dataset.flag,value=!states[id]?.[flag];b.disabled=true;
    try{if(!demo){const {data,error}=await client.rpc('set_reading_flag',{p_paper_id:id,p_flag:flag,p_value:value});if(error)throw error;states[id]=Array.isArray(data)?data[0]:data;}else states[id]={...(states[id]??{}),[flag]:value};cards();message('已保存'+(demo?'（演示状态）':'，其他设备刷新后可见。'));}
    catch{message('保存失败，状态没有改变。',true);b.disabled=false;}
  });
}
function section(title,items){if(!items?.length)return '';return `<section><h3>${title}</h3><ul>${items.map(s=>`<li>${e(s)}</li>`).join('')}</ul></section>`;}
function details(p){
  const d=document.querySelector('#detail'),c=p.card??{};const coverage=p.source_coverage;
  d.innerHTML=`<button class="close" aria-label="关闭研究卡片">×</button><p class="eyebrow">RESEARCH NOTE · ${e(p.version_id)}</p><h2>${e(p.title)}</h2><p class="authors">${e(p.authors.join(' · '))}</p><a href="${safeArxivUrl(p.version_id)}" target="_blank" rel="noopener noreferrer">查看该版本原文 ↗</a><section><h3>摘要 · 中文</h3><p>${e(c.abstract_zh||'尚未生成中文摘要。')}</p><details><summary>英文原摘要</summary><p>${e(p.abstract)}</p></details></section>${section('主要结果',c.main_results)}${section('定理的关键条件',c.key_conditions)}${section('证明方法',c.proof_methods)}<section><h3>与课题的联系</h3><p>${e(c.connection||p.reason)}</p></section>${section('原文定位',c.evidence)}${section('关键参考文献',c.key_references)}${p.references_text?`<details><summary>原文参考文献列表</summary><pre>${e(p.references_text)}</pre></details>`:''}${section('读取边界与待核查项',c.limitations)}${coverage?`<p class="coverage">正文共 ${coverage.pages_total} 页；${coverage.full_text?'已提供全部可提取文本':'本次提供的PDF页码：'+e(coverage.pages_read.join(', '))}。文本提取不等于独立证明核查。</p>`:''}`;
  d.querySelector('.close').onclick=()=>d.close();d.showModal();math();
}
function interests(){
  const d=document.querySelector('#profile');
  d.innerHTML=`<button class="close" aria-label="关闭研究兴趣">×</button><p class="eyebrow">RESEARCH INTERESTS</p><h2>兴趣可以慢慢生长。</h2><p>每行一个方向；各方向同等重视。保存后用于下一次筛选。</p><textarea id="lines" rows="9">${e((profile?.profile?.research_lines??[]).join('\n'))}</textarea><button class="primary" id="save-lines">保存研究方向</button><section><h3>从本地材料提出建议</h3><p>仅手动触发。在电脑上运行“更新兴趣建议”，读取你指定的目录和聊天导出；新方向经你确认后才生效。</p>${profile?.proposal?.suggestions?.length?`<ul>${profile.proposal.suggestions.map(s=>`<li><strong>${e(s.direction)}</strong><p>${e(s.evidence.join('；'))}</p><p>${e(s.uncertainty)}</p></li>`).join('')}</ul><button id="accept-proposal">接受这些新增方向</button>`:'<p class="small">当前没有待确认建议。</p>'}</section><p id="profile-status" role="status"></p>`;
  d.querySelector('.close').onclick=()=>d.close();d.showModal();
  async function save(lines,accept=false){
    const status=d.querySelector('#profile-status');if(!lines.length){status.textContent='请至少保留一个研究方向。';return;}
    if(demo){status.textContent='这是本地演示，没有修改真实研究方向。';return;}
    const value={profile:{research_lines:lines},updated_at:new Date().toISOString()};if(accept)value.proposal=null;
    const {error}=await client.from('research_profiles').update(value).eq('user_id',user.id);
    if(error){status.textContent='保存失败，请重试。';return;}profile={...profile,...value};status.textContent='已保存，下一次筛选时生效。';
  }
  d.querySelector('#save-lines').onclick=()=>save(d.querySelector('#lines').value.split('\n').map(s=>s.trim()).filter(Boolean));
  d.querySelector('#accept-proposal')?.addEventListener('click',()=>save([...new Set([...(profile.profile?.research_lines??[]),...profile.proposal.suggestions.map(s=>s.direction)])],true));
}

async function start(){
  if(demo){
    user={id:'demo'};selectedDay='2026-10-07';digests=[{day:selectedDay,payload:{warnings:[]}}];
    papers=[['关于形变问题的一个示例研究','direct'],['一类导出工具的示例应用','extension'],['已收藏论文的示例修订','direct']].map(([title,relevance],i)=>({id:`0000.0000${i}`,version_id:`0000.0000${i}v1`,title,authors:['示例作者'],categories:['math.QA','math.AG'],abstract:'这是一条用于检查页面布局的虚构示例，不是真实论文推荐。',relevance,event:i===2?'revision':'new',reason:'这是本地界面演示。真实推荐将附摘要、定理条件、证明方法与原文定位。',analysis_status:'complete',card:{abstract_zh:'此处展示摘要译文。公式示例：$H^\\bullet(A)$。',main_results:['示例结果，不能作为研究结论引用。'],key_conditions:['示例条件'],proof_methods:['示例方法'],limitations:['仅演示界面。']}}));profile={profile:{research_lines:['示例研究方向一','示例研究方向二']}};shell();return;
  }
  try{
    const response=await fetch('./config.json',{cache:'no-store'});const cfg=await response.json();
    if(!cfg.supabaseUrl || !cfg.supabaseAnonKey){login();return;}
    client=createClient(cfg.supabaseUrl,cfg.supabaseAnonKey);
    client.auth.onAuthStateChange((event,session)=>{setTimeout(async()=>{if(!session){login();return;}user=session.user;try{await load();}catch{login('数据读取失败，请重试登录。');}},0);});
  }catch{login('网站配置暂不可用，请稍后再试。');}
}
start();
