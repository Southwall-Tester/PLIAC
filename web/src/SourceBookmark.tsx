import {useEffect, useRef, useState} from 'react';
import {api, localLearner} from './api';

type Position = {source_id: string; mode: 'text' | 'page'; zoom: number; page: number};
type Saved = {revision: number; position: Position | null; changed?: boolean};
export function SourceBookmark({course, material, initial, current, allowed, restore}: {
  course: string; material: string; initial: string; current: Omit<Position, 'page'>;
  allowed: string[]; restore: (value: Position) => void;
}) {
  const [saved, setSaved] = useState<Saved>();
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const pending = useRef<{signature: string; id: string} | undefined>(undefined);
  async function read(signal: AbortSignal) {
    setBusy(true);
    try {
      const query = new URLSearchParams({course_id: course, student_id: localLearner(), material_id: material, source_id: initial});
      const value = await api<Saved>(`/api/tutor/source-position?${query}`, signal);
      if (!signal.aborted) {setSaved(value); pending.current = undefined; setMessage(value.changed ? '原文或引用已变化，旧位置不再套用。' : value.position ? `已保存第 ${value.position.page} 页，可主动恢复。` : '可保存引用页与显示模式；临时回看不会覆盖它。');}
    } catch (error) {if (!signal.aborted) setMessage((error as Error).message);}
    finally {if (!signal.aborted) setBusy(false);}
  }
  useEffect(() => {
    const abort = new AbortController(); controller.current = abort;
    void read(abort.signal);
    return () => abort.abort();
  }, [course, material, initial]);
  async function save() {
    if (!saved || busy || !controller.current) return;
    const signal = controller.current.signal;
    const body = {student_id: localLearner(), material_id: material, expected_revision: saved.revision, ...current};
    const signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = {signature, id: crypto.randomUUID()};
    setBusy(true);
    try {
      const response = await fetch(`/api/tutor/source-position?course_id=${encodeURIComponent(course)}`, {method: 'POST', signal,
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...body, request_id: pending.current.id})});
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || '原文位置未保存。');
      if (!signal.aborted) {setSaved(value); pending.current = undefined; setMessage('引用页与显示模式已保存到学习档案。');}
    } catch (error) {if (!signal.aborted) setMessage((error as Error).message);}
    finally {if (!signal.aborted) setBusy(false);}
  }
  return <details><summary>跨次原文续读</summary>
    <button disabled={busy || !saved} onClick={save}>保存当前原文页</button>
    <button disabled={busy || !saved?.position || !allowed.includes(saved.position.source_id)} onClick={() => {if (saved?.position) restore(saved.position);}}>恢复原文续读</button>
    <button disabled={busy} onClick={() => {if (controller.current) void read(controller.current.signal);}}>重新读取原文位置</button>
    <p role="status">{busy ? '正在处理原文位置…' : message}</p>
  </details>;
}
