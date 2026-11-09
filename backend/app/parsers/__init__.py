"""Template parsers for known, fixed document layouts.

A template parser reads a *specific* government/carrier form by its table
structure — far more accurate than the generic label-anchor pass. The extractor
tries these first and falls back to the generic pass for anything they don't
fill.
"""
from __future__ import annotations

from ..document import Document
from . import (
    aof_bl, breakbulk_bl, container_bl, gssw_bl, icegate_sb, jeena_bl, one_masterbl, yusen_hbl,
)

# order: most specific first; jeena_bl is the adaptive fallback for house BLs
# routed through JEENA & COMPANY as India agent. yusen_hbl and one_masterbl
# are doc_type-scoped (house_bl / master_bl respectively) so neither ever
# competes with the bill_of_lading/shipping_bill parsers above them.
_PARSERS = [
    icegate_sb, aof_bl, container_bl, gssw_bl, breakbulk_bl, jeena_bl, yusen_hbl, one_masterbl,
]


def parse_with_template(
    doc: Document, doc_type: str
) -> dict[str, tuple[str, float]] | None:
    """{field_key: (value, confidence)} from the first matching template parser,
    or ``None`` when no template claims this document.

    A non-None result means the template *owns* the document: the extractor must
    trust only these values for that document type and leave the rest blank,
    rather than running the generic label-anchor pass (which produces garbage on
    a dense grid form)."""
    for parser in _PARSERS:
        if parser.DOC_TYPE == doc_type and parser.matches(doc):
            return parser.parse(doc)
    return None
