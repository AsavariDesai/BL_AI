"""Build XLSX / PDF exports from extracted BL fields.

XLSX: one row per document, columns = selected canonical fields.
PDF:  one page per document, a clean key/value table.

PDF is rendered with PyMuPDF's HTML box (already a dependency) so no extra
PDF library is needed.
"""
from __future__ import annotations

import html
import io
import re
from datetime import date

import pymupdf
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .field_catalog import get_field

Row = dict[str, str | None]


def _columns(field_keys: list[str]) -> list[tuple[str, str]]:
    return [(k, get_field(k)["label"]) for k in field_keys]


# --------------------------------------------------------------------- XLSX
def build_xlsx(rows: list[Row], field_keys: list[str]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "BL Export"

    cols = _columns(field_keys)
    headers = ["Source File", *[label for _, label in cols]]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for r in rows:
        ws.append([r.get("_file", ""), *[(r.get(k) or "") for k, _ in cols]])

    for idx, header in enumerate(headers, start=1):
        values = [header] + [str(ws.cell(row=i + 2, column=idx).value or "") for i in range(len(rows))]
        width = min(60, max(12, max(len(v) for v in values) + 2))
        ws.column_dimensions[get_column_letter(idx)].width = width

    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------- PDF
# PyMuPDF's html engine collapses %-width table cells (labels overprint values),
# so lay each field out as a bordered row of two inline-blocks with fixed widths.
_PDF_CSS = """
* { font-family: sans-serif; }
h2 { font-size: 13pt; margin: 0 0 2pt 0; }
p.sub { font-size: 8pt; color: #666; margin: 0 0 10pt 0; }
h3 { font-size: 11pt; margin: 12pt 0 4pt; }
.f { border: 0.5pt solid #bbb; border-top: none; padding: 3pt 6pt; font-size: 8.5pt; }
.f:first-of-type { border-top: 0.5pt solid #bbb; }
.f .k {
  display: inline-block; width: 150pt; vertical-align: top;
  font-weight: bold; background: #f2f4f7;
}
.f .v { display: inline-block; width: 350pt; vertical-align: top; }
ul { margin: 2pt 0; padding-left: 16pt; }
li { font-size: 8.5pt; }
"""

_MAX_CELL = 900  # keep a runaway value from blowing out the page


def _cell(value: str | None) -> str:
    v = (value or "").strip()
    if len(v) > _MAX_CELL:
        v = v[:_MAX_CELL].rstrip() + " …"
    return html.escape(v)


def _fields_html(row: Row, cols: list[tuple[str, str]]) -> str:
    return "".join(
        f"<div class='f'><span class='k'>{html.escape(label)}</span>"
        f"<span class='v'>{_cell(row.get(key))}</span></div>"
        for key, label in cols
    )


def _doc_html(row: Row, cols: list[tuple[str, str]]) -> str:
    title = html.escape(row.get("_file") or "Bill of Lading")
    return (
        f"<h2>Bill of Lading — extracted fields</h2>"
        f"<p class='sub'>{title} &nbsp;·&nbsp; exported {date.today().isoformat()}</p>"
        f"{_fields_html(row, cols)}"
    )


_TYPE_SHEET = {"bill_of_lading": "Bills of Lading", "shipping_bill": "Shipping Bills"}


def build_records_xlsx(groups: dict[str, tuple[list[str], list[Row]]]) -> bytes:
    """One sheet per document type; columns = that type's selected fields."""
    wb = Workbook()
    wb.remove(wb.active)
    for doc_type, (keys, rows) in groups.items():
        ws = wb.create_sheet(_TYPE_SHEET.get(doc_type, doc_type)[:31])
        headers = ["Source File", *[label for _, label in _columns(keys)]]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for r in rows:
            ws.append([r.get("_file", ""), *[(r.get(k) or "") for k, _ in _columns(keys)]])
        for idx, header in enumerate(headers, start=1):
            col = [header] + [
                str(ws.cell(row=i + 2, column=idx).value or "") for i in range(len(rows))
            ]
            ws.column_dimensions[get_column_letter(idx)].width = min(
                60, max(12, max(len(v) for v in col) + 2)
            )
        ws.freeze_panes = "A2"
    if not wb.sheetnames:
        wb.create_sheet("Records")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_records_pdf(groups: dict[str, tuple[list[str], list[Row]]]) -> bytes:
    doc = pymupdf.open()
    try:
        for _doc_type, (keys, rows) in groups.items():
            for r in rows:
                page = doc.new_page(width=595, height=842)
                page.insert_htmlbox(
                    pymupdf.Rect(36, 36, 559, 806), _doc_html(r, _columns(keys)), css=_PDF_CSS
                )
        if doc.page_count == 0:
            doc.new_page(width=595, height=842)
        return doc.write()
    finally:
        doc.close()


def build_pdf(rows: list[Row], field_keys: list[str]) -> bytes:
    cols = _columns(field_keys)
    doc = pymupdf.open()
    try:
        for r in rows:
            page = doc.new_page(width=595, height=842)  # A4 in points
            page.insert_htmlbox(
                pymupdf.Rect(36, 36, 559, 806),
                _doc_html(r, cols),
                css=_PDF_CSS,
            )
        return doc.write()
    finally:
        doc.close()


# ------------------------------------------------ BL + its linked Shipping Bills
_SHEET_NAME_BAD = re.compile(r'[:\\/?*\[\]]')


def _sheet_name(raw: str, used: set[str]) -> str:
    """A valid, unique Excel sheet name (<=31 chars, no :\\/?*[]) derived
    from ``raw`` — collisions get a "(2)", "(3)", ... suffix."""
    base = _SHEET_NAME_BAD.sub(" ", (raw or "").strip()).strip()[:28] or "Sheet"
    name = base
    i = 2
    while name in used:
        suffix = f" ({i})"
        name = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(name)
    return name


def _vertical_sheet(ws, cols: list[tuple[str, str]], row: Row) -> None:
    ws.append(["Field", "Value"])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for k, label in cols:
        ws.append([label, row.get(k) or ""])
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 60
    ws.freeze_panes = "A2"


def build_bl_multi_sb_xlsx(
    bl: Row, bl_keys: list[str], sbs: list[Row], sb_cols: list[tuple[str, str]]
) -> bytes:
    """One vertical Field/Value sheet for the Bill of Lading, then one more
    vertical Field/Value sheet per linked Shipping Bill (50+ supported) —
    every sheet the same familiar layout, named by SB number, easy to page
    through with Excel's sheet tabs rather than scrolling one wide table."""
    wb = Workbook()
    s0 = wb.active
    s0.title = "Bill of Lading"
    _vertical_sheet(s0, _columns(bl_keys), bl)

    used = {"Bill of Lading"}
    for s in sbs:
        label = s.get("sb_number") or s.get("_file") or "Shipping Bill"
        ws = wb.create_sheet(_sheet_name(f"SB {label}", used))
        _vertical_sheet(ws, sb_cols, s)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _tabular_sheet(ws, headers: list[str], rows: list[list[str]]) -> None:
    """One row per document, columns = the given headers — the standard
    tabular layout used across this module's other xlsx builders."""
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    for idx, header in enumerate(headers, start=1):
        values = [header] + [
            str(ws.cell(row=i + 2, column=idx).value or "") for i in range(len(rows))
        ]
        width = min(60, max(12, max(len(v) for v in values) + 2))
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"


def build_bl_records_xlsx(
    bl_rows: list[Row], bl_cols: list[tuple[str, str]],
    sb_rows: list[tuple[str, Row]], sb_cols: list[tuple[str, str]],
) -> bytes:
    """Several Bills of Lading (each with its own linked Shipping Bills)
    merged into ONE workbook instead of one file per document — exactly two
    sheets total no matter how many BLs/SBs are included: a tabular "Bills
    of Lading" sheet (one row per BL) and a tabular "Shipping Bills" sheet
    (one row per Shipping Bill, with its own BL Number as the leading
    column so each one's parent BL is still clear without a separate sheet
    or section per document)."""
    wb = Workbook()
    s0 = wb.active
    s0.title = "Bills of Lading"
    _tabular_sheet(
        s0,
        [label for _, label in bl_cols],
        [[row.get(k) or "" for k, _ in bl_cols] for row in bl_rows],
    )

    s1 = wb.create_sheet("Shipping Bills")
    _tabular_sheet(
        s1,
        ["BL Number"] + [label for _, label in sb_cols],
        [[bl_num] + [row.get(k) or "" for k, _ in sb_cols] for bl_num, row in sb_rows],
    )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_bl_multi_sb_pdf(
    bl: Row, bl_keys: list[str], sbs: list[Row], sb_cols: list[tuple[str, str]]
) -> bytes:
    doc = pymupdf.open()
    try:
        sb_list = "".join(
            f"<li>{html.escape(s.get('_file') or '')}</li>" for s in sbs
        ) or "<li>(none)</li>"
        page = doc.new_page(width=595, height=842)
        page.insert_htmlbox(
            pymupdf.Rect(36, 36, 559, 806),
            f"<h2>Bill of Lading — {html.escape(bl.get('_file') or '')}</h2>"
            f"<p class='sub'>{len(sbs)} linked Shipping Bill(s) &nbsp;·&nbsp; "
            f"exported {date.today().isoformat()}</p>"
            f"{_fields_html(bl, _columns(bl_keys))}"
            f"<h3>Linked Shipping Bills</h3><ul>{sb_list}</ul>",
            css=_PDF_CSS,
        )
        for s in sbs:
            p = doc.new_page(width=595, height=842)
            p.insert_htmlbox(
                pymupdf.Rect(36, 36, 559, 806),
                f"<h2>Shipping Bill — {html.escape(s.get('_file') or '')}</h2>"
                f"{_fields_html(s, sb_cols)}",
                css=_PDF_CSS,
            )
        return doc.write()
    finally:
        doc.close()


# ------------------------------------------------------- Shipping Bill hierarchy
def build_hierarchy_xlsx(
    sb: Row, sb_keys: list[str], bls: list[Row], bl_keys: list[str]
) -> bytes:
    wb = Workbook()

    # Sheet 1 — one row per linked BL, with the Shipping Bill's fields repeated
    # as leading "SB: …" columns so the linkage reads across a single row.
    s0 = wb.active
    s0.title = "SB + Linked BLs"
    sb_cols = _columns(sb_keys)
    bl_cols = _columns(bl_keys)
    headers = (
        ["SB Source File"]
        + [f"SB: {label}" for _, label in sb_cols]
        + ["BL Source File"]
        + [f"BL: {label}" for _, label in bl_cols]
    )
    s0.append(headers)
    for cell in s0[1]:
        cell.font = Font(bold=True)
    sb_prefix = [sb.get("_file", "")] + [sb.get(k) or "" for k, _ in sb_cols]
    for b in bls or [{}]:
        s0.append(sb_prefix + [b.get("_file", "")] + [b.get(k) or "" for k, _ in bl_cols])
    for idx, header in enumerate(headers, start=1):
        vals = [header] + [
            str(s0.cell(row=i + 2, column=idx).value or "")
            for i in range(max(1, len(bls)))
        ]
        s0.column_dimensions[get_column_letter(idx)].width = min(
            60, max(12, max(len(v) for v in vals) + 2)
        )
    s0.freeze_panes = "B2"

    s1 = wb.create_sheet("Shipping Bill")
    s1.append(["Field", "Value"])
    for cell in s1[1]:
        cell.font = Font(bold=True)
    for k, label in sb_cols:
        s1.append([label, sb.get(k) or ""])
    s1.column_dimensions["A"].width = 26
    s1.column_dimensions["B"].width = 60

    s2 = wb.create_sheet("Linked BLs")
    headers = ["Source File", *[label for _, label in _columns(bl_keys)]]
    s2.append(headers)
    for cell in s2[1]:
        cell.font = Font(bold=True)
    for b in bls:
        s2.append([b.get("_file", ""), *[(b.get(k) or "") for k, _ in _columns(bl_keys)]])
    for idx, header in enumerate(headers, start=1):
        col = [header] + [str(s2.cell(row=i + 2, column=idx).value or "") for i in range(len(bls))]
        s2.column_dimensions[get_column_letter(idx)].width = min(60, max(12, max(len(v) for v in col) + 2))
    s2.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_QTY_RE = re.compile(r"([\d][\d,]*(?:\.\d+)?)\s*([A-Za-z]+)?")


def _parse_qty(s: str | None) -> tuple[float, str] | None:
    if not s:
        return None
    m = _QTY_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "")), (m.group(2) or "").upper()
    except ValueError:
        return None


def _sum_quantities(values: list[str | None]) -> str:
    """Sums same-unit quantities (e.g. several SBs' "1234.5 KGS" package
    weights under one BL); different units are kept as separate totals
    rather than summed together incorrectly."""
    totals: dict[str, float] = {}
    for v in values:
        parsed = _parse_qty(v)
        if not parsed:
            continue
        num, unit = parsed
        totals[unit] = totals.get(unit, 0.0) + num
    if not totals:
        return ""
    return ", ".join(
        f"{total:g}" + (f" {unit}" if unit else "") for unit, total in totals.items()
    )


def sum_quantities_total(values: list[str | None]) -> str:
    """Public wrapper for ``_sum_quantities`` — used by the service layer to
    total a BL's linked Shipping Bills' packages/weight for the Summary file."""
    return _sum_quantities(values)


# --------------------------------------------- BL Data / BL + Shipping Bill
# xlsx: horizontal tabular layout (fields as columns, records as rows).
# pdf: one page per record, Field/Value rows under a bold title
# ("Bill of Lading: <number>" / "BL <number> — SB <number>").
def _bl_title(row: Row) -> str:
    return f"Bill of Lading: {row.get('bl_number') or row.get('_file') or 'Bill of Lading'}"


def _sb_title(bl_num: str, row: Row) -> str:
    sb_num = row.get("sb_number") or row.get("_file") or "Shipping Bill"
    return f"BL {bl_num} — SB {sb_num}"


def build_bl_data_xlsx(bl_rows: list[Row], bl_cols: list[tuple[str, str]]) -> bytes:
    """One row per Bill of Lading, columns = the full BL field set — the
    standard tabular layout, fields as columns and records as rows."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Bills of Lading"
    _tabular_sheet(
        ws,
        [label for _, label in bl_cols],
        [[row.get(k) or "" for k, _ in bl_cols] for row in bl_rows],
    )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_bl_sb_data_xlsx(
    sb_rows: list[tuple[str, Row]], sb_cols: list[tuple[str, str]],
) -> bytes:
    """One worksheet, one row per linked Shipping Bill — its "BL Number"
    leads each row so the parent BL stays identifiable without repeating
    that BL's own details."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Shipping Bills"
    _tabular_sheet(
        ws,
        ["BL Number"] + [label for _, label in sb_cols],
        [[bl_num] + [row.get(k) or "" for k, _ in sb_cols] for bl_num, row in sb_rows],
    )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _record_html(title: str, cols: list[tuple[str, str]], row: Row) -> str:
    return f"<h2>{html.escape(title)}</h2>{_fields_html(row, cols)}"


def build_bl_data_pdf(bl_rows: list[Row], bl_cols: list[tuple[str, str]]) -> bytes:
    doc = pymupdf.open()
    try:
        for r in bl_rows:
            page = doc.new_page(width=595, height=842)
            page.insert_htmlbox(
                pymupdf.Rect(36, 36, 559, 806), _record_html(_bl_title(r), bl_cols, r), css=_PDF_CSS
            )
        if doc.page_count == 0:
            doc.new_page(width=595, height=842)
        return doc.write()
    finally:
        doc.close()


def build_bl_sb_data_pdf(
    bl_rows: list[Row], bl_cols: list[tuple[str, str]],
    sb_rows: list[tuple[str, Row]], sb_cols: list[tuple[str, str]],
) -> bytes:
    doc = pymupdf.open()
    try:
        for r in bl_rows:
            page = doc.new_page(width=595, height=842)
            page.insert_htmlbox(
                pymupdf.Rect(36, 36, 559, 806), _record_html(_bl_title(r), bl_cols, r), css=_PDF_CSS
            )
        for bl_num, row in sb_rows:
            page = doc.new_page(width=595, height=842)
            page.insert_htmlbox(
                pymupdf.Rect(36, 36, 559, 806),
                _record_html(_sb_title(bl_num, row), sb_cols, row), css=_PDF_CSS,
            )
        if doc.page_count == 0:
            doc.new_page(width=595, height=842)
        return doc.write()
    finally:
        doc.close()


# ---------------------------------------------------------------- Summary
# xlsx: one row per unique HS code on a BL — BL No, the Shipping Bill No.
# it was found on, that code, and its matching description (IMO Code, UNO
# No, No. of Packages and Type of Packages aren't extracted, so left
# blank). A BL with no HS items at all still gets one (mostly blank) row so
# it isn't silently dropped from the file.
# pdf: one page per BL — SB reconciliation and cargo totals (unchanged).
_SUMMARY_XLSX_HEADERS = [
    "BL No", "Shipping Bill No.", "IMO Code", "UNO No", "HS Code",
    "Cargo Item Description", "No. of Packages", "Type of Packages",
]
_SUMMARY_COLS = [
    ("sb_total", "Linked Shipping Bills"), ("sb_matched", "Keyword Match"),
    ("sb_mismatched", "Keyword Mismatch"),
    ("sb_missing", "Missing (referenced, not uploaded)"), ("sb_duplicate", "Duplicate"),
    ("total_packages", "Total Packages (all linked SBs)"),
    ("total_gross_weight", "Total Gross Weight (all linked SBs)"),
]


def _summary_xlsx_rows(entry: dict) -> list[list[str]]:
    bl_no = entry["bl"].get("bl_number") or ""
    items = (entry.get("summary") or {}).get("hs_items") or []
    if not items:
        return [[bl_no, "", "", "", "", "", "", ""]]
    return [
        [bl_no, item.get("sb_number", ""), "", "", item.get("hs_code", ""),
         item.get("description", ""), "", ""]
        for item in items
    ]


# --------------------------------------------- Import: Master BL / House BL
# No field catalog exists yet for these two doc_types (see field_catalog.py —
# real samples are still needed to design one), so these three sheets carry
# document/linkage metadata rather than extracted BL fields. The shape
# mirrors Export's split (own-record sheet, linked-record sheet, summary
# sheet) so it's a drop-in once real field data lands.
_MASTER_BL_HEADERS = [
    "Job ID", "Filename", "Vessel", "Company", "Status", "Submitted",
    "House BL Count", "Uploaded At",
]
_MASTER_HOUSE_BL_HEADERS = [
    "Master Job ID", "Master Filename", "House BL Filename", "House BL Status",
]
_MASTER_BL_SUMMARY_HEADERS = [
    "Vessel", "Company", "Master BL Count", "House BL Count", "Submitted Count", "Pending Count",
]


def build_master_bl_data_xlsx(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Master BL Data"
    _tabular_sheet(ws, _MASTER_BL_HEADERS, [
        [r["job_id"], r["filename"], r["vessel"], r["company"], r["status"],
         r["submitted"], r["house_bl_count"], r["created_at"]]
        for r in rows
    ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_master_house_bl_xlsx(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Master + House BL"
    _tabular_sheet(ws, _MASTER_HOUSE_BL_HEADERS, [
        [r["master_job_id"], r["master_filename"], r["house_filename"], r["house_status"]]
        for r in rows
    ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_master_bl_summary_xlsx(entries: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    _tabular_sheet(ws, _MASTER_BL_SUMMARY_HEADERS, [
        [e["vessel"], e["company"], e["master_bl_count"], e["house_bl_count"],
         e["submitted_count"], e["master_bl_count"] - e["submitted_count"]]
        for e in entries
    ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_summary_xlsx(entries: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    rows = [row for entry in entries for row in _summary_xlsx_rows(entry)]
    _tabular_sheet(ws, _SUMMARY_XLSX_HEADERS, rows)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_summary_pdf(entries: list[dict]) -> bytes:
    doc = pymupdf.open()
    try:
        for entry in entries:
            s = entry.get("summary") or {}
            row = {k: str(s.get(k, "")) for k, _ in _SUMMARY_COLS}
            page = doc.new_page(width=595, height=842)
            page.insert_htmlbox(
                pymupdf.Rect(36, 36, 559, 806),
                _record_html(_bl_title(entry["bl"]), _SUMMARY_COLS, row), css=_PDF_CSS,
            )
        if doc.page_count == 0:
            doc.new_page(width=595, height=842)
        return doc.write()
    finally:
        doc.close()


def build_hierarchy_pdf(
    sb: Row, sb_keys: list[str], bls: list[Row], bl_keys: list[str]
) -> bytes:
    doc = pymupdf.open()
    try:
        bl_list = "".join(
            f"<li>{html.escape(b.get('_file') or '')}</li>" for b in bls
        ) or "<li>(none)</li>"
        page = doc.new_page(width=595, height=842)
        page.insert_htmlbox(
            pymupdf.Rect(36, 36, 559, 806),
            f"<h2>Shipping Bill — {html.escape(sb.get('_file') or '')}</h2>"
            f"<p class='sub'>{len(bls)} linked Bill(s) of Lading &nbsp;·&nbsp; "
            f"exported {date.today().isoformat()}</p>"
            f"{_fields_html(sb, _columns(sb_keys))}"
            f"<h3>Linked Bills of Lading</h3><ul>{bl_list}</ul>",
            css=_PDF_CSS,
        )
        for b in bls:
            p = doc.new_page(width=595, height=842)
            p.insert_htmlbox(
                pymupdf.Rect(36, 36, 559, 806), _doc_html(b, _columns(bl_keys)), css=_PDF_CSS
            )
        return doc.write()
    finally:
        doc.close()
