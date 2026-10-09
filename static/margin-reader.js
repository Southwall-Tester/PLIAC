(() => {
  'use strict';
  const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const params=new URLSearchParams(location.search),courseId=params.get('course_id')||'';
  let jobId=params.get('job_id'),preferredJob=jobId,base='';const query='course_id='+encodeURIComponent(courseId);
  const scopeFields=['chapter_id','section_id','node_id','source_job_id','concept_id'];
  let selection=Object.fromEntries(scopeFields.map(k=>[k,params.get(k)||''])),scopeData=null,refreshRevision=0,loadRevision=0;
  let selectedConcept=null;
  let lesson,map,network,ready=false,pending='overview',sourceButton,sourceScroll=0;
  const fail=e=>{$('error').hidden=false;$('error').textContent=e.message||String(e);};

  async function get(url){const r=await fetch(url+(url.includes('?')?'&':'?')+query);if(!r.ok){const e=await r.json();throw new Error(e.detail||'讲义读取失败');}return r.json();}
  const practice=new HandoutPractice(courseId,fail);
  function show(mode){$('graphScreen').hidden=mode!=='graph';$('readingScreen').hidden=mode!=='read';$('exerciseScreen').hidden=mode!=='exercise';$('exerciseMode').setAttribute('aria-pressed',mode==='exercise');if(mode==='exercise')practice.load(jobId).catch(fail);$('mapMode').setAttribute('aria-pressed',mode==='graph');$('readMode').setAttribute('aria-pressed',mode==='read');if(mode==='read'){const frame=$('lessonFrame');if(frame.dataset.url&&frame.getAttribute('src')!==frame.dataset.url)frame.src=frame.dataset.url;else jump();}}
  function markReading(anchor){
    pending=anchor;
    const buttons=$('readingScreen').querySelectorAll('nav [data-section]');
    for(const button of buttons){
      if(button.dataset.section===anchor)button.setAttribute('aria-current','location');
      else button.removeAttribute('aria-current');
    }
    const selected=[...buttons].find(button=>button.dataset.section===anchor);
    if(selected&&!$('readingScreen').hidden){
      const nav=$('readingScreen').querySelector('nav'),box=nav.getBoundingClientRect(),item=selected.getBoundingClientRect();
      if(item.top<box.top)nav.scrollTop-=box.top-item.top;
      else if(item.bottom>box.bottom)nav.scrollTop+=item.bottom-box.bottom;
      if(item.left<box.left)nav.scrollLeft-=box.left-item.left;
      else if(item.right>box.right)nav.scrollLeft+=item.right-box.right;
    }
    try{localStorage.setItem('pliac.margin.'+jobId,pending);}catch{}
  }
  function jump(){markReading(pending);if(!ready)return;const doc=$('lessonFrame').contentDocument,target=doc.querySelector('#pages #'+CSS.escape(pending));target?.scrollIntoView({block:'start'});if(target){target.style.outline='2px solid #91b6a1';setTimeout(()=>target.style.outline='',1600);}}
  function read(anchor){markReading(anchor);show('read');}
  function trackReading(win,doc){
    const targets=[...$('readingScreen').querySelectorAll('nav [data-section]')].map(button=>doc.querySelector('#pages #'+CSS.escape(button.dataset.section))).filter(Boolean);
    let scheduled=false,lastScrollY=win.scrollY;
    win.addEventListener('scroll',()=>{
      if(scheduled||!ready||doc!==$('lessonFrame').contentDocument||$('readingScreen').hidden)return;
      scheduled=true;
      win.requestAnimationFrame(()=>{
        scheduled=false;
        if(!ready||doc!==$('lessonFrame').contentDocument||$('readingScreen').hidden||!targets.length)return;
        // Layout/viewport changes can emit scroll without moving the reader.
        // Such events must not overwrite the saved reading position.
        if(win.scrollY===lastScrollY)return;
        lastScrollY=win.scrollY;
        let current=targets[0];
        for(const target of targets)if(target.getBoundingClientRect().top<=32)current=target;
        if(win.scrollY+win.innerHeight>=doc.documentElement.scrollHeight-4)current=targets.at(-1);
        if(current.id!==pending)markReading(current.id);
      });
    },{passive:true});
  }
  function sectionLinks(ids){return ids.map(id=>{const index=lesson.sections.findIndex(s=>s.id===id);return index<0?'':`<a href="#section-${index+1}" data-section="section-${index+1}">阅读：${esc(lesson.sections[index].title)}</a>`;}).join('');}
  function sourceLinks(refs=[]){return refs.filter(ref=>/^[a-f0-9]{32}:[1-9]\d*$/i.test(ref)).map(ref=>`<button data-source-ref="${esc(ref)}">原文 PDF 第 ${esc(ref.split(':')[1])} 页</button>`).join('');}
  function syncSelection(id,reveal=true){
    selectedConcept=id;$('studyConcept').hidden=!id;
    for(const button of $('conceptList').children)button.setAttribute('aria-pressed',String(button.dataset.concept===id));
    const button=[...$('conceptList').children].find(button=>button.dataset.concept===id);
    // A graph click reveals its matching button even when a search excluded it.
    if(reveal&&button?.hidden){$('search').value='';filterConcepts();}
    if(reveal&&button){
      const list=$('conceptList'),box=list.getBoundingClientRect(),item=button.getBoundingClientRect();
      if(item.top<box.top)list.scrollTop-=box.top-item.top+8;
      else if(item.bottom>box.bottom)list.scrollTop+=item.bottom-box.bottom+8;
    }
    if(!network?.data)return;
    const accent=document.documentElement.classList.contains('network-dark')?'#a5dfc4':'#305e50';
    const data={...network.data,nodes:network.data.nodes.map(node=>({...node,style:{...node.style,lineWidth:node.id===id?3:1,stroke:node.id===id?accent:GraphEncoding.outline(node.style.fill)}}))};
    network.setData(data).catch(fail);
  }
  function select(id){const node=map.nodes.find(n=>n.id===id);if(!node)return;$('detail').scrollTop=0;syncSelection(id);$('conceptTitle').textContent=node.title;$('conceptSources').innerHTML=sourceLinks(node.source_refs);$('definition').textContent=node.definition;$('sectionLinks').innerHTML=sectionLinks(node.section_ids);$('relationships').innerHTML=map.edges.map((e,i)=>({...e,i})).filter(e=>e.source===id||e.target===id).map(e=>`<button data-edge="${e.i}">${esc(map.nodes.find(n=>n.id===(e.source===id?e.target:e.source))?.title)} · ${esc(e.predicate)}</button>`).join('');$('evidence').hidden=!node.quote;$('quote').textContent=node.quote||'';}
  function relation(index){const e=map.edges[index];if(!e)return;$('detail').scrollTop=0;syncSelection(null);$('conceptTitle').textContent=map.nodes.find(n=>n.id===e.source).title+' · '+e.predicate+' · '+map.nodes.find(n=>n.id===e.target).title;$('definition').textContent=e.quote;$('conceptSources').innerHTML=sourceLinks(e.source_refs);$('sectionLinks').innerHTML=sectionLinks(e.evidence_section?[e.evidence_section]:[...new Set(map.nodes.filter(n=>[e.source,e.target].includes(n.id)).flatMap(n=>n.section_ids))]);$('evidence').hidden=true;}
  document.addEventListener('click',event=>{const target=event.target.closest('[data-section],[data-concept],[data-edge],[data-source-ref]');if(!target)return;event.preventDefault();if(target.dataset.sourceRef)source(target.dataset.sourceRef,target);if(target.dataset.section)read(target.dataset.section);if(target.dataset.concept)select(target.dataset.concept);if(target.dataset.edge!==undefined)relation(Number(target.dataset.edge));});
  $('exerciseMode').onclick=()=>show('exercise');
  $('studyConcept').onclick=()=>changeScope({source_job_id:jobId,concept_id:selectedConcept});
  $('mapMode').onclick=()=>show('graph');$('readMode').onclick=()=>show('read');$('fit').onclick=()=>network?.fit();$('themeButton').onclick=()=>{GraphTheme.toggle();syncSelection(selectedConcept,false);};
  function filterConcepts(){
    const text=$('search').value.trim().toLowerCase(),buttons=[...$('conceptList').children];
    for(const button of buttons)button.hidden=!button.textContent.toLowerCase().includes(text);
    const count=buttons.filter(button=>!button.hidden).length;
    $('conceptCount').textContent=text?`匹配 ${count} / ${buttons.length} 个知识点`:`共 ${buttons.length} 个知识点`;
    $('conceptEmpty').hidden=count!==0;
    $('conceptList').scrollTop=0;
  }
  $('search').oninput=filterConcepts;
  function closeSource(){$('sourceDialog').close();sourceButton?.focus({preventScroll:true});$('lessonFrame').contentWindow.scrollTo(0,sourceScroll);}
  $('closeSource').onclick=closeSource;$('sourceDialog').oncancel=e=>{e.preventDefault();closeSource();};
  async function source(ref,button){const match=/^([a-f0-9]{32}):([1-9]\d*)$/i.exec(ref);if(!match)return;sourceButton=button;sourceScroll=$('lessonFrame').contentWindow.scrollY;$('sourceTitle').textContent='原材料';$('sourceContent').textContent='正在读取';$('sourceDialog').showModal();try{const unit=await get(`${base}/sources/${match[1]}/${match[2]}`);$('sourceTitle').textContent=unit.document+' · '+unit.label;$('sourceContent').innerHTML=`<pre>${esc(unit.text)}</pre>`+(unit.original?.url?.startsWith('/api/documents/')?`<a href="${esc(unit.original.url)}" target="_blank" rel="noopener">打开课程原文件</a>`:'');}catch(e){$('sourceContent').textContent=e.message;}}
  $('lessonFrame').onload=()=>{
    const frame=$('lessonFrame'),win=frame.contentWindow,doc=frame.contentDocument;
    if(!frame.getAttribute('src')||doc.URL==='about:blank')return;
    ready=false;delete frame.dataset.ready;
    let count=0;
    const timer=setInterval(()=>{
      if(doc!==frame.contentDocument){clearInterval(timer);return;}
      if(!win.learnmarginReport){
        if(++count>300){clearInterval(timer);fail(new Error('讲义加载超时，请刷新或下载 PDF。'));}
        return;
      }
      clearInterval(timer);
      if(win.learnmarginReport.error){fail(new Error('讲义排版未完成，请下载 PDF 查看。'));return;}
      doc.documentElement.classList.add('embedded-reader');
      for(const b of doc.querySelectorAll('.web-source-button'))if(!/^[a-f0-9]{32}:[1-9]\d*$/i.test(b.dataset.sourceRef||''))b.remove();
      doc.addEventListener('click',e=>{const b=e.target.closest?.('.web-source-button');if(b){e.preventDefault();source(b.dataset.sourceRef,b);}});
      // Let embedded layout settle before restoring the anchor and listening to
      // scroll. An old/blank frame's load or scroll cannot reset the new job.
      win.requestAnimationFrame(()=>{
        if(doc!==frame.contentDocument)return;
        ready=true;
        if(!$('readingScreen').hidden)jump();
        win.requestAnimationFrame(()=>{
          if(doc!==frame.contentDocument)return;
          trackReading(win,doc);frame.dataset.ready='true';
        });
      });
    },100);
  };
  async function loadLesson(id){const revision=++loadRevision;practice.reset();$('exerciseScreen').hidden=true;$('studyConcept').hidden=true;ready=false;delete $('lessonFrame').dataset.ready;selectedConcept=null;jobId=id;$('conceptTitle').textContent='内容总览';base='/api/handouts/'+encodeURIComponent(id);$('graphScreen').hidden=false;$('readingScreen').hidden=true;$('relationships').innerHTML='';$('conceptSources').innerHTML='';$('evidence').hidden=true;const [nextLesson,nextMap]=await Promise.all([get(base+'/artifacts/lesson.json'),get(base+'/artifacts/knowledge-map.json')]);if(revision!==loadRevision)return;lesson=nextLesson;map=nextMap;practice.sections=lesson.sections.map(s=>s.id);$('graphNotice').hidden=!map.notice;$('graphNotice').textContent=map.notice||'';$('title').textContent=lesson.title;$('definition').textContent=lesson.overview.summary;$('outline').innerHTML=lesson.sections.map((s,i)=>`<button data-section="section-${i+1}">${esc(s.title)}</button>`).join('');$('sectionLinks').innerHTML='<a href="#overview" data-section="overview">阅读内容总览</a>';$('conceptList').innerHTML=map.nodes.map(n=>`<button data-concept="${esc(n.id)}" aria-pressed="false">${esc(n.title)}</button>`).join('');$('search').value='';filterConcepts();$('pdfDownload').href=base+'/artifacts/lesson.pdf?'+query;$('pdfDownload').download='讲义.pdf';if(!network)network=new NetworkView($('graph'),select,id=>relation(Number(id.slice(1))));window.marginNetwork=network;await network.setData({nodes:map.nodes.map(n=>({id:n.id,data:{title:n.title},style:{size:24,fill:GraphEncoding.family(n.family_index??Math.max(0,lesson.sections.findIndex(s=>s.id===n.section_ids[0]))),labelFontSize:13}})),edges:map.edges.map((e,i)=>({id:'e'+i,source:e.source,target:e.target,data:{label:e.predicate},style:{endArrow:e.directed,opacity:.6}}))},true);if(revision!==loadRevision)return;$('graph').dataset.ready='true';pending='overview';try{pending=localStorage.getItem('pliac.margin.'+jobId)||'overview';}catch{}if(![...$('readingScreen').querySelectorAll('nav [data-section]')].some(button=>button.dataset.section===pending))pending='overview';markReading(pending);ready=false;$('lessonFrame').removeAttribute('src');$('lessonFrame').dataset.url=base+'/artifacts/lesson.html?'+query;}
  let polling,shown=null,activeJob=null;
  function writeLocation(){
    const url=new URL(location.href);
    for(const name of scopeFields){if(selection[name])url.searchParams.set(name,selection[name]);else url.searchParams.delete(name);}
    if(jobId)url.searchParams.set('job_id',jobId);else url.searchParams.delete('job_id');
    history.replaceState(null,'',url);
  }
  async function changeScope(value){
    selection=Object.fromEntries(scopeFields.map(k=>[k,value[k]||'']));
    jobId=null;preferredJob=null;shown=null;lesson=null;ready=false;loadRevision++;practice.reset();
    $('graphScreen').hidden=true;$('readingScreen').hidden=true;$('exerciseScreen').hidden=true;
    $('lessonFrame').removeAttribute('src');delete $('lessonFrame').dataset.ready;
    writeLocation();await refresh().catch(fail);
  }
  async function refresh(){
    const revision=++refreshRevision;
    const data=await get('/api/handouts?'+new URLSearchParams(selection));
    if(revision!==refreshRevision)return;
    scopeData=data.scope;selection=Object.fromEntries(scopeFields.map(k=>[k,data.scope[k]||'']));
    $('title').textContent=shown&&lesson?lesson.title:data.scope.title;
    $('scopeTitle').textContent=data.scope.kind==='course'?data.title:data.title+' / '+data.scope.title;
    $('parentScope').href=data.scope.parent_url;
    $('practiceLink').href='/learn?'+query+(selection.node_id?'&node_id='+encodeURIComponent(selection.node_id):'');
    $('practiceLink').textContent='课程学习记录';
    $('generate').hidden=!data.capabilities.generate_handouts;
    $('chapter').innerHTML='<option value="">整门课程</option>'+data.chapters.map(c=>`<option value="${esc(c.id)}">${esc(c.title)}</option>`).join('');
    $('chapter').value=selection.chapter_id;
    const chapter=data.chapters.find(c=>c.id===selection.chapter_id),sections=(chapter?.document_hierarchy?.nodes||[]).filter(n=>n.kind!=='book');
    $('sectionChoice').hidden=!sections.length;
    $('scopeSection').innerHTML='<option value="">整章</option>'+sections.map(n=>`<option value="${esc(n.id)}">${esc(n.title)}</option>`).join('');$('scopeSection').value=selection.section_id;
    $('scopeNode').innerHTML='<option value="">当前范围全部知识点</option>'+data.nodes.map(n=>`<option value="${esc(n.id)}">${esc(n.title)}</option>`).join('');$('scopeNode').value=selection.node_id;
    $('scopePrerequisites').hidden=!data.scope.prerequisites.length;
    $('scopePrerequisites').innerHTML='相关前置知识：'+data.scope.prerequisites.map(n=>`<a href="${esc(n.url)}">${esc(n.title)}</a>`).join('、');
    const stats=data.snapshot_summary;$('snapshotSummary').hidden=!stats||data.scope.kind!=='course';
    if(stats)$('snapshotSummary').textContent=`资料输入 ${stats.source_pages} 页 · ${stats.source_characters.toLocaleString()} 字符 · ${stats.candidate_nodes} 个候选术语 · ${stats.candidate_edges} 条候选关系。`;
    $('courseExperiments').innerHTML=(data.activities||[]).filter(item=>typeof item.href==='string'&&item.href.startsWith('/')&&!item.href.startsWith('//')).map(item=>`<a href="${esc(item.href)}?${query}">${esc(item.title)}</a>`).join('');
    const jobs=data.scope_jobs,active=jobs.find(j=>['queued','running'].includes(j.status)),latest=jobs[0];
    activeJob=active;$('cancelJob').hidden=!active;$('generate').disabled=!!active;
    $('jobStatus').textContent=active?active.stage+' · '+active.progress+'%':latest?.status==='failed'?latest.error:latest?.status==='cancelled'?'已取消':latest?.status==='completed'?'讲义 '+latest.page_count+' 页':'使用本范围已有资料';
    const completedJobs=jobs.filter(j=>j.status==='completed');
    const completed=completedJobs.find(j=>j.id===preferredJob)||completedJobs[0];
    $('versionChoice').hidden=completedJobs.length<2;
    $('unitVersion').innerHTML=completedJobs.map((j,i)=>`<option value="${j.id}">${esc(j.title)} · ${esc(j.created_at.slice(0,16))}${i===0?' · 最新':''}</option>`).join('');
    $('scopeEmpty').hidden=!!completed;
    for(const id of ['mapMode','readMode','exerciseMode'])$(id).disabled=!completed;
    if(completed){$('unitVersion').value=completed.id;if(shown!==completed.id){await loadLesson(completed.id);if(revision!==refreshRevision)return;shown=completed.id;$('mapMode').setAttribute('aria-pressed','true');$('readMode').setAttribute('aria-pressed','false');$('exerciseMode').setAttribute('aria-pressed','false');}writeLocation();}
    else{$('graphScreen').hidden=true;$('readingScreen').hidden=true;$('exerciseScreen').hidden=true;}
    clearTimeout(polling);if(active)polling=setTimeout(()=>refresh().catch(fail),2000);
  }
  $('unitVersion').onchange=()=>{preferredJob=$('unitVersion').value;refresh().catch(fail);};
  $('cancelJob').onclick=async()=>{if(!activeJob)return;try{const response=await fetch('/api/handouts/'+activeJob.id+'/cancel?'+query,{method:'POST'});if(!response.ok)throw new Error('取消未完成，请刷新后重试。');await refresh();}catch(e){fail(e);}};
  $('chapter').onchange=()=>changeScope({chapter_id:$('chapter').value});
  $('scopeSection').onchange=()=>changeScope({chapter_id:$('chapter').value,section_id:$('scopeSection').value});
  $('scopeNode').onchange=()=>changeScope({chapter_id:$('chapter').value,section_id:$('scopeSection').value,node_id:$('scopeNode').value});
  $('generate').onclick=async()=>{
    $('error').hidden=true;$('generate').disabled=true;
    const revision=refreshRevision;
    try{const r=await fetch('/api/handouts?'+query,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scope:selection})});const data=await r.json();if(!r.ok)throw new Error(data.detail||'生成未完成');if(revision!==refreshRevision)return;preferredJob=data.id;await refresh();}
    catch(e){fail(e);$('generate').disabled=false;}
  };
  refresh().catch(fail);
})();
