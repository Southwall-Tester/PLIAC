(async () => {
  'use strict';
  const account=await (window.PLIACAccountReady ||= fetch('/api/account/me').then(async response=>{
    if(response.status===401){location.assign('/login?next='+encodeURIComponent(location.pathname+location.search));return null;}
    return response.ok?response.json():{testing:true};
  }));
  if(!account)return;
  const $=id=>document.getElementById(id), params=new URLSearchParams(location.search), courseId=params.get('course_id');
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const storageKey=`pliac.student.${courseId}`;
  let state, selected, busy=false, student=account.user?.student_id||params.get('student_id')||localStorage.getItem(storageKey)||('learner-'+crypto.randomUUID().slice(0,8));
  $('studentId').value=student;
  if(account.user){$('studentId').readOnly=true;$('studentId').closest('label').hidden=true;$('loadStudent').hidden=true;}
  const query=()=>new URLSearchParams({course_id:courseId,student_id:student,mode:params.get('mode')||'auto'});
  async function api(path='',body){const response=await fetch('/api/linux-lab'+path+'?'+query(),body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,student_id:student})}:undefined);const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'请求失败。');return data;}
  async function run(fn){if(busy)return;busy=true;$('error').hidden=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);try{await fn();}catch(e){$('error').textContent=e.message;$('error').hidden=false;}finally{busy=false;document.querySelectorAll('button').forEach(b=>b.disabled=false);if(state)$('createRun').disabled=!state.ready;}}
  const graphPath=()=>state?.mode==='preview'?'/author':'/knowledge';
  const link=id=>graphPath()+'?'+new URLSearchParams({course_id:courseId,node_id:id,student_id:student});
  function chips(ids,nodes){const assessments=selected?.assessments||state?.assessments||{};return `<div class="concepts">${ids.map(id=>{const a=assessments[id];return `<a href="${link(id)}" target="_blank" rel="noopener" ${a?`title="自动评估：${esc(a.label)}" style="border-color:${PracticeAssessment.colors[a.level]}"`:''}>${esc(nodes.find(n=>n.id===id)?.title||id)}${a&&a.level!=='not_observed'?' · '+esc(a.label):''}</a>`;}).join('')}</div>`;}
  function renderAssessment(assessments,nodes){
    const rows=Object.entries(assessments||{}).filter(([,a])=>a.level!=='not_observed');
    $('masterySummary').textContent=rows.length?`已评估 ${rows.length} 个知识点。点击条目查看依据；课程图谱使用相同结果。`:'同步正式实训记录后，在这里查看知识点的自动评估。';
    $('masteryList').innerHTML=rows.map(([id,a])=>`<details data-assessment-node="${esc(id)}"><summary><span style="color:${PracticeAssessment.colors[a.level]}">●</span> ${esc(nodes.find(n=>n.id===id)?.title||id)} · ${esc(a.label)}</summary><a href="${link(id)}">在课程图谱中查看</a>${PracticeAssessment.detail(a,courseId,student)}</details>`).join('');
  }
  function renderStages(activity,nodes){$('stages').innerHTML=activity.stages.map(s=>`<article class="stage"><h3>${String(s.phase).padStart(2,'0')} · ${esc(s.title)}</h3><p>${esc(s.goal)}</p>${chips(s.node_ids,nodes)}</article>`).join('');}
  function dialogueContext(context){return (context||[]).map(d=>`<div class="dialogue-context"><p><strong>学习者原话</strong> · 此前提示 ${d.prior_help_level} 级</p><blockquote>${esc(d.learner_text)}</blockquote><details class="tutor-context"><summary>${d.assistant_origin==='model_inference'?'AI 当时的讲解（正确性待核对）':'当时提供的本地资料'}</summary><p class="speech">${esc(d.assistant_text)}</p></details><p class="muted">${d.analysis_origin==='model_inference'?'模型提出的待核验线索':'本地词项关联，不是语义确诊'}${d.echoes_tutor?'；原话与此前助教讲解重合，需换例核验理解':''}。AI 讲解作为帮助背景，不是学习者的作答。</p>${d.signals?.length?`<ul>${d.signals.map(s=>`<li>引用：<q>${esc(s.quote)}</q></li>`).join('')}</ul>`:''}</div>`).join('');}
  async function load(){state=await api();localStorage.setItem(storageKey,student);$('courseTitle').textContent=state.course.title+' · v'+state.course.version;$('modeNotice').textContent=(state.mode==='preview'?'草稿试跑：此模式预览课程草稿，不产生正式学生证据或掌握状态。':'已发布课程实训：检查记录、学习者解释和诊断分别保存。')+' '+state.notice;
    $('scene').innerHTML=Object.entries(state.scenes).map(([k,v])=>`<option value="${k}">${esc(v)}</option>`).join('');
    $('readerLink').href=graphPath()+'?'+new URLSearchParams({course_id:courseId,student_id:student});$('reviewLink').href='/review?'+query();$('reviewLink').hidden=state.mode==='preview';
    const keep=selected?.binding.binding_id||params.get('binding_id');$('runs').innerHTML=state.runs.length?state.runs.map(r=>`<option value="${r.binding_id}">${esc(r.created_at)} · v${r.course_version} · ${r.phases_passed}/9 · ${esc(state.scenes[r.scene])}</option>`).join(''):'<option value="">尚无周目</option>';
    if(keep&&state.runs.some(r=>r.binding_id===keep))$('runs').value=keep;
    renderStages(state.activity,state.nodes);
    renderAssessment(state.assessments,state.nodes);
    if($('runs').value)await select($('runs').value);else{selected=null;$('runControls').hidden=true;$('diagnoses').textContent='创建周目后，在终端开始实训。';$('coverage').textContent='';$('dialogueRecords').textContent='';$('dialogueSummary').textContent='在实验终端使用 lab chat，同步后查看与诊断关联的原话。';}
  }
  async function select(id){selected=await api('/runs/'+id);render();}
  function render(){const s=selected,sum=s.summary,diagnosis=sum.diagnosis;$('runControls').hidden=false;$('launch').hidden=!s.native_launch_available;$('launchCommand').textContent=s.launch_command;
    renderAssessment(s.assessments,s.nodes);
    const dialogues=s.raw_report?.dialogue_evidence||[],analyses=s.raw_report?.dialogue_analysis||[];
    $('dialogueSummary').textContent=`保留 ${dialogues.length}/${s.raw_report?.dialogue_total||0} 轮答疑。提问、AI 讲解和实际操作分别记录；聊天不按测验作答评分。${(s.raw_report?.dialogue_total||0)>dialogues.length?'较早对话超出保留窗口，不补推缺失内容。':''}`;
    $('dialogueRecords').innerHTML=dialogues.map(d=>{const c=diagnosis?.cases.find(c=>c.id==='dialogue-'+d.id),a=analyses.find(a=>a.turn_id===d.id);return `<details data-dialogue="${esc(d.id)}"><summary>第 ${d.phase} 关 · ${esc(d.learner.text.slice(0,65))}</summary>${c?chips(c.node_ids,s.nodes):'<p>当前未关联具体知识点，不据此推断知识问题。</p>'}${dialogueContext([{learner_text:d.learner.text,assistant_text:d.assistant.text,assistant_origin:d.assistant.origin,prior_help_level:d.prior_help_level,analysis_origin:a?.origin,signals:a?.signals}])}</details>`;}).join('');
    const option=[...$('runs').options].find(o=>o.value===s.binding.binding_id);if(option)option.textContent=`${s.binding.created_at} · v${s.binding.course_version} · ${sum.phases_passed||0}/9 · ${state.scenes[s.binding.scene]}`;
    $('runTitle').textContent=`${s.binding.mode==='preview'?'草稿试跑':'正式实训'} · 冻结课程 v${s.binding.course_version} · ${s.binding.binding_id.slice(0,8)}`;
    $('progress').textContent=`已同步 ${sum.phases_passed||0}/9 关。${sum.synced_at?'同步于 '+sum.synced_at:'尚未同步。'}`;renderStages(s.activity,s.nodes);
    $('coverage').textContent=diagnosis?`过程记录${diagnosis.coverage.tracking_enabled?'已开启':'已关闭'}，保留 ${diagnosis.coverage.retained_operations}/${diagnosis.coverage.total_operations} 条有限操作观察。${diagnosis.coverage.truncated?'较早观察已超出保留窗口；缺失部分不可推断。':''} 未采集原生 stderr、按键或 Vim 内部操作。`:'';
    $('diagnoses').innerHTML=diagnosis?.cases.length?diagnosis.cases.map(c=>`<article class="case" data-case="${esc(c.id)}"><span class="badge">诊断草稿 · 待核验</span><h3>第 ${c.phase} 关 · ${esc(c.observations[0])}</h3>${chips(c.node_ids,s.nodes)}
      <p><strong>观察事实</strong></p><ul>${c.observations.map(o=>`<li>${esc(o)}</li>`).join('')}</ul><p class="muted">${c.kind==='dialogue'?'答疑线索 · 不计作错误次数':c.kind==='operation'?`${c.failed_operations} 次命令失败 · ${c.command_attempts} 次相关执行 · 非知识错误计数`:`${c.check_attempts} 次尝试 · ${c.episodes} 个问题段`} · 提示 ${c.prompt_level??'未知'} 级${c.phases?.length>1?' · 本周目涉及关卡 '+c.phases.join('、'):''}</p>
      ${dialogueContext(c.dialogue_context)}
      <p><strong>候选原因，尚未确诊</strong></p><ul>${c.hypotheses.map(o=>`<li>${esc(o)}</li>`).join('')}</ul>
      <details><summary>证据链与诊断质量</summary><p>原始报告：${esc(sum.raw_digest)}</p><pre>${esc(c.evidence_refs.join('\n'))}</pre><p>证据可追溯：${c.quality.traceable?'是':'否'}；知识关联：${c.quality.mapped?'是':'否'}；学习者解释：${c.quality.has_learner_explanation?'已有，待复核':'尚缺'}；人工复核：未完成。</p><p>先修排查候选（不表示这些知识有缺陷）：</p>${chips(c.prerequisite_candidates,s.nodes)}<pre>${esc(JSON.stringify({checks:sum.events.filter(e=>c.evidence_refs.includes('check:'+e.id)),operations:(s.raw_report?.operations||[]).filter(e=>c.evidence_refs.includes('operation:'+e.sequence)),reference_lookups:(s.raw_report?.reference_lookups||[]).filter(e=>c.evidence_refs.includes('reference:'+e.sequence)),input_patterns:(s.raw_report?.input_patterns||[]).filter(e=>c.evidence_refs.includes('input:'+e.id))},null,2))}</pre></details>
      <p><strong>核验问题</strong></p><ul>${c.verification_questions.map(q=>`<li>${esc(q.question)}</li>`).join('')}</ul>
      ${c.learner_explanations.map(r=>`<blockquote>学习者原话：${esc(r.text)}<br><small>提示 ${r.prompt_level} 级 · 待复核</small></blockquote>`).join('')}
      <form data-reflect="${esc(c.id)}"><label>解释关联知识点<select name="node_id">${c.node_ids.map(n=>`<option value="${n}">${esc(s.nodes.find(x=>x.id===n)?.title||n)}</option>`).join('')}</select></label><label>你的解释：发生了什么、依据是什么、如何验证<textarea name="text" required maxlength="3000"></textarea></label><label>作答时使用的提示<select name="prompt_level">${[0,1,2,3,4].map(n=>`<option value="${n}">${n} 级${n===0?'（独立解释）':''}</option>`).join('')}</select></label><button type="submit">保存原始解释</button></form><p class="muted">${esc(c.next_action)}</p></article>`).join(''):(diagnosis?'<p>当前没有可生成问题诊断的错误证据；不据此判定掌握。继续实训或进行独立解释与复测。</p>':'<p>在终端完成操作后，点击“同步记录与诊断”。</p>');
    document.querySelectorAll('[data-reflect]').forEach(form=>{const c=diagnosis.cases.find(c=>c.id===form.dataset.reflect);form.elements.prompt_level.value=Math.max(c.prompt_level||0,...sum.events.filter(e=>e.phase===c.phase).map(e=>e.prompt_level));form.onsubmit=e=>{e.preventDefault();run(async()=>{selected=await api('/runs/'+s.binding.binding_id+'/reflect',{...Object.fromEntries(new FormData(form)),prompt_level:Number(form.elements.prompt_level.value),case_id:form.dataset.reflect,request_id:crypto.randomUUID()});render();$('status').textContent='原始解释已保存，诊断仍待复核。';});};});
  }
  $('themeButton').onclick=()=>GraphTheme.toggle();$('loadStudent').onclick=()=>run(async()=>{student=$('studentId').value.trim();selected=null;await load();localStorage.setItem(storageKey,student);});
  $('runs').onchange=()=>run(()=>select($('runs').value));
  $('createRun').onclick=()=>run(async()=>{selected=await api('/runs',{mode:state.mode,course_version:state.course.version,scene:$('scene').value});await load();$('status').textContent='周目已创建。点击打开实训终端开始；旧周目保留。';});
  $('launch').onclick=()=>run(async()=>{const r=await api('/runs/'+selected.binding.binding_id+'/launch',{});$('status').textContent=r.notice;});
  $('sync').onclick=()=>run(async()=>{selected=await api('/runs/'+selected.binding.binding_id+'/sync',{});render();$('status').textContent='检查与过程记录已同步。';});
  $('export').onclick=()=>{const blob=new Blob([JSON.stringify(selected,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='LinuxLab-diagnostic-draft-'+selected.binding.binding_id+'.json';a.click();URL.revokeObjectURL(url);};
  run(async()=>{if(!courseId)throw new Error('请从课程入口进入 LinuxLab。');await load();});
})();
