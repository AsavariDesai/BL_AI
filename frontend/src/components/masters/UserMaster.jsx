import { useEffect, useState } from 'react'
import { api } from '../../api'
import { Field, SelectField } from './MasterFields'

const BLANK = { username: '', password: '', role: 'user', can_export: true, can_import: true }

const fmtDate = (s) => (s || '').slice(0, 19).replace('T', ' ')

export default function UserMaster({ currentUser }) {
  const [rows, setRows] = useState([])
  const [view, setView] = useState('list') // 'list' | 'form'
  const [form, setForm] = useState(BLANK)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')

  const load = () => api.users().then(setRows).catch((e) => setErr(String(e?.message || e)))
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function set(key, value) { setForm((f) => ({ ...f, [key]: value })) }

  function openForm() {
    setErr(null); setNote('')
    setForm(BLANK)
    setView('form')
  }

  async function save() {
    setBusy(true); setErr(null)
    try {
      await api.createUser(form)
      setNote(`User "${form.username}" created.`)
      setView('list')
      load()
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function changeRole(u, role) {
    setErr(null)
    try {
      await api.updateUser(u.id, { role })
      load()
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  async function resetPassword(u) {
    const password = window.prompt(`New password for "${u.username}" (min 8 characters):`)
    if (!password) return
    setErr(null)
    try {
      await api.updateUser(u.id, { password })
      setNote(`Password reset for "${u.username}".`)
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  async function remove(u) {
    if (!window.confirm(`Delete user "${u.username}"?`)) return
    setErr(null)
    try {
      await api.deleteUser(u.id)
      load()
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  const canSave = form.username.trim() && form.password.length >= 8

  if (view === 'form') {
    return (
      <div className="records">
        <div className="page-head">
          <h1>User Detail</h1>
          <button className="btn ghost sm" onClick={() => setView('list')}>BACK</button>
        </div>
        {err && <div className="bar error">{err}</div>}
        <div className="mform-grid">
          <Field label="Username" required value={form.username} onChange={(v) => set('username', v)} />
          <Field label="Password" required type="password" value={form.password} onChange={(v) => set('password', v)} />
          <SelectField label="Role" required value={form.role} onChange={(v) => set('role', v)} options={['user', 'admin']} placeholder="" />
        </div>
        {form.role === 'user' && (
          <>
            <div className="msection-title">Screen Access</div>
            <div className="mform-grid">
              <label className="mcheck">
                <input type="checkbox" checked={form.can_export} onChange={(e) => set('can_export', e.target.checked)} />
                Export
              </label>
              <label className="mcheck">
                <input type="checkbox" checked={form.can_import} onChange={(e) => set('can_import', e.target.checked)} />
                Import
              </label>
            </div>
          </>
        )}
        <div className="mform-actions">
          <button className="btn" disabled={busy || !canSave} onClick={save}>SUBMIT</button>
        </div>
      </div>
    )
  }

  return (
    <div className="records">
      <div className="page-head">
        <h1>User Master</h1>
      </div>
      {err && <div className="bar error">{err}</div>}
      {!err && note && <div className="bar ok">{note}</div>}
      <div className="filters">
        <span className="grow" />
        <button className="btn" onClick={openForm}>+ Add User</button>
      </div>
      <table className="rec-table">
        <thead>
          <tr>
            <th>Username</th><th>Role</th><th>Created</th><th className="right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={4} className="muted pad">No users yet. Add one above.</td></tr>
          )}
          {rows.map((u) => (
            <tr key={u.id}>
              <td>{u.username}{u.id === currentUser?.id && <span className="muted sm"> (you)</span>}</td>
              <td>
                <select
                  className="sel"
                  value={u.role}
                  disabled={u.id === currentUser?.id}
                  onChange={(e) => changeRole(u, e.target.value)}
                >
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
              </td>
              <td>{fmtDate(u.created_at)}</td>
              <td className="right">
                <button className="link" onClick={() => resetPassword(u)}>Reset Password</button>
                {u.id !== currentUser?.id && (
                  <button className="link danger" onClick={() => remove(u)}>Delete</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
