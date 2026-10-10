import {useEffect, useRef, useState} from 'react';
import {Link} from 'react-router-dom';
import {api, learnerKey, localLearner, type Workspace} from './api';

type Config = {train_percent: number; depth: number; features: string; split: string};
type Scene = {title: string; role: string; mission: string; target: string; receipt: string; features: string[]};
type Run = {id: string; number: number; config: Config; result: {train_accuracy: number; validation_accuracy: number; overlap: number; confusion_matrix: number[][]}};
type Lab = {version: number; course_version: number; scenes: Record<string, Scene>; hint_texts: string[];
  restart_required?: boolean;
  support_offer?: {task_id: string; hint_available: boolean} | null;
  tasks: {id: string; title: string; goal: string; acceptance: string; nodes: string[]}[];
  lab: {sessions: {id: string}[]}; preview: {id: number; x1: number; x2: number; target: number; receipt: number}[];
  active: null | {id: string; scene: string; presentation: Scene; step: number; mode: string; profile: {goal: string}; runs: Run[];
    hints: Record<string, number>; checks: {task_id: string; feedback: string; note: string}[]; final: null | {result: {test_accuracy: number}}};
};
const pct = (value: number) => `${(100 * value).toFixed(1)}%`;

export function MLLab({courseId, materialId, revision, update}: {courseId: string; materialId?: string; revision: number; update: (value: Workspace) => void}) {
  const [state, setState] = useState<Lab>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [scene, setScene] = useState('space');
  const [answer, setAnswer] = useState<Record<string, string>>({});
  const [config, setConfig] = useState<Config>({train_percent: 60, depth: 1, features: 'sensors', split: 'separate'});
  const abort = useRef<AbortController | null>(null);
  const receipt = useRef<{signature: string; id: string} | null>(null);
  const query = new URLSearchParams({course_id: courseId, student_id: localLearner()});
  const session = state?.active;
  const draftKey = learnerKey(`lab-draft.${courseId}.${session?.id || 'new'}.${session?.step || 0}`);
  const configKey = learnerKey(`lab-config.${courseId}.${session?.id || 'new'}`);
  const receiptKey = learnerKey(`lab-request.${courseId}`);
  useEffect(() => {
    const controller = new AbortController(); abort.current = controller;
    api<Lab>(`/api/ml-lab?${query}`, controller.signal).then(setState).catch(failure => {if (!controller.signal.aborted) setError(failure.message);});
    return () => controller.abort();
  }, [courseId, revision]);
  useEffect(() => {
    try {setAnswer(JSON.parse(localStorage.getItem(draftKey) || '{}'));} catch {setAnswer({});}
    receipt.current = null;
  }, [draftKey]);
  useEffect(() => {
    const last = session?.runs.at(-1);
    let saved: Config | undefined;
    try {
      const value = JSON.parse(localStorage.getItem(configKey) || 'null');
      if (value && [50, 60, 70].includes(value.train_percent) && Number.isInteger(value.depth) && value.depth >= 0 && value.depth <= 12 && ['sensors', 'receipt'].includes(value.features) && ['separate', 'reuse'].includes(value.split)) saved = value;
    } catch { /* Invalid local hints never change server state. */ }
    setConfig(saved || last?.config || {train_percent: 60, depth: 1, features: 'sensors', split: 'separate'});
  }, [configKey]);
  function editConfig(next: Config) {setConfig(next); localStorage.setItem(configKey, JSON.stringify(next));}
  useEffect(() => () => abort.current?.abort(), []);
  function field(name: string, value: string) {
    const next = {...answer, [name]: value}; setAnswer(next); localStorage.setItem(draftKey, JSON.stringify(next));
  }
  async function operate(operation: string, fields: Record<string, unknown> = {}) {
    if (!state || busy) return;
    const controller = new AbortController(); abort.current = controller;
    const signature = JSON.stringify([operation, session?.id, fields]);
    if (!receipt.current) {
      try {const saved = JSON.parse(localStorage.getItem(receiptKey) || 'null'); if (saved?.signature === signature && typeof saved.id === 'string') receipt.current = saved;} catch { /* Ignore invalid cache. */ }
    }
    if (receipt.current?.signature !== signature) receipt.current = {signature, id: crypto.randomUUID()};
    localStorage.setItem(receiptKey, JSON.stringify(receipt.current));
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/ml-lab/${operation}?course_id=${encodeURIComponent(courseId)}`, {method: 'POST', signal: controller.signal,
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...fields, student_id: localLearner(),
          expected_version: state.version, course_version: state.course_version, request_id: receipt.current.id, session_id: session?.id})});
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 409) setState(await api<Lab>(`/api/ml-lab?${query}`, controller.signal));
        throw new Error(result.detail || '实验操作未完成。');
      }
      if (!controller.signal.aborted) {setState(result); receipt.current = null; localStorage.removeItem(receiptKey);}
      const workspace = await api<Workspace>(`/api/learning?${query}`, controller.signal);
      if (!controller.signal.aborted) update(workspace);
    } catch (failure) {if (!controller.signal.aborted) setError((failure as Error).message);}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }
  async function download() {
    try {
      const data = await api<unknown>(`/api/ml-lab/export?${query}`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
      const link = document.createElement('a'); link.href = url; link.download = `ml-lab-${courseId}.json`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) {setError((failure as Error).message);}
  }
  const select = (name: string, label: string, options: [string, string][]) => <label>{label}<select aria-label={label} value={answer[name] || ''} onChange={event => field(name, event.target.value)} required>
    <option value="">请选择</option>{options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>;
  const task = state?.tasks[session?.step || 0];
  const presentation = session?.presentation;
  return <article className="lesson ml-lab" aria-label="机器学习实验">
    <Link className="material-link" to={materialId ? `?material=${encodeURIComponent(materialId)}` : '?view=study'}>返回学习材料</Link>
    <h1>机器学习实验</h1><p>使用教学模拟数据进行真实模型实验。实验成果检查与概念掌握判断分开记录。</p>
    {error && <p role="alert">{error}</p>}
    {!state ? <p role="status">{error ? '暂无法打开实验，请返回课程检查配置。' : '正在恢复实验…'}</p> : !session || state.restart_required ? <form onSubmit={event => {event.preventDefault(); void operate('start', {scene});}}>
      {state.restart_required && <><h2>实验版本已更新</h2><p>旧记录已保留，新一轮从第一步开始。</p>
        <button type="button" disabled={busy} onClick={download}>导出旧实验记录</button></>}
      <label>实验情境<select value={scene} onChange={event => setScene(event.target.value)}>{Object.entries(state.scenes).map(([key, value]) => <option key={key} value={key}>{value.title}</option>)}</select></label>
      <button disabled={busy}>{state.restart_required ? '保留旧轮次并开始新版实验' : '开始实验'}</button></form> : <>
      <h2>{presentation?.title}</h2><p>你是{presentation?.role}。{presentation?.mission}</p>
      <p>第 {state.lab.sessions.length} 轮 · {session.mode === 'transfer' ? '迁移复测' : '实操练习'} · 已完成 {session.step} / {state.tasks.length} 步</p>
      <details><summary>实验步骤与要求</summary><ol>{state.tasks.map((item, index) => <li key={item.id} aria-current={index === session.step ? 'step' : undefined}>{item.title}：{item.acceptance}</li>)}</ol></details>
      <details><summary>查看数据样本</summary><div className="lab-table"><table><thead><tr>{['ID', 'x1', 'x2', 'target', 'receipt'].map(key => <th key={key}>{key}</th>)}</tr></thead><tbody>{state.preview.slice(0, 8).map(row => <tr key={row.id}>{[row.id, row.x1, row.x2, row.target, row.receipt].map((value, index) => <td key={index}>{value}</td>)}</tr>)}</tbody></table></div></details>
      {session.step < 4 && <section><h2>训练与验证</h2><form onSubmit={event => {event.preventDefault(); void operate('run', {config});}}><fieldset disabled={busy}>
        <label>训练集比例<select value={config.train_percent} onChange={event => editConfig({...config, train_percent: Number(event.target.value)})}>{[50, 60, 70].map(value => <option key={value} value={value}>{value}%</option>)}</select></label>
        <label>最大树深度<input type="number" min="0" max="12" value={config.depth} required onChange={event => editConfig({...config, depth: Number(event.target.value)})}/><small>0 表示自由生长。</small></label>
        <label>输入特征<select value={config.features} onChange={event => editConfig({...config, features: event.target.value})}><option value="sensors">两路传感器</option><option value="receipt">传感器与事后回执</option></select></label>
        <label>验证方式<select value={config.split} onChange={event => editConfig({...config, split: event.target.value})}><option value="separate">独立划分</option><option value="reuse">复用训练样本</option></select></label>
        <button>训练并验证</button></fieldset></form></section>}
      {!!session.runs.length && <div className="lab-table"><table><caption>实验记录</caption><thead><tr><th>实验</th><th>深度</th><th>训练准确率</th><th>验证准确率</th><th>重叠样本</th></tr></thead><tbody>{session.runs.map(run => <tr key={run.id}><td>#{run.number}</td><td>{run.config.depth || '自由'}</td><td>{pct(run.result.train_accuracy)}</td><td>{pct(run.result.validation_accuracy)}</td><td>{run.result.overlap}</td></tr>)}</tbody></table></div>}
      {task && <section><h2>{session.step + 1}. {task.title}</h2><p>{task.goal}</p><p>检查要求：{task.acceptance}</p><form onSubmit={event => {event.preventDefault(); void operate('check', {answer});}}><fieldset disabled={busy}>
        {session.step === 0 && presentation && <>{select('target', '预测目标', [['target', presentation.target], ['receipt', presentation.receipt], ['x1', presentation.features[0]]])}{select('features', '预测输入', [['sensors', 'x1 + x2'], ['receipt', 'x1 + x2 + receipt']])}{select('timing', '回执产生时间', [['before', '预测之前'], ['after', '处理完成之后']])}</>}
        {session.step >= 1 && session.step <= 3 && select('run_id', '引用实验记录', session.runs.map(run => [run.id, `#${run.number} 深度 ${run.config.depth || '自由'} 验证 ${pct(run.result.validation_accuracy)}`]))}
        {session.step === 2 && select('interpretation', '训练表现高而验证表现下降说明什么', [['gap', '对新样本的泛化表现较弱'], ['perfect', '已经掌握全部规律'], ['more_test', '应该反复查看测试集调参']])}
        {session.step === 3 && select('basis', '选择依据', [['validation', '验证集表现'], ['train', '训练集表现'], ['test', '测试集表现']])}
        {session.step === 4 && select('test_role', '测试结果的用途', [['report', '报告封存方案的泛化表现'], ['tune', '反复调整参数']])}
        {session.step >= 3 && <label>解释你的依据<textarea required maxLength={4000} value={answer.note || ''} onChange={event => field('note', event.target.value)}/></label>}
        <button>{session.step === 4 ? '封存方案并完成测试' : '检查本步成果'}</button></fieldset></form>
        <button disabled={busy || (session.hints[task.id] || 0) >= 3} onClick={() => operate('hint')}>获取提示</button>
        {state.support_offer && <section aria-label="实验帮助邀请"><h3>需要一点帮助吗？</h3>
          <p>本步已有两次成果检查未通过。可以查看分步提示，也可以继续尝试；这不是情绪或能力判断。</p>
          <button disabled={busy || !state.support_offer.hint_available} onClick={() => operate('support', {task_id: task.id, choice: 'hint'})}>查看分步提示</button>
          <button disabled={busy} onClick={() => operate('support', {task_id: task.id, choice: 'continue'})}>我想继续尝试</button>
          <p className="quiet-note">选择会保存到本轮实验，供后续辅导参考；选择继续不会增加受助等级。本步不再重复询问，仍可随时获取提示或打开教学对话。</p>
        </section>}
        {state.hint_texts?.map((hint, index) => <p key={index}>提示 {index + 1}：{hint}</p>)}
        {session.checks.filter(check => check.task_id === task.id).slice(-2).map((check, index) => <p role="status" key={index}>{check.feedback}</p>)}
      </section>}
      {session.final && <section><h2>本轮实验已完成</h2><p>封存方案测试准确率：{pct(session.final.result.test_accuracy)}。这不是概念掌握的自动证明。</p><button disabled={busy} onClick={() => operate('start', {scene: session.scene})}>换一批数据进行迁移复测</button></section>}
      <button disabled={busy} onClick={download}>导出实验与复现代码</button>
    </>}
  </article>;
}
