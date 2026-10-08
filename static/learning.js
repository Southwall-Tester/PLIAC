(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const teacher = location.pathname === '/review';
  const courseId = new URLSearchParams(location.search).get('course_id') || '';
  const query = new URLSearchParams({course_id: courseId});
  const labels = {unknown:'尚未涉及', uncertain:'待核验', needs_review:'需要补学', mastered:'当前已掌握'};
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
    $('lessonContent').innerHTML = `<h3>${esc(lesson.title)}</h3><p class="reason">安排依据：${esc(lesson.reason)}${gaps.length ? `<br>相关先修仍待核验：${gaps.map(i => esc(names[i] || i)).join('、')}` : ''}</p>${lesson.paragraphs.filter(p => p.text).map(p => `<div class="paragraph"><p>${esc(p.text)}</p><button data-paragraph="${esc(p.id)}">不明白</button></div>`).join('')}<div>${lesson.resources.length ? '<h3>可选学习材料</h3>' + lesson.resources.map(r => `<a class="resource-card" data-resource="${esc(r.id)}" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}<small>${esc(r.organization)} · ${esc(r.applicable_segment || '')}</small></a>`).join('') : '<p class="muted">当前没有满足前置要求的已审核补充资源。</p>'}</div>${lesson.annotations.length ? `<details><summary>已记录 ${lesson.annotations.length} 处困惑</summary>${lesson.annotations.map(a => `<p>${esc(a.question)}</p>`).join('')}</details>` : ''}`;
    $('questionText').textContent = lesson.question;
    $('promptBadge').textContent = lesson.prompt_level ? `已使用 ${lesson.prompt_level} 级提示` : '本题尚未使用提示';
    $('taskNotice').textContent = lesson.task ? '作答提交后进入人工复核。同一道题已看过的提示会持续记录，重新打开不会重置。' : '此节点尚未配置正式诊断题。可记录理解与困惑，之后由教师补充任务验证。';
    $('hintList').innerHTML = lesson.hints.map(h => `<div class="hint">提示 ${h.level}：${esc(h.text)}</div>`).join('');
    $('answerText').value = state.workspace.drafts[lesson.id]?.text || '';
    $('responses').innerHTML = lesson.responses.map(r => {
      const diagnoses = state.learner.diagnoses.filter(d => d.evidence_ids.includes(r.evidence_id));
      return `<article><span class="badge">${r.prompt_level ? `${r.prompt_level} 级提示后作答` : '未使用本题提示'}</span><p>${esc(r.text)}</p>${diagnoses.length ? diagnoses.map(d => `<p class="muted">${esc(labels[d.status])} · ${esc(d.basis)}</p>`).join('') : '<p class="muted">已保存原始作答，等待复核。</p>'}</article>`;
    }).join('');
  }
  function renderReports() {
    $('chapterReports').innerHTML = state.chapters.map(c => `<article class="report-row"><h3>${esc(c.title)} <span class="badge">${c.passed ? '当前达标' : c.outcome === 'not_configured' ? '待配置规则' : '待补学 / 核验'}</span></h3><p>${esc(c.advice)}</p><details><summary>查看 ${c.nodes.length} 个节点及判断依据</summary><ul>${c.nodes.map(n => `<li>${esc(n.title)} · ${esc(labels[n.status])}<br><small>${esc(n.reason)} · ${n.evidence_ids.length} 条证据</small></li>`).join('')}</ul></details><button data-report="${esc(c.chapter_id)}">保存本次报告</button></article>`).join('') + `<p class="muted">已保存 ${state.workspace.reports.length} 份报告快照；历史快照随完整记录导出。</p>`;
  }
  function renderHandbook() {
    $('handbook').innerHTML = state.handbook.length ? state.handbook.map(h => `<article class="handbook-entry"><h3>${esc(h.title)}</h3><span class="badge">${esc(labels[h.status])}</span><p>${esc(h.reason)}</p><p>${esc(h.concept)}</p><p class="muted">${esc(h.next_step)}</p>${h.prompted_evidence_ids.length ? '<p class="muted">本节点存在提示后作答。</p>' : ''}${h.repeated_submissions > 1 ? '<p class="muted">存在多次提交，供复核过程参考，不据此判定不会。</p>' : ''}<details><summary>原始证据（${h.evidence_ids.length}）</summary>${h.evidence_ids.map(id => { const e = state.learner.evidence.find(x => x.id === id); return e ? `<p>${esc(e.text)}</p><small>${esc(id)} · 课程 v${e.course_version}</small>` : ''; }).join('')}</details></article>`).join('') : '<p class="muted">还没有需要收录的困惑、补学项或提示依赖记录。</p>';
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
  }
  function renderEvidence() {
    const nodeId = $('reviewNode').value;
    const task = state.teacher_tasks?.[nodeId];
    const raw = state.learner.evidence.filter(e => e.node_id === nodeId && e.course_version === state.course?.version);
    $('reviewEvidence').innerHTML = (task ? `<p>${esc(task.question)}</p><details><summary>教师参考判据</summary><p>${esc(task.expected_answer)}</p><ul>${task.rubric.map(r => `<li>${esc(r)}</li>`).join('')}</ul></details>` : '') + (raw.length ? raw.map(e => `<article class="evidence-entry"><label><input type="checkbox" data-evidence="${esc(e.id)}">${esc(e.source_type)} · 提示 ${e.prompt_level ?? '未知'} 级 · v${e.course_version}</label><pre>${esc(e.text)}</pre><small>${esc(e.id)} · ${esc(e.created_at)}</small></article>`).join('') : '<p class="muted">本节点当前版本尚无学习证据。</p>');
    $('diagnosisHistory').innerHTML = state.learner.diagnoses.filter(d => d.node_id === nodeId).map(d => `<p>${esc(labels[d.status])} · ${esc(d.reviewer)}<br>${esc(d.basis)}</p>`).join('') || '<p class="muted">尚无历史判断。</p>';
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
  }
  async function saveDraft() {
    clearTimeout(saveTimer);
    if (!state?.current_lesson || state.course_changed) return;
    const lesson = state.current_lesson;
    const text = $('answerText').value;
    if (text === (state.workspace.drafts[lesson.id]?.text || '')) return;
    await mutate('draft', {lesson_id:lesson.id, text}, {renderPage:false});
  }
  $('themeButton').onclick = () => GraphTheme.toggle();
  $('graphLink').href = `/knowledge?${query}`;
  $('authorLink').href = `/author?${query}`;
  $('roleLink').href = `${teacher ? '/learn' : '/review'}?${query}`;
  $('roleLink').textContent = teacher ? '学习工作台' : '教师复核';
  try { $('studentId').value = localStorage.getItem(storageKey) || ''; } catch {}
  $('identityForm').onsubmit = event => { event.preventDefault(); run(async () => { await saveDraft(); studentId = $('studentId').value.trim(); await load(); try { localStorage.setItem(storageKey, studentId); } catch {} }); };
  $('refreshButton').onclick = () => run(async () => { const text = $('answerText').value, lessonId = state.current_lesson?.id; await load(); if (lessonId === state.current_lesson?.id && text) $('answerText').value = text; });
  $('onboardForm').onsubmit = event => { event.preventDefault(); run(async () => {
    const selfAssessments = Object.fromEntries([...document.querySelectorAll('[data-assess]')].filter(s => s.value).map(s => [s.dataset.assess,s.value]));
    await mutate('onboard', {goals:$('goals').value, background:$('background').value, interests:$('interests').value.split(/[,，]/).map(x => x.trim()).filter(Boolean), self_assessments:selfAssessments});
  }); };
  $('profileButton').onclick = () => { $('onboarding').hidden = !$('onboarding').hidden; if (!$('onboarding').hidden) $('onboarding').scrollIntoView({behavior:'smooth'}); };
  $('nextLesson').onclick = () => run(async () => { await saveDraft(); await mutate('next'); });
  $('nodeList').onclick = event => { const button = event.target.closest('[data-node]'); if (button) run(async () => { await saveDraft(); await mutate('next', {node_id:button.dataset.node}); }); };
  function scheduleSave() { clearTimeout(saveTimer); saveTimer = setTimeout(() => { if (busy) scheduleSave(); else run(saveDraft); }, 900); }
  $('answerText').oninput = () => { $('saveStatus').textContent = '正在编辑'; scheduleSave(); };
  $('saveDraftButton').onclick = () => run(saveDraft);
  $('answerForm').onsubmit = event => { event.preventDefault(); clearTimeout(saveTimer); const text = $('answerText').value; if (!text.trim()) { error('请先写下你的思路。'); return; } run(() => mutate('answer', {lesson_id:state.current_lesson.id, text})); };
  $('hintButton').onclick = () => run(async () => { await saveDraft(); await mutate('hint', {lesson_id:state.current_lesson.id}); });
  $('lessonContent').onclick = event => {
    const paragraph = event.target.closest('[data-paragraph]');
    if (paragraph) { annotationId = paragraph.dataset.paragraph; const text = state.current_lesson.paragraphs.find(p => p.id === annotationId).text; const selected = window.getSelection()?.toString(); $('annotationQuote').value = selected && text.includes(selected) ? selected.slice(0,3000) : text.slice(0,3000); $('annotationQuestion').value = ''; $('annotationDialog').showModal(); }
    const resource = event.target.closest('[data-resource]');
    if (resource) { event.preventDefault(); if (busy) return; const tab = window.open('about:blank', '_blank'); if (tab) tab.opener = null; run(async () => { try { await saveDraft(); await mutate('resource', {lesson_id:state.current_lesson.id, resource_id:resource.dataset.resource}); if (tab) tab.location.href = resource.href; } catch (failure) { tab?.close(); throw failure; } }); }
  };
  $('cancelAnnotation').onclick = () => $('annotationDialog').close();
  $('annotationForm').onsubmit = event => { event.preventDefault(); run(async () => { await saveDraft(); await mutate('annotate', {lesson_id:state.current_lesson.id, paragraph_id:annotationId, quote:$('annotationQuote').value, question:$('annotationQuestion').value}); $('annotationDialog').close(); }); };
  $('chapterReports').onclick = event => { const button = event.target.closest('[data-report]'); if (button) run(async () => { await saveDraft(); await mutate('report', {chapter_id:button.dataset.report}); }); };
  $('exportButton').onclick = () => run(async () => { if (!teacher) await saveDraft(); const data = await api(`/api/course-graph/learner/export?${studentQuery()}`); download(`PLIAC-${studentId}.json`, JSON.stringify(data,null,2)); });
  $('exportHandbook').onclick = () => download('个人知识手册.txt', state.handbook.map(h => `${h.title} · ${labels[h.status]}\n${h.reason}\n${h.concept}\n下一步：${h.next_step}\n证据：${h.evidence_ids.join(', ')}\n`).join('\n'), 'text/plain');
  $('reviewNode').onchange = renderEvidence;
  $('policyChapter').onchange = renderPolicy;
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
  window.addEventListener('beforeunload', event => { if (state?.current_lesson && $('answerText').value !== (state.workspace.drafts[state.current_lesson.id]?.text || '') && !teacher) { event.preventDefault(); event.returnValue = ''; } });
})();
