import {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {Send, X} from 'lucide-react';
import {localLearner, TutorTurn, Workspace} from './api';
import {Link, useSearchParams} from 'react-router-dom';
import {SourceCitation} from './SourceCitation';
import {RichText} from './RichText';
import {ResourceRecommendations} from './ResourceRecommendations';

interface Props {
  hidden: boolean; courseId: string; nodeId: string; title: string; state: Workspace;
  draft: string; setDraft: (text: string) => void; close: () => void; update: (state: Workspace) => void;
}

export function TutorPanel({hidden, courseId, nodeId, title, state, draft, setDraft, close, update}: Props) {
  const [search] = useSearchParams();
  const labSession = search.get('lab') === '1' ? state.workspace.ml_lab?.active_id || undefined : undefined;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const turns = state.workspace.tutor_turns || [];
  const history = useRef<HTMLDivElement>(null);
  const historyContent = useRef<HTMLDivElement>(null);
  const followLatest = useRef(true);
  const previousCount = useRef(turns.length);
  const [unread, setUnread] = useState(0);
  function showLatest() {
    followLatest.current = true;
    if (history.current) history.current.scrollTop = history.current.scrollHeight;
    setUnread(0);
  }
  useLayoutEffect(() => {
    const added = Math.max(0, turns.length - previousCount.current);
    previousCount.current = turns.length;
    if (!hidden && followLatest.current) showLatest();
    else if (added) setUnread(count => count + added);
  }, [turns.length, busy, hidden]);
  useEffect(() => {
    if (hidden || !historyContent.current) return;
    // Rich text can finish rendering after the response has been inserted.
    // Follow that height change only when the reader is already at the end.
    const observer = new ResizeObserver(() => {if (followLatest.current) showLatest();});
    observer.observe(historyContent.current);
    return () => observer.disconnect();
  }, [hidden]);
  const abort = useRef<AbortController | null>(null);
  type Pending = {id: string; signature: string; message: string; nodeId: string; version: number; expected: number; labSession?: string};
  const pendingKey = `pliac.teaching-request:${localLearner()}:${courseId}`;
  const pending = useRef<Pending | null>((() => {
    try {
      const saved = JSON.parse(localStorage.getItem(pendingKey) || 'null');
      return saved && typeof saved.id === 'string' && typeof saved.message === 'string' &&
        typeof saved.nodeId === 'string' && Number.isInteger(saved.version) && Number.isInteger(saved.expected) ? saved : null;
    } catch {return null;}
  })());
  const latestDraft = useRef(draft);
  latestDraft.current = draft;
  useEffect(() => () => {abort.current?.abort();}, [courseId]);
  async function send(resume = false) {
    if (busy || (!resume && !draft.trim()) || !state.course) return;
    const message = resume && pending.current ? pending.current.message : draft.trim();
    const signature = JSON.stringify([courseId, nodeId, message, state.course.version, labSession]);
    if (!resume && pending.current?.signature !== signature) pending.current = {id: crypto.randomUUID(), signature,
      message, nodeId, version: state.course.version, expected: state.learner.version, labSession};
    if (!pending.current) return;
    const job = pending.current;
    localStorage.setItem(pendingKey, JSON.stringify(job));
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/tutor/reply?${new URLSearchParams({course_id: courseId})}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, signal: controller.signal,
        body: JSON.stringify({student_id: localLearner(), node_id: job.nodeId, message,
          course_version: job.version, expected_version: job.expected, request_id: job.id, lab_session_id: job.labSession}),
      });
      const result = await response.json() as {turn: TutorTurn; state: Workspace; detail?: string};
      if (!response.ok) {
        if (response.status === 409) {
          const statusResponse = await fetch(`/api/tutor/jobs/${encodeURIComponent(job.id)}?${new URLSearchParams({course_id: courseId, student_id: localLearner()})}`, {signal: controller.signal});
          const status = statusResponse.ok ? await statusResponse.json() : null;
          // Running calls retain their original ID. A changed learning version
          // needs a fresh request, never stale generated content forced to save.
          if (status?.status !== 'running') {pending.current = null; localStorage.removeItem(pendingKey);}
          const fresh = await fetch(`/api/learning?${new URLSearchParams({course_id: courseId, student_id: localLearner()})}`, {signal: controller.signal});
          if (fresh.ok && !controller.signal.aborted) update(await fresh.json());
        }
        throw new Error(result.detail || '回复未完成，请重试。');
      }
      if (controller.signal.aborted) return;
      update(result.state); pending.current = null; localStorage.removeItem(pendingKey);
      // Do not erase a new question typed while the current one was generating.
      if (latestDraft.current.trim() === message) setDraft('');
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '网络中断，问题草稿已保留。');
    } finally {if (!controller.signal.aborted) setBusy(false);}
  }
  return <aside className="conversation" hidden={hidden}>
    {labSession && <p className="quiet-note">我会结合你当前的实验步骤和运行结果来辅导。</p>}
    <header><h2>教学对话</h2><button aria-label="收起对话" onClick={close}><X size={18}/></button></header>
    <div className="conversation-context">围绕：{title}</div>
    <div className="conversation-history" aria-label="教学对话记录" role="region" tabIndex={0} ref={history}
      onScroll={event => {
        if (hidden) return;
        const pane = event.currentTarget;
        followLatest.current = pane.scrollHeight - pane.scrollTop - pane.clientHeight <= 32;
        if (followLatest.current) setUnread(0);
      }}>
      <div ref={historyContent}>
      {!turns.length && <div className="suggest"><p className="suggest-title">可以这样开始</p>
        {[`用一个生活中的例子解释「${title}」`, `「${title}」最容易在哪里出错？`, '我说说自己的理解，你帮我看对不对'].map(text =>
          <button key={text} type="button" onClick={() => setDraft(text)}>{text}</button>)}</div>}
      {turns.map(turn => <section className="tutor-turn" key={turn.request_id}>
        <p className="student-message">{turn.message}</p><RichText text={turn.proposal.response}/>
        <ResourceRecommendations turn={turn}/>
        {!!turn.proposal.blocks.length && <Link className="material-link" to={`?material=${encodeURIComponent(turn.request_id)}`}>在正文区阅读完整讲解</Link>}
        {turn.proposal.blocks.map((block, i) => <section key={i}><h3>{block.heading}</h3><RichText text={block.text}/>
          <details><summary>查看依据</summary>{block.citations.map((citation, j) => <SourceCitation key={j} turn={turn} citation={citation}/>)}</details></section>)}
        <details><summary>教学安排依据</summary><p>{turn.proposal.rationale}</p></details>
        {turn.proposal.question && <div className="follow-up"><RichText text={turn.proposal.question}/></div>}
        {turn.proposal.uncertainty && <small>{turn.proposal.uncertainty}</small>}
      </section>)}
      {busy && <p role="status">正在组织课程讲解，仍可阅读正文…</p>}
      </div>
    </div>
    {unread > 0 && <div className="new-replies"><span role="status">有 {unread} 条新回复</span><button type="button" onClick={() => {showLatest(); history.current?.focus({preventScroll: true});}}>查看最新回复</button></div>}
    {error && <p className="send-error" role="alert">{error} 草稿已保留。</p>}
    {!busy && pending.current && <div className="quiet-note"><p>上次请求：{pending.current.message}</p>
      <details><summary>故障协助信息</summary><p>仅在联系平台维护者时提供以下编号，不需要提供恢复码或模型密钥。</p>
        <p>课程：{courseId}</p><p>学习者：{localLearner()}</p><p style={{overflowWrap: 'anywhere'}}>任务：{pending.current.id}</p></details>
      <button type="button" onClick={() => void send(true)}>恢复或重试上次请求</button></div>}
    <form className="composer" onSubmit={event => {event.preventDefault(); void send();}}>
      <label><span className="sr-only">当前课程的问题草稿</span><textarea placeholder="哪里不太理解？" value={draft} onChange={e => setDraft(e.target.value)}/></label>
      <div className="composer-actions"><small>回答依据课程资料</small><button aria-label="发送学习问题" disabled={busy || !draft.trim()} type="submit"><Send size={17}/></button></div>
    </form>
  </aside>;
}
