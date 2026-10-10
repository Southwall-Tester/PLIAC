import {useEffect, useMemo, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {Maximize2, X} from 'lucide-react';
import type {Workspace} from './api';
import {layout, neighborhood} from './graphLayout';

// 星图：课程知识图谱的学生视图。夜空为底；有证据支持掌握的点像萤火一样亮起。
// 有概念图谱（concept_map，旧 /learn 页面使用的数据）时画概念层：概念按分组成星团，点击查看解释、相关小节、关系与来源；
// 否则画小节层（course.nodes / course.edges）。
// 概念本身不推断掌握：概念星的颜色只表示“它所在小节”的学习状态（见 AGENTS.md）。
type G = {
  key: string; concepts: boolean;
  nodes: {id: string; title: string; group?: string}[];
  edges: {id: string; source: string; target: string; kind: string; label?: string}[];
  status: (id: string) => string;
  focus: Set<string>;
};

const groupTint = ['#85b7eb', '#b9a7f0', '#7fd1b9', '#f2b880', '#e6a3c4'];
const edgeStyle: Record<string, {dash?: string; color: string; opacity: number; arrow?: boolean}> = {
  prerequisite: {color: '#85b7eb', opacity: .55, arrow: true},
  directed: {color: '#85b7eb', opacity: .45, arrow: true},
  related: {color: '#85b7eb', opacity: .35, dash: '4 4'},
  confusable: {color: '#ef8a73', opacity: .55, dash: '1.5 4'},
  contains: {color: '#85b7eb', opacity: .18},
};
const labelsFor = (concepts: boolean): Record<string, string> => concepts
  ? {mastered: '所在小节已掌握', uncertain: '所在小节待核验', needs_review: '所在小节需补学'}
  : {mastered: '已掌握', uncertain: '待核验', needs_review: '需补学'};

export function buildGraph(state: Workspace, selected?: string): G {
  const course = state.course!, cm = state.concept_map;
  const lessonStatus = (id: string) => state.learner.states[id]?.status || '';
  if (cm?.nodes.length) {
    const groups = cm.groups.map(g => g.id);
    const status = (id: string) => {
      const ls = cm.nodes.find(n => n.id === id)?.lesson_ids.map(lessonStatus) || [];
      if (!ls.length) return '';
      if (ls.some(s => s === 'needs_review')) return 'needs_review';
      if (ls.every(s => s === 'mastered')) return 'mastered';
      if (ls.some(s => s === 'uncertain' || s === 'mastered')) return 'uncertain';
      return '';
    };
    return {key: `c:${course.id}@${course.version}`, concepts: true, status,
      nodes: cm.nodes.map(n => ({id: n.id, title: n.title, group: String(groups.indexOf(n.group_id))})),
      edges: cm.edges.map(e => ({id: e.id, source: e.source, target: e.target, kind: e.directed ? 'directed' : 'related', label: e.predicate})),
      focus: new Set(cm.nodes.filter(n => selected && n.lesson_ids.includes(selected)).map(n => n.id))};
  }
  return {key: `l:${course.id}@${course.version}`, concepts: false, status: lessonStatus,
    nodes: course.nodes.map(n => ({id: n.id, title: n.title})),
    edges: (course.edges || []).map(e => ({id: e.id, source: e.source, target: e.target, kind: e.type})),
    focus: new Set(selected ? [selected] : [])};
}

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return {ref, width};
}

const cache = new Map<string, Map<string, {x: number; y: number}>>();
function positionsFor(g: G) {
  if (!cache.has(g.key)) {
    // 同组概念加弱连接，让分组自然聚成星团（仅影响布局，不画出来）
    const extra: [string, string][] = [];
    const byGroup = new Map<string, string[]>();
    for (const n of g.nodes) if (n.group) byGroup.set(n.group, [...(byGroup.get(n.group) || []), n.id]);
    for (const ids of byGroup.values()) for (let i = 1; i < ids.length; i++) extra.push([ids[0], ids[i]]);
    cache.set(g.key, layout(g.nodes.map(n => n.id), [...g.edges.map(e => [e.source, e.target] as [string, string]), ...extra]));
  }
  return cache.get(g.key)!;
}

function backgroundStars(count: number) {
  let seed = 7;
  const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  return Array.from({length: count}, () => ({x: rand() * 1600, y: rand() * 1000, r: rand() < .15 ? 1.1 : .6, o: .25 + rand() * .45}));
}

export function StarMap({graph, active, onPick, full = false, height = 340, labels = true}: {
  graph: G; active?: string; onPick: (id: string) => void; full?: boolean; height?: number; labels?: boolean;
}) {
  const {ref, width} = useWidth();
  const pos = useMemo(() => positionsFor(graph), [graph.key]);
  const anchors = active ? [active] : [...graph.focus];
  const hops = graph.concepts ? 1 : 2;
  const visible = useMemo(() => {
    if (full || !anchors.length) return new Set(graph.nodes.map(n => n.id));
    const out = new Set<string>();
    for (const a of anchors) for (const id of neighborhood(a, graph.edges, hops)) out.add(id);
    return out;
  }, [full, graph.key, anchors.join()]);
  const [hover, setHover] = useState('');
  const stateLabel = labelsFor(graph.concepts);

  const padX = !labels ? 24 : full ? 110 : 60, padY = !labels ? 22 : full ? 60 : 40;
  const pts = [...visible].map(id => pos.get(id)).filter(Boolean) as {x: number; y: number}[];
  const minX = Math.min(...pts.map(p => p.x)), maxX = Math.max(...pts.map(p => p.x));
  const minY = Math.min(...pts.map(p => p.y)), maxY = Math.max(...pts.map(p => p.y));
  const w = Math.max(width, 1), h = height;
  const scale = Math.min((w - padX * 2) / Math.max(maxX - minX, 1), (h - padY * 2) / Math.max(maxY - minY, 1), full ? 3 : 2);
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const at = (id: string) => {const p = pos.get(id) || {x: 0, y: 0}; return {x: w / 2 + (p.x - cx) * scale, y: h / 2 + (p.y - cy) * scale};};
  const stars = useMemo(() => backgroundStars(full ? 160 : 60), [full]);
  const short = (t: string) => {if (full) return t; const x = t.replace(/^\d+\s*/, ''); return x.length > 8 ? x.slice(0, 7) + '…' : x;};
  const focusId = hover || active;

  return <div className="starmap" ref={ref} style={{height}}>
    {width > 0 && <svg width={w} height={h} role="img" aria-label={full ? '课程全景星图' : '当前学习附近的星图'}>
      <defs><marker id="sm-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 1 L9 5 L0 9 z" fill="#85b7eb" opacity=".7"/></marker></defs>
      {stars.map((s, i) => <circle key={i} cx={s.x % w} cy={s.y % h} r={s.r} fill="#cfe0ff" opacity={s.o * .6}/>)}
      {graph.edges.map(e => {
        const on = visible.has(e.source) && visible.has(e.target);
        const st = edgeStyle[e.kind] || edgeStyle.related;
        const a = at(e.source), b = at(e.target);
        const d = Math.hypot(b.x - a.x, b.y - a.y) || 1, shrink = 9;
        const bx = b.x - (b.x - a.x) / d * shrink, by = b.y - (b.y - a.y) / d * shrink;
        const lit = !!focusId && (e.source === focusId || e.target === focusId);
        return <g key={e.id}>
          <line x1={a.x} y1={a.y} x2={bx} y2={by} stroke={st.color} strokeWidth={lit ? 1.6 : 1}
            strokeDasharray={st.dash} opacity={on ? (lit ? .95 : st.opacity) : .06} markerEnd={on && st.arrow ? 'url(#sm-arrow)' : undefined}/>
          {lit && on && e.label && labels && <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 4} textAnchor="middle" fontSize={10.5} fill="#9fb4d8"
            style={{paintOrder: 'stroke', stroke: '#0e1a33', strokeWidth: 3}}>{e.label}</text>}
        </g>;
      })}
      {graph.nodes.map(n => {
        const p = at(n.id), on = visible.has(n.id), s = graph.status(n.id);
        const ring = active ? n.id === active : graph.focus.has(n.id);
        if (!on) return <circle key={n.id} cx={p.x} cy={p.y} r={2} fill="#cfe0ff" opacity=".22"/>;
        const fill = s === 'mastered' ? '#ffc35c' : s === 'uncertain' ? '#85b7eb' : s === 'needs_review' ? '#ef8a73' : '#a9bbdb';
        const tint = n.group !== undefined ? groupTint[Number(n.group) % groupTint.length] : '#c9d6ee';
        return <g key={n.id} className="star" transform={`translate(${p.x},${p.y})`} onClick={() => onPick(n.id)}
          onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover('')} style={{cursor: 'pointer'}}>
          <title>{n.title}{stateLabel[s] ? ` · ${stateLabel[s]}` : ''}</title>
          {s === 'mastered' && <circle className="firefly" r={14} fill="#ffc35c" opacity=".22"/>}
          {s === 'uncertain' && <circle r={9} fill="#85b7eb" opacity=".18"/>}
          {ring && <circle r={11} fill="none" stroke="#ffffff" strokeWidth={1.4} opacity=".9"/>}
          <circle r={s === 'mastered' ? 6 : s ? 5.5 : 4} fill={fill} opacity={s ? 1 : .8}/>
          {labels && <text y={-12} textAnchor="middle" fontSize={ring ? 12.5 : 11.5} fontWeight={ring ? 600 : 400}
            fill={s === 'mastered' ? '#ffe3ad' : ring ? '#ffffff' : tint} style={{paintOrder: 'stroke', stroke: '#0e1a33', strokeWidth: 3}}>{short(n.title)}</text>}
        </g>;
      })}
    </svg>}
  </div>;
}

export function StarLegend({state}: {state?: Workspace}) {
  const groups = state?.concept_map?.groups || [];
  const concepts = groups.length > 0;
  const l = labelsFor(concepts);
  return <div className="star-legend">
    <span><i style={{background: '#ffc35c', boxShadow: '0 0 6px #ffc35c'}}/>{l.mastered}</span>
    <span><i style={{background: '#85b7eb'}}/>{l.uncertain}</span>
    <span><i style={{background: '#ef8a73'}}/>{l.needs_review}</span>
    <span><i style={{background: '#a9bbdb', opacity: .8}}/>未学</span>
    {groups.map((g, i) => <span key={g.id} style={{color: groupTint[i % groupTint.length]}}>{g.title}</span>)}
  </div>;
}

/** 概念卡片：解释、相关小节、关系、来源（对应旧 /learn 页面右侧面板）。 */
function ConceptCard({state, id, openLesson, pick}: {state: Workspace; id: string; openLesson: (lesson: string) => void; pick: (id: string) => void}) {
  const cm = state.concept_map!, n = cm.nodes.find(x => x.id === id);
  if (!n) return null;
  const name = (cid: string) => cm.nodes.find(x => x.id === cid)?.title || cid;
  const lesson = (lid: string) => state.course?.nodes.find(x => x.id === lid);
  const rel = cm.edges.filter(e => e.source === id || e.target === id);
  const srcs = n.source_ids.map(s => cm.sources.find(x => x.id === s)).filter(Boolean) as {id: string; title: string; url?: string}[];
  return <div className="concept-card">
    <small>{cm.groups.find(g => g.id === n.group_id)?.title}</small>
    <h3>{n.title}</h3>
    <p>{n.description}</p>
    {n.lesson_ids.length > 0 && <><div className="concept-sub">在这些小节学</div><div className="concept-lessons">{n.lesson_ids.map(l => lesson(l) && <button key={l} onClick={() => openLesson(l)}>
      <i className={`dot ${state.learner.states[l]?.status || ''}`}/>{lesson(l)!.title}</button>)}</div></>}
    {rel.length > 0 && <><div className="concept-sub">关系</div><ul className="concept-rel">{rel.map(e => <li key={e.id} title={e.reason}>
      <button onClick={() => pick(e.source)}>{name(e.source)}</button><span>{e.predicate}</span><button onClick={() => pick(e.target)}>{name(e.target)}</button></li>)}</ul></>}
    {srcs.length > 0 && <div className="concept-src">来源：{srcs.map(s => s.url ? <a key={s.id} href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a> : <span key={s.id}>{s.title}</span>)}</div>}
  </div>;
}

/** 左栏里的星图 + 概念卡片 + 全景星图。 */
export function StarPanel({state, selected, onSelect}: {state: Workspace; selected?: string; onSelect: (id: string) => void}) {
  const [full, setFull] = useState(false);
  const [concept, setConcept] = useState('');
  const graph = useMemo(() => buildGraph(state, selected), [state, selected]);
  const concepts = graph.concepts;
  useEffect(() => setConcept(''), [selected]);
  useEffect(() => {
    if (!full) return;
    const close = (e: KeyboardEvent) => {if (e.key === 'Escape') setFull(false);};
    window.addEventListener('keydown', close); return () => window.removeEventListener('keydown', close);
  }, [full]);
  const pick = (id: string) => {if (concepts) setConcept(id); else {onSelect(id); setFull(false);}};
  const openLesson = (id: string) => {onSelect(id); setFull(false);};
  const lit = graph.nodes.filter(n => graph.status(n.id) === 'mastered').length;
  return <div className="star-panel">
    <StarMap graph={graph} active={concept || undefined} onPick={pick}/>
    <div className="star-panel-bar"><span>{concepts ? `${graph.nodes.length} 个概念 · 本节相关 ${graph.focus.size} 个` : `已点亮 ${lit}/${graph.nodes.length}`}</span>
      <button onClick={() => setFull(true)}><Maximize2 size={14}/>全景星图</button></div>
    {concept ? <ConceptCard state={state} id={concept} openLesson={openLesson} pick={setConcept}/>
      : <p className="star-hint">{concepts ? '点一颗星，看这个概念讲什么、在哪几节学。' : '点一颗星，跳到这个知识点。'}</p>}
    <StarLegend state={state}/>
    {full && createPortal(<div className="starmap-full" role="dialog" aria-label="全景星图">
      <header><strong>{state.course!.title}</strong><span>{concepts ? `${graph.nodes.length} 个概念` : `已点亮 ${lit}/${graph.nodes.length}`}</span>
        <button style={{marginLeft: 'auto'}} aria-label="关闭全景星图" onClick={() => setFull(false)}><X size={18}/></button></header>
      <div className="starmap-full-body">
        <StarMap graph={graph} active={concept || undefined} onPick={pick} full height={window.innerHeight - 110}/>
        {concept && <aside className="starmap-side"><ConceptCard state={state} id={concept} openLesson={openLesson} pick={setConcept}/></aside>}
      </div>
      <StarLegend state={state}/>
    </div>, document.body)}
  </div>;
}

/** 首页等处的小星图（无标签；点击概念跳到它的第一个小节）。 */
export function MiniStarMap({state, selected, onOpen, height = 168}: {state: Workspace; selected?: string; onOpen: (lessonId: string) => void; height?: number}) {
  const graph = useMemo(() => buildGraph(state, selected), [state, selected]);
  const cm = state.concept_map;
  return <StarMap graph={graph} full labels={false} height={height}
    onPick={id => onOpen(cm?.nodes.find(n => n.id === id)?.lesson_ids[0] || id)}/>;
}
