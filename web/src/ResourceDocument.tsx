import {useEffect, useRef, useState} from 'react';
import {api, localLearner} from './api';

type Position = {page: number; mode: 'text' | 'page'; zoom: number};
type DocumentInfo = {title: string; page_count: number; initial_page: number; signature: string; revision: number; changed: boolean; position: Position | null};

export function ResourceDocument({course, resource, close}: {course: string; resource: string; close: () => void}) {
  const [info, setInfo] = useState<DocumentInfo>();
  const [position, setPosition] = useState<Position>({page: 1, mode: 'page', zoom: 100});
  const [content, setContent] = useState<{key: string; image?: string; text?: string; notice?: string}>();
  const [error, setError] = useState('');
  const [pageError, setPageError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempt, retry] = useState(0);
  const lifetime = useRef<AbortController | null>(null);
  const pending = useRef<{signature: string; id: string} | undefined>(undefined);
  const query = () => new URLSearchParams({course_id: course, student_id: localLearner(), resource_id: resource});
  async function load(signal: AbortSignal) {
    setBusy(true); setError(''); setInfo(undefined);
    try {
      const value = await api<DocumentInfo>(`/api/tutor/resource-document?${query()}`, signal);
      if (!signal.aborted) {
        setInfo(value); pending.current = undefined;
        setPosition(value.position || {page: value.initial_page, mode: 'page', zoom: 100});
        setMessage(value.changed ? '原文件或课程资源已更新，旧阅读位置未套用。' : value.position ? `已恢复保存的第 ${value.position.page} 页。` : '可以保存页码与显示模式，下次打开时恢复。');
      }
    } catch (failure) {if (!signal.aborted) setError((failure as Error).message);}
    finally {if (!signal.aborted) setBusy(false);}
  }
  useEffect(() => {
    const controller = new AbortController(); lifetime.current = controller;
    void load(controller.signal);
    return () => controller.abort();
  }, [course, resource]);
  const key = `${info?.signature}:${position.page}:${position.mode}`;
  useEffect(() => {
    if (!info) return;
    const controller = new AbortController(); let objectURL = '';
    setPageError(''); setContent(undefined);
    const params = query(); params.set('page', String(position.page)); params.set('mode', position.mode); params.set('signature', info.signature);
    fetch(`/api/tutor/resource-document-page?${params}`, {signal: controller.signal}).then(async response => {
      if (!response.ok) {const value = await response.json(); throw new Error(value.detail || '页面未加载。');}
      if (position.mode === 'text') {
        const value = await response.json();
        if (!controller.signal.aborted) setContent({key, text: value.text, notice: value.notice});
      } else {
        const blob = await response.blob();
        if (!controller.signal.aborted) {objectURL = URL.createObjectURL(blob); setContent({key, image: objectURL});}
      }
    }).catch(failure => {if (!controller.signal.aborted) setPageError(failure.message);});
    return () => {controller.abort(); if (objectURL) URL.revokeObjectURL(objectURL);};
  }, [course, resource, info?.signature, position.page, position.mode, attempt]);
  async function save() {
    if (!info || busy || !lifetime.current) return;
    const signal = lifetime.current.signal;
    const body = {student_id: localLearner(), resource_id: resource, signature: info.signature, expected_revision: info.revision, ...position};
    const signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = {signature, id: crypto.randomUUID()};
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/tutor/resource-document-position?course_id=${encodeURIComponent(course)}`, {method: 'POST', signal,
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...body, request_id: pending.current.id})});
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || '阅读位置未保存。');
      if (!signal.aborted) {setInfo(value); pending.current = undefined; setMessage(`第 ${position.page} 页与显示模式已保存。`);}
    } catch (failure) {if (!signal.aborted) setError((failure as Error).message);}
    finally {if (!signal.aborted) setBusy(false);}
  }
  return <section aria-label="课程 PDF 阅读器">
    <button autoFocus onClick={close}>返回材料列表</button><h3>{info?.title || '课程原文件'}</h3>
    <p>课程提供的完整 PDF，会记住你读到的页码。</p>
    {error && <p role="alert">{error}</p>}
    <button disabled={busy} onClick={() => {if (lifetime.current) void load(lifetime.current.signal);}}>重新读取文件与位置</button>
    {busy && <p role="status">正在处理阅读位置…</p>}
    {info && <>
      <div className="document-reader-controls">
        <button disabled={busy || position.page <= 1} onClick={() => setPosition(value => ({...value, page: value.page - 1}))}>上一页</button>
        <label>原文件页码<input type="number" min={1} max={info.page_count} value={position.page} disabled={busy} onChange={event => {
          const page = Number(event.target.value); if (Number.isInteger(page) && page >= 1 && page <= info.page_count) setPosition(value => ({...value, page}));
        }}/></label><span>共 {info.page_count} 页</span>
        <button disabled={busy || position.page >= info.page_count} onClick={() => setPosition(value => ({...value, page: value.page + 1}))}>下一页</button>
        <label>显示模式<select disabled={busy} value={position.mode} onChange={event => setPosition(value => ({...value, mode: event.target.value as Position['mode']}))}><option value="page">PDF 原版式</option><option value="text">文字模式</option></select></label>
        {position.mode === 'page' && <label>页面大小<select disabled={busy} value={position.zoom} onChange={event => setPosition(value => ({...value, zoom: Number(event.target.value)}))}><option value={100}>适合宽度</option><option value={150}>放大 1.5 倍</option><option value={200}>放大 2 倍</option></select></label>}
        <button disabled={busy || !!pageError || content?.key !== key} onClick={save}>保存文件阅读位置</button>
      </div>
      <p role="status">{message}</p>
      {pageError ? <p role="alert">{pageError}<button onClick={() => retry(value => value + 1)}>重试当前页</button></p> : content?.key !== key ? <p role="status">正在读取第 {position.page} 页…</p> : content.image ?
        <div tabIndex={0} aria-label="PDF 页面阅读区域" style={{overflowX: 'auto', maxWidth: '100%'}}><img src={content.image} alt={`原文件第 ${position.page} 页`} style={{display: 'block', width: `${position.zoom}%`, maxWidth: 'none', height: 'auto'}}/></div>
        : <><p>{content.notice}</p><div className="source-text">{content.text || '本页没有可提取文字，请切换 PDF 原版式。'}</div></>}
    </>}
  </section>;
}
