import {useEffect, useState} from 'react';
import {Link} from 'react-router-dom';
import {ArrowRight} from 'lucide-react';
import {api, learnerKey, localLearner} from './api';

type Entry = {course_id: string; course_title: string; material_id?: string; resource_id?: string; node_id?: string; session_id?: string; restart_required?: boolean; kind?: 'video' | 'document' | 'lab'; title: string; updated_at: number};

export function ContinueLearning() {
  const [items, setItems] = useState<Entry[]>();
  const [error, setError] = useState('');
  const [attempt, retry] = useState(0);
  const localCourse = localStorage.getItem(learnerKey('recent-course'));
  useEffect(() => {
    const controller = new AbortController(); setError('');
    api<{items: Entry[]}>(`/api/learning/continue?${new URLSearchParams({student_id: localLearner()})}`, controller.signal)
      .then(value => {if (!controller.signal.aborted) setItems(value.items);})
      .catch(failure => {if (!controller.signal.aborted) setError(failure.message);});
    return () => controller.abort();
  }, [attempt]);
  return <section aria-label="继续学习">
    {error && <p role="alert">续读记录读取失败：{error}<button onClick={() => retry(n => n + 1)}>重试读取续读记录</button></p>}
    {!items && !error && <p role="status">正在查找保存的续读点…</p>}
    {items?.map(item => <Link className="continue" key={`${item.course_id}:${item.kind || 'material'}:${item.material_id || item.resource_id || item.session_id}`}
      to={`/courses/${encodeURIComponent(item.course_id)}?${new URLSearchParams(item.kind === 'lab' ? {lab: '1'} : item.resource_id ? {node: item.node_id || '', resource: item.resource_id} : {material: item.material_id || ''})}`}>
      <div><small>{item.course_title} · 服务器续读点</small><h2>{item.title}</h2>
        <p>{item.updated_at ? new Date(item.updated_at * 1000).toLocaleString() : '历史保存位置'} · {item.kind === 'lab' ? (item.restart_required ? '实验版本已变化，打开后可保留旧记录并开始新版' : '继续未完成的实验，恢复已保存步骤与参数') : item.kind === 'video' ? '打开材料后可恢复视频位置，不自动播放' : item.kind === 'document' ? '打开 PDF 后恢复保存页码' : '打开后可回到续读段落'}</p></div><ArrowRight/>
    </Link>)}
    {!items?.length && localCourse && <Link className="continue" to={`/courses/${encodeURIComponent(localCourse)}`}>
      <div><small>此浏览器最近访问</small><h2>回到最近的课程</h2><p>读取课程状态；不是服务器保存的教材续读点。</p></div><ArrowRight/>
    </Link>}
    {items?.length === 0 && !localCourse && <p>还没有保存的续读点。选择课程后，可保存教材、PDF 或视频位置；未完成的实验也会在这里显示。</p>}
  </section>;
}
