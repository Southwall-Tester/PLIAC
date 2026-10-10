import {useEffect, useRef, useState} from 'react';
import {api, localLearner, type Workspace} from './api';

export function LearningPreferences({state, courseId, update}: {state: Workspace; courseId: string; update: (value: Workspace) => void}) {
  const [interests, setInterests] = useState((state.learner.profile.interests || []).join('\n'));
  const [explanation, setExplanation] = useState(state.learner.profile.explanation_preferences || '');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef<{signature: string; id: string} | null>(null);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);
  async function save() {
    if (!state.course || busy) return;
    const values = {interests: interests.split('\n').map(value => value.trim()).filter(Boolean), explanation_preferences: explanation.trim()};
    const signature = JSON.stringify(values);
    if (pending.current?.signature !== signature) pending.current = {signature, id: crypto.randomUUID()};
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setMessage('正在保存偏好…');
    try {
      const response = await fetch(`/api/learning/preferences?course_id=${encodeURIComponent(courseId)}`, {method: 'POST', signal: controller.signal,
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...values, student_id: localLearner(), course_version: state.course.version,
          expected_version: state.learner.version, request_id: pending.current.id})});
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 409) update(await api<Workspace>(`/api/learning?${new URLSearchParams({course_id: courseId, student_id: localLearner()})}`, controller.signal));
        throw new Error(data.detail || '偏好保存失败。');
      }
      if (!controller.signal.aborted) {update(data); pending.current = null; setMessage('偏好已保存，后续教学将读取；当前学习计划未重置。');}
    } catch (error) {if (!controller.signal.aborted) setMessage((error as Error).message);}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }
  return <details className="learning-preferences"><summary>案例与讲解偏好（可随时修改）</summary>
    <p>这是你主动提供的偏好，不是学习能力标签。只保存到本课程；清空后保存即可不再使用这些偏好。</p>
    <form className="start-form" onSubmit={event => {event.preventDefault(); void save();}}>
      <label>希望使用的案例主题<textarea value={interests} maxLength={3000} onChange={event => setInterests(event.target.value)} placeholder="每行一个，例如：体育比赛、校园活动"/></label>
      <label>讲解方式偏好<textarea value={explanation} maxLength={1000} onChange={event => setExplanation(event.target.value)} placeholder="例如：先给直观例子，再解释公式；不跳过推导"/></label>
      <button type="submit" disabled={busy}>保存案例与讲解偏好</button>{message && <p role="status">{message}</p>}
    </form>
  </details>;
}
