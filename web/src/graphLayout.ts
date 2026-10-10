// 力导向布局：移植自旧图谱 static/network-layout.js（CourseNetwork），参数保持一致，结果确定可复现。
export type Point = {id: string; x: number; y: number; vx: number; vy: number};

export function layout(ids: string[], edges: [string, string][], iterations = 320, opts = {repulsion: 6500, distance: 145, gravity: 0.012}) {
  const nodes: Point[] = ids.map((id, i) => {
    const angle = i * 2.3999632297, radius = 45 * Math.sqrt(i + 1);
    return {id, x: Math.cos(angle) * radius, y: Math.sin(angle) * radius, vx: 0, vy: 0};
  });
  const index = new Map(nodes.map((p, i) => [p.id, i]));
  const pairs: number[] = [];
  for (const [a, b] of edges) {const i = index.get(a), j = index.get(b); if (i !== undefined && j !== undefined && i !== j) pairs.push(i, j);}
  const n = nodes.length, fx = new Float64Array(n), fy = new Float64Array(n);
  const {repulsion, distance: rest, gravity} = opts;
  for (let k = 0; k < iterations; k++) {
    for (let i = 0; i < n; i++) {fx[i] = -nodes[i].x * gravity; fy[i] = -nodes[i].y * gravity;}
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const a = nodes[i], b = nodes[j]; let dx = a.x - b.x, dy = a.y - b.y;
      if (Math.abs(dx) + Math.abs(dy) < 0.01) {dx = 0.3; dy = 0.2;}
      const d = Math.max(12, Math.hypot(dx, dy));
      const s = repulsion / (d * d) + (d < 60 ? (60 - d) * 0.12 : 0);
      const x = dx / d * s, y = dy / d * s;
      fx[i] += x; fy[i] += y; fx[j] -= x; fy[j] -= y;
    }
    for (let e = 0; e < pairs.length; e += 2) {
      const i = pairs[e], j = pairs[e + 1], a = nodes[i], b = nodes[j];
      const dx = b.x - a.x, dy = b.y - a.y, d = Math.max(1, Math.hypot(dx, dy));
      const s = (d - rest) * 0.018, x = dx / d * s, y = dy / d * s;
      fx[i] += x; fy[i] += y; fx[j] -= x; fy[j] -= y;
    }
    for (let i = 0; i < n; i++) {
      const p = nodes[i];
      p.vx = Math.max(-12, Math.min(12, (p.vx + fx[i]) * 0.76));
      p.vy = Math.max(-12, Math.min(12, (p.vy + fy[i]) * 0.76));
      p.x += p.vx; p.y += p.vy;
    }
  }
  return new Map(nodes.map(p => [p.id, {x: p.x, y: p.y}]));
}

/** 以 center 为中心、无向距离不超过 hops 的知识点集合。 */
export function neighborhood(center: string, edges: {source: string; target: string}[], hops = 2) {
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    adj.set(e.source, [...(adj.get(e.source) || []), e.target]);
    adj.set(e.target, [...(adj.get(e.target) || []), e.source]);
  }
  const seen = new Set([center]); let frontier = [center];
  for (let h = 0; h < hops; h++) {
    const next: string[] = [];
    for (const id of frontier) for (const m of adj.get(id) || []) if (!seen.has(m)) {seen.add(m); next.push(m);}
    frontier = next;
  }
  return seen;
}
