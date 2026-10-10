import {useEffect, useRef, useState} from 'react';
import {useNavigate} from 'react-router-dom';
import {api, localLearner, type TutorTurn, type Workspace} from './api';

export function TeachingAdvance({state, courseId, nodeId, update}: {
  state: Workspace; courseId: string; nodeId: string; update: (state: Workspace) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  type Pending = {id: string; expected: number; version: number};
  const pendingKey = `pliac.advance-request:${localLearner()}:${courseId}:${nodeId}`;
  const request = useRef<Pending | null>((() => {
    try {
      const saved = JSON.parse(localStorage.getItem(pendingKey) || 'null');
      return saved && typeof saved.id === 'string' && Number.isInteger(saved.expected) && Number.isInteger(saved.version) ? saved : null;
    } catch {return null;}
  })());
  const abort = useRef<AbortController | null>(null);
  const navigate = useNavigate();
  useEffect(() => () => abort.current?.abort(), []);
  async function advance() {
    if (busy || !state.course) return;
    request.current ??= {id: crypto.randomUUID(), expected: state.learner.version, version: state.course.version};
    const pending = request.current;
    localStorage.setItem(pendingKey, JSON.stringify(pending));
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/tutor/advance?course_id=${encodeURIComponent(courseId)}`, {
        method: 'POST', signal: controller.signal, headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({student_id: localLearner(), request_id: pending.id,
          node_id: nodeId, expected_version: pending.expected, course_version: pending.version}),
      });
      const result = await response.json() as {state: Workspace; turn: TutorTurn; detail?: string};
      if (!response.ok) {
        if (response.status === 409) {
          const job = await fetch(`/api/tutor/jobs/${encodeURIComponent(pending.id)}?${new URLSearchParams({course_id: courseId, student_id: localLearner()})}`, {signal: controller.signal});
          const running = job.ok && (await job.json()).status === 'running';
          if (!running) {request.current = null; localStorage.removeItem(pendingKey);}
          const fresh = await api<Workspace>(`/api/learning?course_id=${encodeURIComponent(courseId)}&student_id=${localLearner()}`, controller.signal);
          if (!controller.signal.aborted) update(fresh);
        }
        throw new Error(result.detail || '教学安排未完成，请重试。');
      }
      if (controller.signal.aborted) return;
      update(result.state); request.current = null; localStorage.removeItem(pendingKey);
      navigate(`?material=${encodeURIComponent(result.turn.request_id)}`);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '网络异常，学习记录仍保留。');
    } finally {if (!controller.signal.aborted) setBusy(false);}
  }
  return <section className="assessment-panel" aria-label="下一步学习">
    <button disabled={busy} onClick={advance}>{busy ? '正在安排…' : request.current ? '恢复上次安排' : '让智能体安排下一步'}</button>
    {error && <p role="alert">{error}</p>}
  </section>;
}
