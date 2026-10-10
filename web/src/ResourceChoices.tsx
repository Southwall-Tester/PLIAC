import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {BookOpen} from 'lucide-react';
import {api, localLearner} from './api';
import {VideoResource} from './VideoResource';
import {ResourceDocument} from './ResourceDocument';
import {useSearchParams} from 'react-router-dom';

type Resource = {id: string; title: string; url: string; format: string; applicable_segment: string; video_segment?: {start_seconds: number; end_seconds: number} | null; for_current: boolean; reason: string; missing_prerequisites: {id: string; title: string}[]};
type Choices = {course_version: number; resources: Resource[]; notice: string};
const formatLabel: Record<string, string> = {video: '视频', lesson: '图文讲解', case: '案例与示例', practice: '练习', course: '课程'};
// B站官方外链播放器：只在点击后加载，不自动播放
function bilibiliEmbed(url: string) {
  const m = /^https:\/\/www\.bilibili\.com\/video\/(BV[0-9A-Za-z]{10})/.exec(url);
  return m ? `https://player.bilibili.com/player.html?bvid=${m[1]}&autoplay=0&high_quality=1&danmaku=0` : undefined;
}
function safeLink(value: string) {
  if (/^\/api\/documents\/[A-Za-z0-9_-]+\/source(?:#page=\d+)?$/.test(value)) return value;
  try {const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password ? url.href : undefined;} catch {return undefined;}
}
export function ResourceChoices({course, node, resourceId, label, openKey, text}: {course: string; node: string; resourceId?: string; label?: string; openKey?: number; text?: string}) {
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  const [search, setSearch] = useSearchParams();
  const requested = resourceId ? undefined : search.get('resource') || undefined;
  const previous = useRef<string | undefined>(undefined);
  useEffect(() => {if (requested) setOpen(true); else if (previous.current) setOpen(false); previous.current = requested;}, [requested]);
  useEffect(() => {if (openKey) setOpen(true);}, [openKey]);
  function close() {
    setOpen(false);
    if (requested) setSearch(value => {value.delete('resource'); return value;}, {replace: true});
    requestAnimationFrame(() => opener.current?.focus({preventScroll: true}));
  }
  return <><button ref={opener} aria-label={label || '选择学习材料'} onClick={() => setOpen(true)}>{label || <><BookOpen size={16}/>{text && <span className="label">{text}</span>}</>}</button>{open && <MaterialDialog key={course + node + (resourceId || requested)} course={course} node={node} resourceId={resourceId || requested} close={close}/>}</>;
}
function MaterialDialog({course, node, resourceId, close}: {course: string; node: string; resourceId?: string; close: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [value, setValue] = useState<Choices>();
  const [error, setError] = useState('');
  const [attempt, retry] = useState(0);
  const [format, setFormat] = useState('all');
  const [video, setVideo] = useState<string>();
  const [readingDocument, setReadingDocument] = useState<string>();
  function videoURL(item: Resource) {
    const link = safeLink(item.url);
    if (!link || item.format !== 'video') return undefined;
    const url = new URL(link, location.origin);
    return (url.protocol === 'https:' || url.origin === location.origin) && /\.(mp4|webm|ogg)$/i.test(url.pathname) ? url.href : undefined;
  }
  useEffect(() => {const focus = document.activeElement as HTMLElement; const element = dialog.current; element?.showModal(); return () => {element?.close(); focus?.focus({preventScroll: true});};}, []);
  useEffect(() => {
    const controller = new AbortController(); setError(''); setValue(undefined);
    const query = new URLSearchParams({course_id: course, node_id: node, student_id: localLearner()});
    api<Choices>(`/api/tutor/resources?${query}`, controller.signal).then(data => {if (!controller.signal.aborted) setValue(data);}).catch(failure => {if (!controller.signal.aborted) setError(failure.message);});
    return () => controller.abort();
  }, [course, node, attempt]);
  return createPortal(<dialog ref={dialog} className="source-preview" aria-label="选择学习材料" onCancel={close}>
    <header><h2>选择学习材料</h2><button autoFocus onClick={close}>关闭材料选择</button></header>
    {readingDocument ? <ResourceDocument key={readingDocument} course={course} resource={readingDocument} close={() => {
      const ident = readingDocument; setReadingDocument(undefined);
      requestAnimationFrame(() => dialog.current?.querySelector<HTMLButtonElement>(`[data-document-resource="${CSS.escape(ident)}"]`)?.focus({preventScroll: true}));
    }}/> : error ? <p role="alert">{error}<button onClick={() => retry(n => n + 1)}>重试读取材料</button></p> : !value ? <p role="status">正在读取课程材料…</p> : <>
      <p>{value.notice}</p>{resourceId ? <p>以下核对当前可用材料；历史推荐说明保留在原教学记录中。{!value.resources.some(item => item.id === resourceId) && '该推荐材料目前不再关联此知识点或已不可用，可关闭后重新选择其他材料。'}</p> : <label>材料形式<select value={format} onChange={e => setFormat(e.target.value)}><option value="all">全部形式</option>{[...new Set(value.resources.map(item => item.format))].map(item => <option key={item}>{item}</option>)}</select></label>}
      {!value.resources.length && <p>这个知识点暂时没有配套资料，可以先看讲解或在对话里提问。</p>}
      {value.resources.filter(item => resourceId ? item.id === resourceId : format === 'all' || item.format === format).map(item => <section className="archive-entry" key={item.id}>
        <small>{item.for_current ? '当前知识点' : '建议补充的基础'} · {formatLabel[item.format] || item.format}</small><h3>{item.title}</h3><p>{item.applicable_segment}</p>
        <p>{item.reason}</p>{!!item.missing_prerequisites.length && <p>前置仍待核验：{item.missing_prerequisites.map(node => node.title).join('、')}。可以先查看并向智能体求助。</p>}
        {safeLink(item.url) ? <a href={safeLink(item.url)} target="_blank" rel="noopener noreferrer">打开材料（新标签页）</a> : <p>该资源没有可安全打开的链接。</p>}
        {bilibiliEmbed(item.url) && (video === item.id
          ? <div className="bili-frame"><iframe src={bilibiliEmbed(item.url)} title={item.title} allowFullScreen sandbox="allow-scripts allow-same-origin allow-popups allow-presentation"/><button onClick={() => setVideo(undefined)}>收起视频</button></div>
          : <button className="primary" onClick={() => setVideo(item.id)}>在这里播放</button>)}
        {/^\/api\/documents\/[A-Za-z0-9_-]+\/source(?:#page=[1-9]\d*)?$/.test(item.url) && <button data-document-resource={item.id} onClick={() => {setVideo(undefined); setReadingDocument(item.id);}}>在工作台阅读原文件（PDF）</button>}
        {videoURL(item) && <><p>平台内播放将连接视频提供方。只有点击后才加载，不自动播放。</p>{video === item.id ? <VideoResource key={item.id} course={course} resource={item.id} url={videoURL(item)!} segment={item.video_segment} close={() => {
          setVideo(undefined);
          requestAnimationFrame(() => dialog.current?.querySelector<HTMLButtonElement>(`[data-video-resource="${CSS.escape(item.id)}"]`)?.focus({preventScroll: true}));
        }}/> : <button data-video-resource={item.id} onClick={() => setVideo(item.id)}>在工作台播放视频</button>}</>}
      </section>)}<p>打开材料不会改变学习目标或自动判掌握；外部网站的可用性和内容由其提供方决定。</p>
    </>}
  </dialog>, document.body);
}
