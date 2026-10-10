import {useState} from 'react';
import {useAccessSession} from './Identity';
import {MediaReview} from './MediaReview';

export function MediaAdmin() {
  const access = useAccessSession();
  const [course, setCourse] = useState('');
  const [student, setStudent] = useState('');
  const [target, setTarget] = useState<{course: string; student: string}>();
  if (!access.protected || access.identity?.role !== 'admin') return <div className="page-width"><h1>需要授权管理身份</h1><p>此页面不是学生教学流程的一部分。</p></div>;
  return <div className="page-width"><h1>学习活动媒体回看</h1>
    <p>仅供核查已授权学习活动，不用于比赛展示、心理诊断或直接判定掌握。访问请求会记录管理身份、目标和时间。</p>
    <form onSubmit={e => {e.preventDefault(); setTarget({course: course.trim(), student: student.trim()});}}>
      <label className="identity-field">课程编号<input value={course} onChange={e => setCourse(e.target.value)} required maxLength={100}/></label>
      <label className="identity-field">学习者匿名编号<input value={student} onChange={e => setStudent(e.target.value)} required maxLength={100}/></label>
      <button type="submit">查询授权记录</button>
    </form>
    {target && <MediaReview key={`${target.course}:${target.student}`} courseId={target.course} studentId={target.student} revision="admin"/>}
  </div>;
}
