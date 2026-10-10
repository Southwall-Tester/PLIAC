import {useEffect, useRef, useState} from 'react';
import {Link, useNavigate} from 'react-router-dom';
import {ArrowRight, ArrowUp, BookOpen, Lightbulb, PenLine, RotateCcw} from 'lucide-react';
import {api, Course, learnerKey, localLearner, Workspace} from './api';
import {MiniStarMap} from './StarMap';

// 课程能否学习、显示什么标签，以后端 /api/courses 的 capabilities.learn 与 presentation.label 为准（main 2026-10-09 起提供）。
export const isOpen = (course: Course) => course.capabilities?.learn ?? course.status === 'published';
export const courseLabel = (course: Course) => course.presentation?.label || '';

export function useCourses() {
  const [courses, setCourses] = useState<Course[]>();
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    api<{courses: Course[]}>('/api/courses', controller.signal)
      .then(value => {if (!controller.signal.aborted) setCourses(value.courses);})
      .catch(failure => {if (!controller.signal.aborted) {setError(failure.message); setCourses([]);}});
    return () => controller.abort();
  }, []);
  return {courses, error};
}

type Resume = {course_id: string; course_title: string; material_id?: string; resource_id?: string; node_id?: string; kind?: 'video' | 'document' | 'lab'; title: string; updated_at: number};
type Reminder = {course_id: string; course_title: string; node_id: string; title: string; kind: string; reason: string};
const reminderLabels: Record<string, string> = {needs_work: '需要补学', version_changed: '内容有更新', review_due: '该复习了', needs_check: '待核验'};

function resumeLink(item: Resume) {
  const query: Record<string, string> = item.kind === 'lab' ? {lab: '1'} : item.resource_id ? {node: item.node_id || '', resource: item.resource_id} : {material: item.material_id || ''};
  return `/courses/${encodeURIComponent(item.course_id)}?${new URLSearchParams(query)}`;
}

/** 根据已保存的学习状态，给出“下一步”：当前教学活动 > 上次停留的知识点 > 学习顺序中第一个未掌握的知识点。 */
export function nextStep(state: Workspace, courseId: string) {
  const course = state.course!;
  const flow = state.workspace.teaching_flow;
  const turn = state.workspace.tutor_turns?.find(t => t.request_id === flow?.current_turn_id);
  const title = (id?: string) => course.nodes.find(n => n.id === id)?.title;
  if (turn) {
    const kind = turn.activity?.type === 'assessment' ? '检验' : turn.activity?.type === 'lab' ? '实验' : '学习';
    return {title: title(turn.proposal.target_node_id) || title(turn.node_id) || '当前学习活动', kind,
      reason: turn.proposal.rationale, href: `?material=${encodeURIComponent(turn.request_id)}`, nodeId: turn.proposal.target_node_id || turn.node_id};
  }
  const last = localStorage.getItem(learnerKey(`node.${courseId}`));
  if (last && title(last)) return {title: title(last)!, kind: '学习', reason: '上次停在这里。', href: `?node=${encodeURIComponent(last)}`, nodeId: last};
  const plan = state.workspace.learning_plans?.find(p => p.id === flow?.active_plan_id);
  const order = plan?.proposal.learning_order.length ? plan.proposal.learning_order : course.nodes.map(n => n.id);
  const first = order.find(id => state.learner.states[id]?.status !== 'mastered') || order[0];
  return {title: title(first) || '第一节', kind: '学习', reason: plan ? '按你确认的学习范围，下一节是这里。' : '从第一节开始，学习中会根据你的表现调整。', href: `?node=${encodeURIComponent(first || '')}`, nodeId: first};
}

export function ProgressDots({state}: {state: Workspace}) {
  const nodes = state.course?.nodes || [];
  const mastered = nodes.filter(n => state.learner.states[n.id]?.status === 'mastered').length;
  return <div className="progress-dots" aria-label={`已有证据支持掌握 ${mastered} / ${nodes.length} 个知识点`}>
    <span className="dots">{nodes.map(n => <i key={n.id} className={`dot ${state.learner.states[n.id]?.status || ''}`} title={n.title}/>)}</span>
    <span>{mastered}/{nodes.length} 已掌握</span>
  </div>;
}

function hello() {
  const hour = new Date().getHours();
  return hour < 6 ? '夜深了' : hour < 11 ? '早上好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好';
}

const starters = [
  {icon: BookOpen, label: '系统学习一门课', text: '我想系统学习这门课，从基础开始。'},
  {icon: Lightbulb, label: '弄懂一个概念', text: '我想弄懂：'},
  {icon: PenLine, label: '解决一道题', text: '我遇到一道题：'},
];

export function HomePage() {
  const {courses} = useCourses();
  const open = courses?.filter(isOpen) || [];
  const recentId = localStorage.getItem(learnerKey('recent-course'));
  const recent = open.find(c => c.id === recentId);
  const [state, setState] = useState<Workspace | null>();
  const [goal, setGoal] = useState('');
  const [courseId, setCourseId] = useState('');
  const [resume, setResume] = useState<Resume[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const input = useRef<HTMLTextAreaElement>(null);
  const navigate = useNavigate();

  useEffect(() => {if (!courseId && open.length) setCourseId(recent?.id || open[0].id);}, [courses]);
  useEffect(() => {
    if (!recent) {setState(null); return;}
    const controller = new AbortController();
    api<Workspace>(`/api/learning?${new URLSearchParams({course_id: recent.id, student_id: localLearner()})}`, controller.signal)
      .then(value => {if (!controller.signal.aborted) setState(value.course ? value : null);}).catch(() => setState(null));
    return () => controller.abort();
  }, [recent?.id]);
  useEffect(() => {
    const controller = new AbortController();
    const who = new URLSearchParams({student_id: localLearner()});
    api<{items: Resume[]}>(`/api/learning/continue?${who}`, controller.signal).then(v => setResume(v.items)).catch(() => {});
    api<{items: Reminder[]}>(`/api/learning/review-reminders?${who}`, controller.signal).then(v => setReminders(v.items)).catch(() => {});
    return () => controller.abort();
  }, []);

  const step = state && recent ? nextStep(state, recent.id) : null;
  const submit = () => {
    if (!goal.trim() || !courseId) return;
    navigate(`/courses/${encodeURIComponent(courseId)}?${new URLSearchParams({setup: '1', goal: goal.trim()})}`);
  };

  return <div className="home">
    <h1 className="home-greet">{step ? `${hello()}，接着上次的学习吧` : '今天想学点什么？'}</h1>
    <p className="home-sub">{step ? '也可以在下面换一个目标。' : '说出你的目标，我会结合课程内容和你的基础安排学习路径。'}</p>

    {step && recent && state && <section className="plan-card" aria-label="下一步安排">
      <div className="plan-main">
        <div className="plan-meta"><span className="tag">{step.kind}</span><span>{recent.title}</span></div>
        <h2>{step.title}</h2>
        <p>{step.reason}</p>
        <div className="plan-actions">
          <Link className="primary" to={`/courses/${encodeURIComponent(recent.id)}${step.href}`}>继续学习 <ArrowRight size={16}/></Link>
          <Link className="ghost" to={`/courses/${encodeURIComponent(recent.id)}?setup=1`}><RotateCcw size={14}/>调整目标</Link>
        </div>
      </div>
      <div className="plan-map">
        <MiniStarMap state={state} selected={step.nodeId} onOpen={id => navigate(`/courses/${encodeURIComponent(recent.id)}?node=${encodeURIComponent(id)}`)}/>
        <small>已点亮 {state.course!.nodes.filter(n => state.learner.states[n.id]?.status === 'mastered').length}/{state.course!.nodes.length}</small>
      </div>
    </section>}

    <form className="ask" onSubmit={event => {event.preventDefault(); submit();}}>
      <textarea ref={input} aria-label="学习目标" value={goal} placeholder={step ? '或者告诉我新的学习目标…' : '例如：我想弄懂过拟合是怎么回事，能看懂训练和验证曲线'}
        onChange={event => setGoal(event.target.value)} onKeyDown={event => {if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); submit();}}}/>
      <div className="ask-bar">
        <select aria-label="选择课程" value={courseId} onChange={event => setCourseId(event.target.value)}>
          {open.map(c => <option key={c.id} value={c.id}>{courseLabel(c) ? `${courseLabel(c)} · ${c.title}` : c.title}</option>)}
        </select>
        <button className="send" type="submit" aria-label="开始" disabled={!goal.trim() || !courseId}><ArrowUp size={18}/></button>
      </div>
    </form>
    <div className="starters">{starters.map(({icon: Icon, label, text}) =>
      <button key={label} type="button" onClick={() => {setGoal(text); input.current?.focus();}}><Icon size={14}/>{label}</button>)}</div>

    {reminders.length > 0 && <section className="home-section"><h3>待复习</h3><div className="row-list">
      {reminders.slice(0, 3).map(item => <Link key={`${item.course_id}:${item.node_id}`} to={`/courses/${encodeURIComponent(item.course_id)}?${new URLSearchParams({node: item.node_id})}`}>
        <span className="tag muted">{reminderLabels[item.kind] || '待核验'}</span><span className="row-title">{item.title}</span><small>{item.course_title}</small></Link>)}
    </div></section>}

    {resume.length > 0 && <section className="home-section"><h3>最近的材料</h3><div className="row-list">
      {resume.slice(0, 4).map(item => <Link key={`${item.course_id}:${item.kind}:${item.material_id || item.resource_id || item.title}`} to={resumeLink(item)}>
        <span className="row-title">{item.title}</span><small>{item.kind === 'lab' ? '实验' : item.kind === 'video' ? '视频' : item.kind === 'document' ? 'PDF' : '讲义'} · {item.course_title}</small></Link>)}
    </div></section>}
  </div>;
}
