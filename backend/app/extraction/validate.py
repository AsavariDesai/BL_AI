"""Field normalisation + validation helpers.

Used to (a) clean extracted values, (b) compute a validation signal that feeds
into confidence, and (c) surface cross-field warnings in the review UI.
"""
from __future__ import annotations

import re

CONTAINER_RE = re.compile(r"\b[A-Z]{4}\s?\d{7}\b")
_DATE_FORMATS = (
    "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y",
    "%d-%b-%Y", "%d %b. %Y", "%Y-%m-%d", "%b %d %Y", "%B %d %Y", "%d.%m.%y",
    "%b.%d.%Y", "%b.%d.%y", "%d-%b-%y", "%d.%b.%Y", "%d %b.%Y",
    "%d/%m/%y", "%d-%m-%y", "%m/%d/%y", "%m/%d/%Y",
)


def _iso6346_char_value(ch: str) -> int:
    """Digit -> itself; letter -> ISO 6346 value (A=10..Z=38, skipping /11)."""
    if ch.isdigit():
        return int(ch)
    value = 10
    for code in range(ord("A"), ord("Z") + 1):
        if value % 11 == 0:
            value += 1
        if code == ord(ch):
            return value
        value += 1
    raise ValueError(f"not an A-Z letter: {ch!r}")


def container_check_digit_ok(container: str) -> bool:
    """Validate an ISO 6346 container number (4 letters + 6 digits + check)."""
    c = re.sub(r"[^A-Z0-9]", "", container.upper())
    if not re.fullmatch(r"[A-Z]{4}\d{7}", c):
        return False
    total = sum(_iso6346_char_value(ch) * (2 ** i) for i, ch in enumerate(c[:10]))
    return total % 11 % 10 == int(c[10])


def find_container_numbers(text: str) -> list[str]:
    """Every ISO-6346-shaped container number in ``text``.

    Tolerates at most one OCR-inserted space inside the number itself
    (``\\s?`` between the letter and digit runs), but — unlike an earlier
    version of this function — never strips whitespace from the rest of
    the text first: doing that glued every token in a page into one run,
    so two completely unrelated fields sitting next to each other (e.g.
    "...DELHI" followed by a service contract number "R00000568F8") could
    accidentally form a container-shaped substring ("LHIR0000056") right
    at their boundary. The ``\\b`` word boundaries plus the real spacing
    between tokens is what actually prevents that cross-field false match.
    """
    return [re.sub(r"\s+", "", m) for m in CONTAINER_RE.findall(text.upper())]


def normalize_date(value: str) -> str | None:
    """Return an ISO date string if ``value`` contains a parseable date."""
    from datetime import datetime

    match = re.search(
        r"\d{1,4}[.\-/ ][A-Za-z.]{2,9}[.\-/ ]\d{2,4}|\d{1,4}[.\-/]\d{1,2}[.\-/]\d{2,4}",
        value,
    )
    candidate = (match.group(0) if match else value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_quantity(value: str) -> tuple[float, str] | None:
    """'29,500.000 KGS' -> (29500.0, 'KGS'). Returns None if no number found."""
    m = re.search(r"([\d][\d,]*\.?\d*)\s*([A-Za-z.]{1,6})?", value.replace(" ", " "))
    if not m:
        return None
    try:
        number = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = (m.group(2) or "").upper().strip(".")
    return number, unit


def cross_field_warnings(values: dict[str, str | None]) -> list[str]:
    warnings: list[str] = []

    gross = parse_quantity(values.get("gross_weight") or "")
    net = parse_quantity(values.get("net_weight") or "")
    if gross and net and net[0] > gross[0] > 0:
        warnings.append(
            f"Net weight ({net[0]}) exceeds gross weight ({gross[0]}) — check both."
        )

    containers = find_container_numbers(values.get("container_and_seal_numbers") or "")
    for c in containers:
        if not container_check_digit_ok(c):
            warnings.append(f"Container number {c} fails its ISO 6346 check digit.")

    if (values.get("shipped_on_board_date")
            and not normalize_date(values["shipped_on_board_date"])):
        warnings.append(
            f"Could not parse shipped-on-board date "
            f"{values['shipped_on_board_date']!r}."
        )

    return warnings
