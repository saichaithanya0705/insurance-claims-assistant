import { useCallback, useEffect, useState } from 'react'
import { api, post } from '../lib/api'
import { Card, ErrorBox } from './ui'
import type { User } from './LoginGate'

export function AccountsView() {
  const [users, setUsers] = useState<User[]>([])
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<'user' | 'admin'>('user')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const refresh = useCallback(() => api<{ users: User[] }>('/api/admin/users').then(result => { if (!Array.isArray(result.users)) throw new Error('Account list is invalid.'); setUsers(result.users) }).catch(e => setError(e.message)), [])
  useEffect(() => { refresh() }, [refresh])
  return <section><div className="page-head"><div><div className="eyebrow">Administration</div><h1 className="display" tabIndex={-1}>Accounts</h1><p className="subtitle">Create credentials and choose the access each person needs.</p></div></div><Card><div className="card-body"><h2>Create an account</h2><ErrorBox message={error} /><p role="status">{notice}</p><form className="account-form" onSubmit={async e => {
    e.preventDefault(); if (busy) return; setBusy(true); setError(null); setNotice('')
    try { await post<User>('/api/admin/users', { username, password, role }); setNotice(`Created ${role} account ${username}.`); setUsername(''); setPassword(''); await refresh() }
    catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }}><div className="field"><label htmlFor="account-username">New username</label><input id="account-username" value={username} onChange={e => setUsername(e.target.value)} autoComplete="off" required minLength={3} maxLength={64} pattern="[A-Za-z0-9_.-]+" /></div><div className="field"><label htmlFor="account-password">Initial password</label><input id="account-password" type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="new-password" required minLength={15} maxLength={128} /><span className="help">At least 15 characters. Share it privately with the account holder.</span></div><div className="field"><label htmlFor="account-role">Access</label><select id="account-role" value={role} onChange={e => setRole(e.target.value as 'user' | 'admin')}><option value="user">User · Own cases</option><option value="admin">Admin · All cases and administration</option></select></div><button className="btn primary" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</button></form><h2 style={{ marginTop: 28 }}>Workspace accounts</h2><ul className="account-list">{users.map(user => <li key={user.id}><strong>{user.username}</strong><span>{user.role === 'admin' ? 'Administrator' : 'User'}</span></li>)}</ul></div></Card></section>
}
