(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clone = value => structuredClone(value);
  const labels = {unknown:'尚未涉及', uncertain:'待核验', needs_review:'需要补学', mastered:'证据支持掌握'};
  const relations = {prerequisite:'前置', contains:'包含', related:'关联', confusable:'易混淆'};
  const origins = {learner_expression:'学习者实际表达',system_completion:'系统补全',model_inference:'模型推断'};
  const sourceTypes = {manual:'人工采录',dialog:'对话原话',quiz:'题目作答',practice:'实训操作',annotation:'不理解的标记',self_assessment:'学习者自评',technical:'技术异常'};
  const formats = {video:'讲解视频',lesson:'解读教案',case:'案例资料',practice:'情境式实训',course:'补充课程'};
  const colors = {unknown:['#f8fafc','#becbd7','#657b90'],uncertain:['#fff8e8','#d8b05c','#9c7524'],needs_review:['#fdf0ed','#d78d7c','#aa5140'],mastered:['#eef8f2','#6cae93','#277558']};
  const view = ['/author','/admin'].includes(location.pathname) ? 'draft' : 'published';
  let graph = null, learner = {}, summary = {}, publication = {}, student = '', selected = '', chapter = 'all', activeTab = 'detail', mode = 'node';
  let renderer, topology='', renderBusy=false, renderAgain=false, loadToken=0, detailToken=0, toastTimer, pathResult=null, extracted=null;
  let writeQueue = Promise.resolve();
  const node = id => graph?.nodes.find(n=>n.id===id);
  const state = id => view==='draft' ? 'unknown' : learner.states?.[id]?.status || 'unknown';
  const nodeState = id => learner.states?.[id] || {};
  const date = value => value ? new Date(value).toLocaleString('zh-CN') : '尚无记录';
  const badge = status => `<span class="state-badge ${esc(status)}"><i class="dot ${esc(status)}"></i>${labels[status]||labels.unknown}</span>`;
  const field = (id,label,value='',attributes='') => `<label>${label}<input id="${id}" value="${esc(value)}" ${attributes}/></label>`;
  function toast(message,error=false) {
    const parent=$('manager').open?$('manager'):$('profileDialog').open?$('profileDialog'):document.body;
    parent.appendChild($('toast')); $('toast').textContent=message; $('toast').className=`toast${error?' error':''}`; $('toast').hidden=false;
    clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,error?8000:4500);
  }
  async function api(path='',options={}) {
    let response;
    try { response=await fetch(`/api/course-graph${path}`,{...options,headers:{'Content-Type':'application/json',...options.headers}}); }
    catch { throw new Error('无法连接本地服务，请检查启动窗口。'); }
    let value; try{value=await response.json();}catch{throw new Error('服务返回了无法读取的数据。');}
    if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:JSON.stringify(value.detail||value));
    return value;
  }
  async function busy(button,work) {
    if(!button)return;
    const previous=button.textContent;button.disabled=true;
    try{return await work();}catch(error){toast(error.message,true);}finally{button.disabled=false;button.textContent=previous;}
  }
  function download(value,name) {
    const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  const query = extra => new URLSearchParams({view,student_id:student,...extra}).toString();
  function expressionRecords(){return (learner.evidence||[]).filter(e=>e.course_id===graph?.id&&e.course_version===graph?.version);}
  function expressionNodes(){
    const result=new Map();
    for(const e of expressionRecords())for(const id of [e.node_id,...(e.expressed_relations||[]).flatMap(r=>[r.source,r.target])]){
      if(!result.has(id)||e.origin==='learner_expression')result.set(id,e.origin);
    }return result;
  }
  function visibleNodes() {
    const q=$('search').value.trim().toLowerCase(), filter=$('statusFilter').value;
    const mapped=$('structureView').value==='expressions'?expressionNodes():null;
    return (graph?.nodes||[]).filter(n=>(!mapped||mapped.has(n.id))&&(chapter==='all'||n.chapter_id===chapter)&&(!q||[n.id,n.title,...n.aliases].join(' ').toLowerCase().includes(q))&&(filter==='all'||(filter==='due'?!!nodeState(n.id).due:state(n.id)===filter)));
  }
  function syncSelection() {
    if(!graph)return;
    if(chapter!=='all'&&!graph.chapters.some(c=>c.id===chapter))chapter='all';
    if(!visibleNodes().some(n=>n.id===selected))selected=visibleNodes()[0]?.id||'';
  }
  function updateStats() {
    $('viewLabel').textContent=view==='draft'?'教师草稿工作台 · v7 方案':'已发布课程 · 学习记录';
    $('authorView').classList.toggle('current',view==='draft');$('studentView').classList.toggle('current',view==='published');
    $('manageButton').hidden=view!=='draft';
    $('profileButton').hidden=view==='draft';$('profileInlineButton').hidden=view==='draft';
    $('structureView').disabled=view==='draft';
    $('nodeCount').textContent=graph?.nodes.length||'—';$('edgeCount').textContent=graph?.edges.length||'—';
    $('masteredCount').textContent=graph?graph.nodes.filter(n=>state(n.id)==='mastered').length:'—';
    $('dueCount').textContent=graph&&view==='published'?graph.nodes.filter(n=>nodeState(n.id).due).length:0;
    $('courseTitle').textContent=graph?.title||'监督学习（分类）';
    $('courseSubtitle').textContent=graph?`两个关联学习单元 · ${view==='draft'?'工作草稿':'课程发布'}版本 ${graph.version} · 四类知识关系`:'等待课程侧完成人工审核并发布';
    $('publicationNotice').className=`publication-notice ${view==='published'&&graph?'published':''}`;
    $('publicationNotice').textContent=view==='draft'?'当前为教师草稿预览。草稿编辑不会改变已发布课程；未经人工审核的内容不进入正式学习与资源推荐。':graph?`正在使用已发布版本 ${graph.version}。节点状态来自证据与诊断，到期掌握记录会安排复核。`:(publication.notice||'尚无已发布课程。');
    $('reviewBadge').textContent=view==='draft'?'草稿 · 待人工审核与发布':`已发布 v${graph?.version||''}`;
    $('learnerNote').textContent=view==='draft'?'草稿仅预览课程结构，不写入正式学习判断。':student?`已加载 ${student} · 状态与证据分别保存`:'输入稳定匿名编号，加载画像与学习位置。';
    $('studentId').disabled=view==='draft';document.querySelector('#studentForm button').disabled=view==='draft';
    $('resumeButton').hidden=view!=='published'||!student||!learner.profile?.current_position?.node_id;
  }
  function renderSidebar() {
    if(!graph)return;
    $('chapters').innerHTML=[...graph.chapters,{id:'all',title:'两单元总览'}].map((c,i)=>`<button class="chapter ${c.id===chapter?'active':''}" data-chapter="${esc(c.id)}"><span class="number">${c.id==='all'?'∑':i+1}</span><span class="chapter-name">${esc(c.title)}</span><small>${graph.nodes.filter(n=>c.id==='all'||n.chapter_id===c.id).length}</small></button>`).join('');
    $('chapters').querySelectorAll('button').forEach(b=>b.onclick=()=>{chapter=b.dataset.chapter;changeFilter();});
    const nodes=visibleNodes();$('listCount').textContent=nodes.length;
    $('nodeList').innerHTML=nodes.map(n=>`<button class="node-item ${n.id===selected?'active':''}" data-node="${esc(n.id)}"><i class="dot ${state(n.id)}"></i><span>${esc(n.title)}</span><span class="node-index">${esc(n.id.slice(-3))}</span></button>`).join('')||'<p class="empty">没有匹配的节点。</p>';
    $('nodeList').querySelectorAll('button').forEach(b=>b.onclick=()=>selectNode(b.dataset.node));
    $('viewTitle').textContent=chapter==='all'?'两单元知识总览':graph.chapters.find(c=>c.id===chapter)?.title||'';
    $('viewCount').textContent=`${nodes.length} 个知识点`;
  }
  function changeFilter(){pathResult=null;syncSelection();renderSidebar();renderDetail();renderGraph();}
  function selectNode(id,reveal=false,remember=true){
    if(!node(id))return;selected=id;pathResult=null;
    if(reveal){chapter=node(id).chapter_id;$('search').value='';$('statusFilter').value='all';}
    renderSidebar();renderDetail();renderGraph();
    if(remember&&student&&view==='published')savePosition().catch(error=>toast(`位置未保存：${error.message}`,true));
  }
  async function renderGraph(){
    if(!graph)return;if(renderBusy){renderAgain=true;return;}renderBusy=true;
    try{
      if(!window.G6?.Graph)throw new Error('图谱组件未加载，仍可通过左侧列表浏览。');
      const nodes=visibleNodes(),ids=new Set(nodes.map(n=>n.id)),filter=$('relationFilter').value;
      const isExpression=$('structureView').value==='expressions';
      const mapped=expressionNodes();
      const edges=isExpression?expressionRecords().flatMap(e=>(e.expressed_relations||[]).map((r,i)=>({id:`expressed_${e.id}_${i}`,source:r.source,target:r.target,type:'expressed',relation:r.relation,reason:r.quote,origin:e.origin,evidence_id:e.id}))).filter(e=>ids.has(e.source)&&ids.has(e.target)):graph.edges.filter(e=>ids.has(e.source)&&ids.has(e.target)&&(filter==='all'||e.type===filter));
      const nextTopology=JSON.stringify([nodes.map(n=>n.id),edges.map(e=>[e.id,e.source,e.target,e.type])]);
      const pathIds=new Set(pathResult?.steps?.map(s=>s.node_id)||[]);
      const data={nodes:nodes.map(n=>{const c=colors[state(n.id)],inferred=isExpression&&mapped.get(n.id)!=='learner_expression';return{id:n.id,data:{title:n.title+(inferred?`（${mapped.get(n.id)==='system_completion'?'补全':'推断'}）`:'')},style:{fill:c[0],stroke:n.id===selected?'#176b61':c[1],lineWidth:n.id===selected?2.5:1.2,lineDash:inferred?[4,3]:undefined,labelFill:c[2],opacity:(pathIds.size && !pathIds.has(n.id)) ? 0.4 : 1}};}),edges:edges.map(e=>({id:e.id,source:e.source,target:e.target,data:{reason:e.reason,origin:e.origin,relation:e.relation,evidence_id:e.evidence_id,type:e.type},style:{stroke:e.type==='expressed'?(e.origin==='learner_expression'?'#528a7c':'#b99568'):e.type==='confusable'?'#be9860':e.type==='contains'?'#89af9f':'#b1c2cf',lineDash:['related','confusable'].includes(e.type)||(e.type==='expressed'&&e.origin!=='learner_expression')?[5,4]:undefined,endArrow:['prerequisite','contains','expressed'].includes(e.type),opacity:.8}}))};
      const el=$('graph');
      if(!renderer){
        renderer=new G6.Graph({container:el,width:el.clientWidth,height:el.clientHeight,animation:false,padding:[30,25,60,25],autoFit:'view',zoomRange:[.15,3],data,layout:{type:'dagre',rankdir:'TB',nodesep:23,ranksep:35},node:{type:'rect',style:{size:[150,46],radius:8,labelText:d=>d.data.title,labelPlacement:'center',labelFontSize:12,labelFontFamily:'Microsoft YaHei, sans-serif',labelWordWrap:true,labelMaxWidth:138,labelMaxLines:2}},edge:{type:'cubic-vertical',style:{endArrowSize:5,lineWidth:1.2}},behaviors:['drag-canvas','zoom-canvas']});
        renderer.on('node:click',event=>selectNode(event.target.id));
        renderer.on('edge:click',event=>{
          const e=renderer.getEdgeData(event.target.id);if(!e?.data)return;
          if(e.data.type==='expressed'){
            const raw=learner.evidence.find(p=>p.id===e.data.evidence_id);if(raw){activeTab='evidence';selectNode(raw.node_id,false,false);}
            toast(`${origins[e.data.origin]} · ${e.data.relation}：${e.data.reason}（证据 ${e.data.evidence_id}）`);
          }else toast(`${relations[e.data.type]}：${e.data.reason}`);
        });
        new ResizeObserver(()=>{if(el.clientWidth&&el.clientHeight)renderer.setSize(el.clientWidth,el.clientHeight);}).observe(el);
      }else if(topology===nextTopology){renderer.updateNodeData(data.nodes);renderer.updateEdgeData(data.edges);}else renderer.setData(data);
      if(topology===nextTopology)await renderer.draw();else await renderer.render();topology=nextTopology;
      $('graphMessage').hidden=nodes.length>0;$('graphMessage').textContent=isExpression?'当前版本尚无匹配的表达记录。请先在参考结构中保存原话及其关系。':'没有匹配的知识点，请调整筛选条件。';
      document.querySelector('.graph-hint').textContent=isExpression?'当前课程版本 · 实线为实际表达，虚线为补全 / 推断；点击关系查看原话':'前置箭头：先学 → 后学 · 易混淆线不代表学习顺序';
    }catch(error){$('graphMessage').hidden=false;$('graphMessage').textContent=error.message;console.error(error);}
    finally{renderBusy=false;if(renderAgain){renderAgain=false;renderGraph();}}
  }
  function heading(n){return `<div class="node-kicker">${esc(graph.chapters.find(c=>c.id===n.chapter_id)?.title)} · ${esc(n.id)}</div><h2>${esc(n.title)}</h2>${view==='draft'?'<span class="notice-label">课程草稿预览</span>':badge(state(n.id))}${n.scope==='extension'?' <span class="notice-label">拓展知识</span>':''}`;}
  function bindJumps(){ $('detailContent').querySelectorAll('[data-jump]').forEach(b=>b.onclick=()=>selectNode(b.dataset.jump,true)); }
  function chips(ids,kind=''){return ids.map(id=>`<button class="chip ${kind}" data-jump="${esc(id)}">${esc(node(id)?.title||id)}</button>`).join('');}
  function resourceCard(r){
    const reviewed=r.review_status==='reviewed';
    return `<article class="resource-card"><h4>${esc(r.title)}</h4><p class="resource-meta">${esc(r.organization)} · ${formats[r.format]||esc(r.format)} · ${reviewed?'已人工审核':'待审核候选'}</p><p class="resource-meta">适用片段：${esc(r.applicable_segment)}</p><p class="resource-meta">前置要求：${(r.prerequisite_ids||[]).map(id=>esc(node(id)?.title||id)).join('、')||'无额外前置'}</p><p class="resource-meta">${esc(r.reason||'覆盖当前节点，可用于补充理解与后续核验。')}</p>${r.url?`<a class="learning-link" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer" data-resource="${esc(r.id)}">${view==='draft'?'查看候选原始资料':'选择并打开资料'} ↗</a>`:''}</article>`;
  }
  async function renderDetail(){
    const token=++detailToken,n=node(selected);
    document.querySelectorAll('.detail-tabs button').forEach(b=>{b.classList.toggle('active',b.dataset.tab===activeTab);b.setAttribute('aria-selected',String(b.dataset.tab===activeTab));});
    if(!n){$('detailContent').innerHTML='<p class="empty">选择知识点查看内容、证据与建议。</p>';return;}
    if(activeTab==='evidence'){renderEvidence(n);return;}if(activeTab==='path'){renderPath(n,token);return;}
    const before=graph.edges.filter(e=>e.type==='prerequisite'&&e.target===n.id).map(e=>e.source);
    const confused=graph.edges.filter(e=>e.type==='confusable'&&(e.source===n.id||e.target===n.id)).map(e=>e.source===n.id?e.target:e.source);
    const citations=n.source_ids.map(id=>graph.sources.find(s=>s.id===id)).filter(Boolean);
    const resources=(graph.resources||[]).filter(r=>r.node_ids.includes(n.id)&&(view==='draft'||r.review_status==='reviewed'));
    $('detailContent').innerHTML=`${heading(n)}<p class="description">${esc(n.description)}</p><section class="detail-section"><h3>学习目标</h3><ul>${n.objectives.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></section><section class="detail-section"><h3>前置知识</h3><div class="chips">${before.length?chips(before):'<p>没有额外先修节点。</p>'}</div></section>${confused.length?`<section class="detail-section"><h3>容易混淆</h3><div class="chips">${chips(confused,'confusable')}</div></section>`:''}<section class="detail-section misconception"><h3>典型误解</h3><p>${esc(n.misconception)}</p></section>${n.check_question?`<section class="detail-section"><h3>诊断问题</h3><p>${esc(n.check_question)}</p>${view==='draft'?`<details><summary class="muted">教师查看判据</summary><p>${esc(n.expected_answer||'')}</p><p class="evidence-ref">${esc(n.check_task?.id||'')} · ${esc(n.check_task?.version||'')}</p></details>`:'<p class="muted">先独立表达思路，再记录实际作答及提示程度。</p>'}</section>`:''}<section class="detail-section"><h3>节点学习材料</h3>${view==='draft'?'<p class="draft-help">以下内容为待审资产。官方来源核查不等于教师审核；未审核候选不会成为正式推荐。</p>':''}${['video','lesson','case','practice'].map(kind=>{const items=resources.filter(r=>r.format===kind||(kind==='lesson'&&r.format==='course'));return `<div class="material-group"><h4>${formats[kind]}</h4>${items.length?items.map(resourceCard).join(''):`<p class="empty-column">${view==='draft'?'尚未关联该类材料':'暂无已审核的该类材料'}</p>`}</div>`;}).join('')}${n.blueprint_ids?.length?`<p class="muted">关联统一实训骨架：${n.blueprint_ids.map(esc).join('、')}。骨架资产待审核，实训执行环境尚未接入。</p>`:''}</section><section class="detail-section"><h3>概念出处</h3>${citations.map(s=>s.url?`<a class="resource" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)} ↗</a>`:`<p>${esc(s.title)}</p>`).join('')}</section><div class="detail-actions"><button id="openEvidence" class="button primary">查看证据与判断</button><button id="openPath" class="button subtle">查看下一步</button></div>`;
    bindJumps();$('openEvidence').onclick=()=>{activeTab='evidence';renderDetail();};$('openPath').onclick=()=>{activeTab='path';renderDetail();};
    $('detailContent').querySelectorAll('[data-resource]').forEach(link=>link.onclick=()=>{
      if(view==='published'&&student)writeLearner('/resource-use',{node_id:n.id,resource_id:link.dataset.resource,course_version:graph.version}).catch(error=>toast(`资料已打开，选择记录未保存：${error.message}`,true));
    });
  }
  function writeLearner(path,payload,method='POST') {
    const who=student,generation=loadToken;
    const task=writeQueue.catch(()=>{}).then(async()=>{
      if(!who||who!==student||generation!==loadToken)throw new Error('当前学习记录已切换，请重新提交。');
      const result=await api(path,{method,body:JSON.stringify({...payload,student_id:who,expected_version:learner.version})});
      if(who===student&&generation===loadToken&&result.learner){learner=result.learner;if(result.summary)summary=result.summary;updateStats();renderSidebar();renderGraph();}
      return result;
    });
    writeQueue=task;return task;
  }
  function savePosition(){
    return writeLearner('/profile',{...learner.profile,current_position:{course_id:graph.id,course_version:graph.version,chapter_id:node(selected).chapter_id,node_id:selected,context_ref:`knowledge:${selected}`}},'PUT');
  }
  function readRecommendations(nodeId){
    const who=student,generation=loadToken;
    const task=writeQueue.catch(()=>{}).then(async()=>{
      if(who!==student||generation!==loadToken)throw new Error('学习记录已切换，请重新查看下一步。');
      const result=await api(`/recommendations?${query({node_id:nodeId})}`);
      if(who===student&&generation===loadToken&&result.learner){learner=result.learner;updateStats();}
      return result;
    });writeQueue=task;return task;
  }
  async function loadStudent(id,restore=false){
    const token=++loadToken,result=await api(`?${new URLSearchParams({student_id:view==='draft'?'':id,view})}`);
    if(token!==loadToken)return;
    graph=result.graph;learner=result.learner||{};summary=result.summary||{};publication=result.publication||{};student=view==='draft'?'':id;pathResult=null;
    if(view==='published')try{localStorage.setItem('learningAgent.student',id);}catch{}
    $('workbench').hidden=!graph;$('unpublished').hidden=!!graph;updateStats();
    if(!graph)return;
    if(!selected){chapter=graph.chapters[0]?.id||'all';selected=graph.nodes[0]?.id;}
    if(restore&&learner.profile?.current_position?.node_id&&node(learner.profile.current_position.node_id)){selected=learner.profile.current_position.node_id;chapter=node(selected).chapter_id;}
    syncSelection();renderSidebar();renderDetail();await renderGraph();
  }

  function renderEvidence(n){
    const ns=nodeState(n.id), proofs=(learner.evidence||[]).filter(e=>e.node_id===n.id).slice().reverse(), diagnoses=(learner.diagnoses||[]).filter(d=>d.node_id===n.id).slice().reverse();
    if(view==='draft'){$('detailContent').innerHTML=`${heading(n)}<p class="description">这里预览的是课程参考知识结构。学习者实际表达、系统补全和模型推断会在正式课程中分别记录。</p><div class="draft-help">草稿尚不参与学习者诊断。完成人工审核并发布后，在正式课程中录入原始证据和人工复核判断。</div><a class="button subtle" href="/">进入正式课程</a>`;return;}
    $('detailContent').innerHTML=`${heading(n)}<p class="state-explanation">${esc(ns.reason||'尚无可用于判断的学习证据。')}</p><p class="muted">最近支持掌握：${date(ns.last_mastered_at)}<br/>下次复测：${date(ns.due_at)}</p>${!student?'<div class="path-note">先加载稳定匿名编号，再记录证据。</div>':`
      <h3 class="mini-title">1. 保存原始证据</h3><form id="evidenceForm" class="form-stack">
      <label>来源身份<select id="evidenceOrigin">${Object.entries(origins).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label>
      <label>记录类型<select id="evidenceType">${Object.entries(sourceTypes).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label>
      <label>原话、实际作答或操作<textarea id="evidenceText" required maxlength="4000" rows="4" placeholder="保留原始表达，诊断解释放在下一步。"></textarea></label>
      <label>提示程度<select id="promptLevel"><option value="">未确认</option><option value="0">0 · 独立完成，无提示</option><option value="1">1 · 仅指出位置</option><option value="2">2 · 引导性问题</option><option value="3">3 · 相关概念提示</option><option value="4">4 · 关键要点提示</option></select></label>
      ${field('taskId','任务编号',n.check_task?.id||`review_${n.id}`,'required maxlength="64"')}${field('taskVersion','任务版本',n.check_task?.version||1,'type="number" min="1" required')}${field('turnId','对话轮次（可选）','','type="number" min="1"')}
      <details><summary class="muted">原话中的概念关系（可选，人工对应）</summary><p class="muted">只登记原话实际表达的关系，不照抄课程参考连线。来源身份沿用本条证据。</p><label>起点概念<select id="expressionSource">${options(graph.nodes,n.id)}</select></label><label>终点概念<select id="expressionTarget">${options(graph.nodes,graph.nodes.find(x=>x.id!==n.id)?.id)}</select></label>${field('expressionRelation','实际表达的关系','','maxlength="200" placeholder="例如：用于选择模型"')}<label>对应的逐字原话<textarea id="expressionQuote" rows="2" maxlength="4000" placeholder="必须逐字出现在上方原始证据中。"></textarea></label></details>
      <details><summary class="muted">实训骨架引用（来自实训时填写）</summary>${field('skeletonId','骨架编号','','maxlength="64"')}${field('skeletonVersion','骨架版本','','type="number" min="1"')}</details>
      <button class="button primary" type="submit">保存原始证据</button><p class="muted">保存表达不会直接判为掌握。系统补全、模型推断、自评和技术异常均有独立标记。</p></form>
      <hr class="section-divider"/><h3 class="mini-title">2. 人工诊断复核</h3>
      <form id="diagnosisForm" class="form-stack"><label>引用原始证据</label><div class="proof-list">${proofs.map(e=>`<label><input type="checkbox" name="proof" value="${esc(e.id)}"/><span>${esc(e.text.slice(0,95))}<br/><small>${origins[e.origin]||esc(e.origin)} · ${e.prompt_level===null?'提示未确认':`提示 ${e.prompt_level}`} · ${esc(e.id)}</small></span></label>`).join('')||'<p class="muted">尚无原始证据，先完成上一步。</p>'}</div>
      <label>本次判断<select id="diagnosisStatus"><option value="uncertain">待核验</option><option value="needs_review">需要补学</option><option value="mastered">证据支持掌握</option><option value="unknown">尚未涉及</option></select></label>
      <label>判断依据<textarea id="diagnosisBasis" rows="3" maxlength="4000" required placeholder="说明证据支持什么、仍有哪些不足以及后续如何核验。"></textarea></label>${field('diagnosisReviewer','实际复核人','','required maxlength="100"')}
      <label class="inline-check"><input id="isRetest" type="checkbox"/>本次是按计划进行的独立复测</label>
      <label>关联此前教学建议（可选）<select id="followUpAction"><option value="">普通诊断，不评价此前建议</option>${(learner.actions||[]).filter(a=>a.course_version===graph.version&&a.observed_evidence_ids&&(a.target_node_ids||[a.node_id]).includes(n.id)).slice().reverse().map(a=>`<option value="${esc(a.id)}">${esc(date(a.created_at))} · ${esc(a.follow_up||a.reason)}</option>`).join('')}</select></label><p class="muted">关联时只选建议之后的新任务作答。资料点击不代表学习效果；后续表现仍需人工复核。</p>
      ${diagnoses.length?`<details><summary class="muted">明确调和此前判断（存在冲突时填写）</summary><div class="proof-list">${diagnoses.map(d=>`<label><input type="checkbox" name="resolved" value="${esc(d.id)}"/><span>${labels[d.status]||esc(d.status)}：${esc(d.basis)}<small class="evidence-ref">${esc(d.id)}</small></span></label>`).join('')}</div><p class="muted">只有本次依据已经解释并处理的判断才勾选；未处理的冲突保留待核验。</p></details>`:''}
      <button class="button subtle" type="submit">保存已复核诊断</button></form>`}
      <section class="detail-section"><h3>原始证据 · ${proofs.length}</h3>${proofs.map(e=>`<article class="judgment-card"><span class="evidence-origin">${origins[e.origin]||esc(e.origin)}</span><p>${esc(e.text)}</p><div class="evidence-ref">${esc(e.id)}</div><p class="muted">${sourceTypes[e.source_type]||esc(e.source_type)} · 提示 ${e.prompt_level??'未知'}<br/>${date(e.created_at||e.occurred_at)} · 课程 v${e.course_version}<br/>任务 ${esc(e.context?.task_id||'')} / v${esc(e.context?.task_version||'')}</p></article>`).join('')||'<p class="muted">没有证据。尚未涉及与证据不足是不同状态。</p>'}</section>
      <section class="detail-section"><h3>诊断历史 · ${diagnoses.length}</h3>${diagnoses.map(d=>`<article class="judgment-card">${badge(d.status)}<p>${esc(d.basis)}</p><p class="muted">${esc(d.reviewer||'未复核')} · ${d.review_status==='reviewed'?'已人工复核':'待复核'}<br/>${date(d.created_at)}</p><details><summary class="muted">查看证据引用与版本</summary><p class="evidence-ref">${esc(d.id)}<br/>课程 v${d.course_version}<br/>${(d.evidence_ids||[]).map(esc).join('<br/>')}</p></details></article>`).join('')||'<p class="muted">暂无诊断。</p>'}</section>`;
    if(!student)return;
    $('evidenceForm').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{
      const who=student,token=loadToken;
      const context={task_id:$('taskId').value.trim(),task_version:Number($('taskVersion').value),turn_id:$('turnId').value?Number($('turnId').value):null,skeleton_id:$('skeletonId').value.trim()||null,skeleton_version:$('skeletonVersion').value?Number($('skeletonVersion').value):null};
      const relation=$('expressionRelation').value.trim(),quote=$('expressionQuote').value;
      if((relation&&!quote)||(!relation&&quote))throw new Error('登记概念关系时，请同时填写关系与逐字原话。');
      const expressed_relations=relation?[{source:$('expressionSource').value,target:$('expressionTarget').value,relation,quote}]:[];
      await writeLearner('/evidence',{node_id:n.id,course_version:graph.version,source_type:$('evidenceType').value,origin:$('evidenceOrigin').value,text:$('evidenceText').value,prompt_level:$('promptLevel').value===''?null:Number($('promptLevel').value),context,expressed_relations});
      if(who===student&&token===loadToken)renderDetail();toast(`${who} 的原始证据已保存。`);
    });};
    $('diagnosisForm').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{
      const ids=Array.from(document.querySelectorAll('input[name="proof"]:checked')).map(e=>e.value);
      const resolved=Array.from(document.querySelectorAll('input[name="resolved"]:checked')).map(e=>e.value);
      if(!ids.length)throw new Error('请选择支持本次判断的原始证据。');
      const who=student,token=loadToken;
      await writeLearner('/diagnoses',{node_id:n.id,course_version:graph.version,evidence_ids:ids,status:$('diagnosisStatus').value,basis:$('diagnosisBasis').value,review_status:'reviewed',reviewer:$('diagnosisReviewer').value.trim(),is_retest:$('isRetest').checked,resolves_diagnosis_ids:resolved,follow_up_action_id:$('followUpAction').value});
      if(who===student&&token===loadToken)renderDetail();toast('诊断已保存，节点状态按证据和冲突情况更新。');
    });};
  }
  async function renderPath(n,token){
    $('detailContent').innerHTML=`${heading(n)}<p class="description">${view==='draft'?'课程先修结构预览，不代表个人补学要求。':'依据当前证据、前置关系与复习间隔选择下一步。'}</p><p class="empty">正在检查依赖…</p>`;
    try{
      const result=await api(`/path?${query({target_id:n.id})}`);
      if(token!==detailToken)return;pathResult=result;
      let recommendation={actions:[],resources:[]};
      if(view==='published'){
        recommendation=await readRecommendations(n.id);
        if(token!==detailToken)return;
        if(recommendation.learner){learner=recommendation.learner;updateStats();}
      }
      const actionNames={diagnose:'先核验知识',verify:'补充核验',review:'安排间隔复测',retest:'安排复测',spaced_retest:'安排间隔复测',check_prerequisites:'核验相关先修',preview:'结构预览',remediate:'针对性补学',learn:'学习当前内容',continue:'继续当前学习',practice:'安排独立练习',verify_independent:'减少提示后核验',resource:'使用审核资源'};
      $('detailContent').innerHTML=`${heading(n)}<p class="description">${view==='draft'?'仅按草稿先修关系预览。':'已掌握且未到复习期的分支可以跳过；到期、冲突或新版本需要再核验。'}</p><div class="path-note">${view==='draft'?'正式路径将在人工审核发布后结合学习者证据生成。':state(n.id)==='mastered'?'当前证据支持掌握，请按复习计划继续。':result.ready?'当前没有需要先处理的依赖，可核验目标节点。':'先处理相关依赖；尚无证据的节点安排诊断，不直接判为不会。'}</div>${recommendation.actions.map(a=>`<article class="action-card"><h4>${actionNames[a.type]||esc(a.type)}</h4><p>${esc(a.reason)}</p><p>后续核验：${esc(a.follow_up||'通过新的独立表现补充证据。')}</p><details><summary class="muted">触发依据</summary><p class="evidence-ref">${[...(a.evidence_ids||[]),...(a.diagnosis_ids||[])].map(esc).join('<br/>')||'课程结构 / 复习时间 / 尚无证据'}</p></details></article>`).join('')}<div class="path-list">${result.steps.map((s,i)=>`<article class="path-step"><button data-jump="${esc(s.node_id)}">${i+1}. ${esc(s.title)}</button><p>${esc(s.reason)}</p>${view==='draft'?'':badge(s.status)}</article>`).join('')}</div><button id="showPath" class="button subtle full">在两单元图谱中查看依赖</button>${recommendation.resources.length?`<section class="detail-section"><h3>已审核资源</h3>${recommendation.resources.map(resourceCard).join('')}</section>`:''}<p class="muted" style="margin-top:15px">${esc(recommendation.notice||'')}${view==='published'?`复习间隔：${(graph.review_policy?.intervals_days||[1,7,30]).join('、')} 天。`:''}</p>`;
      if(view==='published')$('detailContent').insertAdjacentHTML('beforeend',selectionAndHistory(recommendation));
      bindJumps();$('showPath').onclick=()=>{chapter='all';$('structureView').value='course';$('relationFilter').disabled=false;$('search').value='';$('statusFilter').value='all';$('relationFilter').value='prerequisite';renderSidebar();renderGraph();};
      $('detailContent').querySelectorAll('[data-resource]').forEach(a=>a.onclick=()=>{const r=recommendation.resources.find(r=>r.id===a.dataset.resource);if(student)writeLearner('/resource-use',{node_id:r?.recommendation_node_id||n.id,resource_id:a.dataset.resource,course_version:graph.version}).catch(e=>toast(e.message,true));});
    }catch(error){if(token===detailToken)$('detailContent').innerHTML=`${heading(n)}<p class="empty error-detail">${esc(error.message)}</p>`;}
  }
  function selectionAndHistory(recommendation){
    const selection=recommendation.selection,history=recommendation.action_history||[];
    if(!selection)return '';
    const names=ids=>(ids||[]).map(id=>esc(node(id)?.title||id)).join('、');
    const resourceTitle=id=>graph.resources.find(r=>r.id===id)?.title||id;
    return `<section class="detail-section" id="recommendationTrace"><h3>资源为什么这样选</h3><p>这一步可先核验：${names(selection.frontier_node_ids)||'当前节点已掌握，无需补学资源'}</p><p>已审核且满足条件 ${selection.selection_trace.eligible_count} 项，本次选择 ${selection.resources.length} 项。</p><details><summary class="muted">查看筛选依据</summary><p class="muted">${esc(selection.selection_trace.ranking_rule)}</p>${selection.excluded_resources.map(r=>`<p class="muted"><strong>${esc(resourceTitle(r.resource_id))}</strong>：${esc(r.reason)}</p>`).join('')||'<p class="muted">本轮没有被排除的资料。</p>'}</details></section><section class="detail-section" id="actionHistory"><h3>教学调整后的核验</h3>${history.map(a=>`<article class="judgment-card"><p class="muted">${date(a.created_at)} · 课程 v${a.course_version}</p><p>${a.outcome==='pending'?'等待新的任务作答和复核':a.outcome==='version_changed'?'历史课程版本，需结合当前课程重新核验':'已有后续复核记录'}</p>${a.observations.map(o=>`<p>${names([o.node_id])}：本次判断 ${labels[o.status]||esc(o.status)}；当前综合状态 ${labels[o.current_status]||esc(o.current_status)}</p><p class="muted">${esc(o.basis)}</p>`).join('')}<details><summary class="muted">查看记录引用</summary><p class="evidence-ref">${esc(a.action_id)}<br/>${a.observations.flatMap(o=>[o.diagnosis_id,...o.evidence_ids]).map(esc).join('<br/>')}</p></details></article>`).join('')||'<p class="muted">加载匿名编号后，教学建议与后续核验会保存在同一学习记录中。</p>'}<p class="muted">后续表现用于回查教学调整；资料点击不代表掌握，尚无核验也不代表失败。</p></section>`;
  }
  function renderProfile(){
    const profile=learner.profile||{};
    $('profileBody').innerHTML=`${view==='draft'?'<div class="draft-help">教师草稿不关联正式学习者画像。请先发布课程，再从正式课程入口加载匿名编号。</div>':!student?'<div class="path-note">请先在页面左侧加载匿名编号。</div>':`<form id="profileForm" class="form-stack"><p class="muted">匿名编号：${esc(student)}。兴趣仅用于情境外观与表达选择，不参与掌握判断。</p><label>学习目标<textarea id="profileGoals" rows="2" maxlength="2000">${esc(profile.goals||'')}</textarea></label><label>必要学习背景<textarea id="profileBackground" rows="2" maxlength="2000">${esc(profile.background||'')}</textarea></label>${field('profileInterests','兴趣偏好（逗号分隔）',(profile.interests||[]).join('，'),'maxlength="1000"')}<div class="profile-grid"><section><h3 class="mini-title">当前学习记忆</h3><p class="muted">${profile.current_position?`${esc(node(profile.current_position.node_id)?.title||profile.current_position.node_id)}<br/>课程 v${profile.current_position.course_version}<br/>${esc(profile.current_position.context_ref||'')}`:'尚未保存学习位置。选择正式课程节点后自动保存。'}</p></section><section><h3 class="mini-title">不同证据分别记录</h3><p class="muted">知识状态：${Object.keys(learner.states||{}).length} 个节点<br/>能力证据：${(profile.ability_evidence||[]).length} 条<br/>行为线索：${(profile.behavioral_clues||[]).length} 条<br/>情绪线索：${(profile.emotional_clues||[]).length} 条</p></section></div><button class="button primary" type="submit">保存画像信息</button></form>`}`;
    if($('profileForm'))$('profileForm').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{
      await writeLearner('/profile',{...learner.profile,goals:$('profileGoals').value,background:$('profileBackground').value,interests:$('profileInterests').value.split(/[,，]/).map(x=>x.trim()).filter(Boolean)},'PUT');toast('画像信息已保存，节点判断未被兴趣或背景改写。');renderProfile();
    });};
  }

  function reviewFields(item){return `<div class="review-fields form-stack"><p class="muted">当前状态：${item.review_status==='reviewed'?`已审核 · ${esc(item.reviewer)} · ${date(item.reviewed_at)}`:'草稿，尚未人工审核'}</p>${field('reviewer','实际审核人',item.review_status==='reviewed'?item.reviewer:'','maxlength="100"')}<label>审核依据与修改说明<textarea id="reviewNote" rows="2" maxlength="2000">${esc(item.review_status==='reviewed'?item.review_note:'')}</textarea></label></div><div class="form-actions"><button class="button subtle" type="submit" value="draft">保存为草稿</button><button class="button primary" type="submit" value="reviewed">人工审核通过并保存</button></div>`;}
  function applyReview(item,status){
    item.review_status=status;
    if(status==='reviewed'){
      item.reviewer=$('reviewer').value.trim();item.review_note=$('reviewNote').value.trim();item.reviewed_at=new Date().toISOString();
      if(!item.reviewer||!item.review_note)throw new Error('请填写实际审核人和具体审核依据。');
    }else{item.reviewer='';item.reviewed_at='';item.review_note=$('reviewNote').value.trim();}
    return item;
  }
  const splitIds = value => value.split(/[,，\s]+/).map(s=>s.trim()).filter(Boolean);
  const options = (items,value,label='title') => items.map(x=>`<option value="${esc(x.id)}" ${x.id===value?'selected':''}>${esc(x.id)} · ${esc(typeof label==='function'?label(x):x[label])}</option>`).join('');
  async function saveGraph(next){
    const result=await api('',{method:'PUT',body:JSON.stringify({graph:next,expected_version:graph.version})});
    graph=result.graph;summary=result.summary||summary;syncSelection();updateStats();renderSidebar();renderDetail();renderGraph();toast(`工作草稿已保存 · v${graph.version}`);
  }
  function renderManager(){
    document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode));
    if(mode==='node')renderNodeEditor(selected);if(mode==='edge')renderEdgeEditor();if(mode==='resource')renderResourceEditor();if(mode==='audit')renderAudit();if(mode==='blueprints')renderBlueprints();if(mode==='publish')renderPublish();if(mode==='import')renderImport();if(mode==='extract')renderExtract();
  }
  async function renderAudit(){
    $('managerBody').innerHTML='<p class="empty">正在核查图谱与参考依据…</p>';
    try{
      const [audit,referenceResponse]=await Promise.all([api('/teacher/audit?view=draft'),fetch('/api/course-assets/design-references')]);
      if(!referenceResponse.ok)throw new Error('书籍参考依据暂时无法读取。');
      const references=await referenceResponse.json();if(mode!=='audit')return;
      $('managerBody').innerHTML=`<div class="version-strip"><span>${audit.summary.node_count} 个知识点</span><span>${audit.summary.edge_count} 条关系</span><span><strong>${audit.summary.issue_count} 项待核查提示</strong></span></div><p class="manager-note">${esc(audit.notice)}</p><h3 class="mini-title">概念、关系与出处核查</h3><div id="auditIssues">${audit.issues.map(issue=>`<article class="judgment-card"><h4>${esc(issue.title)}</h4><p>${esc(issue.message)}</p><p class="muted">${[...(issue.node_ids||[]).map(id=>node(id)?.title||id),...(issue.edge_ids||[]),...(issue.source_ids||[]).map(id=>graph.sources.find(s=>s.id===id)?.title||id)].map(esc).join(' · ')}</p>${issue.details.alternative_path?`<p class="muted">已有路径：${issue.details.alternative_path.map(id=>esc(node(id)?.title||id)).join(' → ')}</p>`:''}</article>`).join('')||'<p class="check-result">未发现这些结构问题；仍需人工核对课程语义。</p>'}</div><h3 class="mini-title">四类关系的边界</h3><div class="audit-grid">${audit.relation_schema.map(r=>`<article class="judgment-card"><h4>${esc(r.label)} · ${esc(r.direction)}</h4><p>${esc(r.meaning)}</p><p class="muted">${esc(r.boundary)}</p></article>`).join('')}</div><details class="detail-section"><summary>查看课程出处定位</summary>${audit.sources.map(s=>`<p class="muted"><strong>${esc(s.title)}</strong><br/>${esc(typeof s.locator==='string'?s.locator:JSON.stringify(s.locator||'待补具体定位'))}</p>`).join('')}</details><h3 class="mini-title">本次书籍参考与落实</h3><p class="manager-note">${esc(references.scope)}</p><div id="bookReferences">${references.books.map(book=>`<article class="judgment-card"><h4>${esc(book.title)}</h4><p class="muted">${esc(book.author)} · ${esc(book.filename)}</p>${book.readings.map(r=>`<p><strong>${esc(r.section)}</strong> · PDF 第 ${r.pdf_pages.join('、')} 页${r.printed_pages?.length?` / 书内第 ${r.printed_pages.join('、')} 页`:''}<br/>${esc(r.application)}</p>`).join('')}</article>`).join('')}</div>`;
    }catch(error){if(mode==='audit')$('managerBody').innerHTML=`<p class="empty error-detail">${esc(error.message)}</p>`;}
  }
  function renderNodeEditor(id){
    const current=node(id),n=current||{id:'',title:'',description:'',chapter_id:graph.chapters[0].id,objectives:[],aliases:[],misconception:'',source_ids:[],review_status:'draft'};
    $('managerBody').innerHTML=`<p class="manager-note">统一维护概念边界与学习目标。修改先进入草稿，人工审核后才可发布。</p><form id="nodeEditor" class="form-stack"><label>知识点<select id="editPick"><option value="">新建知识点</option>${options(graph.nodes,n.id)}</select></label><div class="manager-grid">${field('editId','稳定编号',n.id,`required maxlength="64" ${n.id?'readonly':''}`)}${field('editTitle','名称',n.title,'required maxlength="200"')}<label>学习单元<select id="editChapter">${options(graph.chapters,n.chapter_id)}</select></label>${field('editAliases','别名（逗号分隔）',n.aliases.join('，'))}<label class="span-2">定义与概念边界<textarea id="editDescription" rows="3" maxlength="4000" required>${esc(n.description)}</textarea></label><label>可观察学习目标（每行一条）<textarea id="editObjectives" rows="3">${esc(n.objectives.join('\n'))}</textarea></label><label>典型误解<textarea id="editMisconception" rows="3" maxlength="2000">${esc(n.misconception)}</textarea></label><label>诊断问题<textarea id="editQuestion" rows="3" maxlength="4000">${esc(n.check_question||'')}</textarea></label><label>教师参考判据<textarea id="editAnswer" rows="3" maxlength="4000">${esc(n.expected_answer||'')}</textarea></label>${field('editSources','概念出处 ID（逗号分隔）',n.source_ids.join(','))}<p class="muted">可用出处：${graph.sources.map(s=>`${esc(s.id)}：${esc(s.title)}`).join('<br/>')}</p></div>${reviewFields(n)}${current?'<button type="button" id="deleteNode" class="button danger node-delete">删除草稿节点</button>':''}</form>`;
    $('editPick').value=n.id;$('editPick').onchange=e=>renderNodeEditor(e.target.value);
    $('nodeEditor').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{
      const value={...clone(n),id:$('editId').value.trim(),title:$('editTitle').value.trim(),chapter_id:$('editChapter').value,description:$('editDescription').value,objectives:$('editObjectives').value.split('\n').map(x=>x.trim()).filter(Boolean),misconception:$('editMisconception').value,aliases:splitIds($('editAliases').value),source_ids:splitIds($('editSources').value),check_question:$('editQuestion').value,expected_answer:$('editAnswer').value};
      applyReview(value,event.submitter.value);
      if(value.check_task&&(value.check_question!==n.check_question||value.expected_answer!==n.expected_answer))value.check_task.version+=1;
      const next=clone(graph),index=next.nodes.findIndex(x=>x.id===n.id);
      if(index<0){if(next.nodes.some(x=>x.id===value.id))throw new Error('节点编号已存在。');next.nodes.push(value);}else next.nodes[index]=value;
      await saveGraph(next);selected=value.id;renderNodeEditor(value.id);renderSidebar();renderDetail();renderGraph();
    });};
    if($('deleteNode'))$('deleteNode').onclick=e=>busy(e.target,async()=>{
      if(!confirm(`从草稿删除“${n.title}”及相邻关系？已发布版本和历史证据保留。`))return;
      const next=clone(graph);next.nodes=next.nodes.filter(x=>x.id!==n.id);next.edges=next.edges.filter(x=>x.source!==n.id&&x.target!==n.id);
      for(const r of next.resources){r.node_ids=r.node_ids.filter(x=>x!==n.id);r.prerequisite_ids=r.prerequisite_ids.filter(x=>x!==n.id);r.review_status='draft';r.reviewer='';r.reviewed_at='';}
      await saveGraph(next);renderNodeEditor(selected);
    });
  }
  function renderEdgeEditor(id=''){
    const existing=graph.edges.find(e=>e.id===id),e=existing||{id:'',source:selected||graph.nodes[0].id,target:graph.nodes.find(n=>n.id!==selected)?.id||graph.nodes[0].id,type:'prerequisite',reason:'',source_ids:[],review_status:'draft'};
    $('managerBody').innerHTML=`<p class="manager-note">前置与包含关系有方向；关联、易混淆不用于限制学习顺序。保存时检查前置和包含循环。</p><form id="edgeEditor" class="form-stack"><label>选择关系<select id="edgePick"><option value="">新建关系</option>${options(graph.edges,e.id,x=>`${node(x.source)?.title} / ${relations[x.type]} / ${node(x.target)?.title}`)}</select></label><div class="manager-grid"><label>节点 A<select id="edgeSource">${options(graph.nodes,e.source)}</select></label><label>节点 B<select id="edgeTarget">${options(graph.nodes,e.target)}</select></label><label>关系类型<select id="edgeType">${Object.entries(relations).map(([k,v])=>`<option value="${k}" ${k===e.type?'selected':''}>${v}</option>`).join('')}</select></label>${field('edgeSources','依据出处 ID（逗号分隔）',e.source_ids.join(','))}<label class="span-2">具体关系依据<textarea id="edgeReason" rows="3" maxlength="2000" required>${esc(e.reason)}</textarea></label></div>${reviewFields(e)}${existing?'<button id="deleteEdge" class="button danger node-delete" type="button">删除草稿关系</button>':''}</form>`;
    $('edgePick').value=e.id;$('edgePick').onchange=event=>renderEdgeEditor(event.target.value);
    $('edgeEditor').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{
      const value=applyReview({...clone(e),id:e.id||`edge_${Date.now().toString(36)}`,source:$('edgeSource').value,target:$('edgeTarget').value,type:$('edgeType').value,reason:$('edgeReason').value,source_ids:splitIds($('edgeSources').value)},event.submitter.value),next=clone(graph),index=next.edges.findIndex(x=>x.id===e.id);
      if(index<0)next.edges.push(value);else next.edges[index]=value;await saveGraph(next);renderEdgeEditor(value.id);
    });};
    if($('deleteEdge'))$('deleteEdge').onclick=event=>busy(event.target,async()=>{if(!confirm('删除这条草稿关系？'))return;const next=clone(graph);next.edges=next.edges.filter(x=>x.id!==e.id);await saveGraph(next);renderEdgeEditor();});
  }
  function renderResourceEditor(id=graph.resources[0]?.id){
    const current=graph.resources.find(r=>r.id===id),r=current||{id:'',title:'',organization:'',url:'',node_ids:[],applicable_segment:'',prerequisite_ids:[],format:'course',review_status:'draft'};
    $('managerBody').innerHTML=`<p class="manager-note">概念出处与教学推荐资源分别维护。填写适用片段及前置要求，实际审阅后才能作为正式推荐。</p><form id="resourceEditor" class="form-stack"><label>教学资源<select id="resourcePick"><option value="">新建资源</option>${options(graph.resources,r.id)}</select></label><div class="manager-grid">${field('resourceId','资源编号',r.id,`required maxlength="64" ${r.id?'readonly':''}`)}${field('resourceTitle','标题',r.title,'required maxlength="300"')}${field('resourceOrg','作者或机构',r.organization,'required maxlength="300"')}${field('resourceUrl','来源链接',r.url,'type="url" maxlength="2000"')}<label>资源形态<select id="resourceFormat">${Object.entries(formats).map(([k,v])=>`<option value="${k}" ${k===r.format?'selected':''}>${v}</option>`).join('')}</select></label>${field('resourceNodes','适用节点 ID（逗号分隔）',r.node_ids.join(','),'required')}${field('resourcePrereq','前置节点 ID（逗号分隔）',r.prerequisite_ids.join(','))}<label class="span-2">具体适用片段 / 段落 / 时间范围<textarea id="resourceSegment" rows="3" required maxlength="2000">${esc(r.applicable_segment)}</textarea></label></div>${reviewFields(r)}</form>`;
    $('resourcePick').value=r.id;$('resourcePick').onchange=event=>renderResourceEditor(event.target.value);
    $('resourceEditor').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{
      const value=applyReview({...clone(r),id:$('resourceId').value.trim(),title:$('resourceTitle').value,organization:$('resourceOrg').value,url:$('resourceUrl').value,node_ids:splitIds($('resourceNodes').value),prerequisite_ids:splitIds($('resourcePrereq').value),format:$('resourceFormat').value,applicable_segment:$('resourceSegment').value},event.submitter.value),next=clone(graph),index=next.resources.findIndex(x=>x.id===r.id);
      if(index<0)next.resources.push(value);else next.resources[index]=value;await saveGraph(next);renderResourceEditor(value.id);
    });};
  }
  function renderPublish(){
    const pending=[...graph.nodes,...graph.edges,...graph.resources].filter(x=>x.review_status!=='reviewed');
    $('managerBody').innerHTML=`<div class="version-strip"><span>工作草稿 <strong>v${graph.version}</strong></span><span>当前发布 <strong>${publication.published_version?'v'+publication.published_version:'尚未发布'}</strong></span><span>尚未审核 <strong>${pending.length}</strong> 项</span></div><p class="manager-note">发布会固定当前课程版本。后续草稿修改不影响学生使用中的课程；旧版本继续支持历史证据回溯。</p>${pending.length?`<div class="draft-help">需要逐项审核 ${graph.nodes.filter(x=>x.review_status!=='reviewed').length} 个知识点、${graph.edges.filter(x=>x.review_status!=='reviewed').length} 条关系、${graph.resources.filter(x=>x.review_status!=='reviewed').length} 项资源。<details><summary>查看待审条目</summary><p class="evidence-ref">${pending.map(x=>esc(x.id)).join('、')}</p></details></div>`:'<div class="check-result">所有发布条目已填写人工审核信息，可执行发布检查。</div>'}<form id="publishForm" class="form-stack" style="margin-top:18px">${field('publishedBy','实际发布人','','required maxlength="100"')}<label>发布说明<textarea id="publishNote" rows="3" maxlength="2000" required></textarea></label><label class="inline-check"><input id="publishConfirm" type="checkbox" required/>已核对课程知识、关系与资源的人工审核记录</label><button class="button primary" type="submit">检查并发布课程</button></form><hr class="section-divider"/><p class="muted">当前固定复习间隔：${graph.review_policy.intervals_days.join('、')} 天。可在完整 JSON 中配置，修改后需发布新课程版本。</p><p class="muted">本地工作台尚未接入账号权限。此处操作记录用于人工复核追溯，不等于已完成在线教师身份认证。</p>`;
    $('publishForm').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{
      await api('/publish',{method:'POST',body:JSON.stringify({expected_version:graph.version,published_by:$('publishedBy').value.trim(),note:$('publishNote').value})});
      await loadStudent('');renderPublish();toast('课程发布成功，正式课程入口已可读取该版本。');
    });};
  }
  async function renderBlueprints(){
    $('managerBody').innerHTML='<p class="empty">正在读取课程统一骨架…</p>';
    try{
      const response=await fetch('/api/course-assets/training-blueprints');if(!response.ok)throw new Error('统一实训骨架无法读取。');
      const assets=await response.json();if(mode!=='blueprints')return;
      $('managerBody').innerHTML=`<p class="manager-note">统一考核骨架固定节点、步骤、判定与难度；兴趣只改变情境外观。以下是待教师审核的资产，运行环境和判定脚本尚未接入。</p>${assets.blueprints.map(b=>`<article class="judgment-card"><h3 class="mini-title">${esc(b.title)}</h3><p class="evidence-ref">${esc(b.id)} · v${b.version} · 待审核</p><p class="muted">目标节点：${b.target_node_ids.map(id=>esc(node(id)?.title||id)).join('、')}</p><details><summary>查看固定步骤与判定要求</summary><ol class="summary-list">${b.steps.map(s=>`<li><strong>${esc(s.title)}</strong><pre class="extract-json">${esc(JSON.stringify(s.judge_spec,null,2))}</pre><p class="muted">四级提示：${s.hints.map(h=>esc(typeof h==='string'?h:JSON.stringify(h))).join(' → ')}</p></li>`).join('')}</ol></details><details><summary>查看错误归因库 · ${b.error_types.length} 类</summary><ul class="summary-list">${b.error_types.map(e=>`<li>${esc(e.manifestation)} → ${e.node_ids.map(id=>esc(node(id)?.title||id)).join('、')}<br/>${esc(e.misconception)}</li>`).join('')}</ul></details></article>`).join('')}<div class="form-actions"><button id="exportBlueprints" class="button subtle">导出统一骨架资产</button></div>`;
      $('exportBlueprints').onclick=()=>download(assets,'统一实训骨架_待审核.json');
    }catch(error){if(mode==='blueprints')$('managerBody').innerHTML=`<p class="empty">${esc(error.message)}</p>`;}
  }
  function renderImport(){
    $('managerBody').innerHTML=`<p class="manager-note">完整课程 JSON 包含节点、四类关系、来源、教学资源与复习规则。导入只更新草稿，不能跳过发布与人工审核。</p><div class="form-actions" style="justify-content:flex-start"><button id="exportGraph" class="button subtle">导出工作草稿</button><button id="exportPublished" class="button subtle">导出已发布教师版本</button></div><div class="form-stack" style="margin-top:15px"><label>选择完整课程 JSON<input id="importFile" type="file" accept=".json,application/json"/></label><label>课程数据<textarea id="importJson" class="import-box" rows="11"></textarea></label><div id="validationResult" class="check-result" hidden></div><div class="form-actions"><button id="validateImport" class="button subtle">检查结构</button><button id="saveImport" class="button primary">校验并导入草稿</button></div></div>`;
    $('exportGraph').onclick=event=>busy(event.target,async()=>download(await api('/export?view=draft'),`${graph.id}-draft-v${graph.version}.json`));
    $('exportPublished').onclick=event=>busy(event.target,async()=>download(await api('/teacher/export?view=published'),`${graph.id}-published-teacher.json`));
    $('importFile').onchange=async event=>{const file=event.target.files[0];if(file){if(file.size>2000000){toast('文件超过 2 MB。',true);return;}$('importJson').value=await file.text();}};
    const parse=()=>{try{return JSON.parse($('importJson').value);}catch{throw new Error('JSON 格式不正确，请检查括号、引号与逗号。');}};
    $('validateImport').onclick=event=>busy(event.target,async()=>{const result=await api('/validate',{method:'POST',body:JSON.stringify({graph:parse()})});$('validationResult').hidden=false;$('validationResult').textContent=`结构检查通过：${result.summary.node_count} 个节点，${result.summary.edge_count} 条关系。结构通过不表示人工审核完成。`;});
    $('saveImport').onclick=event=>busy(event.target,async()=>{const value=parse();await api('/validate',{method:'POST',body:JSON.stringify({graph:value})});if(!confirm('替换当前工作草稿？发布版本与原始学习证据保留。'))return;value.version=graph.version;await saveGraph(value);renderImport();});
  }
  function renderExtract(){
    $('managerBody').innerHTML=`<p class="manager-note">从课程原文提取带逐字证据的候选。候选需人工核对，分配节点与来源后再加入工作草稿，不会自动发布。</p><form id="extractForm" class="form-stack"><div class="manager-grid">${field('extractTitle','材料标题','','required maxlength="300"')}${field('extractUrl','来源链接（可选）','','type="url"')}<label class="span-2">课程原文<textarea id="extractText" rows="7" required maxlength="24000"></textarea></label></div><button id="extractSubmit" class="button primary" type="submit">生成待审候选</button></form><div id="extractResult"></div>`;
    $('extractForm').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{event.submitter.textContent='正在提取…';extracted=await api('/extract',{method:'POST',body:JSON.stringify({source_title:$('extractTitle').value,source_url:$('extractUrl').value,text:$('extractText').value})});showCandidates();});};if(extracted)showCandidates();
  }
  function showCandidates(){
    $('extractResult').innerHTML=`<div class="check-result">${extracted.nodes.length} 个候选节点、${extracted.edges.length} 条候选关系。${esc(extracted.notice||'')} ${(extracted.warnings||[]).map(esc).join('；')}</div><div class="table-scroll"><table class="edge-table"><thead><tr><th>候选概念</th><th>原文证据</th></tr></thead><tbody>${extracted.nodes.map(n=>`<tr><td>${esc(n.title)}</td><td>${esc(n.evidence?.text)}<br/><small>字符位置 ${n.evidence?.start}—${n.evidence?.end}</small></td></tr>`).join('')}</tbody></table></div><button id="exportCandidates" class="button subtle">导出候选及原文定位</button>`;
    $('exportCandidates').onclick=()=>download(extracted,'待审知识候选.json');
  }

  $('studentForm').onsubmit=event=>{event.preventDefault();busy(event.submitter,async()=>{await loadStudent($('studentId').value.trim(),true);toast(student?`已恢复 ${student} 的学习记录。`:'已切换到课程浏览。');});};
  $('search').oninput=changeFilter;$('statusFilter').onchange=changeFilter;$('relationFilter').onchange=renderGraph;
  $('structureView').onchange=()=>{$('relationFilter').disabled=$('structureView').value==='expressions';changeFilter();};
  $('fitButton').onclick=()=>renderer?.fitView();$('zoomIn').onclick=()=>renderer?.zoomTo(renderer.getZoom()*1.2);$('zoomOut').onclick=()=>renderer?.zoomTo(renderer.getZoom()/1.2);
  document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{activeTab=b.dataset.tab;renderDetail();});
  document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{mode=b.dataset.mode;renderManager();});
  $('manageButton').onclick=()=>{if(graph){renderManager();$('manager').showModal();}};document.querySelector('.close-dialog').onclick=()=>$('manager').close();
  $('profileButton').onclick=()=>{renderProfile();$('profileDialog').showModal();};$('closeProfile').onclick=()=>$('profileDialog').close();
  $('profileInlineButton').onclick=()=>{renderProfile();$('profileDialog').showModal();};
  $('resumeButton').onclick=()=>{const id=learner.profile?.current_position?.node_id;if(node(id)){activeTab='detail';selectNode(id,true,false);toast('已恢复上次知识节点。');}else toast('上次节点不在当前发布版本中，请重新选择。',true);};
  $('reportButton').onclick=event=>{if(!student){toast('请从正式课程加载匿名编号。',true);return;}busy(event.target,async()=>download(await api(`/learner/export?student_id=${encodeURIComponent(student)}`),`${student}-画像与原始证据.json`));};
  let initial='';if(view==='published')try{initial=localStorage.getItem('learningAgent.student')||'';}catch{}
  $('studentId').value=initial;
  loadStudent(initial,true).catch(error=>{$('graphMessage').textContent=error.message;toast(error.message,true);});
})();
