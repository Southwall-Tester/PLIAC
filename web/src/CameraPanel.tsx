import {useEffect, useRef, useState} from 'react';
import {api, learnerKey, localLearner} from './api';
import {MediaReview} from './MediaReview';
import {useAccessSession} from './Identity';

type Policy = {enabled: boolean; version: string; purpose: string; limits: string; withdrawal: string; retention_days: number; contact: string};
type Session = {id: string; activity_kind: string; activity_id: string; status: string; started: number;
  clips?: {sequence: number; start_ms: number; duration_ms: number}[]};
type Activity = {kind: string; id: string};

export function CameraPanel({courseId, activity}: {courseId: string; activity?: Activity}) {
  const access = useAccessSession();
  const [policy, setPolicy] = useState<Policy>();
  const [session, setSession] = useState<Session>();
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(0);
  const [hasHistory, setHasHistory] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const epoch = useRef(0);
  const current = useRef<Session | undefined>(undefined);
  const controlling = useRef(false);
  const alive = useRef(true);
  const key = learnerKey(`camera-session.${courseId}`);
  const query = (extra: Record<string, string> = {}) => new URLSearchParams({course_id: courseId, student_id: localLearner(), ...extra});
  async function post(operation: string, fields: Record<string, unknown>, keepalive = false) {
    const response = await fetch(`/api/media/${operation}?course_id=${encodeURIComponent(courseId)}`, {method: 'POST', keepalive,
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify({student_id: localLearner(), ...fields})});
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '摄像头操作未完成。');
    return value;
  }
  function release() {
    epoch.current += 1;
    if (recorder.current?.state === 'recording') recorder.current.stop();
    stream.current?.getTracks().forEach(track => track.stop()); stream.current = null;
    if (video.current) video.current.srcObject = null;
    if (alive.current) setRunning(false);
  }
  async function control(operation: 'pause' | 'stop' | 'revoke') {
    release();
    if (controlling.current) return;
    const ident = current.current?.id;
    if (!ident) return;
    controlling.current = true;
    setBusy(true); setError('');
    try {
      const value = await post('control', {session_id: ident, operation}, true);
      if (alive.current) {current.current = value; setSession(value); if (operation === 'revoke') setSaved(0);}
    } catch (failure) {if (alive.current) setError(`设备已关闭，但服务端状态未确认：${(failure as Error).message}`);}
    finally {controlling.current = false; if (alive.current) setBusy(false);}
  }
  useEffect(() => {
    alive.current = true;
    const abort = new AbortController();
    api<Policy>('/api/media/policy', abort.signal).then(setPolicy).catch(() => {});
    if (access.protected && access.identity) api<Session[]>(`/api/media/sessions?${query()}`, abort.signal).then(items => {
      if (!abort.signal.aborted) setHasHistory(items.length > 0);
    }).catch(() => {});
    const ident = sessionStorage.getItem(key);
    if (ident) api<Session>(`/api/media/session?${query({session_id: ident})}`, abort.signal).then(async value => {
      if (abort.signal.aborted) return;
      current.current = value; setSession(value); setSaved(value.clips?.length || 0);
      if (value.status === 'active') {
        const paused = await post('control', {session_id: value.id, operation: 'pause'});
        if (!abort.signal.aborted) {current.current = paused; setSession(paused);}
      }
    }).catch(failure => {if (!abort.signal.aborted) setError(failure.message);});
    const hide = () => {if (document.hidden && stream.current) void control('pause');};
    const exit = () => {
      release(); const ident = current.current?.id;
      if (ident && ['active', 'paused'].includes(current.current?.status || '')) void post('control', {session_id: ident, operation: 'stop'}, true).catch(() => {});
    };
    document.addEventListener('visibilitychange', hide); window.addEventListener('pagehide', exit);
    return () => {alive.current = false; abort.abort(); exit(); document.removeEventListener('visibilitychange', hide); window.removeEventListener('pagehide', exit);};
  }, [courseId]);
  useEffect(() => {
    if (current.current && (current.current.activity_id !== activity?.id || current.current.activity_kind !== activity?.kind)) {
      release();
      if (['active', 'paused'].includes(current.current.status)) void control('stop');
    }
    setAccepted(false);
  }, [activity?.id, activity?.kind]);

  async function start() {
    if (!accepted || !activity || !policy?.enabled || busy || running) return;
    setBusy(true); setError(''); const ticket = ++epoch.current;
    let active: Session | undefined;
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !MediaRecorder.isTypeSupported('video/webm;codecs=vp8')) throw new Error('当前浏览器不支持所需摄像头格式，可继续正常学习。');
      const previous = current.current;
      if (previous?.status === 'paused' && previous.activity_id === activity.id && previous.activity_kind === activity.kind) {
        active = await post('control', {session_id: previous.id, operation: 'resume'});
      } else {
        if (previous && ['active', 'paused'].includes(previous.status)) await post('control', {session_id: previous.id, operation: 'stop'});
        const requestKey = `${key}.request.${activity.kind}.${activity.id}.${policy.version}`;
        const requestId = sessionStorage.getItem(requestKey) || crypto.randomUUID();
        sessionStorage.setItem(requestKey, requestId);
        active = await post('start', {request_id: requestId, activity_kind: activity.kind, activity_id: activity.id, accepted: true, policy_version: policy.version});
        sessionStorage.removeItem(requestKey);
      }
      current.current = active; sessionStorage.setItem(key, active!.id);
      if (ticket !== epoch.current || !alive.current) {await post('control', {session_id: active!.id, operation: 'stop'}, true); return;}
      if (active!.status !== 'active') throw new Error('此前采集已结束，请重新开始并确认授权。');
      setSession(active);
      const media = await navigator.mediaDevices.getUserMedia({audio: false, video: {width: {ideal: 480}, height: {ideal: 360}, frameRate: {ideal: 12, max: 15}}});
      if (ticket !== epoch.current || !alive.current) {media.getTracks().forEach(track => track.stop()); return;}
      stream.current = media; if (video.current) video.current.srcObject = media;
      media.getVideoTracks().forEach(track => track.addEventListener('ended', () => {if (ticket === epoch.current) void control('pause');}));
      setRunning(true); setBusy(false);
      const stored = await api<Session>(`/api/media/session?${query({session_id: active!.id})}`);
      let sequence = stored.clips?.length || 0;
      const last = stored.clips?.at(-1);
      const offset = Math.max(last ? last.start_ms + last.duration_ms : 0, Date.now() - active!.started * 1000);
      const clock = performance.now();
      while (ticket === epoch.current && alive.current) {
        const begun = performance.now();
        const blob = await new Promise<Blob>((resolve, reject) => {
          const chunks: Blob[] = [];
          const item = new MediaRecorder(media, {mimeType: 'video/webm;codecs=vp8', videoBitsPerSecond: 240_000});
          recorder.current = item;
          item.ondataavailable = event => {if (event.data.size) chunks.push(event.data);};
          item.onerror = () => {clearTimeout(timer); reject(new Error('摄像头录制失败。'));};
          item.onstop = () => {clearTimeout(timer); resolve(new Blob(chunks, {type: 'video/webm'}));};
          const timer = window.setTimeout(() => {if (item.state === 'recording') item.stop();}, 5000);
          item.start();
        });
        if (ticket !== epoch.current || !alive.current) break;
        const duration = performance.now() - begun;
        if (!blob.size || blob.size > 1_000_000 || duration > 20_000) throw new Error('片段大小或时长超限，已停止采集。');
        const encoded = await new Promise<string>((resolve, reject) => {const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = reject; reader.readAsDataURL(blob);});
        if (ticket !== epoch.current || !alive.current) break;
        await post('upload', {session_id: active!.id, sequence, start_ms: offset + begun - clock, duration_ms: duration, content_base64: encoded});
        sequence += 1; if (alive.current && ticket === epoch.current) setSaved(sequence);
      }
    } catch (failure) {
      if (ticket !== epoch.current || !alive.current) return;
      release();
      const cause = failure as Error;
      let message = cause.name === 'NotAllowedError'
        ? '浏览器未允许摄像头访问。本页未采集视频，正常学习不受影响；如需使用，可在浏览器站点权限中允许摄像头后重试。'
        : cause.name === 'NotFoundError'
          ? '未找到可用摄像头，正常学习不受影响。连接设备后可以重试。'
          : `${cause.message || '摄像头不可用。'} 正常学习不受影响。`;
      if (active) {
        try {
          const stopped = await post('control', {session_id: active.id, operation: 'stop'}, true);
          current.current = stopped; if (alive.current) setSession(stopped);
        } catch {
          message += ' 本页设备已关闭，但服务端停止状态未确认，请重试“停止本次采集”。';
        }
      }
      if (alive.current) {setBusy(false); setError(message);}
    } finally {if (alive.current && ticket === epoch.current) setBusy(false);}
  }
  if (!policy?.enabled && !session && !hasHistory) return null;
  return <details className="camera-panel"><summary>摄像头 · {running ? '正在采集' : '设备未采集'}</summary>
    {policy?.enabled && <><p>{policy.purpose}</p><p>{policy.limits}</p><p>保存 {policy.retention_days} 天。联系：{policy.contact}</p><p>{policy.withdrawal}</p></>}
    <p>每段单独保存，上传间隔可能有缺口。拒绝或关闭不影响学习。暂停、隐藏页面或离开活动会关闭本页设备。</p>
    <video ref={video} autoPlay playsInline muted aria-label="本地摄像头预览" style={{width: '100%', maxWidth: 320}}/>
    <p role="status">已保存 {saved} 个片段；设备{running ? '正在采集' : '未采集'}。</p>
    {!running && <label><input type="checkbox" checked={accepted} onChange={event => setAccepted(event.target.checked)}/>我同意上述可选摄像头用途与保存规则</label>}
    {!running && <button disabled={!accepted || !activity || !policy?.enabled || busy} onClick={start}>授权并开始采集</button>}
    {!activity && <p>请先进入已保存的学习材料、核验或实验活动。</p>}
    {(running || busy) && <button onClick={() => control('pause')}>暂停并关闭设备</button>}
    {session && <><button onClick={() => control('stop')}>停止本次采集</button><button onClick={() => control('revoke')}>撤回并删除本次片段</button></>}
    {!running && !busy && <MediaReview courseId={courseId} revision={`${session?.status}:${saved}`} revoke={async id => {
      if (id === current.current?.id) release();
      const value = await post('control', {session_id: id, operation: 'revoke'});
      if (id === current.current?.id) {current.current = value; setSession(value); setSaved(0);}
    }}/>}
    {error && <p role="alert">{error}</p>}
  </details>;
}
