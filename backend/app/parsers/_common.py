"""Shared geometry helpers for form parsers (list order in a PDF's text layer is
not visual order, so everything works off token coordinates)."""
from __future__ import annotations

import re

from ..document import Token

_ALNUM_RE = re.compile(r"[^a-z0-9]")
_NUM_FIELD_RE = re.compile(r"^\d{1,2}[.)]")
_DATE_TOK_RE = re.compile(
    r"\d{1,2}[-/][A-Za-z]{3}[-/]\d{2,4}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}"
)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip(" :;,-\t|")


# --- party-block splitting (Name / Address / State) --------------------------
INDIAN_STATES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa",
    "gujarat", "haryana", "himachal pradesh", "jharkhand", "karnataka", "kerala",
    "madhya pradesh", "maharashtra", "manipur", "meghalaya", "mizoram", "nagaland",
    "odisha", "orissa", "punjab", "rajasthan", "sikkim", "tamil nadu", "telangana",
    "tripura", "uttar pradesh", "uttarakhand", "west bengal", "delhi", "new delhi",
    "jammu and kashmir", "ladakh", "puducherry", "chandigarh",
    "dadra and nagar haveli", "daman and diu", "andaman and nicobar islands",
}
US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
}
_US_ABBR = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy",
}
_US_ZIP_RE = re.compile(r"\b([A-Z]{2})\s*\d{5}(?:-\d{4})?\b")

# Foreign shippers rarely carry a province line — fall back to the country.
COUNTRY_AS_STATE = {
    "india", "germany", "spain", "italy", "italia", "china", "france", "netherlands",
    "united kingdom", "uk", "usa", "united states", "u.s.a", "uae",
    "united arab emirates", "poland", "belgium", "turkey", "vietnam", "thailand",
    "singapore", "malaysia", "indonesia", "japan", "korea", "south korea", "taiwan",
    "p.r.china", "pr china", "hong kong", "bangladesh", "sri lanka", "nepal",
}
_ID_LINE_RE = re.compile(
    r"^(IEC|IE CODE|GST(?:IN|N)?|PAN|TEL|FAX|E-?MAIL|EMAIL|CTC|BOARD NO|PH|PHONE|MOB|"
    r"CONTACT|ATTN)\b[.: ]",
    re.I,
)
_EMAIL_LINE_RE = re.compile(r"^\S+@\S+\.\S+$")
_BOILER_RE = re.compile(
    r"\b(hereof|whereof|hereunder|herewith|shall be|clause paramount|"
    r"terms and conditions|in witness|apparent good order|by the carrier|"
    r"carrier.?s liability|the merchant shall|gross weight measurement|"
    r"consignee.?s reference|shipper.?s reference|according information|"
    r"dispute arising|court of milan|claim or dispute)\b",
    re.I,
)


def looks_like_boilerplate(s: str) -> bool:
    """True for legal-clause / column-header text that is not a real field value.

    Company names are frequently ALL-CAPS ("CARRIER AIRCONDITIONING LIMITED"),
    so the lower-case-ratio test is what separates prose from a name.
    """
    if not s:
        return False
    words = s.split()
    lower = sum(w[:1].islower() for w in words)
    if len(words) > 9 and lower >= len(words) * 0.45:
        return True
    return bool(_BOILER_RE.search(s)) and len(words) > 5 and lower >= 2


def _detect_state(line: str) -> tuple[str, str] | None:
    """(state, line_without_the_state_tail) if a state/country is in ``line``.

    A real sub-national state anywhere in the line wins over a country, so
    "GURGAON, HARYANA # 122001, INDIA" yields HARYANA, not INDIA. A
    multi-word state matches whether or not it's actually spaced in the
    source — real addresses commonly run it together ("TAMILNADU" for
    "TAMIL NADU"), which a plain substring check never catches.
    """
    low = " " + re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", line.lower())).strip() + " "
    for st in sorted(INDIAN_STATES | US_STATES, key=len, reverse=True):
        pat = r"\b" + r"\s*".join(re.escape(w) for w in st.split(" ")) + r"\b"
        if re.search(pat, line, re.I):
            cut = re.sub(r"[\s,]*" + pat + r".*$", "", line,
                         flags=re.I).strip(" ,")
            return st.upper(), cut
    zm = _US_ZIP_RE.search(line)
    if zm and zm.group(1).lower() in _US_ABBR:
        cut = line[: zm.start()].strip(" ,")
        return zm.group(1).upper(), cut
    for c in sorted(COUNTRY_AS_STATE, key=len, reverse=True):
        if low.strip() == c or low.endswith(" " + c + " "):
            cut = re.sub(r"[\s,]*" + re.escape(c) + r"\s*$", "", line,
                         flags=re.I).strip(" ,")
            return c.upper(), cut
    return None


def split_party(lines: list[str]) -> tuple[str, str, str]:
    """Split a party block into (name, address, state).

    name  = first line
    state = a recognised Indian state, else the country (for foreign parties)
    address = the remaining lines, minus identifier lines (IEC/GST/PAN/…)
    """
    clean = [_clean(x) for x in lines if _clean(x)]
    if not clean:
        return "", "", ""
    name = clean[0]
    rest = clean[1:]

    state = ""
    body: list[str] = []
    for ln in rest:
        if _ID_LINE_RE.match(ln) or _EMAIL_LINE_RE.match(ln):
            continue
        hit = _detect_state(ln)
        if hit and not state:
            state, remainder = hit
            if remainder:
                body.append(remainder)
        else:
            body.append(ln)
    # a trailing line that is only the country adds nothing once the state is set
    if state and body and body[-1].strip().lower().strip(" .,") in COUNTRY_AS_STATE:
        body.pop()
    address = _clean(", ".join(body))
    return name, address, state


def _denum(s: str) -> str:
    return re.sub(r"^\d{1,2}[.)]", "", s).lower().strip(" :.")


def _cx(t: Token) -> float:
    return (t.x0 + t.x1) / 2


def _cy(t: Token) -> float:
    return (t.y0 + t.y1) / 2


def _find_label(toks: list[Token], phrase: str, *, after_y: float = -1.0):
    """First (start, end) token pair whose concatenated de-numbered,
    alphanumerics-only text (within one text line) contains ``phrase``."""
    target = _ALNUM_RE.sub("", phrase.lower())
    if not target:
        return None
    for i in range(len(toks)):
        if toks[i].y0 <= after_y:
            continue
        y0 = toks[i].y0
        acc = ""
        for j in range(i, min(i + 9, len(toks))):
            if abs(toks[j].y0 - y0) > 4.0:
                break
            acc += _ALNUM_RE.sub("", _denum(toks[j].text))
            if target in acc:
                return toks[i], toks[j]
            if len(acc) > len(target) + 30:
                break
    return None


def _lines(band: list[Token], y_tol: float = 5.0) -> list[list[Token]]:
    out: list[list[Token]] = []
    for t in sorted(band, key=lambda t: (t.y0, t.x0)):
        if out and abs(t.y0 - out[-1][0].y0) <= y_tol:
            out[-1].append(t)
        else:
            out.append([t])
    for ln in out:
        ln.sort(key=lambda t: t.x0)
    return out


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


def _value_in_column(toks: list[Token], anchor_end: Token, *, match: re.Pattern,
                     y_lo: float = -26.0, y_hi: float = 44.0, x_half: float = 80.0):
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


def _cell_below(toks: list[Token], anchor_end: Token, *,
                y_lo: float = 2.0, y_hi: float = 17.0, x_half: float = 90.0) -> str:
    """Full text of the cell directly beneath ``anchor_end`` (all tokens on the
    nearest row within the label's x-column)."""
    cx = _cx(anchor_end)
    below = [
        t for t in toks
        if anchor_end.y1 + y_lo <= _cy(t) <= anchor_end.y1 + y_hi
        and abs(_cx(t) - cx) <= x_half
    ]
    if not below:
        return ""
    y0 = min(t.y0 for t in below)
    row = sorted((t for t in below if abs(t.y0 - y0) <= 4), key=lambda t: t.x0)
    return _clean(" ".join(t.text for t in row))


def _party_lines(toks: list[Token], page_w: float, start_phrases, stop_phrases, *,
                 right: bool, drop_re: re.Pattern | None = None,
                 reach: float = 80.0, mid_frac: float | None = None) -> list[str]:
    """Cleaned text lines of a labelled party box (below its label, one page side),
    stopping numbered sub-fields inside a line and at any stop phrase.

    ``mid_frac`` sets the page-side split (default 0.48 for the left side); pass a
    smaller value on forms with a narrow party column next to a wide right cell.
    """
    start = None
    for ph in start_phrases:
        start = _find_label(toks, ph)
        if start:
            break
    if not start:
        return []
    # a value line can sit almost flush under its label; -6 lets it in, and the
    # label's own row (further up) is dropped by the start-phrase filter below.
    top = start[1].y1 - 6
    mid = page_w * (mid_frac if mid_frac is not None else (0.5 if right else 0.48))
    side = [t for t in toks if (_cx(t) >= mid) == right]

    bottom = top + reach
    for ph in stop_phrases:
        f = _find_label([t for t in side if t.y0 > top + 2], ph)
        if f:
            bottom = min(bottom, f[0].y0)

    out: list[str] = []
    for ln in _lines([t for t in side if top - 1 <= t.y0 < bottom]):
        parts: list[str] = []
        for t in ln:
            if _NUM_FIELD_RE.match(t.text):
                break
            parts.append(t.text)
        s = _clean(" ".join(parts))
        low = _ALNUM_RE.sub("", s.lower())
        if (not s or any(low.startswith(p) for p in start_phrases)
                or any(sp in low for sp in stop_phrases)):
            continue
        if drop_re and drop_re.fullmatch(s.strip()):
            continue
        out.append(s)
    return out
