"""Application services: orchestrate ingest -> extract -> review over the repo."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import sqlite3
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pymupdf

from . import config
from . import learning
from . import repository as repo
from .classify import detect_doc_type, head_text_from_bytes
from .config import settings
from .document import load_document
from .extraction.validate import find_container_numbers
from .export import (
    build_bl_data_pdf,
    build_bl_data_xlsx,
    build_bl_multi_sb_pdf,
    build_bl_multi_sb_xlsx,
    build_bl_records_xlsx,
    build_bl_sb_data_pdf,
    build_bl_sb_data_xlsx,
    build_hierarchy_pdf,
    build_hierarchy_xlsx,
    build_master_bl_data_xlsx,
    build_master_bl_summary_xlsx,
    build_master_house_bl_xlsx,
    build_pdf,
    build_summary_pdf,
    build_summary_xlsx,
    build_xlsx,
    sum_quantities_total,
)
from .extraction import get_extractor
from .field_catalog import DOC_TYPES, SB_EXPORT_FIELDS, catalog
from .field_catalog import field_keys as catalog_field_keys
from .formats import format_key
from .schemas import (
    ContainerReconciliation,
    DocumentDetail,
    DocumentOut,
    FieldOut,
    HierarchyOut,
    HierarchySbOut,
    LinkedBlOut,
    LinkedHouseBlOut,
    LinkedSbOut,
    RecordOut,
    RecordStats,
    SbReconciliation,
    ShippingBillDetail,
    ShippingBillOut,
)


def ingest_upload(
    filename: str,
    content: bytes,
    *,
    doc_type: str | None = None,
    parent_id: str | None = None,
    created_by: str | None = None,
    vessel_id: str | None = None,
    company_id: str | None = None,
) -> str:
    if doc_type is None:
        doc_type, _ = detect_doc_type(head_text_from_bytes(content))
    if doc_type not in DOC_TYPES:
        raise ValueError(f"unknown doc_type: {doc_type!r}")
    if vessel_id is not None:
        vessel = repo.get_vessel(vessel_id)
        if vessel is None:
            raise ValueError("vessel not found")
        if doc_type in ("bill_of_lading", "shipping_bill") and not company_id:
            # Export's vessel-scoped flow passes only vessel_id — carry
            # company_id too (same as every non-vessel-scoped BL/SB upload
            # already does) so the existing company-wide views, stats and
            # exports keep seeing every record regardless of which vessel,
            # or none, it was uploaded under.
            company_id = vessel["company_id"]
    if company_id is not None and doc_type not in ("bill_of_lading", "shipping_bill"):
        raise ValueError("company_id only applies to Bill of Lading / Shipping Bill uploads")
    if company_id is not None and repo.get_company(company_id) is None:
        raise ValueError("company not found")
    if parent_id is not None:
        parent = repo.get_document(parent_id)
        if parent is None or parent["doc_type"] != "shipping_bill":
            raise ValueError("parent_id must be an existing Shipping Bill")
        if doc_type != "bill_of_lading":
            raise ValueError("only Bills of Lading can be linked under a Shipping Bill")

    sha = hashlib.sha256(content).hexdigest()
    try:
        with pymupdf.open(stream=content, filetype="pdf") as d:
            page_count = d.page_count
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Not a readable PDF: {exc}") from exc

    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored = config.UPLOAD_DIR / f"{sha}.pdf"
    if not stored.exists():
        stored.write_bytes(content)

    doc_id = repo.create_document(
        filename=filename,
        stored_path=str(stored),
        content_sha256=sha,
        page_count=page_count,
        doc_type=doc_type,
        parent_id=parent_id,
        created_by=created_by,
        vessel_id=vessel_id,
        company_id=company_id,
    )
    # House BL has a real field catalog + template parser (yusen_hbl.py), so
    # — unlike Master BL, whose catalog is still empty pending real samples —
    # it's worth auto-extracting right away, the same way Export's /ingest
    # auto-extracts a Bill of Lading/Shipping Bill. Scheduled (background):
    # OCR on a scanned upload can take a while and the caller (an upload
    # HTTP request) shouldn't block on it. Export doc_types never reach here
    # with a pending extraction already queued twice — process_upload(_async)
    # schedule their own extraction right after calling this function, and
    # /ingest never produces a house_bl (see api.ingest's own comment).
    #
    # Master BL schedules it too, even though its own field catalog is still
    # empty (so this populates zero canonical fields) — what it actually
    # buys is OCR done once in the background instead of inline the first
    # time someone opens this Master BL's detail page: that page computes
    # container-number reconciliation against its linked House BLs (see
    # _linked_house_bls), which needs this Master BL's own OCR tokens, and
    # a cold OCR pass can take well over a minute (see app/ocr.py) — not
    # something a GET request should ever trigger synchronously.
    if doc_type in ("house_bl", "master_bl"):
        schedule_extraction(doc_id)
    return doc_id


log = logging.getLogger(__name__)

# Several documents extract concurrently — EXTRACT_WORKERS (config.py),
# CPU-aware by default. Each worker thread gets its own OCR engine instance
# (app/ocr.py is thread-local), and each SQLite write opens its own
# connection (db.py's get_conn(), WAL mode, a 30s busy_timeout), so this is
# safe to raise; it's what actually speeds up a large bulk batch (e.g. 400
# House BLs at once) instead of processing them strictly one at a time.
_EXTRACT_POOL = ThreadPoolExecutor(
    max_workers=settings.extract_workers, thread_name_prefix="extract"
)


def run_extraction(doc_id: str, engine: str | None = None) -> DocumentDetail:
    """Extract a document and persist a terminal state no matter what.

    A scanned multi-page PDF can take several minutes to OCR. If that work
    throws (or the request that called it times out), the document must never
    be left silently at 'uploaded' with no data — it is marked 'processing'
    up front and always ends at 'extracted' or 'error'.
    """
    row = repo.get_document(doc_id)
    if row is None:
        raise KeyError(doc_id)

    engine = engine or settings.extraction_engine
    repo.update_document(doc_id, status="processing", warnings=[])
    try:
        extractor = get_extractor(engine)
        result = extractor.extract(
            row["stored_path"], doc_id=doc_id, doc_type=row["doc_type"]
        )
    except Exception as exc:  # noqa: BLE001 — persist the failure, don't lose the doc
        log.exception("extraction failed for %s", doc_id)
        repo.update_document(
            doc_id,
            status="error",
            warnings=[f"Extraction failed: {exc}"[:400] + " — click Re-run to try again."],
        )
        return get_document_detail(doc_id)

    warnings = list(result.warnings)
    if row["doc_type"] == "master_bl" and row["vessel_id"]:
        warnings = _check_master_vessel_match(row["vessel_id"], result, warnings)

    repo.replace_extractions(doc_id, result)
    repo.update_document(
        doc_id,
        engine=result.engine,
        status="extracted",
        format_fingerprint=result.detected_format,
        has_scanned_pages=int(result.has_scanned_pages),
        warnings=warnings,
    )
    _auto_link(row, result)
    return get_document_detail(doc_id)


def _check_master_vessel_match(vessel_id: str, result, warnings: list[str]) -> list[str]:
    """Flag a Master BL whose own extracted "Vessel / Voyage" text doesn't
    name the Vessel Workspace it was uploaded under — a wrong-vessel upload
    (or an OCR misread) otherwise has no visible signal besides someone
    noticing the mismatch by eye. Non-blocking: it only surfaces as a
    warning, the same way an OCR'd-page notice already does.
    """
    vessel = repo.get_vessel(vessel_id)
    if vessel is None or not vessel["name"]:
        return warnings
    value = next((f.value for f in result.fields if f.key == "vessel_and_voyage"), None)
    if not value:
        return warnings
    norm = lambda s: re.sub(r"[^A-Z0-9]", "", s.upper())  # noqa: E731
    if norm(vessel["name"]) not in norm(value):
        return warnings + [
            f"This Master BL's own Vessel/Voyage ({value!r}) doesn't name "
            f"{vessel['name']!r}, the vessel it was uploaded under — double-check it "
            "belongs in this Vessel Workspace."
        ]
    return warnings


def _safe_run_extraction(doc_id: str, engine: str | None) -> None:
    try:
        run_extraction(doc_id, engine)
    except Exception:  # noqa: BLE001 — background job, nothing to surface to
        log.exception("background extraction crashed for %s", doc_id)


def schedule_extraction(doc_id: str, engine: str | None = None) -> None:
    """Queue extraction on the background worker and return immediately."""
    repo.update_document(doc_id, status="queued", warnings=[])
    _EXTRACT_POOL.submit(_safe_run_extraction, doc_id, engine)


def recover_stale_jobs() -> int:
    """Called on startup: a doc left 'queued'/'processing' by a killed server
    kept its row and its PDF but never finished extracting. Mark it so the user
    can re-run it instead of it looking silently empty forever.
    """
    n = 0
    for r in repo.list_documents(1000):
        if r["status"] in ("queued", "processing"):
            repo.update_document(
                r["id"],
                status="error",
                warnings=["Extraction was interrupted when the server stopped. "
                          "Click Re-run to extract this document again."],
            )
            n += 1
    if n:
        log.info("recover_stale_jobs: reset %d interrupted extraction(s)", n)
    return n


def process_upload(
    filename: str,
    content: bytes,
    *,
    doc_type: str | None = None,
    parent_id: str | None = None,
    engine: str | None = None,
    created_by: str | None = None,
    company_id: str | None = None,
    vessel_id: str | None = None,
) -> DocumentDetail:
    """Upload → detect type → extract → auto-link, synchronously, in one call."""
    doc_id = ingest_upload(
        filename, content, doc_type=doc_type, parent_id=parent_id, created_by=created_by,
        company_id=company_id, vessel_id=vessel_id,
    )
    return run_extraction(doc_id, engine)


def process_upload_async(
    filename: str,
    content: bytes,
    *,
    doc_type: str | None = None,
    parent_id: str | None = None,
    engine: str | None = None,
    created_by: str | None = None,
    company_id: str | None = None,
    vessel_id: str | None = None,
) -> DocumentDetail:
    """Upload now, extract on the background worker. Returns immediately with
    status 'queued' — the caller polls GET /documents/{id} for the result.
    """
    doc_id = ingest_upload(
        filename, content, doc_type=doc_type, parent_id=parent_id, created_by=created_by,
        company_id=company_id, vessel_id=vessel_id,
    )
    schedule_extraction(doc_id, engine)
    return get_document_detail(doc_id)


def _auto_link(row: sqlite3.Row, result) -> None:
    """Link a BL to every Shipping Bill it references by number (or, on SB
    upload, every BL that references this SB back) — a BL may reference
    several Shipping Bills, so every number that already matches an existing
    upload gets linked via the many-to-many BL-first table (bl_sb_links),
    not just the first one found. Matching is scoped to the same vessel
    (when the document has one) so two unrelated vessels whose Shipping
    Bills happen to share a short, coincidentally-identical number never get
    cross-linked. The legacy single ``documents.parent_id`` is kept pointed
    at the first match too, for older code that still reads it directly,
    and is never overridden once set.
    """
    values = {f.key: f.value for f in result.fields}
    if row["doc_type"] == "bill_of_lading":
        first_sb_id = None
        for num in sorted(repo._sb_numbers(values.get("shipping_bill_number_and_date"))):
            sb_id = repo.shipping_bill_id_by_number(num, vessel_id=row["vessel_id"])
            if sb_id:
                repo.link_sb_to_bl(row["id"], sb_id, source="auto")
                first_sb_id = first_sb_id or sb_id
        if first_sb_id and row["parent_id"] is None:
            repo.set_parent([row["id"]], first_sb_id, source="auto")
    elif row["doc_type"] == "shipping_bill":
        num = repo._first_number(values.get("sb_number"))
        for bl_id in repo.bl_ids_referencing(num, vessel_id=row["vessel_id"]):
            repo.link_sb_to_bl(bl_id, row["id"], source="auto")
            bl = repo.get_document(bl_id)
            if bl is not None and bl["parent_id"] is None:
                repo.set_parent([bl_id], row["id"], source="auto")


def save_field_edits(doc_id: str, edits: dict[str, str | None]) -> DocumentDetail:
    row = repo.get_document(doc_id)
    if row is None:
        raise KeyError(doc_id)

    fmt_key = format_key(row["format_fingerprint"])
    changed = repo.apply_field_edits(
        doc_id, edits, format_fingerprint=fmt_key
    )
    if changed and row["status"] != "exported":
        repo.update_document(doc_id, status="reviewed")

    # Learn an anchor rule from every corrected field that now has a value.
    # Load the document once (cached) and reuse it for every field.
    learn_keys = [k for k in changed if (edits.get(k) or "").strip()]
    if learn_keys:
        try:
            from .document import load_document

            shared_doc = load_document(row["stored_path"])
        except Exception:  # noqa: BLE001
            shared_doc = None
        for key in learn_keys:
            try:
                learning.learn_from_correction(
                    stored_path=row["stored_path"],
                    format_key_value=fmt_key,
                    field_key=key,
                    corrected_value=edits[key].strip(),
                    doc=shared_doc,
                )
            except Exception:  # noqa: BLE001 — learning must never break a save
                pass

    return get_document_detail(doc_id)


# --------------------------------------------------------------------- delete
def _cleanup_stored_files(deleted_rows: list[sqlite3.Row]) -> None:
    """Remove each deleted row's PDF from disk, unless some other surviving
    document still points at the same path — uploads are deduplicated by
    content hash (see ingest_upload), so two records can share one file."""
    for row in deleted_rows:
        stored_path = row["stored_path"]
        if stored_path and not repo.stored_path_still_used(stored_path, row["id"]):
            Path(stored_path).unlink(missing_ok=True)


def delete_document(doc_id: str) -> list[str]:
    """Delete one document. Cascade behavior depends on what it is:

      - master_bl: a House BL has no existence outside its Master — it's
        never shown anywhere in the UI except nested under one — so
        deleting the Master also deletes every House BL linked under it;
        leaving them behind would make them permanently unreachable.
      - shipping_bill: a Bill of Lading stays independently visible and
        manageable whether or not it's linked to an SB (that's the normal
        BL-first case), so deleting the SB only *unlinks* its BLs — via FK
        cascade on bl_sb_links and ON DELETE SET NULL on the legacy
        parent_id column — it never deletes them.
      - house_bl / bill_of_lading: just that one document.

    Returns every document id actually removed (more than one for a
    Master BL with House BLs under it).
    """
    row = repo.get_document(doc_id)
    if row is None:
        raise KeyError(doc_id)

    ids = [doc_id]
    if row["doc_type"] == "master_bl":
        ids += repo.linked_house_bl_ids(doc_id)

    deleted_rows = repo.delete_document_rows(ids)
    _cleanup_stored_files(deleted_rows)
    return [r["id"] for r in deleted_rows]


def delete_documents(doc_ids: list[str]) -> list[str]:
    """Bulk delete_document — expands any Master BL in the batch to its
    House BLs up front, across the whole batch in one pass, so a 400-item
    batch that happens to be all Master BLs stays O(n), not O(n^2)."""
    if not doc_ids:
        return []
    rows = repo.get_documents(doc_ids)
    all_ids = list(doc_ids)
    for doc_id in doc_ids:
        row = rows.get(doc_id)
        if row is not None and row["doc_type"] == "master_bl":
            all_ids += repo.linked_house_bl_ids(doc_id)
    all_ids = list(dict.fromkeys(all_ids))  # de-dup, keep first-seen order

    deleted_rows = repo.delete_document_rows(all_ids)
    _cleanup_stored_files(deleted_rows)
    return [r["id"] for r in deleted_rows]


def get_document_detail(doc_id: str) -> DocumentDetail:
    row = repo.get_document(doc_id)
    if row is None:
        raise KeyError(doc_id)

    doc_type = row["doc_type"]
    stored = {r["field_key"]: r for r in repo.get_extractions(doc_id)}
    fields: list[FieldOut] = []
    for spec in catalog(doc_type):
        e = stored.get(spec["key"])
        fields.append(
            FieldOut(
                key=spec["key"],
                label=spec["label"],
                group=spec["group"],
                type=spec["type"],
                value=e["value"] if e else None,
                confidence=e["confidence"] if e else 0.0,
                ai_value=e["ai_value"] if e else None,
                page=e["page"] if e else None,
                bbox=json.loads(e["bbox"]) if e and e["bbox"] else None,
                source=e["source"] if e else "rules",
            )
        )

    linked_shipping_bills: list[LinkedSbOut] = []
    sb_reconciliation: SbReconciliation | None = None
    if doc_type == "bill_of_lading":
        linked_shipping_bills, sb_reconciliation = _linked_shipping_bills(doc_id, row["parent_id"])

    linked_house_bls: list[LinkedHouseBlOut] = []
    container_reconciliation: ContainerReconciliation | None = None
    if doc_type == "master_bl":
        linked_house_bls, container_reconciliation = _linked_house_bls(row)

    return DocumentDetail(
        **document_row_to_out(row),
        fields=fields,
        warnings=json.loads(row["warnings"]) if row["warnings"] else [],
        suggested_export_fields=_suggested_export_fields(row["format_fingerprint"], doc_type),
        linked_shipping_bills=linked_shipping_bills,
        sb_reconciliation=sb_reconciliation,
        linked_house_bls=linked_house_bls,
        container_reconciliation=container_reconciliation,
    )


# Document OCR/extraction has settled (tokens are cached — see
# document.load_document) once it reaches one of these; 'uploaded' /
# 'queued' / 'processing' means it hasn't run yet or is mid-run.
_OCR_READY_STATUSES = {"extracted", "reviewed", "exported", "error"}


def _extract_container_numbers(stored_path: str) -> list[str]:
    """Container numbers appearing anywhere in a PDF, carrier-agnostic (no
    template parser needed — a container number is a fixed ISO 6346 shape,
    found the same way cross_field_warnings already checks a BL's own
    container field). Used for Master BL <-> House BL reconciliation
    (_linked_house_bls) since Master BL has no field catalog of its own yet
    (field_catalog.MASTER_BL). Relies on document.load_document's own
    on-disk OCR cache to stay cheap on repeat calls — never call this on a
    document whose OCR hasn't settled yet (_OCR_READY_STATUSES) or it will
    trigger a fresh, synchronous, potentially 1+ minute OCR pass inline.
    """
    try:
        doc = load_document(stored_path)
    except Exception:  # noqa: BLE001 — a missing/corrupt file just yields no containers
        return []
    full_text = " ".join(t.text for p in doc.pages for t in p.tokens)
    return list(dict.fromkeys(find_container_numbers(full_text)))


def _linked_house_bls(
    master: sqlite3.Row,
) -> tuple[list[LinkedHouseBlOut], ContainerReconciliation | None]:
    # link_source lives on master_house_bl_links, not documents.link_source
    # (that column is the older SB-is-master hierarchy's own field) — every
    # House BL currently gets here through the one BL-first link call, so
    # "manual" is accurate, same as _linked_shipping_bills does for its
    # BL-first-linked SBs.
    master_id = master["id"]
    house_ids = repo.linked_house_bl_ids(master_id)
    rows_by_id = repo.get_documents(house_ids)  # one query, not one per id —
    # a Master BL can carry hundreds of House BLs in a bulk batch, and this
    # is rebuilt on every document detail fetch.

    master_containers = (
        set(_extract_container_numbers(master["stored_path"]))
        if master["status"] in _OCR_READY_STATUSES else set()
    )

    # First pass: each House BL's own containers + a running count across
    # all of them, so duplicate detection reflects every upload, not just
    # the ones seen before it in the loop (mirrors _linked_shipping_bills).
    per_house: list[tuple[str, sqlite3.Row, list[str]]] = []
    container_counts: Counter[str] = Counter()
    for house_id in house_ids:
        row = rows_by_id.get(house_id)
        if row is None:
            continue
        containers = (
            _extract_container_numbers(row["stored_path"])
            if row["status"] in _OCR_READY_STATUSES else []
        )
        for c in containers:
            container_counts[c] += 1
        per_house.append((house_id, row, containers))

    out: list[LinkedHouseBlOut] = []
    for house_id, row, containers in per_house:
        out.append(LinkedHouseBlOut(
            id=row["id"], filename=row["filename"], status=row["status"],
            link_source="manual",
            container_numbers=containers,
            has_duplicate_container=any(container_counts[c] > 1 for c in containers),
            has_unrelated_container=bool(master_containers)
            and any(c not in master_containers for c in containers),
        ))

    reconciliation = None
    if master_containers:
        uploaded = set(container_counts)
        reconciliation = ContainerReconciliation(
            total_master=len(master_containers),
            total_uploaded=len(uploaded),
            missing_containers=sorted(master_containers - uploaded),
            duplicate_containers=sorted(c for c, n in container_counts.items() if n > 1),
            unrelated_containers=sorted(uploaded - master_containers),
        )
    return out, reconciliation


def _linked_shipping_bills(
    bl_id: str, legacy_parent_id: str | None
) -> tuple[list[LinkedSbOut], SbReconciliation | None]:
    """Every Shipping Bill linked to this BL via the BL-first flow (supports
    50+), plus — for older records linked before that flow existed — the one
    Shipping Bill still tracked via ``documents.parent_id``, so nothing
    linked the old way silently disappears from this list — together with
    how those uploads reconcile against the BL's own referenced SB numbers.
    """
    sb_ids = list(repo.linked_sb_ids(bl_id))
    if legacy_parent_id and legacy_parent_id not in sb_ids:
        parent = repo.get_document(legacy_parent_id)
        if parent is not None and parent["doc_type"] == "shipping_bill":
            sb_ids.append(legacy_parent_id)

    bl_ex = {e["field_key"]: e["value"] for e in repo.get_extractions(bl_id)}
    bl_sb_numbers = _parse_sb_numbers(bl_ex.get("shipping_bill_number_and_date"))

    # First pass: gather each linked SB's own document row + number, so the
    # per-SB duplicate count below reflects every upload, not just the ones
    # seen before it in the loop.
    rows: list[tuple[str, sqlite3.Row, str | None]] = []
    sb_number_counts: Counter[str] = Counter()
    for sb_id in sb_ids:
        sb = repo.get_document(sb_id)
        if sb is None:
            continue
        sb_ex = {e["field_key"]: e["value"] for e in repo.get_extractions(sb_id)}
        sb_number = sb_ex.get("sb_number")
        if sb_number:
            sb_number_counts[sb_number.strip()] += 1
        rows.append((sb_id, sb, sb_number))

    out: list[LinkedSbOut] = []
    for sb_id, sb, sb_number in rows:
        sb_number_match = None
        is_duplicate = False
        if sb_number:
            stripped = sb_number.strip()
            if bl_sb_numbers:
                sb_number_match = stripped in bl_sb_numbers
            is_duplicate = sb_number_counts[stripped] > 1
        out.append(
            LinkedSbOut(
                id=sb_id,
                filename=sb["filename"],
                status=sb["status"],
                sb_number=sb_number,
                sb_number_match=sb_number_match,
                is_duplicate=is_duplicate,
                link_source=sb["link_source"] if sb_id == legacy_parent_id else "manual",
                fields=_sb_summary(bl_id, sb_id),
            )
        )

    reconciliation = None
    if bl_sb_numbers:
        uploaded_numbers = set(sb_number_counts)
        reconciliation = SbReconciliation(
            total_referenced=len(bl_sb_numbers),
            total_uploaded=len(out),
            missing_numbers=sorted(bl_sb_numbers - uploaded_numbers),
            duplicate_numbers=sorted(n for n, c in sb_number_counts.items() if c > 1),
            unrelated_numbers=sorted(uploaded_numbers - bl_sb_numbers),
        )
    return out, reconciliation


def _parse_sb_numbers(value: str | None) -> set[str]:
    """``shipping_bill_number_and_date`` varies by parser — a bare,
    comma-joined number list (gssw_bl._sb_numbers) or a single "<no> DT.
    <date>" pair (breakbulk_bl) — so pull out the 6-8 digit SB number(s)
    directly rather than assume either shape, for cross-checking an
    uploaded Shipping Bill's own number against what the BL itself names."""
    if not value:
        return set()
    return set(re.findall(r"\b\d{6,8}\b", value))


_SB_NUM_RE = re.compile(r"\b\d{6,8}\b")


def _sb_summary(bl_id: str, sb_id: str) -> list[FieldOut]:
    """The fixed curated Shipping Bill fields to show/export against one
    linked BL (see field_catalog.SB_EXPORT_FIELDS).

    HS Code is included from the SB only when the BL itself doesn't already
    carry one — no point duplicating a value the BL already has.
    """
    sb_ex = {e["field_key"]: e for e in repo.get_extractions(sb_id)}
    bl_ex = {e["field_key"]: e["value"] for e in repo.get_extractions(bl_id)}
    bl_has_hs_code = bool((bl_ex.get("hs_code") or "").strip())

    out: list[FieldOut] = []
    for key, label in SB_EXPORT_FIELDS:
        if key == "hs_code" and bl_has_hs_code:
            continue
        e = sb_ex.get(key)
        if e is None or not (e["value"] or "").strip():
            continue
        out.append(
            FieldOut(
                key=key, label=label, group="Linked Shipping Bill", type="text",
                value=e["value"], confidence=e["confidence"], ai_value=e["ai_value"],
                page=e["page"], bbox=json.loads(e["bbox"]) if e["bbox"] else None,
                source=e["source"],
            )
        )
    return out


def _suggested_export_fields(format_fingerprint: str | None, doc_type: str) -> list[str]:
    """Most recent saved template whose format matches this document's format."""
    if not format_fingerprint:
        return []
    key = format_key(format_fingerprint)
    valid = set(catalog_field_keys(doc_type))
    for tpl in repo.list_export_templates():  # newest first
        if tpl["format_fingerprint"] and format_key(tpl["format_fingerprint"]) == key:
            return [k for k in json.loads(tpl["selected_fields"]) if k in valid]
    return []


# --------------------------------------------------- Vessel-scoped bulk upload
def bulk_upload_to_vessel(
    vessel_id: str, files: list[tuple[str, bytes]], *, created_by: str | None = None,
) -> dict[str, list[str]]:
    """Upload many Bills of Lading / Shipping Bills under one Vessel in a
    single batch (the Export counterpart of link_house_bl_to_master,
    extended to many files at once — up to ~400). Each file's type is
    auto-detected, same as /ingest; Shipping Bills go first within the
    batch — same heuristic the frontend already used — so a same-batch
    Bill of Lading referencing it has the best chance of auto-linking as
    soon as its own extraction finishes.

    Deliberately returns only the id lists, not a DocumentDetail per file
    or a rebuilt vessel-level summary — the caller (the Vessel Workspace's
    own record list) already re-queries its own filtered view after a
    bulk upload, so there is nothing here worth paying to rebuild, same
    reasoning as link_house_bl_to_master's own docstring.
    """
    vessel = repo.get_vessel(vessel_id)
    if vessel is None:
        raise KeyError(vessel_id)

    ordered = sorted(files, key=lambda f: 0 if re.search(r"sb|shipping", f[0], re.I) else 1)

    uploaded: list[str] = []
    failed: list[str] = []
    for filename, content in ordered:
        try:
            doc_id = ingest_upload(
                filename, content, created_by=created_by, vessel_id=vessel_id,
            )
        except ValueError:
            failed.append(filename)
            continue
        uploaded.append(doc_id)
        schedule_extraction(doc_id)
    return {"uploaded": uploaded, "failed": failed}


# ------------------------------------------------------- Shipping Bill hierarchy
def link_bls(sb_id: str, doc_ids: list[str]) -> ShippingBillDetail:
    sb = repo.get_document(sb_id)
    if sb is None or sb["doc_type"] != "shipping_bill":
        raise KeyError(sb_id)
    repo.set_parent(doc_ids, sb_id)
    return get_shipping_bill_detail(sb_id)


def link_shipping_bill_to_bl(
    bl_id: str, filename: str, content: bytes, *,
    background: bool = True, created_by: str | None = None,
) -> DocumentDetail:
    """BL-first linking: upload a Shipping Bill and link it to *this* BL,
    regardless of whether its SB number matches — the user is asserting the
    relationship directly, so it doesn't wait on (or get second-guessed by)
    the automatic SB-number match. A BL can have many linked Shipping Bills
    (50+ supported) — each call adds one more, it never replaces existing
    links. Returns the BL's updated detail, with ``linked_shipping_bills``
    including the new SB (its curated fields fill in once extraction finishes).
    """
    bl = repo.get_document(bl_id)
    if bl is None or bl["doc_type"] != "bill_of_lading":
        raise KeyError(bl_id)

    sb_id = ingest_upload(
        filename, content, doc_type="shipping_bill", created_by=created_by,
        company_id=bl["company_id"],
    )
    repo.link_sb_to_bl(bl_id, sb_id, source="manual")
    if background:
        schedule_extraction(sb_id)
    else:
        run_extraction(sb_id)
    return get_document_detail(bl_id)


def link_existing_sb_to_bl(bl_id: str, sb_id: str) -> DocumentDetail:
    """Link an already-uploaded Shipping Bill to this BL (BL-first flow)."""
    bl = repo.get_document(bl_id)
    if bl is None or bl["doc_type"] != "bill_of_lading":
        raise KeyError(bl_id)
    sb = repo.get_document(sb_id)
    if sb is None or sb["doc_type"] != "shipping_bill":
        raise ValueError("sb_id must be an existing Shipping Bill")
    if bl["company_id"] and sb["company_id"] and bl["company_id"] != sb["company_id"]:
        raise ValueError("this Shipping Bill belongs to a different company")

    repo.link_sb_to_bl(bl_id, sb_id, source="manual")
    return get_document_detail(bl_id)


# --------------------------------------------------- Master BL / House BL
def link_house_bl_to_master(
    master_id: str, filename: str, content: bytes, *, created_by: str | None = None,
) -> str:
    """Upload a House BL and link it to this Master BL — the Import-category
    counterpart of link_shipping_bill_to_bl. Extraction is auto-scheduled by
    ingest_upload (see field_catalog.HOUSE_BL / parsers.yusen_hbl) the same
    way a Bill of Lading is for Export. Returns the new House BL's id.

    Deliberately does NOT build and return a DocumentDetail (unlike
    link_shipping_bill_to_bl) — the caller uploads many files in one batch
    (bulk Import uploads run to the hundreds), and that detail includes
    every currently-linked House BL; building it after each individual file
    would turn an O(n) batch into O(n^2). Build it once, after the batch.
    """
    master = repo.get_document(master_id)
    if master is None or master["doc_type"] != "master_bl":
        raise KeyError(master_id)

    house_id = ingest_upload(
        filename, content, doc_type="house_bl", created_by=created_by, vessel_id=master["vessel_id"],
    )
    repo.link_house_bl(master_id, house_id, source="manual")
    return house_id


def unlink_house_bl_from_master(master_id: str, house_id: str) -> DocumentDetail:
    master = repo.get_document(master_id)
    if master is None or master["doc_type"] != "master_bl":
        raise KeyError(master_id)
    repo.unlink_house_bl(master_id, house_id)
    return get_document_detail(master_id)


def unlink_sb_from_bl(bl_id: str, sb_id: str) -> DocumentDetail:
    """Remove one Shipping Bill from a BL's linked set, leaving the rest
    (and the Shipping Bill document itself) untouched."""
    bl = repo.get_document(bl_id)
    if bl is None or bl["doc_type"] != "bill_of_lading":
        raise KeyError(bl_id)

    repo.unlink_sb_from_bl(bl_id, sb_id)
    if bl["parent_id"] == sb_id:
        repo.set_parent([bl_id], None)
    return get_document_detail(bl_id)


def unlink_bls(sb_id: str, doc_ids: list[str]) -> ShippingBillDetail:
    sb = repo.get_document(sb_id)
    if sb is None or sb["doc_type"] != "shipping_bill":
        raise KeyError(sb_id)
    children = {r["id"] for r in repo.get_children(sb_id)}
    repo.set_parent([d for d in doc_ids if d in children], None)
    return get_shipping_bill_detail(sb_id)


def get_shipping_bill_detail(sb_id: str) -> ShippingBillDetail:
    sb = repo.get_document(sb_id)
    if sb is None or sb["doc_type"] != "shipping_bill":
        raise KeyError(sb_id)
    detail = get_document_detail(sb_id)
    linked: list[LinkedBlOut] = []
    for r in repo.get_children(sb_id):
        ex = {e["field_key"]: e["value"] for e in repo.get_extractions(r["id"])}
        linked.append(
            LinkedBlOut(
                **document_row_to_out(r),
                bl_number=ex.get("bl_number"),
                port_of_discharge=ex.get("port_of_discharge"),
            )
        )
    return ShippingBillDetail(**detail.model_dump(), linked_bls=linked)


def list_shipping_bills(limit: int = 50) -> list[ShippingBillOut]:
    rows = repo.list_documents(limit, doc_type="shipping_bill")
    counts = repo.child_counts([r["id"] for r in rows])
    return [
        ShippingBillOut(**document_row_to_out(r), bl_count=counts.get(r["id"], 0))
        for r in rows
    ]


def _linked_bl_out(row) -> LinkedBlOut:
    ex = {e["field_key"]: e["value"] for e in repo.get_extractions(row["id"])}
    return LinkedBlOut(
        **document_row_to_out(row),
        bl_number=ex.get("bl_number"),
        port_of_discharge=ex.get("port_of_discharge"),
    )


def list_hierarchy(limit: int = 200) -> HierarchyOut:
    """Everything the sidebar tree needs, in one call."""
    sb_rows = repo.list_documents(limit, doc_type="shipping_bill")
    counts = repo.child_counts([r["id"] for r in sb_rows])
    sbs: list[HierarchySbOut] = []
    for r in sb_rows:
        sb_ex = {e["field_key"]: e["value"] for e in repo.get_extractions(r["id"])}
        sbs.append(
            HierarchySbOut(
                **document_row_to_out(r),
                bl_count=counts.get(r["id"], 0),
                sb_number=sb_ex.get("sb_number"),
                linked_bls=[_linked_bl_out(c) for c in repo.get_children(r["id"])],
            )
        )
    unlinked = [
        _linked_bl_out(r)
        for r in repo.list_documents(limit, doc_type="bill_of_lading", unlinked=True)
    ]
    return HierarchyOut(shipping_bills=sbs, unlinked_bls=unlinked)


def export_hierarchy(
    sb_id: str,
    fmt: str = "xlsx",
    sb_fields: list[str] | None = None,
    bl_fields: list[str] | None = None,
) -> tuple[bytes, str, str]:
    if fmt not in ("xlsx", "pdf"):
        raise ValueError(f"unsupported export format: {fmt!r}")

    detail = get_shipping_bill_detail(sb_id)  # KeyError if not a Shipping Bill
    sb_map = {f.key: f.value for f in detail.fields}
    sb_map["_file"] = detail.filename
    sb_keys = [k for k in (sb_fields or catalog_field_keys("shipping_bill"))
               if k in set(catalog_field_keys("shipping_bill"))]

    bl_rows: list[dict] = []
    for bl in detail.linked_bls:
        bd = get_document_detail(bl.id)
        row = {f.key: f.value for f in bd.fields}
        row["_file"] = bd.filename
        bl_rows.append(row)
    bl_keys = _resolve_export_keys(bl_fields, None, bl_rows, catalog_field_keys("bill_of_lading"))

    if fmt == "xlsx":
        data = build_hierarchy_xlsx(sb_map, sb_keys, bl_rows, bl_keys)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        data = build_hierarchy_pdf(sb_map, sb_keys, bl_rows, bl_keys)
        media = "application/pdf"

    num = repo._first_number(sb_map.get("sb_number")) or sb_id[:8]
    return data, media, f"shipping_bill_{num}_{date.today().isoformat()}.{fmt}"


def _bl_with_sb_bytes(bl: DocumentDetail, fmt: str) -> bytes:
    """The actual BL-plus-every-linked-SB workbook/PDF bytes — the BL's fields
    on top (or page one), every linked Shipping Bill below it / after it as
    one row / one sheet each (supports 50+), using the fixed curated SB field
    set (see field_catalog.SB_EXPORT_FIELDS). Shared by the single-BL combined
    download and the bulk Submitted/Uploaded Data export, so a BL is exported
    the same way — complete with its Shipping Bills — everywhere.
    """
    bl_row = {f.key: f.value for f in bl.fields}
    bl_row["_file"] = bl.filename
    bl_keys = _resolve_export_keys(None, None, [bl_row], catalog_field_keys("bill_of_lading"))

    sb_cols_by_lsb = [lsb.fields for lsb in bl.linked_shipping_bills]
    sb_cols = _union_columns(sb_cols_by_lsb)
    sb_rows: list[dict] = []
    for lsb, fields in zip(bl.linked_shipping_bills, sb_cols_by_lsb):
        row = {f.key: f.value for f in fields}
        row["_file"] = lsb.filename
        sb_rows.append(row)

    if fmt == "xlsx":
        return build_bl_multi_sb_xlsx(bl_row, bl_keys, sb_rows, sb_cols)
    return build_bl_multi_sb_pdf(bl_row, bl_keys, sb_rows, sb_cols)


def export_bl_with_sb(bl_id: str, fmt: str = "xlsx") -> tuple[bytes, str, str]:
    if fmt not in ("xlsx", "pdf"):
        raise ValueError(f"unsupported export format: {fmt!r}")

    bl = get_document_detail(bl_id)  # KeyError if missing
    if bl.doc_type != "bill_of_lading":
        raise ValueError("only a Bill of Lading can be exported with its linked SB(s)")
    if not bl.linked_shipping_bills:
        raise ValueError("this Bill of Lading has no linked Shipping Bill")

    data = _bl_with_sb_bytes(bl, fmt)
    media = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if fmt == "xlsx" else "application/pdf"
    )
    num = repo._first_number({f.key: f.value for f in bl.fields}.get("bl_number")) or bl_id[:8]
    return data, media, f"bl_sb_{num}_{date.today().isoformat()}.{fmt}"


def _union_columns(field_lists: list[list[FieldOut]]) -> list[tuple[str, str]]:
    """Column (key, label) pairs across every linked SB's field list, in
    first-seen order — different SBs can have different fields populated
    (e.g. one missing HS Code), so the export needs every column any of
    them uses, not just the first SB's.
    """
    seen: dict[str, str] = {}
    for fields in field_lists:
        for f in fields:
            seen.setdefault(f.key, f.label)
    return list(seen.items())


def _job_id(doc_id: str) -> str:
    return f"PDF-JOB-{doc_id[:8].upper()}"


def list_records(**filters) -> list[RecordOut]:
    out: list[RecordOut] = []
    for r in repo.list_records(**filters):
        warnings = json.loads(r["warnings"]) if r["warnings"] else []
        # Cheap because both sides are already-extracted field text, not a
        # fresh OCR read — the referenced numbers come from the BL's own
        # 'shipping_bill_number_and_date' field, the linked numbers from a
        # single GROUP_CONCAT join done in repo.list_records's own SQL, so
        # this never re-reads a PDF just to render the overview list.
        ref_numbers = set(_SB_NUM_RE.findall(r["sb_ref_text"] or ""))
        linked_numbers = _SB_NUM_RE.findall(r["linked_sb_numbers"] or "")
        linked_counts = Counter(linked_numbers)
        missing_count = len(ref_numbers - set(linked_numbers)) if ref_numbers else 0
        duplicate_count = sum(1 for c in linked_counts.values() if c > 1)
        out.append(
            RecordOut(
                id=r["id"],
                job_id=_job_id(r["id"]),
                doc_type=r["doc_type"],
                doc_number=r["doc_number"],
                filename=r["filename"],
                status=r["status"],
                submitted=bool(r["submitted"]),
                field_count=r["field_count"] or 0,
                issue_count=len(warnings),
                parent_id=r["parent_id"],
                link_source=r["link_source"],
                linked_sb_count=r["linked_sb_count"] or 0,
                linked_house_bl_count=r["linked_house_bl_count"] or 0,
                sb_referenced_count=len(ref_numbers),
                sb_missing_count=missing_count,
                sb_duplicate_count=duplicate_count,
                vessel_id=r["vessel_id"],
                vessel_name=r["vessel_name"],
                company_id=r["company_id"],
                company_name=r["company_name"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
        )
    return out


def record_stats(submitted: bool | None = None, *, owner_id: str | None = None) -> RecordStats:
    return RecordStats(**repo.record_stats(submitted, owner_id=owner_id))


def submit_records(doc_ids: list[str]) -> int:
    """Submit records. A BL's Shipping Bills live inside its entry, so they
    are submitted together with it (otherwise they'd be stranded as pending
    entries of their own). The count returned is for the records asked for."""
    n = repo.mark_submitted(doc_ids, submitted=True)
    nested = [
        sb for d in doc_ids for sb in repo.all_linked_sb_ids(d) if sb not in doc_ids
    ]
    repo.mark_submitted(list(dict.fromkeys(nested)), submitted=True)
    return n


_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _export_stub(detail: DocumentDetail) -> str:
    """A short, filesystem-safe name for one document's export file."""
    num = next(
        (f.value for f in detail.fields if f.key in ("bl_number", "sb_number") and f.value),
        None,
    )
    base = num or (detail.filename or "").rsplit(".", 1)[0] or _job_id(detail.id)
    base = re.sub(r"[^A-Za-z0-9_.\-]+", "_", base).strip("_.")
    return (base or _job_id(detail.id))[:60]


def _unique_filename(stub: str, fmt: str, used: set[str]) -> str:
    name = f"{stub}.{fmt}"
    i = 2
    while name in used:
        name = f"{stub}_{i}.{fmt}"
        i += 1
    used.add(name)
    return name


def _build_single_export(fmt: str, row: dict, keys: list[str]) -> bytes:
    return build_xlsx([row], keys) if fmt == "xlsx" else build_pdf([row], keys)


def export_records(
    doc_ids: list[str], fmt: str = "xlsx"
) -> tuple[bytes, str, str]:
    """Excel/PDF export for a set of Submitted/Uploaded records.

    One document -> one file, returned directly. Several documents -> **one
    file per document** (never merged into a single workbook), delivered as a
    .zip so the browser still gets a single download. A Bill of Lading with
    linked Shipping Bills exports *with* them (same as the single-BL combined
    download) rather than just its own fields, using the fixed curated SB
    field set (see field_catalog.SB_EXPORT_FIELDS).
    """
    if fmt not in ("xlsx", "pdf"):
        raise ValueError(f"unsupported export format: {fmt!r}")
    if not doc_ids:
        raise ValueError("no records selected")

    entries: list[tuple[str, bytes]] = []
    for doc_id in doc_ids:
        detail = get_document_detail(doc_id)  # raises KeyError if missing
        stub = _export_stub(detail)
        if detail.doc_type == "bill_of_lading" and detail.linked_shipping_bills:
            # xlsx uses the same horizontal, two-sheet layout as the
            # combined export (just scoped to this one BL); PDF keeps its
            # existing per-document page layout, unaffected by this change.
            data = _bl_with_sb_tabular_xlsx_bytes(detail) if fmt == "xlsx" else _bl_with_sb_bytes(detail, fmt)
        else:
            row = {f.key: f.value for f in detail.fields}
            row["_file"] = detail.filename
            keys = _resolve_export_keys(None, None, [row], catalog_field_keys(detail.doc_type))
            data = _build_single_export(fmt, row, keys)
        entries.append((stub, data))

    stamp = date.today().isoformat()

    if len(entries) == 1:
        stub, data = entries[0]
        media = _XLSX_MEDIA if fmt == "xlsx" else "application/pdf"
        return data, media, f"{stub}.{fmt}"

    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for stub, data in entries:
            zf.writestr(_unique_filename(stub, fmt, used), data)
    return buf.getvalue(), "application/zip", f"bl_records_{len(doc_ids)}_{stamp}.zip"


def _bl_cols() -> list[tuple[str, str]]:
    return [(f["key"], f["label"]) for f in catalog("bill_of_lading")]


def _bl_row_and_sb_rows(detail: DocumentDetail) -> tuple[dict, list[tuple[str, dict]]]:
    """This BL's own field row, plus one (bl_number, sb_row) pair per linked
    Shipping Bill — the shared building block behind both the
    one-file-per-BL and the all-BLs-combined tabular xlsx exports, so a
    single BL's file and the combined file always lay out identically."""
    bl_row = {f.key: f.value for f in detail.fields}
    bl_row["_file"] = detail.filename
    bl_num = bl_row.get("bl_number") or detail.filename
    sb_rows: list[tuple[str, dict]] = []
    for lsb in detail.linked_shipping_bills:
        sb_row = {f.key: f.value for f in lsb.fields}
        sb_row["_file"] = lsb.filename
        sb_rows.append((bl_num, sb_row))
    return bl_row, sb_rows


def _bl_with_sb_tabular_xlsx_bytes(detail: DocumentDetail) -> bytes:
    """One BL's own xlsx in "Separate Excel Files" bulk-export mode — the
    same horizontal, two-sheet layout as the combined export
    (build_bl_records_xlsx), just scoped to this one BL, so every xlsx
    export (combined or separate) reads identically."""
    bl_row, sb_rows = _bl_row_and_sb_rows(detail)
    return build_bl_records_xlsx([bl_row], _bl_cols(), sb_rows, SB_EXPORT_FIELDS)


def export_records_combined(doc_ids: list[str]) -> tuple[bytes, str, str]:
    """Several Bills of Lading merged into ONE Excel file — the alternative
    to ``export_records``'s one-file-per-document .zip. Exactly two sheets
    regardless of how many BLs/SBs are selected: a tabular "Bills of Lading"
    sheet (one row per BL) and a tabular "Shipping Bills" sheet (one row per
    Shipping Bill, led by a "BL Number" column naming its parent BL). A
    selected document that isn't a Bill of Lading is skipped — this export
    is BL-centric and a standalone Shipping Bill has no BL row to join.
    """
    if not doc_ids:
        raise ValueError("no records selected")

    bl_rows: list[dict] = []
    sb_rows: list[tuple[str, dict]] = []
    for doc_id in doc_ids:
        detail = get_document_detail(doc_id)  # raises KeyError if missing
        if detail.doc_type != "bill_of_lading":
            continue
        row, rows = _bl_row_and_sb_rows(detail)
        bl_rows.append(row)
        sb_rows.extend(rows)

    if not bl_rows:
        raise ValueError("no Bills of Lading in the selection")

    data = build_bl_records_xlsx(bl_rows, _bl_cols(), sb_rows, SB_EXPORT_FIELDS)
    stamp = date.today().isoformat()
    return data, _XLSX_MEDIA, f"bl_records_combined_{len(bl_rows)}_{stamp}.xlsx"


def _bl_hs_items(sb_rows: list[dict]) -> list[dict]:
    """One entry per unique (HS code, description) pair on each of a BL's
    linked Shipping Bills, tagged with the Shipping Bill No. it came from.
    Each SB's own ``hs_code`` (comma list) and ``cargo_description``
    (newline list) are already aligned 1:1 by position — see
    ``icegate_sb._hs_codes`` — so zipping them pairs each code with its own
    description. Dedup is scoped to *each SB individually* (a multi-page SB
    can list the same item on more than one page) and never across
    different SBs, so every Shipping Bill linked to the BL still gets its
    own row(s) here even when another SB happens to carry an identical HS
    code/description. An SB with no HS code at all still gets one (blank)
    row, so it isn't silently missing from the Summary."""
    items: list[dict] = []
    for row in sb_rows:
        sb_no = row.get("sb_number") or ""
        codes = [c.strip() for c in (row.get("hs_code") or "").split(",") if c.strip()]
        if not codes:
            items.append({"sb_number": sb_no, "hs_code": "", "description": ""})
            continue
        descs = (row.get("cargo_description") or "").split("\n")
        descs += [""] * (len(codes) - len(descs))
        seen: set[tuple[str, str]] = set()
        for code, desc in zip(codes, descs):
            key = (code, desc.strip())
            if key in seen:
                continue
            seen.add(key)
            items.append({"sb_number": sb_no, "hs_code": code, "description": desc.strip()})
    return items


def _bl_summary_entries(doc_ids: list[str]) -> list[dict]:
    """Every selected Bill of Lading's own fields, its linked Shipping
    Bills' fields, and a precomputed reconciliation/cargo-totals summary —
    the shared gathering step behind the Summary file of the split BL/SB
    export. A selected document that isn't a Bill of Lading is skipped (SB
    numbers/weight are themselves sourced from a BL's own linked SBs)."""
    entries: list[dict] = []
    for doc_id in doc_ids:
        detail = get_document_detail(doc_id)  # raises KeyError if missing
        if detail.doc_type != "bill_of_lading":
            continue
        bl_row = {f.key: f.value for f in detail.fields}
        sb_rows = [{f.key: f.value for f in lsb.fields} for lsb in detail.linked_shipping_bills]

        matched = sum(1 for lsb in detail.linked_shipping_bills if lsb.sb_number_match is True)
        mismatched = sum(1 for lsb in detail.linked_shipping_bills if lsb.sb_number_match is False)
        rec = detail.sb_reconciliation
        summary = {
            "sb_total": len(detail.linked_shipping_bills),
            "sb_matched": matched,
            "sb_mismatched": mismatched,
            "sb_missing": len(rec.missing_numbers) if rec else 0,
            "sb_duplicate": len(rec.duplicate_numbers) if rec else 0,
            "total_packages": sum_quantities_total(
                [r.get("sb_packages") for r in sb_rows]
            ),
            "total_gross_weight": sum_quantities_total(
                [r.get("sb_gross_weight") for r in sb_rows]
            ),
            "hs_items": _bl_hs_items(sb_rows),
        }
        entries.append({"bl": bl_row, "sbs": sb_rows, "summary": summary})
    return entries


def export_records_split(doc_ids: list[str], fmt: str = "xlsx") -> tuple[bytes, str, str]:
    """Three separate files, zipped into one download, in whichever format
    was asked for: every selected Bill of Lading's own details, every one
    of their linked Shipping Bills' details (BL Number identifying each
    one's parent, without repeating that BL's own fields), and a Summary of
    how each BL's linked SBs reconcile plus their combined cargo totals —
    instead of merging BL and SB rows into sheets/pages of the same file
    (that's what ``export_records_combined`` is for). xlsx is laid out
    horizontally throughout (fields as columns, records as rows); pdf keeps
    one page per record as Field/Value rows. A selected document that isn't
    a Bill of Lading is skipped, same as the other bulk BL exports. Always
    three files, even for a single selected BL, so the download is uniform.
    """
    if fmt not in ("xlsx", "pdf"):
        raise ValueError(f"unsupported export format: {fmt!r}")
    if not doc_ids:
        raise ValueError("no records selected")

    bl_rows: list[dict] = []
    sb_rows: list[tuple[str, dict]] = []
    for doc_id in doc_ids:
        detail = get_document_detail(doc_id)  # raises KeyError if missing
        if detail.doc_type != "bill_of_lading":
            continue
        row, rows = _bl_row_and_sb_rows(detail)
        bl_rows.append(row)
        sb_rows.extend(rows)

    if not bl_rows:
        raise ValueError("no Bills of Lading in the selection")

    summary_entries = _bl_summary_entries(doc_ids)
    stamp = date.today().isoformat()
    bl_cols = _bl_cols()

    if fmt == "xlsx":
        bl_data = build_bl_data_xlsx(bl_rows, bl_cols)
        bl_sb_data = build_bl_sb_data_xlsx(sb_rows, SB_EXPORT_FIELDS)
        summary = build_summary_xlsx(summary_entries)
    else:
        bl_data = build_bl_data_pdf(bl_rows, bl_cols)
        bl_sb_data = build_bl_sb_data_pdf(bl_rows, bl_cols, sb_rows, SB_EXPORT_FIELDS)
        summary = build_summary_pdf(summary_entries)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"bl_data_{stamp}.{fmt}", bl_data)
        zf.writestr(f"bl_shipping_bills_{stamp}.{fmt}", bl_sb_data)
        zf.writestr(f"summary_{stamp}.{fmt}", summary)
    return buf.getvalue(), "application/zip", f"bl_records_{len(bl_rows)}_{stamp}.zip"


def export_master_bl_split(doc_ids: list[str]) -> tuple[bytes, str, str]:
    """Three files zipped into one download — the Import-side mirror of
    export_records_split: every selected Master BL's own metadata, every one
    of their linked House BLs, and a per-vessel Summary. No field catalog
    exists yet for Master BL / House BL (see field_catalog.py — still
    waiting on real samples), so these sheets carry document/linkage
    metadata rather than extracted fields; the shape is ready to grow once
    that extraction exists, same column-per-row layout as Export's own
    split. A selected document that isn't a Master BL is skipped."""
    if not doc_ids:
        raise ValueError("no records selected")

    master_rows: list[dict] = []
    house_rows: list[dict] = []
    vessel_totals: dict[str, dict] = {}

    for doc_id in doc_ids:
        detail = get_document_detail(doc_id)
        if detail.doc_type != "master_bl":
            continue
        vessel = repo.get_vessel(detail.vessel_id) if detail.vessel_id else None
        vessel_label = vessel["name"] if vessel else "Unassigned"
        company_label = vessel["company_name"] if vessel else ""

        master_rows.append({
            "job_id": _job_id(detail.id),
            "filename": detail.filename,
            "vessel": vessel_label,
            "company": company_label,
            "status": detail.status,
            "submitted": "Yes" if detail.submitted else "No",
            "house_bl_count": len(detail.linked_house_bls),
            "created_at": detail.created_at,
        })
        for h in detail.linked_house_bls:
            house_rows.append({
                "master_job_id": _job_id(detail.id),
                "master_filename": detail.filename,
                "house_filename": h.filename,
                "house_status": h.status,
            })

        totals = vessel_totals.setdefault(
            vessel_label, {"vessel": vessel_label, "company": company_label,
                           "master_bl_count": 0, "house_bl_count": 0, "submitted_count": 0},
        )
        totals["master_bl_count"] += 1
        totals["house_bl_count"] += len(detail.linked_house_bls)
        if detail.submitted:
            totals["submitted_count"] += 1

    if not master_rows:
        raise ValueError("no Master BLs in the selection")

    stamp = date.today().isoformat()
    master_data = build_master_bl_data_xlsx(master_rows)
    house_data = build_master_house_bl_xlsx(house_rows)
    summary = build_master_bl_summary_xlsx(list(vessel_totals.values()))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"master_bl_data_{stamp}.xlsx", master_data)
        zf.writestr(f"master_house_bl_{stamp}.xlsx", house_data)
        zf.writestr(f"summary_{stamp}.xlsx", summary)
    return buf.getvalue(), "application/zip", f"master_bl_records_{len(master_rows)}_{stamp}.zip"


def _resolve_export_keys(
    explicit: list[str] | None,
    template_row: sqlite3.Row | None,
    rows: list[dict],
    all_keys: list[str],
) -> list[str]:
    valid = set(all_keys)
    if explicit:
        keys = [k for k in explicit if k in valid]
    elif template_row is not None:
        selected = [k for k in json.loads(template_row["selected_fields"]) if k in valid]
        order = template_row["column_order"]
        if order:
            ordered = [k for k in json.loads(order) if k in selected]
            selected = ordered + [k for k in selected if k not in ordered]
        keys = selected
    else:
        present: set[str] = set()
        for r in rows:
            present |= {k for k, v in r.items() if not k.startswith("_") and v}
        keys = [k for k in all_keys if k in present] or list(all_keys)

    if not keys:
        raise ValueError("no fields selected for export")
    return keys


def export_documents(
    doc_ids: list[str],
    fmt: str = "xlsx",
    field_keys: list[str] | None = None,
    template_id: str | None = None,
) -> tuple[bytes, str, str]:
    if fmt not in ("xlsx", "pdf"):
        raise ValueError(f"unsupported export format: {fmt!r}")
    if not doc_ids:
        raise ValueError("no documents selected")

    rows: list[dict] = []
    doc_type = "bill_of_lading"
    for doc_id in doc_ids:
        detail = get_document_detail(doc_id)  # raises KeyError if missing
        doc_type = detail.doc_type
        row = {f.key: f.value for f in detail.fields}
        row["_file"] = detail.filename
        rows.append(row)

    template_row = repo.get_export_template(template_id) if template_id else None
    keys = _resolve_export_keys(
        field_keys, template_row, rows, catalog_field_keys(doc_type)
    )

    if fmt == "xlsx":
        data = build_xlsx(rows, keys)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        data = build_pdf(rows, keys)
        media = "application/pdf"

    stamp = date.today().isoformat()
    name = (
        f"bl_{doc_ids[0][:8]}_{stamp}.{fmt}"
        if len(doc_ids) == 1
        else f"bl_export_{len(doc_ids)}_{stamp}.{fmt}"
    )
    return data, media, name


def document_row_to_out(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "doc_type": row["doc_type"],
        "parent_id": row["parent_id"],
        "link_source": row["link_source"],
        "submitted": bool(row["submitted"]),
        "status": row["status"],
        "engine": row["engine"],
        "page_count": row["page_count"],
        "has_scanned_pages": bool(row["has_scanned_pages"]),
        "format_fingerprint": row["format_fingerprint"],
        "created_by": row["created_by"] if "created_by" in row.keys() else None,
        "vessel_id": row["vessel_id"] if "vessel_id" in row.keys() else None,
        "vessel_name": row["vessel_name"] if "vessel_name" in row.keys() else None,
        "company_id": row["company_id"] if "company_id" in row.keys() else None,
        "company_name": row["company_name"] if "company_name" in row.keys() else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
