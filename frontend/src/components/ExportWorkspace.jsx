import { useEffect, useState } from 'react'
import { api } from '../api'
import RecordsPage from './RecordsPage'
import { CompanyWorkspace } from './ImportWorkspace'

/**
 * Export's own Company Workspace — the Export-side mirror of
 * ImportWorkspace's company picker (see that file). Company Master is
 * shared infrastructure, so the same companies an admin assigns there are
 * what a login picks from here. From a company, Export now has the same
 * Vessel-based structure Import does (CompanyWorkspace is the literal same
 * shared component, `category="export"`): pick or create a Vessel, then
 * upload/review/export/delete BLs and Shipping Bills scoped to it.
 *
 * Existing records uploaded before Export had vessels (company_id set,
 * vessel_id null) are never forced into one — they keep showing exactly as
 * before under the Company's own "All Records" tab, which is the same
 * RecordsPage this screen always rendered directly, just moved one level
 * in. New uploads go through a Vessel instead, same as Import.
 */
export default function ExportWorkspace({ onOpen, onOpenChild, onUpload, busy }) {
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
            <h1>Export</h1>
            <p className="muted sm">Pick a company to open its workspace.</p>
          </div>
        </div>
        {companies.length === 0 ? (
          <div className="bar warn">No companies assigned to your account yet — ask an Admin to assign one.</div>
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
      <ExportVesselWorkspace
        vesselId={vesselId}
        onBack={() => setVesselId(null)}
        onOpen={onOpen}
        onOpenChild={onOpenChild}
        onUpload={onUpload}
        busy={busy}
      />
    )
  }

  return (
    <CompanyWorkspace
      company={company}
      category="export"
      onBackToCompanies={companies.length > 1 ? () => setCompanyId(null) : null}
      onOpenVessel={setVesselId}
      onOpen={onOpen}
      onOpenChild={onOpenChild}
      onUpload={onUpload}
      recordsBusy={busy}
    />
  )
}

function ExportVesselWorkspace({ vesselId, onBack, onOpen, onOpenChild, onUpload, busy }) {
  const [vessel, setVessel] = useState(null)
  const [err, setErr] = useState(null)
  const [note, setNote] = useState('')
  const [bulkBusy, setBulkBusy] = useState(false)

  useEffect(() => {
    api.vessel(vesselId).then(setVessel).catch((e) => setErr(String(e?.message || e)))
  }, [vesselId])

  async function bulkUpload(files) {
    setBulkBusy(true); setErr(null); setNote('')
    try {
      const { uploaded, failed } = await api.bulkUploadToVessel(vesselId, files)
      setNote(
        `${uploaded.length} uploaded — extracting in the background.` +
          (failed.length ? ` ${failed.length} failed: ${failed.join(', ')}` : ''),
      )
    } catch (e) {
      setErr(String(e?.message || e))
    } finally {
      setBulkBusy(false)
    }
  }

  return (
    <>
      {err && <div className="bar error" style={{ margin: '0 24px' }}>{err}</div>}
      {!err && note && <div className="bar ok" style={{ margin: '0 24px' }}>{note}</div>}
      <RecordsPage
        onOpen={onOpen}
        onOpenChild={onOpenChild}
        onUpload={onUpload}
        busy={busy}
        companyId={vessel?.company_id}
        companyName={vessel ? `${vessel.name} (IMO ${vessel.imo_code})` : 'Vessel'}
        onBackToCompanies={onBack}
        backLabel="‹ Vessels"
        vesselId={vesselId}
        onBulkUpload={bulkUpload}
        bulkBusy={bulkBusy}
      />
    </>
  )
}
