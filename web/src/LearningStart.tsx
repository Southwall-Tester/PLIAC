import {useEffect, useRef, useState} from 'react';
import {api, localLearner, Workspace} from './api';
import {LearningPreferences} from './LearningPreferences';

export function LearningStart({state, courseId, done, update, initialGoal = ''}: {state: Workspace; courseId: string; done: (state: Workspace) => void; update: (state: Workspace) => void; initialGoal?: string}) {
  const flow = state.workspace.teaching_flow;
  const prior = flow?.plan_request || state.workspace.learning_plans?.find(plan => plan.id === (flow?.pending_plan_id || flow?.active_plan_id));
  const [goal, setGoal] = useState(initialGoal || state.learner.profile.goals || '');
  const [background, setBackground] = useState(state.learner.profile.background || '');
  const [assessments, setAssessments] = useState<Record<string, string>>({});
  const [guided, setGuided] = useState(state.workspace.teaching_flow?.enabled ?? true);
  const [startNode, setStartNode] = useState('');
  const [mode, setMode] = useState(prior?.mode || 'topic');
  const [form, setForm] = useState(prior?.preferred_form || 'mixed');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pending = useRef<{signature: string; id: string} | null>(null);
  const abort = useRef<AbortController | null>(null);
  useEffect(() => () => abort.current?.abort(), []);
  async function save() {
    if (!state.course || busy || !goal.trim()) return;
    const values = {goals: goal.trim(), background, self_assessments: assessments, agent_guided: guided,
      start_node_id: startNode, plan_mode: mode, preferred_form: form};
    const signature = JSON.stringify(values);
    if (pending.current?.signature !== signature) pending.current = {signature, id: crypto.randomUUID()};
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/learning/onboard?${new URLSearchParams({course_id: courseId})}`, {
        method: 'POST', signal: controller.signal, headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({...values, student_id: localLearner(), course_version: state.course.version,
          expected_version: state.learner.version, request_id: pending.current.id}),
      });
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 409) update(await api<Workspace>(`/api/learning?${new URLSearchParams({course_id: courseId, student_id: localLearner()})}`, controller.signal));
        throw new Error(data.detail || '起点保存失败。');
      }
      if (!controller.signal.aborted) done(data);
    } catch (failure) {if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '保存失败，输入仍保留。');}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }
  const modes = [{id: 'systematic', label: '系统学习这门课'}, {id: 'topic', label: '补一个知识点'}, {id: 'task', label: '完成一类任务'}];
  return <article className="lesson start-page"><h1>这次想学会什么？</h1>
    <form className="start-form" onSubmit={e => {e.preventDefault(); void save();}}>
      <label><span className="sr-only">学习目标</span><textarea required maxLength={2000} value={goal} onChange={e => setGoal(e.target.value)} placeholder="例如：理解过拟合，能解释训练与验证结果的差异"/></label>
      <div className="mode-chips" role="radiogroup" aria-label="学习范围类型">{modes.map(item => <button type="button" role="radio" aria-checked={mode === item.id} key={item.id} className={mode === item.id ? 'on' : ''} onClick={() => setMode(item.id)}>{item.label}</button>)}</div>
      {error && <p role="alert">{error}</p>}<button className="primary" type="submit" disabled={busy || !goal.trim()}>{busy ? '正在安排…' : '开始学习'}</button>
      <details className="more-settings"><summary>更多设置（可选）</summary>
      <label>已有基础<textarea maxLength={2000} value={background} onChange={e => setBackground(e.target.value)} placeholder="学过哪些相关内容？哪里仍不确定？"/></label>
      <label>更想怎样开始<select aria-label="教学形式偏好" value={form} onChange={event => setForm(event.target.value)}><option value="mixed">由智能体结合目标安排</option><option value="explanation">先理解讲解与案例</option><option value="practice">先做练习检验</option><option value="lab">先做可用的实验</option></select></label>
      <label>希望先从哪个知识点开始<select aria-label="起始知识点" value={startNode} onChange={event => setStartNode(event.target.value)}><option value="">请智能体根据目标建议</option>{state.course?.nodes.map(node => <option key={node.id} value={node.id}>{node.title}</option>)}</select></label>
      <label className="identity-check"><input type="checkbox" checked={guided} onChange={event => setGuided(event.target.checked)}/>由智能体接续安排学习</label>
      <details><summary>选择起点自评（可选）</summary><p>只勾选你愿意说明的知识点，未选项保持待核验。</p>{state.course?.nodes.map(node => <label className="assessment-row" key={node.id}><span>{node.title}</span><select value={assessments[node.id] || ''} onChange={e => setAssessments(previous => {const next = {...previous}; if (e.target.value) next[node.id] = e.target.value; else delete next[node.id]; return next;})}><option value="">暂不自评</option><option value="new">尚未学过</option><option value="unsure">学过但不确定</option><option value="confident">能够解释和应用</option></select></label>)}</details>
        <LearningPreferences courseId={courseId} state={state} update={update}/>
      </details>
    </form></article>;
}
