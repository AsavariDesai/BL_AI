"""Extraction engines: turn a BL document into canonical FieldValues.

  rules  -> AnchorExtractor: label-anchor + geometry, no training (Tier A)
  kie    -> trained LiLT/Donut model (Tier B) — added once corrections accrue
"""
from __future__ import annotations

from .anchor_extractor import AnchorExtractor
from .base import Extractor


def get_extractor(engine: str) -> Extractor:
    if engine in ("rules", "anchor", "local"):
        from ..learning import anchor_rules_for

        return AnchorExtractor(rules_provider=anchor_rules_for)
    if engine == "kie":
        from .kie_extractor import KieExtractor  # noqa: F401 — added in Tier B

        return KieExtractor()
    raise ValueError(f"Unknown extraction engine: {engine!r}")
