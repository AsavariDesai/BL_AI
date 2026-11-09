import { useEffect, useRef, useState } from 'react'

const isFlagged = (h) => h.has_duplicate_container || h.has_unrelated_container

function compareHouseRows(a, b) {
  const aFlagged = isFlagged(a)
  const bFlagged = isFlagged(b)
  if (aFlagged !== bFlagged) return aFlagged ? -1 : 1
  return (a.filename || '').localeCompare(b.filename || '')
}

/**
 * Everything about a Master BL's House BLs, in ONE expandable card — the
 * Import counterpart of Export's LinkedSb:
 *
 *   ▸ House BLs  [3]  2 being read…            [ + Add House BL(s) ]
 *
 * The header always shows the count and a one-click Add button (single or
 * bulk — one file input, same as Export's own). Expanding it reveals the
 * container reconciliation summary, a drag-and-drop box, and the full list
 * of linked House BLs (click one to see its PDF beside the Master).
 */
export default function LinkedHouse({
  doc, busy, viewHouseId, initiallyOpen = true,
  onView, onLink, onUnlink, onDelete,
}) {
  const [open, setOpen] = useState(!!initiallyOpen)
  const [query, setQuery] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const [dropNote, setDropNote] = useState('')
  const [checked, setChecked] = useState(() => new Set())
  const selectAllRef = useRef(null)

  const linked = doc.linked_house_bls ?? []
  const reading = linked.filter((h) => ['queued', 'processing'].includes(h.status)).length
  const failed = linked.filter((h) => h.status === 'error').length
  const reconcile = doc.container_reconciliation
  const missingCount = reconcile?.missing_containers?.length ?? 0
  const duplicateCount = reconcile?.duplicate_containers?.length ?? 0
  const unrelatedCount = reconcile?.unrelated_containers?.length ?? 0
  const countDiff = reconcile ? reconcile.total_uploaded - reconcile.total_master : 0

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

  function unlink(h) {
    if (window.confirm(`Unlink House BL "${h.filename}" from this Master BL?\n\nThe file itself is not deleted.`)) {
      onUnlink(h.id)
    }
  }

  function remove(h) {
    onDelete(h.id, h.filename)
  }

  function toggleCheck(id) {
    setChecked((prev) => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }

  function toggleSelectAll() {
    setChecked((prev) => {
      const n = new Set(prev)
      const allShownChecked = shown.length > 0 && shown.every((h) => n.has(h.id))
      shown.forEach((h) => (allShownChecked ? n.delete(h.id) : n.add(h.id)))
      return n
    })
  }

  async function removeSelected() {
    const ids = [...checked].filter((id) => linked.some((h) => h.id === id))
    if (ids.length === 0) return
    if (
      !window.confirm(
        `Delete ${ids.length} House BL${ids.length > 1 ? 's' : ''}? You can re-upload ${ids.length > 1 ? 'them' : 'it'} here afterward.`,
      )
    ) {
      return
    }
    for (const id of ids) {
      await onDelete(id)
    }
    setChecked(new Set())
  }

  const q = query.trim().toLowerCase()
  const filtered = q
    ? linked.filter((h) => `${(h.container_numbers || []).join(' ')} ${h.filename}`.toLowerCase().includes(q))
    : linked
  // Red-flagged rows (duplicate or unrelated container) surface first, so
  // the issues needing attention are seen immediately.
  const shown = [...filtered].sort(compareHouseRows)
  const checkedCount = [...checked].filter((id) => linked.some((h) => h.id === id)).length
  const allShownChecked = shown.length > 0 && shown.every((h) => checked.has(h.id))
  const someShownChecked = shown.some((h) => checked.has(h.id))

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
        <span className="sbcard-title">House BLs</span>
        <span className="sbcard-count">{linked.length}</span>
        {linked.length === 0 && <span className="sbcard-hint">none added yet</span>}
        {reading > 0 && <span className="sb-pill busy">{reading} being read…</span>}
        {failed > 0 && <span className="sb-pill bad">{failed} failed</span>}
        {missingCount > 0 && (
          <span
            className="sb-pill bad"
            title="Container numbers on the Master BL that haven't turned up on any House BL"
          >
            {missingCount} not uploaded
          </span>
        )}
        {duplicateCount > 0 && (
          <span
            className="sb-pill bad"
            title="The same container number appears on more than one House BL"
          >
            {duplicateCount} duplicate{duplicateCount > 1 ? 's' : ''}
          </span>
        )}
        <span className="sbcard-grow" />
        <label
          className={`btn sm ${busy ? 'disabled' : ''}`}
          onClick={(e) => e.stopPropagation()}
        >
          + Add House BL(s)
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
                <strong>{reconcile.total_master}</strong> container{reconcile.total_master === 1 ? '' : 's'} on
                this Master BL ·{' '}
                <strong>{reconcile.total_uploaded}</strong> found on House BL(s)
                {countDiff !== 0 && (
                  <span className="sb-reconcile-diff">
                    {' '}({countDiff > 0 ? `${countDiff} excess` : `${-countDiff} short`})
                  </span>
                )}
              </div>
              {missingCount === 0 && duplicateCount === 0 && unrelatedCount === 0 && (
                <div className="sb-reconcile-row ok">
                  ✓ Every container on the Master BL is accounted for, with no duplicates or unrelated numbers.
                </div>
              )}
              {missingCount > 0 && (
                <div className="sb-reconcile-row bad">
                  <strong>Missing ({missingCount}):</strong> on the Master BL but not found on any
                  House BL — {reconcile.missing_containers.join(', ')}
                </div>
              )}
              {duplicateCount > 0 && (
                <div className="sb-reconcile-row bad">
                  <strong>Duplicate ({duplicateCount}):</strong> the same container number appears
                  on more than one House BL — {reconcile.duplicate_containers.join(', ')}
                </div>
              )}
              {unrelatedCount > 0 && (
                <div className="sb-reconcile-row bad">
                  <strong>Possibly incorrect upload ({unrelatedCount}):</strong> found on a House BL
                  but not among the Master BL's own containers — {reconcile.unrelated_containers.join(', ')}
                </div>
              )}
            </div>
          )}

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
            <div className="dz-title">Drag &amp; drop House BL PDFs here</div>
            <div className="dz-sub">
              or <span className="dz-link">click to choose files</span> · 50 or more at once is fine
            </div>
          </label>
          {dropNote && <div className="sm sb-warn">{dropNote}</div>}

          {linked.length > 0 && (
            <>
              {linked.length > 6 && (
                <input
                  className="sb-search"
                  type="search"
                  placeholder="Search by container number or file…"
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
                      Delete selected
                    </button>
                  </>
                )}
              </div>

              <div className="sb-list">
                {shown.map((h) => {
                  const viewing = viewHouseId === h.id
                  const flag = isFlagged(h) ? 'flag-bad' : ''
                  return (
                    <div
                      key={h.id}
                      className={`sb-row ${viewing ? 'viewing' : ''} ${flag}`}
                      onClick={() => onView(h.id)}
                      title="Click to see this House BL's PDF on the right"
                    >
                      <input
                        type="checkbox"
                        className="sb-check"
                        checked={checked.has(h.id)}
                        onClick={(e) => e.stopPropagation()}
                        onChange={() => toggleCheck(h.id)}
                      />
                      <div className="sb-main">
                        <div className="sb-name">{h.filename}</div>
                        <div className="sb-meta">
                          {h.status}
                          {h.container_numbers?.length > 0 && ` · ${h.container_numbers.join(', ')}`}
                        </div>
                      </div>
                      {h.has_duplicate_container && (
                        <span
                          className="sb-pill bad"
                          title="One of this House BL's container numbers also appears on another House BL"
                        >
                          Duplicate container
                        </span>
                      )}
                      {!h.has_duplicate_container && h.has_unrelated_container && (
                        <span
                          className="sb-pill bad"
                          title="One of this House BL's container numbers isn't among the Master BL's own containers"
                        >
                          Unrelated container
                        </span>
                      )}
                      <div className="sb-actions">
                        <button
                          className="link"
                          disabled={busy}
                          onClick={(e) => { e.stopPropagation(); unlink(h) }}
                        >
                          Unlink
                        </button>
                        <button
                          className="link danger"
                          disabled={busy}
                          onClick={(e) => { e.stopPropagation(); remove(h) }}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  )
                })}
                {shown.length === 0 && (
                  <div className="sb-empty">No House BL matches “{query}”.</div>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
