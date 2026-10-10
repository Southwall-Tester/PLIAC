import {useEffect, useRef, useState} from 'react';
import {api, localLearner} from './api';

type Saved = {revision: number; seconds: number | null; changed?: boolean};
export function VideoResource({course, resource, url, segment, close}: {course: string; resource: string; url: string; segment?: {start_seconds: number; end_seconds: number} | null; close: () => void}) {
  const player = useRef<HTMLVideoElement>(null);
  const abort = useRef<AbortController | null>(null);
  const pending = useRef<{seconds: number; revision: number; id: string} | undefined>(undefined);
  const [saved, setSaved] = useState<Saved>();
  const [ready, setReady] = useState(false);
  const [seeking, setSeeking] = useState(false);
  const restoring = useRef<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  async function read(signal: AbortSignal) {
    try {
      const value = await api<Saved>(`/api/tutor/resource-position?${new URLSearchParams({course_id: course, student_id: localLearner(), resource_id: resource})}`, signal);
      if (!signal.aborted) {setSaved(value); pending.current = undefined; setMessage(value.changed ? '课程或资源信息已变化，旧位置不自动使用。' : value.seconds !== null ? `已保存到 ${Math.floor(value.seconds)} 秒，可主动恢复。` : '会记住播放位置。');}
    } catch (error) {if (!signal.aborted) setMessage((error as Error).message);}
  }
  useEffect(() => {
    const controller = new AbortController(); abort.current = controller;
    const element = player.current;
    if (element && !element.hasAttribute('src')) {element.src = url; element.load();}
    element?.focus({preventScroll: true});
    void read(controller.signal);
    return () => {controller.abort(); element?.pause(); element?.removeAttribute('src'); element?.load();};
  }, [course, resource, url]);
  async function save() {
    if (!saved || !ready || busy || !player.current || !abort.current) return;
    const seconds = player.current.currentTime;
    if (!Number.isFinite(seconds)) return;
    if (!pending.current || pending.current.seconds !== seconds || pending.current.revision !== saved.revision) pending.current = {seconds, revision: saved.revision, id: crypto.randomUUID()};
    const signal = abort.current.signal; setBusy(true);
    try {
      const response = await fetch(`/api/tutor/resource-position?course_id=${encodeURIComponent(course)}`, {method: 'POST', signal, headers: {'Content-Type': 'application/json'}, body: JSON.stringify({student_id: localLearner(), resource_id: resource, seconds, expected_revision: saved.revision, request_id: pending.current.id})});
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || '播放位置未保存。');
      if (!signal.aborted) {setSaved(value); pending.current = undefined; setMessage('播放位置已保存到学习档案。');}
    } catch (error) {if (!signal.aborted) setMessage((error as Error).message);}
    finally {if (!signal.aborted) setBusy(false);}
  }
  function restore() {
    const element = player.current;
    if (!element || saved?.seconds == null) return;
    if (!Number.isFinite(element.duration) || saved.seconds > element.duration) {setMessage('当前视频不支持该位置恢复，或时长已变化，请手动定位。'); return;}
    element.pause();
    if (Math.abs(element.currentTime - saved.seconds) < .1) {setMessage('已定位到保存时间，请按播放继续。'); return;}
    restoring.current = saved.seconds;
    setMessage('正在定位到保存时间…'); element.currentTime = saved.seconds;
  }
  function locateSegment() {
    const element = player.current;
    if (!element || !segment) return;
    if (!Number.isFinite(element.duration) || segment.end_seconds > element.duration) {
      setMessage('推荐片段超出当前视频时长，请核对课程资源；仍可手动观看完整视频。'); return;
    }
    element.pause();
    element.currentTime = segment.start_seconds;
    setMessage(`已请求定位到推荐起点 ${segment.start_seconds} 秒，请确认位置后主动播放；可自由观看其他部分。`);
  }
  function seeked() {
    setSeeking(false);
    if (restoring.current !== null && player.current) {
      setMessage(Math.abs(player.current.currentTime - restoring.current) < .5 ? '已定位到保存时间，请按播放继续。' : '视频提供方未能定位到保存时间，请手动选择位置。');
      restoring.current = null;
    }
  }
  return <div aria-label="课程视频播放器">
    {segment && <p>课程推荐片段：{segment.start_seconds}—{segment.end_seconds} 秒。<button disabled={!ready || busy || seeking} onClick={locateSegment}>定位推荐片段</button></p>}
    <video ref={player} src={url} controls playsInline crossOrigin="anonymous" preload="metadata" style={{width: '100%', maxHeight: '60vh'}} onSeeking={() => setSeeking(true)} onSeeked={seeked} onLoadedMetadata={() => setReady(true)} onError={() => {setReady(false); setSeeking(false); restoring.current = null; setMessage('视频无法在平台内播放，可能是格式、权限或跨域限制。可关闭播放器并打开原链接。');}} onEnded={() => setMessage('看完了，去做几道题检验一下吧。')}/>
    <button disabled={!ready || !saved || busy || seeking} onClick={save}>保存视频位置</button><button disabled={!ready || saved?.seconds == null || busy || seeking} onClick={restore}>恢复视频位置</button>
    <button disabled={busy} onClick={() => {if (abort.current) void read(abort.current.signal);}}>重新读取视频位置</button><button onClick={close}>关闭视频</button>
    <p role="status">{message}</p><p>只保存时间点。外部提供方可能在相同链接下更换内容，平台无法保证视频文件未改变。</p>
  </div>;
}
