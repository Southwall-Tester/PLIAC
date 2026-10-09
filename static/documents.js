(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const names={prerequisite:'前置',contains:'包含',related:'关联',confusable:'易混淆',cooccurs:'共现',structure:'包含'};
  const statusNames={queued:'排队中',parsing:'解析中',extracting:'提取中',completed:'已生成',partial:'部分完成',failed:'生成失败',cancelled:'已取消'};
  const activeStates=new Set(['queued','parsing','extracting']);
  const pageParams=new URL(location.href).searchParams;
  let targetCourseId=pageParams.get('course_id')||'',courseChoices=[],draftRequest=0;
  let current=null,graph=null,shownSignature='',listSignature='',timer=null,loadToken=0,toastTimer=null,uploading=false,draftVersion=null;
  let structure=[],memberships=[],collapsed=new Set(),filterTimer=null,encoding=null;
  let structureById=new Map(),nodeById=new Map(),childrenByParent=new Map(),parentsByConcept=new Map(),conceptsByParent=new Map();
  let searchText=new Map(),allEdges=[],edgeById=new Map(),drawnNodes=new Map(),drawnEdges=new Map();
  let listedNodes=[],nodeListSignature='',renderTask=null,renderAgain=false;
  let subgraphs=null,subgraphId='',requestedSubgraph='',scopeRequest=0,cameras=new Map();
  const network=new NetworkView($('graph'),selectNode,selectEdge,documentMenu);
  network.bindControls();
  new ResizeObserver(()=>document.documentElement.style.setProperty('--toolbar-height',`${document.querySelector('.toolbar').offsetHeight}px`)).observe(document.querySelector('.toolbar'));

  function closeChapters(){ $('chaptersPanel').hidden=true;$('chaptersButton').setAttribute('aria-expanded','false'); }
  function rememberSubgraph(){
    if(!current)return;
    requestedSubgraph=subgraphId;
    const url=new URL(location.href);
    if(subgraphId)url.searchParams.set('chapter',subgraphId);else url.searchParams.delete('chapter');
    history.replaceState({},'',url);
    try{localStorage.setItem(`pliac-document-subgraph.${current.id}`,subgraphId);}catch{}
    $('graphCaption').textContent=subgraphId?`${current.title} / ${structureById.get(subgraphId).title}`:current.title||current.filename;
    $('exportButton').textContent=subgraphId?'导出子图':'导出';
  }
  function markChapter(){
    for(const button of $('subgraphList').querySelectorAll('[data-subgraph]')){
      const active=button.dataset.subgraph===subgraphId;
      button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));
      if(active)for(let parent=button.parentElement;parent&&parent!==$('subgraphList');parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
    }
  }
  function renderChapters(){
    function branch(item){return `<div class="subgraph-branch"><button class="subgraph-choice" data-subgraph="${escape(item.id)}"><span>${escape(item.title)}</span><small>${item.count}</small></button>${item.children.length?`<details class="subgraph-sections"><summary>小节（${item.children.length}）</summary>${item.children.map(branch).join('')}</details>`:''}</div>`;}
    $('subgraphList').innerHTML=`<button class="subgraph-choice" data-subgraph=""><span>全部章节</span><small>${graph.nodes.length}</small></button>${subgraphs.tree.map(branch).join('')}`;
    markChapter();
  }
  async function switchSubgraph(id){
    if(!graph||(id&&!subgraphs.scope(id))||id===subgraphId)return;
    const request=++scopeRequest;
    if(!renderTask&&network.data?.nodes.length)cameras.set(subgraphId,{zoom:network.graph.getZoom(),origin:network.graph.getViewportByCanvas([0,0])});
    subgraphId=id;collapsed.clear();$('search').value='';$('relationFilter').value='all';$('hierarchyLevel').value='all';$('sourcePanel').hidden=true;
    rememberSubgraph();markChapter();if(innerWidth<750)closeChapters();
    await render();
    await network.enqueue(async()=>{
      if(request!==scopeRequest)return;
      const camera=cameras.get(id);
      if(camera){await network.graph.zoomTo(camera.zoom);const now=network.graph.getViewportByCanvas([0,0]);await network.graph.translateBy([camera.origin[0]-now[0],camera.origin[1]-now[1]]);}
      else await network.fit();
    });
  }

  function updateToolbar(){
    const library=!$('libraryPanel').hidden,active=!!graph&&!library;
    const count=active?(network.data?.nodes.length||0):0;
    $('physicsSettings').hidden=count<2;$('stabilizeButton').hidden=count<2;$('labelsButton').hidden=!count;
    $('filtersButton').hidden=!active;$('statsButton').hidden=!active;
    $('hierarchyLevel').hidden=!active||structure.length<2;
    $('chaptersButton').hidden=!active||!subgraphs?.tree.length;
    $('wholeGraphButton').hidden=!active||!subgraphId;
    $('libraryButton').hidden=library;
    $('importButton').hidden=!active||!graph.nodes.length;$('importButton').disabled=$('importButton').hidden;
    $('exportButton').hidden=!active;$('exportButton').disabled=!active;
    $('canvasControls').hidden=!count;
    $('edgeLegend').hidden=!active||!network.data?.edges.length;
    $('encodingLegend').hidden=!count;$('graphCaption').hidden=library||!current;
    $('graph').style.visibility=library?'hidden':'';$('graph').inert=library;$('graph').setAttribute('aria-hidden',String(library));
    if(library){$('filtersPanel').hidden=true;$('sourcePanel').hidden=true;closeChapters();$('filtersButton').setAttribute('aria-expanded','false');$('jobPanel').hidden=true;}
  }

  function toast(message){const dialog=document.querySelector('dialog[open]');(dialog||document.body).appendChild($('toast'));$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,5500);}
  function showError(id,message){$(id).textContent=message||'';$(id).hidden=!message;}
  async function api(path='',options={}){
    let response;try{response=await fetch(`/api/documents${path}`,options);}catch{throw new Error('连接中断，请检查本地服务。');}
    let data;try{data=await response.json();}catch{throw new Error('服务响应读取失败。');}
    if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:'操作失败，请重试。');error.status=response.status;throw error;}
    return data;
  }
  async function action(button,work){button.disabled=true;try{await work();}catch(error){toast(error.message);}finally{button.disabled=false;}}
  function remember(id){const url=new URL(location.href);if(id)url.searchParams.set('id',id);else url.searchParams.delete('id');history.replaceState({},'',url);try{localStorage.setItem('pliac-document-id',id||'');}catch{}}
  function sourceURL(page){return `/api/documents/${encodeURIComponent(current.id)}/source${page?`#page=${Number(page)}`:''}`;}
  function openLibrary(){ $('libraryPanel').hidden=false;$('closeLibrary').hidden=!current;updateToolbar();refreshList().catch(error=>showError('libraryError',error.message)); }
  function closeLibrary(){if(current){$('libraryPanel').hidden=true;updateJob();}}
  function showTargetCourse(){
    const course=courseChoices.find(c=>c.id===targetCourseId);
    $('activeCourseTitle').textContent=course?.title||'';$('editCourseLink').hidden=!course;
    if(course)$('editCourseLink').href='/author?'+new URLSearchParams({course_id:course.id});
  }
  async function readCourses(){
    const response=await fetch('/api/courses'),data=await response.json();if(!response.ok)throw new Error(data.detail||'课程列表读取失败。');
    courseChoices=data.courses||[];showTargetCourse();return courseChoices;
  }

  async function refreshList(){
    const data=await api();const docs=data.documents||[];const signature=JSON.stringify(docs.map(d=>[d.id,d.status,d.updated_at,d.stats]));
    if(signature===listSignature)return;listSignature=signature;
    $('documentList').innerHTML=docs.length?docs.map(d=>`<button class="document-row" data-document="${escape(d.id)}"><span><strong>${escape(d.title||d.filename)}</strong><small>${escape(d.stats?.nodes||0)} 个知识点 · ${escape(d.stats?.edges||0)} 条关系</small></span><span>${escape(statusNames[d.status]||d.status)}</span></button>`).join(''):'';
    $('documentList').querySelectorAll('[data-document]').forEach(button=>button.onclick=()=>loadDocument(button.dataset.document).catch(error=>toast(error.message)));
  }
  function updateJob(){
    if(!current)return;const active=activeStates.has(current.status),p=current.progress||{},stats=current.stats||{};
    $('jobTitle').textContent=current.title||current.filename;$('jobTitle').title=current.title||current.filename;
    const count=p.total?` ${p.current||0}/${p.total}`:'';
    $('jobStatus').textContent=`${statusNames[current.status]||current.status}${active?count:''}`;
    if(active&&!p.total)$('jobProgress').removeAttribute('value');else $('jobProgress').value=active?Math.min(100,100*(p.current||0)/p.total):100;
    $('jobProgress').hidden=!active;showError('jobError',current.error);
    $('jobWarnings').innerHTML=(current.warnings||[]).map(w=>`<p>${escape(typeof w==='string'?w:w.message||JSON.stringify(w))}</p>`).join('');
    $('cancelButton').hidden=!active;$('retryButton').hidden=!['failed','cancelled','partial'].includes(current.status);
    $('viewResultButton').hidden=!(stats.nodes>0)||!!graph;$('hideJobButton').hidden=active;
    $('closeLibrary').hidden=false;
    if(active||current.error||current.status==='partial'||current.status==='cancelled')$('jobPanel').hidden=false;
    updateStats();updateToolbar();
  }
  function schedulePoll(){clearTimeout(timer);timer=setTimeout(poll,2000);}
  async function poll(){
    try{
      if(current&&activeStates.has(current.status)){
        const id=current.id;const next=await api(`/${encodeURIComponent(id)}`);if(current?.id!==id)return;
        current=next;updateJob();
        if(!activeStates.has(next.status)&&(next.stats?.nodes>0||['completed','partial'].includes(next.status)))await loadGraph();
      }
      if(!$('libraryPanel').hidden)await refreshList();
    }catch(error){showError('jobError',error.message);$('jobPanel').hidden=false;}
    finally{schedulePoll();}
  }
  async function loadDocument(id){
    const token=++loadToken;const job=await api(`/${encodeURIComponent(id)}`);if(token!==loadToken)return;
    const params=new URL(location.href).searchParams;
    requestedSubgraph=params.get('id')===id?params.get('chapter'):null;
    if(requestedSubgraph===null)try{requestedSubgraph=localStorage.getItem(`pliac-document-subgraph.${id}`)||'';}catch{requestedSubgraph='';}
    subgraphId='';subgraphs=null;cameras.clear();scopeRequest++;closeChapters();
    current=job;graph=null;shownSignature='';structure=[];memberships=[];listedNodes=[];nodeListSignature='';collapsed.clear();remember(id);
    $('search').value='';$('relationFilter').value='all';$('hierarchyLevel').value='all';$('sourcePanel').hidden=true;
    $('libraryPanel').hidden=true;$('jobPanel').hidden=false;$('edgeLegend').hidden=true;$('graphCaption').textContent=job.title||job.filename;
    updateToolbar();
    await network.clearLayout();await network.setData({nodes:[],edges:[]},true);updateJob();
    if(job.stats?.nodes>0||['completed','partial'].includes(job.status))await loadGraph(token);
    schedulePoll();
  }
  // Accept explicit structural nodes separately from extracted semantic relations.
  function readHierarchy(){
    const hierarchy=graph.hierarchy||{};
    structure=Array.isArray(hierarchy)?hierarchy:(hierarchy.nodes||[]);
    if(!structure.length&&hierarchy.root){structure=[hierarchy.root,...(hierarchy.chapters||[])];}
    structure=structure.map(n=>({...n,id:String(n.id),title:n.title||n.label||n.name,parent_id:n.parent_id||n.parent||null,kind:n.kind||n.type||'chapter'}));
    const raw=graph.memberships||hierarchy.memberships||[];
    memberships=Array.isArray(raw)?raw.map(m=>({node_id:m.node_id||m.concept_id||m.target,parent_id:m.parent_id||m.chapter_id||m.source})):Object.entries(raw).flatMap(([node,parents])=>(Array.isArray(parents)?parents:[parents]).map(parent=>({node_id:node,parent_id:parent})));
    const assigned=new Set(memberships.map(m=>m.node_id));
    for(const n of graph.nodes||[])if(n.chapter_id&&!assigned.has(n.id))memberships.push({node_id:n.id,parent_id:n.chapter_id});
    if(GraphEncoding.collapseTextSections){
      const normalized=GraphEncoding.collapseTextSections({nodes:structure,memberships:memberships.map(m=>({source:m.parent_id,target:m.node_id}))});
      structure=normalized.nodes;memberships=normalized.memberships.map(m=>({parent_id:m.source,node_id:m.target}));
    }
    encoding=GraphEncoding.documentFamilies(structure,memberships);
    structureById=new Map(structure.map(n=>[n.id,n]));nodeById=new Map([...(graph.nodes||[]),...structure].map(n=>[n.id,n]));
    childrenByParent=new Map();parentsByConcept=new Map();conceptsByParent=new Map();
    const append=(map,key,value)=>{if(!map.has(key))map.set(key,[]);map.get(key).push(value);};
    for(const n of structure)append(childrenByParent,n.parent_id,n);
    for(const m of memberships){append(parentsByConcept,m.node_id,m.parent_id);const n=nodeById.get(m.node_id);if(n)append(conceptsByParent,m.parent_id,n);}
    searchText=new Map([...nodeById].map(([id,n])=>[id,`${n.title} ${structureById.has(id)?'':n.description||''}`.toLocaleLowerCase()]));
    allEdges=[...(graph.edges||[]),...structure.filter(n=>n.parent_id).map(n=>({id:`structure-${n.id}`,source:n.parent_id,target:n.id,type:'structure'})),...memberships.map(m=>({id:`member-${m.parent_id}-${m.node_id}`,source:m.parent_id,target:m.node_id,type:'structure'}))];
    edgeById=new Map(allEdges.map(e=>[e.id,e]));
    subgraphs=DocumentSubgraphs.create(graph,structure,memberships);
    subgraphId=subgraphs.scope(requestedSubgraph)?requestedSubgraph:'';
    rememberSubgraph();renderChapters();
    drawnNodes=new Map([...nodeById].map(([id,n])=>{const e=encoding.encoding(id);return [id,{id,data:{title:n.title,family_id:e.family_id,family_title:e.family_title,kind:e.kind,depth:e.depth},style:{fill:e.fill,size:e.size,...(e.kind!=='concept'?{lineWidth:2,labelFontWeight:600}:{})}}];}));
    drawnEdges=new Map(allEdges.map(e=>[e.id,{id:e.id,source:e.source,target:e.target,data:{label:names[e.type]||e.type,type:e.type},style:{endArrow:['prerequisite','contains','structure'].includes(e.type),lineDash:e.type==='cooccurs'?[4,4]:undefined,lineWidth:e.type==='structure'?1.5:1,opacity:e.type==='structure'?.3:.35}}]));
    shownSignature='';nodeListSignature='';
    $('colorLegend').innerHTML=encoding.families.map(f=>`<span data-family="${escape(f.id)}"><i style="background:${f.color}"></i>${escape(f.title)}</span>`).join('');
  }
  async function loadGraph(token=loadToken){
    if(!current)return;const id=current.id;const next=await api(`/${encodeURIComponent(id)}/graph`);
    if(token!==loadToken||current?.id!==id)return;
    graph=next;readHierarchy();await render(true);updateJob();
    if(current.status==='completed'&&!current.error&&!(current.warnings||[]).length)$('jobPanel').hidden=true;
    updateToolbar();
  }
  function ancestorVisible(id,memo){
    let current=structureById.get(id),visible=true;const path=[],seen=new Set();
    while(current?.parent_id&&!seen.has(current.id)){
      if(current.id===subgraphId)break;
      if(memo.has(current.id)){visible=memo.get(current.id);break;}
      seen.add(current.id);path.push(current.id);
      if(collapsed.has(current.parent_id)){visible=false;break;}current=structureById.get(current.parent_id);
    }
    for(const member of path)memo.set(member,visible);memo.set(id,visible);return visible;
  }
  function visibleNodes(){
    if(!graph)return [];const query=$('search').value.trim().toLocaleLowerCase(),visibility=new Map();
    const scope=subgraphs?.scope(subgraphId);
    let concepts=(graph.nodes||[]).filter(n=>(!scope||scope.concepts.has(n.id))&&(!query||searchText.get(n.id).includes(query)));
    const level=$('hierarchyLevel').value;
    concepts=concepts.filter(n=>{if(!structure.length)return true;if(level!=='all')return false;const parents=parentsByConcept.get(n.id)||[];return !parents.length||parents.some(p=>(!scope||scope.containers.has(p))&&!collapsed.has(p)&&ancestorVisible(p,visibility));});
    let containers=structure.filter(n=>(!scope||scope.containers.has(n.id))&&ancestorVisible(n.id,visibility)&&(level!=='book'||(subgraphId?n.id===subgraphId:!n.parent_id)));
    if(query){
      const relevant=new Set();for(const n of concepts)for(const parent of parentsByConcept.get(n.id)||[]){let id=parent;while(id&&!relevant.has(id)){relevant.add(id);id=structureById.get(id)?.parent_id;}}
      containers=containers.filter(n=>relevant.has(n.id)||searchText.get(n.id).trim().includes(query));
    }
    return [...containers,...concepts];
  }
  function visibleData(){
    const nodes=visibleNodes(),ids=new Set(nodes.map(n=>n.id)),relation=$('relationFilter').value;
    return {nodes,edges:allEdges.filter(e=>ids.has(e.source)&&ids.has(e.target)&&(e.type==='structure'||relation==='all'||e.type===relation))};
  }
  function renderNodeList(){
    if($('filtersPanel').hidden)return;const signature=JSON.stringify(listedNodes.map(n=>n.id));if(signature===nodeListSignature)return;
    nodeListSignature=signature;$('nodeList').innerHTML=listedNodes.map(n=>`<button data-node="${escape(n.id)}">${escape(n.title)}</button>`).join('');
  }
  async function renderCurrent(){
    const data=visibleData();const signature=JSON.stringify([data.nodes.map(n=>n.id),data.edges.map(e=>e.id)]);
    listedNodes=data.nodes;renderNodeList();
    $('filterCount').textContent=`${data.nodes.length} 个节点 · ${data.edges.length} 条关系`;
    if(signature===shownSignature)return;shownSignature=signature;
    $('encodingLegend').hidden=false;
    try{await network.setData({nodes:data.nodes.map(n=>drawnNodes.get(n.id)),edges:data.edges.map(e=>drawnEdges.get(e.id))},true);}catch(error){shownSignature='';throw error;}
    updateToolbar();
  }
  function render(){
    renderAgain=true;if(renderTask)return renderTask;
    renderTask=(async()=>{try{do{renderAgain=false;await renderCurrent();}while(renderAgain);}finally{renderTask=null;}})();return renderTask;
  }
  function revealSource(){ $('sourcePanel').hidden=false;if(innerWidth<750){$('filtersPanel').hidden=true;closeChapters();$('filtersButton').setAttribute('aria-expanded','false');} }
  function renderEvidence(evidence=[]){return evidence.length?evidence.map(e=>`<section class="source-quote"><a class="quote-link" href="${escape(sourceURL(e.page))}" target="_blank" rel="noopener">第 ${escape(e.page)} ${current.page_kind==='pdf'?'页':'段'} ↗</a><blockquote>${escape(e.quote)}</blockquote></section>`).join(''):'<a class="quote-link" href="'+escape(sourceURL())+'" target="_blank" rel="noopener">打开资料 ↗</a>';}
  function selectNode(id){
    if(!graph)return;const container=structureById.get(id),n=nodeById.get(id);if(!n)return;
    $('sourceTitle').textContent=n.title;
    if(container){const children=childrenByParent.get(id)||[],concepts=conceptsByParent.get(id)||[];
      $('sourceContent').innerHTML=`<div class="source-type">${container.kind==='book'?'资料':container.kind==='page'?'资料页':'章节'}</div><div class="source-description">${children.length?`${children.length} 个章节 · `:''}${concepts.length} 个知识点</div>${renderEvidence(n.evidence||((n.page||n.start_page)?[{page:n.page||n.start_page,quote:n.title}]:[]))}<div class="node-list">${[...children,...concepts].map(child=>`<button data-child="${escape(child.id)}">${escape(child.title)}</button>`).join('')}</div>`;
      $('sourceContent').querySelectorAll('[data-child]').forEach(button=>button.onclick=()=>selectNode(button.dataset.child));
      if(container.kind!=='book'&&id!==subgraphId){const button=document.createElement('button');button.textContent='查看此章节子图';button.onclick=()=>switchSubgraph(id).catch(error=>toast(error.message));$('sourceContent').prepend(button);}
    }else{
      const parentIds=new Set(parentsByConcept.get(id)||[]),family=encoding.encoding(id);
      const others=structure.filter(s=>parentIds.has(s.id)&&s.id!==family.family_id);
      const shared=parentIds.size>1?`<div class="source-description">${family.family_title?`<div class="source-family">所属族群：${escape(family.family_title)}</div>`:''}${others.length?`<div class="source-occurrences">出现于：${others.map(s=>escape(s.title)).join('、')}</div>`:''}</div>`:'';
      $('sourceContent').innerHTML=`<div class="source-type">知识点</div>${shared}<p class="source-description">${escape(n.description||'')}</p>${renderEvidence(n.evidence)}`;
    }
    revealSource();
  }
  function documentMenu(id,point){
    const container=structureById.get(id),item=nodeById.get(id);if(!graph||!item)return;
    const items=[{label:'查看详情',action:()=>selectNode(id)}];
    if(container){
      if(container.kind!=='book'&&id!==subgraphId)items.push({label:'查看此章节子图',action:()=>switchSubgraph(id).catch(error=>toast(error.message))});
      const before=new Set(visibleNodes().map(n=>n.id)),closed=collapsed.has(id)||$('hierarchyLevel').value!=='all',oldLevel=$('hierarchyLevel').value,wasCollapsed=collapsed.has(id);
      if(closed){collapsed.delete(id);$('hierarchyLevel').value='all';}else collapsed.add(id);
      const after=new Set(visibleNodes().map(n=>n.id)),count=closed?[...after].filter(n=>!before.has(n)).length:[...before].filter(n=>!after.has(n)).length;
      wasCollapsed?collapsed.add(id):collapsed.delete(id);$('hierarchyLevel').value=oldLevel;
      items.push({label:`${closed?'展开':'收起'}下级（${count}）`,action:()=>{if(closed){collapsed.delete(id);$('hierarchyLevel').value='all';}else collapsed.add(id);render(true).catch(e=>toast(e.message));}});
      items.push({label:'展开全部',action:()=>{collapsed.clear();$('hierarchyLevel').value='all';render(true).catch(e=>toast(e.message));}});
    }
    showGraphMenu(item.title,items,point);
  }
  function selectEdge(id){
    if(!graph)return;const e=edgeById.get(id);if(!e)return;
    const from=nodeById.get(e.source)?.title||e.source,to=nodeById.get(e.target)?.title||e.target;
    const directed=['prerequisite','contains','structure'].includes(e.type);
    const meaning=e.type==='prerequisite'?`${from} 是 ${to} 的前置知识。`:['contains','structure'].includes(e.type)?`${from} 包含 ${to}。`:e.type==='confusable'?`${from} 与 ${to} 容易混淆。`:e.type==='cooccurs'?`${from} 与 ${to} 在原文中共同出现。`:`${from} 与 ${to} 相关。`;
    $('sourceTitle').textContent=`${from} ${directed?'→':'—'} ${to}`;
    $('sourceContent').innerHTML=`<div class="source-type">${escape(names[e.type]||e.type)}</div><p class="source-description">${escape(meaning)}</p>${e.reason?`<p class="source-description">${escape(e.reason)}</p>`:''}${e.type==='structure'?'':renderEvidence(e.evidence)}`;revealSource();
  }
  function updateStats(force=false){if(!force&&!$('statsDialog').open)return;const s=current?.stats||{};const items=[['页数',s.pages],['知识点',graph?.nodes?.length??s.nodes],['关系',graph?.edges?.length??s.edges],['章节',structure.length-(childrenByParent.get(null)?.length||0)],['文本片段',s.chunks],['OCR 页数',s.ocr_pages]];$('statsContent').innerHTML=`<div class="stat-grid">${items.map(([title,value])=>`<div><strong>${escape(value??0)}</strong><span>${title}</span></div>`).join('')}</div>`;}
  async function upload(file){
    if(uploading)return;if(!file)return;
    if(!/\.(pdf|docx|txt|md)$/i.test(file.name)){showError('libraryError','请选择 PDF、DOCX、TXT 或 Markdown 文件。');return;}
    const start=Number($('startPage').value),end=$('endPage').value?Number($('endPage').value):null;
    if(!Number.isInteger(start)||start<1||(end!==null&&(!Number.isInteger(end)||end<start))){showError('libraryError','请检查起始页和结束页。');return;}
    uploading=true;$('fileInput').disabled=true;$('uploadProgress').hidden=false;$('uploadMeter').value=0;$('uploadStatus').textContent='正在上传…';showError('libraryError','');
    try{
      const data=new FormData();data.append('file',file);data.append('engine',$('engine').value);data.append('start_page',String(start));if(end!==null)data.append('end_page',String(end));
      const job=await new Promise((resolve,reject)=>{const request=new XMLHttpRequest();request.open('POST','/api/documents/upload');request.upload.onprogress=e=>{if(e.lengthComputable){$('uploadMeter').value=100*e.loaded/e.total;$('uploadStatus').textContent=e.loaded===e.total?'正在建立任务…':`上传 ${Math.round(100*e.loaded/e.total)}%`;}};request.onerror=()=>reject(new Error('上传中断，请重试。'));request.onload=()=>{let result;try{result=JSON.parse(request.responseText);}catch{reject(new Error('上传响应读取失败。'));return;}if(request.status>=200&&request.status<300)resolve(result);else reject(new Error(typeof result.detail==='string'?result.detail:'上传失败，请重试。'));};request.send(data);});
      await loadDocument(job.id);await refreshList();
    }catch(error){showError('libraryError',error.message);$('libraryPanel').hidden=false;}
    finally{uploading=false;$('fileInput').disabled=false;$('fileInput').value='';$('uploadProgress').hidden=true;updateToolbar();}
  }
  async function readDraftVersion(){
    const token=++draftRequest,id=targetCourseId;draftVersion=null;$('draftVersion').textContent='';updateImportCount();
    if(!id)throw new Error('请选择目标课程。');
    const response=await fetch('/api/course-graph?'+new URLSearchParams({view:'draft',course_id:id}));const data=await response.json();
    if(token!==draftRequest||id!==targetCourseId)return;
    if(!response.ok)throw new Error(data.detail||'课程草稿读取失败。');draftVersion=data.graph.version;$('draftVersion').textContent=`草稿 v${draftVersion}`;updateImportCount();
  }
  function updateImportCount(){const inputs=[...$('importNodes').querySelectorAll('input')],checked=inputs.filter(n=>n.checked).length;$('importCount').textContent=`已选 ${checked} / ${inputs.length}`;$('selectAll').checked=checked===inputs.length;$('selectAll').indeterminate=checked>0&&checked<inputs.length;$('confirmImport').disabled=!checked||draftVersion===null||!targetCourseId;}
  async function openImport(){
    if(!graph)return;showError('importError','');draftVersion=null;$('targetCourse').innerHTML='';$('targetCourse').disabled=true;
    $('importNodes').innerHTML=subgraphs.exportGraph(subgraphId).nodes.map(n=>`<label><input type="checkbox" value="${escape(n.id)}" checked/><span>${escape(n.title)}</span></label>`).join('');$('importNodes').querySelectorAll('input').forEach(input=>input.onchange=updateImportCount);updateImportCount();$('importDialog').showModal();
    try{
      await readCourses();
      if(!targetCourseId)targetCourseId=courseChoices.find(c=>c.is_default||c.id==='ml_classification')?.id||'';
      $('targetCourse').innerHTML=`<option value="">选择课程</option>`+courseChoices.map(c=>`<option value="${escape(c.id)}">${escape(c.title)}</option>`).join('');
      $('targetCourse').value=targetCourseId;
      if(!$('targetCourse').value){targetCourseId='';throw new Error('请选择目标课程。');}
      showTargetCourse();await readDraftVersion();
    }catch(error){showError('importError',error.message);}finally{$('targetCourse').disabled=false;updateImportCount();}
  }
  $('targetCourse').onchange=async()=>{
    targetCourseId=$('targetCourse').value;showError('importError','');showTargetCourse();
    const url=new URL(location.href);if(targetCourseId)url.searchParams.set('course_id',targetCourseId);else url.searchParams.delete('course_id');history.replaceState({},'',url);
    try{await readDraftVersion();}catch(error){showError('importError',error.message);}
  };
  $('confirmImport').onclick=async()=>{
    const ids=[...$('importNodes').querySelectorAll('input:checked')].map(n=>n.value);if(!ids.length||draftVersion===null||!targetCourseId)return;
    $('confirmImport').disabled=true;$('targetCourse').disabled=true;showError('importError','');
    try{
      await api(`/${encodeURIComponent(current.id)}/import`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:draftVersion,node_ids:ids,course_id:targetCourseId})});
      $('importDialog').close();showTargetCourse();toast('已加入课程草稿');
    }catch(error){if(error.status===409){try{await readDraftVersion();showError('importError','课程草稿已更新，请核对后重新加入。');}catch(failure){showError('importError',failure.message);}}else showError('importError',error.message);}
    finally{$('targetCourse').disabled=false;updateImportCount();}
  };
  $('selectAll').onchange=()=>{$('importNodes').querySelectorAll('input').forEach(input=>input.checked=$('selectAll').checked);updateImportCount();};
  $('uploadForm').onsubmit=e=>e.preventDefault();$('fileInput').onchange=e=>upload(e.target.files[0]);
  $('dropZone').onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();$('fileInput').click();}};
  for(const event of ['dragenter','dragover'])$('dropZone').addEventListener(event,e=>{e.preventDefault();$('dropZone').classList.add('drag-over');});
  for(const event of ['dragleave','drop'])$('dropZone').addEventListener(event,e=>{e.preventDefault();$('dropZone').classList.remove('drag-over');});
  $('dropZone').addEventListener('drop',e=>{if(e.dataTransfer.files.length>1){showError('libraryError','每次拖入一本书籍。');return;}upload(e.dataTransfer.files[0]);});
  document.addEventListener('dragover',e=>e.preventDefault());document.addEventListener('drop',e=>e.preventDefault());
  $('libraryButton').onclick=openLibrary;$('closeLibrary').onclick=closeLibrary;
  $('filtersButton').onclick=()=>{closeChapters();$('filtersPanel').hidden=!$('filtersPanel').hidden;renderNodeList();$('filtersButton').setAttribute('aria-expanded',String(!$('filtersPanel').hidden));if(innerWidth<750&&!$('filtersPanel').hidden)$('sourcePanel').hidden=true;};
  $('chaptersButton').onclick=()=>{const open=$('chaptersPanel').hidden;$('chaptersPanel').hidden=!open;$('chaptersButton').setAttribute('aria-expanded',String(open));if(open){$('filtersPanel').hidden=true;$('filtersButton').setAttribute('aria-expanded','false');if(innerWidth<750)$('sourcePanel').hidden=true;}};
  $('closeChapters').onclick=closeChapters;
  $('wholeGraphButton').onclick=()=>switchSubgraph('').catch(error=>toast(error.message));
  $('subgraphList').onclick=event=>{const button=event.target.closest('[data-subgraph]');if(button)switchSubgraph(button.dataset.subgraph).catch(error=>toast(error.message));};
  $('nodeList').onclick=event=>{const button=event.target.closest('[data-node]');if(button)selectNode(button.dataset.node);};
  $('closeFilters').onclick=()=>{$('filtersPanel').hidden=true;$('filtersButton').setAttribute('aria-expanded','false');};$('closeSource').onclick=()=>$('sourcePanel').hidden=true;
  $('search').oninput=()=>{clearTimeout(filterTimer);filterTimer=setTimeout(()=>render().catch(error=>toast(error.message)),180);};$('relationFilter').onchange=()=>render().catch(error=>toast(error.message));
  $('hierarchyLevel').onchange=()=>{collapsed.clear();render(true).catch(error=>toast(error.message));};
  $('statsButton').onclick=()=>{updateStats(true);$('statsDialog').showModal();};
  document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>$(button.dataset.close).close());
  $('importButton').onclick=()=>openImport().catch(error=>toast(error.message));
  $('cancelButton').onclick=()=>action($('cancelButton'),async()=>{current=await api(`/${encodeURIComponent(current.id)}/cancel`,{method:'POST'});updateJob();});
  $('retryButton').onclick=()=>action($('retryButton'),async()=>{current=await api(`/${encodeURIComponent(current.id)}/retry`,{method:'POST'});updateJob();schedulePoll();});
  $('hideJobButton').onclick=()=>$('jobPanel').hidden=true;$('viewResultButton').onclick=()=>loadGraph().catch(error=>toast(error.message));
  $('exportButton').onclick=()=>{if(!graph)return;const value=subgraphs.exportGraph(subgraphId),blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${value.title||'资料图谱'}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  let saved='';try{saved=localStorage.getItem('pliac-document-id')||'';}catch{}
  const initial=pageParams.get('id')||(pageParams.get('new')==='1'?'':saved);
  if(targetCourseId)readCourses().catch(error=>showError('libraryError',error.message));
  updateToolbar();
  refreshList().catch(error=>showError('libraryError',error.message));
  if(initial)loadDocument(initial).catch(error=>{remember('');showError('libraryError',error.message);$('libraryPanel').hidden=false;updateToolbar();});else schedulePoll();
})();
