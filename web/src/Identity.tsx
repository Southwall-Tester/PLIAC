import {createContext, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {adoptLearner, localLearner} from './api';

type Identity = {student: string; role: 'learner' | 'admin'};
type Session = {protected: boolean; identity: Identity | null; recovery_code?: string};
const AccessContext = createContext<Session>({protected: false, identity: null});
export function useAccessSession() {return useContext(AccessContext);}

async function sessionRequest(operation = 'session', body?: Record<string, string>, signal?: AbortSignal): Promise<Session> {
  const result = await fetch(`/api/access/${operation}`, {signal, cache: 'no-store', credentials: 'same-origin',
    ...(body !== undefined ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {})});
  const data = await result.json();
  if (!result.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '身份操作未完成，请重试。');
  return data;
}

export function IdentityGate({children}: {children: ReactNode}) {
  const [session, setSession] = useState<Session>();
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [recovery, setRecovery] = useState('');
  const [adminSecret, setAdminSecret] = useState('');
  const [newCode, setNewCode] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [copied, setCopied] = useState(false);
  const action = useRef<AbortController | null>(null);
  useEffect(() => () => action.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    document.documentElement.dataset.theme = localStorage.getItem('pliac.theme') || 'paper';
    setError('');
    sessionRequest('session', undefined, controller.signal).then(value => {
      if (value.identity) adoptLearner(value.identity.student);
      setSession(value);
    }).catch(e => {if (!controller.signal.aborted) setError(e.message);});
    return () => controller.abort();
  }, [attempt]);

  // Changing/logout in another tab must not keep private old content on screen.
  useEffect(() => {
    function changed(event: StorageEvent) {
      if (event.key === 'pliac.local-learner' && event.newValue !== localLearner()) window.location.reload();
    }
    window.addEventListener('storage', changed);
    return () => window.removeEventListener('storage', changed);
  }, []);

  useEffect(() => {
    if (!session?.protected || !session.identity || newCode) return;
    const controller = new AbortController();
    let checking = false;
    async function check() {
      if (document.hidden || checking) return;
      checking = true;
      try {
        const next = await sessionRequest('session', undefined, controller.signal);
        if (!controller.signal.aborted && (!next.identity || next.identity.student !== session!.identity!.student || !next.protected)) {
          setSession({protected: true, identity: null});
          setError('学习会话已结束或身份已切换，请重新进入。浏览器内草稿仍按原身份保留。');
        }
      } catch { /* Network loss is not identity loss; writes remain server-checked. */ }
      finally {checking = false;}
    }
    window.addEventListener('focus', check);
    document.addEventListener('visibilitychange', check);
    const timer = window.setInterval(check, 60000);
    return () => {controller.abort(); clearInterval(timer); window.removeEventListener('focus', check); document.removeEventListener('visibilitychange', check);};
  }, [session, newCode]);

  async function enter(operation: 'anonymous' | 'recover' | 'admin') {
    if (busy) return;
    const controller = new AbortController(); action.current = controller;
    setBusy(true); setError('');
    try {
      const body: Record<string, string> = operation === 'recover' ? {recovery_code: recovery.trim()} : operation === 'admin' ? {secret: adminSecret} : {};
      const next = await sessionRequest(operation, body, controller.signal);
      if (!next.identity) throw new Error('服务器没有返回学习身份，请重试。');
      adoptLearner(next.identity.student);
      setSession(next); setRecovery(''); setAdminSecret('');
      setNewCode(next.recovery_code || ''); setAcknowledged(false); setCopied(false);
    } catch (e) {if (!controller.signal.aborted) setError((e as Error).message);}
    finally {if (!controller.signal.aborted) setBusy(false);}
  }

  if (newCode) return <main className="identity-page"><div className="eyebrow">匿名学习档案</div><h1>保存你的恢复码</h1>
    <p>它用于下次登录、浏览器会话过期或更换设备后找回学习记录。不需要姓名或学号。</p>
    <label className="identity-field">本次恢复码<input readOnly value={newCode} spellCheck={false} onFocus={event => event.target.select()}/></label>
    <p className="quiet-note">恢复码只在这里显示。恢复身份后会生成新码、停用旧码并退出其他会话。请保存在自己的安全位置，不要发给他人或放进比赛截图；丢失后不能仅凭匿名编号认领记录。</p>
    <button onClick={async () => {try {await navigator.clipboard.writeText(newCode); setCopied(true);} catch {setError('无法自动复制，请选中恢复码手动保存。');}}}>{copied ? '已复制' : '复制恢复码'}</button>
    <label className="identity-check"><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)}/>我已在安全位置保存恢复码</label>
    {error && <p role="alert">{error}</p>}<button className="primary" disabled={!acknowledged} onClick={() => setNewCode('')}>进入学习空间</button>
  </main>;
  if (!session) return <main className="identity-page"><h1>正在连接学习档案</h1><p role={error ? 'alert' : 'status'}>{error || '正在核对当前会话…'}</p>{error && <button onClick={() => setAttempt(value => value + 1)}>重试连接</button>}</main>;
  if (!session.protected || session.identity) return <AccessContext.Provider value={session}>{children}</AccessContext.Provider>;
  return <main className="identity-page"><div className="eyebrow">星萤 Starglow</div><h1>从你的学习档案开始</h1>
    <p>创建匿名档案，或用恢复码找回已有记录。匿名编号用于关联学习过程，不是登录凭证。</p>
    <button className="primary" disabled={busy} onClick={() => enter('anonymous')}>{busy ? '正在处理…' : '创建匿名学习档案'}</button>
    <form onSubmit={event => {event.preventDefault(); void enter('recover');}}><h2>继续已有学习</h2><label className="identity-field">恢复码<input type="password" autoComplete="off" value={recovery} onChange={event => setRecovery(event.target.value)} required minLength={32} maxLength={128}/></label><button type="submit" disabled={busy || !recovery.trim()}>恢复我的档案</button></form>
    <p className="quiet-note">需要迁移旧记录时，请联系维护者。</p>
    <details><summary>管理入口</summary><form onSubmit={event => {event.preventDefault(); void enter('admin');}}><label className="identity-field">管理凭证<input type="password" autoComplete="off" value={adminSecret} onChange={event => setAdminSecret(event.target.value)} required/></label><button type="submit" disabled={busy || !adminSecret}>进入管理身份</button></form></details>
    {error && <p role="alert">{error}</p>}
  </main>;
}

export function IdentitySettings() {
  const session = useContext(AccessContext);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function logout() {
    setBusy(true); setError('');
    try {
      await sessionRequest('logout', {});
      // Explicit logout removes browser-only private caches; server records stay intact.
      for (const key of Object.keys(localStorage)) if (key.startsWith('pliac.') && key !== 'pliac.theme') localStorage.removeItem(key);
      localStorage.removeItem('pliac-ml-student');
      window.location.assign('/app/');
    } catch (e) {setError((e as Error).message); setBusy(false);}
  }
  return <section className="page-width identity-settings"><div className="eyebrow">账户与访问</div><h1>你的学习身份</h1>
    {session.protected && session.identity ? <><p>当前身份：{session.identity.role === 'admin' ? '管理身份' : '匿名学习者'}</p><p>匿名编号：<code>{session.identity.student}</code></p>
      <p>会话有效期为 24 小时。退出或过期后，请使用已保存的恢复码重新进入；管理身份使用管理凭证。</p>
      <p>退出会清除此浏览器中的学习草稿与任务恢复缓存，不会删除已经保存到服务器的教材、笔记和报告。请先保存需要保留的内容。</p>
      {session.identity.role === 'admin' && <p><a className="material-link" href="/manage/courses">打开课程管理</a></p>}
      {session.identity.role === 'admin' && <p><a className="material-link" href="/app/admin/media-review">打开授权媒体回看</a></p>}
      {session.identity.role === 'admin' && <p><a className="material-link" href="/app/admin/job-recovery">打开教学任务恢复</a></p>}
      {session.identity.role === 'admin' && <p><a className="material-link" href="/app/admin/knowledge-activation">打开课程自动核验</a></p>}
      <button className="primary" disabled={busy} onClick={logout}>{busy ? '正在退出…' : '退出此浏览器的学习身份'}</button></> : <><p>本机模式：学习记录保存在这台电脑上。</p></>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
