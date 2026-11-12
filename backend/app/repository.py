"""Typed CRUD over the SQLite schema. All SQL lives here."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone

from .db import get_conn
from .models import ExtractionResult, FieldValue


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _uid() -> str:
    return uuid.uuid4().hex


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip()
    return v or None


# --------------------------------------------------------------------- documents
def create_document(
    *, filename: str, stored_path: str, content_sha256: str | None,
    page_count: int | None, doc_type: str = "bill_of_lading",
    parent_id: str | None = None, created_by: str | None = None,
    vessel_id: str | None = None, company_id: str | None = None,
) -> str:
    doc_id = _uid()
    ts = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO documents
                 (id, filename, stored_path, content_sha256, page_count,
                  doc_type, parent_id, created_by, vessel_id, company_id,
                  status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?, ?)""",
            (doc_id, filename, stored_path, content_sha256, page_count,
             doc_type, parent_id, created_by, vessel_id, company_id, ts, ts),
        )
    return doc_id


def get_document(doc_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            """SELECT d.*, v.name AS vessel_name, c.company_name AS company_name
                 FROM documents d
                 LEFT JOIN vessels v ON v.id = d.vessel_id
                 LEFT JOIN companies c ON c.id = d.company_id
                WHERE d.id = ?""",
            (doc_id,),
        ).fetchone()


def get_documents(doc_ids: list[str]) -> dict[str, sqlite3.Row]:
    """Batched get_document — one query instead of one per id. Used wherever
    a list of linked document ids (House BLs under a Master BL, BLs under a
    Shipping Bill, ...) needs their rows: avoids the N+1 query pattern that
    turns O(n) linked-document listings into O(n^2) across a bulk batch."""
    if not doc_ids:
        return {}
    marks = ",".join("?" * len(doc_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT d.*, v.name AS vessel_name, c.company_name AS company_name
                  FROM documents d
                  LEFT JOIN vessels v ON v.id = d.vessel_id
                  LEFT JOIN companies c ON c.id = d.company_id
                 WHERE d.id IN ({marks})""",
            doc_ids,
        ).fetchall()
    return {r["id"]: r for r in rows}


def stored_path_still_used(stored_path: str, exclude_doc_id: str) -> bool:
    """True if some OTHER document row still points at this stored PDF —
    uploads are deduplicated by content hash (see service.ingest_upload), so
    two different document records can share one file on disk; only delete
    the file itself once nothing references it any more."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM documents WHERE stored_path = ? AND id != ? LIMIT 1",
            (stored_path, exclude_doc_id),
        ).fetchone()
    return row is not None


def delete_document_row(doc_id: str) -> sqlite3.Row | None:
    """Delete one document row. FK cascades (ON DELETE CASCADE/SET NULL,
    foreign_keys=ON in db.get_conn) take care of its extractions,
    corrections, bl_sb_links, master_house_bl_links rows and any child's
    now-dangling parent_id — the caller only needs to decide whether the
    stored PDF on disk is now orphaned (see stored_path_still_used)."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    return row


def delete_document_rows(doc_ids: list[str]) -> list[sqlite3.Row]:
    """Batched delete_document_row — one SELECT + one DELETE instead of two
    per id, for a bulk-delete batch that can run into the hundreds."""
    if not doc_ids:
        return []
    marks = ",".join("?" * len(doc_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM documents WHERE id IN ({marks})", doc_ids
        ).fetchall()
        conn.execute(f"DELETE FROM documents WHERE id IN ({marks})", doc_ids)
    return rows


def document_counts_by_vessel(doc_type: str = "master_bl") -> dict[str, int]:
    """How many Master BLs each vessel has — the Vessel list in a Company
    Workspace shows this inline instead of a separate click-through."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT vessel_id, COUNT(*) AS n FROM documents "
            "WHERE doc_type = ? AND vessel_id IS NOT NULL GROUP BY vessel_id",
            (doc_type,),
        ).fetchall()
    return {r["vessel_id"]: r["n"] for r in rows}


def any_document_count_for_vessel(vessel_id: str) -> int:
    """Every document under this vessel regardless of doc_type — Master BL
    and House BL (Import) or Bill of Lading and Shipping Bill (Export),
    since a vessel is shared infrastructure between both sides now. Used
    to block deleting a vessel that still has uploads under it, the same
    way Company Master blocks deleting a company that's still in use."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM documents WHERE vessel_id = ?", (vessel_id,)
        ).fetchone()
    return row["n"] if row else 0


def document_counts_by_company(doc_types: list[str]) -> list[sqlite3.Row]:
    """Company-wise analytics across both sides of the app: an Export
    document carries ``company_id`` directly; an Import document (Master BL,
    or a House BL that inherited its vessel) only carries ``vessel_id``, so
    its company is resolved through the vessel. ``COALESCE`` lets one query
    serve both categories without a category-specific branch."""
    marks = ",".join("?" * len(doc_types))
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT COALESCE(d.company_id, v.company_id) AS company_id,
                       COALESCE(c.company_name, 'Unassigned') AS company_name,
                       COUNT(*) AS n
                  FROM documents d
                  LEFT JOIN vessels v ON v.id = d.vessel_id
                  LEFT JOIN companies c ON c.id = COALESCE(d.company_id, v.company_id)
                 WHERE d.doc_type IN ({marks})
                 GROUP BY COALESCE(d.company_id, v.company_id)
                 ORDER BY n DESC""",
            doc_types,
        ).fetchall()


_UNSET = object()


def _nested_sb(alias: str) -> str:
    """SQL condition: this document is a Shipping Bill that belongs under a
    BL — linked via the BL-first flow (bl_sb_links) or, for older records,
    referenced as a BL's parent_id. Such SBs are shown inside their BL's
    entry rather than as entries of their own."""
    return (
        f"({alias}.doc_type = 'shipping_bill' AND ("
        f"EXISTS (SELECT 1 FROM bl_sb_links l WHERE l.sb_id = {alias}.id) OR "
        f"EXISTS (SELECT 1 FROM documents b WHERE b.parent_id = {alias}.id "
        f"AND b.doc_type = 'bill_of_lading')))"
    )


def _nested_house_bl(alias: str) -> str:
    """Same idea as _nested_sb, for the Master BL / House BL hierarchy: a
    House BL linked to a Master BL is shown inside that Master BL's entry,
    not as a top-level record of its own."""
    return (
        f"({alias}.doc_type = 'house_bl' AND "
        f"EXISTS (SELECT 1 FROM master_house_bl_links l WHERE l.house_bl_id = {alias}.id))"
    )


def list_documents(
    limit: int = 50,
    *,
    doc_type: str | None = None,
    parent_id: object = _UNSET,   # None means "no parent"; _UNSET means "any"
    unlinked: bool = False,
    owner_id: str | None = None,  # None (admin) = everyone's; else only this user's own
) -> list[sqlite3.Row]:
    clauses, params = [], []
    if doc_type:
        clauses.append("doc_type = ?")
        params.append(doc_type)
    if owner_id:
        # a record with no owner predates per-user ownership — it stays
        # visible to every user rather than silently vanishing for everyone
        # but an admin (see the matching note on _assert_owns_or_admin).
        clauses.append("(created_by = ? OR created_by IS NULL)")
        params.append(owner_id)
    if unlinked or parent_id is None:
        clauses.append("parent_id IS NULL")
        if unlinked and doc_type == "shipping_bill":
            clauses.append(f"NOT {_nested_sb('documents')}")
        elif unlinked and doc_type == "house_bl":
            clauses.append(f"NOT {_nested_house_bl('documents')}")
    elif parent_id is not _UNSET:
        clauses.append("parent_id = ?")
        params.append(parent_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM documents {where} ORDER BY created_at DESC LIMIT ?", params
        ).fetchall()


def list_records(
    *, q: str | None = None, status: str | None = None,
    doc_type: str | list[str] | None = None,
    date_from: str | None = None, date_to: str | None = None, limit: int = 200,
    submitted: bool | None = None, owner_id: str | None = None,
    vessel_id: str | None = None, company_id: str | None = None,
) -> list[sqlite3.Row]:
    clauses: list[str] = [f"NOT ({_nested_sb('d')} OR {_nested_house_bl('d')})"]
    params: list = []
    if vessel_id:
        clauses.append("d.vessel_id = ?")
        params.append(vessel_id)
    if company_id:
        # a record with no company predates Export's Company Workspace — it
        # stays visible inside every company (same "legacy stays visible"
        # leniency as owner_id below) rather than disappearing once this
        # screen started requiring a company to be picked first.
        clauses.append("(d.company_id = ? OR d.company_id IS NULL)")
        params.append(company_id)
    if submitted is not None:
        clauses.append("d.submitted = ?")
        params.append(1 if submitted else 0)
    if owner_id:
        # a record with no owner predates per-user ownership — it stays
        # visible to every user rather than silently vanishing for everyone
        # but an admin (see the matching note on _assert_owns_or_admin).
        clauses.append("(d.created_by = ? OR d.created_by IS NULL)")
        params.append(owner_id)
    if q:
        like = f"%{q}%"
        # a BL also matches on any of its linked Shipping Bills' number/file,
        # since those no longer have rows of their own to search
        clauses.append(
            "(d.filename LIKE ? OR d.id LIKE ? OR EXISTS (SELECT 1 FROM extractions e2 "
            "WHERE e2.doc_id = d.id AND e2.field_key IN ('bl_number','sb_number') "
            "AND e2.value LIKE ?) OR EXISTS (SELECT 1 FROM bl_sb_links l "
            "JOIN documents s ON s.id = l.sb_id "
            "LEFT JOIN extractions e3 ON e3.doc_id = s.id AND e3.field_key = 'sb_number' "
            "WHERE l.bl_id = d.id AND (s.filename LIKE ? OR e3.value LIKE ?)) "
            "OR EXISTS (SELECT 1 FROM documents s2 "
            "LEFT JOIN extractions e4 ON e4.doc_id = s2.id AND e4.field_key = 'sb_number' "
            "WHERE s2.id = d.parent_id AND (s2.filename LIKE ? OR e4.value LIKE ?)))"
        )
        params += [like, like, like, like, like, like, like]
    if status:
        clauses.append("d.status = ?")
        params.append(status)
    if doc_type:
        if isinstance(doc_type, str):
            clauses.append("d.doc_type = ?")
            params.append(doc_type)
        else:
            marks = ",".join("?" * len(doc_type))
            clauses.append(f"d.doc_type IN ({marks})")
            params += list(doc_type)
    if date_from:
        clauses.append("substr(d.created_at,1,10) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("substr(d.created_at,1,10) <= ?")
        params.append(date_to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT d.*, v.name AS vessel_name, c.company_name AS company_name,
                  (SELECT COUNT(*) FROM extractions e WHERE e.doc_id = d.id
                     AND e.value IS NOT NULL AND e.value <> '') AS field_count,
                  (SELECT e.value FROM extractions e WHERE e.doc_id = d.id
                     AND e.field_key IN ('bl_number','sb_number') AND e.value <> ''
                     ORDER BY e.field_key LIMIT 1) AS doc_number,
                  (SELECT COUNT(*) FROM (
                     SELECT l.sb_id AS sid FROM bl_sb_links l WHERE l.bl_id = d.id
                     UNION
                     SELECT d.parent_id WHERE d.parent_id IS NOT NULL
                  )) AS linked_sb_count,
                  (SELECT COUNT(*) FROM master_house_bl_links l4
                     WHERE l4.master_bl_id = d.id) AS linked_house_bl_count,
                  (SELECT e7.value FROM extractions e7 WHERE e7.doc_id = d.id
                     AND e7.field_key = 'shipping_bill_number_and_date') AS sb_ref_text,
                  (SELECT GROUP_CONCAT(e8.value, '||') FROM (
                     SELECT sb_id FROM bl_sb_links WHERE bl_id = d.id
                     UNION
                     SELECT d.parent_id WHERE d.parent_id IS NOT NULL
                   ) sbs
                   JOIN extractions e8 ON e8.doc_id = sbs.sb_id AND e8.field_key = 'sb_number'
                  ) AS linked_sb_numbers
                FROM documents d
                LEFT JOIN vessels v ON v.id = d.vessel_id
                LEFT JOIN companies c ON c.id = d.company_id
                {where}
                ORDER BY d.created_at DESC LIMIT ?""",
            params,
        ).fetchall()


def record_stats(submitted: bool | None = None, *, owner_id: str | None = None) -> dict:
    # Shipping Bills nested under a BL are part of that BL's entry, not
    # records of their own, so they don't count towards these totals.
    conds = [f"NOT {_nested_sb('d')}"]
    params: list = []
    if submitted is not None:
        conds.append("d.submitted = ?")
        params.append(1 if submitted else 0)
    if owner_id:
        conds.append("(d.created_by = ? OR d.created_by IS NULL)")
        params.append(owner_id)
    scope = "WHERE " + " AND ".join(conds)
    with get_conn() as conn:
        by_status = {
            r["status"]: r["n"]
            for r in conn.execute(
                f"SELECT d.status AS status, COUNT(*) AS n FROM documents d {scope} "
                "GROUP BY d.status",
                params,
            ).fetchall()
        }
        last_saved = conn.execute(
            f"SELECT MAX(d.updated_at) AS m FROM documents d {scope}", params
        ).fetchone()["m"]
        needs = conn.execute(
            f"SELECT COUNT(*) AS n FROM documents d {scope} AND "
            "(d.status = 'uploaded' OR (d.warnings IS NOT NULL AND d.warnings <> '[]'))",
            params,
        ).fetchone()["n"]
    total = sum(by_status.values())
    complete = sum(by_status.get(s, 0) for s in ("extracted", "reviewed", "exported"))
    return {
        "total": total, "complete": complete, "needs_review": needs,
        "by_status": by_status, "last_saved": last_saved,
    }


def mark_submitted(doc_ids: list[str], submitted: bool = True) -> int:
    if not doc_ids:
        return 0
    marks = ",".join("?" * len(doc_ids))
    ts = _now()
    with get_conn() as conn:
        cur = conn.execute(
            f"""UPDATE documents
                   SET submitted = ?, submitted_at = ?, updated_at = ?
                 WHERE id IN ({marks})""",
            (1 if submitted else 0, ts if submitted else None, ts, *doc_ids),
        )
        return cur.rowcount


def get_children(parent_id: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM documents WHERE parent_id = ? ORDER BY created_at", (parent_id,)
        ).fetchall()


def child_counts(parent_ids: list[str]) -> dict[str, int]:
    if not parent_ids:
        return {}
    marks = ",".join("?" * len(parent_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT parent_id, COUNT(*) AS n FROM documents
                WHERE parent_id IN ({marks}) GROUP BY parent_id""",
            parent_ids,
        ).fetchall()
    return {r["parent_id"]: r["n"] for r in rows}


def set_parent(
    child_ids: list[str], parent_id: str | None, *, source: str = "manual"
) -> int:
    if not child_ids:
        return 0
    marks = ",".join("?" * len(child_ids))
    ts = _now()
    link_source = source if parent_id is not None else None
    with get_conn() as conn:
        cur = conn.execute(
            f"""UPDATE documents SET parent_id = ?, link_source = ?, updated_at = ?
                WHERE id IN ({marks}) AND doc_type = 'bill_of_lading'""",
            (parent_id, link_source, ts, *child_ids),
        )
        return cur.rowcount


# ------------------------------------------------------------------- users
def create_user(
    *, username: str, password_hash: str, role: str = "user",
    can_export: bool = True, can_import: bool = True,
) -> str:
    user_id = _uid()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO users (id, username, password_hash, role, can_export, can_import, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, password_hash, role, int(can_export), int(can_import), _now()),
        )
    return user_id


def update_user_role(user_id: str, role: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))


def update_user_rights(user_id: str, *, can_export: bool, can_import: bool) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET can_export = ?, can_import = ? WHERE id = ?",
            (int(can_export), int(can_import), user_id),
        )


def get_user_by_username(username: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()


def get_user(user_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def list_users() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()


def delete_user(user_id: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cur.rowcount


def set_user_password(user_id: str, password_hash: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
        )


def register_failed_login(user_id: str) -> int:
    """Increments the failed-login counter and returns the new count."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET failed_login_attempts = failed_login_attempts + 1 WHERE id = ?",
            (user_id,),
        )
        return conn.execute(
            "SELECT failed_login_attempts FROM users WHERE id = ?", (user_id,)
        ).fetchone()["failed_login_attempts"]


def lock_user(user_id: str, locked_until: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET locked_until = ? WHERE id = ?", (locked_until, user_id))


def clear_failed_logins(user_id: str) -> None:
    """Resets the lockout state — called on a successful login or an admin
    password reset, either of which should let the account in again."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET failed_login_attempts = 0, locked_until = NULL WHERE id = ?",
            (user_id,),
        )


# ---------------------------------------------------------------- sessions
def create_session(*, token: str, user_id: str, created_at: str, expires_at: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, created_at, expires_at),
        )


def get_session(token: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sessions WHERE token = ?", (token,)
        ).fetchone()


def delete_session(token: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def delete_sessions_for_user(user_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


# --------------------------------------------------------- BL-first SB links
def link_sb_to_bl(bl_id: str, sb_id: str, *, source: str = "manual") -> str:
    """Link one Shipping Bill to one BL. Idempotent — linking the same pair
    twice is a no-op, so bulk/repeated uploads never create duplicates."""
    link_id = _uid()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO bl_sb_links (id, bl_id, sb_id, link_source, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (bl_id, sb_id) DO NOTHING""",
            (link_id, bl_id, sb_id, source, _now()),
        )
    return link_id


def unlink_sb_from_bl(bl_id: str, sb_id: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM bl_sb_links WHERE bl_id = ? AND sb_id = ?", (bl_id, sb_id)
        )
        return cur.rowcount


def linked_sb_ids(bl_id: str) -> list[str]:
    """Every Shipping Bill id linked to this BL via the BL-first flow, oldest first."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT sb_id FROM bl_sb_links WHERE bl_id = ? ORDER BY created_at", (bl_id,)
        ).fetchall()
    return [r["sb_id"] for r in rows]


def all_linked_sb_ids(bl_id: str) -> list[str]:
    """Every Shipping Bill that sits under this BL — its BL-first links plus,
    for older records, the SB still tracked via documents.parent_id."""
    ids = linked_sb_ids(bl_id)
    row = get_document(bl_id)
    if (
        row is not None
        and row["doc_type"] == "bill_of_lading"
        and row["parent_id"]
        and row["parent_id"] not in ids
    ):
        ids.append(row["parent_id"])
    return ids


def linked_sb_counts(bl_ids: list[str]) -> dict[str, int]:
    if not bl_ids:
        return {}
    marks = ",".join("?" * len(bl_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT bl_id, COUNT(*) AS n FROM bl_sb_links
                WHERE bl_id IN ({marks}) GROUP BY bl_id""",
            bl_ids,
        ).fetchall()
    return {r["bl_id"]: r["n"] for r in rows}


# ----------------------------------------------------- master/house BL links
def link_house_bl(master_bl_id: str, house_bl_id: str, *, source: str = "manual") -> str:
    """Link one House BL to one Master BL. Idempotent, same as link_sb_to_bl."""
    link_id = _uid()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO master_house_bl_links
                 (id, master_bl_id, house_bl_id, link_source, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (master_bl_id, house_bl_id) DO NOTHING""",
            (link_id, master_bl_id, house_bl_id, source, _now()),
        )
    return link_id


def unlink_house_bl(master_bl_id: str, house_bl_id: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM master_house_bl_links WHERE master_bl_id = ? AND house_bl_id = ?",
            (master_bl_id, house_bl_id),
        )
        return cur.rowcount


def linked_house_bl_ids(master_bl_id: str) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT house_bl_id FROM master_house_bl_links WHERE master_bl_id = ? ORDER BY created_at",
            (master_bl_id,),
        ).fetchall()
    return [r["house_bl_id"] for r in rows]


def linked_house_bl_counts(master_bl_ids: list[str]) -> dict[str, int]:
    if not master_bl_ids:
        return {}
    marks = ",".join("?" * len(master_bl_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT master_bl_id, COUNT(*) AS n FROM master_house_bl_links
                WHERE master_bl_id IN ({marks}) GROUP BY master_bl_id""",
            master_bl_ids,
        ).fetchall()
    return {r["master_bl_id"]: r["n"] for r in rows}


# ------------------------------------------------------------------ activity
def log_activity(
    *, user_id: str | None, username: str, action: str,
    doc_type: str | None = None, category: str | None = None, detail: str | None = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO activity_log (id, user_id, username, action, doc_type, category, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (_uid(), user_id, username, action, doc_type, category, detail, _now()),
        )


def list_activity(
    *, user_id: str | None = None, category: str | None = None, limit: int = 200
) -> list[sqlite3.Row]:
    clauses, params = [], []
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if category:
        # an account-level action (category IS NULL, e.g. login) shows up in
        # both sides' feeds — it isn't Export- or Import-specific data.
        clauses.append("(category = ? OR category IS NULL)")
        params.append(category)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM activity_log {where} ORDER BY created_at DESC LIMIT ?", params
        ).fetchall()


def activity_counts_by_user(*, category: str | None = None) -> list[sqlite3.Row]:
    """Per-user, per-action totals — the admin analytics dashboard's
    "by user" breakdown, and a regular user's own activity summary."""
    clauses, params = [], []
    if category:
        clauses.append("(category = ? OR category IS NULL)")
        params.append(category)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT user_id, username, action, COUNT(*) AS n
                  FROM activity_log {where}
                 GROUP BY user_id, username, action
                 ORDER BY username, action""",
            params,
        ).fetchall()


def document_counts_by_type() -> list[sqlite3.Row]:
    """Per doc_type/status totals across every document — the admin
    analytics dashboard's document counts."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT doc_type, status, COUNT(*) AS n FROM documents GROUP BY doc_type, status"
        ).fetchall()


def document_counts_by_user(doc_types: list[str]) -> list[sqlite3.Row]:
    """Per-user document totals straight from the documents table — unlike
    activity_log (which only has entries from the point logging went live),
    this always reflects every existing record, including ones uploaded
    before per-user ownership existed (bucketed as 'Unassigned (legacy)')."""
    marks = ",".join("?" * len(doc_types))
    with get_conn() as conn:
        return conn.execute(
            f"""SELECT d.created_by AS user_id,
                       COALESCE(u.username, 'Unassigned (legacy)') AS username,
                       COUNT(*) AS n
                  FROM documents d
                  LEFT JOIN users u ON u.id = d.created_by
                 WHERE d.doc_type IN ({marks})
                 GROUP BY d.created_by
                 ORDER BY n DESC""",
            doc_types,
        ).fetchall()


def document_counts_by_location(field_key: str) -> list[sqlite3.Row]:
    """Bill of Lading count grouped by an extracted location field
    (port_of_loading / port_of_discharge) — the admin dashboard's "by
    location" visualization. Only a Bill of Lading carries these fields."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT e.value AS location, COUNT(DISTINCT e.doc_id) AS n
                 FROM extractions e
                 JOIN documents d ON d.id = e.doc_id
                WHERE e.field_key = ? AND e.value IS NOT NULL AND e.value <> ''
                  AND d.doc_type = 'bill_of_lading'
                GROUP BY e.value
                ORDER BY n DESC
                LIMIT 20""",
            (field_key,),
        ).fetchall()


_NUM_RE = re.compile(r"\d{4,}")
_SBNUM_RE = re.compile(r"\d{6,8}")


def _first_number(text: str | None) -> str:
    m = _NUM_RE.search(text or "")
    return m.group(0) if m else ""


def _sb_numbers(text: str | None) -> set[str]:
    """Every 6-8 digit Shipping Bill number in a value (a BL may list several)."""
    return set(_SBNUM_RE.findall(text or ""))


def shipping_bill_ids_by_number(number: str, *, vessel_id: str | None = None) -> list[str]:
    """IDs of Shipping Bill documents whose sb_number is ``number`` (newest
    first). Scoped to one vessel when given — a short 6-8 digit SB number can
    coincidentally repeat across unrelated vessels, and without this an
    auto-link could attach a Shipping Bill from a completely different
    shipment just because the numbers happened to match.
    """
    if not number:
        return []
    clause = "WHERE d.doc_type = 'shipping_bill'"
    params: list = []
    if vessel_id:
        clause += " AND d.vessel_id = ?"
        params.append(vessel_id)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT d.id AS id, e.value AS value
                 FROM documents d
                 JOIN extractions e
                   ON e.doc_id = d.id AND e.field_key = 'sb_number'
                {clause}
                ORDER BY d.created_at DESC""",
            params,
        ).fetchall()
    return [r["id"] for r in rows if number in _sb_numbers(r["value"])]


def shipping_bill_id_by_number(number: str, *, vessel_id: str | None = None) -> str | None:
    ids = shipping_bill_ids_by_number(number, vessel_id=vessel_id)
    return ids[0] if ids else None


def bl_ids_referencing(number: str, *, vessel_id: str | None = None) -> list[str]:
    """Every BL (linked or not) whose shipping_bill_number_and_date lists
    ``number`` — a BL can reference several Shipping Bills, so this no
    longer stops at the first one it's linked to. Scoped to one vessel when
    given, same reasoning as shipping_bill_ids_by_number.
    """
    if not number:
        return []
    clause = "WHERE d.doc_type = 'bill_of_lading'"
    params: list = []
    if vessel_id:
        clause += " AND d.vessel_id = ?"
        params.append(vessel_id)
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT d.id AS id, e.value AS value
                 FROM documents d
                 JOIN extractions e
                   ON e.doc_id = d.id AND e.field_key = 'shipping_bill_number_and_date'
                {clause}""",
            params,
        ).fetchall()
    return [r["id"] for r in rows if number in _sb_numbers(r["value"])]


def update_document(doc_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = _now()
    if "warnings" in fields and not isinstance(fields["warnings"], str):
        fields["warnings"] = json.dumps(fields["warnings"])
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE documents SET {cols} WHERE id = ?",
            (*fields.values(), doc_id),
        )


# ------------------------------------------------------------------- extractions
def replace_extractions(doc_id: str, result: ExtractionResult) -> None:
    ts = _now()
    rows = [
        (
            _uid(), doc_id, f.key,
            _norm(f.value), f.confidence,          # ai_value, ai_confidence
            _norm(f.value), f.confidence,          # value, confidence (current)
            f.page,
            json.dumps(list(f.bbox)) if f.bbox else None,
            f.source, ts,
        )
        for f in result.fields
    ]
    with get_conn() as conn:
        conn.execute("DELETE FROM extractions WHERE doc_id = ?", (doc_id,))
        conn.executemany(
            """INSERT INTO extractions
                 (id, doc_id, field_key, ai_value, ai_confidence,
                  value, confidence, page, bbox, source, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )


def get_extractions(doc_id: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM extractions WHERE doc_id = ? ORDER BY rowid", (doc_id,)
        ).fetchall()


def apply_field_edits(
    doc_id: str,
    edits: dict[str, str | None],
    *,
    format_fingerprint: str | None,
) -> list[str]:
    """Update changed field values in place and log a correction for each.

    Returns the list of field keys that actually changed.
    """
    ts = _now()
    changed: list[str] = []
    with get_conn() as conn:
        existing = {
            r["field_key"]: r
            for r in conn.execute(
                "SELECT * FROM extractions WHERE doc_id = ?", (doc_id,)
            ).fetchall()
        }
        for key, raw in edits.items():
            new_value = _norm(raw)
            row = existing.get(key)
            old_value = _norm(row["value"]) if row else None
            if new_value == old_value:
                continue

            if row is None:
                conn.execute(
                    """INSERT INTO extractions
                         (id, doc_id, field_key, ai_value, ai_confidence,
                          value, confidence, source, updated_at)
                       VALUES (?, ?, ?, NULL, 0, ?, 1.0, 'user', ?)""",
                    (_uid(), doc_id, key, new_value, ts),
                )
                ai_value = None
                page, bbox = None, None
            else:
                conn.execute(
                    """UPDATE extractions
                          SET value = ?, confidence = 1.0, source = 'user',
                              updated_at = ?
                        WHERE doc_id = ? AND field_key = ?""",
                    (new_value, ts, doc_id, key),
                )
                ai_value = _norm(row["ai_value"])
                page, bbox = row["page"], row["bbox"]

            conn.execute(
                """INSERT INTO corrections
                     (id, doc_id, format_fingerprint, field_key, ai_value,
                      corrected_value, page, bbox, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_uid(), doc_id, format_fingerprint, key, ai_value,
                 new_value, page, bbox, ts),
            )
            changed.append(key)
    return changed


# ------------------------------------------------------------------- corrections
def list_corrections(
    *, limit: int = 200, field_key: str | None = None,
    format_fingerprint: str | None = None,
) -> list[sqlite3.Row]:
    clauses, params = [], []
    if field_key:
        clauses.append("field_key = ?")
        params.append(field_key)
    if format_fingerprint:
        clauses.append("format_fingerprint = ?")
        params.append(format_fingerprint)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM corrections {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()


def correction_counts() -> dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT field_key, COUNT(*) AS n FROM corrections GROUP BY field_key"
        ).fetchall()
    return {r["field_key"]: r["n"] for r in rows}


# ----------------------------------------------------------------- anchor rules
def upsert_anchor_rule(
    *, format_fingerprint: str, field_key: str, label_text: str | None,
    rel_dx: float | None, rel_dy: float | None,
    val_w: float | None, val_h: float | None, page: int | None,
    value_regex: str | None = None,
) -> None:
    ts = _now()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO anchor_rules
                 (id, format_fingerprint, field_key, label_text, rel_dx, rel_dy,
                  val_w, val_h, page, value_regex, hit_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
               ON CONFLICT(format_fingerprint, field_key) DO UPDATE SET
                 label_text = excluded.label_text,
                 rel_dx = excluded.rel_dx,
                 rel_dy = excluded.rel_dy,
                 val_w = excluded.val_w,
                 val_h = excluded.val_h,
                 page = excluded.page,
                 value_regex = excluded.value_regex,
                 hit_count = anchor_rules.hit_count + 1,
                 updated_at = excluded.updated_at""",
            (_uid(), format_fingerprint, field_key, label_text, rel_dx, rel_dy,
             val_w, val_h, page, value_regex, ts, ts),
        )


def get_anchor_rules(format_fingerprint: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM anchor_rules WHERE format_fingerprint = ?",
            (format_fingerprint,),
        ).fetchall()


def list_anchor_rules() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM anchor_rules ORDER BY format_fingerprint, field_key"
        ).fetchall()


# ------------------------------------------------------------------ masters
_COMPANY_COLUMNS = [
    "assigned_user_id",
    "company_code", "company_name", "city_name", "state_region", "country_name",
    "company_address", "zip_code", "phone", "email_id", "pan_no", "gstin_no",
    "company_group_name", "credit_period", "currency", "iec_no", "website", "remarks",
]

_COMPANY_SELECT = """
    SELECT c.*, u.username AS assigned_username
      FROM companies c
      LEFT JOIN users u ON u.id = c.assigned_user_id
"""


def _replace_company_branches(conn: sqlite3.Connection, company_id: str, branches: list[dict]) -> None:
    conn.execute("DELETE FROM company_branches WHERE company_id = ?", (company_id,))
    conn.executemany(
        """INSERT INTO company_branches
             (id, company_id, sort_order, branch_code, branch_name, branch_address,
              city, state, country, gstin_no, zipcode, telephone_no, email_id, remarks)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (_uid(), company_id, i, b["branch_code"], b["branch_name"], b["branch_address"],
             b.get("city"), b.get("state"), b.get("country"), b.get("gstin_no"),
             b["zipcode"], b["telephone_no"], b["email_id"], b.get("remarks"))
            for i, b in enumerate(branches)
        ],
    )


def create_company(
    fields: dict, branches: list[dict], *, updated_by: str | None, created_by: str | None = None
) -> str:
    cid = _uid()
    ts = _now()
    cols = ", ".join(_COMPANY_COLUMNS)
    qs = ", ".join("?" * len(_COMPANY_COLUMNS))
    with get_conn() as conn:
        conn.execute(
            f"""INSERT INTO companies (id, created_by, {cols}, updated_by, created_at, updated_at)
                VALUES (?, ?, {qs}, ?, ?, ?)""",
            (cid, created_by, *[fields.get(c) for c in _COMPANY_COLUMNS], updated_by, ts, ts),
        )
        _replace_company_branches(conn, cid, branches)
    return cid


def update_company(company_id: str, fields: dict, branches: list[dict], *, updated_by: str | None) -> None:
    ts = _now()
    sets = ", ".join(f"{c} = ?" for c in _COMPANY_COLUMNS)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE companies SET {sets}, updated_by = ?, updated_at = ? WHERE id = ?",
            (*[fields.get(c) for c in _COMPANY_COLUMNS], updated_by, ts, company_id),
        )
        _replace_company_branches(conn, company_id, branches)


def get_company(company_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(f"{_COMPANY_SELECT} WHERE c.id = ?", (company_id,)).fetchone()


def get_company_branches(company_id: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM company_branches WHERE company_id = ? ORDER BY sort_order",
            (company_id,),
        ).fetchall()


def list_companies(
    q: str | None = None, limit: int = 200, *, owner_id: str | None = None
) -> list[sqlite3.Row]:
    clauses, params = [], []
    if q:
        like = f"%{q}%"
        clauses.append("(c.company_code LIKE ? OR c.company_name LIKE ?)")
        params += [like, like]
    if owner_id:
        # access is now granted by explicit admin assignment, not by who
        # happened to create the record — an unassigned company stays
        # admin-only until an admin assigns it to someone.
        clauses.append("c.assigned_user_id = ?")
        params.append(owner_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with get_conn() as conn:
        return conn.execute(
            f"{_COMPANY_SELECT} {where} ORDER BY c.company_name LIMIT ?", params
        ).fetchall()


def delete_company(company_id: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))
        return cur.rowcount


_PORT_COLUMNS = [
    "company_id", "port_type", "port_code", "edi_port_code", "port_name", "country", "active", "sez",
]

_PORT_SELECT = """
    SELECT p.*, c.company_name AS company_name
      FROM ports p
      LEFT JOIN companies c ON c.id = p.company_id
"""


def _replace_port_berths(conn: sqlite3.Connection, port_id: str, berths: list[dict]) -> None:
    conn.execute("DELETE FROM port_berths WHERE port_id = ?", (port_id,))
    conn.executemany(
        "INSERT INTO port_berths (id, port_id, sort_order, berth, fpd_code) VALUES (?, ?, ?, ?, ?)",
        [
            (_uid(), port_id, i, b.get("berth"), b.get("fpd_code"))
            for i, b in enumerate(berths)
        ],
    )


def create_port(
    fields: dict, berths: list[dict], *, updated_by: str | None, created_by: str | None = None
) -> str:
    pid = _uid()
    ts = _now()
    cols = ", ".join(_PORT_COLUMNS)
    qs = ", ".join("?" * len(_PORT_COLUMNS))
    with get_conn() as conn:
        conn.execute(
            f"""INSERT INTO ports (id, created_by, {cols}, updated_by, created_at, updated_at)
                VALUES (?, ?, {qs}, ?, ?, ?)""",
            (pid, created_by, *[fields.get(c) for c in _PORT_COLUMNS], updated_by, ts, ts),
        )
        _replace_port_berths(conn, pid, berths)
    return pid


def update_port(port_id: str, fields: dict, berths: list[dict], *, updated_by: str | None) -> None:
    ts = _now()
    sets = ", ".join(f"{c} = ?" for c in _PORT_COLUMNS)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE ports SET {sets}, updated_by = ?, updated_at = ? WHERE id = ?",
            (*[fields.get(c) for c in _PORT_COLUMNS], updated_by, ts, port_id),
        )
        _replace_port_berths(conn, port_id, berths)


def get_port(port_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(f"{_PORT_SELECT} WHERE p.id = ?", (port_id,)).fetchone()


def get_port_berths(port_id: str) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM port_berths WHERE port_id = ? ORDER BY sort_order", (port_id,)
        ).fetchall()


def list_ports(
    q: str | None = None, limit: int = 200, *, owner_id: str | None = None, company_id: str | None = None,
) -> list[sqlite3.Row]:
    clauses, params = [], []
    if q:
        like = f"%{q}%"
        clauses.append("(p.port_code LIKE ? OR p.port_name LIKE ? OR p.edi_port_code LIKE ?)")
        params += [like, like, like]
    if owner_id:
        # a port's accessibility now follows its company's assignment, not
        # who created the port record.
        clauses.append("c.assigned_user_id = ?")
        params.append(owner_id)
    if company_id:
        clauses.append("p.company_id = ?")
        params.append(company_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with get_conn() as conn:
        return conn.execute(
            f"{_PORT_SELECT} {where} ORDER BY p.port_name LIMIT ?", params
        ).fetchall()


def delete_port(port_id: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM ports WHERE id = ?", (port_id,))
        return cur.rowcount


_VESSEL_COLUMNS = [
    "name", "imo_code", "call_sign", "build_year",
    "gross_tonnage", "net_tonnage", "ship_type",
    "company_id", "departure_port_id", "destination_port_id",
]

_VESSEL_SELECT = """
    SELECT v.*, c.company_name AS company_name,
           dp.port_name AS departure_port_name, xp.port_name AS destination_port_name
      FROM vessels v
      LEFT JOIN companies c ON c.id = v.company_id
      LEFT JOIN ports dp ON dp.id = v.departure_port_id
      LEFT JOIN ports xp ON xp.id = v.destination_port_id
"""


def create_vessel(
    fields: dict, *, updated_by: str | None, created_by: str | None = None
) -> str:
    vid = _uid()
    ts = _now()
    cols = ", ".join(_VESSEL_COLUMNS)
    qs = ", ".join("?" * len(_VESSEL_COLUMNS))
    with get_conn() as conn:
        conn.execute(
            f"""INSERT INTO vessels (id, created_by, {cols}, updated_by, created_at, updated_at)
                VALUES (?, ?, {qs}, ?, ?, ?)""",
            (vid, created_by, *[fields.get(c) for c in _VESSEL_COLUMNS], updated_by, ts, ts),
        )
    return vid


def update_vessel(vessel_id: str, fields: dict, *, updated_by: str | None) -> None:
    ts = _now()
    sets = ", ".join(f"{c} = ?" for c in _VESSEL_COLUMNS)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE vessels SET {sets}, updated_by = ?, updated_at = ? WHERE id = ?",
            (*[fields.get(c) for c in _VESSEL_COLUMNS], updated_by, ts, vessel_id),
        )


def get_vessel(vessel_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(f"{_VESSEL_SELECT} WHERE v.id = ?", (vessel_id,)).fetchone()


def list_vessels(
    q: str | None = None, limit: int = 200, *, owner_id: str | None = None, company_id: str | None = None,
) -> list[sqlite3.Row]:
    clauses, params = [], []
    if q:
        like = f"%{q}%"
        clauses.append("(v.name LIKE ? OR v.imo_code LIKE ? OR v.call_sign LIKE ?)")
        params += [like, like, like]
    if owner_id:
        # a vessel's accessibility now follows its company's assignment, not
        # who created the vessel record.
        clauses.append("c.assigned_user_id = ?")
        params.append(owner_id)
    if company_id:
        clauses.append("v.company_id = ?")
        params.append(company_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with get_conn() as conn:
        return conn.execute(
            f"{_VESSEL_SELECT} {where} ORDER BY v.name LIMIT ?", params
        ).fetchall()


def delete_vessel(vessel_id: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM vessels WHERE id = ?", (vessel_id,))
        return cur.rowcount


# -------------------------------------------------------------- export templates
def create_export_template(
    *, name: str, selected_fields: list[str], column_order: list[str] | None,
    output_type: str, format_fingerprint: str | None, owner: str | None,
) -> str:
    tid = _uid()
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO export_templates
                 (id, name, owner, selected_fields, column_order,
                  output_type, format_fingerprint, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (tid, name, owner, json.dumps(selected_fields),
             json.dumps(column_order) if column_order else None,
             output_type, format_fingerprint, _now()),
        )
    return tid


def list_export_templates() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM export_templates ORDER BY created_at DESC"
        ).fetchall()


def get_export_template(tid: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM export_templates WHERE id = ?", (tid,)
        ).fetchone()
