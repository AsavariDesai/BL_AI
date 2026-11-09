"""Normalise a BL's detected format into a stable key for the learning loop.

The anchor extractor's ``detected_format`` is the document-type string (e.g.
"Combined Transport Bill Of Lading"). ``format_key`` collapses casing / spacing
so corrections and learned anchor rules bucket together across BLs that share a
layout, even when their numbers, dates and party names differ.
"""
from __future__ import annotations

import re


def format_key(detected_format: str | None) -> str:
    if not detected_format:
        return ""
    s = detected_format.upper()
    s = re.sub(r"[^A-Z ]+", " ", s)      # drop digits & punctuation
    s = re.sub(r"\s+", " ", s).strip()
    return s[:80]
