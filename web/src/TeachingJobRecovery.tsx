import {useRef, useState} from 'react';
import {api} from './api';
import {useAccessSession} from './Identity';
import {useSearchParams} from 'react-router-dom';

type Job = {request_id: string; status: string; attempts: number; retry_limit: number; retry_remaining: number};
export function JobRecovery() {
  const access = useAccessSession();
  const [search] = useSearchParams();
  const [course, setCourse] = useState(search.get('course') || '');
  const [student, setStudent] = useState(search.get('student') || '');
  const [ident, setIdent] = useState(search.get('job') || '');
  const [reason, setReason] = useState('');
  const [job, setJob] = useState<Job>();
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const target = useRef<{course: string; student: string; ident: string} | undefined>(undefined);
  const pending = useRef<{signature: string; id: string} | undefined>(undefined);
  if (!access.protected || access.identity?.role !== 'admin') return <div className="page-width"><h1>需要管理身份</h1></div>;
  async function read() {
    setBusy(true); setMessage(''); setJob(undefined);
    const value = {course: course.trim(), student: student.trim(), ident: ident.trim()}; target.current = value;
    try {setJob(await api<Job>(`/api/tutor/jobs/${encodeURIComponent(value.ident)}?${new URLSearchParams({course_id: value.course, student_id: value.student})}`));}
    catch (error) {setMessage((error as Error).message);}
    finally {setBusy(false);}
  }
  async function recover() {
    if (!job || !target.current || busy) return;
    const values = {student_id: target.current.student, job_id: target.current.ident, expected_attempts: job.attempts, expected_limit: job.retry_limit, reason: reason.trim()};
    const signature = JSON.stringify([target.current.course, values]);
    if (pending.current?.signature !== signature) pending.current = {signature, id: crypto.randomUUID()};
    setBusy(true); setMessage('');
    try {
      const response = await fetch(`/api/tutor/job-recovery?course_id=${encodeURIComponent(target.current.course)}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...values, request_id: pending.current.id})});
      const value = await response.json();
      if (!response.ok) throw new Error(value.detail || '恢复未完成。');
      setJob(value); setMessage('已增加三次显式重试额度，没有自动调用模型。请学生恢复原请求。');
    } catch (error) {setMessage((error as Error).message);}
    finally {setBusy(false);}
  }
  return <div className="page-width"><h1>教学生成任务恢复</h1><p>先检查模型配置及失败原因，再恢复已用完次数的任务。不会删除历史尝试，也不会自动发起付费调用。</p>
    <form onSubmit={e => {e.preventDefault(); void read();}}><fieldset disabled={busy}>
      <label className="identity-field">课程编号<input placeholder="留空使用默认课程" value={course} onChange={e => {setCourse(e.target.value); setJob(undefined);}}/></label>
      <label className="identity-field">学习者匿名编号<input required value={student} onChange={e => {setStudent(e.target.value); setJob(undefined);}}/></label>
      <label className="identity-field">任务请求编号<input required value={ident} onChange={e => {setIdent(e.target.value); setJob(undefined);}}/></label>
      <button type="submit">读取任务状态</button></fieldset></form>
    {job && <section><p>状态：{job.status}；已尝试 {job.attempts} 次，当前上限 {job.retry_limit} 次。</p>
      <label className="identity-field">检查结果与恢复原因<textarea maxLength={500} value={reason} onChange={e => setReason(e.target.value)}/></label>
      <button disabled={busy || !reason.trim() || job.retry_remaining > 0 || job.retry_limit >= 12 || !['failed', 'interrupted'].includes(job.status)} onClick={recover}>允许原任务再重试三次</button>
      <p>恢复后仍校验原学习上下文；上下文已变应由学生重新安排学习。累计十二次后不再扩充。</p></section>}
    {message && <p role="status">{message}</p>}
  </div>;
}
