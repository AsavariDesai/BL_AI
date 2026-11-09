import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { SB_PENDING, sbMetaLine, sbStatus } from '../sbUtil'

const isFlagged = (lsb) => lsb.is_duplicate || lsb.sb_number_match === false

// numeric ascending by SB number; a missing/non-numeric number sorts last
// within its group rather than breaking the ordering.
const sbSortKey = (lsb) => {
  const n = parseInt(lsb.sb_number, 10)
  return Number.isFinite(n) ? n : Infinity
}

function compareSbRows(a, b) {
  const aFlagged = isFlagged(a)
  const bFlagged = isFlagged(b)
  if (aFlagged !== bFlagged) return aFlagged ? -1 : 1
  const diff = sbSortKey(a) - sbSortKey(b)
  if (diff !== 0) return diff
  return (a.filename || '').localeCompare(b.filename || '')
}

/**
 * Everything about a Bill of Lading's Shipping Bills, in ONE expandable card:
 *
 *   ▸ Shipping Bills  [3]  2 being read…            [ + Add Shipping Bills ]
 *
 * The header always shows the count and a one-click Add button. Expanding it
 * reveals a drag-and-drop box, the full list of linked Shipping Bills (click
 * one to see its PDF beside the BL), and a single Download control.
 */
export default function LinkedSb({
  doc, busy, uploadProgress, viewSbId, initiallyOpen,
  onView, onLink, onLinkExisting, onUnlink, onExport, onEditSb,
}) {
  const [open, setOpen] = useState(!!initiallyOpen)
  const [picker, setPicker] = useState(false)
  const [unlinked, setUnlinked] = useState([])
  const [query, setQuery] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [dropNote, setDropNote] = useState('')
  const [checked, setChecked] = useState(() => new Set())
  const selectAllRef = useRef(null)

  const linked = doc.linked_shipping_bills ?? []
  const reading = linked.filter((l) => SB_PENDING.has(l.status)).length
  const failed = linked.filter((l) => l.status === 'error').length
  const mismatched = linked.filter((l) => l.sb_number_match === false).length
  const reconcile = doc.sb_reconciliation
  const missingCount = reconcile?.missing_numbers?.length ?? 0
  const duplicateCount = reconcile?.duplicate_numbers?.length ?? 0
  const unrelatedCount = reconcile?.unrelated_numbers?.length ?? 0
  const countDiff = reconcile ? reconcile.total_uploaded - reconcile.total_referenced : 0

  // an upload in progress is what the user wants to watch — show it
  useEffect(() => {
    if (uploadProgress) setOpen(true)
  }, [uploadProgress])

  useEffect(() => {
    if (picker) refreshUnlinked()
  }, [picker])

  function refreshUnlinked() {
    api
      .listDocs({ doc_type: 'shipping_bill', unlinked: 'true', limit: 100 })
      .then((rows) => setUnlinked(rows.filter((d) => !linked.some((l) => l.id === d.id))))
      .catch(() => setUnlinked([]))
  }

  function pick(id) {
    onLinkExisting(id)
    setUnlinked((rows) => rows.filter((d) => d.id !== id))
  }

  function accept(fileList) {
    const all = Array.from(fileList || [])
    const pdfs = all.filter((f) => /\.pdf$/i.test(f.name))
    const skipped = all.length - pdfs.length
    setDropNote(skipped ? `${skipped} file(s) skipped — only PDF files can be added.` : '')
    if (pdfs.length) onLink(pdfs)
  }

  function onDrop(e) {
    e.preventDefault()
    setDragOver(false)
    if (!busy) accept(e.dataTransfer.files)
  }

  function remove(lsb) {
    const name = lsb.sb_number || lsb.filename
    if (
      window.confirm(
        `Remove Shipping Bill ${name} from this Bill of Lading?\n\nThe file itself is not deleted.`,
      )
    ) {
      onUnlink(lsb.id)
    }
  }

  function toggleCheck(id) {
    setChecked((prev) => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }

  // Selects/clears every row currently visible (respects the search filter)
  // rather than every linked Shipping Bill, so "Select all" matches what the
  // user can actually see on screen.
  function toggleSelectAll() {
    setChecked((prev) => {
      const n = new Set(prev)
      const allShownChecked = shown.length > 0 && shown.every((l) => n.has(l.id))
      shown.forEach((l) => (allShownChecked ? n.delete(l.id) : n.add(l.id)))
      return n
    })
  }

  // removing several at once still goes through the same one-at-a-time
  // unlink call, sequentially (the backend has no bulk-unlink endpoint) —
  // awaiting each keeps the BL's state update race-free.
  async function removeSelected() {
    const ids = [...checked].filter((id) => linked.some((l) => l.id === id))
    if (ids.length === 0) return
    if (
      !window.confirm(
        `Remove ${ids.length} Shipping Bill${ids.length > 1 ? 's' : ''} from this Bill of Lading?\n\nThe files themselves are not deleted.`,
      )
    ) {
      return
    }
    for (const id of ids) {
      await onUnlink(id)
    }
    setChecked(new Set())
  }

  const q = query.trim().toLowerCase()
  const filtered = q
    ? linked.filter((l) => `${l.sb_number || ''} ${l.filename}`.toLowerCase().includes(q))
    : linked
  // Red-flagged rows (duplicate upload or a number the BL doesn't reference)
  // surface first, ascending by Shipping Bill number, so the issues needing
  // attention are seen immediately instead of scattered through the list —
  // the rest follow, same ascending order.
  const shown = [...filtered].sort(compareSbRows)
  const checkedCount = [...checked].filter((id) => linked.some((l) => l.id === id)).length
  const allShownChecked = shown.length > 0 && shown.every((l) => checked.has(l.id))
  const someShownChecked = shown.some((l) => checked.has(l.id))

  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = someShownChecked && !allShownChecked
    }
  }, [someShownChecked, allShownChecked])

  return (
    <div className={`sbcard ${open ? 'open' : ''}`}>
      <div
        className="sbcard-head"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setOpen((o) => !o)
          }
        }}
      >
        <span className="sbcard-chev" aria-hidden="true">{open ? '▾' : '▸'}</span>
        <span className="sbcard-title">Shipping Bills</span>
        <span className="sbcard-count">{linked.length}</span>
        {linked.length === 0 && <span className="sbcard-hint">none added yet</span>}
        {reading > 0 && <span className="sb-pill busy">{reading} being read…</span>}
        {failed > 0 && <span className="sb-pill bad">{failed} failed</span>}
        {mismatched > 0 && (
          <span className="sb-pill bad" title="Shipping Bill number doesn't match the BL's own reference">
            {mismatched} Keyword Mismatch{mismatched > 1 ? 'es' : ''}
          </span>
        )}
        {missingCount > 0 && (
          <span
            className="sb-pill bad"
            title="Shipping Bill numbers the BL references that haven't been uploaded yet"
          >
            {missingCount} not uploaded
          </span>
        )}
        {duplicateCount > 0 && (
          <span
            className="sb-pill bad"
            title="The same Shipping Bill number was uploaded more than once"
          >
            {duplicateCount} duplicate{duplicateCount > 1 ? 's' : ''}
          </span>
        )}
        <span className="sbcard-grow" />
        <label
          className={`btn sm ${busy ? 'disabled' : ''}`}
          onClick={(e) => e.stopPropagation()}
        >
          + Add Shipping Bills
          <input
            type="file"
            accept=".pdf,application/pdf"
            multiple
            className="sr-only"
            disabled={busy}
            onChange={(e) => {
              accept(e.target.files)
              e.target.value = ''
            }}
          />
        </label>
      </div>

      {open && (
        <div className="sbcard-body">
          {reconcile && (
            <div className="sb-reconcile">
              <div className="sb-reconcile-summary">
                <strong>{reconcile.total_referenced}</strong> Shipping Bill
                {reconcile.total_referenced === 1 ? '' : 's'} referenced on this BL ·{' '}
                <strong>{reconcile.total_uploaded}</strong> uploaded
                {countDiff !== 0 && (
                  <span className="sb-reconcile-diff">
                    {' '}({countDiff > 0 ? `${countDiff} excess` : `${-countDiff} short`})
                  </span>
                )}
              </div>
              {missingCount === 0 && duplicateCount === 0 && unrelatedCount === 0 && (
                <div className="sb-reconcile-row ok">
                  ✓ Every referenced Shipping Bill is uploaded, with no duplicates or unrelated files.
                </div>
              )}
              {missingCount > 0 && (
                <div className="sb-reconcile-row bad">
                  <strong>Missing ({missingCount}):</strong> referenced on this BL but not yet
                  uploaded — {reconcile.missing_numbers.join(', ')}
                </div>
              )}
              {duplicateCount > 0 && (
                <div className="sb-reconcile-row bad">
                  <strong>Duplicate ({duplicateCount}):</strong> the same Shipping Bill number was
                  uploaded more than once — {reconcile.duplicate_numbers.join(', ')}
                </div>
              )}
              {unrelatedCount > 0 && (
                <div className="sb-reconcile-row bad">
                  <strong>Possibly incorrect upload ({unrelatedCount}):</strong> uploaded but not
                  among this BL's referenced numbers — {reconcile.unrelated_numbers.join(', ')}
                </div>
              )}
            </div>
          )}
          {uploadProgress ? (
            <div className="dropzone uploading">
              <div className="dz-title">
                Uploading {uploadProgress.done} of {uploadProgress.total}…
              </div>
              <div className="upload-progress-bar">
                <div
                  className="upload-progress-fill"
                  style={{ width: `${(100 * uploadProgress.done) / uploadProgress.total}%` }}
                />
              </div>
              <div className="dz-sub">Please keep this page open until the upload finishes.</div>
            </div>
          ) : (
            <label
              className={`dropzone ${dragOver ? 'over' : ''} ${busy ? 'disabled' : ''}`}
              onDragOver={(e) => { e.preventDefault(); if (!busy) setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
            >
              <input
                type="file"
                accept=".pdf,application/pdf"
                multiple
                className="sr-only"
                disabled={busy}
                onChange={(e) => {
                  accept(e.target.files)
                  e.target.value = ''
                }}
              />
              <div className="dz-title">Drag &amp; drop Shipping Bill PDFs here</div>
              <div className="dz-sub">
                or <span className="dz-link">click to choose files</span> · 50 or more at once is fine
              </div>
            </label>
          )}
          {dropNote && <div className="sm sb-warn">{dropNote}</div>}

          <div className="sb-existing">
            <button className="link" disabled={busy} onClick={() => setPicker((v) => !v)}>
              {picker ? 'Hide list' : 'Uploaded some earlier? Add them from a list'}
            </button>
          </div>
          {picker && (
            <div className="picker">
              {unlinked.length === 0 && (
                <div className="muted sm">No other Shipping Bills are waiting to be linked.</div>
              )}
              {unlinked.map((d) => (
                <div key={d.id} className="picker-row">
                  <span className="fn">{d.filename}</span>
                  <button className="btn xs" disabled={busy} onClick={() => pick(d.id)}>
                    Add
                  </button>
                </div>
              ))}
            </div>
          )}

          {linked.length > 0 && (
            <>
              {linked.length > 6 && (
                <input
                  className="sb-search"
                  type="search"
                  placeholder="Search by Shipping Bill number…"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                />
              )}

              <div className={`selbar ${checkedCount > 0 ? '' : 'idle'}`}>
                <label className="selbar-all">
                  <input
                    type="checkbox"
                    ref={selectAllRef}
                    checked={allShownChecked}
                    disabled={busy || shown.length === 0}
                    onChange={toggleSelectAll}
                  />
                  Select all{shown.length > 0 ? ` (${shown.length})` : ''}
                </label>
                {checkedCount > 0 && (
                  <>
                    <span className="pill">{checkedCount} selected</span>
                    <span className="grow" />
                    <button className="btn ghost sm" disabled={busy} onClick={() => setChecked(new Set())}>
                      Clear
                    </button>
                    <button className="btn danger sm" disabled={busy} onClick={removeSelected}>
                      Remove selected
                    </button>
                  </>
                )}
              </div>

              <div className="sb-list">
                {shown.map((lsb) => {
                  const [label, tone] = sbStatus(lsb.status)
                  const viewing = viewSbId === lsb.id
                  // Row-level flag: red for a duplicate upload or a number
                  // the BL never references (unrelated/excess), green for a
                  // clean single match — recomputed from the BL's current
                  // state every time, so removing one of a duplicate pair
                  // automatically turns the remaining row green again.
                  const flag = isFlagged(lsb) ? 'flag-bad' : lsb.sb_number_match === true ? 'flag-good' : ''
                  return (
                    <div
                      key={lsb.id}
                      className={`sb-row ${viewing ? 'viewing' : ''} ${flag}`}
                      onClick={() => onView(viewing ? null : lsb.id)}
                      title="Click to see this Shipping Bill's PDF on the right"
                    >
                      <input
                        type="checkbox"
                        className="sb-check"
                        checked={checked.has(lsb.id)}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => toggleCheck(lsb.id)}
                      />
                      <div className="sb-main">
                        <div className="sb-name">{lsb.sb_number || lsb.filename}</div>
                        <div className="sb-meta">{sbMetaLine(lsb)}</div>
                      </div>
                      {lsb.is_duplicate && (
                        <span
                          className="sb-pill bad"
                          title="This Shipping Bill number was uploaded more than once — remove the extra copy"
                        >
                          Duplicate
                        </span>
                      )}
                      {!lsb.is_duplicate && lsb.sb_number_match === true && (
                        <span
                          className="sb-pill ok"
                          title="This Shipping Bill's number matches the BL's own Shipping Bill No. & Date field"
                        >
                          Keyword Match
                        </span>
                      )}
                      {!lsb.is_duplicate && lsb.sb_number_match === false && (
                        <span
                          className="sb-pill bad"
                          title="This Shipping Bill's number doesn't appear in the BL's own Shipping Bill No. & Date field — double-check it belongs here"
                        >
                          Keyword Mismatch
                        </span>
                      )}
                      <span className={`sb-pill ${tone}`}>{label}</span>
                      <div className="sb-actions">
                        <button
                          className="link"
                          disabled={busy}
                          onClick={(e) => { e.stopPropagation(); onEditSb(lsb.id) }}
                        >
                          Edit
                        </button>
                        <button
                          className="link danger"
                          disabled={busy}
                          onClick={(e) => { e.stopPropagation(); remove(lsb) }}
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  )
                })}
                {shown.length === 0 && (
                  <div className="sb-empty">No Shipping Bill matches “{query}”.</div>
                )}
              </div>

              <div className="sb-download">
                <span className="sb-download-label">Download this BL with all its Shipping Bills:</span>
                <button className="btn" disabled={busy} onClick={() => onExport('xlsx')}>
                  Excel
                </button>
                <button className="btn ghost" disabled={busy} onClick={() => onExport('pdf')}>
                  PDF
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
