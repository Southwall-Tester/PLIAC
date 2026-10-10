import {useEffect, useRef, useState} from 'react';
import {Link} from 'react-router-dom';
import {api, localLearner, type Workspace} from './api';
import {postTeachingRequest} from './jobRecovery';

type Pending = {trigger_id: string; request_id: string; node_id: string; expected_version: number; course_version: number};
const reasons: Record<string, string> = {initial_diagnosis: '正在确认学习起点', goal_changed: '正在结合新目标调整',
  plan_accepted: '正在按采用的范围确认起点', assessment_evaluated: '正在根据核验结果调整', reading_finished: '正在安排阅读后的学习', lab_finished: '正在安排实验后的理解核验', student_choice: '正在结合你的选择安排'};

export function GuidedFlow({state, courseId, nodeId, materialId, update}: {
  state: Workspace; courseId: string; nodeId: string; materialId?: string; update: (value: Workspace) => void;
}) {
  const flow = state.workspace.teaching_flow;
  const trigger = flow?.pending;
  const current = state.workspace.tutor_turns?.find(turn => turn.request_id === flow?.current_turn_id);
  const staleScope = state.workspace.learning_plans?.some(plan =>
    [flow?.active_plan_id, flow?.pending_plan_id].includes(plan.id) && plan.course_version !== state.course?.version)
    || (!!flow?.plan_request && flow.plan_request.course_version !== state.course?.version);
  const cacheKey = `pliac.flow-request:${localLearner()}:${courseId}`;
  const [busy, setBusy] = useState(false);
  const [commandBusy, setCommandBusy] = useState(false);
  const [error, setError] = useState('');
  const active = useRef<AbortController | null>(null);
  const commandAbort = useRef<AbortController | null>(null);
  useEffect(() => () => {commandAbort.current?.abort(); active.current?.abort();}, []);

  async function run(controller: AbortController, fresh = false) {
    if (!trigger || !state.course || staleScope) return;
    let request: Pending | undefined;
    if (!fresh) {
      try {
        const saved = JSON.parse(localStorage.getItem(cacheKey) || 'null');
        if (saved?.trigger_id === trigger.id && saved.node_id === trigger.node_id && Number.isInteger(saved.expected_version) && saved.course_version === state.course.version) request = saved;
      } catch { /* An invalid browser cache is not server state. */ }
    }
    request ??= {trigger_id: trigger.id, request_id: `flow-${trigger.id}-v${state.learner.version}`,
      node_id: trigger.node_id, expected_version: state.learner.version, course_version: state.course.version};
    localStorage.setItem(cacheKey, JSON.stringify(request));
    setBusy(true); setError('');
    try {
        const jobURL = `/api/tutor/jobs/${request.request_id}?${new URLSearchParams({course_id: courseId, student_id: localLearner()})}`;
        const response = await postTeachingRequest(`/api/tutor/advance?course_id=${encodeURIComponent(courseId)}`,
          {...request, student_id: localLearner()}, jobURL, controller.signal);
        const result = await response.json();
        if (response.ok) {
          if (!controller.signal.aborted) {localStorage.removeItem(cacheKey); update(result.state);}
          return;
        }
        if (response.status === 409) {
          const latest = await api<Workspace>(`/api/learning?${new URLSearchParams({course_id: courseId, student_id: localLearner()})}`, controller.signal);
          if (!controller.signal.aborted) update(latest);
        }
        throw new Error(typeof result.detail === 'string' ? result.detail : '教学安排未完成，已保存内容仍可使用。');
    } catch (failure) {if (!controller.signal.aborted) setError((failure as Error).message);}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }

  useEffect(() => {
    if (!flow?.enabled || !trigger || staleScope) {setBusy(false); return;}
    const controller = new AbortController(); active.current = controller;
    void run(controller);
    return () => controller.abort();
    // Only a new server trigger/resume starts work, not every note/save rerender.
  }, [trigger?.id, flow?.enabled, courseId, staleScope]);

  async function command(operation: string) {
    if (commandBusy || !state.course) return;
    const controller = new AbortController(); commandAbort.current = controller;
    setCommandBusy(true); setError('');
    try {
      const result = await fetch(`/api/tutor/flow?course_id=${encodeURIComponent(courseId)}`, {
        method: 'POST', signal: controller.signal, headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
          operation, node_id: nodeId, turn_id: current?.request_id, student_id: localLearner(), request_id: crypto.randomUUID(),
          expected_version: state.learner.version, course_version: state.course.version,
        }),
      });
      const data = await result.json();
      if (!result.ok) throw new Error(data.detail || '操作未完成，请刷新学习状态后重试。');
      if (!controller.signal.aborted) update(data);
    } catch (failure) {if (!controller.signal.aborted) setError((failure as Error).message);}
    finally {if (!controller.signal.aborted) setCommandBusy(false);}
  }

  if (!state.workspace.onboarded) return null;
  if (staleScope) return <section className="guided-flow" aria-label="智能体学习进程"><h2>先确认更新后的学习范围</h2>
    <p>课程内容更新了，需要重新确认学习范围。</p>
    <Link className="material-link" to="?setup=1">重新协商学习范围</Link></section>;
  return <section className="guided-flow" aria-label="智能体学习进程"><h2>智能体安排</h2>
    {flow?.enabled ? <>
      {trigger ? <p role={busy ? 'status' : undefined}>{busy ? reasons[trigger.reason] || '正在安排学习' : '下一步还没安排好'}…</p>
        : current ? <><p>下一步：<b>{state.course?.nodes.find(n => n.id === current.proposal.target_node_id)?.title || '当前学习活动'}</b></p><details><summary>为什么这样安排</summary><p>{current.proposal.rationale}</p></details></> : <p>可以选择知识点，让智能体接续安排。</p>}
      {current && current.request_id !== materialId && <Link className="material-link" to={`?material=${encodeURIComponent(current.request_id)}`}>打开当前学习活动</Link>}
      {!trigger && current?.request_id === materialId && !['assessment', 'lab'].includes(current?.activity?.type || '') &&
        <button disabled={commandBusy} onClick={() => command('continue')}>本节已读，继续学习</button>}
      <button disabled={commandBusy} onClick={() => command('pause')}>暂停自动安排</button>
    </> : <><p>已暂停智能体安排，可以自由浏览。</p><button disabled={commandBusy} onClick={() => command('resume')}>恢复智能体安排</button></>}
    {!busy && flow?.enabled && <button disabled={commandBusy} onClick={() => command('choose')}>围绕当前知识点重新安排</button>}
    {error && <p role="alert">{error}</p>}
    {error && trigger && flow?.enabled && <button disabled={busy} onClick={() => {const controller = new AbortController(); active.current?.abort(); active.current = controller; void run(controller, true);}}>按最新状态重试安排</button>}
  </section>;
}
