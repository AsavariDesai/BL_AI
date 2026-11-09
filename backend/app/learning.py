"""Learning loop v1 — turn user corrections into reusable anchor rules.

When a reviewer fixes a field, we:
  1. re-open the document and locate the corrected value's tokens,
  2. find the nearest label matching that field's known aliases,
  3. store the value's position *relative to that label* as an anchor rule keyed
     by (format_key, field_key).

Next time a BL of the same format is extracted, ``AnchorExtractor`` re-finds the
label and reads the value at the learned offset — high confidence, layout-aware,
no model training required.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from . import repository as repo
from .document import Document, Token, group_rows, load_document
from .field_catalog import get_field

_MIN_VALUE_MATCH = 85     # fuzz score to accept a located value span
_MIN_LABEL_MATCH = 78
_MAX_SPAN = 14            # max tokens to consider as one value
_STRIP = " :;.-–—|\t"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def anchor_rules_for(fmt_key: str) -> dict[str, dict]:
    """Provider handed to AnchorExtractor: {field_key: rule row as dict}.

    Best-effort — a missing DB (e.g. the CLI before any API run) must not break
    extraction."""
    if not fmt_key:
        return {}
    try:
        return {r["field_key"]: dict(r) for r in repo.get_anchor_rules(fmt_key)}
    except Exception:  # noqa: BLE001
        return {}


def learn_from_correction(
    *,
    stored_path: str,
    format_key_value: str,
    field_key: str,
    corrected_value: str,
    doc: Document | None = None,
) -> bool:
    """Capture / refresh one anchor rule. Returns True if a rule was written."""
    if not (format_key_value and corrected_value):
        return False

    document = doc or load_document(stored_path)
    target = _norm(corrected_value)

    for page in document.pages:
        span = _find_value_span(page.tokens, target)
        if span is None:
            continue
        label = _nearest_label(field_key, page, span)
        if label is None:
            continue

        label_tokens, label_phrase = label
        vx0 = min(t.x0 for t in span)
        vy0 = min(t.y0 for t in span)
        vx1 = max(t.x1 for t in span)
        vy1 = max(t.y1 for t in span)
        lx0 = min(t.x0 for t in label_tokens)
        ly0 = min(t.y0 for t in label_tokens)

        repo.upsert_anchor_rule(
            format_fingerprint=format_key_value,
            field_key=field_key,
            label_text=label_phrase,
            rel_dx=round(vx0 - lx0, 1),
            rel_dy=round(vy0 - ly0, 1),
            val_w=round(vx1 - vx0, 1),
            val_h=round(vy1 - vy0, 1),
            page=page.number,
        )
        return True
    return False


def _find_value_span(tokens: list[Token], target: str) -> list[Token] | None:
    best_score, best_span = 0.0, None
    for i in range(len(tokens)):
        acc: list[Token] = []
        for j in range(i, min(i + _MAX_SPAN, len(tokens))):
            acc.append(tokens[j])
            phrase = _norm(" ".join(t.text for t in acc))
            score = fuzz.ratio(phrase, target)
            if score > best_score:
                best_score, best_span = score, list(acc)
            if len(phrase) > len(target) + 10:
                break
    return best_span if best_score >= _MIN_VALUE_MATCH else None


def _nearest_label(
    field_key: str, page, span: list[Token]
) -> tuple[list[Token], str] | None:
    aliases = [a.lower() for a in get_field(field_key)["aliases"]]
    if not aliases:
        return None
    sx = min(t.x0 for t in span)
    sy = min(t.y0 for t in span)

    best: tuple[float, float, list[Token], str] | None = None  # (score, dist, tokens, phrase)
    for row in group_rows(page.tokens):
        for start in range(len(row)):
            for n in range(1, 6):
                window = row[start:start + n]
                if len(window) < n:
                    break
                phrase = " ".join(t.text for t in window).lower().strip(_STRIP)
                if len(phrase) < 3:
                    continue
                score = max(fuzz.ratio(phrase, a) for a in aliases)
                if score < _MIN_LABEL_MATCH:
                    continue
                lx = min(t.x0 for t in window)
                ly = min(t.y0 for t in window)
                dist = abs(lx - sx) + abs(ly - sy)
                if best is None or (score, -dist) > (best[0], -best[1]):
                    best = (score, dist, window, phrase)
    if best is None:
        return None
    return best[2], best[3]
