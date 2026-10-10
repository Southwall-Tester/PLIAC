import {useEffect, useState} from 'react';
import {Link} from 'react-router-dom';
import {api, localLearner} from './api';

type Reminder = {course_id: string; course_title: string; node_id: string; title: string; kind: string; reason: string; due_at?: string};
const labels: Record<string, string> = {needs_work: '需要补学', version_changed: '内容更新待核验', review_due: '到期复习', needs_check: '证据待核验'};

export function ReviewReminders() {
  const [items, setItems] = useState<Reminder[]>();
  const [error, setError] = useState('');
  const [attempt, retry] = useState(0);
  const [all, setAll] = useState(false);
  useEffect(() => {
    const controller = new AbortController(); setError('');
    api<{items: Reminder[]}>(`/api/learning/review-reminders?${new URLSearchParams({student_id: localLearner()})}`, controller.signal)
      .then(value => {if (!controller.signal.aborted) setItems(value.items);})
      .catch(failure => {if (!controller.signal.aborted) setError(failure.message);});
    return () => controller.abort();
  }, [attempt]);
  return <section aria-label="复习与核验提醒"><div className="section-heading"><h2>复习与核验</h2><button onClick={() => retry(n => n + 1)}>刷新提醒</button></div>
    <p>依据已保存的学习证据与课程状态整理。到期不代表已经遗忘，打开知识点也不会自动判定掌握。</p>
    {error && <p role="alert">提醒读取失败：{error}</p>}
    {!items && !error && <p role="status">正在读取复习安排…</p>}
    {items?.length === 0 && <p>目前没有待处理提醒。这不代表所有课程都已掌握。</p>}
    <ol>{(all ? items : items?.slice(0, 5))?.map(item => <li key={`${item.course_id}:${item.node_id}`}>
      <Link className="material-link" to={`/courses/${encodeURIComponent(item.course_id)}?${new URLSearchParams({node: item.node_id})}`}>
        {item.course_title} · {item.title} · {labels[item.kind] || '待核验'}
      </Link><p>{item.reason}{item.due_at && `（复习时间：${new Date(item.due_at).toLocaleString('zh-CN')}）`}</p>
    </li>)}</ol>
    {!!items && items.length > 5 && <button onClick={() => setAll(value => !value)}>{all ? '收起提醒' : `查看全部 ${items.length} 项提醒`}</button>}
  </section>;
}
