(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const teacher = location.pathname === '/review';
  const courseId = new URLSearchParams(location.search).get('course_id') || '';
  const hasChoices = () => !!state?.current_lesson?.options?.length;
  const autoAssessed = () => !!state?.capabilities?.objective_assessment;
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
  let state, draftGraph, studentId = '', busy = false, annotationId, saveTimer, failedRequest, home, study, journey;
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
    const planning = !!journey && (!journey.ready() || journey.submitting || journey.data?.learner_version > state.learner.version);
    const answerLocked = !current || state.course_changed || planning || (autoAssessed() && current?.status === 'assessed');
    $('answerForm').querySelectorAll('button,input,textarea,select').forEach(b => b.disabled = busy || answerLocked);
    $('hintButton').disabled = busy || planning || !current?.task || current.prompt_level >= 4 || state.course_changed;
    if (study) for (const id of ['recallToggle','takeBreak','skipBreak']) $(id).disabled = !!state.course_changed;
    const complete = state.chapters.length > 0 && state.chapters.every(c => c.passed);
    $('nextLesson').disabled = busy || !state.workspace.onboarded || complete || planning;
    if(!teacher)$('studyTab').disabled=!state.workspace.onboarded;
    $('nextLesson').textContent = complete ? '本课程当前已完成' : current && state.learner.states[current.node_id].status !== 'mastered' ? '继续练习' : '继续学习';
  }
  async function mutate(operation, values = {}, {renderPage = true} = {}) {
    const data = {student_id:studentId, course_version:state.course.version, ...(operation === "next" ? {study_protocol:1} : {}), ...values};
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
    $('pageTitle').textContent = `${state.course?.title || '课程'}${teacher ? ' · 教师复核' : ''}`;
    $('notice').hidden = !!state.course && !state.course_changed;
    $('notice').textContent = state.course_changed ? '课程已有新发布版本。这里保留了原小节与作答，请安排新小节后继续。' : state.publication.notice;
    $('studentWorkspace').hidden = teacher || !state.course;
    $('teacherWorkspace').hidden = !teacher;
    $('taskAuthoring').hidden = !teacher || !state.capabilities.edit;
    $('policyForm').closest('.panel').hidden = !state.capabilities.edit;
    $('courseProgress').hidden = !state.course || teacher;
    $('courseProgress').textContent = state.course ? `已学习 ${new Set(state.workspace.lessons.map(l => l.node_id)).size} / ${state.course.nodes.length} 小节` : '';
    $('onboarding').hidden = teacher || !state.course || state.workspace.onboarded;
    if (teacher) { renderTeacher(); return; }
    if (!state.course) return;
    $('goals').value = state.learner.profile.goals;
    $('background').value = state.learner.profile.background;
    $('interests').value = state.learner.profile.interests.join('，');
    $('selfAssessments').innerHTML = state.course.chapters.map(c => {
      const nodes = state.course.nodes.filter(n => n.chapter_id === c.id);
      return `<details class="assessment-group"><summary><span>${esc(c.title)}</span><small data-selection-count>0 / ${nodes.length} 已选</small></summary><div class="assessment-options">${nodes.map(n => {
        const saved = state.workspace.self_assessments[n.id]?.value;
        const known = ['confident','unsure'].includes(saved);
        return `<div class="assessment-item"><label class="assessment-toggle"><input type="checkbox" data-known="${esc(n.id)}" ${known?'checked':''}><span>${esc(n.title)}</span></label><span class="assessment-unlearned" ${known?'hidden':''}>还没学过</span><select data-confidence="${esc(n.id)}" aria-label="${esc(n.title)}的理解程度" ${known?'':'hidden disabled'}><option value="confident" ${saved==='confident'?'selected':''}>我已经会了</option><option value="unsure" ${saved==='unsure'?'selected':''}>学过，还不确定</option></select><input type="hidden" data-assess="${esc(n.id)}" value="${known?esc(saved):'new'}"></div>`;
      }).join('')}</div></details>`;
    }).join('');
    const updateAssessment = () => {
      let count = 0;
      for (const group of document.querySelectorAll('.assessment-group')) {
        let selected = 0;
        for (const row of group.querySelectorAll('.assessment-item')) {
          const known = row.querySelector('[data-known]').checked;
          const confidence = row.querySelector('[data-confidence]');
          confidence.hidden = !known; confidence.disabled = !known;
          row.querySelector('.assessment-unlearned').hidden = known;
          row.querySelector('[data-assess]').value = known ? confidence.value : 'new';
          selected += Number(known);
        }
        group.querySelector('[data-selection-count]').textContent = `${selected} / ${group.querySelectorAll('[data-known]').length} 已选`;
        count += selected;
      }
      $('assessmentSummary').textContent = count ? `已选 ${count} 个知识点，接下来用最多 3 道题核验已有基础。` : '全部从基础开始，直接安排学习路线。';
      $('onboardContinue').textContent = count ? '继续，核验已有基础' : '开始安排学习路线';
    };
    $('selfAssessments').onchange = updateAssessment;
    updateAssessment();
    const learned = new Set(state.workspace.lessons.map(l => l.node_id));
    $('nodeList').innerHTML = state.course.chapters.map(c => `<h3>${esc(c.title)}</h3>${state.course.nodes.filter(n => n.chapter_id === c.id).map(n => `<button class="node-button ${state.current_lesson?.node_id === n.id ? 'active' : ''}" data-node="${esc(n.id)}" title="${state.current_lesson?.node_id===n.id?'正在学习':learned.has(n.id)?'已学习':'未学习'}"><span class="state-dot ${learned.has(n.id)?'studied':''}"></span>${esc(n.title)}</button>`).join('')}`).join('');
    $('reportsPanel').hidden = true; $('handbookPanel').hidden = true;
    $('chapterReports').replaceChildren(); $('handbook').replaceChildren();
    renderLesson(); home?.render(state); study?.render(state); journey?.render(state); setAvailability();
    if(state.current_lesson)window.PLIACAssistant?.setContext({course_id:state.course.id,node_id:state.current_lesson.node_id,title:state.current_lesson.title});
  }
  function renderLesson() {
    const lesson = state.current_lesson;
    $('taskPanel').hidden = !lesson;
    if (!lesson) { $('lessonContent').innerHTML = '<p class="muted">保存起点资料后，安排第一小节。</p>'; return; }
    $('lessonContent').innerHTML = `<h3>${esc(lesson.title)}</h3>${lesson.paragraphs.filter(p => p.text).map(p => `<div class="paragraph"><div class="paragraph-body">${p.heading ? `<h4>${esc(p.heading)}</h4>` : ''}<p>${esc(p.text)}</p></div><button data-paragraph="${esc(p.id)}">不明白</button></div>`).join('')}<div>${lesson.resources.length ? '<h3>可选学习材料</h3>' + lesson.resources.map(r => `<a class="resource-card" data-resource="${esc(r.id)}" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${esc(r.title)}<small>${esc(r.organization)} · ${esc(r.applicable_segment || '')}</small></a>`).join('') : ''}</div>${(lesson.sources || []).map(s => `<a class="resource-card" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">延伸阅读：${esc(s.title)}<small>${esc(s.locator)}</small></a>`).join('')}${lesson.annotations.length ? `<details><summary>已记录 ${lesson.annotations.length} 处困惑</summary>${lesson.annotations.map(a => `<p>${esc(a.question)}</p>`).join('')}</details>` : ''}`;
    $('questionText').textContent = lesson.question;
    $('promptBadge').textContent = autoAssessed() && lesson.prompt_level === 4 ? '已显示本题解析' : lesson.prompt_level ? `已使用 ${lesson.prompt_level} 级提示` : '本题尚未使用提示';
    $('taskNotice').textContent = autoAssessed() ? '' : lesson.task ? '提交后由教师复核。' : '请先记录理解与困惑，教师将补充诊断题。';
    $('taskNotice').hidden = !$('taskNotice').textContent;
    $('hintList').innerHTML = lesson.hints.map(h => `<div class="hint">提示 ${h.level}：${esc(h.text)}</div>`).join('');
    $('answerText').value = state.workspace.drafts[lesson.id]?.text || '';
    $('answerText').maxLength = hasChoices() ? 3500 : 4000;
    $('answerText').placeholder = hasChoices() ? '可选：写下你的判断理由。选项会和思路一起保存。' : '写下结论，也写下你这样判断的原因。';
    $('answerChoices').hidden = !lesson.options;
    $('answerChoices').innerHTML = (lesson.options || []).map(o => `<label class="answer-choice"><input type="radio" name="answerChoice" value="${esc(o.id)}" ${state.workspace.drafts[lesson.id]?.choice_id === o.id ? 'checked' : ''}><span>${esc(o.id)}. ${esc(o.text)}</span></label>`).join('');
    $('responses').innerHTML = lesson.responses.map(r => {
      const feedback = state.learner.diagnoses.filter(d => d.review_status === 'reviewed' && d.evidence_ids.includes(r.evidence_id));
      return `<article><span class="badge">${r.prompt_level ? `${r.prompt_level} 级提示或解析后作答` : '未使用本题提示'}</span><p>${esc(r.text)}</p>${r.judgement ? `<p class="quiz-feedback"><strong>${r.judgement.passed ? '回答正确' : '需要再想一想'}</strong><br>${esc(r.judgement.explanation)}</p>` : ''}${feedback.length ? feedback.map(d => `<p class="muted">教师反馈：${esc(displayReason(d.basis))}</p>`).join('') : '<p class="muted">作答已保存。</p>'}</article>`;
    }).join('');
  }
  function renderReports() {
    $('chapterReports').innerHTML = state.chapters.map(c => `<article class="report-row"><h3>${esc(c.title)} <span class="badge">${c.passed ? '当前达标' : c.outcome === 'not_configured' ? '待配置规则' : '待补学 / 核验'}</span></h3><p>${esc(c.advice)}</p><details><summary>查看 ${c.nodes.length} 个节点及判断依据</summary><ul>${c.nodes.map(n => `<li>${esc(n.title)} · ${esc(labels[n.status])}<br><small>${esc(displayReason(n.reason))} · ${n.evidence_ids.length} 条证据</small></li>`).join('')}</ul></details><button data-report="${esc(c.chapter_id)}">保存本次报告</button></article>`).join('') + `<p class="muted">已保存 ${state.workspace.reports.length} 份报告快照；历史快照随完整记录导出。</p>`;
  }
  function renderHandbook() {
    $('handbook').innerHTML = state.handbook.length ? state.handbook.map(h => `<article class="handbook-entry"><h3>${esc(h.title)}</h3><span class="badge">${esc(labels[h.status])}</span><p>${esc(displayReason(h.reason))}</p><p>${esc(h.concept)}</p><p class="muted">${esc(h.next_step)}</p>${h.prompted_evidence_ids.length ? '<p class="muted">本节点存在提示后作答。</p>' : ''}${h.repeated_submissions > 1 ? '<p class="muted">已收录多次作答。</p>' : ''}<details><summary>原始证据（${h.evidence_ids.length}）</summary>${h.evidence_ids.map(id => { const e = state.learner.evidence.find(x => x.id === id); return e ? `<p>${esc(e.text)}</p><small>${esc(id)} · 课程 v${e.course_version}</small>` : ''; }).join('')}</details></article>`).join('') : '<p class="muted">暂无手册条目。</p>';
  }
  function renderTeacher() {
    $('teacherWorkspace').append($('reportsPanel'), $('handbookPanel'));
    $('reportsPanel').hidden = false; $('handbookPanel').hidden = false;
    renderReports(); renderHandbook();
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
  async function load({navigate=true}={}) {
    const loaded = await api(`/api/learning${teacher ? '/teacher' : ''}?${studentQuery()}`);
    if (state?.learner.student_id === loaded.learner.student_id && state.course?.id === loaded.course?.id &&
        state.course?.version === loaded.course?.version && loaded.learner.version < state.learner.version) return;
    state = loaded;
    if (teacher) draftGraph = (await api('/api/course-graph?view=draft')).graph;
    render(); $('saveStatus').textContent = '已恢复最近保存的记录';
    if(navigate)await openRequestedNode();
  }
  async function openRequestedNode() {
    if (teacher || !requestedNode || !state.workspace.onboarded) return;
    if(journey && !journey.ready())return;
    const node = requestedNode; requestedNode = null;
    if (state.course.nodes.some(n => n.id === node) && state.current_lesson?.node_id !== node) await mutate('next', {node_id:node});
    const url=new URL(location.href);url.searchParams.delete('node_id');history.replaceState(null,'',url);
    home?.show('study');
  }
  async function saveDraft() {
    clearTimeout(saveTimer);
    if (!state?.current_lesson || state.course_changed) return;
    await study?.saveCard();
    const lesson = state.current_lesson;
    const confidence = $("answerConfidence")?.value || "";
    const text = $('answerText').value;
    const choice_id = choiceValue();
    if (confidence === (state.workspace.drafts[lesson.id]?.confidence || '') && text === (state.workspace.drafts[lesson.id]?.text || '') && choice_id === (state.workspace.drafts[lesson.id]?.choice_id || '')) return;
    await mutate('draft', {lesson_id:lesson.id, text, confidence, ...(hasChoices() ? {choice_id} : {})}, {renderPage:false});
  }
  $('themeButton').onclick = () => { GraphTheme.toggle(); home?.theme(); };
  $('handoutLink').href = `/course-reader?${query}`;
  $('graphLink').href = `/knowledge?${query}`;
  $('authorLink').href = `/author?${query}`;
  $('roleLink').href = `${teacher ? '/learn' : '/review'}?${query}`;
  $('roleLink').textContent = teacher ? '学习工作台' : '教师复核';
  try { $('studentId').value = localStorage.getItem(storageKey) || ''; } catch {}
  $('studentId').value = new URLSearchParams(location.search).get('student_id') || $('studentId').value;
  if (!teacher && !$('studentId').value) $('studentId').value = 'learner-' + crypto.randomUUID().slice(0,8);
  function choiceValue() { return document.querySelector('[name=answerChoice]:checked')?.value || ''; }
  $('identityForm').onsubmit = event => { event.preventDefault(); run(async () => { await saveDraft(); studentId = $('studentId').value.trim(); await load(); try { localStorage.setItem(storageKey, studentId); } catch {} }); };
  $('refreshButton').onclick = () => run(async () => { if (!teacher) await saveDraft(); await load(); });
  $('onboardForm').onsubmit = event => { event.preventDefault(); run(async () => {
    const selfAssessments = Object.fromEntries([...document.querySelectorAll('[data-assess]')].filter(s => s.value).map(s => [s.dataset.assess,s.value]));
    await mutate('onboard', {goals:$('goals').value, background:$('background').value, interests:$('interests').value.split(/[,，]/).map(x => x.trim()).filter(Boolean), self_assessments:selfAssessments});
    home?.show('journey');await journey?.refresh();
  }); };
  $('nextLesson').onclick = () => run(async () => { await saveDraft(); await mutate('next'); home?.show('study'); });
  $('nodeList').onclick = event => { const button = event.target.closest('[data-node]'); if (button) { if(home?.mode==='overview'){home.select(button.dataset.node);return;} if(journey&&!journey.ready()){home.show('overview');home.select(button.dataset.node);return;} run(async () => { await saveDraft(); await mutate('next', {node_id:button.dataset.node}); home?.show('study'); }); } };
  function scheduleSave() { clearTimeout(saveTimer); saveTimer = setTimeout(() => { if (busy || (journey && (!journey.ready() || journey.submitting || journey.data?.learner_version > state.learner.version))) scheduleSave(); else run(saveDraft); }, 900); }
  $('answerText').oninput = () => { $('saveStatus').textContent = '正在编辑'; scheduleSave(); };
  $('answerChoices').onchange = () => { $('saveStatus').textContent = '正在编辑'; scheduleSave(); };
  $('answerForm').onsubmit = event => { event.preventDefault(); clearTimeout(saveTimer); const text = $('answerText').value, choice_id = choiceValue(); if (hasChoices() ? !choice_id : !text.trim()) { error(hasChoices() ? '请先选择一个选项。' : '请先写下你的思路。'); return; } run(() => mutate('answer', {lesson_id:state.current_lesson.id, text, confidence:$('answerConfidence')?.value, ...(hasChoices() ? {choice_id} : {})})); };
  $('hintButton').onclick = () => run(async () => { await saveDraft(); await mutate('hint', {lesson_id:state.current_lesson.id}); });
  $('lessonContent').onclick = event => {
    const paragraph = event.target.closest('[data-paragraph]');
    if (paragraph) { annotationId = paragraph.dataset.paragraph; const text = String(state.current_lesson.paragraphs.find(p => p.id === annotationId)?.text || ''); const selected = window.getSelection()?.toString(); $('annotationQuote').value = selected && text.includes(selected) ? selected.slice(0,3000) : text.slice(0,3000); $('annotationQuestion').value = ''; $('annotationDialog').showModal(); }
    const resource = event.target.closest('[data-resource]');
    if (resource) { event.preventDefault(); if (busy) return; const tab = window.open('about:blank', '_blank'); if (tab) tab.opener = null; run(async () => { try { await saveDraft(); await mutate('resource', {lesson_id:state.current_lesson.id, resource_id:resource.dataset.resource}); if (tab) tab.location.href = resource.href; } catch (failure) { tab?.close(); throw failure; } }); }
  };
  $('cancelAnnotation').onclick = () => $('annotationDialog').close();
  $('annotationForm').onsubmit = event => { event.preventDefault(); run(async () => { await saveDraft(); await mutate('annotate', {lesson_id:state.current_lesson.id, paragraph_id:annotationId, quote:$('annotationQuote').value, question:$('annotationQuestion').value}); $('annotationDialog').close(); }); };
  $('lessonLabLink').onclick = event => {event.preventDefault();run(async()=>{await saveDraft();location.assign($('lessonLabLink').href);});};
  $('courseLabList').onclick = event => {const link=event.target.closest('a');if(!link)return;event.preventDefault();run(async()=>{await saveDraft();location.assign(link.href);});};
  $('chapterReports').onclick = event => { const button = event.target.closest('[data-report]'); if (button) run(async () => { await saveDraft(); await mutate('report', {chapter_id:button.dataset.report}); }); };
  $('exportButton').onclick = () => run(async () => { if (!teacher) await saveDraft(); const data = await api(`/api/course-graph/learner/export?${studentQuery()}`); download(`PLIAC-${studentId}.json`, JSON.stringify(data,null,2)); });
  $('exportHandbook').onclick = () => run(async()=>{ await saveDraft(); render(); download('个人知识手册.txt', state.handbook.map(h => `${h.title} · ${labels[h.status]}\n${displayReason(h.reason)}\n${h.concept}\n下一步：${h.next_step}\n证据：${h.evidence_ids.join(', ')}\n`).join('\n') + '\n' + (study?.exportCards() || ''), 'text/plain'); });
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
  window.addEventListener('beforeunload', event => { if (state?.current_lesson && !teacher && (study?.cardDrafts.size || $('answerText').value !== (state.workspace.drafts[state.current_lesson.id]?.text || '') || choiceValue() !== (state.workspace.drafts[state.current_lesson.id]?.choice_id || ''))) { event.preventDefault(); event.returnValue = ''; } });
  if(!teacher){
    study=new StudyPanel({run,mutate,save:saveDraft,refresh:render});
    $('answerConfidence').onchange=scheduleSave;
    home=new LearningHome({error,displayReason,changeView:mode=>run(async()=>{await saveDraft();if(mode==='study'&&journey&&!journey.ready()){home.show('journey');return;}home.show(mode);}),study:id=>run(async()=>{if(journey&&!journey.ready()){home.show('journey');return;}await saveDraft();if(!state.current_lesson||state.current_lesson.node_id!==id)await mutate('next',{node_id:id});home.show('study');})});
    journey=new LearningJourney({state:()=>state,api,run,availability:setAvailability,reload:()=>load({navigate:false}),error:e=>error(e.message||String(e)),resume:()=>run(async()=>{await saveDraft();if(requestedNode){await openRequestedNode();return;}if(!state.current_lesson)await mutate('next');home.show('study');})});
    run(async()=>{
      const account=await window.PLIACAccountReady;
      if(account?.user){
        $('studentId').value=account.user.student_id;$('identityForm').hidden=true;$('logoutButton').hidden=false;
        $('logoutButton').onclick=async()=>{await fetch('/api/account/logout',{method:'POST'});location.assign('/login');};
      }
      studentId=$('studentId').value.trim();await load();try{localStorage.setItem(storageKey,studentId);}catch{}
    });
  }else{
    $('learningTabs').hidden=true;
    $('identityForm').querySelectorAll('input,button').forEach(control=>control.disabled=false);
  }
})();
