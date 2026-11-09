import { useState } from 'react'

/**
 * Always-visible document tree: each Shipping Bill with its linked Bills of
 * Lading nested beneath it, plus an "Unlinked BLs" group. One click opens any
 * document in the main review pane.
 */
export default function HierarchySidebar({ hierarchy, openId, onOpen }) {
  const [collapsed, setCollapsed] = useState(() => new Set())
  const sbs = hierarchy?.shipping_bills ?? []
  const unlinked = hierarchy?.unlinked_bls ?? []

  const toggle = (id) =>
    setCollapsed((s) => {
      const n = new Set(s)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })

  const blLabel = (bl) => bl.bl_number || bl.filename

  return (
    <aside className="tree">
      <div className="tree-hd">Documents</div>

      {sbs.length === 0 && unlinked.length === 0 && (
        <div className="tree-empty">Nothing yet — upload a PDF above.</div>
      )}

      {sbs.map((sb) => {
        const open = !collapsed.has(sb.id)
        return (
          <div className="tree-group" key={sb.id}>
            <div className={`tree-row sb ${openId === sb.id ? 'active' : ''}`}>
              <button className="twist" onClick={() => toggle(sb.id)} aria-label="expand">
                {open ? '▾' : '▸'}
              </button>
              <button className="tree-label" onClick={() => onOpen(sb.id)}>
                <span className="ico">🧾</span>
                <span className="name">SB {sb.sb_number || sb.filename}</span>
                <span className="count" title="linked Bills of Lading">{sb.bl_count}</span>
              </button>
            </div>
            {open && sb.linked_bls.length === 0 && (
              <div className="tree-row child muted">no BLs linked yet</div>
            )}
            {open &&
              sb.linked_bls.map((bl) => (
                <button
                  key={bl.id}
                  className={`tree-row child ${openId === bl.id ? 'active' : ''}`}
                  onClick={() => onOpen(bl.id)}
                >
                  <span className="ico">📄</span>
                  <span className="name">{blLabel(bl)}</span>
                  {bl.port_of_discharge && <span className="sub">→ {bl.port_of_discharge}</span>}
                  {bl.link_source === 'auto' && <span className="tag">auto</span>}
                </button>
              ))}
          </div>
        )
      })}

      {unlinked.length > 0 && (
        <div className="tree-group">
          <div className="tree-row grp">Unlinked BLs ({unlinked.length})</div>
          {unlinked.map((bl) => (
            <button
              key={bl.id}
              className={`tree-row child ${openId === bl.id ? 'active' : ''}`}
              onClick={() => onOpen(bl.id)}
            >
              <span className="ico">📄</span>
              <span className="name">{blLabel(bl)}</span>
            </button>
          ))}
        </div>
      )}
    </aside>
  )
}
