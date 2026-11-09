import { useEffect, useMemo, useRef, useState } from 'react'
import { api, downloadBlob } from './api'

const DONE = new Set(['extracted', 'reviewed', 'exported', 'error'])

// Poll a document until extraction reaches a terminal state (scanned PDFs can
// take several minutes). onTick fires with every intermediate status.
async function pollDoc(id, onTick) {
  for (let i = 0; i < 300; i++) {
    const d = await api.getDoc(id)
    onTick?.(d)
    if (DONE.has(d.status)) return d
    await new Promise((r) => setTimeout(r, 3000))
  }
  return api.getDoc(id)
}
import PdfViewer from './components/PdfViewer'
import LinkedSb from './components/LinkedSb'
import Sidebar, { accessFor, categoryOf } from './components/Sidebar'
import ExportWorkspace from './components/ExportWorkspace'
import Login from './components/Login'
import CompanyMaster from './components/masters/CompanyMaster'
import UserMaster from './components/masters/UserMaster'
import RightsManagement from './components/masters/RightsManagement'
import ImportWorkspace from './components/ImportWorkspace'
import AnalyticsPage from './components/AnalyticsPage'

const confClass = (c) => (c >= 0.8 ? 'hi' : c >= 0.5 ? 'mid' : 'lo')
const sbNumberOf = (sb) =>
  sb?.fields?.find((f) => f.key === 'sb_number')?.value || sb?.filename || 'Shipping Bill'
const blNumberOf = (d) =>
  d?.fields?.find((f) => f.key === 'bl_number')?.value || d?.filename || 'Bill of Lading'

function docTypeLabel(doc) {
  if (doc.doc_type === 'shipping_bill') return 'Shipping Bill'
  const dt = doc.fields?.find((f) => f.key === 'document_type')?.value || ''
  if (/container/i.test(dt)) return 'Container BL'
  if (/break\s*bulk/i.test(dt)) return 'Break Bulk BL'
  return 'Bill of Lading'
}

export default function App() {
  const [user, setUser] = useState(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [doc, setDoc] = useState(null)
  const [edits, setEdits] = useState({})
  const [exportKeys, setExportKeys] = useState(() => new Set())
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')
  const [lowOnly, setLowOnly] = useState(false)
  const [fmt, setFmt] = useState('xlsx')
  const [templates, setTemplates] = useState([])
  const [uploadType] = useState('') // '' = auto-detect
  const [sb, setSb] = useState(null) // ShippingBillDetail context, if any
  const [uploadProgress, setUploadProgress] = useState(null) // { done, total } | null, while bulk-uploading SBs
  const [viewSbId, setViewSbId] = useState(null) // linked SB whose PDF is shown beside the BL
  const [fromBl, setFromBl] = useState(null) // { id, label } of the BL we left to edit one of its SBs
  const [view, setView] = useState('export') // 'export' | 'import' | 'review' | a master/admin screen key

  const openIdRef = useRef(null)
  useEffect(() => {
    openIdRef.current = doc?.id ?? null
  }, [doc])

  // Opening a different record starts by showing its own PDF. Coming "Back to
  // Bill of Lading" from editing one of its Shipping Bills reopens the
  // Shipping Bills card (LinkedSb reads this at mount, then it resets).
  const openSbRef = useRef(false)
  useEffect(() => {
    openSbRef.current = false
    setViewSbId(null)
  }, [doc?.id])

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true))
  }, [])

  // Whenever the logged-in user changes (login, or an admin edits someone's
  // rights mid-session on next load), land on a screen this login can
  // actually reach rather than a blank/forbidden one.
  useEffect(() => {
    if (!user) return
    const { canExport, canImport } = accessFor(user)
    const cat = categoryOf(view)
    if (cat === 'export' && !canExport) setView(canImport ? 'import' : 'no-access')
    else if (cat === 'import' && !canImport) setView(canExport ? 'export' : 'no-access')
  }, [user]) // eslint-disable-line react-hooks/exhaustive-deps

  async function onLogout() {
    try {
      await api.logout()
    } catch {
      /* best-effort — clear local state regardless */
    }
    setUser(null)
    setDoc(null)
    setFromBl(null)
    setView('export')
  }

  const refreshTemplates = () => api.templates().then(setTemplates).catch(() => {})
  useEffect(() => {
    if (user) refreshTemplates()
  }, [user])

  // Follow a background extraction and fold the finished data into the open doc.
  async function watchExtraction(id) {
    const final = await pollDoc(id, (d) => {
      if (openIdRef.current === d.id) {
        setDoc((c) => (c && c.id === d.id ? { ...c, status: d.status } : c))
      }
    })
    if (openIdRef.current === id) {
      if (final.status === 'error') {
        setDoc(final)
        setErr(final.warnings?.[0] || 'Extraction failed.')
      } else {
        seed(final, new Set(exportKeys))
        setNote(
          `Extraction complete — ${final.fields.filter((f) => f.value).length} fields found.`,
        )
        // refresh the Shipping Bill ↔ BL linkage now that auto-link has run
        try {
          if (final.doc_type === 'shipping_bill') {
            const s = await api.shippingBill(final.id)
            setSb(s)
            const n = s.linked_bls?.length || 0
            if (n) setNote(`Shipping Bill extracted — ${n} Bill(s) of Lading auto-linked.`)
          } else if (final.parent_id) {
            setSb(await api.shippingBill(final.parent_id))
            setNote('Bill of Lading extracted — auto-linked to its Shipping Bill.')
          }
        } catch {
          /* linkage refresh is best-effort */
        }
      }
    }
    return final
  }

  function seed(detail, keepExport) {
    setDoc(detail)
    setEdits(Object.fromEntries(detail.fields.map((f) => [f.key, f.value ?? ''])))
    const learned = detail.suggested_export_fields ?? []
    setExportKeys(
      keepExport ??
        new Set(
          learned.length
            ? learned
            : detail.fields
                .filter((f) => (f.value ?? '') !== '' && f.confidence >= 0.6)
                .map((f) => f.key),
        ),
    )
    if (learned.length && !keepExport) {
      setNote(`Applied your saved field selection for this BL format (${learned.length} fields).`)
    }
    setSelected(null)
  }

  async function onUpload(files, companyId, vesselId) {
    const list = Array.from(files)
    setBusy(true)
    setErr(null)
    setNote('')
    setDoc(null)
    setSb(null)
    setFromBl(null)
    try {
      // upload Shipping Bills first so BLs in the same batch auto-link on arrival
      const ordered = [...list].sort((a, b) =>
        /sb|shipping/i.test(b.name) - /sb|shipping/i.test(a.name),
      )
      const results = []
      for (const f of ordered) {
        results.push(
          await api.ingest(f, { docType: uploadType || undefined, background: true, companyId, vesselId }),
        )
      }

      const sbs = results.filter((d) => d.doc_type === 'shipping_bill')
      const bls = results.filter((d) => d.doc_type === 'bill_of_lading')

      if (results.length === 1) {
        const primary = results[0]
        seed(primary)
        const sbId =
          primary.doc_type === 'shipping_bill' ? primary.id : primary.parent_id
        setSb(sbId ? await api.shippingBill(sbId) : null)
        setView('review')
        setNote(
          `Detected ${primary.doc_type === 'shipping_bill' ? 'Shipping Bill' : 'Bill of Lading'} — ` +
            'extracting in the background. Large or scanned PDFs can take a few minutes.',
        )
        watchExtraction(primary.id) // no await — runs while the user waits
      } else {
        setNote(
          `Uploaded ${results.length}: ${sbs.length} Shipping Bill(s), ${bls.length} Bill(s) of ` +
            'Lading — extracting in the background. Records appear as each one finishes.',
        )
        results.forEach((r) => watchExtraction(r.id))
      }
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  // Import category: Master BL plain upload (no extraction yet — see
  // ImportWorkspace), scoped to the vessel whose workspace triggered it.
  async function onUploadMasterBl(files, vesselId) {
    setBusy(true)
    setErr(null)
    try {
      for (const f of Array.from(files)) {
        await api.upload(f, { docType: 'master_bl', vesselId })
      }
      setNote(`Uploaded ${files.length} Master BL(s).`)
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function onSubmitCurrent() {
    if (!doc) return
    setBusy(true)
    setErr(null)
    try {
      if (changed > 0) {
        const fields = doc.fields.map((f) => ({ key: f.key, value: edits[f.key] ?? '' }))
        seed(await api.saveFields(doc.id, fields), new Set(exportKeys))
      }
      await api.submitRecords([doc.id])
      setDoc(null)
      setSb(null)
      setFromBl(null)
      setView('export')
      setNote('Record submitted.')
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  // BL-first linking: upload one or more Shipping Bills (50+ supported) and
  // link them all straight to the open BL, regardless of whether their SB
  // numbers match anything. Each upload ADDS to the BL's linked set.
  async function watchLinkedSbs(blId, sbIds) {
    const pending = new Set(sbIds)
    for (let i = 0; i < 300 && pending.size; i++) {
      await new Promise((r) => setTimeout(r, 3000))
      let latest
      try {
        latest = await api.getDoc(blId)
      } catch {
        return
      }
      if (openIdRef.current === blId) setDoc(latest)
      for (const s of latest.linked_shipping_bills || []) {
        if (pending.has(s.id) && s.status !== 'queued' && s.status !== 'processing') {
          pending.delete(s.id)
        }
      }
    }
  }

  // Bulk uploads (50+ files) go in small batches rather than one giant
  // request: it gives visible progress, and a bad PDF in one batch doesn't
  // take down the other 45 files with it.
  const UPLOAD_BATCH_SIZE = 5

  async function linkShippingBillToBl(files) {
    if (!doc) return
    const blId = doc.id
    const list = Array.from(files)
    const beforeIds = new Set((doc.linked_shipping_bills || []).map((s) => s.id))
    setBusy(true)
    setErr(null)
    setUploadProgress({ done: 0, total: list.length })

    let latest = doc
    const failedFiles = []
    for (let i = 0; i < list.length; i += UPLOAD_BATCH_SIZE) {
      const batch = list.slice(i, i + UPLOAD_BATCH_SIZE)
      try {
        latest = await api.linkShippingBills(blId, batch, { background: true })
        // per-file failures inside an otherwise-successful batch (bad PDF, etc.)
        if (latest._failedFiles?.length) failedFiles.push(...latest._failedFiles)
      } catch (e) {
        // the whole batch request itself failed (network error, server down, ...)
        failedFiles.push(...batch.map((f) => f.name))
      }
      setUploadProgress({ done: Math.min(i + batch.length, list.length), total: list.length })
    }

    const newIds = (latest.linked_shipping_bills || [])
      .map((s) => s.id)
      .filter((id) => !beforeIds.has(id))
    if (openIdRef.current === blId) {
      setDoc(latest)
      const okCount = newIds.length
      if (failedFiles.length) {
        setErr(`${failedFiles.length} file(s) failed to upload: ${failedFiles.join(', ')}`)
        setNote(okCount ? `${okCount} Shipping Bill(s) linked successfully.` : '')
      } else {
        setNote(
          okCount <= 1
            ? 'Shipping Bill uploaded and linked — extracting in the background…'
            : `${okCount} Shipping Bills uploaded and linked — extracting in the background…`,
        )
      }
    }
    if (newIds.length) watchLinkedSbs(blId, newIds) // no await — runs while the user waits

    setUploadProgress(null)
    setBusy(false)
  }

  async function linkExistingSbToBl(sbId) {
    if (!doc) return
    setBusy(true)
    setErr(null)
    try {
      const updated = await api.linkExistingSb(doc.id, [sbId])
      setDoc(updated)
      setNote('Linked to the existing Shipping Bill.')
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  // Edit one of this BL's Shipping Bills on its own record page, with a
  // "Back to Bill of Lading" crumb so the user never loses their place.
  function editLinkedSb(sbId) {
    if (!doc) return
    setFromBl({ id: doc.id, label: blNumberOf(doc) })
    openDoc(sbId, { keepSb: true, keepFrom: true })
  }

  // Same, but starting from a Shipping Bill listed inside a BL's entry on the
  // Uploaded/Submitted Data page.
  function openNestedSb(sbId, bl) {
    setFromBl({ id: bl.id, label: bl.doc_number || bl.filename })
    openDoc(sbId, { keepSb: true, keepFrom: true })
  }

  function backToBl() {
    if (!fromBl) return
    const id = fromBl.id
    setFromBl(null)
    openSbRef.current = true
    openDoc(id)
  }

  async function unlinkSbFromBl(sbId) {
    if (!doc) return
    setBusy(true)
    setErr(null)
    if (viewSbId === sbId) setViewSbId(null)
    try {
      const updated = await api.unlinkSb(doc.id, sbId)
      setDoc(updated)
      setNote('Shipping Bill removed from this Bill of Lading.')
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function onExportBlWithSb(fmt) {
    if (!doc) return
    setBusy(true)
    setErr(null)
    try {
      const { blob, filename } = await api.exportBlWithSb(doc.id, { fmt })
      downloadBlob(blob, filename)
      setNote(`Exported ${filename}.`)
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function openDoc(id, { keepSb = false, keepFrom = false } = {}) {
    setBusy(true)
    setErr(null)
    setNote('')
    setView('review')
    if (!keepFrom) setFromBl(null)
    try {
      const detail = await api.getDoc(id)
      seed(detail)
      if (!DONE.has(detail.status)) {
        setNote('Extraction still running — this page will update when it finishes.')
        watchExtraction(id)
      }
      if (!keepSb) {
        setSb(
          detail.doc_type === 'shipping_bill'
            ? await api.shippingBill(id)
            : detail.parent_id
              ? await api.shippingBill(detail.parent_id)
              : null,
        )
      } else if (detail.doc_type === 'shipping_bill') {
        setSb(await api.shippingBill(id))
      }
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function onReExtract() {
    if (!doc) return
    setErr(null)
    try {
      const d = await api.extract(doc.id, { background: true })
      setDoc((c) => (c ? { ...c, status: d.status } : c))
      setNote('Re-running extraction…')
      watchExtraction(doc.id)
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  async function onSave() {
    if (!doc) return
    setBusy(true)
    setErr(null)
    try {
      const fields = doc.fields.map((f) => ({ key: f.key, value: edits[f.key] ?? '' }))
      const detail = await api.saveFields(doc.id, fields)
      seed(detail, new Set(exportKeys))
      setNote('Saved. Corrections logged for every changed field.')
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  async function onSaveSelection() {
    const name = window.prompt('Name this export field selection:')
    if (!name) return
    try {
      await api.saveTemplate({
        name,
        selected_fields: [...exportKeys],
        format_fingerprint: doc?.format_fingerprint ?? null,
        output_type: fmt,
      })
      await refreshTemplates()
      setNote(`Export template "${name}" saved (${exportKeys.size} fields).`)
    } catch (e) {
      setErr(String(e?.message || e))
    }
  }

  function onApplyTemplate(id) {
    const t = templates.find((x) => x.id === id)
    if (t) {
      setExportKeys(new Set(t.selected_fields))
      setNote(`Applied "${t.name}" — ${t.selected_fields.length} fields selected.`)
    }
  }

  async function onExport() {
    if (!doc || exportKeys.size === 0) return
    setBusy(true)
    setErr(null)
    try {
      if (changed > 0) {
        const fields = doc.fields.map((f) => ({ key: f.key, value: edits[f.key] ?? '' }))
        seed(await api.saveFields(doc.id, fields), new Set(exportKeys))
      }
      const { blob, filename } = await api.exportDoc(doc.id, {
        fmt,
        fields: [...exportKeys],
      })
      downloadBlob(blob, filename)
      setNote(`Exported ${filename} (${exportKeys.size} fields).`)
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBusy(false)
    }
  }

  const changed = useMemo(() => {
    if (!doc) return 0
    return doc.fields.filter((f) => (edits[f.key] ?? '') !== (f.value ?? '')).length
  }, [doc, edits])

  const visible = doc ? doc.fields.filter((f) => !lowOnly || f.confidence < 0.8) : []

  function toggleExport(key, on) {
    const s = new Set(exportKeys)
    on ? s.add(key) : s.delete(key)
    setExportKeys(s)
  }

  if (!authChecked) return null
  if (!user) return <Login onLoggedIn={setUser} />

  return (
    <div className="shell">
      <Sidebar view={view} onNav={setView} user={user} onLogout={onLogout} />

      <div className="content">
        {view === 'export' ? (
          <ExportWorkspace
            onOpen={(id) => openDoc(id)}
            onOpenChild={openNestedSb}
            onUpload={onUpload}
            busy={busy}
          />
        ) : view === 'import' ? (
          <ImportWorkspace currentUser={user} busy={busy} onUpload={onUploadMasterBl} />
        ) : view === 'export-analytics' ? (
          <AnalyticsPage currentUser={user} category="export" />
        ) : view === 'import-analytics' ? (
          <AnalyticsPage currentUser={user} category="import" />
        ) : view === 'company-master' ? (
          user.role === 'admin'
            ? <CompanyMaster />
            : accessFor(user).canExport
              ? <ExportWorkspace onOpen={(id) => openDoc(id)} onOpenChild={openNestedSb} onUpload={onUpload} busy={busy} />
              : <ImportWorkspace currentUser={user} busy={busy} onUpload={onUploadMasterBl} />
        ) : view === 'user-master' ? (
          <UserMaster currentUser={user} />
        ) : view === 'rights-management' ? (
          <RightsManagement currentUser={user} />
        ) : view === 'no-access' ? (
          <div className="records">
            <div className="empty">
              <p className="muted">
                Your account has no Export or Import access yet — ask an Admin to assign rights
                in Rights Management.
              </p>
            </div>
          </div>
        ) : (
          <>
            <header className="topbar review-head">
              <button
                className="btn ghost sm"
                onClick={() => setView('export')}
              >
                ‹ Back
              </button>
              {doc && (
                <div className="docmeta">
                  <span className={`chip ${doc.doc_type === 'shipping_bill' ? 'sb' : 'blk'}`}>
                    {docTypeLabel(doc)}
                  </span>
                  <strong title={doc.filename}>{doc.filename}</strong>
                  <span className={`chip s-${doc.status}`}>{doc.status}</span>
                  {doc.has_scanned_pages && <span className="chip warn">scanned</span>}
                </div>
              )}
              <div className="spacer" />
              {doc && (
                <>
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={lowOnly}
                      onChange={(e) => setLowOnly(e.target.checked)}
                    />
                    low-confidence only
                  </label>
                  {['uploaded', 'queued', 'processing', 'error'].includes(doc.status) && (
                    <button
                      className="btn"
                      disabled={busy || doc.status === 'queued' || doc.status === 'processing'}
                      onClick={onReExtract}
                    >
                      ↻ Re-run
                    </button>
                  )}
                  <button className="btn" disabled={busy || !changed} onClick={onSave}>
                    Save{changed ? ` (${changed})` : ''}
                  </button>
                  {!doc.submitted && (
                    <button className="btn ok" disabled={busy} onClick={onSubmitCurrent}>
                      ✓ Submit
                    </button>
                  )}
                </>
              )}
            </header>

            {doc && (
              <div className="subbar">
                <span className="subbar-l">Export</span>
                {templates.length > 0 && (
                  <select
                    className="sel"
                    defaultValue=""
                    onChange={(e) => {
                      onApplyTemplate(e.target.value)
                      e.target.value = ''
                    }}
                  >
                    <option value="" disabled>Apply saved selection…</option>
                    {templates.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name} ({t.selected_fields.length})
                      </option>
                    ))}
                  </select>
                )}
                <button
                  className="btn ghost sm"
                  disabled={busy || exportKeys.size === 0}
                  onClick={onSaveSelection}
                >
                  Save selection ({exportKeys.size})
                </button>
                <span className="grow" />
                <select className="sel" value={fmt} onChange={(e) => setFmt(e.target.value)}>
                  <option value="xlsx">Excel</option>
                  <option value="pdf">PDF</option>
                </select>
                <button
                  className="btn"
                  disabled={busy || exportKeys.size === 0}
                  onClick={onExport}
                >
                  Export ({exportKeys.size})
                </button>
              </div>
            )}

            {fromBl && doc && doc.id !== fromBl.id && (
              <div className="bar crumb">
                <button className="link" onClick={backToBl}>
                  ‹ Back to Bill of Lading {fromBl.label}
                </button>
                <span className="muted"> / {doc.filename}</span>
              </div>
            )}
            {!fromBl && sb && doc && doc.id !== sb.id && (
              <div className="bar crumb">
                <button className="link" onClick={() => openDoc(sb.id, { keepSb: true })}>
                  ‹ Shipping Bill {sbNumberOf(sb)}
                </button>
                <span className="muted"> / {doc.filename}</span>
              </div>
            )}
            {err && <div className="bar error">{err}</div>}
            {!err && note && <div className="bar ok">{note}</div>}
            {doc?.warnings?.length > 0 && (
              <div className="bar warn">
                {doc.warnings.map((w, i) => (
                  <div key={i}>⚠ {w}</div>
                ))}
              </div>
            )}

            <main className="main">
              {doc ? (
                <div className="workarea">
                  <section className="fields">
                    <div className="fields-scroll">
                      {doc.doc_type === 'bill_of_lading' && (
                        <LinkedSb
                          key={doc.id}
                          doc={doc}
                          busy={busy}
                          uploadProgress={uploadProgress}
                          viewSbId={viewSbId}
                          initiallyOpen={openSbRef.current}
                          onView={setViewSbId}
                          onLink={linkShippingBillToBl}
                          onLinkExisting={linkExistingSbToBl}
                          onUnlink={unlinkSbFromBl}
                          onExport={onExportBlWithSb}
                          onEditSb={editLinkedSb}
                        />
                      )}
                      <GroupedRows
                        fields={visible}
                        edits={edits}
                        exportKeys={exportKeys}
                        selected={selected}
                        onSelect={setSelected}
                        onEdit={(key, value) => setEdits((prev) => ({ ...prev, [key]: value }))}
                        onToggleExport={toggleExport}
                      />
                    </div>
                  </section>
                  <section className="pdf">
                    {viewSbId && (
                      <div className="pdf-banner">
                        <span>
                          Showing Shipping Bill{' '}
                          <strong>
                            {(() => {
                              const v = doc.linked_shipping_bills?.find((l) => l.id === viewSbId)
                              return v?.sb_number || v?.filename || ''
                            })()}
                          </strong>
                        </span>
                        <button className="link" onClick={() => setViewSbId(null)}>
                          Show Bill of Lading
                        </button>
                      </div>
                    )}
                    <PdfViewer
                      fileUrl={api.fileUrl(viewSbId ?? doc.id)}
                      selected={viewSbId ? null : selected}
                    />
                  </section>
                </div>
              ) : (
                <div className="empty">
                  <p className="muted">{busy ? 'Working…' : 'Select a record from the list.'}</p>
                </div>
              )}
            </main>
          </>
        )}
      </div>
    </div>
  )
}

function GroupedRows({ fields, edits, exportKeys, selected, onSelect, onEdit, onToggleExport }) {
  const out = []
  let lastGroup = null
  for (const f of fields) {
    if (f.group !== lastGroup) {
      out.push(
        <div className="grouphdr" key={`g-${f.group}`}>
          {f.group}
        </div>,
      )
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
          <input
            type="checkbox"
            checked={exportKeys.has(f.key)}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => onToggleExport(f.key, e.target.checked)}
          />
          <span className="label">{f.label}</span>
          <span
            className={`badge ${f.source === 'user' ? 'user' : confClass(f.confidence)}`}
          >
            {f.source === 'user'
              ? '✓ edited'
              : f.confidence
                ? `${Math.round(f.confidence * 100)}%`
                : '—'}
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
