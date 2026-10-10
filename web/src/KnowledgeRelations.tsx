import {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {Network} from 'lucide-react';
import {type Workspace} from './api';

const states: Record<string, string> = {mastered: '已有掌握证据', uncertain: '仍需核验', needs_review: '需要补学核验', unknown: '尚无充分证据'};
const groups = [
  {id: 'before', title: '理解此点所需的先修', note: '以下知识是当前知识点的先修基础。'},
  {id: 'after', title: '以此点为先修的知识', note: '以下知识以当前知识点为基础；不是强制跳转。'},
  {id: 'confusable', title: '容易混淆的知识', note: '需要辨析，不表示先后顺序。'},
  {id: 'related', title: '相关知识', note: '用于联系理解，不表示先后顺序。'},
  {id: 'parent', title: '所属知识范围', note: '包含关系，不等同于先修关系。'},
  {id: 'child', title: '包含的知识', note: '包含关系，不等同于掌握判断。'},
];

export function KnowledgeRelations({state, nodeId, browse}: {state: Workspace; nodeId: string; browse: (id: string) => void}) {
  const [open, setOpen] = useState(false);
  const [focusId, focus] = useState(nodeId);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!open) return;
    const trigger = document.activeElement as HTMLElement | null;
    const target = dialog.current; target?.showModal();
    return () => {target?.close(); trigger?.focus({preventScroll: true});};
  }, [open]);
  const course = state.course;
  if (!course) return null;
  const current = course.nodes.find(node => node.id === focusId);
  const knowledge = state.learner.states[focusId];
  const relationships = (course.edges || []).filter(edge => edge.source === focusId || edge.target === focusId).map(edge => {
    const incoming = edge.target === focusId;
    const group = edge.type === 'prerequisite' ? (incoming ? 'before' : 'after') : edge.type === 'contains' ? (incoming ? 'parent' : 'child') : edge.type;
    return {edge, group, node: course.nodes.find(node => node.id === (incoming ? edge.source : edge.target))};
  }).filter(item => item.node);
  return <><button aria-label="查看知识关系" onClick={() => {focus(nodeId); setOpen(true);}}><Network size={18}/></button>
    {open && createPortal(<dialog className="source-preview knowledge-relations" aria-label="当前知识关系" ref={dialog} onCancel={() => setOpen(false)}>
      <header><h2>知识关系</h2><button onClick={() => setOpen(false)} autoFocus>关闭知识关系</button></header>
      <p>当前课程 v{course.version} 的直接关系。仅先修关系说明学习依赖；浏览关系不会改变学习目标或掌握状态。</p>
      <label>预览知识点<select value={focusId} onChange={e => focus(e.target.value)}>{course.nodes.map(node => <option key={node.id} value={node.id}>{node.title}</option>)}</select></label>
      {current && <section className="knowledge-focus"><h3>{current.title}</h3><p>{current.description}</p>
        <p>学习状态：{states[knowledge?.status] || '尚无充分证据'}。{knowledge?.reason || '暂无相关判断依据。'}</p>
        <button onClick={() => {setOpen(false); browse(current.id);}}>在工作台查看此知识点</button>
        <small>只切换查看内容，不自动改写智能体的学习计划。</small>
      </section>}
      {!relationships.length && <p>这个知识点暂时没有记录关联。</p>}
      {groups.map(group => {
        const items = relationships.filter(item => item.group === group.id);
        return items.length ? <section key={group.id} aria-label={group.title}><h3>{group.title}</h3><p>{group.note}</p>
          <ol>{items.map(({edge, node}) => <li key={edge.id}><button onClick={() => focus(node!.id)}>{node!.title}</button>
            {edge.reason && <p>关系说明：{edge.reason}</p>}
            <small>来源：{edge.source_ids?.map(id => course.sources?.find(source => source.id === id)?.title || id).join('；') || '当前关系未附来源说明'}</small>
          </li>)}</ol>
        </section> : null;
      })}
    </dialog>, document.body)}
  </>;
}
