(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pct = value => `${(value * 100).toFixed(1)}%`;
  let state = null, busy = false, lastStep = '', receipt = null;
  $('themeButton').onclick = () => GraphTheme.toggle();
  $('studentId').value = new URLSearchParams(location.search).get('student_id') || localStorage.getItem('pliac-ml-student') || '';
  function error(message='') { $('labError').textContent = message; $('labError').hidden = !message; }
  const courseId = new URLSearchParams(location.search).get('course_id') || 'ml_acceptance_demo';
  async function request(path, body) {
    path += `${path.includes('?') ? '&' : '?'}course_id=${encodeURIComponent(courseId)}`;
    const response = await fetch(`/api/ml-lab${path}`, body ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '请求未完成，请重试。');
    return data;
  }
  async function operate(name, fields={}) {
    if (busy) return;
    busy = true; error();
    document.querySelectorAll('button,input,textarea,select').forEach(b => { if(b.id !== 'themeButton') b.disabled = true; });
    const signature = JSON.stringify([name,fields]);
    if (!receipt || receipt.signature !== signature) receipt = {signature,id:crypto.randomUUID()};
    try {
      state = await request(`/${name}`, {student_id:state.student_id,expected_version:state.version,course_version:state.course_version,
        request_id:receipt.id,session_id:state.active?.id,...fields});
      receipt = null; $('saveState').textContent = '已保存到本机'; render();
    } catch (e) {
      error(e.message);
      // Refresh revisions after concurrent-tab conflicts; keep the request ID for safe retry.
      try { state = await request(`?student_id=${encodeURIComponent(state.student_id)}`); render(); } catch (_) {}
    } finally { busy=false; document.querySelectorAll('button,input,textarea,select').forEach(b=>b.disabled=false); lockControls(); }
  }
  function lockControls() {
    $('exportLab').disabled = !state?.active;
    $('runButton').disabled = !state?.active || state.active.step >= 4;
    $('hintButton').disabled = !state?.active || state.active.step >= 5 || (state.active.hints[state.tasks[state.active.step]?.id] || 0) >= 3;
  }
  function select(id,label,options) { return `<label>${esc(label)}<select id="${id}"><option value="">请选择</option>${options.map(([v,t])=>`<option value="${esc(v)}">${esc(t)}</option>`).join('')}</select></label>`; }
  function render() {
    const s=state.active;
    $('setup').hidden = !!s; $('workbench').hidden = !s;
    for(const [id,path] of [['learnLink','learn'],['graphLink','knowledge'],['reviewLink','review']]) $(id).href=`/${path}?course_id=${encodeURIComponent(courseId)}&student_id=${encodeURIComponent(state.student_id)}`;
    const originNode=new URLSearchParams(location.search).get('node_id');
    if(originNode){$('learnLink').href+=`&node_id=${encodeURIComponent(originNode)}&view=study`;$('learnLink').textContent='返回讲义';}
    const returnPath = new URLSearchParams(location.search).get('return_to');
    if (returnPath) {
      const target = new URL(returnPath, location.origin);
      if (target.origin === location.origin && target.pathname === `/app/courses/${encodeURIComponent(courseId)}`) {
        $('learnLink').href = target.href; $('learnLink').textContent = '返回学习工作台';
      }
    }
    if (!s) {lockControls();return;}
    const scene=s.presentation || state.scenes[s.scene], task=state.tasks[s.step];
    $('sceneTitle').textContent=scene.title; $('mission').textContent=`你是${scene.role}。${scene.mission}`;
    $('mode').textContent=`${s.mode==='transfer'?'迁移复测':'实操练习'} · 第 ${state.lab.sessions.length} 轮`;
    $('progress').textContent=`${s.step} / 5`;
    const pause=state.rhythm?.current;
    $('labRest').hidden=!pause;
    $('labRestText').textContent=pause?`这段实验可以告一段落。可以休息约 ${pause.break_minutes} 分钟，回来后${pause.resume}也可以直接继续。`:'';
    $('dismissLabRest').onclick=()=>operate('rest',{point_id:pause.id,choice:'continue'});
    $('takeLabRest').onclick=()=>operate('rest',{point_id:pause.id,choice:'rest'});
    $('taskList').innerHTML=state.tasks.map((t,i)=>`<div class="task-row ${i===s.step?'active':i<s.step?'done':''}" ${i===s.step?'aria-current="step"':''}><span class="task-index">${i<s.step?'✓':i+1}</span>${esc(t.title)}</div>`).join('');
    $('knowledge').innerHTML=[['训练、验证与测试','训练集用来拟合模型；验证集比较候选方案；测试集在方案确定后评估最终表现。','roles'],['模型复杂度','浅树表达能力较弱；深树能够拟合更细的局部变化。比较训练和验证表现，判断复杂度是否合适。','complexity'],['数据泄漏','输入特征应在实际预测时就能取得。结果产生后的回执会把答案的信息带进模型。','leakage']].map(([title,text,node])=>`<details><summary>${title}</summary><p>${text}</p><a href="/learn?course_id=${encodeURIComponent(courseId)}&student_id=${encodeURIComponent(state.student_id)}&node_id=${encodeURIComponent(state.node_mapping[node] || node)}">进入相关小节</a></details>`).join('');
    $('taskPanel').hidden=!task;
    if(task){
      $('taskTitle').textContent=`${s.step+1}. ${task.title}`; $('taskGoal').textContent=task.goal; $('acceptance').textContent=`验收目标：${task.acceptance}`;
      $('hints').innerHTML=(state.hint_texts||[]).map((h,i)=>`<p class="hint">提示 ${i+1} · ${esc(h)}</p>`).join('');
      const key=`${s.id}:${s.step}`;
      const oldRun=$('chosenRun')?.value;
      if(lastStep!==key){
        lastStep=key; $('note').value='';
        let fields='';
        if(s.step===0) fields=select('target','预测目标',[['target',scene.target],['receipt',scene.receipt],['x1',scene.features[0]]])+select('inputChoice','输入特征',[['sensors','x1 + x2'],['receipt','x1 + x2 + receipt']])+select('timing','回执产生时间',[['before','预测之前'],['after','处理完成之后']]);
        if(s.step>=1&&s.step<=3) fields=select('chosenRun','引用实验记录',[]);
        if(s.step===2) fields+=select('interpretation','训练表现高、验证表现下降说明什么',[['gap','模型对新样本的泛化表现较弱'],['perfect','训练分数高说明已可靠掌握全部规律'],['more_test','应反复查看测试集调参']]);
        if(s.step===3) fields+=select('basis','选择方案的主要依据',[['validation','验证集表现'],['train','训练集表现'],['test','测试集表现']]);
        if(s.step===4) fields=select('testRole','测试结果的用途',[['report','报告已封存方案的泛化表现'],['tune','反复调整参数直到测试分数最高']]);
        $('answerFields').innerHTML=fields; $('noteLabel').hidden=s.step<3; $('note').required=s.step>=3;
        $('checkButton').textContent=s.step===4?'封存方案并完成测试':'检查本步成果';
      }
      if($('chosenRun')){ $('chosenRun').innerHTML='<option value="">请选择实验</option>'+s.runs.map(r=>`<option value="${r.id}">#${r.number} · 深度 ${r.config.depth||'自由'} · 验证 ${pct(r.result.validation_accuracy)}</option>`).join(''); if(s.runs.some(r=>r.id===oldRun)) $('chosenRun').value=oldRun; }
      $('feedback').innerHTML=s.checks.filter(c=>c.task_id===task.id).slice(-3).map(c=>`<div class="feedback-entry">${esc(c.feedback)}</div>`).join('');
    }
    $('dataDescription').textContent=`每行代表一条${scene.sample}；x1 是${scene.features[0]}，x2 是${scene.features[1]}，target 表示是否${scene.target}。`;
    $('dataHead').innerHTML='<tr><th>ID</th><th>x1</th><th>x2</th><th>target</th><th>receipt</th></tr>';
    $('dataRows').innerHTML=state.preview.slice(0,8).map(r=>`<tr>${['id','x1','x2','target','receipt'].map(k=>`<td>${r[k]}</td>`).join('')}</tr>`).join('');
    const points=state.preview, minX=Math.min(...points.map(p=>p.x1))-.2,maxX=Math.max(...points.map(p=>p.x1))+.2,minY=Math.min(...points.map(p=>p.x2))-.2,maxY=Math.max(...points.map(p=>p.x2))+.2;
    $('scatter').innerHTML='<path d="M35 15V255H425" fill="none" stroke="var(--control-border)"/><text x="390" y="280">x1</text><text x="10" y="20">x2</text>'+points.map(p=>`<circle cx="${35+(p.x1-minX)/(maxX-minX)*380}" cy="${250-(p.x2-minY)/(maxY-minY)*225}" r="3.5" fill="${p.target?'#ba7c43':'#527e9c'}" opacity=".8"/>`).join('')+'<text x="280" y="20">● 类别 0 / 类别 1</text>';
    $('runs').innerHTML=s.runs.map(r=>`<tr><td>#${r.number}</td><td>${r.config.depth||'自由'}</td><td>${r.config.features==='sensors'?'传感器':'含回执'} / ${r.config.train_percent}% / ${r.config.split==='separate'?'独立':'复用'}</td><td>${pct(r.result.train_accuracy)}</td><td>${pct(r.result.validation_accuracy)}</td><td>${r.result.overlap}</td></tr>`).join('');
    const latest=s.runs.at(-1);
    $('runStatus').textContent=s.step>=4?'方案已封存':latest?`已运行 ${s.runs.length} 次 · scikit-learn ${latest.result.engine.version}`:'';
    if(latest){
      const r=latest.result;
      $('latestResult').innerHTML=`<div class="metrics"><div class="metric"><span>训练准确率</span><strong>${pct(r.train_accuracy)}</strong><span>${r.counts.train} 条样本</span></div><div class="metric"><span>验证准确率</span><strong>${pct(r.validation_accuracy)}</strong><span>${r.counts.validation} 条样本</span></div><div class="metric"><span>测试集</span><strong>${r.counts.test}</strong><span>封存方案后评估</span></div></div><div class="matrix"><table><caption>验证集混淆矩阵</caption><tr><th>实际 / 预测</th><th>0</th><th>1</th></tr>${r.confusion_matrix.map((row,i)=>`<tr><th>${i}</th><td>${row[0]}</td><td>${row[1]}</td></tr>`).join('')}</table><p>对角线是判断正确的样本。<br>训练与验证重叠 ${r.overlap} 条；树包含 ${r.tree_nodes} 个节点。</p></div>`;
      $('trainPercent').value=latest.config.train_percent; $('depth').value=latest.config.depth; $('features').value=latest.config.features; $('split').value=latest.config.split;
      request(`/export?student_id=${encodeURIComponent(state.student_id)}`).then(data=>{if(state.active?.id===s.id)$('codePreview').textContent=data.scripts[`experiment-${latest.number}.py`];}).catch(e=>error(e.message));
    } else { $('latestResult').innerHTML=''; $('codePreview').textContent='运行实验后可查看与导出复现代码。'; }
    $('reportPanel').hidden=s.step<5;
    if(s.final){
      const assisted=Object.keys(s.hints).filter(k=>s.hints[k]);
      $('report').innerHTML=`<p>本轮 5 项实操验收完成，共运行 ${s.runs.length} 次实验。</p><div class="metrics"><div class="metric"><span>封存实验</span><strong>#${s.runs.find(r=>r.id===s.selected_id).number}</strong></div><div class="metric"><span>测试准确率</span><strong>${pct(s.final.result.test_accuracy)}</strong></div><div class="metric"><span>提示使用</span><strong>${assisted.length} 项</strong></div></div><p>${assisted.length?'下一步：换一批数据，独立完成曾借助提示的任务。':'下一步：换一批数据，验证这套方法能否迁移。'} 文字解释已保存，可在教师复核中查看。</p>${s.checks.filter(c=>c.passed).map(c=>`<details><summary>${esc(state.tasks.find(t=>t.id===c.task_id).title)} · 查看证据</summary><p>${esc(c.note||c.feedback)}</p><p class="muted">作答证据：${c.evidence_ids.map(esc).join('、')}<br>实验依据：${c.experiment_evidence_ids.map(esc).join('、')}</p></details>`).join('')}`;
    }
    lockControls();
  }
  $('identityForm').addEventListener('submit',async e=>{
    e.preventDefault(); if(busy)return; error(); busy=true;
    document.querySelectorAll('button,input,textarea,select').forEach(b=>b.disabled=true);
    try {const student=$('studentId').value.trim(); state=await request(`?student_id=${encodeURIComponent(student)}`); localStorage.setItem('pliac-ml-student',student); const url=new URL(location);url.searchParams.set('student_id',student);history.replaceState(null,'',url);lastStep='';render();$('saveState').textContent='已恢复学习记录';}catch(e){error(e.message);}finally{busy=false;document.querySelectorAll('button,input,textarea,select').forEach(b=>b.disabled=false);lockControls();}
  });
  $('startForm').addEventListener('submit',e=>{e.preventDefault();operate('start',{scene:$('scene').value,goal:$('goal').value});});
  $('runForm').addEventListener('submit',e=>{e.preventDefault();operate('run',{config:{train_percent:Number($('trainPercent').value),depth:Number($('depth').value),features:$('features').value,split:$('split').value}});});
  $('hintButton').addEventListener('click',()=>operate('hint'));
  $('checkForm').addEventListener('submit',e=>{e.preventDefault(); const value=id=>$(id)?.value;operate('check',{answer:{target:value('target'),features:value('inputChoice'),timing:value('timing'),run_id:value('chosenRun'),interpretation:value('interpretation'),basis:value('basis'),test_role:value('testRole'),note:$('note').value}});});
  $('transferButton').addEventListener('click',()=>operate('start',{scene:state.active.scene,goal:state.active.profile.goal}));
  $('exportLab').addEventListener('click',async()=>{try{const data=await request(`/export?student_id=${encodeURIComponent(state.student_id)}`);const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`ml-lab-${state.student_id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}catch(e){error(e.message);}});
  const downloadCode=document.createElement('button'); downloadCode.type='button'; downloadCode.textContent='下载 Python 文件'; downloadCode.id='downloadCode';
  $('codePreview').before(downloadCode);
  downloadCode.onclick=async()=>{try{const data=await request(`/export?student_id=${encodeURIComponent(state.student_id)}`);const run=state.active.runs.at(-1);if(!run)return;const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([data.scripts[`experiment-${run.number}.py`]],{type:'text/x-python;charset=utf-8'}));a.download=`experiment-${run.number}.py`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}catch(e){error(e.message);}};
  lockControls();
  $('identityForm').querySelectorAll('input,button').forEach(control=>control.disabled=false);
  if(new URLSearchParams(location.search).has('student_id'))$('identityForm').requestSubmit();
})();
