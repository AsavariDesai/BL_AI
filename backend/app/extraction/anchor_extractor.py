"""Tier A extraction: label-anchor + geometry. No training, no network.

For each canonical field:
  1. Find the printed label on the page by fuzzy-matching token n-grams against
     the field's known aliases (rapidfuzz).
  2. Read the value from the tokens immediately to the right of the label, or —
     if nothing usable is there — from the lines directly beneath it, within the
     same column band.
  3. Normalise / validate and score confidence from
     (label match strength) x (value found) x (validation passed).

A few fields (container numbers, document type, freight terms) use dedicated
regex/keyword passes instead, because they have no single reliable label.

This engine is deliberately simple. Its real purpose is to be good enough to run
day one and to generate the corrected examples that train the Tier B model.
"""
from __future__ import annotations

import re
from typing import Callable

from rapidfuzz import fuzz

from ..document import Document, Token, group_rows, load_document
from ..field_catalog import catalog, field_keys, get_field
from ..formats import format_key
from ..parsers import parse_with_template
from ..parsers.icegate_sb import scan_hs_codes
from ..models import ExtractionResult, FieldValue
from .base import Extractor
from .validate import (
    container_check_digit_ok,
    cross_field_warnings,
    normalize_date,
    parse_quantity,
)

_LABEL_MATCH_MIN = 82          # rapidfuzz score (0-100) to accept a label hit
_MAX_LABEL_NGRAM = 5
_VALUE_STRIP = " :;.-–—|\t"

_LOCATE_MIN_LEN = 4            # needles shorter than this are too easy to match by chance
_LOCATE_PREFIX = 80            # long values (addresses, descriptions) match on a solid prefix


class _PageTextIndex:
    """One page's tokens as a single uppercased string, plus which token(s)
    cover each character offset — lets a value string built by a template
    parser (regex/geometry, no token references kept) be found again after
    the fact, so the PDF viewer can still highlight it on click.
    """

    def __init__(self, page) -> None:
        toks = sorted(page.tokens, key=lambda t: (round(t.y0), t.x0))
        parts: list[str] = []
        self.spans: list[tuple[int, int, Token]] = []
        pos = 0
        for t in toks:
            piece = re.sub(r"\s+", " ", t.text).strip()
            if not piece:
                continue
            if parts:
                parts.append(" ")
                pos += 1
            start = pos
            parts.append(piece)
            pos += len(piece)
            self.spans.append((start, pos, t))
        self.text = "".join(parts).upper()

    def find(self, needle: str) -> list[float] | None:
        idx = self.text.find(needle)
        if idx < 0:
            return None
        end = idx + len(needle)
        hit = [t for (s, e, t) in self.spans if s < end and e > idx]
        if not hit:
            return None
        return [min(t.x0 for t in hit), min(t.y0 for t in hit),
                max(t.x1 for t in hit), max(t.y1 for t in hit)]


def _locate_value(
    page_index: list["_PageTextIndex"], value: str
) -> tuple[int | None, list[float] | None]:
    cleaned = re.sub(r"\s+", " ", value).strip().upper()
    # a parser-joined multi-line value (address, multi-value list) rarely
    # matches the page verbatim — but its first clause usually is an
    # unmodified source line, so that's worth a second try.
    needles = [cleaned[:_LOCATE_PREFIX], cleaned.split(",")[0].split("\n")[0][:_LOCATE_PREFIX]]
    for needle in dict.fromkeys(needles):  # dedupe, keep order
        if len(needle) < _LOCATE_MIN_LEN:
            continue
        for page_no, idx in enumerate(page_index, start=1):
            bbox = idx.find(needle)
            if bbox is not None:
                return page_no, bbox
    return None, None
_TITLES = [
    "combined transport bill of lading",
    "multimodal transport bill of lading",
    "liner bill of lading",
    "bill of lading",
    "sea waybill",
    "house bill of lading",
    "ocean bill of lading",
]
_FREIGHT_RE = re.compile(r"freight\s+(prepaid|collect|payable[^,\n]*)", re.I)
_CONTAINER_RE = re.compile(r"\b([A-Z]{4}\s?\d{7})\b")

# Shipping Bill references carried on a Bill of Lading. A single BL often
# consolidates cargo cleared under several Shipping Bills.
_SB_LABEL = r"(?:\bSHIPPING\s*BILL\b|\bS[./]\s?B\b|\bS\.?B\.?\s*NO\b)"
_SB_REF_RE = re.compile(
    _SB_LABEL + r"\s*(?:NO|NOS|NUMBER|#)?\.?\s*[:.\-]?\s*"
    r"(\d{6,8})\s*(?:(?:DT|DATED|DATE)\.?\s*[:.]?\s*([0-3]?\d[./\-][01]?\d[./\-]\d{2,4}))?",
    re.I,
)
_SB_LIST_RE = re.compile(
    _SB_LABEL + r"\s*NOS?\.?\s*[:.\-]?\s*((?:\d{6,8}[\s,/&]+(?:and\s+)?){1,15}\d{6,8})",
    re.I,
)
_SB_NUM_RE = re.compile(r"\d{6,8}")

# --- cross-layout document-identifier extraction (BL No. / SB No.) ------------
_ID_SPECS = {
    "bill_of_lading": {
        "key": "bl_number",
        "labels": ["b/l no", "bl no", "b/l number", "bl number", "bill of lading no",
                   "bill of lading number", "document no", "mbl no", "hbl no",
                   "master bl no", "house bl no", "waybill no", "sea waybill no",
                   "b/l no.", "bl-no", "b l no"],
        "shape": re.compile(r"^(?=.*\d)[A-Z0-9][A-Z0-9/\-]{5,19}$"),
        "reject": re.compile(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$"),
    },
    "shipping_bill": {
        "key": "sb_number",
        "labels": ["shipping bill no", "sb no", "s/b no", "sb no.", "sb.no",
                   "shipping bill number", "s.b. no", "shipping bill no."],
        "shape": re.compile(r"^\d{6,8}$"),
        "reject": re.compile(r"^(0{6,}|1{6,})$"),
    },
}
_ID_STRIP = " :#.-\t|"


class AnchorExtractor(Extractor):
    name = "rules"

    def __init__(
        self,
        rules_provider: Callable[[str], dict[str, dict]] | None = None,
    ) -> None:
        # rules_provider(format_key) -> {field_key: anchor_rule_row_dict}
        self.rules_provider = rules_provider

    def extract(self, pdf_path, *, doc_id, doc_type="bill_of_lading", examples=None):
        doc = load_document(pdf_path)
        fields: list[FieldValue] = []

        # Known fixed forms (e.g. ICEGATE Shipping Bill) are read by their table
        # structure. A non-None template *owns* the document — trust only its
        # values and leave the rest blank; do NOT run the generic label-anchor
        # pass, which produces garbage on a dense grid form.
        template = parse_with_template(doc, doc_type)

        if template is not None:
            page_index = [_PageTextIndex(p) for p in doc.pages]

        for spec in catalog(doc_type):
            key = spec["key"]
            if template is not None:
                value, conf = template.get(key, (None, 0.0))
                # a template parser may carry a value's own bbox directly
                # (see icegate_sb._pkg_gross) when the value is too short or
                # differently-ordered to find again by a page-text search —
                # prefer that over the generic locator.
                bbox_hint = template.get(f"__bbox__:{key}")
                if bbox_hint is not None:
                    page_no, bbox = bbox_hint
                else:
                    page_no, bbox = (
                        _locate_value(page_index, value) if value else (None, None)
                    )
                fields.append(FieldValue(key=key, value=value, confidence=conf,
                                         page=page_no, bbox=bbox, source="rules"))
            elif key == "document_type":
                fields.append(self._document_type(doc))
            elif key == "container_and_seal_numbers":
                fields.append(self._containers(doc))
            elif key == "freight_terms":
                fields.append(self._freight_terms(doc))
            else:
                fields.append(self._by_label(spec, doc))

        # The document's own number (BL No. / SB No.) is the most important field
        # and the most layout-variable — give it a dedicated multi-strategy pass.
        self._harden_identifier(fields, doc, doc_type)

        # A Bill of Lading can reference several Shipping Bills — collect every
        # SB number on it so the SB→BL auto-link matches on any of them.
        if doc_type == "bill_of_lading":
            self._collect_sb_refs(fields, doc)

        # Every Shipping Bill's item table can list several HS codes across
        # its invoice/item-detail pages — rescan it regardless of which
        # template (if any) claimed the document, so a form outside the
        # ICEGATE template, or one whose grid reader only caught the first
        # item, still gets every unique code and its matching description.
        if doc_type == "shipping_bill":
            self._enrich_hs_codes(fields, doc)

        detected = self._fingerprint(doc, doc_type)
        fields = self._apply_learned_rules(
            fields, doc, format_key(detected), doc_type
        )

        result_map = {f.key: f.value for f in fields}
        warnings = cross_field_warnings(result_map)
        if doc.has_scanned_pages:
            warnings.append(
                "One or more pages were image-only and read with OCR — verify "
                "low-confidence values carefully."
            )

        return ExtractionResult(
            doc_id=doc_id,
            file_name=str(pdf_path),
            engine=self.name,
            detected_format=detected,
            has_scanned_pages=doc.has_scanned_pages,
            fields=fields,
            warnings=warnings,
        )

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _value_below(label: list[Token], rows: list[list[Token]], row_index: int,
                     max_lines: int = 3) -> str:
        """Value taken from the lines directly beneath the label, same column."""
        lx0 = min(t.x0 for t in label)
        parts: list[str] = []
        for row in rows[row_index + 1: row_index + 1 + max_lines]:
            band = [t for t in row if (lx0 - 30) <= t.x0 <= (lx0 + 300)]
            if not band:
                break
            parts.append(" ".join(t.text for t in band))
        return " / ".join(parts).strip(_VALUE_STRIP)

    def _by_label(self, spec: dict, doc: Document) -> FieldValue:
        """Find the label inside a single visual row, then read the value from
        the remainder of that same row (falling back to the lines below)."""
        best: FieldValue = FieldValue(key=spec["key"], value=None, confidence=0.0)
        aliases = [a.lower() for a in spec["aliases"]]

        for page in doc.pages:
            rows = group_rows(page.tokens)
            for ri, row in enumerate(rows):
                for start in range(len(row)):
                    for n in range(1, _MAX_LABEL_NGRAM + 1):
                        window = row[start:start + n]
                        if len(window) < n:
                            break
                        phrase = " ".join(t.text for t in window).lower().strip(_VALUE_STRIP)
                        if len(phrase) < 3:
                            continue
                        score = max(fuzz.ratio(phrase, a) for a in aliases)
                        if score < _LABEL_MATCH_MIN:
                            continue

                        placement = 0.0
                        value = " ".join(t.text for t in row[start + n:]).strip(_VALUE_STRIP)
                        if len(value) < 2:
                            value = self._value_below(window, rows, ri)
                            placement = -0.1
                        if len(value) < 2:
                            continue

                        value = self._clean(spec, value)
                        conf = round(min(0.95, score / 100 * 0.8 + 0.15 + placement
                                         + self._validation_bonus(spec, value)), 2)
                        if conf > best.confidence:
                            best = FieldValue(
                                key=spec["key"], value=value, confidence=conf,
                                page=page.number,
                                bbox=(min(t.x0 for t in window), min(t.y0 for t in window),
                                      max(t.x1 for t in window), max(t.y1 for t in window)),
                                source="rules",
                            )
        return best

    # --------------------------------------------- Shipping Bill references
    @staticmethod
    def _collect_sb_refs(fields: list[FieldValue], doc: Document) -> None:
        fv = next(
            (f for f in fields if f.key == "shipping_bill_number_and_date"), None
        )
        if fv is None:
            return

        text = doc.full_text
        ordered: list[str] = []
        dates: dict[str, str] = {}

        # value a template/generic pass already found (may hold a date)
        if fv.value:
            for n in _SB_NUM_RE.findall(fv.value):
                ordered.append(n)
            dm = re.search(r"(\d{6,8}).{0,12}?([0-3]?\d[./\-][01]?\d[./\-]\d{2,4})",
                           fv.value)
            if dm:
                dates[dm.group(1)] = dm.group(2)

        for m in _SB_REF_RE.finditer(text):
            ordered.append(m.group(1))
            if m.group(2):
                dates.setdefault(m.group(1), m.group(2))
        for m in _SB_LIST_RE.finditer(text):
            ordered.extend(_SB_NUM_RE.findall(m.group(1)))

        seen: list[str] = []
        for n in ordered:
            if n not in seen:
                seen.append(n)
        if not seen:
            return

        parts = [f"{n} DT. {dates[n]}" if n in dates else n for n in seen]
        fv.value = ", ".join(parts)
        fv.confidence = max(fv.confidence, 0.85 if len(seen) == 1 else 0.8)
        fv.source = "rules"

    # ------------------------------------------------- HS code / description
    @staticmethod
    def _enrich_hs_codes(fields: list[FieldValue], doc: Document) -> None:
        scanned = scan_hs_codes(doc)
        if "hs_code" not in scanned:
            return
        by_key = {f.key: f for f in fields}
        hs_fv = by_key.get("hs_code")
        if hs_fv is not None and hs_fv.value == scanned["hs_code"][0]:
            # the owning parser already ran this same scan (e.g. the ICEGATE
            # template) and its page/bbox are already correct — leave as is.
            return
        for key in ("hs_code", "cargo_description"):
            if key not in scanned:
                continue
            fv = by_key.get(key)
            if fv is None:
                continue
            fv.value, fv.confidence = scanned[key]
            fv.page, fv.bbox = None, None  # value now spans several items/pages
            fv.source = "rules"

    # -------------------------------------------- document identifier hardening
    def _harden_identifier(self, fields: list[FieldValue], doc: Document,
                           doc_type: str) -> None:
        spec = _ID_SPECS.get(doc_type)
        if not spec:
            return
        fv = next((f for f in fields if f.key == spec["key"]), None)
        if fv is None:
            return

        best_value, best_score, best_bbox, best_page = None, 0.0, None, None
        for page in doc.pages:
            rows = group_rows(page.tokens)
            for ri, row in enumerate(rows):
                for start in range(len(row)):
                    for n in range(1, _MAX_LABEL_NGRAM + 1):
                        window = row[start:start + n]
                        if len(window) < n:
                            break
                        phrase = " ".join(t.text for t in window).lower().strip(_ID_STRIP)
                        if len(phrase) < 4:
                            continue
                        lscore = max(fuzz.ratio(phrase, a) for a in spec["labels"])
                        if lscore < 84:
                            continue
                        cand = self._id_from_context(
                            spec, row[start + n:], rows, ri,
                            label_x0=min(t.x0 for t in window),
                        )
                        if not cand:
                            continue
                        score = lscore / 100 * 0.9 + 0.1
                        if score > best_score:
                            best_value, best_score = cand, score
                            best_page = page.number
                            best_bbox = (min(t.x0 for t in window), min(t.y0 for t in window),
                                         max(t.x1 for t in window), max(t.y1 for t in window))

        # doc-wide regex fallback when no label was matched
        if best_value is None:
            best_value = self._id_regex_fallback(spec, doc)
            best_score = 0.55 if best_value else 0.0

        if best_value and best_score >= max(fv.confidence, 0.4):
            fv.value = best_value
            fv.confidence = round(min(0.95, best_score + 0.05), 2)
            fv.page = best_page or fv.page
            fv.bbox = best_bbox or fv.bbox
            fv.source = "rules"

    @staticmethod
    def _id_from_context(spec: dict, rest: list[Token], rows: list[list[Token]],
                         row_index: int, *, label_x0: float) -> str | None:
        # value tokens beside the label (same row) + column-aligned on the row
        # below (so an adjacent cell's number is not mistaken for this one)
        pool: list[str] = [t.text for t in rest]
        for r in rows[row_index + 1: row_index + 2]:
            pool += [t.text for t in r if abs(t.x0 - label_x0) <= 95]
        for raw in pool:
            tok = raw.strip(_ID_STRIP)
            if spec["shape"].match(tok) and not spec["reject"].match(tok):
                return tok
        glued = "".join(p.strip(_ID_STRIP) for p in pool[:3])  # e.g. "H" "680557"
        if spec["shape"].match(glued) and not spec["reject"].match(glued):
            return glued
        return None

    @staticmethod
    def _id_regex_fallback(spec: dict, doc: Document) -> str | None:
        text = doc.full_text
        anchor = "shipping bill" if spec["key"] == "sb_number" else "bill of lading"
        idx = text.lower().find(anchor)
        window = text[max(0, idx - 40): idx + 200] if idx >= 0 else text[:400]
        for tok in re.split(r"[\s|]+", window):
            t = tok.strip(_ID_STRIP)
            if not (spec["shape"].match(t) and not spec["reject"].match(t)):
                continue
            # a bare 4-8 digit number this far from a label is almost always a
            # PIN code / phone fragment, not a BL number — require a letter.
            if spec["key"] == "bl_number" and t.isdigit() and len(t) < 9:
                continue
            return t
        return None

    @staticmethod
    def _clean(spec: dict, value: str) -> str:
        value = re.sub(r"\s+", " ", value).strip(_VALUE_STRIP)
        if spec["type"] == "date":
            return normalize_date(value) or value
        if spec["type"] == "quantity":
            q = parse_quantity(value)
            return f"{q[0]:g} {q[1]}".strip() if q else value
        return value

    @staticmethod
    def _validation_bonus(spec: dict, value: str) -> float:
        if spec["type"] == "date":
            return 0.1 if normalize_date(value) else -0.15
        if spec["type"] == "quantity":
            return 0.1 if parse_quantity(value) else -0.1
        return 0.0

    # ------------------------------------------------------- dedicated passes
    def _document_type(self, doc: Document) -> FieldValue:
        head = " ".join(
            t.text for t in doc.pages[0].tokens if t.y0 < doc.pages[0].height * 0.25
        ).lower()
        best_title, best_score = None, 0.0
        for title in _TITLES:
            score = fuzz.partial_ratio(title, head)
            if score > best_score:
                best_title, best_score = title, score
        if best_title and best_score >= 80:
            return FieldValue(
                key="document_type", value=best_title.title(),
                confidence=round(best_score / 100 * 0.9, 2), page=1, source="rules",
            )
        return FieldValue(key="document_type", value=None, confidence=0.0)

    def _containers(self, doc: Document) -> FieldValue:
        found: list[str] = []
        page_no = None
        for page in doc.pages:
            text = " ".join(t.text for t in page.tokens)
            for m in _CONTAINER_RE.findall(text.upper()):
                c = m.replace(" ", "")
                if c not in found:
                    found.append(c)
                    page_no = page_no or page.number
        if not found:
            return FieldValue(key="container_and_seal_numbers", value=None, confidence=0.0)
        ok = all(container_check_digit_ok(c) for c in found)
        return FieldValue(
            key="container_and_seal_numbers",
            value=", ".join(found),
            confidence=0.85 if ok else 0.6,
            page=page_no,
            source="rules",
        )

    def _freight_terms(self, doc: Document) -> FieldValue:
        m = _FREIGHT_RE.search(doc.full_text)
        if not m:
            return FieldValue(key="freight_terms", value=None, confidence=0.0)
        return FieldValue(
            key="freight_terms",
            value=f"FREIGHT {m.group(1).upper().strip()}",
            confidence=0.8,
            source="rules",
        )

    def _fingerprint(self, doc: Document, doc_type: str) -> str | None:
        """Format label used for learning."""
        if doc_type == "shipping_bill":
            return "Shipping Bill"
        if doc_type == "master_bl":
            # The generic title detector matches boilerplate "Bill of
            # Lading" text inside this form's own legal clauses just as
            # readily as a real export-side Bill of Lading, which would
            # otherwise let that doc_type's learned corrections bleed into
            # Master BL extraction (and vice versa) under the same format
            # key — a fixed, doc_type-scoped label keeps them separate.
            return "Master Bill Of Lading"
        return self._document_type(doc).value

    # --------------------------------------------------- learned anchor rules
    def _apply_learned_rules(
        self, fields: list[FieldValue], doc: Document, fmt_key: str, doc_type: str
    ) -> list[FieldValue]:
        if not (self.rules_provider and fmt_key):
            return fields
        rules = self.rules_provider(fmt_key) or {}
        if not rules:
            return fields

        by_key = {f.key: f for f in fields}
        for key, rule in rules.items():
            if key not in by_key:
                continue
            learned = self._apply_rule(key, rule, doc)
            # A learned rule encodes a human correction for this exact layout —
            # trust it over the generic label guess whenever it produces a value.
            if learned and learned.value:
                by_key[key] = learned
        return [by_key[k] for k in field_keys(doc_type)]

    def _apply_rule(self, key: str, rule: dict, doc: Document) -> FieldValue | None:
        label_text = (rule.get("label_text") or "").lower().strip(_VALUE_STRIP)
        if not label_text:
            return None
        page = next(
            (p for p in doc.pages if p.number == rule.get("page")), doc.pages[0]
        )

        best_label: tuple[list[Token], float] | None = None
        for row in group_rows(page.tokens):
            for start in range(len(row)):
                for n in range(1, _MAX_LABEL_NGRAM + 1):
                    window = row[start:start + n]
                    if len(window) < n:
                        break
                    phrase = " ".join(t.text for t in window).lower().strip(_VALUE_STRIP)
                    score = fuzz.ratio(phrase, label_text)
                    if best_label is None or score > best_label[1]:
                        best_label = (window, score)
        if not best_label or best_label[1] < 85:
            return None

        window, lscore = best_label
        lx0 = min(t.x0 for t in window)
        ly0 = min(t.y0 for t in window)
        tx0 = lx0 + float(rule.get("rel_dx") or 0.0)
        ty0 = ly0 + float(rule.get("rel_dy") or 0.0)

        spec = get_field(key)
        val_w = float(rule.get("val_w") or 140.0)
        val_h = float(rule.get("val_h") or 12.0)
        x_hi = tx0 + max(120.0, val_w * 1.4)
        y_hi = ty0 + max(14.0, val_h * 1.3)
        cand = [
            t for t in page.tokens
            if (tx0 - 15) <= t.x0 <= x_hi and (ty0 - 6) <= t.cy <= y_hi
        ]
        if not cand:
            return None
        cand.sort(key=lambda t: (round(t.y0), t.x0))
        value = self._clean(spec, " ".join(t.text for t in cand).strip(_VALUE_STRIP))
        if len(value) < 2:
            return None

        conf = round(
            min(0.97, 0.82 + lscore / 100 * 0.12 + self._validation_bonus(spec, value)),
            2,
        )
        return FieldValue(
            key=key, value=value, confidence=conf, page=page.number,
            bbox=(lx0, ly0, max(t.x1 for t in window), max(t.y1 for t in window)),
            source="rules",
        )
