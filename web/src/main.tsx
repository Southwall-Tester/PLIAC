import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter, Link, NavLink, Outlet, Route, Routes, useParams, useSearchParams} from 'react-router-dom';
import {ArrowLeft, ArrowRight, BookOpen, ClipboardCheck, FlaskConical, FolderOpen, History, Menu, MessageSquare, NotebookPen, PanelLeft, Settings2, Sparkles, Target, UserRound, X} from 'lucide-react';
import {api, learnerKey, localLearner, Workspace} from './api';
import {IdentityGate, IdentitySettings} from './Identity';
import {GuidedFlow} from './GuidedFlow';
import {LearningPlanPanel} from './LearningPlanPanel';
import {MLLab} from './MLLab';
import {CameraPanel} from './CameraPanel';
import {MediaAdmin} from './MediaAdmin';
import {KnowledgeRelations} from './KnowledgeRelations';
import {JobRecovery} from './TeachingJobRecovery';
import {KnowledgeActivation} from './KnowledgeActivation';
import {ResourceChoices} from './ResourceChoices';
import './style.css';
import {TutorPanel} from './TutorPanel';
import {LearningStart} from './LearningStart';
import {TeachingMaterial} from './TeachingMaterial';
import {AssessmentPanel} from './AssessmentPanel';
import {TeachingAdvance} from './TeachingAdvance';
import {NotebookPanel} from './NotebookPanel';
import {LearningArchive} from './LearningArchive';
import {LearningMemory} from './LearningMemory';
import {StageReport, SaveStageReport} from './StageReport';
import {DEMO_COURSE, HomePage, isOpen, useCourses} from './Home';
import {BRAND, Wordmark} from './Brand';
import {StarPanel} from './StarMap';

function useLoad<T>(path: string) {
  const [value, setValue] = useState<T>();
  const [error, setError] = useState('');
  const [attempt, retry] = useState(0);
  useEffect(() => {
    const controller = new AbortController(); setValue(undefined); setError('');
    api<T>(path, controller.signal).then(setValue).catch(e => {if (!controller.signal.aborted) setError(e.message);});
    return () => controller.abort();
  }, [path, attempt]);
  return {value, error, setValue, retry: () => retry(a => a + 1)};
}

function LoadState({error, retry}: {error: string; retry: () => void}) {
  return <div className="notice" role={error ? 'alert' : 'status'}>{error || '正在加载…'}{error && <button onClick={retry}>重试</button>}</div>;
}

function Appearance() {
  const [theme, setTheme] = useState(localStorage.getItem('pliac.theme') || 'paper');
  useEffect(() => {document.documentElement.dataset.theme = theme; localStorage.setItem('pliac.theme', theme);}, [theme]);
  return <label className="appearance"><Settings2 size={14}/><span className="sr-only">外观主题</span><select aria-label="外观主题" value={theme} onChange={e => setTheme(e.target.value)}><option value="paper">暖白</option><option value="neutral">中性白</option><option value="dark">星夜</option></select></label>;
}

function Shell() {
  const [open, setOpen] = useState(false);
  const navigation = useRef<HTMLElement | null>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const {courses} = useCourses();
  const Navigation = open ? 'dialog' : 'aside';
  useEffect(() => {
    if (!open || !(navigation.current instanceof HTMLDialogElement)) return;
    const target = navigation.current;
    target.showModal();
    target.querySelector<HTMLButtonElement>('.mobile-close')?.focus({preventScroll: true});
    const desktop = window.matchMedia('(min-width: 761px)');
    const resize = () => {if (desktop.matches) setOpen(false);};
    desktop.addEventListener('change', resize);
    return () => {
      desktop.removeEventListener('change', resize); target.close();
      if (opener.current?.getClientRects().length) opener.current.focus({preventScroll: true});
    };
  }, [open]);
  return <div className="shell"><header className="mobile-bar"><button ref={opener} aria-label="打开导航" aria-expanded={open} onClick={() => setOpen(true)}><Menu size={20}/></button><span>{BRAND.zh}</span></header>
    <Navigation ref={element => {navigation.current = element;}} aria-label="主导航" onCancel={event => {event.preventDefault(); setOpen(false);}} className={`global-nav ${open ? 'mobile-open' : ''}`}>
      <Link to="/" className="brand" onClick={() => setOpen(false)}><Wordmark/></Link>
      <button className="mobile-close" aria-label="关闭导航" autoFocus={open} onClick={() => setOpen(false)}><X size={18}/></button>
      <nav onClick={() => setOpen(false)}><NavLink to="/" end><Sparkles size={17}/>开始学习</NavLink><NavLink to="/courses"><BookOpen size={17}/>我的课程</NavLink><NavLink to="/archive"><FolderOpen size={17}/>学习档案</NavLink></nav>
      {!!courses?.filter(isOpen).length && <><div className="nav-section">课程</div><div className="nav-recent" onClick={() => setOpen(false)}>
        {courses.filter(isOpen).slice(0, 6).map(c => <Link key={c.id} to={`/courses/${encodeURIComponent(c.id)}`} title={c.title}>{c.title}</Link>)}</div></>}
      <div className="nav-bottom"><Link className="account-link" to="/account" onClick={() => setOpen(false)}><UserRound size={15}/>账户</Link><Appearance/></div>
    </Navigation><main className="main-page"><Outlet/></main></div>;
}

function CourseList() {
  const {courses, error} = useCourses();
  if (!courses) return <LoadState error={error} retry={() => location.reload()}/>;
  const open = courses.filter(isOpen), pending = courses.filter(c => !isOpen(c));
  return <>
    <div className="course-grid">{open.map(course => <Link key={course.id} className="course-card" to={`/courses/${encodeURIComponent(course.id)}`}>
      {course.status === 'demo' && <span className="tag" style={{alignSelf: 'flex-start'}}>体验课</span>}
      <h3>{course.title}</h3><p>{course.chapter_count} 章 · {course.node_count} 个知识点</p><span>进入学习<ArrowRight size={15}/></span></Link>)}</div>
    {pending.length > 0 && <><div className="section-heading"><h2>准备中</h2></div><div className="course-grid">{pending.map(course =>
      <div key={course.id} className="course-card pending" aria-disabled="true"><h3>{course.title}</h3><p>{course.chapter_count} 章 · {course.node_count} 个知识点</p><span>知识内容核验完成后开放</span></div>)}</div></>}
  </>;
}

function CoursesPage() {return <div className="page-width"><h1>我的课程</h1><CourseList/></div>;}

function ArchivePage() {return <LearningArchive/>;}

type View = 'learn' | 'check' | 'lab';
type Drawer = 'notes' | 'record' | null;
const statusLabel: Record<string, string> = {mastered: '已掌握', needs_review: '需补学', uncertain: '待核验'};

function WorkspacePage() {
  const {courseId = ''} = useParams();
  const query = new URLSearchParams({course_id: courseId, student_id: localLearner()});
  const {value, error, retry, setValue} = useLoad<Workspace>(`/api/learning?${query}`);
  const [navigation, setNavigation] = useState(() => window.innerWidth >= 900);
  const [conversation, setConversationState] = useState(() => (localStorage.getItem('pliac.tutor-open') ?? '1') === '1' && window.innerWidth >= 1180);
  const setConversation = (open: boolean) => {setConversationState(open); localStorage.setItem('pliac.tutor-open', open ? '1' : '0');};
  const [drawer, setDrawer] = useState<Drawer>(null);
  const [navMode, setNavModeState] = useState(() => localStorage.getItem('pliac.nav-mode') === 'map' ? 'map' : 'list');
  const setNavMode = (mode: string) => {setNavModeState(mode); localStorage.setItem('pliac.nav-mode', mode);};
  const [nodeId, selectNode] = useState('');
  const [draft, setDraft] = useState('');
  const [search, setSearch] = useSearchParams();
  const readingPane = useRef<HTMLElement>(null);
  useEffect(() => {localStorage.setItem(learnerKey('recent-course'), courseId); selectNode(localStorage.getItem(learnerKey(`node.${courseId}`)) || ''); setDraft(localStorage.getItem(learnerKey(`question.${courseId}`)) || '');}, [courseId]);
  const archived = value?.workspace.lessons.find(l => l.id === search.get('lesson'));
  const material = value?.workspace.tutor_turns?.find(turn => turn.request_id === search.get('material'));
  const showStart = search.get('setup') === '1';
  const report = value?.workspace.stage_reports?.find(item => item.id === search.get('report'));
  const selected = value?.course?.nodes.find(n => n.id === material?.proposal.target_node_id) || value?.course?.nodes.find(n => n.id === archived?.node_id) || value?.course?.nodes.find(n => n.id === (search.get('node') || nodeId)) || value?.course?.nodes.find(n => n.id === value.current_lesson?.node_id) || value?.course?.nodes[0];
  // 中栏一次只呈现一个活动：学习（讲义/教学材料）、检验、实验。
  const view: View = search.get('lab') === '1' ? 'lab'
    : search.get('view') === 'check' || (material?.activity?.type === 'assessment' && search.get('view') !== 'learn') ? 'check' : 'learn';
  const setView = (next: View) => {
    const params = new URLSearchParams(search); params.delete('lab'); params.delete('view'); params.delete('report');
    if (next === 'check') params.set('view', 'check'); else if (next === 'lab') params.set('lab', '1'); else if (material?.activity?.type === 'assessment') params.set('view', 'learn');
    setSearch(params);
  };
  const readingKey = learnerKey(`reading.${courseId}.${material?.request_id || archived?.id || selected?.id || ''}${view === 'lab' ? '.lab' : view === 'check' ? '.check' : ''}`);
  const cameraActivity = showStart || report ? undefined : view === 'lab'
    ? (value?.workspace.ml_lab?.active_id ? {kind: 'lab', id: value.workspace.ml_lab.active_id} : undefined)
    : material ? (material.activity?.type === 'assessment' && material.activity.id ? {kind: 'assessment', id: material.activity.id} : {kind: 'material', id: material.request_id})
    : undefined;
  useLayoutEffect(() => {if (readingPane.current) readingPane.current.scrollTop = Number(localStorage.getItem(readingKey) || 0);}, [readingKey]);
  const node = (id: string) => {setSearch({}); selectNode(id); localStorage.setItem(learnerKey(`node.${courseId}`), id); if (window.innerWidth < 900) setNavigation(false);};
  const flowBusy = !!value?.workspace.teaching_flow?.plan_request || !!value?.workspace.teaching_flow?.pending_plan_id;
  const course = value?.course;
  const ready = !!course && !!selected;
  const title = course?.title || (courseId === DEMO_COURSE.id ? DEMO_COURSE.title : '课程学习');

  let body: React.ReactNode;
  if (!value) body = <LoadState error={error} retry={retry}/>;
  else if (!course) body = <div className="empty"><h1>这门课程还在准备中</h1><p>知识内容核验完成后即可开始学习。</p><Link className="primary" to="/courses">看看其他课程</Link></div>;
  else if (showStart) body = <LearningStart key={'start:' + courseId} update={setValue} state={value} courseId={courseId} initialGoal={search.get('goal') || ''} done={next => {setValue(next); setSearch({});}}/>;
  else if (report) body = <StageReport report={report}/>;
  else if (!selected) body = <div className="empty"><h1>还没有知识内容</h1></div>;
  else if (view === 'lab') body = <MLLab key={'lab:' + courseId} revision={value.learner.version} courseId={courseId} materialId={material?.request_id} update={setValue}/>;
  else if (view === 'check') body = <AssessmentPanel key={'assessment:' + courseId + selected.id + (material?.activity?.id || value.workspace.assessments?.filter(item => item.node_id === selected.id).at(-1)?.id || 'new')} courseId={courseId} nodeId={selected.id} assessmentId={material?.activity?.type === 'assessment' ? material.activity.id : undefined} state={value} update={setValue}/>;
  else body = <>
    {material ? <TeachingMaterial turn={material}/> : <article className="lesson">
      {!value.workspace.onboarded && <div className="start-notice"><p>先说说你的目标和基础，讲解会更贴合你。</p><button onClick={() => setSearch({setup: '1'})}>设置起点</button></div>}
      <h1>{archived?.title || selected.title}</h1>
      {archived ? archived.paragraphs.map(p => <section key={p.id}>{p.heading && <h2>{p.heading}</h2>}<p>{p.text}</p></section>)
        : <>{selected.description && <p className="lead">{selected.description}</p>}<h2>学习目标</h2><ol>{selected.objectives.map((objective, i) => <li key={i}>{objective}</li>)}</ol></>}
    </article>}
    <div className="next-step"><div><b>读完了？</b><p>做几道题检验一下，智能体会据此安排下一步。</p></div><div className="next-actions">
      {!value.workspace.teaching_flow?.enabled && <TeachingAdvance key={'advance:' + courseId + selected.id} state={value} courseId={courseId} nodeId={selected.id} update={setValue}/>}
      <button className="primary" onClick={() => setView('check')}>去检验 <ArrowRight size={15}/></button></div></div>
  </>;

  return <div className={`workspace ${navigation ? '' : 'nav-hidden'} ${conversation ? 'conversation-open' : ''} ${navigation && navMode === 'map' ? 'nav-map' : ''}`}>
    {course && <CameraPanel key={'camera:' + courseId} courseId={courseId} activity={cameraActivity}/>}
    <header className="workspace-top">
      <Link to="/" aria-label="返回首页"><ArrowLeft size={17}/></Link>
      <button aria-label="切换课程目录" aria-expanded={navigation} onClick={() => setNavigation(!navigation)}><PanelLeft size={17}/></button>
      <span className="course-name">{title}{selected && !showStart && <> / <b>{selected.title}</b></>}</span>
      <span className="top-spacer"/>
      {ready && <><KnowledgeRelations state={value!} nodeId={selected!.id} browse={node}/><ResourceChoices course={courseId} node={selected!.id}/></>}
      {ready && <button aria-expanded={drawer === 'notes'} onClick={() => setDrawer(drawer === 'notes' ? null : 'notes')}><NotebookPen size={16}/><span className="label">笔记</span></button>}
      {ready && <button aria-expanded={drawer === 'record'} onClick={() => setDrawer(drawer === 'record' ? null : 'record')}><History size={16}/><span className="label">学习记录</span></button>}
      {course && <button aria-expanded={showStart} onClick={() => setSearch(showStart ? {} : {setup: '1'})}><Target size={16}/><span className="label">目标与起点</span></button>}
      <span className="top-divider"/>
      <Appearance/>
      <button aria-label="切换教学对话" aria-expanded={conversation} onClick={() => setConversation(!conversation)}><MessageSquare size={16}/><span className="label">对话</span></button>
    </header>
    {navigation && <aside className="course-nav" aria-label="学习目录">
      {course && <div className="seg" role="tablist" aria-label="目录或星图"><button role="tab" aria-selected={navMode === 'list'} className={navMode === 'list' ? 'on' : ''} onClick={() => setNavMode('list')}>目录</button><button role="tab" aria-selected={navMode === 'map'} className={navMode === 'map' ? 'on' : ''} onClick={() => setNavMode('map')}>星图</button></div>}
      {course && navMode === 'map' && <StarPanel state={value!} selected={selected?.id} onSelect={node}/>}
      {navMode === 'list' && course?.chapters.map(chapter => <section key={chapter.id}><h3>{chapter.title}</h3>{course.nodes.filter(n => n.chapter_id === chapter.id).map(n => {
        const status = value!.learner.states[n.id]?.status || '';
        return <button key={n.id} className={selected?.id === n.id ? 'selected' : ''} onClick={() => node(n.id)} title={statusLabel[status] || '尚未学习'}><i className={`dot ${status}`}/>{n.title}</button>;
      })}</section>)}
      {course && navMode === 'list' && <div className="nav-legend"><span><i className="dot mastered"/>已掌握</span><span><i className="dot uncertain"/>待核验</span><span><i className="dot needs_review"/>需补学</span></div>}
    </aside>}
    <main className="lesson-pane" ref={readingPane} onScroll={e => localStorage.setItem(readingKey, String(e.currentTarget.scrollTop))}>
      {ready && !showStart && !report && <nav className="activity-head" aria-label="学习活动"><div className="activity-head-inner">
        <button className={`activity-tab ${view === 'learn' ? 'on' : ''}`} aria-current={view === 'learn'} onClick={() => setView('learn')}><BookOpen size={15}/>学习</button>
        <button className={`activity-tab ${view === 'check' ? 'on' : ''}`} aria-current={view === 'check'} onClick={() => setView('check')}><ClipboardCheck size={15}/>检验</button>
        <button className={`activity-tab ${view === 'lab' ? 'on' : ''}`} aria-current={view === 'lab'} onClick={() => setView('lab')}><FlaskConical size={15}/>实验</button>
      </div></nav>}
      <div className="activity-body">
        {course && !showStart && view !== 'lab' && <LearningPlanPanel key={'plan:' + courseId} state={value!} courseId={courseId} update={setValue}/>}
        {ready && !showStart && view !== 'lab' && !flowBusy && <GuidedFlow key={'flow:' + courseId} state={value!} courseId={courseId} nodeId={selected!.id} materialId={material?.request_id} update={setValue}/>}
        {body}
      </div>
    </main>
    {ready && <TutorPanel key={courseId} hidden={!conversation} courseId={courseId} nodeId={selected!.id} title={selected!.title} state={value!} update={setValue} draft={draft} setDraft={text => {setDraft(text); localStorage.setItem(learnerKey(`question.${courseId}`), text);}} close={() => setConversation(false)}/>}
    {ready && drawer && <aside className="drawer" aria-label={drawer === 'notes' ? '笔记' : '学习记录'}>
      <div className="drawer-head"><strong style={{fontSize: 13, paddingLeft: 8}}>{drawer === 'notes' ? '笔记' : '学习记录'}</strong><span className="spacer"/><button aria-label="关闭" onClick={() => setDrawer(null)}><X size={16}/></button></div>
      <div className="drawer-body">{drawer === 'notes'
        ? <NotebookPanel key={'notebook:' + courseId + selected!.id} state={value!} courseId={courseId} nodeId={selected!.id} materialId={material?.request_id} update={setValue}/>
        : <><LearningMemory memory={value!.workspace.memory?.nodes[selected!.id]}/><SaveStageReport key={'report:' + courseId} state={value!} courseId={courseId} update={setValue}/></>}</div>
    </aside>}
  </div>;
}

function App() {return <BrowserRouter basename="/app"><Routes><Route element={<Shell/>}><Route index element={<HomePage/>}/><Route path="courses" element={<CoursesPage/>}/><Route path="archive" element={<ArchivePage/>}/><Route path="account" element={<IdentitySettings/>}/><Route path="media-review" element={<MediaAdmin/>}/><Route path="job-recovery" element={<JobRecovery/>}/><Route path="knowledge-activation" element={<KnowledgeActivation/>}/></Route><Route path="courses/:courseId" element={<WorkspacePage/>}/><Route path="*" element={<div className="empty"><h1>没有这个页面</h1><Link to="/">回到首页</Link></div>}/></Routes></BrowserRouter>;}

createRoot(document.getElementById('root')!).render(<React.StrictMode><IdentityGate><App/></IdentityGate></React.StrictMode>);
