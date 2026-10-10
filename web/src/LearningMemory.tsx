import {Link} from 'react-router-dom';
import {type LearningMemory as Memory} from './api';

export function LearningMemory({memory}: {memory?: Memory}) {
  if (!memory) return null;
  const label: Record<string, string> = {mastered: '已有证据支持掌握', needs_review: '需要复习或补学', uncertain: '仍需核验', unknown: '尚未核验'};
  return <section className="assessment-panel" aria-label="学习记忆"><details><summary>学习记忆 · {label[memory.status] || memory.status}</summary>
    <p>{memory.reason}</p><p>保存了 {memory.evidence_count} 条过程证据、{memory.diagnosis_count} 次诊断，其中 {memory.assisted_evidence_count} 条证据记录了帮助使用。</p>
    <p className="quiet-note"></p>
    {memory.version_changed && <p>知识版本已变化，历史判断需要重新核验。</p>}
    {memory.due_at && <p>复习时间：{new Date(memory.due_at).toLocaleString('zh-CN')}</p>}
    {!!memory.pending_assessments.length && <p>仍有 {memory.pending_assessments.length} 项已列出的未完成或待评价任务。</p>}
    {!!memory.recent_feedback.length && <><h3>最近评价记录</h3><ol>{memory.recent_feedback.map(item => <li key={item.diagnosis_id}><p>课程 v{item.course_version}：{item.text}</p>{item.applicable === false && <p className="quiet-note">课程内容已更新，这条是旧版本的记录。</p>}{item.resolved && <small>这条历史问题已由后续独立核验覆盖，保留记录供回看。</small>}</li>)}</ol></>}
    {!!memory.material_ids.length && <><h3>回看近期教学材料</h3><ol>{memory.material_ids.map((id, index) => <li key={id}><Link className="material-link" to={`?material=${encodeURIComponent(id)}`}>打开保存材料 {index + 1}</Link></li>)}</ol></>}
  </details></section>;
}
