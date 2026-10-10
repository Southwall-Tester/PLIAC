import {useEffect, useMemo, useState} from 'react';
import {ExternalLink, X} from 'lucide-react';
import {api, type Workspace} from './api';
import {RichText} from './RichText';
import {GraphCanvas, type GEdge, type GNode} from './GraphCanvas';

// 讲义：迁移自 LearnMargin 讲义阅读器（/margin-reader）。读取课程已生成的讲义（/api/handouts），
// 在新工作台内呈现正文、算例、自检题与原文出处；批注、讲义练习等高级功能仍可在原阅读器中使用。
type Job = {id: string; chapter_id: string; status: string; title: string; page_count?: number};
type Listing = {jobs: Job[]; scope_jobs?: Job[]};
type Section = {id: string; title: string; explanation?: string; worked_example?: string; source_refs?: string[];
  practice?: {id: string; prompt: string; hint?: string; answer?: string}[];
  study_prompts?: {id: string; when?: string; task: string}[]};
type Lesson = {title: string; subtitle?: string; overview?: {summary?: string}; sections: Section[]; review_plan?: string[];
  sources?: {ref: string; document: string; label: string}[]; scope_note?: string};
type Source = {document: string; label: string; text: string};
type KMap = {nodes: {id: string; title: string; definition?: string; quote?: string; family_index?: number; section_ids?: string[]; source_refs?: string[]}[];
  edges: {source: string; target: string; predicate?: string; directed?: boolean; relation_type?: string}[]; notice?: string};

/** 讲义知识图：讲义生成时抽取的概念与关系（knowledge-map.json），渲染引擎为原 NetworkView。
 *  沿用原讲义阅读器的做法：大图按章节投影（只看一章的概念及其相互关系）+ 可搜索概念列表；
 *  概念与课程知识框架按名称精确对齐（同名的课程概念或小节），可直接去学对应小节。 */
function HandoutMap({map, jobId, lesson, openSource, label, state, chapter, openLesson}: {map: KMap; jobId: string; lesson?: Lesson;
  openSource: (ref: string) => void; label: (ref: string) => string; state: Workspace; chapter?: string; openLesson?: (id: string) => void}) {
  const [pick, setPick] = useState('');
  const [query, setQuery] = useState('');
  const sections = useMemo(() => {
    const ids = new Set(map.nodes.flatMap(n => n.section_ids || []));
    return [...ids].map(id => ({id, title: lesson?.sections.find(s => s.id === id)?.title || id}));
  }, [jobId, lesson]);
  const big = map.nodes.length > 150;
  const [scope, setScope] = useState(() => big ? (sections.find(s => s.id === chapter)?.id || sections[0]?.id || '') : '');
  useEffect(() => {setPick(''); setScope(big ? (sections.find(s => s.id === chapter)?.id || sections[0]?.id || '') : '');}, [jobId]);
  const inScope = useMemo(() => new Set(map.nodes.filter(n => !scope || n.section_ids?.includes(scope)).map(n => n.id)), [jobId, scope]);
  const nodes: GNode[] = useMemo(() => map.nodes.filter(n => inScope.has(n.id)).map(n => ({id: n.id, title: n.title, group: n.family_index ?? 0, anchor: n.id === pick})), [inScope, pick]);
  const edges: GEdge[] = useMemo(() => map.edges.filter(e => inScope.has(e.source) && inScope.has(e.target)).map((e, i) => ({id: `e${i}`, source: e.source, target: e.target, label: e.predicate,
    kind: e.relation_type === 'cooccurs' ? 'cooccurs' : e.directed ? 'directed' : 'related'})), [inScope]);
  const n = map.nodes.find(x => x.id === pick);
  const section = (id: string) => lesson?.sections.find(x => x.id === id)?.title || id;
  const matches = query.trim() ? map.nodes.filter(x => x.title.toLowerCase().includes(query.trim().toLowerCase())).slice(0, 30) : [];
  // 与课程知识框架对齐：只认名称完全相同的课程概念或小节，不做模糊对应
  const norm = (t: string) => t.replace(/^\d+\s*/, '').trim().toLowerCase();
  const courseMatch = (title: string) => {
    const concept = state.concept_map?.nodes.find(c => norm(c.title) === norm(title));
    const lessonIds = concept?.lesson_ids || state.course?.nodes.filter(l => norm(l.title) === norm(title)).map(l => l.id) || [];
    return lessonIds.map(id => state.course?.nodes.find(l => l.id === id)).filter(Boolean) as {id: string; title: string}[];
  };
  const choose = (id: string) => {
    const target = map.nodes.find(x => x.id === id);
    if (target && scope && !target.section_ids?.includes(scope)) setScope('');
    setPick(id); setQuery('');
  };
  const linked = n ? courseMatch(n.title) : [];
  return <div className="handout-map">
    <div className="handout-map-tools">
      {sections.length > 1 && <select aria-label="按章节查看" value={scope} onChange={e => {setScope(e.target.value); setPick('');}}>
        <option value="">全部章节（{map.nodes.length} 个概念）</option>
        {sections.map(s => <option key={s.id} value={s.id}>{s.title}（{map.nodes.filter(x => x.section_ids?.includes(s.id)).length}）</option>)}
      </select>}
      <input type="search" aria-label="搜索概念" placeholder="搜索概念，例如 CPI、cache、流水线" value={query} onChange={e => setQuery(e.target.value)}/>
    </div>
    <div className="handout-map-grid">
      <GraphCanvas key={jobId + scope} nodes={nodes} edges={edges} focus={pick || undefined} onSelect={choose} height={540}/>
      <aside className="handout-map-side">
        {matches.length > 0 ? <div className="concept-card"><div className="concept-sub">找到 {matches.length} 个概念</div>
          <div className="chips">{matches.map(m => <button key={m.id} onClick={() => choose(m.id)}>{m.title}</button>)}</div></div>
        : n ? <div className="concept-card">
          <h3>{n.title}</h3>
          {n.definition?.trim() && <p>{n.definition.trim()}</p>}
          {n.quote?.trim() && n.quote.trim() !== n.definition?.trim() && <blockquote>{n.quote.trim()}</blockquote>}
          {!!n.section_ids?.length && <><div className="concept-sub">出现在</div><p>{n.section_ids.map(section).join('、')}</p></>}
          {!!n.source_refs?.length && <><div className="concept-sub">教材原文</div><div className="handout-refs">{n.source_refs.slice(0, 8).map(r => <button key={r} onClick={() => openSource(r)}>{label(r)}</button>)}</div></>}
          {linked.length > 0 && openLesson && <><div className="concept-sub">在课程中学习</div><div className="chips">{linked.map(l =>
            <button key={l.id} onClick={() => openLesson(l.id)}><i className={`dot ${state.learner.states[l.id]?.status || ''}`}/>{l.title}</button>)}</div></>}
        </div>
        : <p className="star-hint">{scope ? `本章 ${nodes.length} 个概念、${edges.length} 条关系。` : `共 ${map.nodes.length} 个概念、${map.edges.length} 条关系。`}点一颗星查看定义和教材原文；拖动、滚轮缩放，悬停看它连着谁。</p>}
      </aside>
    </div>
    {map.notice && <p className="handout-note">{map.notice}</p>}
  </div>;
}

export function Handouts({state, courseId, nodeId, openLesson}: {state: Workspace; courseId: string; nodeId: string; openLesson?: (id: string) => void}) {
  const [listing, setListing] = useState<Listing>();
  const [jobId, setJobId] = useState('');
  const [lesson, setLesson] = useState<Lesson>();
  const [error, setError] = useState('');
  const [source, setSource] = useState<Source | null>(null);
  const [mode, setMode] = useState<'text' | 'map'>('text');
  const [kmap, setKmap] = useState<KMap | null>();
  const chapter = state.course?.nodes.find(n => n.id === nodeId)?.chapter_id;
  const q = `course_id=${encodeURIComponent(courseId)}`;

  useEffect(() => {
    const c = new AbortController();
    api<Listing>(`/api/handouts?${q}`, c.signal).then(value => {
      setListing(value);
      const done = [...(value.jobs || []), ...(value.scope_jobs || [])].filter(j => j.status === 'completed');
      setJobId(done.find(j => j.chapter_id && (j.chapter_id === chapter || j.chapter_id === nodeId))?.id || done[0]?.id || '');
    }).catch(e => !c.signal.aborted && setError(e.message));
    return () => c.abort();
  }, [courseId]);
  useEffect(() => {
    if (!jobId) return;
    const c = new AbortController(); setLesson(undefined);
    api<Lesson>(`/api/handouts/${jobId}/artifacts/lesson.json?${q}`, c.signal).then(setLesson).catch(e => !c.signal.aborted && setError(e.message));
    setKmap(undefined);
    api<KMap>(`/api/handouts/${jobId}/artifacts/knowledge-map.json?${q}`, c.signal).then(setKmap).catch(() => !c.signal.aborted && setKmap(null));
    return () => c.abort();
  }, [jobId]);

  const openSource = (ref: string) => {
    const [doc, index] = ref.split(':');
    api<Source>(`/api/handouts/${jobId}/sources/${doc}/${index}?${q}`).then(setSource).catch(e => setError(e.message));
  };
  const label = (ref: string) => lesson?.sources?.find(s => s.ref === ref)?.label || ref.split(':')[1];
  const done = [...(listing?.jobs || []), ...(listing?.scope_jobs || [])].filter(j => j.status === 'completed');

  if (error) return <div className="empty"><h1>讲义暂时打不开</h1><p>{error}</p></div>;
  if (!listing) return <div className="notice" role="status">正在加载讲义…</div>;
  if (!done.length) return <div className="empty"><h1>这门课还没有讲义</h1><p>先在“学习”里看讲解，或在对话里提问。</p></div>;
  return <article className="handout">
    <div className="handout-bar">
      <select aria-label="选择讲义" value={jobId} onChange={e => setJobId(e.target.value)}>{done.map(j => <option key={j.id} value={j.id}>{j.title}</option>)}</select>
      {!!kmap?.nodes.length && <div className="seg handout-seg" role="tablist" aria-label="正文或知识图"><button role="tab" aria-selected={mode === 'text'} className={mode === 'text' ? 'on' : ''} onClick={() => setMode('text')}>正文</button><button role="tab" aria-selected={mode === 'map'} className={mode === 'map' ? 'on' : ''} onClick={() => setMode('map')}>知识图</button></div>}
      <a className="ghost" href={`/margin-reader?${q}&job_id=${encodeURIComponent(jobId)}`} target="_blank" rel="noopener noreferrer"><ExternalLink size={14}/>在阅读器中批注与练习</a>
    </div>
    {mode === 'map' && kmap ? <HandoutMap map={kmap} jobId={jobId} lesson={lesson} openSource={openSource} label={label} state={state} chapter={chapter} openLesson={openLesson}/>
    : !lesson ? <div className="notice" role="status">正在打开讲义…</div> : <>
      <h1>{lesson.title}</h1>
      {lesson.subtitle && <p className="handout-sub">{lesson.subtitle}</p>}
      {lesson.overview?.summary && <div className="lead"><RichText text={lesson.overview.summary}/></div>}
      {lesson.sections.map(s => <section key={s.id} className="handout-section">
        <h2>{s.title}</h2>
        {s.explanation && <RichText text={s.explanation}/>}
        {s.worked_example && <div className="handout-example"><RichText text={s.worked_example}/></div>}
        {!!s.practice?.length && <div className="handout-practice"><h3>自检</h3>{s.practice.map(p => <details key={p.id}>
          <summary><RichText text={p.prompt}/></summary>
          {p.hint && <p className="hint">提示：{p.hint}</p>}{p.answer && <div className="answer"><RichText text={p.answer}/></div>}</details>)}</div>}
        {!!s.source_refs?.length && <p className="handout-refs">原文：{s.source_refs.map(r => <button key={r} onClick={() => openSource(r)}>{label(r)}</button>)}</p>}
      </section>)}
      {!!lesson.review_plan?.length && <section className="handout-section"><h2>复习安排</h2><ol>{lesson.review_plan.map((r, i) => <li key={i}>{r}</li>)}</ol></section>}
      {lesson.scope_note && <p className="handout-note">{lesson.scope_note}</p>}
    </>}
    {source && <div className="source-overlay" onClick={() => setSource(null)}><div className="source-preview" role="dialog" aria-label="原文" onClick={e => e.stopPropagation()}>
      <header><h2>{source.document} · {source.label}</h2><button aria-label="关闭原文" onClick={() => setSource(null)}><X size={18}/></button></header>
      <div className="source-text">{source.text}</div></div></div>}
  </article>;
}
