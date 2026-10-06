import { useCallback, useEffect, useRef, useState, type ComponentType } from 'react'
import { LockKeyhole } from 'lucide-react'
import { api, post, setCsrfToken } from '../lib/api'
import { ErrorBox } from './ui'
import { RECENT_KEY } from '../lib/format'

export interface User { id: string; username: string; role: 'user' | 'admin' }
interface Session { user: User | null; setup_required: boolean; csrf_token: string; auth_enabled: boolean }

function validSession(session: Session) {
  if (!session || typeof session.csrf_token !== 'string' || (session.user && (!session.user.id || !session.user.username || !['user', 'admin'].includes(session.user.role)))) throw new Error('The sign-in response is invalid.')
  setCsrfToken(session.csrf_token)
  return session
}

export function LoginGate({ component: Component }: { component: ComponentType<{ user: User; onLogout: () => void; authEnabled: boolean }> }) {
  const [session, setSession] = useState<Session | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const sessionRequest = useRef(0)
  const refresh = useCallback((keepError = false) => {
    if (!keepError) setError(null)
    const request = ++sessionRequest.current
    api<Session>('/api/auth/session').then(result => { if (request === sessionRequest.current) setSession(validSession(result)) }).catch(e => { if (request === sessionRequest.current) setError(e.message) })
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    const request = ++sessionRequest.current
    api<Session>('/api/auth/session', { signal: controller.signal }).then(result => { if (request === sessionRequest.current) setSession(validSession(result)) }).catch(e => { if (request === sessionRequest.current && !controller.signal.aborted) setError(e.message) })
    const expired = () => { setSession(null); setPassword(''); setConfirm(''); refresh() }
    window.addEventListener('claims-session-expired', expired)
    return () => { controller.abort(); sessionRequest.current += 1; window.removeEventListener('claims-session-expired', expired) }
  }, [refresh])
  const logout = async () => {
    setBusy(true)
    try { await post('/api/auth/logout'); Object.keys(sessionStorage).filter(key => key.startsWith(RECENT_KEY)).forEach(key => sessionStorage.removeItem(key)); setSession(null); setPassword(''); setConfirm(''); refresh() }
    catch (e) { setError((e as Error).message) }
    finally { setBusy(false) }
  }
  if (session?.user) return <><Component key={session.user.id} user={session.user} onLogout={logout} authEnabled={session.auth_enabled} />{error && <div className="auth-toast" role="alert">{error}</div>}</>
  return <main className="login-page"><section className="login-card" aria-labelledby="login-title">
    <div className="login-mark"><LockKeyhole size={24} /></div><div className="eyebrow">Claims investigator</div>
    <h1 id="login-title">{session?.setup_required ? 'Create your administrator account' : 'Welcome back'}</h1>
    <p className="section-desc">{session?.setup_required ? 'Set up this local workspace. You can create user and additional admin accounts after signing in.' : 'Sign in with your user or admin account to continue.'}</p>
    <ErrorBox message={error} />
    {!session ? <><p role="status">{error ? 'The sign-in service could not be reached.' : 'Loading sign-in…'}</p>{error && <button className="btn" onClick={() => refresh()}>Retry connection</button>}</> : <form onSubmit={async e => {
      e.preventDefault(); if (busy) return
      setError(null)
      if (session.setup_required && password !== confirm) { setError('Passwords must match.'); return }
      setBusy(true)
      try {
        if (session.setup_required) await post('/api/auth/setup', { username, password, role: 'admin' })
        const result = await post<{ user: User; csrf_token: string }>('/api/auth/login', { username, password })
        sessionRequest.current += 1
        setSession(validSession({ ...session, ...result, setup_required: false }))
        setPassword(''); setConfirm('')
      } catch (e) { setError((e as Error).message); if (session.setup_required) refresh(true) }
      finally { setBusy(false) }
    }}>
      <div className="field"><label htmlFor="login-username">Username</label><input id="login-username" autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} minLength={3} maxLength={64} pattern="[A-Za-z0-9_.-]+" required disabled={busy} autoFocus /><span className="help">Letters, numbers, dots, underscores or hyphens.</span></div>
      <div className="field"><label htmlFor="login-password">Password</label><input id="login-password" type="password" autoComplete={session.setup_required ? 'new-password' : 'current-password'} value={password} onChange={e => setPassword(e.target.value)} minLength={session.setup_required ? 15 : 1} maxLength={128} required disabled={busy} />{session.setup_required && <span className="help">Use at least 15 characters. A passphrase works well.</span>}</div>
      {session.setup_required && <div className="field"><label htmlFor="login-confirm">Confirm password</label><input id="login-confirm" type="password" autoComplete="new-password" value={confirm} onChange={e => setConfirm(e.target.value)} minLength={15} maxLength={128} required disabled={busy} /></div>}
      <button className="btn primary login-submit" disabled={busy}>{busy ? 'Signing in…' : session.setup_required ? 'Create account and sign in' : 'Sign in'}</button>
    </form>}
    <p className="footnote">Your account determines access. Users see their own cases; admins manage accounts and review all cases.</p>
  </section></main>
}
