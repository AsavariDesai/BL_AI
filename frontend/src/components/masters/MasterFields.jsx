// Shared form building blocks for the Vessel / Company / Port master screens
// — a labeled input/select (with the "| Label" required marker matching the
// reference screens) and an add/remove-row editable table for a master's
// nested rows (Company Branches, Port Berths).

export function Field({ label, required, value, onChange, type = 'text', multiline }) {
  const common = {
    value: value ?? '',
    onChange: (e) => onChange(e.target.value),
  }
  return (
    <label className="mfield">
      <span>{required && <span className="req">|</span>}{label}</span>
      {multiline ? <textarea rows={2} {...common} /> : <input type={type} {...common} />}
    </label>
  )
}

export function SelectField({ label, required, value, onChange, options, placeholder = '—' }) {
  return (
    <label className="mfield">
      <span>{required && <span className="req">|</span>}{label}</span>
      <select value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
        <option value="">{placeholder}</option>
        {options.map((o) =>
          Array.isArray(o) ? (
            <option key={o[0]} value={o[0]}>{o[1]}</option>
          ) : (
            <option key={o} value={o}>{o}</option>
          ),
        )}
      </select>
    </label>
  )
}

export function RadioField({ label, required, value, onChange }) {
  return (
    <div className="mfield">
      <span>{required && <span className="req">|</span>}{label}</span>
      <div className="mradio-group">
        <label className="mradio">
          <input type="radio" checked={value === true} onChange={() => onChange(true)} /> Yes
        </label>
        <label className="mradio">
          <input type="radio" checked={value === false} onChange={() => onChange(false)} /> No
        </label>
      </div>
    </div>
  )
}

export function rowsValid(rows, columns) {
  return rows.every((r) => columns.every((c) => !c.required || (r[c.key] ?? '').trim()))
}

export function EditableTable({ columns, rows, onChange }) {
  function update(i, key, value) {
    const next = rows.slice()
    next[i] = { ...next[i], [key]: value }
    onChange(next)
  }
  function addRow() {
    onChange([...rows, Object.fromEntries(columns.map((c) => [c.key, '']))])
  }
  function removeRow(i) {
    onChange(rows.filter((_, idx) => idx !== i))
  }
  return (
    <div className="msub">
      <button type="button" className="btn ghost sm" onClick={addRow}>+ ADD</button>
      <div className="msub-table-wrap">
        <table className="msub-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key}>{c.required && <span className="req">|</span>}{c.label}</th>
              ))}
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={columns.length + 1} className="muted pad-sm">No rows yet.</td></tr>
            )}
            {rows.map((row, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c.key}>
                    <input value={row[c.key] ?? ''} onChange={(e) => update(i, c.key, e.target.value)} />
                  </td>
                ))}
                <td>
                  <button type="button" className="link danger" onClick={() => removeRow(i)}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
