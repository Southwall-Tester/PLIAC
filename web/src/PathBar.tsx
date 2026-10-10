import {ArrowRight} from 'lucide-react';
import type {Workspace} from './api';
import type {ActivityKey} from './activities';

// 学习路径条：本章位置 + 当前知识点状态 + 一条带依据的下一步。
// 下一步只依据已有知识判断（status/due），不由页面点击推断掌握。
type State = {status: string; reason: string; due?: boolean};
const statusText: Record<string, string> = {mastered: '已掌握', needs_review: '需补学', uncertain: '待核验'};

export function nextStep(state: Workspace, nodeId: string): {text: string; action: 'setup' | 'check' | 'explain' | 'next' | 'learn'; label: string} {
  if (!state.workspace.onboarded) return {text: '先说说目标和基础，智能体据此安排', action: 'setup', label: '设定起点'};
  const s = state.learner.states[nodeId] as State | undefined;
  if (s?.due) return {text: '距上次掌握已有一段时间，做一次简短复测', action: 'check', label: '去复测'};
  if (s?.status === 'needs_review') return {text: '上次检验暴露了缺口，让智能体换个讲法', action: 'explain', label: '重新讲解'};
  if (s?.status === 'uncertain') return {text: '已有学习记录但还不确定，做几道题确认', action: 'check', label: '去检验'};
  if (s?.status === 'mastered') return {text: '证据支持已掌握，可以进入下一个知识点', action: 'next', label: '下一个'};
  return {text: '先读讲解，再做几道题检验', action: 'learn', label: '开始'};
}

export function PathBar({state, nodeId, activity, onNode, onAct}: {
  state: Workspace; nodeId: string; activity: ActivityKey;
  onNode: (id: string) => void; onAct: (action: ReturnType<typeof nextStep>['action']) => void;
}) {
  const course = state.course!;
  const node = course.nodes.find(n => n.id === nodeId);
  if (!node) return null;
  const chapter = course.chapters.find(c => c.id === node.chapter_id);
  const nodes = course.nodes.filter(n => n.chapter_id === node.chapter_id);
  const mastered = nodes.filter(n => state.learner.states[n.id]?.status === 'mastered').length;
  const current = state.learner.states[nodeId] as State | undefined;
  const step = nextStep(state, nodeId);
  const redundant = (step.action === 'check' && activity === 'check') || (step.action === 'learn' && activity === 'learn');
  return <div className="path-bar" aria-label="学习路径">
    <div className="path-chapter">
      <span className="path-title">{chapter?.title || '本章'}</span>
      <span className="path-dots">{nodes.map(n => <button key={n.id} type="button" title={n.title}
        aria-label={`${n.title}：${statusText[state.learner.states[n.id]?.status] || '尚未学习'}`} aria-current={n.id === nodeId}
        className={`path-dot ${state.learner.states[n.id]?.status || ''} ${n.id === nodeId ? 'here' : ''}`} onClick={() => onNode(n.id)}/>)}</span>
      <span className="path-count">{mastered}/{nodes.length}</span>
    </div>
    <div className="path-next">
      <span className={`path-state ${current?.status || ''}`}>{current?.due ? '复习到期' : statusText[current?.status || ''] || '尚未学习'}</span>
      <span className="path-text">{step.text}</span>
      {!redundant && <button type="button" onClick={() => onAct(step.action)}>{step.label}<ArrowRight size={13}/></button>}
    </div>
  </div>;
}
