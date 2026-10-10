import {useEffect, useState} from 'react';
import {api, localLearner} from './api';

type Session = {id: string; activity_kind: string; activity_id: string; status: string; started: number; expires: number};
type Detail = Session & {clips: {sequence: number; start_ms: number; duration_ms: number}[];
  timeline?: {items: {id: string; label: string; relative_ms: number; sequences: number[]; detail?: string}[]; truncated: boolean}};
const statuses: Record<string, string> = {active: '采集中', paused: '已暂停', closed: '已结束', revoked: '已撤回', expired: '已到期'};

export function MediaReview({courseId, revision, revoke, studentId}: {courseId: string; revision: string; revoke?: (id: string) => Promise<void>; studentId?: string}) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, select] = useState('');
  const [detail, setDetail] = useState<Detail>();
  const [clip, setClip] = useState<number>();
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const query = new URLSearchParams({course_id: courseId, student_id: studentId || localLearner()});
  const prefix = studentId ? '/api/media/review' : '/api/media';
  useEffect(() => {
    const abort = new AbortController();
    api<Session[]>(`${prefix}/sessions?${query}`, abort.signal).then(setSessions).catch(e => {if (!abort.signal.aborted) setError(e.message);});
    return () => abort.abort();
  }, [courseId, revision, refresh]);
  useEffect(() => {
    const abort = new AbortController(); setDetail(undefined); setClip(undefined); setError('');
    if (selected) api<Detail>(`${prefix}/session?${query}&session_id=${encodeURIComponent(selected)}`, abort.signal)
      .then(setDetail).catch(e => {if (!abort.signal.aborted) setError(e.message);});
    return () => abort.abort();
  }, [courseId, selected, revision, refresh]);
  async function remove() {
    if (!selected || deleting || !revoke) return;
    setDeleting(true); setClip(undefined); setError('');
    try {await revoke(selected); setRefresh(n => n + 1);} catch (e) {setError((e as Error).message);}
    finally {setDeleting(false);}
  }
  return <section aria-label={studentId ? '授权片段回看' : '本人片段回看'}>
    <h3>{studentId ? '授权片段回看' : '本人片段回看'}</h3><button onClick={() => setRefresh(n => n + 1)}>刷新保存记录</button>
    <label>采集记录<select value={selected} onChange={e => select(e.target.value)}><option value="">选择一次采集</option>
      {sessions.map(item => <option key={item.id} value={item.id}>{new Date(item.started * 1000).toLocaleString()} · {statuses[item.status] || item.status} · {item.activity_kind}</option>)}
    </select></label>
    {detail && <><p>关联活动：{detail.activity_kind} / {detail.activity_id}。到期时间：{new Date(detail.expires * 1000).toLocaleString()}。</p>
      <p>以下时间相对于采集会话开始，间隔没有视频，不代表学习状态。</p>
      <ol>{detail.clips.map(item => <li key={item.sequence}><button onClick={() => setClip(item.sequence)}>片段 {item.sequence + 1} · {(item.start_ms / 1000).toFixed(1)}—{((item.start_ms + item.duration_ms) / 1000).toFixed(1)} 秒</button></li>)}</ol>
      {!detail.clips.length && <p>没有可回看的片段。</p>}
      {!!detail.timeline?.items.length && <details><summary>关联活动的关键事件</summary>
        <p>仅列出本活动、已保存视频时间范围内的服务器事件。时间为近似对应，不是逐帧同步；缺少事件或视频不代表任何学习情绪。</p>
        {detail.timeline.truncated && <p>此处展示最近 200 条事件。</p>}
        <ol>{detail.timeline.items.map(item => <li key={item.id}>
          <p>{(item.relative_ms / 1000).toFixed(1)} 秒 · {item.label}{item.detail && ` · ${item.detail}`}</p>
          {item.sequences.map(sequence => <button key={sequence} onClick={() => setClip(sequence)}>打开关联片段 {sequence + 1}</button>)}
          {!item.sequences.length && <p>该时刻没有已保存的视频片段。</p>}
        </li>)}</ol>
      </details>}
      {clip !== undefined && <video key={`${detail.id}:${clip}`} controls playsInline preload="metadata" aria-label="已保存片段播放器" style={{width: '100%'}}
        src={`${prefix}/clip?${query}&session_id=${encodeURIComponent(detail.id)}&sequence=${clip}`} onError={() => {setClip(undefined); setError('片段不可播放，可能已到期或撤回，请刷新记录。');}}/>}
      {revoke && !['revoked', 'expired'].includes(detail.status) && <button disabled={deleting} onClick={remove}>撤回并删除所选记录</button>}
    </>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
