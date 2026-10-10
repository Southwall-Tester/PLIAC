import {useEffect, useRef, useState} from 'react';
import {Link} from 'react-router-dom';
import {api, localLearner, type Workspace} from './api';
import {postTeachingRequest} from './jobRecovery';

export function LearningPlanPanel({state, courseId, update}: {state: Workspace; courseId: string; update: (value: Workspace) => void}) {
  const flow = state.workspace.teaching_flow;
  const request = flow?.plan_request;
  const pending = state.workspace.learning_plans?.find(plan => plan.id === flow?.pending_plan_id);
  const active = state.workspace.learning_plans?.find(plan => plan.id === flow?.active_plan_id);
  const plan = pending || active;
  const stale = (!!plan && plan.course_version !== state.course?.version) || (!!request && request.course_version !== state.course?.version);
  const [startNode, setStartNode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const abort = useRef<AbortController | null>(null);
  const applyRequest = useRef<string | null>(null);
  const cacheKey = `pliac.plan-request:${localLearner()}:${courseId}`;
  useEffect(() => {setStartNode(plan?.proposal.start_node_id || ''); applyRequest.current = null;}, [plan?.id]);
  useEffect(() => () => abort.current?.abort(), []);

  async function refresh(signal: AbortSignal) {
    const fresh = await api<Workspace>(`/api/learning?${new URLSearchParams({course_id: courseId, student_id: localLearner()})}`, signal);
    if (!signal.aborted) update(fresh);
  }

  async function generate(controller: AbortController, fresh = false) {
    if (!request || !state.course || stale) return;
    let expected = state.learner.version;
    if (!fresh) {
      try {const saved = JSON.parse(localStorage.getItem(cacheKey) || 'null'); if (saved?.id === request.id && Number.isInteger(saved.expected)) expected = saved.expected;} catch { /* Ignore malformed browser hints. */ }
    }
    localStorage.setItem(cacheKey, JSON.stringify({id: request.id, expected}));
    setBusy(true); setError('');
    try {
      const job = `plan-${request.id}-v${expected}`;
      const response = await postTeachingRequest(`/api/tutor/plan?course_id=${encodeURIComponent(courseId)}`,
        {student_id: localLearner(), plan_request_id: request.id, expected_version: expected, course_version: state.course.version},
        `/api/tutor/jobs/${job}?${new URLSearchParams({course_id: courseId, student_id: localLearner()})}`, controller.signal);
      const result = await response.json();
      if (!response.ok) {if (response.status === 409) await refresh(controller.signal); throw new Error(result.detail || '规划尚未完成。');}
      if (!controller.signal.aborted) {localStorage.removeItem(cacheKey); update(result.state);}
    } catch (failure) {if (!controller.signal.aborted) setError((failure as Error).message);}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }
  useEffect(() => {
    if (!request || !flow?.enabled || stale) {setBusy(false); return;}
    const controller = new AbortController(); abort.current = controller; void generate(controller);
    return () => controller.abort();
  }, [request?.id, flow?.enabled, courseId, stale]);

  async function accept() {
    if (!pending || !state.course || busy || stale) return;
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError(''); applyRequest.current ??= crypto.randomUUID();
    try {
      const response = await fetch(`/api/tutor/plan/apply?course_id=${encodeURIComponent(courseId)}`, {method: 'POST', signal: controller.signal,
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({student_id: localLearner(), request_id: applyRequest.current,
          expected_version: state.learner.version, course_version: state.course.version, plan_id: pending.id, start_node_id: startNode})});
      const result = await response.json();
      if (!response.ok) {if (response.status === 409) await refresh(controller.signal); throw new Error(result.detail || '暂未采用规划。');}
      if (!controller.signal.aborted) update(result);
    } catch (failure) {if (!controller.signal.aborted) setError((failure as Error).message);}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }

  if (!request && !plan) return null;
  const title = (id: string) => state.course?.nodes.find(node => node.id === id)?.title || id;
  const labels: Record<string, string> = {mastered: '已有证据支持', needs_review: '需要补学', uncertain: '仍需核验', unknown: '尚无充分证据'};
  if (plan && !pending && !request && !stale && plan.proposal.status === 'proposed') return <details className="guided-flow learning-plan plan-compact">
    <summary>本阶段 · {plan.proposal.learning_order.length} 个知识点{plan.completion ? ' · 已完成阶段总结' : ''}</summary>
    <p>{plan.proposal.summary}</p>
    <ol>{plan.proposal.learning_order.map(id => <li key={id}><span>{title(id)}</span><small>{labels[state.learner.states[id]?.status] || '尚未学习'}</small></li>)}</ol>
    {plan.completion && <Link className="material-link" to={`?report=${encodeURIComponent(plan.completion.report_id)}`}>查看阶段总结</Link>}
    <Link className="material-link" to="?setup=1">调整目标与范围</Link>
  </details>;
  return <section className="guided-flow learning-plan" aria-label="学习范围规划"><h2>{pending || request ? '确认这次的学习范围' : '本阶段学习范围'}</h2>
    {request ? <><p role="status">{stale ? '课程已更新，旧规划请求已不适用。请调整目标与范围后重新规划。' : busy ? '正在为你规划学习范围…' : '目标已保存，正在等待规划。'}</p></> : plan && <>
      <p>{plan.proposal.summary}</p>
      {plan.completion && <p>这个范围已经完成阶段总结。<Link className="material-link" to={`?report=${encodeURIComponent(plan.completion.report_id)}`}>查看阶段总结</Link></p>}
      {stale && <p role="status">课程已更新。这份范围属于旧版本，请调整目标并重新规划；历史学习记录仍保留。</p>}
      {plan.proposal.status === 'clarify' ? <p className="plan-clarification">{plan.proposal.clarification}</p> : <details open={!!pending}><summary>查看范围、顺序与当前证据</summary>
        <ol>{plan.proposal.learning_order.map(id => <li key={id}><span>{title(id)}</span><small>{stale ? '旧计划，需重新核验适用性' : labels[state.learner.states[id]?.status] || '需要核验'}</small></li>)}</ol>
        {plan.prerequisite_node_ids.length > 0 && <p>需要时补充的前置知识：{plan.prerequisite_node_ids.map(title).join('、')}。</p>}
        <p>{plan.proposal.rationale}</p>
      </details>}
      {pending?.proposal.status === 'proposed' && !stale && <><label className="plan-start">本次起点<select aria-label="规划起点" value={startNode} onChange={event => {setStartNode(event.target.value); applyRequest.current = null;}}>{[...plan.proposal.target_node_ids, ...plan.prerequisite_node_ids].map(id => <option key={id} value={id}>{title(id)}</option>)}</select></label><button disabled={busy || !startNode} onClick={accept}>按这个范围开始学习</button></>}
    </>}
    <Link className="material-link" to="?setup=1">调整目标与范围</Link>
    {error && <p role="alert">{error}</p>}
    {request && error && !stale && <button disabled={busy} onClick={() => {const controller = new AbortController(); abort.current?.abort(); abort.current = controller; void generate(controller, true);}}>按最新目标重试规划</button>}
  </section>;
}
