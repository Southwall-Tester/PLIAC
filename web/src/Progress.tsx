import type {Workspace} from './api';

// 学习进度：章节达标情况（/api/learning 的 chapters）与知识手册（handbook）。数据由后端按课程规则计算，前端只呈现。
type Chapter = {chapter_id: string; title: string; passed: boolean; outcome: string; required_node_ids: string[]; rule?: {basis?: string}};
const outcomeLabel: Record<string, string> = {passed: '已达标', pending: '进行中', needs_work: '需补学', review_due: '待复习'};

export function ChapterProgress({state, open}: {state: Workspace & {chapters?: Chapter[]; handbook?: {node_id?: string; title?: string; text?: string}[]}; open: (nodeId: string) => void}) {
  const title = (id: string) => state.course?.nodes.find(n => n.id === id)?.title || id;
  const chapters = state.chapters || [];
  return <div className="progress-panel">
    {chapters.map(ch => {
      const done = ch.required_node_ids.filter(id => state.learner.states[id]?.status === 'mastered').length;
      return <section key={ch.chapter_id} className="chapter-progress">
        <header><strong>{ch.title}</strong><span className={`tag ${ch.passed ? '' : 'muted'}`}>{ch.passed ? '已达标' : outcomeLabel[ch.outcome] || '进行中'}</span></header>
        <div className="chapter-bar"><i style={{width: `${ch.required_node_ids.length ? done / ch.required_node_ids.length * 100 : 0}%`}}/></div>
        <ul>{ch.required_node_ids.map(id => <li key={id}><button onClick={() => open(id)}><i className={`dot ${state.learner.states[id]?.status || ''}`}/>{title(id)}</button></li>)}</ul>
        {ch.rule?.basis && <details><summary>达标规则</summary><p>{ch.rule.basis}</p></details>}
      </section>;
    })}
    {!!state.handbook?.length && <section className="chapter-progress"><header><strong>知识手册</strong></header>
      <ul>{state.handbook.map((h, i) => <li key={i}><button onClick={() => h.node_id && open(h.node_id)}>{h.title || title(h.node_id || '')}</button></li>)}</ul></section>}
  </div>;
}
