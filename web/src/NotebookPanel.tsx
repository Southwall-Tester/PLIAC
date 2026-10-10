import {useEffect, useRef, useState} from 'react';
import {api, localLearner, type Workspace} from './api';

export function NotebookPanel({state, courseId, nodeId, materialId, update}: {
  state: Workspace; courseId: string; nodeId: string; materialId?: string; update: (state: Workspace) => void;
}) {
  const history = state.workspace.notes?.[nodeId] || [];
  const latest = history.at(-1);
  const draftKey = `pliac.note.${localLearner()}.${courseId}.${nodeId}`;
  const [text, setText] = useState(() => localStorage.getItem(draftKey) ?? latest?.text ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const current = useRef(text); current.current = text;
  const pending = useRef<{signature: string; id: string} | null>(null);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);
  async function save() {
    if (busy) return;
    const submitted = text;
    const signature = JSON.stringify([submitted, materialId, state.course!.version]);
    if (pending.current?.signature !== signature) pending.current = {signature, id: crypto.randomUUID()};
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/tutor/notes?course_id=${encodeURIComponent(courseId)}`, {
        method: 'POST', signal: controller.signal, headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({student_id: localLearner(), request_id: pending.current.id,
          expected_version: state.learner.version, course_version: state.course!.version,
          node_id: nodeId, text: submitted, material_id: materialId}),
      });
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 409) update(await api<Workspace>(`/api/learning?course_id=${encodeURIComponent(courseId)}&student_id=${localLearner()}`, controller.signal));
        throw new Error(typeof result.detail === 'string' ? result.detail : '笔记保存失败，请重试。');
      }
      if (controller.signal.aborted) return;
      update(result); pending.current = null;
      if (current.current === submitted) localStorage.removeItem(draftKey);
    } catch (failure) {if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '网络异常，草稿仍保留。');}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }
  return <section className="assessment-panel" aria-label="学习笔记"><details>
    <summary>我的学习笔记{latest ? ` · 第 ${latest.revision} 版` : ''}</summary>
    <p>记录有效解释、疑问和自己的理解。保存后下次可继续阅读，也会作为学生自述供教学参考。</p>
    <label>当前知识点的笔记<textarea value={text} maxLength={8000} onChange={event => {
      setText(event.target.value); localStorage.setItem(draftKey, event.target.value);
    }}/></label>
    <button onClick={save} disabled={busy || text === (latest?.text || '')}>{busy ? '正在保存…' : '保存笔记'}</button>
    <p role="status">{text === (latest?.text || '') ? (latest ? '已保存到学习档案' : '尚无笔记') : '有未保存修改，草稿保留在此浏览器'}</p>
    {error && <p role="alert">{error}</p>}
    {history.length > 1 && <details><summary>查看历史版本</summary><ol>{history.slice(0, -1).reverse().map(note => <li key={note.id}>
      <p>第 {note.revision} 版 · {new Date(note.created_at).toLocaleString('zh-CN')}</p><p style={{whiteSpace: 'pre-wrap'}}>{note.text || '空白笔记'}</p>
    </li>)}</ol></details>}
  </details></section>;
}
