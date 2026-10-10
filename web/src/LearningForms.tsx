import {useEffect, useState} from 'react';
import {BookOpenText, ClipboardCheck, FileText, FlaskConical, MessageSquare, NotebookTabs, PlayCircle, Sparkles} from 'lucide-react';
import {api, localLearner, type Workspace} from './api';

// 多种学习形式（build-guide 7.1、框架 v3 3.4-3）：同一知识点、同一学习目标下，学生可选择不同形式；
// 只显示当前真实可用的形式，没有的不显示入口。各形式共享课程、知识点与学习位置。
type Props = {
  state: Workspace; courseId: string; nodeId: string; hasLab: boolean;
  onExplain: () => void; onHandout: () => void; onCheck: () => void; onLab: () => void; onTalk: () => void; onMaterials: () => void; onHandbook: () => void;
};

export function LearningForms({state, courseId, nodeId, hasLab, onExplain, onHandout, onCheck, onLab, onTalk, onMaterials, onHandbook}: Props) {
  const [resources, setResources] = useState<{video: number; other: number}>({video: 0, other: 0});
  const [handout, setHandout] = useState(false);
  useEffect(() => {
    const c = new AbortController();
    api<{resources: {format: string}[]}>(`/api/tutor/resources?${new URLSearchParams({course_id: courseId, node_id: nodeId, student_id: localLearner()})}`, c.signal)
      .then(v => setResources({video: v.resources.filter(r => r.format === 'video').length, other: v.resources.filter(r => r.format !== 'video').length}))
      .catch(() => setResources({video: 0, other: 0}));
    return () => c.abort();
  }, [courseId, nodeId]);
  useEffect(() => {
    const c = new AbortController();
    api<{jobs: {status: string}[]; scope_jobs?: {status: string}[]}>(`/api/handouts?course_id=${encodeURIComponent(courseId)}`, c.signal)
      .then(v => setHandout([...v.jobs, ...(v.scope_jobs || [])].some(j => j.status === 'completed'))).catch(() => setHandout(false));
    return () => c.abort();
  }, [courseId]);
  const handbook = !!(state as Workspace & {handbook?: unknown[]}).handbook?.length;
  const forms = [
    {key: 'explain', icon: Sparkles, label: '智能体讲解', note: '按你的基础生成', on: true, go: onExplain},
    {key: 'handout', icon: FileText, label: '课程讲义', note: '完整讲解与例题', on: handout, go: onHandout},
    {key: 'video', icon: PlayCircle, label: '视频与课件', note: resources.video ? `${resources.video} 段视频` : `${resources.other} 份资料`, on: resources.video + resources.other > 0, go: onMaterials},
    {key: 'check', icon: ClipboardCheck, label: '做几道题', note: '检验并获得反馈', on: true, go: onCheck},
    {key: 'lab', icon: FlaskConical, label: '动手实验', note: '在情境中操作', on: hasLab, go: onLab},
    {key: 'talk', icon: MessageSquare, label: '和智能体讨论', note: '追问、举例、说理解', on: true, go: onTalk},
    {key: 'handbook', icon: NotebookTabs, label: '知识手册', note: '错过的点与有效解释', on: handbook, go: onHandbook},
  ].filter(f => f.on);
  return <section className="learning-forms" aria-label="这一节可以这样学">
    <div className="learning-forms-title"><BookOpenText size={14}/>这一节可以这样学</div>
    <div className="learning-forms-grid">{forms.map(({key, icon: Icon, label, note, go}) =>
      <button key={key} type="button" onClick={go}><Icon size={17}/><span><b>{label}</b><small>{note}</small></span></button>)}</div>
  </section>;
}
