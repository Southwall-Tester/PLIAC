/* Read-only chapter projections over the original document hierarchy. */
(() => {
  'use strict';
  function create(graph, structure, memberships) {
    const byId = new Map(structure.map(n => [n.id, n]));
    const children = new Map(), concepts = new Map(), cache = new Map();
    const conceptIds = new Set(graph.nodes.map(n => n.id));
    const append = (map, key, value) => { if (!map.has(key)) map.set(key, []); map.get(key).push(value); };
    for (const node of structure) append(children, node.parent_id, node);
    for (const member of memberships) if (conceptIds.has(member.node_id)) append(concepts, member.parent_id, member.node_id);
    function scope(id = '') {
      if (!id || !byId.has(id)) return null;
      if (cache.has(id)) return cache.get(id);
      const containers = new Set(), nodes = new Set(), pending = [id];
      while (pending.length) {
        const current = pending.pop();
        if (containers.has(current)) continue;
        containers.add(current);
        for (const child of children.get(current) || []) pending.push(child.id);
        for (const concept of concepts.get(current) || []) nodes.add(concept);
      }
      const result = {id, containers, concepts:nodes, ids:new Set([...containers, ...nodes])};
      cache.set(id, result);
      return result;
    }
    const visited = new Set();
    function branch(node) {
      if (visited.has(node.id)) return [];
      visited.add(node.id);
      const descendants = (children.get(node.id) || []).flatMap(branch);
      return node.kind === 'book' ? descendants : [{id:node.id, title:node.title, children:descendants, count:scope(node.id).concepts.size}];
    }
    const tree = structure.filter(n => !n.parent_id || !byId.has(n.parent_id)).flatMap(branch);
    function exportGraph(id) {
      const selected = scope(id);
      if (!selected) return graph;
      return {...graph, title:`${graph.title} · ${byId.get(id).title}`,
        subgraph:{root_id:id, source_document_id:graph.id},
        nodes:graph.nodes.filter(n => selected.concepts.has(n.id)),
        edges:graph.edges.filter(e => selected.concepts.has(e.source) && selected.concepts.has(e.target)),
        hierarchy:{...graph.hierarchy,
          nodes:structure.filter(n => selected.containers.has(n.id)).map(n => ({...n, parent_id:n.id === id ? null : n.parent_id})),
          memberships:memberships.filter(m => selected.containers.has(m.parent_id) && selected.concepts.has(m.node_id))
            .map(m => ({source:m.parent_id, target:m.node_id}))}};
    }
    return {tree, scope, exportGraph};
  }
  window.DocumentSubgraphs = {create};
})();
