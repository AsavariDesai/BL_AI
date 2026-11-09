import { useEffect, useState } from 'react'
import { api } from '../../api'
import { EditableTable, Field, SelectField } from './MasterFields'

const BRANCH_COLUMNS = [
  { key: 'branch_code', label: 'Branch Code', required: true },
  { key: 'branch_name', label: 'Branch Name', required: true },
  { key: 'branch_address', label: 'Branch Address', required: true },
  { key: 'city', label: 'City' },
  { key: 'state', label: 'State' },
  { key: 'country', label: 'Country' },
  { key: 'gstin_no', label: 'GSTIN No' },
  { key: 'zipcode', label: 'Zipcode', required: true },
  { key: 'telephone_no', label: 'Telephone No', required: true },
  { key: 'email_id', label: 'Email Id', required: true },
  { key: 'remarks', label: 'Remark' },
]

const BLANK = {
  assigned_user_id: '',
  company_code: '', company_name: '', city_name: '', state_region: '', country_name: '',
  company_address: '', zip_code: '', phone: '', email_id: '', pan_no: '', gstin_no: '',
  company_group_name: '', credit_period: '', currency: '', iec_no: '', website: '',
  remarks: '', branches: [],
}

const fmtDate = (s) => (s || '').slice(0, 19).replace('T', ' ')

// Admin-only screen, shared by both Export and Import: the admin creates a
// company here, then assigns it to exactly one user login — that user (and
// only that user) can then use it in their Export Company Workspace and
// their Import Vessel/Port Master + Master BL/House BL OCR.
export default function CompanyMaster() {
  const [rows, setRows] = useState([])
  const [q, setQ] = useState('')
  const [view, setView] = useState('list')
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState(BLANK)
  const [users, setUsers] = useState([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')

  const load = (query) =>
    api.companies(query ?? '').then(setRows).catch((e) => setErr(String(e?.message || e)))
  useEffect(() => { load(''); api.users().then(setUsers).catch(() => {}) }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function set(key, value) { setForm((f) => ({ ...f, [key]: value })) }

  function openForm(row) {
    setErr(null); setNote('')
    setEditingId(row ? row.id : null)
    setForm(row ? { ...BLANK, ...row, branches: row.branches || [] } : BLANK)
    setView('form')
  }

  async function save() {
    setBusy(true); setErr(null)
    try {
      if (editingId) await api.updateCompany(editingId, form)
      else await api.createCompany(form)
      setNote(editingId ? 'Company updated.' : 'Company created.')
      setView('list')
      load(q)
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function remove(id) {
    if (!window.confirm('Delete this company?')) return
    setErr(null)
    try {
      await api.deleteCompany(id)
      load(q)
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  const canSave =
    form.company_code.trim() && form.company_name.trim() &&
    form.country_name.trim() && form.pan_no.trim() && form.gstin_no.trim()

  if (view === 'form') {
    return (
      <div className="records">
        <div className="page-head">
          <h1>Company</h1>
          <button className="btn ghost sm" onClick={() => setView('list')}>BACK</button>
        </div>
        {err && <div className="bar error">{err}</div>}

        <div className="msection-title">Assignment</div>
        <div className="mform-grid">
          <SelectField
            label="Assign to User" value={form.assigned_user_id} onChange={(v) => set('assigned_user_id', v)}
            options={users.map((u) => [u.id, u.username])}
            placeholder="Unassigned (admin-only for now)"
          />
        </div>

        <div className="msection-title">Company Details</div>
        <div className="mform-grid">
          <Field label="Company Code" required value={form.company_code} onChange={(v) => set('company_code', v)} />
          <Field label="Company Name" required value={form.company_name} onChange={(v) => set('company_name', v)} />
          <Field label="City Name" value={form.city_name} onChange={(v) => set('city_name', v)} />
          <Field label="State/Region" value={form.state_region} onChange={(v) => set('state_region', v)} />
          <Field label="Country Name" required value={form.country_name} onChange={(v) => set('country_name', v)} />
          <Field label="Company Address" multiline value={form.company_address} onChange={(v) => set('company_address', v)} />
          <Field label="Zip Code" value={form.zip_code} onChange={(v) => set('zip_code', v)} />
          <Field label="Phone" value={form.phone} onChange={(v) => set('phone', v)} />
          <Field label="Email ID" value={form.email_id} onChange={(v) => set('email_id', v)} />
          <Field label="Pan No" required value={form.pan_no} onChange={(v) => set('pan_no', v)} />
          <Field label="GSTIN No" required value={form.gstin_no} onChange={(v) => set('gstin_no', v)} />
          <Field label="Company Group Name" value={form.company_group_name} onChange={(v) => set('company_group_name', v)} />
          <Field label="Credit Period" value={form.credit_period} onChange={(v) => set('credit_period', v)} />
          <Field label="Currency" value={form.currency} onChange={(v) => set('currency', v)} />
          <Field label="IEC No" value={form.iec_no} onChange={(v) => set('iec_no', v)} />
          <Field label="Website" value={form.website} onChange={(v) => set('website', v)} />
          <Field label="Remarks" multiline value={form.remarks} onChange={(v) => set('remarks', v)} />
        </div>

        <div className="msection-title">Company Branch</div>
        <EditableTable columns={BRANCH_COLUMNS} rows={form.branches} onChange={(v) => set('branches', v)} />

        <div className="mform-actions">
          <button className="btn" disabled={busy || !canSave} onClick={save}>SUBMIT</button>
        </div>
      </div>
    )
  }

  return (
    <div className="records">
      <div className="page-head">
        <h1>Company</h1>
      </div>
      {err && <div className="bar error">{err}</div>}
      {!err && note && <div className="bar ok">{note}</div>}
      <div className="filters">
        <label>Search
          <input
            placeholder="Company code or name"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && load(q)}
          />
        </label>
        <button className="btn ghost sm" onClick={() => load(q)}>Search</button>
        <span className="grow" />
        <button className="btn" onClick={() => openForm(null)}>+ Add Company</button>
      </div>
      <table className="rec-table">
        <thead>
          <tr>
            <th>Company Code</th><th>Company Name</th><th>City</th><th>Country</th>
            <th>Assigned To</th><th>Updated By</th><th>Updated Date</th><th className="right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={8} className="muted pad">No companies yet. Add one above.</td></tr>
          )}
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="mono">{r.company_code}</td>
              <td>{r.company_name}</td>
              <td>{r.city_name || '—'}</td>
              <td>{r.country_name}</td>
              <td>{r.assigned_username || <span className="chip sm warn">Unassigned</span>}</td>
              <td>{r.updated_by || '—'}</td>
              <td>{fmtDate(r.updated_at)}</td>
              <td className="right">
                <button className="link" onClick={() => openForm(r)}>Edit</button>
                <button className="link danger" onClick={() => remove(r.id)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
