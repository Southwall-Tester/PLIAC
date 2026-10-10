import {useEffect, useRef, useState} from 'react';
import {Link, useSearchParams} from 'react-router-dom';
import {api} from './api';
import {useAccessSession} from './Identity';

type Status = {status: string; job_id: string; job_owner: string; course_version: number; course_title: string; published_version: number | null; attempts: number; retry_remaining: number};
const labels: Record<string, string> = {not_started: '尚未核验', running: '核验中', generated: '核验结果已保存', failed: '核验未完成', interrupted: '任务中断'};
export function KnowledgeActivation() {
  const access = useAccessSession();
  const [search] = useSearchParams();
  const [course, setCourse] = useState(search.get('course') || '');
  const [target, setTarget] = useState('');
  const [status, setStatus] = useState<Status>();
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {const value = new AbortController(); controller.current = value; return () => value.abort();}, []);
  if (!access.protected || access.identity?.role !== 'admin') return <div className="page-width"><h1>需要管理身份</h1></div>;
  async function read() {
    const signal = controller.current!.signal;
    setBusy(true); setMessage(''); setStatus(undefined); setConfirmed(false);
    const selected = course.trim(); setTarget(selected);
    try {const value = await api<Status>(`/api/tutor/activation-status?course_id=${encodeURIComponent(selected)}`, signal); if (!signal.aborted) setStatus(value);}
    catch (error) {if (!signal.aborted) setMessage((error as Error).message);}
    finally {if (!signal.aborted) setBusy(false);}
  }
  async function activate() {
    if (!status || !confirmed || busy) return;
    const signal = controller.current!.signal;
    setBusy(true); setMessage('正在自动核验来源与课程内容…');
    try {
      const response = await fetch(`/api/tutor/activate?course_id=${encodeURIComponent(target)}`, {method: 'POST', signal,
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({expected_version: status.course_version})});
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || '课程核验未完成。');
      const next = await api<Status>(`/api/tutor/activation-status?course_id=${encodeURIComponent(target)}`, signal);
      if (!signal.aborted) {setStatus(next); setMessage(`课程 v${value.version} 已自动生效。仍需正式教学质量评测，不等于内容绝无错误。`); setConfirmed(false);}
    } catch (error) {if (!signal.aborted) setMessage(`${(error as Error).message} 请重新读取状态后决定下一步；离开页面不会取消已经发出的模型调用。`);}
    finally {if (!signal.aborted) setBusy(false);}
  }
  return <div className="page-width"><h1>课程自动核验</h1><p>检查来源和课程内容后自动生效，不要求逐次人工审核学生教学。缺少来源或存在不确定项时保留原可用版本。</p>
    <form onSubmit={e => {e.preventDefault(); void read();}}><label className="identity-field">课程编号<input value={course} disabled={busy} onChange={e => {setCourse(e.target.value); setStatus(undefined);}} placeholder="留空使用默认课程"/></label><button disabled={busy}>读取课程核验状态</button></form>
    {status && <section><h2>{status.course_title}</h2><p>当前草稿 v{status.course_version}；可用版本：{status.published_version ? `v${status.published_version}` : '暂无'}。</p>
      <p>{labels[status.status] || status.status} · 已尝试 {status.attempts} 次</p>
      <p>核验结果保存与课程生效是两个步骤。失败后重新读取状态，不自动反复调用。</p>
      <label className="identity-field"><input type="checkbox" disabled={busy} checked={confirmed} onChange={e => setConfirmed(e.target.checked)}/>我确认本次核验可能调用配置的模型，来源内容允许传输</label>
      <button disabled={busy || !confirmed || status.status === 'running' || (status.status !== 'generated' && status.retry_remaining === 0)} onClick={activate}>自动核验并生效</button>
      <details><summary>任务与恢复信息</summary><p style={{overflowWrap: 'anywhere'}}>任务编号：{status.job_id}</p><p>核验耗尽次数时，先排查原因，再允许原任务重试。</p>
        <Link to={`/admin/job-recovery?${new URLSearchParams({course: target, student: status.job_owner, job: status.job_id})}`}>打开此任务的管理恢复</Link></details></section>}
    {message && <p role="status">{message}</p>}
    <p><a href="/manage/courses">返回已有课程资料管理</a></p>
  </div>;
}
