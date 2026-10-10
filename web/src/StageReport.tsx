import {useEffect, useRef, useState} from 'react';
import {Link, useNavigate} from 'react-router-dom';
import {api, localLearner, type Workspace, type StageReport as Report} from './api';
import {ExportPDF} from './ExportPDF';
import {PersonalTextbook} from './PersonalTextbook';

export function SaveStageReport({state, courseId, update}: {state: Workspace; courseId: string; update: (state: Workspace) => void}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const id = useRef(crypto.randomUUID());
  const abort = useRef<AbortController | null>(null);
  const navigate = useNavigate();
  useEffect(() => () => abort.current?.abort(), []);
  async function save() {
    if (busy || !state.course) return;
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/tutor/report?course_id=${encodeURIComponent(courseId)}`, {
        method: 'POST', signal: controller.signal, headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({student_id: localLearner(), request_id: id.current,
          expected_version: state.learner.version, course_version: state.course.version}),
      });
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 409) update(await api<Workspace>(`/api/learning?course_id=${encodeURIComponent(courseId)}&student_id=${localLearner()}`, controller.signal));
        throw new Error(result.detail || '报告未保存，请重试。');
      }
      if (controller.signal.aborted) return;
      const saved = (result as Workspace).workspace.stage_reports!.find(report => report.request_id === id.current)!;
      update(result); id.current = crypto.randomUUID(); navigate(`?report=${saved.id}`);
    } catch (failure) {if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '网络异常，请重试。');}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }
  return <section className="assessment-panel"><button disabled={busy} onClick={save}>{busy ? '正在保存总结…' : '保存阶段学习总结'}</button>
    <p className="quiet-note">保存当前目标、证据与学习状态快照，之后可从学习档案再次打开。</p>{error && <p role="alert">{error}</p>}
  </section>;
}

export function StageReport({report}: {report: Report}) {
  const [showTextbook, setShowTextbook] = useState(false);
  useEffect(() => setShowTextbook(false), [report.id]);
  const resolved = new Set(report.diagnoses.flatMap(item => item.resolves_diagnosis_ids || []));
  const labels: Record<string, string> = {mastered: '有证据支持掌握', needs_review: '需要复习或补学', uncertain: '仍需核验', unknown: '尚未核验'};
  return <article className="lesson stage-report"><div className="eyebrow">阶段报告 · 历史快照</div><h1>{report.title}</h1>
    <ExportPDF key={report.id} kind="report" id={report.id}/>
    <button aria-expanded={showTextbook} onClick={() => setShowTextbook(value => !value)}>{showTextbook ? '收起教材汇编' : '查看本阶段教材汇编'}</button>
    {showTextbook && <PersonalTextbook key={report.id} reportId={report.id}/>}
    <p>课程 v{report.course_version} · {new Date(report.created_at).toLocaleString('zh-CN')}</p>
    <h2>学习目标与范围</h2><p>{report.goals || '尚未填写学习目标。'}</p><p>{report.scope}</p>
    <h2>知识点记录</h2>{Object.entries(report.nodes).map(([id, node]) => <section key={id}>
      <h3>{node.title} · {labels[node.status] || node.status}</h3><p>{node.reason}</p>
      <p>证据 {node.evidence_count} 条，诊断 {node.diagnosis_count} 次；数量不是掌握比例。</p>
      <details><summary>查看原始作答与诊断依据</summary><ol>{report.evidence.filter(item => item.node_id === id).map(item => <li key={item.id}>
        <p>{item.origin === 'system_observation' ? '工具观察' : '学习者记录'} · {item.prompt_level ? '记录了帮助使用' : '未记录帮助使用'}</p><p style={{whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'}}>{item.text}</p>
      </li>)}</ol>{report.diagnoses.filter(item => item.node_id === id).map(item => <p key={item.id}>历史诊断：{item.basis}{item.applicable === false && '（旧版本内容的记录）'}{resolved.has(item.id) && '（保存报告前已由后续独立核验覆盖，保留原记录。）'}</p>)}</details>
      <Link className="material-link" to={`?node=${encodeURIComponent(id)}`}>返回知识点继续学习</Link>
    </section>)}
    {!!report.notes.length && <><h2>当时保存的笔记</h2>{report.notes.map(note => <section key={note.id}><h3>{report.nodes[note.node_id]?.title} · 第 {note.revision} 版</h3><p style={{whiteSpace: 'pre-wrap'}}>{note.text}</p></section>)}</>}
    <h2>理解这份报告</h2><p>{report.limitations}</p><p>本报告不会随之后的学习更新。继续学习后，可另存一份新报告。</p>
  </article>;
}
