import { useEffect, useState } from 'react'
import { api, downloadBlob } from '../api'
import PdfViewer from './PdfViewer'
import RecordsPage from './RecordsPage'
import LinkedHouse from './LinkedHouse'
import { Field, SelectField, RadioField, EditableTable } from './masters/MasterFields'

const PORT_TYPES = ['SEA PORT', 'AIR PORT', 'ICD', 'CFS', 'LAND CUSTOMS STATION']
const SHIP_TYPES = [
  'Container', 'Bulk Carrier', 'Tanker', 'General Cargo', 'RoRo',
  'Reefer', 'LPG/LNG Carrier', 'Passenger Vessel', 'Other',
]
const BERTH_COLUMNS = [
  { key: 'berth', label: 'Berth' },
  { key: 'fpd_code', label: 'FPD Code' },
]
const PORT_BLANK = {
  port_type: 'SEA PORT', port_code: '', edi_port_code: '', port_name: '', country: '',
  active: true, sez: false, berths: [],
}
const VESSEL_BLANK = {
  name: '', imo_code: '', call_sign: '', build_year: '', gross_tonnage: '', net_tonnage: '',
  ship_type: '', departure_port_id: '',
}

const DONE_STATUSES = new Set(['extracted', 'reviewed', 'exported', 'error'])
const confClass = (c) => (c >= 0.8 ? 'hi' : c >= 0.5 ? 'mid' : 'lo')

// Poll a House BL until extraction reaches a terminal state — the Import
// counterpart of App.jsx's pollDoc, kept local since this workspace doesn't
// share state with the Export review screen.
async function pollHouseDoc(id, onTick) {
  for (let i = 0; i < 300; i++) {
    const d = await api.getDoc(id)
    onTick?.(d)
    if (DONE_STATUSES.has(d.status)) return d
    await new Promise((r) => setTimeout(r, 3000))
  }
  return api.getDoc(id)
}

// House BL's own field review — the Import counterpart of App.jsx's
// GroupedRows, minus the export-field-selection checkbox (Import has no
// export-template concept yet; the Master BL's own "Download Excel" button
// covers export at the Master+linked-House level).
function HouseFieldRows({ fields, edits, selected, onSelect, onEdit }) {
  const out = []
  let lastGroup = null
  for (const f of fields) {
    if (f.group !== lastGroup) {
      out.push(<div className="grouphdr" key={`g-${f.group}`}>{f.group}</div>)
      lastGroup = f.group
    }
    const multiline = f.type === 'block' || f.type === 'list'
    const current = edits[f.key] ?? ''
    const isChanged = current !== (f.value ?? '')
    out.push(
      <div
        className={`row ${selected?.key === f.key ? 'sel' : ''}`}
        key={f.key}
        onClick={() => onSelect({ key: f.key, page: f.page, bbox: f.bbox })}
      >
        <div className="rowhead">
          <span className="label">{f.label}</span>
          <span className={`badge ${f.source === 'user' ? 'user' : confClass(f.confidence)}`}>
            {f.source === 'user' ? '✓ edited' : f.confidence ? `${Math.round(f.confidence * 100)}%` : '—'}
          </span>
          {isChanged && <span className="dot" title="unsaved change" />}
        </div>
        {multiline ? (
          <textarea
            rows={2}
            value={current}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => onEdit(f.key, e.target.value)}
          />
        ) : (
          <input
            value={current}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => onEdit(f.key, e.target.value)}
          />
        )}
        {f.ai_value && f.source === 'user' && f.ai_value !== current && (
          <div className="aihint">AI had: {f.ai_value}</div>
        )}
      </div>,
    )
  }
  return out
}

/**
 * Import's entire workflow, in one nested workspace instead of flat
 * Company/Vessel/Port Master screens: pick a company (skipped when a
 * regular user has exactly one assigned) -> that company's Vessels (and
 * Ports, which vessels pick from) -> a vessel's own workspace, where Master
 * BL / House BL uploads happen, scoped by vessel_id end to end. Company
 * creation stays admin-only (Company Master, reached from Administration),
 * since this screen is about using a company, not provisioning one.
 */
export default function ImportWorkspace({ currentUser, busy: uploadBusy, onUpload }) {
  const isAdmin = currentUser?.role === 'admin'
  const [companies, setCompanies] = useState(null)
  const [companyId, setCompanyId] = useState(null)
  const [vesselId, setVesselId] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    api.companies()
      .then((rows) => {
        setCompanies(rows)
        if (rows.length === 1) setCompanyId(rows[0].id)
      })
      .catch((e) => setErr(String(e?.message || e)))
  }, [])

  if (err) return <div className="records"><div className="bar error">{err}</div></div>
  if (companies === null) return <div className="records"><p className="muted">Loading…</p></div>

  if (!companyId) {
    return (
      <div className="records">
        <div className="page-head">
          <div>
            <h1>Import</h1>
            <p className="muted sm">Pick a company to open its workspace.</p>
          </div>
        </div>
        {companies.length === 0 ? (
          <div className="bar warn">
            {isAdmin
              ? 'No companies yet — create one in Company Master first.'
              : 'No companies assigned to your account yet — ask an Admin to assign one.'}
          </div>
        ) : (
          <div className="company-grid">
            {companies.map((c) => (
              <button key={c.id} className="company-card" onClick={() => setCompanyId(c.id)}>
                <div className="company-card-code">{c.company_code}</div>
                <div className="company-card-name">{c.company_name}</div>
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  const company = companies.find((c) => c.id === companyId)

  if (vesselId) {
    return (
      <VesselWorkspace
        vesselId={vesselId}
        onBack={() => setVesselId(null)}
        busy={uploadBusy}
        onUpload={onUpload}
      />
    )
  }

  return (
    <CompanyWorkspace
      company={company}
      onBackToCompanies={companies.length > 1 ? () => setCompanyId(null) : null}
      onOpenVessel={setVesselId}
    />
  )
}

// ------------------------------------------------------------- company tier
// Shared by Import and Export — Company -> Vessels/Ports is the same screen
// either way (Vessels/Ports are shared infrastructure, not Import-specific
// any more). `category` only changes two things: which count column the
// vessel table shows (Master BLs vs. BLs/Shipping Bills), and — Export
// only — a third "All Records" tab for the pre-vessel flat company view,
// so existing records keep showing exactly as before rather than being
// forced into a vessel after the fact (see ExportWorkspace's own comment).
export function CompanyWorkspace({
  company, onBackToCompanies, onOpenVessel, category = 'import',
  onUpload, onOpen, onOpenChild, recordsBusy,
}) {
  const [tab, setTab] = useState('vessels')
  const [vessels, setVessels] = useState([])
  const [ports, setPorts] = useState([])
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')
  const [vesselForm, setVesselForm] = useState(null) // null | {} (open form)
  const [portForm, setPortForm] = useState(null)
  const [busy, setBusy] = useState(false)

  const loadVessels = () =>
    api.vessels('', company.id).then(setVessels).catch((e) => setErr(String(e?.message || e)))
  const loadPorts = () =>
    api.ports('', company.id).then(setPorts).catch((e) => setErr(String(e?.message || e)))

  useEffect(() => { loadVessels(); loadPorts() }, [company.id]) // eslint-disable-line react-hooks/exhaustive-deps

  async function saveVessel(form) {
    setBusy(true); setErr(null)
    try {
      await api.createVessel({ ...form, company_id: company.id })
      setNote(`Vessel "${form.name}" added.`)
      setVesselForm(null)
      loadVessels()
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function savePort(form) {
    setBusy(true); setErr(null)
    try {
      await api.createPort({ ...form, company_id: company.id })
      setNote(`Port "${form.port_name}" added.`)
      setPortForm(null)
      loadPorts()
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function togglePortActive(p) {
    setBusy(true); setErr(null)
    try {
      await api.updatePort(p.id, {
        company_id: p.company_id || company.id,
        port_type: p.port_type,
        port_code: p.port_code,
        edi_port_code: p.edi_port_code,
        port_name: p.port_name,
        country: p.country,
        active: !p.active,
        sez: p.sez,
        berths: (p.berths || []).map(({ berth, fpd_code }) => ({ berth, fpd_code })),
      })
      setNote(`Port "${p.port_name}" ${p.active ? 'deactivated' : 'activated'}.`)
      loadPorts()
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  const activePorts = ports.filter((p) => p.active)

  return (
    <div className="records">
      <div className="page-head">
        <div>
          {onBackToCompanies && (
            <button className="link" onClick={onBackToCompanies}>‹ All companies</button>
          )}
          <h1>{company.company_name}</h1>
          <p className="muted sm">{company.company_code} · {company.country_name}</p>
        </div>
      </div>

      {err && <div className="bar error">{err}</div>}
      {!err && note && <div className="bar ok">{note}</div>}

      <div className="stage-tabs">
        <button className={`stage-tab ${tab === 'vessels' ? 'active' : ''}`} onClick={() => setTab('vessels')}>
          Vessels <span className="count">{vessels.length}</span>
        </button>
        <button className={`stage-tab ${tab === 'ports' ? 'active' : ''}`} onClick={() => setTab('ports')}>
          Ports <span className="count">{ports.length}</span>
        </button>
        {category === 'export' && (
          <button className={`stage-tab ${tab === 'all' ? 'active' : ''}`} onClick={() => setTab('all')}>
            All Records
          </button>
        )}
      </div>

      {tab === 'all' ? (
        <RecordsPage
          onOpen={onOpen} onOpenChild={onOpenChild} onUpload={onUpload} busy={recordsBusy}
          companyId={company.id} companyName={company.company_name}
        />
      ) : tab === 'vessels' ? (
        <>
          <div className="filters">
            <span className="grow" />
            <button className="btn" onClick={() => setVesselForm(VESSEL_BLANK)}>+ Add Vessel</button>
          </div>
          {vesselForm && (
            <VesselForm
              ports={activePorts} form={vesselForm} setForm={setVesselForm} busy={busy}
              onCancel={() => setVesselForm(null)} onSave={saveVessel}
            />
          )}
          <table className="rec-table">
            <thead>
              <tr>
                <th>Name</th><th>IMO Code</th><th>Call Sign</th><th>POL</th>
                {category === 'export' ? (
                  <><th>BLs</th><th>Shipping Bills</th></>
                ) : (
                  <th>Master BLs</th>
                )}
                <th className="right">Open</th>
              </tr>
            </thead>
            <tbody>
              {vessels.length === 0 && (
                <tr><td colSpan={category === 'export' ? 7 : 6} className="muted pad">No vessels yet. Add one above.</td></tr>
              )}
              {vessels.map((v) => (
                <tr key={v.id}>
                  <td>{v.name}</td>
                  <td className="mono">{v.imo_code}</td>
                  <td className="mono">{v.call_sign}</td>
                  <td className="muted sm">{v.departure_port_name || '—'}</td>
                  {category === 'export' ? (
                    <><td>{v.bl_count}</td><td>{v.sb_count}</td></>
                  ) : (
                    <td>{v.master_bl_count}</td>
                  )}
                  <td className="right">
                    <button className="link" onClick={() => onOpenVessel(v.id)}>Open workspace ›</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : (
        <>
          <div className="filters">
            <span className="grow" />
            <button className="btn" onClick={() => setPortForm(PORT_BLANK)}>+ Add Port</button>
          </div>
          {portForm && (
            <PortForm form={portForm} setForm={setPortForm} busy={busy} onCancel={() => setPortForm(null)} onSave={savePort} />
          )}
          <table className="rec-table">
            <thead>
              <tr><th>Port Code</th><th>Port Name</th><th>Type</th><th>Country</th><th>Status</th><th className="right">Actions</th></tr>
            </thead>
            <tbody>
              {ports.length === 0 && (
                <tr><td colSpan={6} className="muted pad">No ports yet. Add one above.</td></tr>
              )}
              {ports.map((p) => (
                <tr key={p.id}>
                  <td className="mono">{p.port_code}</td>
                  <td>{p.port_name}</td>
                  <td>{p.port_type}</td>
                  <td>{p.country}</td>
                  <td>
                    <span className={`chip sm ${p.active ? 's-reviewed' : 'warn'}`}>
                      {p.active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="right">
                    <button className={`link ${p.active ? 'danger' : ''}`} disabled={busy} onClick={() => togglePortActive(p)}>
                      {p.active ? 'Deactivate' : 'Activate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

function VesselForm({ ports, form, setForm, busy, onCancel, onSave }) {
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }))
  const canSave = form.name.trim() && form.imo_code.trim() && form.call_sign.trim()
  const portOption = (p) => [p.id, `${p.port_code} — ${p.port_name}`]
  return (
    <div className="mform-grid">
      <Field label="Name" required value={form.name} onChange={(v) => set('name', v)} />
      <Field label="IMO Code" required value={form.imo_code} onChange={(v) => set('imo_code', v)} />
      <Field label="Call Sign" required value={form.call_sign} onChange={(v) => set('call_sign', v)} />
      <Field label="Build Year" value={form.build_year} onChange={(v) => set('build_year', v)} />
      <Field label="Gross Tonnage" value={form.gross_tonnage} onChange={(v) => set('gross_tonnage', v)} />
      <Field label="Net Tonnage" value={form.net_tonnage} onChange={(v) => set('net_tonnage', v)} />
      <SelectField label="Ship Type" value={form.ship_type} onChange={(v) => set('ship_type', v)} options={SHIP_TYPES} />
      <SelectField
        label="Port of Loading (POL)" value={form.departure_port_id} onChange={(v) => set('departure_port_id', v)}
        options={ports.map(portOption)}
        placeholder={ports.length ? '—' : 'Add an active port first'}
      />
      <div className="mform-actions" style={{ gridColumn: '1 / -1' }}>
        <button className="btn ghost sm" onClick={onCancel}>Cancel</button>
        <button className="btn" disabled={busy || !canSave} onClick={() => onSave(form)}>SAVE VESSEL</button>
      </div>
    </div>
  )
}

function PortForm({ form, setForm, busy, onCancel, onSave }) {
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }))
  const canSave = form.port_code.trim() && form.port_name.trim() && form.country.trim()
  return (
    <div className="mform-grid">
      <SelectField label="Port Type" value={form.port_type} onChange={(v) => set('port_type', v)} options={PORT_TYPES} />
      <Field label="Port Code" required value={form.port_code} onChange={(v) => set('port_code', v)} />
      <Field label="EDI Port Code" value={form.edi_port_code} onChange={(v) => set('edi_port_code', v)} />
      <Field label="Port Name" required value={form.port_name} onChange={(v) => set('port_name', v)} />
      <Field label="Country" required value={form.country} onChange={(v) => set('country', v)} />
      <RadioField label="Active/Inactive" required value={form.active} onChange={(v) => set('active', v)} />
      <RadioField label="SEZ" value={form.sez} onChange={(v) => set('sez', v)} />
      <div style={{ gridColumn: '1 / -1' }}>
        <div className="msection-title">Berth</div>
        <EditableTable columns={BERTH_COLUMNS} rows={form.berths} onChange={(v) => set('berths', v)} />
      </div>
      <div className="mform-actions" style={{ gridColumn: '1 / -1' }}>
        <button className="btn ghost sm" onClick={onCancel}>Cancel</button>
        <button className="btn" disabled={busy || !canSave} onClick={() => onSave(form)}>SAVE PORT</button>
      </div>
    </div>
  )
}

// -------------------------------------------------------------- vessel tier
function VesselWorkspace({ vesselId, onBack, busy: uploadBusy, onUpload }) {
  const [vessel, setVessel] = useState(null)
  const [rows, setRows] = useState([])
  const [stage, setStage] = useState('')
  const [counts, setCounts] = useState({ pending: 0, submitted: 0 })
  const [sel, setSel] = useState(() => new Set())
  const [openId, setOpenId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [viewHouseId, setViewHouseId] = useState(null)
  const [houseDoc, setHouseDoc] = useState(null)
  const [houseEdits, setHouseEdits] = useState({})
  const [houseSelected, setHouseSelected] = useState(null)
  const [houseBusy, setHouseBusy] = useState(false)
  const [masterEdits, setMasterEdits] = useState({})
  const [masterSelected, setMasterSelected] = useState(null)
  const [masterFieldsOpen, setMasterFieldsOpen] = useState(true)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')

  useEffect(() => { api.vessel(vesselId).then(setVessel).catch((e) => setErr(String(e?.message || e))) }, [vesselId])

  const load = () => {
    setLoading(true)
    const submitted = stage === 'pending' ? false : stage === 'submitted' ? true : undefined
    api.recordsOverview({ vessel_id: vesselId, submitted }, 'import')
      .then((r) => {
        setRows(r)
        setSel((prev) => new Set([...prev].filter((id) => r.some((x) => x.id === id))))
      })
      .catch((e) => setErr(String(e?.message || e)))
      .finally(() => setLoading(false))
  }
  useEffect(load, [stage, vesselId]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadCounts = () => {
    Promise.all([
      api.recordsOverview({ vessel_id: vesselId, submitted: false }, 'import'),
      api.recordsOverview({ vessel_id: vesselId, submitted: true }, 'import'),
    ])
      .then(([pending, submitted]) => setCounts({ pending: pending.length, submitted: submitted.length }))
      .catch(() => {})
  }
  useEffect(loadCounts, [vesselId]) // eslint-disable-line react-hooks/exhaustive-deps

  function seedMaster(d) {
    setDetail(d)
    setMasterEdits(Object.fromEntries((d.fields || []).map((f) => [f.key, f.value ?? ''])))
    setMasterSelected(null)
  }

  async function watchMasterExtraction(id) {
    const final = await pollHouseDoc(id, (d) => {
      setDetail((c) => (c && c.id === d.id ? { ...c, status: d.status } : c))
    })
    if (openId === id) {
      if (final.status === 'error') {
        setDetail(final)
        setErr(final.warnings?.[0] || 'Extraction failed.')
      } else {
        seedMaster(final)
        setNote(`Extraction complete — ${final.fields.filter((f) => f.value).length} fields found.`)
      }
    }
  }

  function openDetail(id) {
    setErr(null); setNote('')
    closeHouseView()
    setOpenId(id)
    setDetail(null)
    api.getDoc(id).then((d) => {
      seedMaster(d)
      if (['uploaded', 'queued', 'processing'].includes(d.status)) watchMasterExtraction(id)
    }).catch((e) => setErr(String(e?.message || e)))
  }
  function closeDetail() { setOpenId(null); setDetail(null); closeHouseView() }

  const masterChanged = detail
    ? detail.fields.filter((f) => (masterEdits[f.key] ?? '') !== (f.value ?? '')).length
    : 0

  async function onSaveMaster() {
    if (!detail) return
    setBusy(true); setErr(null)
    try {
      const fields = detail.fields.map((f) => ({ key: f.key, value: masterEdits[f.key] ?? '' }))
      seedMaster(await api.saveFields(detail.id, fields))
      setNote('Saved. Corrections logged for every changed field.')
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function onReExtractMaster() {
    if (!detail) return
    setBusy(true); setErr(null)
    try {
      await api.extract(detail.id, { background: true })
      setNote('Re-extracting in the background…')
      watchMasterExtraction(detail.id) // no await — runs while the user waits
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  // A Master BL isn't ready to submit until every container it names has
  // turned up on an uploaded House BL, with no duplicates left unresolved —
  // mirrors Export's Shipping Bill reconciliation gate on the same idea.
  function containerIncomplete(d) {
    const rec = d?.container_reconciliation
    if (!rec) return false
    return rec.missing_containers.length > 0 || rec.duplicate_containers.length > 0
  }

  async function submit(id) {
    if (detail && detail.id === id && containerIncomplete(detail)) {
      setErr('This Master BL still has missing or duplicate containers — resolve those before submitting.')
      return
    }
    setBusy(true); setErr(null)
    try {
      await api.submitRecords([id])
      setNote('Master BL submitted.')
      closeDetail()
      load(); loadCounts()
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function uploadHouseBls(files) {
    if (!detail || !files?.length) return
    setBusy(true); setErr(null)
    try {
      const updated = await api.linkHouseBl(detail.id, Array.from(files))
      setDetail(updated)
      const n = updated.linked_house_bls?.length || 0
      setNote(updated._failedFiles?.length
        ? `${updated._failedFiles.length} file(s) failed: ${updated._failedFiles.join(', ')}`
        : `${n} House BL(s) now linked.`)
      load()
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function unlinkHouse(houseId) {
    if (!detail) return
    setBusy(true); setErr(null)
    try {
      const updated = await api.unlinkHouseBl(detail.id, houseId)
      setDetail(updated)
      if (viewHouseId === houseId) closeHouseView()
      load()
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function deleteHouse(houseId, filename) {
    if (!detail) return
    if (filename && !window.confirm(`Delete House BL "${filename}"? You can re-upload it here afterward.`)) return
    setBusy(true); setErr(null)
    try {
      await api.deleteDocument(houseId)
      if (viewHouseId === houseId) closeHouseView()
      const updated = await api.getDoc(detail.id)
      setDetail(updated)
      setNote('House BL deleted.')
      load()
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  function seedHouse(d) {
    setHouseDoc(d)
    setHouseEdits(Object.fromEntries((d.fields || []).map((f) => [f.key, f.value ?? ''])))
    setHouseSelected(null)
  }

  async function watchHouseExtraction(id) {
    const final = await pollHouseDoc(id, (d) => {
      setHouseDoc((c) => (c && c.id === d.id ? { ...c, status: d.status } : c))
    })
    if (viewHouseId === id || houseDoc?.id === id) {
      if (final.status === 'error') {
        setHouseDoc(final)
        setErr(final.warnings?.[0] || 'Extraction failed.')
      } else {
        seedHouse(final)
        setNote(`Extraction complete — ${final.fields.filter((f) => f.value).length} fields found.`)
      }
    }
  }

  function openHouse(id) {
    setErr(null); setNote('')
    setViewHouseId(id)
    setHouseDoc(null)
    setHouseEdits({})
    api.getDoc(id).then((d) => {
      seedHouse(d)
      if (['uploaded', 'queued', 'processing'].includes(d.status)) watchHouseExtraction(id)
    }).catch((e) => setErr(String(e?.message || e)))
  }

  function closeHouseView() {
    setViewHouseId(null)
    setHouseDoc(null)
    setHouseEdits({})
    setHouseSelected(null)
  }

  const houseChanged = houseDoc
    ? houseDoc.fields.filter((f) => (houseEdits[f.key] ?? '') !== (f.value ?? '')).length
    : 0

  async function onSaveHouse() {
    if (!houseDoc) return
    setHouseBusy(true); setErr(null)
    try {
      const fields = houseDoc.fields.map((f) => ({ key: f.key, value: houseEdits[f.key] ?? '' }))
      seedHouse(await api.saveFields(houseDoc.id, fields))
      setNote('Saved. Corrections logged for every changed field.')
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setHouseBusy(false)
    }
  }

  async function onReExtractHouse() {
    if (!houseDoc) return
    setHouseBusy(true); setErr(null)
    try {
      await api.extract(houseDoc.id, { background: true })
      setNote('Re-extracting in the background…')
      watchHouseExtraction(houseDoc.id) // no await — runs while the user waits
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setHouseBusy(false)
    }
  }

  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const allChecked = rows.length > 0 && rows.every((r) => sel.has(r.id))
  const toggleAll = () => setSel(allChecked ? new Set() : new Set(rows.map((r) => r.id)))

  async function exportSelected() {
    if (sel.size === 0) return
    setErr(null)
    try {
      // Checked at click time rather than kept disabled up front — container
      // reconciliation needs each Master BL's own detail (OCR'd container
      // numbers aren't columns in this list), so it's only worth fetching
      // for the handful actually selected, not every row in the table.
      const details = await Promise.all([...sel].map((id) => api.getDoc(id)))
      const incomplete = details.filter(containerIncomplete)
      if (incomplete.length > 0) {
        setErr(
          `${incomplete.length} selected Master BL(s) still have missing or duplicate containers — ` +
          `resolve those before downloading: ${incomplete.map((d) => d.filename).join(', ')}`,
        )
        return
      }
      const { blob, filename } = await api.exportMasterBlSplit([...sel])
      downloadBlob(blob, filename)
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  async function deleteMaster(id, filename) {
    if (!window.confirm(
      `Delete Master BL "${filename}"? Its linked House BL(s) are deleted too. The vessel stays — you can re-upload here afterward.`,
    )) return
    setErr(null); setBusy(true)
    try {
      await api.deleteDocument(id)
      setNote('Master BL deleted.')
      load(); loadCounts()
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function deleteSelected() {
    if (sel.size === 0) return
    if (!window.confirm(
      `Delete ${sel.size} Master BL(s)? Their linked House BL(s) are deleted too. The vessel stays — you can re-upload here afterward.`,
    )) return
    setErr(null); setBusy(true)
    try {
      const { deleted } = await api.bulkDeleteDocuments([...sel])
      setNote(`Deleted ${sel.size} Master BL(s) (${deleted.length} record(s) including linked House BLs).`)
      setSel(new Set())
      load(); loadCounts()
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  const fmtDate = (s) => (s || '').slice(0, 10)

  if (openId && detail) {
    return (
      <div className="records" style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div className="page-head">
          <h1>Master BL — {detail.filename}</h1>
          <div style={{ display: 'flex', gap: 8 }}>
            {!detail.submitted && (
              <button
                className="btn ok sm"
                disabled={busy || containerIncomplete(detail)}
                title={containerIncomplete(detail) ? 'Missing or duplicate containers must be resolved first' : ''}
                onClick={() => submit(detail.id)}
              >
                ✓ Submit
              </button>
            )}
            <button className="btn ghost sm" onClick={closeDetail}>‹ Back</button>
          </div>
        </div>
        {err && <div className="bar error">{err}</div>}
        {!err && note && <div className="bar ok">{note}</div>}
        {viewHouseId && (
          <div className="subbar">
            <span className="subbar-l">House BL{houseDoc ? ` — ${houseDoc.filename}` : ''}</span>
            {houseDoc && <span className={`chip s-${houseDoc.status}`}>{houseDoc.status}</span>}
            {houseDoc?.has_scanned_pages && <span className="chip warn">scanned</span>}
            <span className="grow" />
            {houseDoc && ['uploaded', 'queued', 'processing', 'error'].includes(houseDoc.status) && (
              <button
                className="btn ghost sm"
                disabled={houseBusy || ['queued', 'processing'].includes(houseDoc.status)}
                onClick={onReExtractHouse}
              >
                ↻ Re-run
              </button>
            )}
            <button className="btn sm" disabled={!houseDoc || houseBusy || !houseChanged} onClick={onSaveHouse}>
              Save{houseChanged ? ` (${houseChanged})` : ''}
            </button>
          </div>
        )}
        <div className="workarea">
          <section className="fields">
            <div className="fields-scroll">
              {viewHouseId ? (
                houseDoc ? (
                  <HouseFieldRows
                    fields={houseDoc.fields}
                    edits={houseEdits}
                    selected={houseSelected}
                    onSelect={setHouseSelected}
                    onEdit={(key, value) => setHouseEdits((prev) => ({ ...prev, [key]: value }))}
                  />
                ) : (
                  <p className="muted">Loading…</p>
                )
              ) : (
                <div className="linked">
                  <LinkedHouse
                    doc={detail}
                    busy={busy}
                    viewHouseId={viewHouseId}
                    onView={openHouse}
                    onLink={uploadHouseBls}
                    onUnlink={unlinkHouse}
                    onDelete={deleteHouse}
                  />
                  <div className={`sbcard ${masterFieldsOpen ? 'open' : ''}`}>
                    <div
                      className="sbcard-head"
                      role="button"
                      tabIndex={0}
                      aria-expanded={masterFieldsOpen}
                      onClick={() => setMasterFieldsOpen((o) => !o)}
                    >
                      <span className="sbcard-chev" aria-hidden="true">{masterFieldsOpen ? '▾' : '▸'}</span>
                      <span className="sbcard-title">Master BL Fields</span>
                      <span className="sbcard-count">{detail.fields.filter((f) => f.value).length}/{detail.fields.length}</span>
                      {['queued', 'processing'].includes(detail.status) && (
                        <span className="sb-pill busy">reading…</span>
                      )}
                      <span className="sbcard-grow" />
                      {!['queued', 'processing'].includes(detail.status) && (
                        <button
                          className="btn ghost xs"
                          disabled={busy}
                          onClick={(e) => { e.stopPropagation(); onReExtractMaster() }}
                        >
                          ↻ Re-run
                        </button>
                      )}
                      <button
                        className="btn xs"
                        disabled={busy || !masterChanged}
                        onClick={(e) => { e.stopPropagation(); onSaveMaster() }}
                      >
                        Save{masterChanged ? ` (${masterChanged})` : ''}
                      </button>
                    </div>
                    {masterFieldsOpen && (
                      <div className="sbcard-body">
                        <HouseFieldRows
                          fields={detail.fields}
                          edits={masterEdits}
                          selected={masterSelected}
                          onSelect={setMasterSelected}
                          onEdit={(key, value) => setMasterEdits((prev) => ({ ...prev, [key]: value }))}
                        />
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </section>
          <section className="pdf">
            {viewHouseId && (
              <div className="pdf-banner">
                <span>Showing House BL</span>
                <button className="link" onClick={closeHouseView}>Show Master BL</button>
              </div>
            )}
            <PdfViewer
              fileUrl={api.fileUrl(viewHouseId ?? detail.id)}
              selected={viewHouseId ? houseSelected : masterSelected}
            />
          </section>
        </div>
      </div>
    )
  }

  return (
    <div className="records">
      <div className="page-head">
        <div>
          <button className="link" onClick={onBack}>‹ {vessel?.company_name || 'Company'}</button>
          <h1>{vessel?.name || 'Vessel'}</h1>
          <p className="muted sm">
            {vessel ? `IMO ${vessel.imo_code} · POL ${vessel.departure_port_name || '—'}` : ''}
          </p>
        </div>
        <label className={`btn ${uploadBusy ? 'disabled' : ''}`}>
          {uploadBusy ? 'Working…' : '↑ Upload Master BL(s)'}
          <input
            type="file" accept="application/pdf" multiple hidden disabled={uploadBusy}
            onChange={(e) => e.target.files.length && Promise.resolve(onUpload(e.target.files, vesselId)).then(() => { load(); loadCounts() })}
          />
        </label>
      </div>

      <div className="stage-tabs">
        <button className={`stage-tab ${stage === '' ? 'active' : ''}`} onClick={() => setStage('')}>
          All <span className="count">{counts.pending + counts.submitted}</span>
        </button>
        <button className={`stage-tab ${stage === 'pending' ? 'active' : ''}`} onClick={() => setStage('pending')}>
          Pending <span className="count">{counts.pending}</span>
        </button>
        <button className={`stage-tab ${stage === 'submitted' ? 'active' : ''}`} onClick={() => setStage('submitted')}>
          Submitted <span className="count">{counts.submitted}</span>
        </button>
      </div>

      {err && <div className="bar error">{err}</div>}
      {!err && note && <div className="bar ok">{note}</div>}

      {sel.size > 0 && (
        <div className="selbar">
          <span className="pill">{sel.size} selected</span>
          <span className="grow" />
          <button className="btn" onClick={exportSelected}>
            ↓ Download Excel (.zip, {sel.size} Master BL{sel.size > 1 ? 's' : ''})
          </button>
          <button className="btn danger" disabled={busy} onClick={deleteSelected}>
            🗑 Delete {sel.size}
          </button>
        </div>
      )}

      <table className="rec-table">
        <thead>
          <tr>
            <th className="cb"><input type="checkbox" checked={allChecked} onChange={toggleAll} /></th>
            <th>Job ID</th><th>Source File</th><th>Linked House BLs</th>
            <th>Stage</th><th>Updated</th><th>Status</th><th className="right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && !loading && (
            <tr><td colSpan={8} className="muted pad">Nothing here yet. Upload a Master BL above.</td></tr>
          )}
          {rows.map((r) => (
            <tr key={r.id} className={sel.has(r.id) ? 'on' : ''}>
              <td className="cb"><input type="checkbox" checked={sel.has(r.id)} onChange={() => toggle(r.id)} /></td>
              <td className="mono">{r.job_id}</td>
              <td className="fn" title={r.filename}>{r.filename}</td>
              <td>{r.linked_house_bl_count || 0}</td>
              <td>
                <span className={`chip sm ${r.submitted ? 's-reviewed' : 'warn'}`}>
                  {r.submitted ? 'Submitted' : 'Pending'}
                </span>
              </td>
              <td>{fmtDate(r.updated_at)}</td>
              <td><span className={`chip sm s-${r.status}`}>{r.status}</span></td>
              <td className="right">
                <button className="link" onClick={() => openDetail(r.id)}>Manage ›</button>
                <button className="link danger" disabled={busy} onClick={() => deleteMaster(r.id, r.filename)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
