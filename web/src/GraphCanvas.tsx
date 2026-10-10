import {useEffect, useRef, useState} from 'react';

// 图谱渲染引擎：复用原平台的 NetworkView（static/network-*.js，PixiJS GPU 渲染，支持缩放、平移、拖拽、聚焦高亮，
// 500 个点 / 2000 条边仍可交互）。这里只负责按需加载脚本、挂载引擎，并把数据翻译成星图主题。
// 评估与取舍见 docs/knowledge-graph-requirements.md。
declare global {interface Window {NetworkView?: any}}

const SCRIPTS = ['/static/vendor/pixi-8.19.0.min.js', '/static/network-layout.js', '/static/graph-encoding.js', '/static/network-pixi.js', '/static/network-view.js'];
let loading: Promise<void> | null = null;
function loadEngine() {
  loading ??= (async () => {
    for (const src of SCRIPTS) {
      if (document.querySelector(`script[data-graph-engine="${src}"]`)) continue;
      await new Promise<void>((resolve, reject) => {
        const s = document.createElement('script');
        s.src = src; s.async = false; s.dataset.graphEngine = src;
        s.onload = () => resolve(); s.onerror = () => reject(new Error('图谱引擎加载失败'));
        document.head.appendChild(s);
      });
    }
    // 引擎以 body.network-dark 选择浅色标签；星图画布始终是夜空底色。
    document.body.classList.add('network-dark');
  })();
  return loading;
}

export type GNode = {id: string; title: string; group?: number; status?: string; anchor?: boolean};
export type GEdge = {id: string; source: string; target: string; kind: string; label?: string};

const groupTint = ['#85b7eb', '#b9a7f0', '#7fd1b9', '#f2b880', '#e6a3c4', '#9fd0e6', '#c8d98a'];
const statusStyle: Record<string, Record<string, unknown>> = {
  mastered: {fill: '#ffc35c', stroke: '#ffe3ad', shadowColor: '#ffc35c', shadowBlur: 26},
  uncertain: {fill: '#85b7eb', stroke: '#cfe0ff', shadowColor: '#85b7eb', shadowBlur: 12},
  needs_review: {fill: '#ef8a73', stroke: '#ffc4b6'},
};

function toEngine(nodes: GNode[], edges: GEdge[], big: boolean) {
  const few = nodes.length <= 14;
  return {
    nodes: nodes.map(n => ({id: n.id, data: {title: n.title, kind: 'concept', family_id: String(n.group ?? 0), layout_anchor: !!n.anchor},
      style: {size: n.anchor ? (big ? 18 : 26) : big ? 11 : few ? 20 : 18, labelFontSize: big ? 12 : nodes.length <= 14 ? 17 : 14,
        fill: groupTint[(n.group ?? 0) % groupTint.length], stroke: '#0e1a33', opacity: n.status ? 1 : .82,
        ...(n.status ? statusStyle[n.status] : {}), ...(n.anchor ? {lineWidth: 2.5, stroke: '#ffffff'} : {})}})),
    edges: edges.map(e => ({id: e.id, source: e.source, target: e.target, data: {label: e.label || '', type: e.kind},
      style: {stroke: e.kind === 'confusable' ? '#ef8a73' : '#85b7eb', opacity: e.kind === 'cooccurs' ? .16 : e.kind === 'contains' ? .2 : .42,
        endArrow: ['prerequisite', 'directed', 'contains'].includes(e.kind), lineDash: ['related', 'cooccurs', 'confusable'].includes(e.kind) ? [4, 3] : undefined}})),
  };
}

export function GraphCanvas({nodes, edges, focus, onSelect, height = 340, labels = true}: {
  nodes: GNode[]; edges: GEdge[]; focus?: string; onSelect: (id: string) => void; height?: number | string; labels?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const view = useRef<any>(null);
  const select = useRef(onSelect); select.current = onSelect;
  const topology = useRef('');
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');

  useEffect(() => {
    let alive = true;
    loadEngine().then(() => {
      if (!alive || !box.current || !window.NetworkView) return;
      view.current = new window.NetworkView(box.current, (id: string) => select.current(id), () => {});
      (box.current as any).__graphView = view.current; // 供浏览器测试定位节点，不参与业务逻辑
      const big = nodes.length > 60, small = nodes.length <= 14;
      view.current.force.repulsion = big ? 9000 : small ? 5000 : 18000; view.current.force.distance = big ? 120 : small ? 95 : 170;
      setState('ready');
    }).catch(() => alive && setState('error'));
    return () => {alive = false; view.current?.graph?.destroy?.(); view.current = null;};
  }, []);

  useEffect(() => {
    if (state !== 'ready' || !view.current) return;
    const v = view.current; v.labels = labels;
    const data = toEngine(nodes, edges, nodes.length > 60);
    const t = JSON.stringify([nodes.map(n => n.id), edges.map(e => e.id)]);
    const changed = t !== topology.current; topology.current = t;
    v.setData(data, changed).then(() => changed && v.fit?.()).catch(() => setState('error'));
  }, [state, nodes, edges, labels]);

  useEffect(() => {if (state === 'ready') view.current?.setFocus?.(focus || null);}, [state, focus]);

  const zoom = (k: number) => {const g = view.current?.graph; if (g) g.zoomTo(Math.max(.08, Math.min(6, g.getZoom() * k)), {duration: 120});};
  return <div className="graph-canvas" style={{height}}>
    <div ref={box} className="graph-canvas-stage"/>
    {state === 'loading' && <div className="graph-canvas-note">正在绘制星图…</div>}
    {state === 'error' && <div className="graph-canvas-note">星图暂时无法显示，可以从目录继续学习。</div>}
    {state === 'ready' && <div className="graph-canvas-tools">
      <button aria-label="适应画布" title="适应画布" onClick={() => view.current?.fit?.()}>⤢</button>
      <button aria-label="放大" title="放大" onClick={() => zoom(1.25)}>＋</button>
      <button aria-label="缩小" title="缩小" onClick={() => zoom(0.8)}>－</button>
    </div>}
  </div>;
}
