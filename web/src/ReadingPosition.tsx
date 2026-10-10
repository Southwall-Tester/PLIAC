import {useEffect, useRef, useState} from 'react';
import {useParams} from 'react-router-dom';
import {api, localLearner} from './api';

type Saved = {revision: number; position: {anchor: string; offset: number} | null; changed?: boolean};

export function ReadingPosition({materialId}: {materialId: string}) {
  const {courseId = ''} = useParams();
  const element = useRef<HTMLDivElement>(null);
  const [saved, setSaved] = useState<Saved>();
  const [message, setMessage] = useState('正在读取续读位置…');
  const [busy, setBusy] = useState(false);
  const pending = useRef<Record<string, unknown> | undefined>(undefined);
  const query = new URLSearchParams({course_id: courseId, student_id: localLearner(), material_id: materialId});
  async function reload() {
    try {const value = await api<Saved>(`/api/learning/reading-position?${query}`); setSaved(value); pending.current = undefined; setMessage(value.changed ? '材料内容已变化，旧位置不自动套用。' : '已读取服务器续读位置。');}
    catch (error) {setMessage((error as Error).message);}
  }
  useEffect(() => {
    const abort = new AbortController();
    api<Saved>(`/api/learning/reading-position?${query}`, abort.signal).then(value => {
      if (!abort.signal.aborted) {setSaved(value); setMessage(value.changed ? '材料内容已变化，旧位置不自动套用。' : value.position ? '已保存续读位置，可跨浏览器恢复。' : '可以保存当前位置，临时回看不会覆盖它。');}
    }).catch(error => {if (!abort.signal.aborted) setMessage(error.message);});
    return () => abort.abort();
  }, [courseId, materialId]);
  function targets() {
    const article = element.current?.closest('article');
    return article ? [article, ...Array.from(article.querySelectorAll<HTMLElement>('section[id^="paragraph-"]'))] : [];
  }
  async function save() {
    if (!saved || busy) return;
    const pane = element.current?.closest<HTMLElement>('.lesson-pane');
    if (!pane) return;
    const top = pane.getBoundingClientRect().top;
    const nodes = targets();
    const anchor = nodes.filter(node => node.getBoundingClientRect().top <= top + 1).at(-1) || nodes[0];
    if (!anchor) return;
    const position = {anchor: anchor.id || 'top', offset: Math.max(0, Math.min(10000, top - anchor.getBoundingClientRect().top))};
    if (!pending.current || pending.current.anchor !== position.anchor || pending.current.offset !== position.offset) {
      pending.current = {student_id: localLearner(), material_id: materialId, expected_revision: saved.revision, request_id: crypto.randomUUID(), ...position};
    }
    setBusy(true); setMessage('正在保存续读位置…');
    try {
      const response = await fetch(`/api/learning/reading-position?course_id=${encodeURIComponent(courseId)}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(pending.current)});
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || '保存未完成，请重试。');
      setSaved(value); pending.current = undefined; setMessage('续读位置已保存到服务器。');
    } catch (error) {setMessage((error as Error).message);}
    finally {setBusy(false);}
  }
  function restore() {
    if (!saved?.position) return;
    const pane = element.current?.closest<HTMLElement>('.lesson-pane');
    const anchor = targets().find(node => (node.id || 'top') === saved.position!.anchor);
    if (!pane || !anchor) {setMessage('原段落暂不可用，请等待正文载入或重新选择位置。'); return;}
    pane.scrollTop += anchor.getBoundingClientRect().top - pane.getBoundingClientRect().top + Math.min(saved.position.offset, anchor.getBoundingClientRect().height);
    setMessage('已回到保存的阅读段落；排版变化时位置可能略有偏移。');
  }
  return <div className="reading-position" ref={element} aria-label="跨次续读">
    <button disabled={!saved || busy} onClick={save}>保存为续读位置</button>
    <button disabled={!saved?.position || busy} onClick={restore}>回到续读位置</button>
    <button disabled={busy} onClick={reload}>重新读取位置</button><small role="status">{message}</small>
  </div>;
}
