/* Chat app. Reads the token set by the login page (sessionStorage); if it is
   missing, bounce back to the login page. */

const authToken = sessionStorage.getItem('av_token');

let conversations = [];        // sidebar entries: {id, sessionId, title, messages, loaded}
let activeId = null;
let busy = false;

const $ = s => document.querySelector(s);
const thread=$('#thread'), scroll=$('#scroll'), input=$('#input'), send=$('#send'),
      history=$('#history'), topTitle=$('#topTitle'), searchInput=$('#searchInput');

const MARK_SVG = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="3.2" y="3.2" width="9.6" height="9.6" rx="1.4" transform="rotate(45 8 8)" stroke="var(--accent-ink)" stroke-width="1.5"/><circle cx="8" cy="8" r="1.7" fill="var(--accent-ink)"/></svg>';

const suggestions = [
  {ic:'search', t:'Search your notes',  d:'Summarize a topic from my notes.'},
  {ic:'memory', t:'Multi-turn memory',  d:'My name is Sushmita. (then later: what is my name?)'},
  {ic:'draft',  t:'Do quick math',      d:'What is 15% of 240?'},
  {ic:'link',   t:'Ask the date',       d:'What is today’s date?'},
];

/* ============ SAFETY: escape everything dynamic ============ */
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function inline(s){
  return s.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
          .replace(/`([^`]+?)`/g,'<code>$1</code>');
}

/* markdown -> html. handles fenced code, headings, ordered/bullet lists, bold,
   inline code. all text is escaped before any formatting (XSS-safe). */
function fmt(text){
  const parts = String(text).split('```');
  let html='';
  for(let i=0;i<parts.length;i++){
    if(i % 2 === 1){
      let body=parts[i], lang='';
      const nl=body.indexOf('\n');
      if(nl!==-1){
        const head=body.slice(0,nl).trim();
        if(/^[\w+#.-]{0,16}$/.test(head)){ lang=head; body=body.slice(nl+1); }
      }
      html+=`<div class="codeblock"><div class="cb-head"><span>${esc(lang||'code')}</span></div><pre>${esc(body.replace(/\n$/,''))}</pre></div>`;
    } else {
      html+=renderBlocks(parts[i]);
    }
  }
  return html;
}
function renderBlocks(chunk){
  const lines=chunk.split('\n');
  let html='', i=0;
  const isH=l=>/^\s*#{1,6}\s+/.test(l), isOl=l=>/^\s*\d+\.\s+/.test(l), isUl=l=>/^\s*[-*]\s+/.test(l);
  while(i<lines.length){
    const line=lines[i];
    if(!line.trim()){ i++; continue; }
    const m=line.match(/^\s*(#{1,6})\s+(.*)$/);
    if(m){ const lvl=Math.min(m[1].length,6); html+=`<div class="h h${lvl}">${inline(esc(m[2].trim()))}</div>`; i++; continue; }
    if(isOl(line)){
      const items=[];
      while(i<lines.length && isOl(lines[i])){ items.push(`<li>${inline(esc(lines[i].replace(/^\s*\d+\.\s+/,'')))}</li>`); i++; }
      html+=`<ol>${items.join('')}</ol>`; continue;
    }
    if(isUl(line)){
      const items=[];
      while(i<lines.length && isUl(lines[i])){ items.push(`<li>${inline(esc(lines[i].replace(/^\s*[-*]\s+/,'')))}</li>`); i++; }
      html+=`<ul>${items.join('')}</ul>`; continue;
    }
    const para=[];
    while(i<lines.length && lines[i].trim() && !isH(lines[i]) && !isOl(lines[i]) && !isUl(lines[i])){ para.push(lines[i]); i++; }
    html+=`<p>${inline(esc(para.join('\n'))).replace(/\n/g,'<br>')}</p>`;
  }
  return html;
}

function citesHTML(cites){
  return `<div class="cites">`+cites.map(c=>`<span class="cite"><span class="ci-num">${c.n}</span>${esc(c.title)}</span>`).join('')+`</div>`;
}
function memHTML(text){
  return `<div class="mem-saved"><svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M8 2.6c1.5 0 2.4 1 2.4 1 1.7 0 3 1.2 3 2.9 0 .8-.3 1.4-.3 1.4s.6.7.6 1.6c0 1.6-1.4 2.6-3 2.6 0 0-.9 1.3-2.7 1.3S5.3 12.7 5.3 12.7c-1.6 0-3-1-3-2.6 0-.9.6-1.6.6-1.6S2.6 7.3 2.6 6.5c0-1.7 1.3-2.9 3-2.9 0 0 .9-1 2.4-1Z" stroke="var(--accent)" stroke-width="1.2"/></svg><span class="ms-txt"><b>Memory saved</b>${text ? ' · '+esc(text) : ''}</span></div>`;
}
function guardHTML(){
  return `<div class="guard-ok"><svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M2.5 6.2 5 8.5l4.5-5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>output validated</div>`;
}
const actionsHTML = `<div class="m-actions">
  <button class="m-act copy" title="Copy"><svg width="15" height="15" viewBox="0 0 16 16" fill="none"><rect x="5.5" y="5.5" width="7.5" height="7.5" rx="1.5" stroke="currentColor" stroke-width="1.3"/><path d="M3 10.5V4a1.5 1.5 0 0 1 1.5-1.5H10" stroke="currentColor" stroke-width="1.3"/></svg></button>
</div>`;

/* collapsible tool trace: which tools ran, and what they returned */
function traceHTML(tools){
  const steps=tools.map(t=>{
    const arg=t.detail ? `("${esc(t.detail)}")` : '';
    const right=(t.sources && t.sources.length) ? `${t.sources.length} notes` : (t.result ? esc(t.result) : '');
    return `<div class="trace-step"><span class="arrow">→</span><span class="path">${esc(t.name)}${arg}</span><span class="lines">${right}</span></div>`;
  }).join('');
  const label=tools.length===1 ? '1 tool' : tools.length+' tools';
  return `<div class="trace"><div class="trace-head"><span class="glow">⟢</span> agent · ${label}<span class="tcount"><svg class="chev" width="13" height="13" viewBox="0 0 16 16" fill="none"><path d="M5.5 6.5 8 9l2.5-2.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></span></div><div class="trace-body">${steps}</div></div>`;
}
function bindTraces(root){
  (root||thread).querySelectorAll('.trace-head').forEach(h=>{
    h.onclick=()=> h.parentElement.classList.toggle('collapsed');
  });
}

/* ============ RENDER ============ */
function assistantHTML(m){
  const trace = (m.tools && m.tools.length) ? traceHTML(m.tools) : '';
  const mems = (m.mems && m.mems.length) ? m.mems.map(memHTML).join('') : '';
  const badge = m.guardOk ? guardHTML() : '';
  const body = trace
    + `<div class="answer">${fmt(m.text)}</div>`
    + badge
    + (m.cites && m.cites.length ? citesHTML(m.cites) : '')
    + mems
    + actionsHTML;
  return `<div class="msg assistant"><div class="m-avatar">${MARK_SVG}</div><div class="m-body">${body}</div></div>`;
}
function userHTML(m){
  return `<div class="msg user"><div class="bubble">${esc(m.text)}</div></div>`;
}

function renderHistory(){
  const q=(searchInput.value||'').toLowerCase();
  const list=conversations.filter(c=>!q || c.title.toLowerCase().includes(q));
  history.innerHTML='';
  if(!list.length){
    const lbl=document.createElement('div');
    lbl.className='group-label'; lbl.textContent = q ? 'No matches' : 'No conversations yet';
    history.appendChild(lbl); return;
  }
  const lbl=document.createElement('div'); lbl.className='group-label'; lbl.textContent='Recent';
  history.appendChild(lbl);
  list.forEach(c=>{
    const el=document.createElement('div');
    el.className='chat-item'+(c.id===activeId?' active':'');
    el.innerHTML='<span class="ci-dot"></span><span class="ci-title"></span>';
    el.querySelector('.ci-title').textContent=c.title;   // textContent = XSS-safe
    el.onclick=()=> openConversation(c.id);
    history.appendChild(el);
  });
}

async function loadConversations(){
  try{
    const resp=await fetch('/conversations',{headers:{'Authorization':'Bearer '+authToken}});
    if(resp.status===401){ logout(); return; }
    if(!resp.ok) return;
    const rows=await resp.json();                 // [{id, title, updated_at}]
    conversations=rows.map(r=>({id:r.id, sessionId:r.id, title:r.title, messages:[], loaded:false}));
    renderHistory();
  }catch(e){ /* leave the sidebar empty if it can't load */ }
}

async function openConversation(id){
  if(busy) return;
  activeId=id; renderHistory();
  const conv=conversations.find(c=>c.id===id);
  if(conv && !conv.loaded){
    try{
      const resp=await fetch('/conversations/'+encodeURIComponent(id),{headers:{'Authorization':'Bearer '+authToken}});
      if(resp.status===401){ logout(); return; }
      if(resp.ok){
        const msgs=await resp.json();             // [{role, content, sources}]
        conv.messages=msgs.map(m=>({role:m.role, text:m.content, cites:(m.sources||[]).map((s,i)=>({n:i+1, title:s}))}));
        conv.loaded=true;
      }
    }catch(e){}
  }
  renderThread();
}

function renderThread(){
  const conv=conversations.find(c=>c.id===activeId);
  topTitle.textContent = conv ? conv.title : 'New conversation';
  if(!conv || conv.messages.length===0){ renderEmpty(); return; }
  thread.innerHTML = conv.messages.map(m=> m.role==='user'?userHTML(m):assistantHTML(m)).join('');
  bindActions(); bindTraces();
  requestAnimationFrame(()=>{ scroll.scrollTop=scroll.scrollHeight; });
}

function renderEmpty(){
  const ic={
    search:'<svg width="20" height="20" viewBox="0 0 18 18" fill="none"><circle cx="8" cy="8" r="5" stroke="currentColor" stroke-width="1.5"/><path d="m12 12 3 3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>',
    link:'<svg width="20" height="20" viewBox="0 0 18 18" fill="none"><path d="M7.5 10.5 10.5 7.5M6 12l-1 1a2.5 2.5 0 0 1-3.5-3.5l2-2A2.5 2.5 0 0 1 6 7M12 6l1-1a2.5 2.5 0 0 0-3.5-3.5l-2 2A2.5 2.5 0 0 0 7 6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>',
    memory:'<svg width="20" height="20" viewBox="0 0 16 16" fill="none"><path d="M8 2.6c1.5 0 2.4 1 2.4 1 1.7 0 3 1.2 3 2.9 0 .8-.3 1.4-.3 1.4s.6.7.6 1.6c0 1.6-1.4 2.6-3 2.6 0 0-.9 1.3-2.7 1.3S5.3 12.7 5.3 12.7c-1.6 0-3-1-3-2.6 0-.9.6-1.6.6-1.6S2.6 7.3 2.6 6.5c0-1.7 1.3-2.9 3-2.9 0 0 .9-1 2.4-1Z" stroke="currentColor" stroke-width="1.3"/></svg>',
    draft:'<svg width="20" height="20" viewBox="0 0 18 18" fill="none"><path d="M3 13.5 4 10l7-7 3 3-7 7-3.5 1Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>',
  };
  thread.innerHTML=`<div class="empty">
    <div class="e-mark"><svg width="26" height="26" viewBox="0 0 16 16" fill="none"><rect x="3.2" y="3.2" width="9.6" height="9.6" rx="1.4" transform="rotate(45 8 8)" stroke="var(--accent-ink)" stroke-width="1.4"/><circle cx="8" cy="8" r="1.7" fill="var(--accent-ink)"/></svg></div>
    <h1>What should we dig up?</h1>
    <p>Ask about your notes, do some math, or check the date. I cite the notes I use and remember the conversation.</p>
    <div class="suggests"></div>
  </div>`;
  const wrap=thread.querySelector('.suggests');
  suggestions.forEach(s=>{
    const b=document.createElement('button');
    b.className='suggest';
    b.innerHTML=`<div class="s-ic">${ic[s.ic]}</div><div class="s-t"></div><div class="s-d"></div>`;
    b.querySelector('.s-t').textContent=s.t;
    b.querySelector('.s-d').textContent=s.d;
    b.onclick=()=>{ input.value=s.d; input.dispatchEvent(new Event('input')); input.focus(); };
    wrap.appendChild(b);
  });
}

function bindActions(){
  thread.querySelectorAll('.m-act.copy').forEach(btn=>{
    btn.onclick=()=>{
      const ans=btn.closest('.m-body').querySelector('.answer');
      if(ans) navigator.clipboard?.writeText(ans.innerText);
    };
  });
}

/* ============ SEND + REAL STREAMING ============ */
const shorten=s=>{const w=s.replace(/\s+/g,' ').trim().split(' ');return w.slice(0,7).join(' ')+(w.length>7?'…':'');};

async function handleSend(){
  const q=input.value.trim();
  if(!q || busy || !authToken) return;

  let conv=conversations.find(c=>c.id===activeId);
  if(!conv){
    const cid=crypto.randomUUID();
    conv={id:cid, sessionId:cid, title:shorten(q), messages:[], loaded:true};
    conversations.unshift(conv); activeId=conv.id;
  } else {
    conversations=[conv, ...conversations.filter(c=>c!==conv)];   // bump to most-recent
  }
  if(conv.messages.length===0) conv.title=shorten(q);

  conv.messages.push({role:'user', text:q});
  input.value=''; input.style.height='auto'; updateSend();
  renderHistory(); renderThread();

  busy=true; updateSend();

  const work=document.createElement('div');
  work.className='msg assistant';
  work.innerHTML=`<div class="m-avatar">${MARK_SVG}</div><div class="m-body"><div class="working"><span>thinking</span><span class="dots"><i></i><i></i><i></i></span></div></div>`;
  thread.appendChild(work);
  scroll.scrollTop=scroll.scrollHeight;

  let acc='';
  try{
    const resp=await fetch('/chat',{
      method:'POST',
      headers:{'content-type':'application/json','Authorization':'Bearer '+authToken},
      body:JSON.stringify({session_id:conv.sessionId, message:q}),
    });
    if(resp.status===401){ logout(); return; }
    if(!resp.ok || !resp.body) throw new Error('server responded '+resp.status);

    const mbody=work.querySelector('.m-body');
    mbody.innerHTML='';
    let traceWrap=null, ansEl=null, guardOk=null;
    const tools=[], sources=[], memSaved=[];

    const reader=resp.body.getReader();
    const dec=new TextDecoder();
    let buf='';
    while(true){
      const {done, value}=await reader.read();
      if(done) break;
      buf+=dec.decode(value,{stream:true});
      const lines=buf.split('\n');
      buf=lines.pop();                 // keep any partial line for next chunk
      for(const line of lines){
        if(!line.startsWith('data: ')) continue;
        let ev; try{ ev=JSON.parse(line.slice(6)); }catch{ continue; }
        if(ev.type==='token'){
          acc+=ev.text;
          if(!ansEl){ ansEl=document.createElement('div'); ansEl.className='answer streaming'; mbody.appendChild(ansEl); }
          ansEl.innerHTML=fmt(acc);    // fmt escapes before formatting
          scroll.scrollTop=scroll.scrollHeight;
        } else if(ev.type==='tool'){
          tools.push(ev);
          (ev.sources||[]).forEach(s=>{ if(!sources.includes(s)) sources.push(s); });
          if(!traceWrap){ traceWrap=document.createElement('div'); mbody.insertBefore(traceWrap, mbody.firstChild); }
          traceWrap.innerHTML=traceHTML(tools);
          bindTraces(mbody);
          scroll.scrollTop=scroll.scrollHeight;
        } else if(ev.type==='memory'){
          memSaved.push(ev.text);
        } else if(ev.type==='replace'){
          acc=ev.text;     // post-guard failed: swap the streamed answer for the safe one
          if(!ansEl){ ansEl=document.createElement('div'); ansEl.className='answer'; mbody.appendChild(ansEl); }
          ansEl.innerHTML=fmt(acc);
        } else if(ev.type==='guard'){
          guardOk=ev.ok;
        }
      }
    }
    if(ansEl) ansEl.classList.remove('streaming');

    const cites = (guardOk===false) ? [] : sources.map((s,i)=>({n:i+1, title:s}));
    if(guardOk===true) mbody.insertAdjacentHTML('beforeend', guardHTML());
    if(cites.length) mbody.insertAdjacentHTML('beforeend', citesHTML(cites));
    memSaved.forEach(t=> mbody.insertAdjacentHTML('beforeend', memHTML(t)));
    mbody.insertAdjacentHTML('beforeend', actionsHTML);
    bindActions();
    conv.messages.push({role:'assistant', text:acc, cites, tools, mems:memSaved, guardOk});
  }catch(e){
    work.querySelector('.m-body').innerHTML=`<div class="answer err">Could not reach the agent (${esc(String(e.message||e))}). Is the server running?</div>`;
  }finally{
    busy=false; updateSend();
    scroll.scrollTop=scroll.scrollHeight;
  }
}

/* ============ COMPOSER WIRING ============ */
function updateSend(){ send.disabled = busy || input.value.trim()===''; }
input.addEventListener('input', ()=>{
  input.style.height='auto';
  input.style.height=Math.min(input.scrollHeight,180)+'px';
  updateSend();
});
input.addEventListener('keydown', e=>{
  if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); handleSend(); }
});
send.addEventListener('click', handleSend);
$('#composer').addEventListener('focusin',()=>$('#composer').classList.add('focus'));
$('#composer').addEventListener('focusout',()=>$('#composer').classList.remove('focus'));

$('#newChatBtn').onclick=()=>{
  if(busy) return;
  activeId=null;
  topTitle.textContent='New conversation';
  renderHistory(); renderEmpty(); input.focus();
};
searchInput.addEventListener('input', renderHistory);

/* ============ AUTH ============ */
function logout(){
  sessionStorage.removeItem('av_token');
  window.location.replace('/');
}
$('#logoutBtn').onclick=()=>logout();

/* ============ INIT ============ */
if(!authToken){
  window.location.replace('/');     // not signed in -> back to login
}else{
  loadConversations();
  renderEmpty();
  input.focus();
  updateSend();
}
