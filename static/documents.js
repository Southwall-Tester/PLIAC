(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const names={prerequisite:'前置',contains:'包含',related:'关联',confusable:'易混淆',cooccurs:'共现',structure:'包含'};
  const statusNames={queued:'排队中',parsing:'解析中',extracting:'提取中',completed:'已生成',partial:'部分完成',failed:'生成失败',cancelled:'已取消'};
  const activeStates=new Set(['queued','parsing','extracting']);
  let current=null,graph=null,shownSignature='',listSignature='',timer=null,loadToken=0,toastTimer=null,uploading=false,draftVersion=null;
  let structure=[],memberships=[],collapsed=new Set(),filterTimer=null;
  const network=new NetworkView($('graph'),selectNode,selectEdge,documentMenu);
  network.bindControls();
  new ResizeObserver(()=>document.documentElement.style.setProperty('--toolbar-height',`${document.querySelector('.toolbar').offsetHeight}px`)).observe(document.querySelector('.toolbar'));

  function updateToolbar(){
    const library=!$('libraryPanel').hidden,active=!!graph&&!library;
    const count=active?(network.data?.nodes.length||0):0;
    $('physicsSettings').hidden=count<2;$('stabilizeButton').hidden=count<2;$('labelsButton').hidden=!count;
    $('filtersButton').hidden=!active;$('statsButton').hidden=!active;
    $('hierarchyLevel').hidden=!active||structure.length<2;
    $('libraryButton').hidden=library;
    $('importButton').hidden=!active||!graph.nodes.length;$('importButton').disabled=$('importButton').hidden;
    $('exportButton').hidden=!active;$('exportButton').disabled=!active;
    $('canvasControls').hidden=!count;
    $('edgeLegend').hidden=!active||!network.data?.edges.length;
    $('encodingLegend').hidden=!count;$('graphCaption').hidden=library||!current;
    $('graph').style.visibility=library?'hidden':'';$('graph').inert=library;$('graph').setAttribute('aria-hidden',String(library));
    if(library){$('filtersPanel').hidden=true;$('sourcePanel').hidden=true;$('filtersButton').setAttribute('aria-expanded','false');$('jobPanel').hidden=true;}
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
    current=job;graph=null;shownSignature='';structure=[];memberships=[];collapsed.clear();remember(id);
    $('search').value='';$('relationFilter').value='all';$('hierarchyLevel').value='all';$('sourcePanel').hidden=true;
    $('libraryPanel').hidden=true;$('jobPanel').hidden=false;$('edgeLegend').hidden=true;$('graphCaption').textContent=job.title||job.filename;
    updateToolbar();
    await network.setData({nodes:[],edges:[]},true);updateJob();
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
    for(const n of graph.nodes||[])if(n.chapter_id&&!memberships.some(m=>m.node_id===n.id))memberships.push({node_id:n.id,parent_id:n.chapter_id});
  }
  async function loadGraph(token=loadToken){
    if(!current)return;const id=current.id;const next=await api(`/${encodeURIComponent(id)}/graph`);
    if(token!==loadToken||current?.id!==id)return;
    graph=next;readHierarchy();await render(true);updateJob();
    if(current.status==='completed'&&!current.error&&!(current.warnings||[]).length)$('jobPanel').hidden=true;
    updateToolbar();
  }
  function ancestorVisible(id){const item=structure.find(n=>n.id===id);if(!item)return true;let p=item.parent_id;const visited=new Set();while(p&&!visited.has(p)){if(collapsed.has(p))return false;visited.add(p);p=structure.find(n=>n.id===p)?.parent_id;}return true;}
  function visibleData(){
    if(!graph)return {nodes:[],edges:[]};const query=$('search').value.trim().toLocaleLowerCase(),relation=$('relationFilter').value;
    let concepts=(graph.nodes||[]).filter(n=>!query||`${n.title} ${n.description||''}`.toLocaleLowerCase().includes(query));
    const level=$('hierarchyLevel').value;
    concepts=concepts.filter(n=>{if(!structure.length)return true;if(level!=='all')return false;const parents=memberships.filter(m=>m.node_id===n.id).map(m=>m.parent_id);return !parents.length||parents.some(p=>!collapsed.has(p)&&ancestorVisible(p));});
    let containers=structure.filter(n=>ancestorVisible(n.id)&&(level!=='book'||!n.parent_id));
    if(query){const relevant=new Set(memberships.filter(m=>concepts.some(n=>n.id===m.node_id)).map(m=>m.parent_id));let size;do{size=relevant.size;structure.filter(n=>relevant.has(n.id)&&n.parent_id).forEach(n=>relevant.add(n.parent_id));}while(size!==relevant.size);containers=containers.filter(n=>relevant.has(n.id)||n.title.toLocaleLowerCase().includes(query));}
    const ids=new Set([...concepts,...containers].map(n=>n.id));
    const edges=(graph.edges||[]).filter(e=>ids.has(e.source)&&ids.has(e.target)&&(relation==='all'||e.type===relation));
    for(const n of containers)if(n.parent_id&&ids.has(n.parent_id))edges.push({id:`structure-${n.id}`,source:n.parent_id,target:n.id,type:'structure'});
    for(const m of memberships)if(ids.has(m.node_id)&&ids.has(m.parent_id))edges.push({id:`member-${m.parent_id}-${m.node_id}`,source:m.parent_id,target:m.node_id,type:'structure'});
    return {nodes:[...containers,...concepts],edges};
  }
  async function render(force=false){
    const data=visibleData();const signature=JSON.stringify([data.nodes.map(n=>n.id),data.edges.map(e=>e.id)]);
    $('nodeList').innerHTML=data.nodes.map(n=>`<button data-node="${escape(n.id)}">${escape(n.title)}</button>`).join('');
    $('nodeList').querySelectorAll('[data-node]').forEach(button=>button.onclick=()=>selectNode(button.dataset.node));
    $('filterCount').textContent=`${data.nodes.length} 个节点 · ${data.edges.length} 条关系`;
    if(!force&&signature===shownSignature)return;shownSignature=signature;
    const encoding=GraphEncoding.documentFamilies(structure,memberships);
    $('encodingLegend').hidden=false;
    $('colorLegend').innerHTML=encoding.families.map(f=>`<span data-family="${escape(f.id)}"><i style="background:${f.color}"></i>${escape(f.title)}</span>`).join('');
    await network.setData({nodes:data.nodes.map(n=>{const e=encoding.encoding(n.id),container=e.kind!=='concept';return {id:n.id,data:{title:n.title,family_id:e.family_id,family_title:e.family_title,kind:e.kind,depth:e.depth},style:{fill:e.fill,size:e.size,...(container?{lineWidth:2,labelFontWeight:600}:{})}};}),edges:data.edges.map(e=>({id:e.id,source:e.source,target:e.target,data:{label:names[e.type]||e.type},style:{endArrow:['prerequisite','contains','structure'].includes(e.type),lineDash:e.type==='cooccurs'?[4,4]:undefined,lineWidth:e.type==='structure'?1.5:1,opacity:e.type==='structure'?.3:.35}}))},true);
    updateToolbar();
  }
  function revealSource(){ $('sourcePanel').hidden=false;if(innerWidth<750){$('filtersPanel').hidden=true;$('filtersButton').setAttribute('aria-expanded','false');} }
  function renderEvidence(evidence=[]){return evidence.length?evidence.map(e=>`<section class="source-quote"><a class="quote-link" href="${escape(sourceURL(e.page))}" target="_blank" rel="noopener">第 ${escape(e.page)} ${current.page_kind==='pdf'?'页':'段'} ↗</a><blockquote>${escape(e.quote)}</blockquote></section>`).join(''):'<a class="quote-link" href="'+escape(sourceURL())+'" target="_blank" rel="noopener">打开资料 ↗</a>';}
  function selectNode(id){
    if(!graph)return;const container=structure.find(n=>n.id===id),n=container||graph.nodes.find(n=>n.id===id);if(!n)return;
    $('sourceTitle').textContent=n.title;
    if(container){const children=structure.filter(s=>s.parent_id===id),concepts=memberships.filter(m=>m.parent_id===id).map(m=>graph.nodes.find(n=>n.id===m.node_id)).filter(Boolean);
      $('sourceContent').innerHTML=`<div class="source-description">${children.length?`${children.length} 个章节 · `:''}${concepts.length} 个知识点</div>${renderEvidence(n.evidence||((n.page||n.start_page)?[{page:n.page||n.start_page,quote:n.title}]:[]))}<div class="node-list">${[...children,...concepts].map(child=>`<button data-child="${escape(child.id)}">${escape(child.title)}</button>`).join('')}</div>`;
      $('sourceContent').querySelectorAll('[data-child]').forEach(button=>button.onclick=()=>selectNode(button.dataset.child));
    }else $('sourceContent').innerHTML=`<p class="source-description">${escape(n.description||'')}</p>${renderEvidence(n.evidence)}`;
    revealSource();
  }
  function documentMenu(id,point){
    const container=structure.find(n=>n.id===id),item=container||graph?.nodes.find(n=>n.id===id);if(!item)return;
    const items=[{label:'查看详情',action:()=>selectNode(id)}];
    if(container){
      const before=new Set(visibleData().nodes.map(n=>n.id)),closed=collapsed.has(id)||$('hierarchyLevel').value!=='all',oldLevel=$('hierarchyLevel').value,wasCollapsed=collapsed.has(id);
      if(closed){collapsed.delete(id);$('hierarchyLevel').value='all';}else collapsed.add(id);
      const after=new Set(visibleData().nodes.map(n=>n.id)),count=closed?[...after].filter(n=>!before.has(n)).length:[...before].filter(n=>!after.has(n)).length;
      wasCollapsed?collapsed.add(id):collapsed.delete(id);$('hierarchyLevel').value=oldLevel;
      items.push({label:`${closed?'展开':'收起'}下级（${count}）`,action:()=>{if(closed){collapsed.delete(id);$('hierarchyLevel').value='all';}else collapsed.add(id);render(true).catch(e=>toast(e.message));}});
      items.push({label:'展开全部',action:()=>{collapsed.clear();$('hierarchyLevel').value='all';render(true).catch(e=>toast(e.message));}});
    }
    showGraphMenu(item.title,items,point);
  }
  function selectEdge(id){const e=graph?.edges.find(e=>e.id===id);if(!e)return;const from=graph.nodes.find(n=>n.id===e.source),to=graph.nodes.find(n=>n.id===e.target);$('sourceTitle').textContent=`${from?.title||e.source} → ${to?.title||e.target}`;$('sourceContent').innerHTML=`<div class="source-type">${escape(names[e.type]||e.type)}</div><p class="source-description">${escape(e.reason||'')}</p>${renderEvidence(e.evidence)}`;revealSource();}
  function updateStats(){const s=current?.stats||{};const items=[['页数',s.pages],['知识点',graph?.nodes?.length??s.nodes],['关系',graph?.edges?.length??s.edges],['章节',structure.filter(n=>n.parent_id).length],['文本片段',s.chunks],['OCR 页数',s.ocr_pages]];$('statsContent').innerHTML=`<div class="stat-grid">${items.map(([title,value])=>`<div><strong>${escape(value??0)}</strong><span>${title}</span></div>`).join('')}</div>`;}
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
  async function readDraftVersion(){const response=await fetch('/api/course-graph?view=draft');const data=await response.json();if(!response.ok)throw new Error(data.detail||'课程草稿读取失败。');draftVersion=data.graph.version;$('draftVersion').textContent=`课程草稿 v${draftVersion}`;}
  function updateImportCount(){const inputs=[...$('importNodes').querySelectorAll('input')],checked=inputs.filter(n=>n.checked).length;$('importCount').textContent=`已选 ${checked} / ${inputs.length}`;$('selectAll').checked=checked===inputs.length;$('selectAll').indeterminate=checked>0&&checked<inputs.length;$('confirmImport').disabled=!checked;}
  async function openImport(){if(!graph)return;showError('importError','');$('importNodes').innerHTML=graph.nodes.map(n=>`<label><input type="checkbox" value="${escape(n.id)}" checked/><span>${escape(n.title)}</span></label>`).join('');$('importNodes').querySelectorAll('input').forEach(input=>input.onchange=updateImportCount);updateImportCount();$('importDialog').showModal();$('confirmImport').disabled=true;try{await readDraftVersion();updateImportCount();}catch(error){showError('importError',error.message);}}
  $('confirmImport').onclick=()=>action($('confirmImport'),async()=>{showError('importError','');const ids=[...$('importNodes').querySelectorAll('input:checked')].map(n=>n.value);if(!ids.length)return;try{await api(`/${encodeURIComponent(current.id)}/import`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:draftVersion,node_ids:ids})});$('importDialog').close();toast('已加入课程草稿');}catch(error){if(error.status===409){await readDraftVersion();showError('importError','课程草稿已更新，请核对后重新加入。');}else showError('importError',error.message);}});
  $('selectAll').onchange=()=>{$('importNodes').querySelectorAll('input').forEach(input=>input.checked=$('selectAll').checked);updateImportCount();};
  $('uploadForm').onsubmit=e=>e.preventDefault();$('fileInput').onchange=e=>upload(e.target.files[0]);
  $('dropZone').onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();$('fileInput').click();}};
  for(const event of ['dragenter','dragover'])$('dropZone').addEventListener(event,e=>{e.preventDefault();$('dropZone').classList.add('drag-over');});
  for(const event of ['dragleave','drop'])$('dropZone').addEventListener(event,e=>{e.preventDefault();$('dropZone').classList.remove('drag-over');});
  $('dropZone').addEventListener('drop',e=>{if(e.dataTransfer.files.length>1){showError('libraryError','每次拖入一本书籍。');return;}upload(e.dataTransfer.files[0]);});
  document.addEventListener('dragover',e=>e.preventDefault());document.addEventListener('drop',e=>e.preventDefault());
  $('libraryButton').onclick=openLibrary;$('closeLibrary').onclick=closeLibrary;
  $('filtersButton').onclick=()=>{$('filtersPanel').hidden=!$('filtersPanel').hidden;$('filtersButton').setAttribute('aria-expanded',String(!$('filtersPanel').hidden));if(innerWidth<750&&!$('filtersPanel').hidden)$('sourcePanel').hidden=true;};
  $('closeFilters').onclick=()=>{$('filtersPanel').hidden=true;$('filtersButton').setAttribute('aria-expanded','false');};$('closeSource').onclick=()=>$('sourcePanel').hidden=true;
  $('search').oninput=()=>{clearTimeout(filterTimer);filterTimer=setTimeout(()=>render().catch(error=>toast(error.message)),180);};$('relationFilter').onchange=()=>render().catch(error=>toast(error.message));
  $('hierarchyLevel').onchange=()=>{collapsed.clear();render(true).catch(error=>toast(error.message));};
  $('statsButton').onclick=()=>{updateStats();$('statsDialog').showModal();};
  document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>$(button.dataset.close).close());
  $('importButton').onclick=()=>openImport().catch(error=>toast(error.message));
  $('cancelButton').onclick=()=>action($('cancelButton'),async()=>{current=await api(`/${encodeURIComponent(current.id)}/cancel`,{method:'POST'});updateJob();});
  $('retryButton').onclick=()=>action($('retryButton'),async()=>{current=await api(`/${encodeURIComponent(current.id)}/retry`,{method:'POST'});updateJob();schedulePoll();});
  $('hideJobButton').onclick=()=>$('jobPanel').hidden=true;$('viewResultButton').onclick=()=>loadGraph().catch(error=>toast(error.message));
  $('exportButton').onclick=()=>{if(!graph)return;const blob=new Blob([JSON.stringify(graph,null,2)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${current.title||'资料图谱'}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  let saved='';try{saved=localStorage.getItem('pliac-document-id')||'';}catch{}
  const initial=new URL(location.href).searchParams.get('id')||saved;
  updateToolbar();
  refreshList().catch(error=>showError('libraryError',error.message));
  if(initial)loadDocument(initial).catch(error=>{remember('');showError('libraryError',error.message);$('libraryPanel').hidden=false;updateToolbar();});else schedulePoll();
})();
