import {useEffect, useRef, useState} from 'react';
import {Link, useSearchParams} from 'react-router-dom';
import {api, localLearner} from './api';

interface Item {
  kind: string; id: string; node_id: string; node_title: string; title: string;
  course_version: number; created_at: string; text?: string; revision?: number;
  status?: string; answer?: string; result?: {feedback: string; status: string};
  lab?: {contract_version: number; step: number; completed: boolean; test_accuracy: number | null;
    runs: {number: number; config: {train_percent: number; depth: number; features: string; split: string}; train_accuracy: number; validation_accuracy: number}[];
    checks: {task_id: string; passed: boolean; note?: string; feedback: string; prompt_level?: number}[]};
}
interface Archive {courses: {id: string; title: string; items: Item[]}[]}
const kinds: Record<string, string> = {material: '个人教材与教学安排', lesson: '已保存小节', note: '学习笔记', assessment: '核验记录', report: '阶段报告', lab: '实验记录'};

export function LearningArchive() {
  const [data, setData] = useState<Archive>();
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const results = useRef<HTMLParagraphElement>(null);
  const [search, setSearch] = useSearchParams();
  const kind = search.get('kind') || 'all';
  const selectedCourse = search.get('course') || 'all';
  const text = search.get('q') || '';
  const requestedPage = Number(search.get('page') || 1);
  function filter(key: string, value: string) {
    const next = new URLSearchParams(search);
    if (!value || value === 'all') next.delete(key); else next.set(key, value);
    next.delete('page'); setSearch(next, {replace: true});
  }
  useEffect(() => {
    const controller = new AbortController(); setError('');
    api<Archive>(`/api/tutor/archive?student_id=${localLearner()}`, controller.signal).then(setData)
      .catch(failure => {if (!controller.signal.aborted) setError(failure.message);});
    return () => controller.abort();
  }, [retry]);
  const matched = (data?.courses || []).flatMap(course => course.items.map(item => ({course, item})))
    .filter(({course, item}) => (selectedCourse === 'all' || selectedCourse === course.id) && (kind === 'all' || kind === item.kind)
      && (!text.trim() || [course.title, item.title, item.node_title, item.text || ''].join('\n').toLocaleLowerCase().includes(text.trim().toLocaleLowerCase())))
    .sort((a, b) => b.item.created_at.localeCompare(a.item.created_at) || a.course.id.localeCompare(b.course.id) || a.item.id.localeCompare(b.item.id));
  const pageCount = Math.max(1, Math.ceil(matched.length / 20));
  const page = Math.min(pageCount, Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1);
  const visible = matched.slice((page - 1) * 20, page * 20);
  function paginate(value: number) {
    const next = new URLSearchParams(search); next.set('page', String(value)); setSearch(next);
    results.current?.scrollIntoView({block: 'start'}); results.current?.focus({preventScroll: true});
  }
  return <div className="page-width"><h1>学习档案</h1>
    <p className="lead">你的教材、笔记和学习总结都在这里。</p>
    <label>查看内容 <select value={kind} onChange={event => filter('kind', event.target.value)}><option value="all">全部</option>
      {Object.entries(kinds).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label>
    <label className="identity-field">筛选课程<select value={selectedCourse} onChange={event => filter('course', event.target.value)}><option value="all">全部课程</option>{data?.courses.map(course => <option key={course.id} value={course.id}>{course.title}</option>)}</select></label>
    <label className="identity-field">搜索档案<input type="search" value={text} onChange={event => filter('q', event.target.value)} placeholder="课程、标题、知识点或笔记文字"/></label>
    {error ? <p role="alert">{error}<button onClick={() => setRetry(value => value + 1)}>重试</button></p> : !data ? <p role="status">正在读取档案…</p> : !data.courses.length ?
      <div className="empty"><h2>还没有保存的学习成果</h2><Link to="/courses">选择课程</Link></div> : <>
      <p role="status" ref={results} tabIndex={-1}>找到 {matched.length} 条记录 · 第 {page} / {pageCount} 页</p>
      {!matched.length && <p>没有符合条件的记录。<button onClick={() => setSearch({})}>清除筛选</button></p>}
      {data.courses.filter(course => visible.some(entry => entry.course.id === course.id)).map(course => {
        const items = visible.filter(entry => entry.course.id === course.id).map(entry => entry.item);
        return <section className="archive-course" key={course.id}><h2>{course.title}</h2>{!items.length ? <p>本课程暂无此类记录。</p> : items.map(item => {
          const query = new URLSearchParams({node: item.node_id});
          if (item.kind === 'material' || item.kind === 'lesson' || item.kind === 'report') query.set(item.kind, item.id);
          if (item.kind === 'lab') {query.delete('node'); query.set('lab', '1');}
          return <article className="archive-entry" key={item.kind + item.id}>
            <small>{kinds[item.kind]} · 课程 v{item.course_version} · {new Date(item.created_at).toLocaleString('zh-CN')}</small>
            <h3>{item.title}</h3>{item.kind !== 'report' && item.kind !== 'lab' && <p>{item.node_title}</p>}
            {item.lab && <details><summary>查看本轮实验记录</summary>
              <p>实验规则 v{item.lab.contract_version} · 已完成 {item.lab.step} 步 · {item.lab.completed ? '本轮已封存' : '本轮未完成'}。技术成果不等于概念掌握。</p>
              <div style={{overflowX: 'auto'}}><table><caption>当时保存的训练与验证结果</caption><thead><tr><th>次数</th><th>参数</th><th>训练准确率</th><th>验证准确率</th></tr></thead>
                <tbody>{item.lab.runs.map(run => <tr key={run.number}><td>{run.number}</td><td>训练 {run.config.train_percent}%；深度 {run.config.depth || '自由'}；特征 {run.config.features}；划分 {run.config.split}</td><td>{(run.train_accuracy * 100).toFixed(1)}%</td><td>{(run.validation_accuracy * 100).toFixed(1)}%</td></tr>)}</tbody></table></div>
              {!item.lab.runs.length && <p>本轮暂无训练记录。</p>}
              <ol>{item.lab.checks.map((check, index) => <li key={index}>步骤 {check.task_id}：{check.passed ? '成果检查通过' : '成果检查未通过'}；记录受助等级 {check.prompt_level ?? '未知'}。<p>{check.note || '未附解释文字'}</p><p>{check.feedback}</p></li>)}</ol>
              <p>{item.lab.test_accuracy === null ? '本轮未封存测试结果。' : `封存方案测试准确率 ${(item.lab.test_accuracy * 100).toFixed(1)}%。`}</p>
              <p>这里展示原轮次，不重跑模型，也不把旧结果改成当前版本结论。</p>
            </details>}
            {item.kind === 'note' && <details><summary>查看第 {item.revision} 版笔记</summary><p style={{whiteSpace: 'pre-wrap'}}>{item.text || '当前笔记为空；历史版本可在工作台查看。'}</p></details>}
            {item.kind === 'assessment' && <details><summary>{item.status === 'assessed' ? '查看当时的作答与反馈' : item.status === 'submitted' ? '作答已保存，评价待完成' : '尚未提交作答'}</summary>
              <p>{item.answer || '暂无作答'}</p><p>{item.result?.feedback || '尚未形成评价。'}</p></details>}
            <Link className="material-link" to={`/courses/${encodeURIComponent(course.id)}?${query}`}>{item.kind === 'lab' ? '打开当前实验（不切换历史轮次）' : item.kind === 'material' || item.kind === 'lesson' || item.kind === 'report' ? '打开保存的内容' : '回到该知识点'}</Link>
          </article>;
        })}</section>;
      })}
      {pageCount > 1 && <nav aria-label="档案分页"><button disabled={page === 1} onClick={() => paginate(page - 1)}>上一页档案</button><span> 第 {page} / {pageCount} 页 </span><button disabled={page === pageCount} onClick={() => paginate(page + 1)}>下一页档案</button></nav>}
      </>}
  </div>;
}
