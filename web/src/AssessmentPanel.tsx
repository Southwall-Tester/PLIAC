import {useEffect, useRef, useState} from 'react';
import {api, learnerKey, localLearner, type Workspace} from './api';
import {RichText} from './RichText';

export function AssessmentPanel({state, courseId, nodeId, assessmentId, update}: {
  state: Workspace; courseId: string; nodeId: string; assessmentId?: string; update: (state: Workspace) => void;
}) {
  const task = assessmentId ? state.workspace.assessments?.find(item => item.id === assessmentId)
    : state.workspace.assessments?.filter(item => item.node_id === nodeId && item.course_version === state.course!.version).at(-1);
  const guided = !!task && state.workspace.teaching_flow?.enabled && state.workspace.tutor_turns?.some(turn => turn.request_id === state.workspace.teaching_flow?.current_turn_id && turn.activity?.id === task.id);
  const key = learnerKey(`answer.${courseId}.${task?.id || nodeId}`);
  const [answer, setAnswer] = useState(() => localStorage.getItem(key) || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);
  type Pending = {signature: string; id: string; expected: number};
  const pendingKey = `pliac.assessment-request:${localLearner()}:${courseId}:${task?.id || nodeId}`;
  const pending = useRef<Pending | undefined>((() => {
    try {
      const saved = JSON.parse(localStorage.getItem(pendingKey) || 'null');
      return saved && typeof saved.signature === 'string' && typeof saved.id === 'string' && Number.isInteger(saved.expected) ? saved : undefined;
    } catch {return undefined;}
  })());
  async function perform(initialOperation: string, fields: Record<string, string>) {
    if (busy) return;
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError('');
    let latestState = state;
    try {
      for (const operation of initialOperation === 'submit' && guided ? ['submit', 'evaluate'] : [initialOperation]) {
        const signature = JSON.stringify({operation, fields, courseId, version: latestState.course!.version});
        if (pending.current?.signature !== signature) pending.current = {signature, id: crypto.randomUUID(), expected: latestState.learner.version};
        const request = pending.current;
        localStorage.setItem(pendingKey, JSON.stringify(request));
        const response = await fetch(`/api/tutor/assessment/${operation}?course_id=${encodeURIComponent(courseId)}`, {
          method: 'POST', signal: controller.signal, headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
            student_id: localLearner(), course_version: state.course!.version, expected_version: request.expected,
            request_id: request.id, ...fields,
          }),
        });
        const data = await response.json();
        if (!response.ok) {
          if (response.status === 409) {
            let running = false;
            if (operation === 'evaluate') {
              const job = await fetch(`/api/tutor/jobs/assessment-${fields.assessment_id}-v${request.expected}?${new URLSearchParams({course_id: courseId, student_id: localLearner()})}`, {signal: controller.signal});
              running = job.ok && (await job.json()).status === 'running';
            }
            if (!running) {pending.current = undefined; localStorage.removeItem(pendingKey);}
            const fresh = await api<Workspace>(`/api/learning?course_id=${encodeURIComponent(courseId)}&student_id=${localLearner()}`, controller.signal);
            if (!controller.signal.aborted) update(fresh);
          }
          throw new Error(typeof data.detail === 'string' ? data.detail : '操作未完成，作答草稿仍保留。');
        }
        if (controller.signal.aborted) return;
        latestState = data; update(data); pending.current = undefined; localStorage.removeItem(pendingKey);
      }
    } catch (failure) {if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '网络异常，请重试。');}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }
  return <section className="assessment-panel" aria-label="理解核验">
    <h2>检验一下理解</h2><p>几道题，看看这一节学得怎么样。</p>
    {!task ? <button disabled={busy} onClick={() => perform('start', {node_id: nodeId})}>开始核验</button> : <>
      <div className="assessment-question"><RichText text={task.question}/></div>
      {task.status === 'open' && <p className="quiet-note">卡住了可以随时求助，求助后的作答会单独记录。</p>}
      {task.status === 'open' ? <form onSubmit={event => {event.preventDefault(); perform('submit', {assessment_id: task.id, answer});}}>
        {task.options.length ? <fieldset disabled={busy}><legend>请选择答案</legend>{task.options.map(option => <label key={option.id}>
          <input type="radio" name={`choice-${task.id}`} value={option.id} checked={answer === option.id}
            onChange={() => {setAnswer(option.id); localStorage.setItem(key, option.id);}}/>{option.text}
        </label>)}</fieldset> : <label>你的解释<textarea value={answer} maxLength={4000} disabled={busy}
          onChange={event => {setAnswer(event.target.value); localStorage.setItem(key, event.target.value);}}/></label>}
        <button disabled={busy || !answer.trim()} type="submit">{guided ? '保存作答并评价' : '保存作答'}</button>
      </form> : <>
        <p>已保存作答：{task.options.find(option => option.id === task.answer)?.text || task.answer}</p>
        {!!task.assistance_turn_ids?.length && <p className="quiet-note">本次作答关联了 {task.assistance_turn_ids.length} 条课程辅导记录，已纳入受助判断。{task.assistance_policy === 'legacy-time-v1' ? '这是旧任务，关联依据为历史时间记录。' : '关联依据为任务开启后的保存顺序，而非停顿时长或情绪推断。'}</p>}
        {!!task.assistance_lab_event_ids?.length && <p className="quiet-note">本次作答关联了 {task.assistance_lab_event_ids.length} 条相关实验提示记录，已纳入受助判断。{task.lab_assistance_policy === 'legacy-time-v1' ? '这是旧任务，关联依据为历史时间记录。' : '仅关联核验开启后、作答保存前的同版本相关知识点提示。'}</p>}
        {task.status === 'submitted' ? <><p>作答已保存，尚未形成评价。</p><button disabled={busy} onClick={() => perform('evaluate', {assessment_id: task.id})}>按标准评价</button></> : <>
          <h3>{({mastery_supported: '本任务证据支持掌握', assisted_success: '已完成，稍后再独立做一题巩固', needs_work: '发现需要补学的内容', uncertain: '还需要再练一练'} as Record<string, string>)[task.result!.status]}</h3>
          <RichText text={task.result!.feedback}/><details><summary>查看评价依据</summary><ol>{task.result!.criteria.map(criterion => <li key={criterion.criterion_id}>
            <p>{criterion.reason}</p>{criterion.quote && <blockquote>{criterion.quote}</blockquote>}
          </li>)}</ol></details>
          {task.result!.resolution && <p className="quiet-note">已覆盖 {task.result!.resolution.diagnosis_ids.length} 条历史问题。{task.result!.resolution.reason}</p>}
          {task.result!.follow_up_question && <RichText text={task.result!.follow_up_question}/>}
          {!assessmentId && !guided && <button disabled={busy} onClick={() => perform('start', {node_id: nodeId})}>继续核验</button>}
        </>}
      </>}
    </>}
    {busy && <p role="status">正在处理，请稍候；无需重复提交。</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
