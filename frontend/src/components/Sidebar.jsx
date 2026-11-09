const EXPORT_ITEMS = [
  { key: 'export', label: 'Export', icon: '⬆' },
  { key: 'export-analytics', label: 'Analytics', icon: '📊' },
]

// Import is one nested workspace now (Company -> Vessels/Ports -> a
// vessel's own Master BL / House BL screen — see ImportWorkspace), not flat
// Company/Vessel/Port Master screens.
const IMPORT_ITEMS_ADMIN = [
  { key: 'import', label: 'Import', icon: '⬇' },
  { key: 'import-analytics', label: 'Analytics', icon: '📊' },
]
const IMPORT_ITEMS_USER = IMPORT_ITEMS_ADMIN

// Company Master is shared infrastructure, not Import-specific (Export has
// its own Company Workspace too — see ExportWorkspace) — it lives under
// Administration instead of nested under either side. Still admin-only: the
// admin creates companies and assigns each one to a user login, so a
// regular user never sees this item here.
const ADMIN_ITEMS = [
  { key: 'company-master', label: 'Company Master', icon: '🏢' },
  { key: 'user-master', label: 'User Master', icon: '👤' },
  { key: 'rights-management', label: 'Rights Management', icon: '🔐' },
]

// Review (editing a Bill of Lading / Shipping Bill's fields) only ever opens
// from the Export screen, so it counts as "Export" for the toggle/sub-nav.
// Company Master isn't in here — it's reachable regardless of which
// category toggle is active (see ADMIN_ITEMS above).
const IMPORT_VIEWS = new Set(['import', 'import-analytics'])
export function categoryOf(view) {
  if (view === 'export' || view === 'review' || view === 'export-analytics') return 'export'
  if (IMPORT_VIEWS.has(view)) return 'import'
  return null
}

function NavGroup({ title, items, view, onNav }) {
  return (
    <>
      <div className="nav-group">{title}</div>
      {items.map((it) => (
        <button
          key={it.key}
          className={`nav-item ${view === it.key ? 'active' : ''}`}
          onClick={() => onNav(it.key)}
        >
          <span className="nav-ico">{it.icon}</span>
          {it.label}
        </button>
      ))}
    </>
  )
}

// Screen-level rights (set by an admin in Rights Management): which
// top-level category(ies) this login can reach at all. An admin ignores
// these and always has both, same as every other admin-bypass in the app.
export function accessFor(user) {
  const isAdmin = user?.role === 'admin'
  return {
    isAdmin,
    canExport: isAdmin || !!user?.can_export,
    canImport: isAdmin || !!user?.can_import,
  }
}

export default function Sidebar({ view, onNav, user, onLogout }) {
  const { isAdmin, canExport, canImport } = accessFor(user)
  const both = canExport && canImport
  const requested = categoryOf(view)
  // if the current view belongs to a category this login can't reach,
  // fall back to whichever one it can.
  const category = requested && (requested === 'export' ? canExport : canImport)
    ? requested
    : canExport ? 'export' : canImport ? 'import' : null

  return (
    <aside className="nav">
      <div className="nav-brand">
        <span className="nav-logo">BL</span>
        <div>
          <strong>BL-AI</strong>
          <div className="nav-sub">document extraction</div>
        </div>
      </div>

      {both && (
        <div className="nav-toggle">
          <button
            className={`nav-toggle-btn ${category === 'import' ? 'active' : ''}`}
            onClick={() => onNav('import')}
          >
            ⬇ Import
          </button>
          <button
            className={`nav-toggle-btn ${category === 'export' ? 'active' : ''}`}
            onClick={() => onNav('export')}
          >
            ⬆ Export
          </button>
        </div>
      )}

      {category ? (
        <NavGroup
          title={category === 'import' ? 'Import' : 'Export'}
          items={category === 'import' ? (isAdmin ? IMPORT_ITEMS_ADMIN : IMPORT_ITEMS_USER) : EXPORT_ITEMS}
          view={view}
          onNav={onNav}
        />
      ) : (
        <div className="nav-noaccess">No screens assigned yet — ask an Admin.</div>
      )}

      {isAdmin && <NavGroup title="Administration" items={ADMIN_ITEMS} view={view} onNav={onNav} />}

      <div className="grow" />
      {user && (
        <div className="nav-user">
          <span className="nav-user-name" title={user.username}>{user.username}</span>
          <button className="link" onClick={onLogout}>
            Sign out
          </button>
        </div>
      )}
    </aside>
  )
}
