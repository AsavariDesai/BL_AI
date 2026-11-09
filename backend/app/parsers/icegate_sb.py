"""Parser for the Indian Customs EDI System (ICEGATE) Shipping Bill.

A fixed government form. Read by geometry, not by row order — bordered tables
scramble naive row grouping, so every value is found by:

  * locating the label token(s) (tolerant to '<n>.' prefixes and OCR merges), then
  * projecting DOWN a column (grid headers) or RIGHT along the same y-band
    (inline numbered fields), picking the value token by pattern.

Returns {field_key: (value, confidence)}. A field it cannot find is simply
omitted; the extractor then leaves it blank for the reviewer (it never falls
back to the generic label-anchor pass on this form).
"""
from __future__ import annotations

import re

from ..document import Document, Token

DOC_TYPE = "shipping_bill"

_HS_RE = re.compile(r"^\d{8}$")
_NUM_FIELD_RE = re.compile(r"^\d{1,2}[.)]")
_UNIT_RE = re.compile(r"^(MTS|MT|KGS|KG|LBS|TON|TONNES|NOS)$", re.I)
_FLOAT_RE = re.compile(r"^\d[\d,]*\.?\d*$")
_DATE_TOK_RE = re.compile(r"\d{1,2}[-/][A-Za-z]{3}[-/]\d{2,4}|\d{1,2}[./]\d{1,2}[./]\d{2,4}")
_PORT_RE = re.compile(r"^[A-Z]{3,6}\d?$")
_GSTIN_RE = re.compile(r"^\d{2}[A-Z0-9]{13}$")
_CCY_RE = re.compile(r"^[A-Z]{3}$")
_STOPWORDS = {
    "IEC", "BR", "IEC/BR", "GSTIN", "TYPE", "GSTIN/TYPE", "CB", "CODE", "CBCODE",
    "SB", "NO", "DATE", "INV", "ITEM", "CONT", "PKG", "NOS", "GWT", "G.WT",
    "PORT", "MODE", "SEA", "AIR",
}


def matches(doc: Document) -> bool:
    head = " ".join(t.text for t in doc.pages[0].tokens[:500]).upper()
    return (
        "INDIAN CUSTOMS EDI" in head
        or "SHIPPING BILL SUMMARY" in head
        or ("PORT CODE" in head and "SB NO" in head and "SB DATE" in head)
    )


def parse(doc: Document) -> dict[str, tuple[str, float]]:
    all_toks: list[Token] = [t for p in doc.pages for t in p.tokens]
    p1: list[Token] = list(doc.pages[0].tokens)   # SB summary lives on page 1;
    page_w = doc.pages[0].width or 595.0          # a flat multi-page list would
    full = " ".join(t.text for t in all_toks)     # collide y-coords across pages

    out: dict[str, tuple[str, float]] = {}
    _grid(p1, out, full)
    _pkg_gross(p1, out)
    _destination(p1, out, page_w)
    _inline_numbered(p1, out)
    _iec_br(p1, out)
    _extras(p1, out)

    # Exporter's Name & Address is printed on every page, but page 1 sometimes
    # truncates it under other header content — Page 2 carries the full block,
    # so prefer it and only fall back to page 1 for a single-page SB.
    p2: list[Token] = list(doc.pages[1].tokens) if len(doc.pages) > 1 else []
    _party(p2, out, page_w, "exporter",
           ("exportersnameaddress", "exportersname", "exportername", "exporter"),
           ("buyersname", "adcode", "fobvalue", "gstin", "cbname"), right=False,
           name_key="exporter_name", addr_key="shipper_address")
    if "exporter_name" not in out:
        _party(p1, out, page_w, "exporter",
               ("exportersnameaddress", "exportersname", "exportername", "exporter"),
               ("consigneename", "adcode", "fobvalue", "gstin", "cbname"), right=False,
               name_key="exporter_name", addr_key="shipper_address")

    # Page 1's "7.CONSIGNEE NAME & ADDRESS" is the B/L consignee — on a
    # negotiable shipment that's just "TO ORDER" + a country, not an actual
    # company. Page 2's "2.BUYER'S NAME & ADDRESS" (invoice terms) carries
    # the real buyer, so prefer it and only fall back to page 1 when the SB
    # is single-page or that block is missing.
    _party(p2, out, page_w, "buyer",
           ("buyersnameaddress", "buyersname", "buyer"),
           ("thirdpartynameaddress", "thirdparty", "buyeraeostatus"), right=True,
           name_key="consignee_name", addr_key="consignee_address", drop_to_the=True)
    if "consignee_name" not in out:
        _party(p1, out, page_w, "consignee",
               ("consigneenameaddress", "consigneename", "consignee"),
               ("gstin", "forexbank", "adcode", "fobvalue", "ifsc", "dbkbank"), right=True,
               name_key="consignee_name", addr_key="consignee_address", drop_to_the=True)
    _hs_codes(all_toks, out)                       # item details span later pages
    return {k: v for k, v in out.items() if v[0]}


# --------------------------------------------------------------------- helpers
def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" :;,-\t|")


def _denum(s: str) -> str:
    return re.sub(r"^\d{1,2}[.)]", "", s).lower().strip(" :.")


def _cx(t: Token) -> float:
    return (t.x0 + t.x1) / 2


def _cy(t: Token) -> float:
    return (t.y0 + t.y1) / 2


_ALNUM_RE = re.compile(r"[^a-z0-9]")


def _find_label(toks: list[Token], phrase: str, *, after_y: float = -1.0):
    """First (start, end) token pair whose concatenated de-numbered,
    alphanumerics-only text contains ``phrase``. Tolerates '13.COUNTRY',
    "EXPORTER'S", '&' separators and OCR-merged runs."""
    target = _ALNUM_RE.sub("", phrase.lower())
    if not target:
        return None
    for i in range(len(toks)):
        if toks[i].y0 <= after_y:
            continue
        y0 = toks[i].y0
        acc = ""
        for j in range(i, min(i + 9, len(toks))):
            if abs(toks[j].y0 - y0) > 4.0:      # only accumulate within one line
                break
            acc += _ALNUM_RE.sub("", _denum(toks[j].text))
            if target in acc:
                return toks[i], toks[j]
            if len(acc) > len(target) + 30:
                break
    return None


def _row_after(toks: list[Token], anchor: Token, *, y_tol: float = 6.0,
               max_tokens: int = 16, stop_num: bool = True) -> list[str]:
    same = sorted(
        (t for t in toks if abs(_cy(t) - _cy(anchor)) <= y_tol and t.x0 >= anchor.x1 - 2),
        key=lambda t: t.x0,
    )
    picked: list[str] = []
    for t in same:
        if stop_num and _NUM_FIELD_RE.match(t.text) and picked:
            break
        picked.append(t.text)
        if len(picked) >= max_tokens:
            break
    return picked


def _col_below(toks: list[Token], header_end: Token, col_cx: float, x_half: float,
               match: re.Pattern, *, y_max: float = 60.0):
    cands = [
        t for t in toks
        if header_end.y1 - 3 <= t.y0 <= header_end.y1 + y_max
        and abs(_cx(t) - col_cx) <= x_half
        and match.fullmatch(t.text.strip("|"))
    ]
    cands.sort(key=lambda t: (t.y0, abs(_cx(t) - col_cx)))
    return cands[0].text.strip("|") if cands else ""


def _value_in_column(toks: list[Token], anchor_end: Token, *, match: re.Pattern,
                     y_lo: float = -26.0, y_hi: float = 44.0, x_half: float = 80.0):
    """Value token in the label's x-column, in the row just above OR below it —
    for cells where the value is stacked under (or over) the label, not beside."""
    cx = _cx(anchor_end)
    cands = [
        t for t in toks
        if t is not anchor_end
        and anchor_end.y1 + y_lo <= _cy(t) <= anchor_end.y1 + y_hi
        and abs(_cx(t) - cx) <= x_half
        and match.fullmatch(t.text.strip("|"))
    ]
    cands.sort(key=lambda t: (abs(_cy(t) - anchor_end.y1), abs(_cx(t) - cx)))
    return cands[0].text.strip("|") if cands else ""


# --------------------------------------------------------- top-right grid
def _grid(toks: list[Token], out: dict, full: str) -> None:
    hdr_no = _find_label(toks, "sb no") or _find_label(toks, "sbno")
    hdr_date = _find_label(toks, "sb date") or _find_label(toks, "sbdate")
    hdr_port = _find_label(toks, "port code") or _find_label(toks, "portcode")

    col_gap = 55.0
    if hdr_no and hdr_date:
        col_gap = max(30.0, abs(_cx(hdr_date[0]) - _cx(hdr_no[-1])))
    half = col_gap / 2 + 8

    if hdr_no:
        v = _col_below(toks, hdr_no[-1], _cx(hdr_no[-1]), max(half, 32),
                       re.compile(r"\d{6,8}"))
        if not v:
            m = re.search(r"SB\s*No\.?\s*[:\-]?\s*(\d{6,8})", full, re.I)
            v = m.group(1) if m else ""
        if v:
            out["sb_number"] = (v, 0.95 if v else 0.0)

    if hdr_date:
        v = _col_below(toks, hdr_date[-1], _cx(hdr_date[-1]), max(half, 40), _DATE_TOK_RE)
        if v:
            out["sb_date"] = (v, 0.95)

    if hdr_port:
        col_cx = _cx(hdr_port[-1])
        cands = [
            t for t in toks
            if hdr_port[-1].y1 - 3 <= t.y0 <= hdr_port[-1].y1 + 60
            and abs(_cx(t) - col_cx) <= max(half, 40)
            and _PORT_RE.fullmatch(t.text.strip("|").upper())
            and t.text.strip("|").upper() not in _STOPWORDS
        ]
        cands.sort(key=lambda t: (t.y0, abs(_cx(t) - col_cx)))
        if cands:
            out["sb_field_location"] = (cands[0].text.strip("|"), 0.9)


# ----------------------------------------------------------- PKG / gross wt
def _pkg_gross(toks: list[Token], out: dict) -> None:
    pkg = next((t for t in toks if t.text.upper().strip("|.") == "PKG"), None)
    if not pkg:
        return
    # stay within the grid row: same y-band, just right of "PKG", not far right
    band = sorted(
        (t for t in toks
         if abs(_cy(t) - _cy(pkg)) <= 4.0
         and pkg.x1 - 2 <= t.x0 <= pkg.x1 + 160),
        key=lambda t: t.x0,
    )
    num_toks = [t for t in band if _FLOAT_RE.fullmatch(t.text.strip("|").replace(",", ""))]
    unit_toks = [t for t in band if _UNIT_RE.fullmatch(t.text.strip("|"))]
    # The package count is a bare 1-2 digit number and the weight is printed
    # as "G.WT <unit> <value>" (unit before value) while we report it as
    # "<value> <unit>" — both shapes defeat the generic page-text locator
    # (too short to search reliably / wrong order to match verbatim), so the
    # PDF viewer would never highlight anything for these two fields. Carry
    # each value's own grid-cell bbox directly instead of relying on that
    # after-the-fact text search — see anchor_extractor._locate_value and its
    # "__bbox__:<key>" override lookup.
    if num_toks:
        t = num_toks[0]
        out["sb_packages"] = (t.text.strip("|"), 0.9)
        out["__bbox__:sb_packages"] = (1, (t.x0, t.y0, t.x1, t.y1))
    if len(num_toks) >= 2:
        wt_tok = num_toks[-1]
        unit_tok = unit_toks[0] if unit_toks else None
        unit_text = unit_tok.text.strip("|") if unit_tok else ""
        out["sb_gross_weight"] = (_clean(f"{wt_tok.text.strip('|')} {unit_text}"), 0.9)
        cell = [wt_tok, unit_tok] if unit_tok else [wt_tok]
        out["__bbox__:sb_gross_weight"] = (
            1, (min(c.x0 for c in cell), min(c.y0 for c in cell),
                max(c.x1 for c in cell), max(c.y1 for c in cell)),
        )


# ------------------------------------------------------ final destination
def _destination(toks: list[Token], out: dict, page_w: float) -> None:
    country = port = ""
    lbl = _find_label(toks, "country of final destination")
    if lbl:
        country = _clean(" ".join(_row_after(toks, lbl[1], y_tol=6, max_tokens=6)))
    lbl = _find_label(toks, "port of final destination")
    if lbl:
        port = _clean(" ".join(_row_after(toks, lbl[1], y_tol=6, max_tokens=6)))
    dest = ", ".join(x for x in (port, country) if x)
    if dest:
        out["sb_destination"] = (_clean(dest), 0.88)


# ------------------------------------------------ CIN / LEO / nature-of-cargo
_CIN_RE = re.compile(r"[A-Z0-9]{12,30}")
_WORD_RE = re.compile(r"[A-Za-z]{4,}")


def _inline_numbered(toks: list[Token], out: dict) -> None:
    # CIN No. / CIN Dt. — value is stacked UNDER the label
    lbl = _find_label(toks, "cin no")
    if lbl:
        cin = _value_in_column(toks, lbl[1], match=_CIN_RE, y_lo=2, y_hi=40, x_half=75)
        dl = _find_label(toks, "cin dt") or _find_label(toks, "cin date")
        dt = _value_in_column(toks, dl[1], match=_DATE_TOK_RE, y_lo=2, y_hi=40,
                              x_half=75) if dl else ""
        if cin:
            out["cin_number"] = (cin, 0.9)
        if dt:
            out["cin_date"] = (dt, 0.85)

    # LEO No. / LEO Date — value is BESIDE the label
    lbl = _find_label(toks, "leo no")
    if lbl:
        v = _clean(" ".join(_row_after(toks, lbl[1], y_tol=6, max_tokens=2)))
        if v:
            out["leo_number"] = (v.split()[0], 0.9)

    lbl = _find_label(toks, "leo date") or _find_label(toks, "leodate")
    if lbl:
        m = _DATE_TOK_RE.search(" ".join(_row_after(toks, lbl[1], y_tol=6, max_tokens=4)))
        if not m:
            v = _value_in_column(toks, lbl[1], match=_DATE_TOK_RE, y_lo=2, y_hi=40)
            m = _DATE_TOK_RE.search(v)
        if m:
            out["leo_date"] = (m.group(0), 0.9)

    # Nature of cargo — in the ICEGATE annex table the value sits in the row
    # ABOVE the label ("WAREHOUSE SEALED  PACKAGED  71 ...").
    lbl = _find_label(toks, "nature of cargo")
    if lbl:
        v = _value_in_column(toks, lbl[1], match=_WORD_RE, y_lo=-26, y_hi=4, x_half=70)
        if v and v.upper() not in ("NATURE", "CARGO", "SEAL", "TYPE", "WAREHOUSE"):
            out["nature_of_cargo"] = (v.upper(), 0.85)


_IEC_VAL_RE = re.compile(r"^[A-Z0-9]{10}$")


def _iec_br(toks: list[Token], out: dict) -> None:
    """IEC/Br sits in the running header on every page: label and value are on
    the same row ('IEC/Br  0797000119'), not stacked."""
    lbl = _find_label(toks, "iec/br") or _find_label(toks, "iec br") or _find_label(toks, "iec")
    if not lbl:
        return
    for raw in _row_after(toks, lbl[1], y_tol=4, max_tokens=4):
        v = raw.strip("|").upper()
        if _IEC_VAL_RE.fullmatch(v) and v not in _STOPWORDS:
            out["shipper_code"] = (v, 0.92)
            return


def _extras(toks: list[Token], out: dict) -> None:
    # GST / GSTIN — same row as its label in the running header
    # ("GSTIN/TYPE  33AAICS1940E1ZO GSN").
    lbl = _find_label(toks, "gstin")
    if lbl:
        for raw in _row_after(toks, lbl[1], y_tol=4, max_tokens=4):
            v = raw.strip("|").upper()
            if _GSTIN_RE.fullmatch(v):
                out["gstin"] = (v, 0.9)
                break

    # Marks & Numbers — free text beside its label on the I.ANNEX table
    # ('6.MARKS & NUMBERS  AS PER INVOICE ("WE INTEND...")').
    lbl = _find_label(toks, "marks & numbers") or _find_label(toks, "marks numbers")
    if lbl:
        v = _clean(" ".join(_row_after(toks, lbl[1], y_tol=6, max_tokens=24)))
        if v:
            out["marks_and_numbers"] = (v, 0.8)

    # Invoice Amount / Currency — the E.MANIFEST table's own small grid
    # ('3.INV AMT.  4.CURRENCY' labels, values stacked in the row below).
    lbl = _find_label(toks, "inv amt") or _find_label(toks, "invoice amount")
    if lbl:
        v = _value_in_column(toks, lbl[1], match=_FLOAT_RE, y_lo=2, y_hi=20, x_half=40)
        if v:
            out["invoice_amount"] = (v, 0.85)

    # The real form sometimes clips the printed label to "CURRENC" (column
    # too narrow for the full word) — search on the shorter stem.
    lbl = _find_label(toks, "currenc")
    if lbl:
        v = _value_in_column(toks, lbl[1], match=_CCY_RE, y_lo=2, y_hi=20, x_half=40)
        if v:
            out["currency"] = (v, 0.85)


# --------------------------------------------------------------- party blocks
def _lines(band: list[Token], y_tol: float = 5.0) -> list[list[Token]]:
    out_lines: list[list[Token]] = []
    for t in sorted(band, key=lambda t: (t.y0, t.x0)):
        if out_lines and abs(t.y0 - out_lines[-1][0].y0) <= y_tol:
            out_lines[-1].append(t)
        else:
            out_lines.append([t])
    for ln in out_lines:
        ln.sort(key=lambda t: t.x0)
    return out_lines


# A narrow rotated section label runs down the far left margin of every page
# ("TRANSACTION PARTIES", "DECLARANT DETAILS", …). Its words can land within a
# line-height of the real party block and merge into it — drop the tokens
# themselves (not just whole lines) so they can never leak into an address.
_PARTY_NOISE_WORDS = {"TRANSACTION", "PARTIES", "DECLARANT", "DETAILS", "DECLARAN"}


def _party(toks, out, page_w, tag, start_phrases, stop_phrases, *, right,
           name_key, addr_key, drop_to_the=False) -> None:
    start = None
    for ph in start_phrases:
        start = _find_label(toks, ph)
        if start:
            break
    if not start:
        return
    top = start[1].y1
    mid = page_w / 2
    side = [
        t for t in toks
        if (_cx(t) >= mid) == right and t.text.strip("|.,").upper() not in _PARTY_NOISE_WORDS
    ]

    bottom = top + 90
    for ph in stop_phrases:
        f = _find_label([t for t in side if t.y0 > top + 2], ph)
        if f:
            bottom = min(bottom, f[0].y0)

    band = [t for t in side if top - 1 <= t.y0 < bottom]
    texts: list[str] = []
    for ln in _lines(band):
        parts: list[str] = []
        for t in ln:
            if _NUM_FIELD_RE.match(t.text):   # a numbered sub-field starts here
                break
            parts.append(t.text)
        s = _clean(" ".join(parts))
        if not s or any(
            _denum(s).replace(" ", "").startswith(p) for p in stop_phrases
        ):
            continue
        texts.append(s)

    if drop_to_the:
        while texts and re.fullmatch(r"TO(\s+THE)?", texts[0].upper()):
            texts.pop(0)
    if texts:
        out[name_key] = (texts[0], 0.85)
        if len(texts) > 1:
            out[addr_key] = (_clean(", ".join(texts[1:])), 0.8)


# ------------------------------------------------------------------- HS codes
def _hs_codes(toks: list[Token], out: dict) -> None:
    # The description scan below walks forward through ``toks`` assuming
    # visual reading order (page, top-to-bottom, left-to-right) — the raw
    # per-page token order from the PDF isn't guaranteed to match that (a
    # second invoice row's own HS code can land right after the first row's
    # HS code, ahead of that first row's own wrapped description text),
    # which silently truncated every description to nothing.
    toks = sorted(toks, key=lambda t: (t.page, round(t.y0), t.x0))
    seen: list[str] = []
    pairs: list[tuple[str, str]] = []
    for i, t in enumerate(toks):
        code = t.text.strip("|")
        if not _HS_RE.fullmatch(code) or not (1 <= int(code[:2]) <= 97):
            continue
        if code in seen:
            continue
        seen.append(code)
        desc: list[str] = []
        # A long description wraps across several close rows — track the gap
        # to the row just seen (not the fixed original anchor), or only the
        # first wrapped line is ever captured. Only the next item's own HS
        # code ends the scan outright — the Quantity/Rate/Value columns sit
        # inline on the description's own first row (to its right), so
        # breaking on any numeric token would stop before ever reaching the
        # wrapped continuation line below. Instead, a large x-gap from the
        # last column-accepted token *on the same row* marks a jump into one
        # of those other columns — skip just that cell (not the whole scan),
        # since the first token of the next row is always accepted again.
        last_y = _cy(t)
        prev = t
        for nxt in toks[i + 1:]:
            if nxt.page != t.page or _cy(nxt) - last_y > 11:
                break
            txt = nxt.text.strip("|")
            if _HS_RE.fullmatch(txt):
                break
            same_row = round(nxt.y0) == round(prev.y0)
            if same_row and nxt.x0 - prev.x1 > 35:
                continue
            if any(c.isalpha() for c in txt):
                desc.append(txt)
            last_y = _cy(nxt)
            prev = nxt
            if len(desc) >= 22:
                break
        pairs.append((code, _clean(" ".join(desc))))
    if seen:
        out["hs_code"] = (", ".join(seen), 0.85)
        # Keep one description slot per code, even a blank one, so
        # ``hs_code``'s comma list and ``cargo_description``'s newline list
        # stay aligned 1:1 by position — filtering out blanks here would
        # silently shift every later description out of step with its code.
        descs = [d for _, d in pairs]
        if any(descs):
            out["cargo_description"] = ("\n".join(descs), 0.75)


def scan_hs_codes(doc: Document) -> dict[str, tuple[str, float]]:
    """Multi-page HS code + description item-table scan, usable for ANY
    Shipping Bill layout — not just a document the ICEGATE template
    recognises (see ``matches`` above). A plain single-label locator only
    catches the first item's code/description on a form with several line
    items spread across its invoice/item-detail pages; this walks every
    page's tokens the same way ``parse`` does internally."""
    all_toks = [t for p in doc.pages for t in p.tokens]
    out: dict[str, tuple[str, float]] = {}
    _hs_codes(all_toks, out)
    return out


