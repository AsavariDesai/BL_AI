// Shared by the BL screen's Shipping Bills section and the Uploaded Data list,
// so a Shipping Bill reads the same way everywhere.

// Plain-English status for non-technical users: [label, css tone]
export const SB_STATUS = {
  uploaded: ['Waiting', 'wait'],
  queued: ['Waiting', 'wait'],
  processing: ['Reading…', 'busy'],
  extracted: ['Ready', 'ok'],
  reviewed: ['Ready', 'ok'],
  exported: ['Ready', 'ok'],
  error: ['Failed', 'bad'],
}

export const SB_PENDING = new Set(['uploaded', 'queued', 'processing'])

export const sbStatus = (status) => SB_STATUS[status] ?? [status, 'wait']

const fieldOf = (lsb, key) => lsb.fields?.find((f) => f.key === key)?.value || ''

// One short line under a Shipping Bill's number: "01-JUL-26 · 71 pkgs · 132.44 MTS"
export function sbMetaLine(lsb) {
  if (lsb.status === 'error') return "Couldn't read this file — open it, then choose Re-run."
  if (SB_PENDING.has(lsb.status)) return 'Reading the document…'
  const pkgs = fieldOf(lsb, 'sb_packages')
  const parts = [fieldOf(lsb, 'sb_date'), pkgs && `${pkgs} pkgs`, fieldOf(lsb, 'sb_gross_weight')]
  const line = parts.filter(Boolean).join(' · ')
  return line || 'No details found'
}
