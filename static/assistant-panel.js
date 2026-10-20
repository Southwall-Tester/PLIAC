/* One local conversation follows the learner through all platform pages. */
(async () => {
  if (window.PLIACAssistant) return;
  let pendingContext={};
  window.PLIACAssistant={setContext:value=>{pendingContext=value;},open:()=>{}};
  window.PLIACAccountReady ||= fetch('/api/account/me').then(async response=>{
    if(response.status===401){location.assign('/login?next='+encodeURIComponent(location.pathname+location.search));return null;}
    return response.ok?response.json():{testing:true};
  });
  const account=await window.PLIACAccountReady;
  if(!account)return;
  const key=account.user?'pliac-assistant-v2-'+account.user.id:'pliac-assistant-v1', uid=()=>crypto.randomUUID().replaceAll('-','');
  const get=(k,f='')=>{try{return localStorage.getItem(key+k)||f;}catch{return f;}};
  const put=(k,v)=>{try{localStorage.setItem(key+k,v);}catch{}};
  let owner=account.user?.assistant_owner||get('-owner');if(!owner){owner=uid();put('-owner',owner);}
  let active=get('-active'), current=null, busy=false, timer=null, selected=pendingContext, quote='', epoch=0;
  const host=document.createElement('pliac-assistant');
  document.body.appendChild(host);
  const shadow=host.attachShadow({mode:'open'});
  const icon='<svg class="mark" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-8l-6 4v-4H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z"/><path d="m8 11 2 2 5-5"/></svg>';
  shadow.innerHTML=`<link rel="stylesheet" href="/static/assistant-panel.css?v=2">
  <aside class="panel" aria-label="学习助手"><div class="heading">${icon}<strong>学习助手</strong><button id="profileButton" title="查看画像与记忆">记忆</button><button class="icon" id="new" title="新对话" aria-label="新对话">＋</button><button class="icon" id="close" title="收起助手" aria-label="收起助手">›</button></div>
  <section id="profile" class="profile" hidden><div class="profile-head"><strong>画像与记忆</strong><button id="backChat">返回聊天</button></div><label class="profile-toggle"><input id="profileEnabled" type="checkbox">记住对话，并用于个性化回答</label><div id="profileItems"></div><div id="episodeItems"></div></section>
  <div class="history"><select id="history" aria-label="历史对话"><option value="">新对话</option></select></div>
  <div class="context"><label><input type="checkbox" id="attach" checked><span id="context">结合当前页面</span></label><small>上下文</small></div>
  <div class="messages" id="messages" role="log" aria-label="聊天记录"></div>
  <div class="status" id="status" role="status" aria-live="polite"></div><button class="retry" id="retry" hidden>重试回答</button>
  <form class="compose" id="form"><div class="quote" id="quote" hidden><span></span><button type="button" class="icon" id="removeQuote" aria-label="移除引用">×</button></div><div class="input-box">
  <textarea id="input" rows="3" maxlength="6000" aria-label="向学习助手提问" placeholder="随时提问，或选中一段内容来讨论…"></textarea>
  <div class="actions"><button type="button" id="quoteButton" title="引用页面选中的文字">引用</button><small>Enter 发送 · Shift+Enter 换行</small><button type="button" id="stop" hidden>停止</button><button class="send" id="send" type="submit">发送 ↑</button></div></div><div class="footer" id="model">学习助手</div></form></aside>
  <button class="launcher" id="open" aria-label="打开学习助手">${icon}问问助手</button>`;
  const $=id=>shadow.getElementById(id);
  const wide=matchMedia('(min-width:1100px)'),openKey=()=>wide.matches?'-open':'-open-mobile';
  const layout=document.createElement('style');
  layout.textContent='@media(min-width:1100px){html.pliac-assistant-open body{width:calc(100% - 360px);margin-right:360px}html.pliac-assistant-open .workspace-grid{grid-template-columns:220px minmax(0,1fr)}html.pliac-assistant-open #graphScreen{grid-template-columns:minmax(0,1fr) 240px}}';
  document.head.appendChild(layout);
  const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function inline(text){return esc(text).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');}
  function markdown(text){
    return text.split(/(```[\s\S]*?```)/g).map(part=>{
      if(part.startsWith('```'))return '<pre><code>'+esc(part.replace(/^```[^\n]*\n?/,'').replace(/```$/,''))+'</code></pre>';
      return part.split(/\n\n+/).filter(Boolean).map(block=>{
        if(/^#{1,4} /.test(block))return '<h3>'+inline(block.replace(/^#{1,4} /,''))+'</h3>';
        const rows=block.split('\n');
        if(rows.length>=2&&rows[0].includes('|')&&/^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(rows[1])){
          const cells=row=>row.trim().replace(/^\||\|$/g,'').split('|').map(cell=>inline(cell.trim()));
          return '<div class="table-wrap"><table><thead><tr>'+cells(rows[0]).map(c=>'<th>'+c+'</th>').join('')+'</tr></thead><tbody>'+
            rows.slice(2).map(row=>'<tr>'+cells(row).map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
        }
        if(rows.every(x=>/^\s*[-*] /.test(x)))return '<ul>'+rows.map(x=>'<li>'+inline(x.replace(/^\s*[-*] /,''))+'</li>').join('')+'</ul>';
        if(rows.every(x=>/^\s*\d+[.)] /.test(x)))return '<ol>'+rows.map(x=>'<li>'+inline(x.replace(/^\s*\d+[.)] /,''))+'</li>').join('')+'</ol>';
        return '<p>'+inline(block).replaceAll('\n','<br>')+'</p>';
      }).join('');
    }).join('');
  }
  async function api(path,body){
    const response=await fetch('/api/assistant'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify({owner,...body}):undefined});
    const data=await response.json();if(!response.ok)throw Error(data.detail||'连接未完成，请重试。');return data;
  }
  function show(open,focus=false){
    shadow.querySelector('.panel').hidden=!open;$('open').hidden=open;
    document.documentElement.classList.toggle('pliac-assistant-open',open);
    put(openKey(),open?'yes':'no');window.dispatchEvent(new Event('resize'));if(open&&focus)$('input').focus();
  }
  function restorePanel(){const saved=get(openKey());show(saved?saved==='yes':wide.matches);}
  restorePanel();wide.addEventListener('change',restorePanel);
  $('close').onclick=()=>show(false);$('open').onclick=()=>show(true,true);
  function profileMode(open){
    $('profile').hidden=!open;
    for(const selector of ['.history','.context','.messages','.compose'])shadow.querySelector(selector).hidden=open;
    if(open){$('status').hidden=true;$('retry').hidden=true;}
    else{$('status').hidden=false;render(current);}
  }
  function renderProfile(data){
    $('profileEnabled').checked=data.enabled;
    $('profileItems').innerHTML=(!data.items.length&&!data.concepts.length)?'<p class="empty-profile">聊聊你的学习目标或讲解偏好，画像会逐步形成。</p>':
      data.items.map(i=>`<article class="memory profile-item" data-memory="${i.id}"><div class="memory-label">${esc(i.category_label)} · ${i.basis==='edited'?'你已修正':i.basis==='explicit'?'来自你的表达':'根据对话推测'}</div><p>${esc(i.value)}</p><details><summary>查看依据</summary>${i.evidence.map(e=>`<blockquote>${esc(e.quote)}</blockquote><button data-conversation="${e.conversation_id}">打开原对话</button>`).join('')}</details><div class="memory-actions"><button data-edit="${i.id}">修改</button><button data-delete="${i.id}">删除</button></div></article>`).join('')+
      (data.concepts.length?'<h3>知识点表现</h3>'+data.concepts.map(c=>`<article class="memory"><div class="memory-label">${esc(c.label)}</div><strong>${esc(c.concept_title)}</strong><p>${esc(c.reason)}</p><details><summary>判断依据</summary><blockquote>${esc(c.quote)}</blockquote><button data-conversation="${c.conversation_id}">打开原对话</button></details><button data-forget="${esc(c.course_id+':'+c.concept_id)}">移除这条判断</button></article>`).join(''):'');
    $('profileItems').querySelectorAll('[data-conversation]').forEach(b=>b.onclick=()=>{profileMode(false);switchTo(b.dataset.conversation);$('history').value=b.dataset.conversation;});
    $('profileItems').querySelectorAll('[data-delete]').forEach(b=>b.onclick=()=>editProfile({action:'delete',id:b.dataset.delete}));
    $('profileItems').querySelectorAll('[data-forget]').forEach(b=>b.onclick=()=>editProfile({action:'forget_concept',key:b.dataset.forget}));
    $('profileItems').querySelectorAll('[data-edit]').forEach(b=>b.onclick=()=>{
      const item=data.items.find(i=>i.id===b.dataset.edit),card=b.closest('.memory'),p=card.querySelector('p');
      const input=document.createElement('textarea');input.maxLength=240;input.value=item.value;p.replaceWith(input);input.focus();
      b.textContent='保存';b.onclick=()=>editProfile({action:'edit',id:item.id,value:input.value});
    });
    const episodes=data.memory?.entries||[],domains={learning:'学习',work:'工作',coding:'代码',general:'交流'};
    $('episodeItems').innerHTML='<h3>任务记忆</h3>'+(episodes.length?episodes.map(i=>`<article class="memory episode" data-episode="${esc(i.id)}"><div class="memory-label">${esc(domains[i.domain]||'交流')} · ${i.edited?'你已修正':esc((i.source?.created_at||'').slice(0,10))}</div><strong>${esc(i.subject||'对话记录')}</strong><p>${esc(i.summary)}</p><details><summary>查看原话</summary><blockquote>${esc(i.quote||'')}</blockquote><button data-episode-conversation="${esc(i.source.conversation_id)}">打开原对话</button></details><div class="memory-actions"><button data-episode-edit="${esc(i.id)}">修改</button><button data-episode-delete="${esc(i.id)}">删除</button></div></article>`).join(''):'<p class="empty-episodes">讨论任务后，目标、决策和过程会保存在这里。</p>');
    $('episodeItems').querySelectorAll('[data-episode-conversation]').forEach(b=>b.onclick=()=>openConversation(b.dataset.episodeConversation));
    $('episodeItems').querySelectorAll('[data-episode-delete]').forEach(b=>b.onclick=()=>editMemory({action:'delete',id:b.dataset.episodeDelete}));
    $('episodeItems').querySelectorAll('[data-episode-edit]').forEach(b=>b.onclick=()=>{
      const item=episodes.find(i=>i.id===b.dataset.episodeEdit),card=b.closest('.episode'),p=card.querySelector('p');
      const input=document.createElement('textarea');input.maxLength=400;input.value=item.summary;p.replaceWith(input);input.focus();
      b.textContent='保存';b.onclick=()=>editMemory({action:'edit',id:item.id,value:input.value});
    });
  }
  function openConversation(id){profileMode(false);switchTo(id);$('history').value=id;}
  async function editProfile(body){try{renderProfile(await api('/profile',body));}catch(e){$('profileItems').insertAdjacentHTML('afterbegin','<p>'+esc(e.message)+'</p>');}}
  async function editMemory(body){try{renderProfile(await api('/memory',body));}catch(e){$('episodeItems').insertAdjacentHTML('afterbegin','<p>'+esc(e.message)+'</p>');}}
  $('profileEnabled').onchange=()=>editProfile({action:'toggle',enabled:$('profileEnabled').checked});
  $('profileButton').onclick=async()=>{profileMode(true);try{renderProfile(await api('/profile?owner='+owner));}catch(e){$('profileItems').textContent=e.message;}};
  $('backChat').onclick=()=>profileMode(false);
  function theme(){host.toggleAttribute('dark',document.documentElement.classList.contains('network-dark'));}
  new MutationObserver(theme).observe(document.documentElement,{attributes:true,attributeFilter:['class']});theme();
  function context(){
    if(!$('attach').checked)return {selection:quote};
    const p=new URLSearchParams(location.search);
    return {page:location.pathname,course_id:p.get('course_id')||'',document_id:location.pathname==='/documents'?(p.get('id')||''):'',
      node_id:p.get('node_id')||'',chapter_id:p.get('chapter_id')||'',job_id:p.get('job_id')||'',...selected,selection:quote};
  }
  function contextLabel(){
    const title=selected.title||document.getElementById('activeCourseTitle')?.textContent||document.getElementById('courseName')?.textContent||document.title;
    $('context').textContent=title.trim()||'当前页面';$('context').title=title;
  }
  window.PLIACAssistant={setContext(value){selected=value;contextLabel();},open:()=>show(true,true)};
  // Title and selection labels arrive after asynchronous course loading.
  new MutationObserver(contextLabel).observe(document.body,{subtree:true,childList:true,characterData:true});
  contextLabel();
  function status(text){$('status').textContent=text;}
  function captureQuote(){
    let text=window.getSelection()?.toString()||'';
    if(!text)try{text=document.getElementById('lessonFrame')?.contentWindow?.getSelection()?.toString()||'';}catch{}
    if(text.trim()){quote=text.trim().slice(0,3000);$('quote').hidden=false;$('quote').querySelector('span').textContent=quote;}
  }
  document.addEventListener('mouseup',event=>{if(!event.composedPath().includes(host))captureQuote();});
  $('quoteButton').onclick=()=>{captureQuote();if(!quote)status('先在页面选中想讨论的文字，再点“引用”。');};
  $('removeQuote').onclick=()=>{quote='';$('quote').hidden=true;};
  $('input').value=get('-draft');$('input').oninput=()=>put('-draft',$('input').value);
  function recallSources(message){
    const sources=message.memory_references||[];
    if(!sources.length)return '';
    return `<details class="recall"><summary>参考了 ${sources.length} 条历史记忆</summary>`+
      sources.map(i=>`<p>${esc(i.summary)}</p><button data-recall-conversation="${esc(i.source.conversation_id)}">查看原对话</button>`).join('')+'</details>';
  }
  function render(data){
    const box=$('messages'),nearEnd=box.scrollHeight-box.scrollTop-box.clientHeight<90;
    current=data;
    const messages=data?.messages||[];
    const fingerprint=JSON.stringify(messages);
    if(box.dataset.fingerprint!==fingerprint){
      box.dataset.fingerprint=fingerprint;
      box.innerHTML=messages.length?messages.map(m=>`<article class="message ${m.role}"><div class="role">${m.role==='user'?'你':'学习助手'}${m.role==='assistant'?`<button data-copy="${esc(m.id)}">复制</button>`:''}</div><div class="body">${markdown(m.content)}</div>${m.diagnosis?.length?`<div class="focus">${m.diagnosis.map(d=>`<strong>${esc(d.concept_title)} · ${esc(d.label)}</strong><p>${esc(d.reason)}</p>${d.check_question?`<button data-question="${esc(d.check_question)}">练一题：${esc(d.check_question)}</button>`:''}`).join('')}</div>`:''}${m.references?.length?'<div class="sources">'+m.references.filter(r=>r.url.startsWith('/')&&!r.url.startsWith('//')).map(r=>`<a href="${esc(r.url)}" title="${esc(r.title)}">[${esc(r.id)}] ${esc(r.title)}</a>`).join('')+'</div>':''}${recallSources(m)}</article>`).join(''):
        `<div class="welcome"><h2>哪里想再聊一聊？</h2><p>解释知识、分析卡点，或一起推敲你的想法。</p><div class="suggestions"><button>用一个例子解释当前内容</button><button>帮我判断哪里理解错了</button><button>出一道题，看看我理解得怎样</button></div></div>`;
      box.querySelectorAll('.suggestions button').forEach(b=>b.onclick=()=>{$('input').value=b.textContent;put('-draft',$('input').value);$('input').focus();});
      box.querySelectorAll('[data-copy]').forEach(b=>b.onclick=async()=>{try{await navigator.clipboard.writeText(messages.find(m=>m.id===b.dataset.copy).content);b.textContent='已复制';}catch{status('请选择回答文字复制。');}});
      box.querySelectorAll('[data-question]').forEach(b=>b.onclick=()=>{$('input').value='针对“'+b.dataset.question+'”，我的回答是：';$('input').focus();});
      box.querySelectorAll('[data-recall-conversation]').forEach(b=>b.onclick=()=>openConversation(b.dataset.recallConversation));
      if(nearEnd)box.scrollTop=box.scrollHeight;
    }
    const running=data?.status==='running';$('send').disabled=running||busy;$('stop').hidden=!running;$('send').hidden=running;
    $('retry').hidden=!['failed','cancelled'].includes(data?.status);
    $('status').classList.toggle('loading',running);status(running?'正在思考…':data?.error||'');
    clearTimeout(timer);
    if(running)timer=setTimeout(()=>load(active),1000);
  }
  async function history(){
    const result=await api('/conversations?owner='+owner);
    $('history').innerHTML='<option value="">新对话</option>'+result.conversations.map(c=>`<option value="${c.id}">${esc(c.title)}</option>`).join('');
    $('history').value=active||'';
  }
  async function load(id){
    if(!id){render(null);return;}
    const generation=epoch;
    try{const data=await api('/conversations/'+id+'?owner='+owner);if(generation===epoch&&active===id)render(data);}
    catch(error){if(generation===epoch)status(error.message);}
  }
  async function switchTo(id){epoch++;clearTimeout(timer);active=id;put('-active',id);current=null;render(null);await load(id);}
  $('history').onchange=()=>switchTo($('history').value);
  $('new').onclick=()=>{profileMode(false);switchTo('');$('history').value='';$('input').value='';put('-draft','');$('input').focus();};
  $('form').onsubmit=async event=>{
    event.preventDefault();const text=$('input').value.trim();if(!text||busy||current?.status==='running')return;
    busy=true;$('send').disabled=true;status('正在发送…');const generation=epoch;
    try{
      let id=active;
      if(!id){const created=await api('/conversations',{});id=created.id;if(epoch!==generation)return;active=id;put('-active',id);}
      const data=await api('/conversations/'+id+'/messages',{message:text,request_id:uid(),context:context()});
      if(epoch!==generation)return;
      $('input').value='';put('-draft','');quote='';$('quote').hidden=true;busy=false;render(data);$('messages').scrollTop=$('messages').scrollHeight;await history();
    }catch(error){if(epoch===generation)status(error.message);}
    finally{busy=false;$('send').disabled=current?.status==='running';}
  };
  $('input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('form').requestSubmit();}});
  for(const action of ['stop','retry'])$(action).onclick=async()=>{
    const id=active,generation=epoch;
    try{const data=await api('/conversations/'+id+'/'+action,{});if(epoch===generation&&active===id)render(data);}catch(e){status(e.message);}
  };
  document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='j'){e.preventDefault();show(shadow.querySelector('.panel').hidden,true);}});
  render(null);history().then(()=>load(active)).catch(e=>status(e.message));
  api('/status').then(data=>{$('model').textContent=data.ready?data.model:'配置模型后即可开始对话';}).catch(()=>{$('model').textContent='连接恢复后可继续提问';});
})();
