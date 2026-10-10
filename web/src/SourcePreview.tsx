import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {useParams} from 'react-router-dom';
import {api, localLearner, type TutorTurn} from './api';
import {SourceBookmark} from './SourceBookmark';

type Preview = {title: string; page: number; text: string; changed: boolean; notice: string};

export function SourcePreview({turn, initial, close}: {turn: TutorTurn; initial: string; close: () => void}) {
  const {courseId = ''} = useParams();
  const dialog = useRef<HTMLDialogElement>(null);
  const [sourceId, setSourceId] = useState(initial);
  const [value, setValue] = useState<Preview>();
  const [error, setError] = useState('');
  const [attempt, retry] = useState(0);
  const [mode, setMode] = useState<'text' | 'page'>('text');
  const [pageImage, setPageImage] = useState('');
  const [zoom, setZoom] = useState(100);
  const initialSource = turn.source_catalog?.find(item => item.id === initial);
  const originalURL = initialSource?.url?.split('#')[0];
  const pages = (turn.source_catalog || []).filter((item, index, all) => item.origin === 'uploaded_document' && item.url?.split('#')[0] === originalURL
    && (item.page === initialSource?.page ? item.id === initial : all.findIndex(other => other.url?.split('#')[0] === originalURL && other.page === item.page) === index));
  useEffect(() => {
    const target = dialog.current;
    const focus = document.activeElement as HTMLElement | null;
    target?.showModal();
    return () => {target?.close(); focus?.focus({preventScroll: true});};
  }, []);
  useEffect(() => {
    const controller = new AbortController(); setValue(undefined); setPageImage(''); setError('');
    let objectURL = '';
    const query = new URLSearchParams({course_id: courseId, student_id: localLearner(), material_id: turn.request_id, source_id: sourceId});
    if (mode === 'text') api<Preview>(`/api/tutor/source-preview?${query}`, controller.signal).then(data => {if (!controller.signal.aborted) setValue(data);})
      .catch(failure => {if (!controller.signal.aborted) setError(failure.message);});
    else fetch(`/api/tutor/source-page-image?${query}`, {signal: controller.signal}).then(async response => {
      if (!response.ok) {const failure = await response.json(); throw new Error(failure.detail || '原版式加载失败。');}
      const blob = await response.blob();
      if (!controller.signal.aborted) {objectURL = URL.createObjectURL(blob); setPageImage(objectURL);}
    }).catch(failure => {if (!controller.signal.aborted) setError(failure.message);});
    return () => {controller.abort(); if (objectURL) URL.revokeObjectURL(objectURL);};
  }, [courseId, turn.request_id, sourceId, attempt, mode]);
  return createPortal(<dialog ref={dialog} className="source-preview" aria-label="课程原文预览" onCancel={close}>
    <header><h2>课程原文预览</h2><button onClick={close} autoFocus>关闭原文预览</button></header>
    <label>本次讲解关联的原文页<select value={sourceId} onChange={e => setSourceId(e.target.value)}>
      {pages.map(item => <option value={item.id} key={item.id}>第 {item.page} 页／单元</option>)}
    </select></label>
    <p>这次讲解引用的原文页。</p>
    <SourceBookmark course={courseId} material={turn.request_id} initial={initial} current={{source_id: sourceId, mode, zoom}} allowed={pages.map(item => item.id)} restore={value => {setSourceId(value.source_id); setMode(value.mode); setZoom(value.zoom);}}/>
    <div><button aria-pressed={mode === 'text'} onClick={() => setMode('text')}>文字模式</button> <button aria-pressed={mode === 'page'} onClick={() => setMode('page')}>PDF 原版式</button></div>
    {mode === 'page' && <p>显示当前原文件的引用页，不是生成讲解时的历史文件快照。图片不运行文件中的脚本或链接；需要复制文字可切回文字模式。</p>}
    {mode === 'page' && <label>原版式大小<select value={zoom} onChange={e => setZoom(Number(e.target.value))}><option value={100}>适合宽度</option><option value={150}>放大 1.5 倍</option><option value={200}>放大 2 倍</option></select></label>}
    {error ? <p role="alert">{error}<button onClick={() => retry(n => n + 1)}>重试原文预览</button></p> : mode === 'page' ? pageImage ? <div style={{overflowX: 'auto', maxWidth: '100%'}} tabIndex={0} aria-label="原版式阅读区域"><img src={pageImage} alt={`课程原文第 ${pages.find(item => item.id === sourceId)?.page} 页`} style={{display: 'block', width: `${zoom}%`, maxWidth: 'none', height: 'auto'}}/></div> : <p role="status">正在显示原版式…</p> : !value ? <p role="status">正在读取原文…</p> : <>
      <h3>{value.title} · 第 {value.page} 页／单元</h3><p>{value.notice}</p>
      {value.changed && <p role="status">原文已与生成讲解时不同；历史引文未改写，请核对差异。</p>}
      <div className="source-text">{value.text}</div>
    </>}
  </dialog>, document.body);
}
