// VITE_API is only for the split dev-server case (`npm run dev` on :5173
// talking to a separately-run backend on :8000) — set it in frontend/.env
// if that's what you're doing. A built production bundle (SERVE_FRONTEND=1,
// one process/port for everything) instead defaults to the page's own
// origin, so it works correctly whether it's reached as localhost, 127.0.0.1,
// a real IP, or a real domain — a hardcoded 'localhost' fallback would only
// work for exactly one of those.
const BASE =
  import.meta.env.VITE_API ?? (import.meta.env.DEV ? 'http://localhost:8000' : window.location.origin)

// Every request must carry the session cookie, including cross-origin ones
// (the Vite dev server on :5173 talking to uvicorn on :8000) — plain fetch()
// only sends cookies same-origin by default.
function f(url, opts) {
  return fetch(url, { ...opts, credentials: 'include' })
}

async function j(res) {
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `${res.status} ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  base: BASE,
  login: (username, password) =>
    f(`${BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }).then(j),
  logout: () => f(`${BASE}/auth/logout`, { method: 'POST' }).then(j),
  me: () => f(`${BASE}/auth/me`).then(j),
  fields: (docType = 'bill_of_lading') =>
    f(`${BASE}/fields?doc_type=${docType}`).then(j),
  docTypes: () => f(`${BASE}/doc-types`).then(j),
  upload: (file, { docType = 'bill_of_lading', parentId, vesselId, companyId } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('doc_type', docType)
    if (parentId) fd.append('parent_id', parentId)
    if (vesselId) fd.append('vessel_id', vesselId)
    if (companyId) fd.append('company_id', companyId)
    return f(`${BASE}/documents`, { method: 'POST', body: fd }).then(j)
  },
  ingest: (file, { docType, parentId, background = false, companyId, vesselId } = {}) => {
    const fd = new FormData()
    fd.append('file', file)
    if (docType) fd.append('doc_type', docType)
    if (parentId) fd.append('parent_id', parentId)
    if (background) fd.append('background', 'true')
    if (companyId) fd.append('company_id', companyId)
    if (vesselId) fd.append('vessel_id', vesselId)
    return f(`${BASE}/ingest`, { method: 'POST', body: fd }).then(j)
  },
  extract: (id, { background = false } = {}) =>
    f(`${BASE}/documents/${id}/extract${background ? '?background=true' : ''}`, {
      method: 'POST',
    }).then(j),
  getDoc: (id) => f(`${BASE}/documents/${id}`).then(j),
  listDocs: (params = {}) => {
    const qs = new URLSearchParams(params)
    return f(`${BASE}/documents?${qs}`).then(j)
  },
  shippingBills: () => f(`${BASE}/shipping-bills`).then(j),
  shippingBill: (id) => f(`${BASE}/shipping-bills/${id}`).then(j),
  hierarchy: () => f(`${BASE}/hierarchy`).then(j),
  records: (params = {}, source = 'records') => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== '' && v != null),
    )
    return f(`${BASE}/${source}?${qs}`).then(j)
  },
  recordStats: (source = 'records') => f(`${BASE}/${source}/stats`).then(j),
  submitRecords: (docIds) =>
    f(`${BASE}/records/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: docIds }),
    }).then(j),
  exportRecords: async (docIds, fmt = 'xlsx', { combine = false } = {}) => {
    const res = await f(`${BASE}/records/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: docIds, fmt, combine }),
    })
    if (!res.ok) throw new Error((await res.text().catch(() => '')) || res.statusText)
    return { blob: await res.blob(), filename: filenameFrom(res, `bl_records.${fmt}`) }
  },
  linkBls: (id, docIds) =>
    f(`${BASE}/shipping-bills/${id}/link`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: docIds }),
    }).then(j),
  unlinkBls: (id, docIds) =>
    f(`${BASE}/shipping-bills/${id}/unlink`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: docIds }),
    }).then(j),
  exportHierarchy: async (id, { fmt = 'xlsx', blFields = [], sbFields = [] } = {}) => {
    const qs = new URLSearchParams({ fmt })
    if (blFields.length) qs.set('bl_fields', blFields.join(','))
    if (sbFields.length) qs.set('sb_fields', sbFields.join(','))
    const res = await f(`${BASE}/shipping-bills/${id}/export?${qs}`)
    if (!res.ok) throw new Error((await res.text().catch(() => '')) || res.statusText)
    return { blob: await res.blob(), filename: filenameFrom(res, `shipping_bill.${fmt}`) }
  },
  linkShippingBills: async (blId, files, { background = true } = {}) => {
    const fd = new FormData()
    for (const file of files) fd.append('files', file)
    fd.append('background', background ? 'true' : 'false')
    const res = await f(`${BASE}/documents/${blId}/link-shipping-bill`, {
      method: 'POST',
      body: fd,
    })
    const data = await j(res)
    // Files that individually failed to process (e.g. an unreadable PDF)
    // don't fail the whole request — they're listed here instead, so a bad
    // file in a large batch never blocks the rest.
    const failedHeader = res.headers.get('X-Failed-Files')
    data._failedFiles = failedHeader ? failedHeader.split(',') : []
    return data
  },
  linkExistingSb: (blId, sbIds) =>
    f(`${BASE}/documents/${blId}/link-existing-sb`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: sbIds }),
    }).then(j),
  unlinkSb: (blId, sbId) =>
    f(`${BASE}/documents/${blId}/unlink-sb/${sbId}`, { method: 'POST' }).then(j),
  exportBlWithSb: async (blId, { fmt = 'xlsx' } = {}) => {
    const res = await f(`${BASE}/documents/${blId}/export-with-sb?fmt=${fmt}`)
    if (!res.ok) throw new Error((await res.text().catch(() => '')) || res.statusText)
    return { blob: await res.blob(), filename: filenameFrom(res, `bl_sb.${fmt}`) }
  },
  saveFields: (id, fields) =>
    f(`${BASE}/documents/${id}/fields`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fields }),
    }).then(j),
  fileUrl: (id) => `${BASE}/documents/${id}/file`,
  templates: () => f(`${BASE}/export-templates`).then(j),
  saveTemplate: (body) =>
    f(`${BASE}/export-templates`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(j),
  exportDoc: async (id, { fmt = 'xlsx', fields = [], templateId } = {}) => {
    const qs = new URLSearchParams({ fmt })
    if (fields.length) qs.set('fields', fields.join(','))
    if (templateId) qs.set('template_id', templateId)
    const res = await f(`${BASE}/documents/${id}/export?${qs}`)
    if (!res.ok) throw new Error((await res.text().catch(() => '')) || res.statusText)
    return { blob: await res.blob(), filename: filenameFrom(res, `bl_${id}.${fmt}`) }
  },
  // One .zip with three separate files: all selected BLs' own details (BL
  // Data), all their linked Shipping Bills' details alongside the BLs' own
  // (BL + Shipping Bill), and a Summary of each BL's SB reconciliation and
  // cargo totals — always a .zip, whether one BL or many were selected.
  exportRecordsSplit: async (docIds, fmt = 'xlsx') => {
    const res = await f(`${BASE}/records/export-split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: docIds, fmt }),
    })
    if (!res.ok) throw new Error((await res.text().catch(() => '')) || res.statusText)
    return { blob: await res.blob(), filename: filenameFrom(res, 'bl_records.zip') }
  },
  // Import's mirror of exportRecordsSplit — three files in one .zip: Master
  // BL Data, Master + House BL, Summary (document/linkage metadata today;
  // the shape is ready to grow once Master BL/House BL field extraction
  // exists).
  exportMasterBlSplit: async (docIds) => {
    const res = await f(`${BASE}/records/export-master-bl-split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: docIds, fmt: 'xlsx' }),
    })
    if (!res.ok) throw new Error((await res.text().catch(() => '')) || res.statusText)
    return { blob: await res.blob(), filename: filenameFrom(res, 'master_bl_records.zip') }
  },

  // ------------------------------------------------------------- masters
  vessels: (q = '', companyId = '') => {
    const params = { ...(q ? { q } : {}), ...(companyId ? { company_id: companyId } : {}) }
    return f(`${BASE}/vessels?${new URLSearchParams(params)}`).then(j)
  },
  vessel: (id) => f(`${BASE}/vessels/${id}`).then(j),
  createVessel: (body) =>
    f(`${BASE}/vessels`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(j),
  updateVessel: (id, body) =>
    f(`${BASE}/vessels/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(j),
  deleteVessel: (id) => f(`${BASE}/vessels/${id}`, { method: 'DELETE' }).then(j),

  companies: (q = '') => f(`${BASE}/companies?${new URLSearchParams(q ? { q } : {})}`).then(j),
  company: (id) => f(`${BASE}/companies/${id}`).then(j),
  createCompany: (body) =>
    f(`${BASE}/companies`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(j),
  updateCompany: (id, body) =>
    f(`${BASE}/companies/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(j),
  deleteCompany: (id) => f(`${BASE}/companies/${id}`, { method: 'DELETE' }).then(j),

  // ------------------------------------------------- Master BL / House BL
  linkHouseBl: async (masterId, files) => {
    const fd = new FormData()
    for (const file of files) fd.append('files', file)
    const res = await f(`${BASE}/documents/${masterId}/link-house-bl`, { method: 'POST', body: fd })
    const data = await j(res)
    const failedHeader = res.headers.get('X-Failed-Files')
    data._failedFiles = failedHeader ? failedHeader.split(',') : []
    return data
  },
  unlinkHouseBl: (masterId, houseId) =>
    f(`${BASE}/documents/${masterId}/unlink-house-bl/${houseId}`, { method: 'POST' }).then(j),

  // ----------------------------------------------------- document delete
  // Shared by Export (Bill of Lading / Shipping Bill) and Import (Master
  // BL / House BL) — removes a bad upload so it can be re-uploaded without
  // touching the Company/Vessel it lives under.
  deleteDocument: (id) => f(`${BASE}/documents/${id}`, { method: 'DELETE' }).then(j),
  bulkDeleteDocuments: (docIds) =>
    f(`${BASE}/documents/bulk-delete`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_ids: docIds }),
    }).then(j),

  // Export's own Vessel Workspace bulk upload — the counterpart of
  // linkHouseBl, sized for up to ~400 files in one batch; each file's type
  // (Bill of Lading / Shipping Bill) is auto-detected.
  bulkUploadToVessel: async (vesselId, files) => {
    const fd = new FormData()
    for (const file of files) fd.append('files', file)
    const res = await f(`${BASE}/vessels/${vesselId}/bulk-upload`, { method: 'POST', body: fd })
    return j(res)
  },

  // ---------------------------------------------------------- user management
  users: () => f(`${BASE}/users`).then(j),
  createUser: (body) =>
    f(`${BASE}/users`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(j),
  updateUser: (id, body) =>
    f(`${BASE}/users/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(j),
  deleteUser: (id) => f(`${BASE}/users/${id}`, { method: 'DELETE' }).then(j),

  ports: (q = '', companyId = '') => {
    const params = { ...(q ? { q } : {}), ...(companyId ? { company_id: companyId } : {}) }
    return f(`${BASE}/ports?${new URLSearchParams(params)}`).then(j)
  },
  port: (id) => f(`${BASE}/ports/${id}`).then(j),
  createPort: (body) =>
    f(`${BASE}/ports`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(j),
  updatePort: (id, body) =>
    f(`${BASE}/ports/${id}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    }).then(j),
  deletePort: (id) => f(`${BASE}/ports/${id}`, { method: 'DELETE' }).then(j),

  // One list, pending and submitted together — the single Export screen and
  // single Import screen both read this (`category: 'export' | 'import'`
  // picks which side's doc_types to include).
  recordsOverview: (params = {}, category = 'export') => {
    const qs = new URLSearchParams(
      Object.entries({ ...params, category }).filter(([, v]) => v !== '' && v != null),
    )
    return f(`${BASE}/records/overview?${qs}`).then(j)
  },

  // Export's and Import's activity/analytics are completely separate —
  // `category` picks which side.
  activity: (category = 'export', params = {}) =>
    f(`${BASE}/activity?${new URLSearchParams({ ...params, category })}`).then(j),
  activitySummary: (category = 'export') =>
    f(`${BASE}/activity/summary?${new URLSearchParams({ category })}`).then(j),
  analyticsOverview: (category = 'export') =>
    f(`${BASE}/analytics/overview?${new URLSearchParams({ category })}`).then(j),
}

function filenameFrom(res, fallback) {
  const cd = res.headers.get('content-disposition') || ''
  const m = cd.match(/filename="?([^"]+)"?/i)
  return m ? m[1] : fallback
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
