(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const teacher = location.pathname === '/review';
  const courseId = new URLSearchParams(location.search).get('course_id') || '';
  const demo = courseId === 'ml_acceptance_demo';
  const query = new URLSearchParams({course_id: courseId});
  let requestedNode = new URLSearchParams(location.search).get('node_id');
  const labels = {unknown:'尚未涉及', uncertain:'待核验', needs_review:'需要补学', mastered:'当前已掌握'};
  // Old session snapshots keep their original wording on disk.
  function displayReason(text) {
    return ({
      '尚无学习证据，不能据此判断不会。':'待完成首次作答。',
      '示范客观题独立通过；仅表示本课程该节点的规则核验结果。':'本题独立作答通过。',
      '已到间隔复习时间，请先做简短复测；到期不代表不会。':'已到复习时间，请完成复测。',
      '教师尚未配置章节达标规则；以下仅汇总学习状态。':'请教师配置本章必达节点。'
    })[text] || text;
  }
  function paragraphText(text) {
    return text.replace('这只是教学算例，不是实际训练产出的性能承诺。', '')
      .replace('这里只报告实际观察，不宣称它对所有数据都成立。', '');
  }
  let state, draftGraph, studentId = '', busy = false, annotationId, saveTimer, failedRequest;
  const storageKey = `pliac.student.${courseId}`;
  function error(message = '') { $('workspaceError').textContent = message; $('workspaceError').hidden = !message; }
  async function api(path, body, method = 'POST') {
    let response;
    try { response = await fetch(`${path}${path.includes('?') ? '&' : '?'}${query}`, body === undefined ? {} : {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}); }
    catch { throw new Error('连接中断。未提交的文字仍在输入框，请恢复连接后重试。'); }
    const result = await response.json();
    if (!response.ok) { const failure = new Error(typeof result.detail === 'string' ? result.detail : '请求未完成，请重试。'); failure.status = response.status; throw failure; }
    return result;
  }
  function studentQuery() { return new URLSearchParams({student_id:studentId}); }
  function download(name, data, type = 'application/json') {
    const url = URL.createObjectURL(new Blob([data], {type:`${type};charset=utf-8`}));
    const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function run(action) {
    if (busy) return;
    busy = true; error();
    document.querySelectorAll('button,input,textarea,select').forEach(b => b.disabled = true);
    try { await action(); }
    catch (failure) { error(failure.message); $('saveStatus').textContent = '未完成，请检查提示'; }
    finally { busy = false; document.querySelectorAll('button,input,textarea,select').forEach(b => b.disabled = false); setAvailability(); }
  }
  function setAvailability() {
    if (!state) return;
    const current = state.current_lesson;
    $('hintButton').disabled = !current?.task || current.prompt_level >= 4 || state.course_changed;
    $('answerForm').querySelector('button[type=submit]').disabled = !current || state.course_changed;
    $('saveDraftButton').disabled = !current || state.course_changed;
    if (demo && current?.status === 'assessed') {
      $('answerForm').querySelectorAll('button,input,textarea').forEach(b => b.disabled = true);
    }
    const complete = state.chapters.length > 0 && state.chapters.every(c => c.passed);
    $('nextLesson').disabled = !state.workspace.onboarded || complete;
    $('nextLesson').textContent = complete ? '本课程当前已完成' : demo && current && state.learner.states[current.node_id].status !== 'mastered' ? '安排补学 / 复测' : '安排下一小节';
  }
  async function mutate(operation, values = {}, {renderPage = true} = {}) {
    const data = {student_id:studentId, course_version:state.course.version, ...values};
    const signature = JSON.stringify({operation, data});
    const requestId = failedRequest?.signature === signature ? failedRequest.id : crypto.randomUUID();
    failedRequest = {signature, id:requestId};
    try {
      state = await api(`/api/learning/${operation}`, {...data, expected_version:state.learner.version, request_id:requestId});
      failedRequest = null;
      if (renderPage) render();
      $('saveStatus').textContent = '已保存到本机';
    } catch (failure) {
      if (failure.status) failedRequest = null;
      throw failure;
    }
  }
  function render() {
    $('refreshButton').hidden = false; $('exportButton').hidden = false;
    $('pageTitle').textContent = `${state.course?.title || '课程'} · ${teacher ? '教师复核' : '学习工作台'}`;
    $('notice').hidden = !!state.course && !state.course_changed;
    $('notice').textContent = state.course_changed ? '课程已有新发布版本。这里保留了原小节与作答，请安排新小节后继续。' : state.publication.notice;
    $('studentWorkspace').hidden = teacher || !state.course;
    $('teacherWorkspace').hidden = !teacher;
    $('taskAuthoring').hidden = !teacher || demo;
    $('policyForm').closest('.panel').hidden = demo;
    $('courseProgress').hidden = !demo || teacher;
    $('courseProgress').textContent = demo ? `学习进度：${Object.values(state.learner.states).filter(s => s.status === 'mastered').length} / ${state.course.nodes.length} 小节已通过独立核验` : '';
    $('onboarding').hidden = teacher || !state.course || state.workspace.onboarded;
    if (teacher) { renderTeacher(); return; }
    if (!state.course) return;
    $('goals').value = state.learner.profile.goals;
    $('background').value = state.learner.profile.background;
    $('interests').value = state.learner.profile.interests.join('，');
    $('selfAssessments').innerHTML = state.course.nodes.map(n => `<label>${esc(n.title)}<select data-assess="${esc(n.id)}"><option value="">暂不自评</option><option value="new">尚未学过</option><option value="unsure">学过但不确定</option><option value="confident">能够独立解释和应用</option></select></label>`).join('');
    for (const [node, item] of Object.entries(state.workspace.self_assessments)) {
      const select = [...document.querySelectorAll('[data-assess]')].find(s => s.dataset.assess === node);
      if (select) select.value = item.value;
    }
    $('nodeList').innerHTML = state.course.chapters.map(c => `<h3>${esc(c.title)}</h3>${state.course.nodes.filter(n => n.chapter_id === c.id).map(n => `<button class="node-button ${state.current_lesson?.node_id === n.id ? 'active' : ''}" data-node="${esc(n.id)}" title="${esc(labels[state.learner.states[n.id].status])}"><span class="state-dot ${esc(state.learner.states[n.id].status)}"></span>${esc(n.title)}</button>`).join('')}`).join('');
    renderLesson(); renderReports(); renderHandbook(); setAvailability();
  }
  function renderLesson() {
    const lesson = state.current_lesson;
    $('taskPanel').hidden = !lesson;
    if (!lesson) { $('lessonContent').innerHTML = '<p class="muted">保存起点资料后，安排第一小节。</p>'; return; }
    const names = Object.fromEntries(state.course.nodes.map(n => [n.id,n.title]));
    const gaps = lesson.prerequisite_gaps.filter(i => i !== lesson.node_id);
    $('lessonContent').innerHTML = `<h3>${esc(lesson.title)}</h3><p class="reason">安排依据：${esc(displayReason(lesson.reason))}${gaps.length ? `<br>相关先修仍待核验：${gaps.map(i => esc(names[i] || i)).join('、')}` : ''}</p>${lesson.paragraphs.filter(p => p.text).map(p => `<div class="paragraph"><div class="paragraph-body">${p.heading ? `<h4>${esc(p.heading)}</h4>` : ''}<p>${esc(paragraphText(p.text))}</p></div><button data-paragraph="${esc(p.id)}">不明白</button></div>`).join('')}<div>${lesson.resources.length ? '<h3>可选学习材料</h3>' + lesson.resources.map(r => `<a class="resource-card" data-resource="${esc(r.id)}" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}<small>${esc(r.organization)} · ${esc(r.applicable_segment || '')}</small></a>`).join('') : demo ? '' : '<p class="muted">暂无学习材料。</p>'}</div>${(lesson.sources || []).map(s => `<a class="resource-card" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">延伸阅读：${esc(s.title)}<small>${esc(s.locator)}</small></a>`).join('')}${lesson.annotations.length ? `<details><summary>已记录 ${lesson.annotations.length} 处困惑</summary>${lesson.annotations.map(a => `<p>${esc(a.question)}</p>`).join('')}</details>` : ''}`;
    $('questionText').textContent = lesson.question;
    $('promptBadge').textContent = demo && lesson.prompt_level === 4 ? '已显示本题解析' : lesson.prompt_level ? `已使用 ${lesson.prompt_level} 级提示` : '本题尚未使用提示';
    $('taskNotice').textContent = demo ? '' : lesson.task ? '提交后由教师复核。' : '请先记录理解与困惑，教师将补充诊断题。';
    $('taskNotice').hidden = !$('taskNotice').textContent;
    $('hintList').innerHTML = lesson.hints.map(h => `<div class="hint">提示 ${h.level}：${esc(h.text)}</div>`).join('');
    $('answerText').value = state.workspace.drafts[lesson.id]?.text || '';
    $('answerText').maxLength = demo ? 3500 : 4000;
    $('answerText').placeholder = demo ? '可选：写下你的判断理由。选项会和思路一起保存。' : '写下结论，也写下你这样判断的原因。';
    $('answerChoices').hidden = !lesson.options;
    $('answerChoices').innerHTML = (lesson.options || []).map(o => `<label class="answer-choice"><input type="radio" name="answerChoice" value="${esc(o.id)}" ${state.workspace.drafts[lesson.id]?.choice_id === o.id ? 'checked' : ''}><span>${esc(o.id)}. ${esc(o.text)}</span></label>`).join('');
    $('responses').innerHTML = lesson.responses.map(r => {
      const diagnoses = state.learner.diagnoses.filter(d => d.evidence_ids.includes(r.evidence_id));
      return `<article><span class="badge">${r.prompt_level ? `${r.prompt_level} 级提示或解析后作答` : '未使用本题提示'}</span><p>${esc(r.text)}</p>${r.judgement ? `<p class="quiz-feedback"><strong>${r.judgement.passed ? '回答正确' : '需要再想一想'}</strong><br>${esc(r.judgement.explanation)}</p>` : ''}${diagnoses.length ? diagnoses.map(d => `<p class="muted">${esc(labels[d.status])} · ${esc(displayReason(d.basis))}</p>`).join('') : '<p class="muted">已保存原始作答，等待复核。</p>'}</article>`;
    }).join('');
  }
  function renderReports() {
    $('chapterReports').innerHTML = state.chapters.map(c => `<article class="report-row"><h3>${esc(c.title)} <span class="badge">${c.passed ? '当前达标' : c.outcome === 'not_configured' ? '待配置规则' : '待补学 / 核验'}</span></h3><p>${esc(c.advice)}</p><details><summary>查看 ${c.nodes.length} 个节点及判断依据</summary><ul>${c.nodes.map(n => `<li>${esc(n.title)} · ${esc(labels[n.status])}<br><small>${esc(displayReason(n.reason))} · ${n.evidence_ids.length} 条证据</small></li>`).join('')}</ul></details><button data-report="${esc(c.chapter_id)}">保存本次报告</button></article>`).join('') + `<p class="muted">已保存 ${state.workspace.reports.length} 份报告快照；历史快照随完整记录导出。</p>`;
  }
  function renderHandbook() {
    $('handbook').innerHTML = state.handbook.length ? state.handbook.map(h => `<article class="handbook-entry"><h3>${esc(h.title)}</h3><span class="badge">${esc(labels[h.status])}</span><p>${esc(displayReason(h.reason))}</p><p>${esc(h.concept)}</p><p class="muted">${esc(h.next_step)}</p>${h.prompted_evidence_ids.length ? '<p class="muted">本节点存在提示后作答。</p>' : ''}${h.repeated_submissions > 1 ? '<p class="muted">已收录多次作答。</p>' : ''}<details><summary>原始证据（${h.evidence_ids.length}）</summary>${h.evidence_ids.map(id => { const e = state.learner.evidence.find(x => x.id === id); return e ? `<p>${esc(e.text)}</p><small>${esc(id)} · 课程 v${e.course_version}</small>` : ''; }).join('')}</details></article>`).join('') : '<p class="muted">暂无手册条目。</p>';
  }
  function renderTeacher() {
    const selected = $('reviewNode').value;
    $('reviewNode').innerHTML = (state.course?.nodes || []).map(n => `<option value="${esc(n.id)}">${esc(n.title)}</option>`).join('');
    if (state.course?.nodes.some(n => n.id === selected)) $('reviewNode').value = selected;
    renderEvidence();
    const chapter = $('policyChapter').value;
    $('policyChapter').innerHTML = (draftGraph?.chapters || []).map(c => `<option value="${esc(c.id)}">${esc(c.title)}</option>`).join('');
    if (draftGraph?.chapters.some(c => c.id === chapter)) $('policyChapter').value = chapter;
    renderPolicy();
    const taskNode = $('taskNode').value;
    $('taskNode').innerHTML = (draftGraph?.nodes || []).map(n => `<option value="${esc(n.id)}">${esc(n.title)}</option>`).join('');
    if (draftGraph?.nodes.some(n => n.id === taskNode)) $('taskNode').value = taskNode;
    renderTask();
  }
  function renderTask() {
    const node = draftGraph?.nodes.find(n => n.id === $('taskNode').value);
    $('taskQuestion').value = node?.check_question || '';
    $('taskAnswer').value = node?.expected_answer || '';
    $('taskRubric').value = (node?.check_task?.rubric || []).join('\n');
    for (let i = 1; i <= 4; i++) $(`taskHint${i}`).value = node?.check_task?.hint_levels?.[i - 1] || '';
    $('taskVersion').textContent = node?.check_task ? `草稿任务 v${node.check_task.version} · 修改内容会递增版本并退回节点审核。` : '此节点尚未配置正式诊断任务。';
  }
  function renderEvidence() {
    const nodeId = $('reviewNode').value;
    const task = state.teacher_tasks?.[nodeId];
    const raw = state.learner.evidence.filter(e => e.node_id === nodeId && e.course_version === state.course?.version);
    $('reviewEvidence').innerHTML = (task ? `<p>${esc(task.question)}</p><details><summary>教师参考判据</summary><p>${esc(task.expected_answer)}</p><ul>${task.rubric.map(r => `<li>${esc(r)}</li>`).join('')}</ul></details>` : '') + (raw.length ? raw.map(e => `<article class="evidence-entry"><label><input type="checkbox" data-evidence="${esc(e.id)}">${esc(e.source_type)} · 提示 ${e.prompt_level ?? '未知'} 级 · v${e.course_version}</label><pre>${esc(e.text)}</pre><small>${esc(e.id)} · ${esc(e.created_at)}</small></article>`).join('') : '<p class="muted">本节点当前版本尚无学习证据。</p>');
    $('diagnosisHistory').innerHTML = state.learner.diagnoses.filter(d => d.node_id === nodeId).map(d => `<p>${esc(labels[d.status])} · ${esc(d.reviewer)}<br>${esc(displayReason(d.basis))}</p>`).join('') || '<p class="muted">尚无历史判断。</p>';
  }
  function renderPolicy() {
    const chapter = draftGraph?.chapters.find(c => c.id === $('policyChapter').value);
    const selected = chapter?.completion_policy?.required_node_ids || [];
    $('policyNodes').innerHTML = (draftGraph?.nodes || []).filter(n => n.chapter_id === chapter?.id).map(n => `<label class="policy-node"><input type="checkbox" data-policy-node="${esc(n.id)}" ${selected.includes(n.id) ? 'checked' : ''}>${esc(n.title)}</label>`).join('');
    $('policyAuthor').value = chapter?.completion_policy?.configured_by || '';
    $('policyBasis').value = chapter?.completion_policy?.basis || '';
  }
  async function load() {
    state = await api(`/api/learning${teacher ? '/teacher' : ''}?${studentQuery()}`);
    if (teacher) draftGraph = (await api('/api/course-graph?view=draft')).graph;
    render(); $('saveStatus').textContent = '已恢复最近保存的记录';
    await openRequestedNode();
  }
  async function openRequestedNode() {
    if (teacher || !requestedNode || !state.workspace.onboarded) return;
    const node = requestedNode; requestedNode = null;
    if (state.course.nodes.some(n => n.id === node) && state.current_lesson?.node_id !== node) await mutate('next', {node_id:node});
  }
  async function saveDraft() {
    clearTimeout(saveTimer);
    if (!state?.current_lesson || state.course_changed) return;
    const lesson = state.current_lesson;
    const text = $('answerText').value;
    const choice_id = choiceValue();
    if (text === (state.workspace.drafts[lesson.id]?.text || '') && choice_id === (state.workspace.drafts[lesson.id]?.choice_id || '')) return;
    await mutate('draft', {lesson_id:lesson.id, text, ...(demo ? {choice_id} : {})}, {renderPage:false});
  }
  $('themeButton').onclick = () => GraphTheme.toggle();
  $('graphLink').href = `/knowledge?${query}`;
  $('authorLink').href = `/author?${query}`;
  $('roleLink').href = `${teacher ? '/learn' : '/review'}?${query}`;
  $('roleLink').textContent = teacher ? '学习工作台' : '教师复核';
  try { $('studentId').value = localStorage.getItem(storageKey) || ''; } catch {}
  $('studentId').value = new URLSearchParams(location.search).get('student_id') || $('studentId').value;
  if (demo && !$('studentId').value) $('studentId').value = 'demo-' + crypto.randomUUID().slice(0,8);
  function choiceValue() { return document.querySelector('[name=answerChoice]:checked')?.value || ''; }
  $('identityForm').onsubmit = event => { event.preventDefault(); run(async () => { await saveDraft(); studentId = $('studentId').value.trim(); await load(); $('labLink').href = `/ml-lab?student_id=${encodeURIComponent(studentId)}`; try { localStorage.setItem(storageKey, studentId); } catch {} }); };
  $('refreshButton').onclick = () => run(async () => { if (!teacher) await saveDraft(); await load(); });
  $('onboardForm').onsubmit = event => { event.preventDefault(); run(async () => {
    const selfAssessments = Object.fromEntries([...document.querySelectorAll('[data-assess]')].filter(s => s.value).map(s => [s.dataset.assess,s.value]));
    await mutate('onboard', {goals:$('goals').value, background:$('background').value, interests:$('interests').value.split(/[,，]/).map(x => x.trim()).filter(Boolean), self_assessments:selfAssessments});
    await openRequestedNode();
  }); };
  $('profileButton').onclick = () => { $('onboarding').hidden = !$('onboarding').hidden; if (!$('onboarding').hidden) $('onboarding').scrollIntoView({behavior:'smooth'}); };
  $('nextLesson').onclick = () => run(async () => { await saveDraft(); await mutate('next'); });
  $('nodeList').onclick = event => { const button = event.target.closest('[data-node]'); if (button) run(async () => { await saveDraft(); await mutate('next', {node_id:button.dataset.node}); }); };
  function scheduleSave() { clearTimeout(saveTimer); saveTimer = setTimeout(() => { if (busy) scheduleSave(); else run(saveDraft); }, 900); }
  $('answerText').oninput = () => { $('saveStatus').textContent = '正在编辑'; scheduleSave(); };
  $('answerChoices').onchange = () => { $('saveStatus').textContent = '正在编辑'; scheduleSave(); };
  $('saveDraftButton').onclick = () => run(saveDraft);
  $('answerForm').onsubmit = event => { event.preventDefault(); clearTimeout(saveTimer); const text = $('answerText').value, choice_id = choiceValue(); if (demo ? !choice_id : !text.trim()) { error(demo ? '请先选择一个选项。' : '请先写下你的思路。'); return; } run(() => mutate('answer', {lesson_id:state.current_lesson.id, text, ...(demo ? {choice_id} : {})})); };
  $('hintButton').onclick = () => run(async () => { await saveDraft(); await mutate('hint', {lesson_id:state.current_lesson.id}); });
  $('lessonContent').onclick = event => {
    const paragraph = event.target.closest('[data-paragraph]');
    if (paragraph) { annotationId = paragraph.dataset.paragraph; const text = paragraphText(state.current_lesson.paragraphs.find(p => p.id === annotationId).text); const selected = window.getSelection()?.toString(); $('annotationQuote').value = selected && text.includes(selected) ? selected.slice(0,3000) : text.slice(0,3000); $('annotationQuestion').value = ''; $('annotationDialog').showModal(); }
    const resource = event.target.closest('[data-resource]');
    if (resource) { event.preventDefault(); if (busy) return; const tab = window.open('about:blank', '_blank'); if (tab) tab.opener = null; run(async () => { try { await saveDraft(); await mutate('resource', {lesson_id:state.current_lesson.id, resource_id:resource.dataset.resource}); if (tab) tab.location.href = resource.href; } catch (failure) { tab?.close(); throw failure; } }); }
  };
  $('cancelAnnotation').onclick = () => $('annotationDialog').close();
  $('annotationForm').onsubmit = event => { event.preventDefault(); run(async () => { await saveDraft(); await mutate('annotate', {lesson_id:state.current_lesson.id, paragraph_id:annotationId, quote:$('annotationQuote').value, question:$('annotationQuestion').value}); $('annotationDialog').close(); }); };
  $('chapterReports').onclick = event => { const button = event.target.closest('[data-report]'); if (button) run(async () => { await saveDraft(); await mutate('report', {chapter_id:button.dataset.report}); }); };
  $('exportButton').onclick = () => run(async () => { if (!teacher) await saveDraft(); const data = await api(`/api/course-graph/learner/export?${studentQuery()}`); download(`PLIAC-${studentId}.json`, JSON.stringify(data,null,2)); });
  $('exportHandbook').onclick = () => download('个人知识手册.txt', state.handbook.map(h => `${h.title} · ${labels[h.status]}\n${displayReason(h.reason)}\n${h.concept}\n下一步：${h.next_step}\n证据：${h.evidence_ids.join(', ')}\n`).join('\n'), 'text/plain');
  $('reviewNode').onchange = renderEvidence;
  $('policyChapter').onchange = renderPolicy;
  $('taskNode').onchange = renderTask;
  $('taskEditorForm').onsubmit = event => { event.preventDefault(); run(async () => {
    const result = await api('/api/learning/teacher/task', {node_id:$('taskNode').value, question:$('taskQuestion').value, expected_answer:$('taskAnswer').value, rubric:$('taskRubric').value.split('\n').map(x => x.trim()).filter(Boolean), hint_levels:[1,2,3,4].map(i => $(`taskHint${i}`).value), expected_version:draftGraph.version});
    draftGraph = result.graph; renderTask(); $('saveStatus').textContent = '任务草稿已保存，请重新审核节点并发布';
  }); };
  $('reviewForm').onsubmit = event => { event.preventDefault(); run(async () => {
    const nodeId = $('reviewNode').value;
    const ids = [...document.querySelectorAll('[data-evidence]:checked')].map(x => x.dataset.evidence);
    const resolves = $('resolvePrior').checked ? state.learner.diagnoses.filter(d => d.node_id === nodeId).map(d => d.id) : [];
    await api('/api/course-graph/diagnoses', {student_id:studentId, course_version:state.course.version, expected_version:state.learner.version, node_id:nodeId, evidence_ids:ids, status:$('reviewStatus').value, review_status:'reviewed', basis:$('reviewBasis').value, reviewer:$('reviewer').value, is_retest:$('isRetest').checked, resolves_diagnosis_ids:resolves});
    $('reviewBasis').value = ''; $('resolvePrior').checked = false; await load();
  }); };
  $('policyForm').onsubmit = event => { event.preventDefault(); run(async () => {
    const result = await api('/api/learning/teacher/chapter-policy', {chapter_id:$('policyChapter').value, required_node_ids:[...document.querySelectorAll('[data-policy-node]:checked')].map(x => x.dataset.policyNode), configured_by:$('policyAuthor').value, basis:$('policyBasis').value, expected_version:draftGraph.version});
    draftGraph = result.graph; renderPolicy(); $('saveStatus').textContent = '规则草稿已保存，请审核发布';
  }); };
  window.addEventListener('beforeunload', event => { if (state?.current_lesson && !teacher && ($('answerText').value !== (state.workspace.drafts[state.current_lesson.id]?.text || '') || choiceValue() !== (state.workspace.drafts[state.current_lesson.id]?.choice_id || ''))) { event.preventDefault(); event.returnValue = ''; } });
})();
