import { useEffect, useState } from 'react'
import { api } from '../api'

const fmtDate = (s) => (s || '').slice(0, 19).replace('T', ' ')
const fmtCompact = (n) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 10_000 ? `${Math.round(n / 1000)}K` : String(n)

// Ranked horizontal bars — one dimension's magnitude, one hue (sequential),
// not a multi-series comparison, so no legend is needed (title names it).
function BarList({ title, rows }) {
  const max = Math.max(1, ...rows.map((r) => r.count))
  return (
    <div className="analytics-block">
      <h3 className="sm">{title}</h3>
      {rows.length === 0 ? (
        <div className="muted sm">No data yet.</div>
      ) : (
        <div className="barlist">
          {rows.map((r) => (
            <div className="barrow" key={r.label}>
              <span className="barrow-label" title={r.label}>{r.label}</span>
              <div className="barrow-track">
                <div
                  className="barrow-fill viz-tip"
                  data-tip={`${r.label}: ${r.count}`}
                  tabIndex={0}
                  style={{ width: `${(r.count / max) * 100}%` }}
                />
              </div>
              <span className="barrow-n">{r.count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// Document status is a real state machine, not a free-form category, so it
// takes the reserved status palette (good/warning/critical) plus a neutral
// step for "not started yet" and the sequential hue for "in review" — never
// color alone, every segment carries an icon + label in the legend.
const STATUS_META = {
  uploaded: { label: 'Uploaded', color: 'var(--st-neutral)', icon: '•' },
  queued: { label: 'Queued', color: 'var(--st-warning)', icon: '⏳' },
  processing: { label: 'Processing', color: 'var(--st-warning)', icon: '⏳' },
  extracted: { label: 'Extracted', color: 'var(--series-1)', icon: 'i' },
  reviewed: { label: 'Reviewed', color: 'var(--series-1)', icon: 'i' },
  exported: { label: 'Exported', color: 'var(--st-good)', icon: '✓' },
  error: { label: 'Error', color: 'var(--st-critical)', icon: '✕' },
}

// Part-to-whole, read beside its own figures (a stat tile above it) — a thin
// segmented bar, not a donut: bars-on-one-baseline would also work, but the
// whole point here is "how is this ONE type's pipeline distributed right
// now," at a glance, which is exactly the thin-segmented-bar's job.
function StatusBar({ label, byStatus }) {
  const total = Object.values(byStatus).reduce((a, b) => a + b, 0)
  const present = Object.entries(byStatus).filter(([, n]) => n > 0)
  if (total === 0) return null
  return (
    <div className="statusbar-wrap">
      <div className="statusbar-hd">
        <span>{label.replace(/_/g, ' ')}</span>
        <span className="muted">{total} total</span>
      </div>
      <div className="statusbar-track">
        {present.map(([status, n]) => {
          const meta = STATUS_META[status] || { label: status, color: 'var(--muted)', icon: '' }
          const pct = (n / total) * 100
          return (
            <div
              key={status}
              className="statusbar-seg viz-tip"
              data-tip={`${meta.label}: ${n} (${pct.toFixed(0)}%)`}
              tabIndex={0}
              style={{ width: `${pct}%`, background: meta.color }}
            />
          )
        })}
      </div>
      <div className="statusbar-legend">
        {present.map(([status, n]) => {
          const meta = STATUS_META[status] || { label: status, color: 'var(--muted)', icon: '' }
          return (
            <span className="statusbar-legend-item" key={status}>
              <span className="statusbar-dot" style={{ background: meta.color }} />
              {meta.icon} {meta.label} ({n})
            </span>
          )
        })}
      </div>
    </div>
  )
}

// Single ratio against a limit — exactly what a Meter is for, not a 2-slice
// pie or a bar chart of its own.
function Meter({ label, value, total }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div className="meter-wrap">
      <div className="meter-hd">
        <span>{label}</span>
        <strong>{pct}%</strong>
      </div>
      <div className="meter-track-wrap">
        <div
          className="meter-fill viz-tip"
          data-tip={`${value} of ${total} exported`}
          tabIndex={0}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

const STAT_ICONS = ['📄', '👥', '📦', '🧾', '📬', '📮']
const STAT_ACCENTS = ['var(--series-1)', 'var(--series-7)', 'var(--series-3)', 'var(--series-2)', 'var(--series-5)', 'var(--series-4)']

/**
 * Export's and Import's analytics are completely separate screens reading
 * completely separate (category-scoped) data — this component is reused for
 * both, picked by `category`, never shown with mixed data. A regular user
 * sees only their own activity; an admin sees a consolidated view across
 * every user, plus (Export only, since Import has no extracted fields yet)
 * a "by location" breakdown from the Bill of Lading's own Port of Loading /
 * Port of Discharge fields.
 */
export default function AnalyticsPage({ currentUser, category = 'export' }) {
  const isAdmin = currentUser?.role === 'admin'
  const title = category === 'import' ? 'Import' : 'Export'
  const [overview, setOverview] = useState(null)
  const [summary, setSummary] = useState([])
  const [feed, setFeed] = useState([])
  const [err, setErr] = useState(null)

  useEffect(() => {
    setErr(null)
    setOverview(null)
    const calls = [api.activitySummary(category), api.activity(category, { limit: 100 })]
    if (isAdmin) calls.push(api.analyticsOverview(category))
    Promise.all(calls)
      .then(([s, f, o]) => {
        setSummary(s)
        setFeed(f)
        if (o) setOverview(o)
      })
      .catch((e) => setErr(String(e?.message || e)))
  }, [isAdmin, category])

  const byUser = {}
  for (const row of summary) {
    byUser[row.username] = byUser[row.username] || {}
    byUser[row.username][row.action] = row.count
  }
  const actions = [...new Set(summary.map((r) => r.action))].sort()
  const usernames = Object.keys(byUser).sort()
  const byUserBars = usernames
    .map((u) => ({ label: u, count: actions.reduce((sum, a) => sum + (byUser[u][a] || 0), 0) }))
    .sort((a, b) => b.count - a.count)

  const docTypeEntries = overview ? Object.entries(overview.documents_by_type) : []
  const exportedTotal = docTypeEntries.reduce((sum, [, s]) => sum + (s.exported || 0), 0)

  return (
    <div className="records">
      <div className="page-head">
        <div>
          <h1>{title} Analytics</h1>
          <p className="muted sm">
            {isAdmin
              ? `Consolidated ${title.toLowerCase()} usage — every user, every document.`
              : `Your own ${title.toLowerCase()} activity.`}
          </p>
        </div>
      </div>
      {err && <div className="bar error">{err}</div>}

      {isAdmin && overview && (
        <div className="stats">
          <div className="stat" style={{ '--stat-accent': STAT_ACCENTS[0] }}>
            <span className="stat-ico">{STAT_ICONS[0]}</span>
            <div className="stat-n">{fmtCompact(overview.total_documents)}</div>
            <div className="stat-l">Total {title} Records</div>
          </div>
          <div className="stat" style={{ '--stat-accent': STAT_ACCENTS[1] }}>
            <span className="stat-ico">{STAT_ICONS[1]}</span>
            <div className="stat-n">{overview.total_users}</div>
            <div className="stat-l">Total Users</div>
          </div>
          {docTypeEntries.map(([docType, byStatus], i) => (
            <div className="stat" key={docType} style={{ '--stat-accent': STAT_ACCENTS[(i + 2) % STAT_ACCENTS.length] }}>
              <span className="stat-ico">{STAT_ICONS[(i + 2) % STAT_ICONS.length]}</span>
              <div className="stat-n">{Object.values(byStatus).reduce((a, b) => a + b, 0)}</div>
              <div className="stat-l">{docType.replace(/_/g, ' ')}</div>
            </div>
          ))}
        </div>
      )}

      {isAdmin && overview && docTypeEntries.length > 0 && (
        <div className="analytics-grid">
          <div className="analytics-block">
            <h3 className="sm">Pipeline status, by document type</h3>
            {docTypeEntries.map(([docType, byStatus]) => (
              <StatusBar key={docType} label={docType} byStatus={byStatus} />
            ))}
          </div>
          <div className="analytics-block">
            <h3 className="sm">Exported completion</h3>
            <Meter label={`${title} records exported`} value={exportedTotal} total={overview.total_documents} />
            <p className="muted sm" style={{ marginTop: 12 }}>
              {exportedTotal} of {overview.total_documents} {title.toLowerCase()} records have reached the
              "exported" stage.
            </p>
          </div>
        </div>
      )}

      <div className="analytics-grid">
        {isAdmin && overview?.documents_by_user && (
          <BarList
            title={`${title} records by user`}
            rows={overview.documents_by_user.map((r) => ({ label: r.username, count: r.n }))}
          />
        )}
        {isAdmin && overview?.documents_by_company && (
          <BarList
            title={`${title} records by company`}
            rows={overview.documents_by_company.map((r) => ({ label: r.company_name, count: r.n }))}
          />
        )}
        <BarList title="Logins/uploads/submits by user" rows={byUserBars} />
        {isAdmin && overview?.by_port_of_loading && (
          <BarList
            title="Bills of Lading by Port of Loading"
            rows={overview.by_port_of_loading.map((r) => ({ label: r.location, count: r.n }))}
          />
        )}
        {isAdmin && overview?.by_port_of_discharge && (
          <BarList
            title="Bills of Lading by Port of Discharge"
            rows={overview.by_port_of_discharge.map((r) => ({ label: r.location, count: r.n }))}
          />
        )}
      </div>

      <h3 className="sm" style={{ margin: '18px 0 8px' }}>
        {isAdmin ? 'Activity by user & action' : 'Your activity by action'}
      </h3>
      <table className="rec-table" style={{ marginBottom: 20 }}>
        <thead>
          <tr>
            <th>User</th>
            {actions.map((a) => <th key={a}>{a}</th>)}
          </tr>
        </thead>
        <tbody>
          {usernames.length === 0 && (
            <tr><td colSpan={actions.length + 1} className="muted pad">No activity yet.</td></tr>
          )}
          {usernames.map((u) => (
            <tr key={u}>
              <td>{u}</td>
              {actions.map((a) => <td key={a}>{byUser[u][a] || 0}</td>)}
            </tr>
          ))}
        </tbody>
      </table>

      <h3 className="sm" style={{ margin: '18px 0 8px' }}>Recent activity</h3>
      <table className="rec-table">
        <thead>
          <tr><th>When</th><th>User</th><th>Action</th><th>Type</th><th>Detail</th></tr>
        </thead>
        <tbody>
          {feed.length === 0 && (
            <tr><td colSpan={5} className="muted pad">Nothing yet.</td></tr>
          )}
          {feed.map((a) => (
            <tr key={a.id}>
              <td className="mono sm">{fmtDate(a.created_at)}</td>
              <td>{a.username}</td>
              <td>{a.action}</td>
              <td>{a.doc_type || '—'}</td>
              <td className="muted sm">{a.detail || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
