import { Fragment, useEffect, useState } from 'react'
import { api, downloadBlob } from '../api'
import { SB_PENDING, sbMetaLine, sbStatus } from '../sbUtil'

const STATUSES = ['uploaded', 'queued', 'processing', 'extracted', 'reviewed', 'exported', 'error']

/**
 * Export: the Bill of Lading + Shipping Bill extraction tool, as a single
 * screen — upload, review/edit extracted fields (via onOpen), and export
 * Excel/PDF all live here. Every record shows together regardless of
 * whether it's been submitted yet; "Stage" is just a filter, not a
 * separate page, and submitting is an inline action on a row.
 *
 * Scoped to one Company Workspace when `companyId` is set (see
 * ExportWorkspace) — every upload and list query carries it. Scoped
 * further to one Vessel when `vesselId` is also set (Export's own Vessel
 * Workspace — see ExportVesselWorkspace), mirroring Import's Vessel
 * Workspace exactly; `onBulkUpload`, when given, adds the "bulk upload up
 * to ~400 at once" dropzone a vessel-scoped view offers alongside the
 * regular one-or-few-at-a-time upload button. A record uploaded before
 * Export required a company (company_id null) stays visible inside every
 * company rather than disappearing, so its row shows "Unassigned".
 */
export default function RecordsPage({
  onOpen, onOpenChild, onUpload, busy, companyId, companyName, onBackToCompanies,
  backLabel = '‹ All companies', vesselId, onBulkUpload, bulkBusy,
}) {
  const [rows, setRows] = useState([])
  const [sel, setSel] = useState(() => new Set())
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [docType, setDocType] = useState('')
  const [stage, setStage] = useState('') // '' = all, 'pending', 'submitted'
  const [counts, setCounts] = useState({ pending: 0, submitted: 0 })
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [limit, setLimit] = useState(25)
  const [fmt, setFmt] = useState('xlsx')
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')
  const [loading, setLoading] = useState(false)
  // A BL's Shipping Bills live inside its own entry: expand it to see them.
  const [openIds, setOpenIds] = useState(() => new Set())
  const [kids, setKids] = useState({})
  const [recon, setRecon] = useState({})
  const [linkBusyId, setLinkBusyId] = useState(null)

  const fetchKids = (id) =>
    api
      .getDoc(id)
      .then((d) => {
        setKids((k) => ({ ...k, [id]: d.linked_shipping_bills || [] }))
        setRecon((r) => ({ ...r, [id]: d.sb_reconciliation || null }))
      })
      .catch(() => {})

  async function uploadMissing(blId, files) {
    const pdfs = Array.from(files || []).filter((f) => /\.pdf$/i.test(f.name))
    if (pdfs.length === 0) return
    setLinkBusyId(blId)
    try {
      await api.linkShippingBills(blId, pdfs)
      setNote(`Uploaded ${pdfs.length} Shipping Bill(s).`)
      await fetchKids(blId)
      load(); loadCounts()
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setLinkBusyId(null)
    }
  }

  function toggleOpen(id) {
    const willOpen = !openIds.has(id)
    setOpenIds((prev) => {
      const n = new Set(prev)
      willOpen ? n.add(id) : n.delete(id)
      return n
    })
    if (willOpen) fetchKids(id)
  }

  const load = () => {
    setLoading(true)
    const submitted = stage === 'pending' ? false : stage === 'submitted' ? true : undefined
    api
      .recordsOverview(
        {
          q, status, doc_type: docType, date_from: from, date_to: to, limit, submitted,
          company_id: companyId, vessel_id: vesselId,
        },
        'export',
      )
      .then((r) => {
        setRows(r)
        setSel((prev) => new Set([...prev].filter((id) => r.some((x) => x.id === id))))
      })
      .catch((e) => setErr(String(e?.message || e)))
      .finally(() => setLoading(false))
  }

  useEffect(load, [q, status, docType, stage, from, to, limit, companyId, vesselId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Pending/Submitted counts for the tab bar — independent of which tab is
  // active, so switching tabs doesn't make the other tab's count disappear.
  const loadCounts = () => {
    const base = {
      q, status, doc_type: docType, date_from: from, date_to: to, limit: 2000,
      company_id: companyId, vessel_id: vesselId,
    }
    Promise.all([
      api.recordsOverview({ ...base, submitted: false }, 'export'),
      api.recordsOverview({ ...base, submitted: true }, 'export'),
    ])
      .then(([pending, submitted]) => setCounts({ pending: pending.length, submitted: submitted.length }))
      .catch(() => {})
  }
  useEffect(loadCounts, [q, status, docType, from, to, companyId, vesselId]) // eslint-disable-line react-hooks/exhaustive-deps

  // While anything is still extracting in the background, refresh periodically.
  const pending = rows.some((r) => r.status === 'queued' || r.status === 'processing')
  const kidsPending = [...openIds].some((id) =>
    (kids[id] || []).some((s) => SB_PENDING.has(s.status)),
  )
  useEffect(() => {
    if (!pending && !kidsPending) return
    const t = setInterval(() => {
      load()
      openIds.forEach(fetchKids)
    }, 4000)
    return () => clearInterval(t)
  }, [pending, kidsPending]) // eslint-disable-line react-hooks/exhaustive-deps

  const allChecked = rows.length > 0 && rows.every((r) => sel.has(r.id))
  const toggleAll = () => setSel(allChecked ? new Set() : new Set(rows.map((r) => r.id)))
  const toggle = (id) =>
    setSel((s) => {
      const n = new Set(s)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })

  const clearFilters = () => {
    setQ(''); setStatus(''); setDocType(''); setStage(''); setFrom(''); setTo(''); setLimit(25)
  }

  const selPending = [...sel].filter((id) => rows.find((r) => r.id === id)?.submitted === false)

  // A BL isn't ready to submit/download until every Shipping Bill it
  // references is uploaded, with no duplicate numbers left unresolved —
  // "validated" per the reconciliation already computed for this list.
  const isBlIncomplete = (r) =>
    r.doc_type === 'bill_of_lading' && (r.sb_missing_count > 0 || r.sb_duplicate_count > 0)
  const incompleteSel = [...sel]
    .map((id) => rows.find((r) => r.id === id))
    .filter((r) => r && isBlIncomplete(r))
  const incompleteBlockReason = incompleteSel.length > 0
    ? `${incompleteSel.length} selected Bill(s) of Lading still have missing or duplicate Shipping Bills — resolve those before submitting or downloading.`
    : ''

  async function submitSelected() {
    if (selPending.length === 0 || incompleteSel.length > 0) return
    try {
      const { submitted } = await api.submitRecords(selPending)
      setNote(`Submitted ${submitted} record(s).`)
      load(); loadCounts()
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  async function submitOne(r) {
    if (isBlIncomplete(r)) return
    try {
      await api.submitRecords([r.id])
      setNote('Submitted.')
      load(); loadCounts()
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  async function exportSelected() {
    if (sel.size === 0 || incompleteSel.length > 0) return
    try {
      const { blob, filename } = await api.exportRecordsSplit([...sel], fmt)
      downloadBlob(blob, filename)
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  async function deleteOne(r) {
    const label = r.doc_type === 'shipping_bill' ? 'Shipping Bill' : 'Bill of Lading'
    const extra = r.doc_type === 'shipping_bill'
      ? ' Any linked Bill(s) of Lading stay — only unlinked.'
      : ''
    if (!window.confirm(`Delete this ${label} (${r.filename})?${extra} You can re-upload it afterward.`)) return
    try {
      await api.deleteDocument(r.id)
      setNote(`${label} deleted.`)
      load(); loadCounts()
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  async function deleteKid(sbk, parentId) {
    if (!window.confirm(`Delete Shipping Bill ${sbk.sb_number || sbk.filename}?`)) return
    try {
      await api.deleteDocument(sbk.id)
      setNote('Shipping Bill deleted.')
      fetchKids(parentId)
      load()
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  async function deleteSelected() {
    if (sel.size === 0) return
    if (!window.confirm(
      `Delete ${sel.size} record(s)? Any Shipping Bill(s) among them only unlink their BL(s); Bill(s) of Lading are deleted outright. You can re-upload afterward.`,
    )) return
    try {
      const { deleted } = await api.bulkDeleteDocuments([...sel])
      setNote(`Deleted ${deleted.length} record(s).`)
      setSel(new Set())
      load(); loadCounts()
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  // one-click export straight from a row — no need to tick its checkbox and
  // use the selection bar above just to grab a single record. A Bill of
  // Lading goes through the same split export as the bulk toolbar (so it
  // gets the same up-to-date 3-file .zip — BL Data, BL + Shipping Bill,
  // Summary — instead of the older flat single-sheet file); a standalone
  // Shipping Bill (export-split requires a BL) keeps the plain .xlsx.
  async function exportOne(r) {
    if (isBlIncomplete(r)) return
    try {
      const { blob, filename } =
        r.doc_type === 'bill_of_lading'
          ? await api.exportRecordsSplit([r.id], 'xlsx')
          : await api.exportRecords([r.id], 'xlsx')
      downloadBlob(blob, filename)
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  const fmtDate = (s) => (s || '').slice(0, 10)

  return (
    <div className="records">
      <div className="page-head">
        <div>
          {onBackToCompanies && (
            <button className="link" onClick={onBackToCompanies}>{backLabel}</button>
          )}
          <h1>{companyName || 'Export'}</h1>
          <p className="muted sm">Upload a PDF, review the extracted fields, then export Excel or PDF.</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <label className={`btn ${busy ? 'disabled' : ''}`}>
            {busy ? 'Working…' : '↑ Upload PDF(s)'}
            <input
              type="file"
              accept="application/pdf"
              multiple
              hidden
              disabled={busy}
              onChange={(e) => e.target.files.length && Promise.resolve(onUpload(e.target.files, companyId, vesselId)).then(() => { load(); loadCounts() })}
            />
          </label>
          {onBulkUpload && (
            <label className={`btn ghost ${bulkBusy ? 'disabled' : ''}`} title="Upload up to ~400 BLs/Shipping Bills at once">
              {bulkBusy ? 'Uploading…' : '↑↑ Bulk Upload'}
              <input
                type="file"
                accept="application/pdf"
                multiple
                hidden
                disabled={bulkBusy}
                onChange={(e) => e.target.files.length && Promise.resolve(onBulkUpload([...e.target.files])).then(() => { load(); loadCounts() })}
              />
            </label>
          )}
        </div>
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

      <div className="filters">
        <label>Search
          <input placeholder="Job ID, BL number, file" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label>Type
          <select value={docType} onChange={(e) => setDocType(e.target.value)}>
            <option value="">All types</option>
            <option value="bill_of_lading">Bill of Lading</option>
            <option value="shipping_bill">Shipping Bill</option>
          </select>
        </label>
        <label>Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>From
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </label>
        <label>To
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} />
        </label>
        <label>Rows
          <select value={limit} onChange={(e) => setLimit(+e.target.value)}>
            {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n} rows</option>)}
          </select>
        </label>
        <button className="btn ghost sm" onClick={clearFilters}>✕ Clear</button>
      </div>

      {err && <div className="bar error">{err}</div>}
      {!err && note && <div className="bar ok">{note}</div>}

      {sel.size > 0 && (
        <div className="selbar">
          <span className="pill">{sel.size} selected</span>
          <span className="grow" />
          {incompleteBlockReason && (
            <span className="sb-pill bad" title={incompleteBlockReason}>⚠ {incompleteSel.length} incomplete</span>
          )}
          {selPending.length > 0 && (
            <button
              className="btn ghost sm"
              disabled={incompleteSel.length > 0}
              title={incompleteBlockReason}
              onClick={submitSelected}
            >
              ✓ Submit {selPending.length}
            </button>
          )}
          <select
            className="sel"
            value={fmt}
            onChange={(e) => setFmt(e.target.value)}
            title="Excel or PDF — either way the download is a .zip with three files: BL Data, BL + Shipping Bill, and Summary"
          >
            <option value="xlsx">Excel</option>
            <option value="pdf">PDF</option>
          </select>
          <button
            className="btn"
            disabled={incompleteSel.length > 0}
            title={incompleteBlockReason}
            onClick={exportSelected}
          >
            ↓ Download {fmt === 'xlsx' ? 'Excel' : 'PDF'} (.zip, {sel.size} BL{sel.size > 1 ? 's' : ''})
          </button>
          <button className="btn danger" onClick={deleteSelected}>
            🗑 Delete {sel.size}
          </button>
        </div>
      )}

      <table className="rec-table">
        <thead>
          <tr>
            <th className="cb"><input type="checkbox" checked={allChecked} onChange={toggleAll} /></th>
            <th>Job ID</th>
            <th>Doc Number</th>
            <th>Source File</th>
            <th>Type</th>
            <th>Company</th>
            <th>Stage</th>
            <th>Updated</th>
            <th>Status</th>
            <th className="right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && !loading && (
            <tr>
              <td colSpan={10} className="muted pad">Nothing here yet. Upload a PDF above.</td>
            </tr>
          )}
          {rows.map((r) => {
            const isOpen = openIds.has(r.id)
            const list = kids[r.id]
            const reconcile = recon[r.id]
            const incomplete = isBlIncomplete(r)
            const showToggle = r.linked_sb_count > 0 || r.sb_missing_count > 0
            const incompleteTitle = r.sb_missing_count > 0 && r.sb_duplicate_count > 0
              ? `${r.sb_missing_count} missing, ${r.sb_duplicate_count} duplicate Shipping Bill(s)`
              : r.sb_missing_count > 0
                ? `${r.sb_missing_count} Shipping Bill(s) not yet uploaded`
                : r.sb_duplicate_count > 0
                  ? `${r.sb_duplicate_count} duplicate Shipping Bill number(s)`
                  : ''
            return (
            <Fragment key={r.id}>
            <tr className={sel.has(r.id) ? 'on' : ''}>
              <td className="cb"><input type="checkbox" checked={sel.has(r.id)} onChange={() => toggle(r.id)} /></td>
              <td className="mono">{r.job_id}</td>
              <td className="mono">
                {r.doc_number || '—'}
                {showToggle && (
                  <div>
                    <button
                      className="sb-toggle"
                      aria-expanded={isOpen}
                      onClick={() => toggleOpen(r.id)}
                    >
                      {isOpen ? '▾' : '▸'} {r.linked_sb_count} Shipping Bill
                      {r.linked_sb_count === 1 ? '' : 's'}
                    </button>
                    {r.sb_missing_count > 0 && (
                      <span className="sb-pill bad" title="Shipping Bill numbers this BL references that haven't been uploaded yet">
                        {r.sb_missing_count} pending
                      </span>
                    )}
                    {r.sb_duplicate_count > 0 && (
                      <span className="sb-pill bad" title="The same Shipping Bill number was uploaded more than once">
                        {r.sb_duplicate_count} duplicate{r.sb_duplicate_count > 1 ? 's' : ''}
                      </span>
                    )}
                  </div>
                )}
              </td>
              <td className="fn" title={r.filename}>{r.filename}</td>
              <td>
                <span className={`chip sm ${r.doc_type === 'shipping_bill' ? 'sb' : 'blk'}`}>
                  {r.doc_type === 'shipping_bill' ? 'SB' : 'BL'}
                </span>
              </td>
              <td className="muted sm">{r.company_name || 'Unassigned'}</td>
              <td>
                <span className={`chip sm ${r.submitted ? 's-reviewed' : 'warn'}`}>
                  {r.submitted ? 'Submitted' : 'Pending'}
                </span>
              </td>
              <td>{fmtDate(r.updated_at)}</td>
              <td>
                <span className={`chip sm s-${r.status}`}>{r.status}</span>
                <div className="muted xs">{r.field_count} fields · {r.issue_count} issues</div>
              </td>
              <td className="right">
                <button className="link" onClick={() => onOpen(r.id)}>View ›</button>
                {!r.submitted && (
                  <button className="link" disabled={incomplete} title={incompleteTitle} onClick={() => submitOne(r)}>
                    ✓ Submit
                  </button>
                )}
                <button className="link" disabled={incomplete} title={incompleteTitle} onClick={() => exportOne(r)}>
                  ↓ Excel{r.doc_type === 'bill_of_lading' ? ' (.zip)' : ''}
                </button>
                <button className="link danger" onClick={() => deleteOne(r)}>Delete</button>
              </td>
            </tr>
            {isOpen && (
              <tr className="rec-kids">
                <td />
                <td colSpan={9}>
                  {reconcile && (
                    <div className="sb-reconcile">
                      <div className="sb-reconcile-summary">
                        <strong>{reconcile.total_referenced}</strong> Shipping Bill
                        {reconcile.total_referenced === 1 ? '' : 's'} referenced on this BL ·{' '}
                        <strong>{reconcile.total_uploaded}</strong> uploaded
                      </div>
                      {reconcile.missing_numbers.length === 0 && reconcile.duplicate_numbers.length === 0 && reconcile.unrelated_numbers.length === 0 && (
                        <div className="sb-reconcile-row ok">
                          ✓ Every referenced Shipping Bill is uploaded, with no duplicates or unrelated files.
                        </div>
                      )}
                      {reconcile.missing_numbers.length > 0 && (
                        <div className="sb-reconcile-row bad">
                          <strong>Missing ({reconcile.missing_numbers.length}):</strong> referenced on
                          this BL but not yet uploaded — {reconcile.missing_numbers.join(', ')}
                        </div>
                      )}
                      {reconcile.duplicate_numbers.length > 0 && (
                        <div className="sb-reconcile-row bad">
                          <strong>Duplicate ({reconcile.duplicate_numbers.length}):</strong> the same
                          Shipping Bill number was uploaded more than once — {reconcile.duplicate_numbers.join(', ')}
                        </div>
                      )}
                      {reconcile.unrelated_numbers.length > 0 && (
                        <div className="sb-reconcile-row bad">
                          <strong>Possibly incorrect upload ({reconcile.unrelated_numbers.length}):</strong>{' '}
                          uploaded but not among this BL's referenced numbers — {reconcile.unrelated_numbers.join(', ')}
                        </div>
                      )}
                    </div>
                  )}
                  {r.sb_missing_count > 0 && (
                    <label className={`btn ghost sm ${linkBusyId === r.id ? 'disabled' : ''}`} style={{ margin: '8px 0', display: 'inline-block' }}>
                      {linkBusyId === r.id ? 'Uploading…' : '↑ Upload missing Shipping Bill(s)'}
                      <input
                        type="file"
                        accept=".pdf,application/pdf"
                        multiple
                        hidden
                        disabled={linkBusyId === r.id}
                        onChange={(e) => {
                          const files = e.target.files
                          e.target.value = ''
                          uploadMissing(r.id, files)
                        }}
                      />
                    </label>
                  )}
                  <div className="kid-list">
                    {!list && <div className="muted sm">Loading…</div>}
                    {list?.map((sbk) => {
                      const [label, tone] = sbStatus(sbk.status)
                      return (
                        <div key={sbk.id} className="kid-row">
                          <span className="kid-tag">SB</span>
                          <div className="kid-main">
                            <div className="sb-name">{sbk.sb_number || sbk.filename}</div>
                            <div className="sb-meta">{sbMetaLine(sbk)}</div>
                          </div>
                          <span className={`sb-pill ${tone}`}>{label}</span>
                          <button className="link" onClick={() => onOpenChild?.(sbk.id, r)}>
                            View ›
                          </button>
                          <button className="link danger" onClick={() => deleteKid(sbk, r.id)}>
                            Delete
                          </button>
                        </div>
                      )
                    })}
                  </div>
                </td>
              </tr>
            )}
            </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
