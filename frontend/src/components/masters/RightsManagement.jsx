import { useEffect, useState } from 'react'
import { api } from '../../api'

// Admin-only: who can see the Export screen, the Import screen, or both.
// An admin account always has both regardless of these flags, so admins
// aren't listed here — there's nothing to toggle for them.
export default function RightsManagement({ currentUser }) {
  const [rows, setRows] = useState([])
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')
  const [savingId, setSavingId] = useState(null)

  const load = () =>
    api.users().then((all) => setRows(all.filter((u) => u.role !== 'admin')))
      .catch((e) => setErr(String(e?.message || e)))
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function toggle(u, key) {
    setErr(null); setNote('')
    setSavingId(u.id)
    const next = { can_export: u.can_export, can_import: u.can_import, [key]: !u[key] }
    try {
      await api.updateUser(u.id, next)
      setRows((rs) => rs.map((r) => (r.id === u.id ? { ...r, ...next } : r)))
      setNote(`Updated access for "${u.username}".`)
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setSavingId(null)
    }
  }

  return (
    <div className="records">
      <div className="page-head">
        <div>
          <h1>Rights Management</h1>
          <p className="muted sm">
            Control which screens each login can reach — Export only, Import only, or both.
          </p>
        </div>
      </div>
      {err && <div className="bar error">{err}</div>}
      {!err && note && <div className="bar ok">{note}</div>}

      <table className="rec-table">
        <thead>
          <tr>
            <th>Username</th>
            <th>Export Access</th>
            <th>Import Access</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={4} className="muted pad">No regular users yet — add one in User Master.</td></tr>
          )}
          {rows.map((u) => (
            <tr key={u.id}>
              <td>{u.username}{u.id === currentUser?.id && <span className="muted sm"> (you)</span>}</td>
              <td>
                <label className="mcheck">
                  <input
                    type="checkbox" checked={u.can_export} disabled={savingId === u.id}
                    onChange={() => toggle(u, 'can_export')}
                  />
                  Export
                </label>
              </td>
              <td>
                <label className="mcheck">
                  <input
                    type="checkbox" checked={u.can_import} disabled={savingId === u.id}
                    onChange={() => toggle(u, 'can_import')}
                  />
                  Import
                </label>
              </td>
              <td>
                {u.can_export && u.can_import && <span className="chip sm s-reviewed">Both</span>}
                {u.can_export && !u.can_import && <span className="chip sm blk">Export only</span>}
                {!u.can_export && u.can_import && <span className="chip sm sb">Import only</span>}
                {!u.can_export && !u.can_import && <span className="chip sm warn">No access</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
