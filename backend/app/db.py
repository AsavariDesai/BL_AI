"""SQLite storage.

Kept deliberately thin (stdlib ``sqlite3``, SQL in one place) so the move to
Postgres later is a connection swap, not a rewrite. Ids are UUID strings and
timestamps are ISO-8601 text — both p
ortable.
"""
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from typing import Iterator
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id                  TEXT PRIMARY KEY,
  filename            TEXT NOT NULL,
  stored_path         TEXT NOT NULL,
  content_sha256      TEXT,
  page_count          INTEGER,
  has_scanned_pages   INTEGER NOT NULL DEFAULT 0,
  format_fingerprint  TEXT,
  engine              TEXT,
  status              TEXT NOT NULL DEFAULT 'uploaded',
  warnings            TEXT,                       -- JSON array
  doc_type            TEXT NOT NULL DEFAULT 'bill_of_lading',
  parent_id           TEXT REFERENCES documents(id) ON DELETE SET NULL,
  link_source         TEXT,                       -- 'auto' | 'manual'
  submitted           INTEGER NOT NULL DEFAULT 0, -- 0 = pending (Upload page), 1 = Submitted page
  submitted_at        TEXT,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extractions (
  id            TEXT PRIMARY KEY,
  doc_id        TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  field_key     TEXT NOT NULL,
  ai_value      TEXT,
  ai_confidence REAL NOT NULL DEFAULT 0,
  value         TEXT,
  confidence    REAL NOT NULL DEFAULT 0,
  page          INTEGER,
  bbox          TEXT,                             -- JSON [x0,y0,x1,y1]
  source        TEXT NOT NULL DEFAULT 'rules',    -- rules | kie | user
  updated_at    TEXT NOT NULL,
  UNIQUE (doc_id, field_key)
);

CREATE TABLE IF NOT EXISTS corrections (
  id                  TEXT PRIMARY KEY,
  doc_id              TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  format_fingerprint  TEXT,
  field_key           TEXT NOT NULL,
  ai_value            TEXT,
  corrected_value     TEXT,
  page                INTEGER,
  bbox                TEXT,
  ocr_context         TEXT,
  created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_templates (
  id                  TEXT PRIMARY KEY,
  name                TEXT NOT NULL,
  owner               TEXT,
  selected_fields     TEXT NOT NULL,              -- JSON array of field keys
  column_order        TEXT,                       -- JSON array of field keys
  output_type         TEXT NOT NULL DEFAULT 'xlsx',
  format_fingerprint  TEXT,
  created_at          TEXT NOT NULL
);

-- Populated by the learning loop (Step 5); created now so migrations stay simple.
CREATE TABLE IF NOT EXISTS anchor_rules (
  id                  TEXT PRIMARY KEY,
  format_fingerprint  TEXT NOT NULL,
  field_key           TEXT NOT NULL,
  label_text          TEXT,
  rel_dx              REAL,
  rel_dy              REAL,
  val_w               REAL,
  val_h               REAL,
  page                INTEGER,
  value_regex         TEXT,
  hit_count           INTEGER NOT NULL DEFAULT 0,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  UNIQUE (format_fingerprint, field_key)
);

CREATE TABLE IF NOT EXISTS users (
  id            TEXT PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'user',   -- 'admin' | 'user'
  -- Screen-level rights (Rights Management, admin-only): which of the two
  -- top-level categories a login can see at all. An admin ignores these and
  -- always sees both, same as it ignores per-record ownership elsewhere.
  can_export    INTEGER NOT NULL DEFAULT 1,
  can_import    INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token       TEXT PRIMARY KEY,
  user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  TEXT NOT NULL,
  expires_at  TEXT NOT NULL
);

-- BL-first linking: many Shipping Bills can be linked to one Bill of Lading
-- (and, symmetrically, one Shipping Bill could be linked to several BLs this
-- way too). Separate from documents.parent_id, which drives the older
-- "Shipping Bill is the master, many BLs reference it" hierarchy — that
-- relationship is untouched; this table is the one the BL-first "Link
-- Shipping Bill(s)" UI reads and writes, and supports 50+ SBs per BL.
CREATE TABLE IF NOT EXISTS bl_sb_links (
  id           TEXT PRIMARY KEY,
  bl_id        TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  sb_id        TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  link_source  TEXT NOT NULL DEFAULT 'manual',   -- 'auto' | 'manual'
  created_at   TEXT NOT NULL,
  UNIQUE (bl_id, sb_id)
);

-- ------------------------------------------------------------- master data
-- Vessel, Company and Port masters (Master BL / House BL phase). A vessel
-- names the company operating it and its departure/destination ports by id,
-- so the upcoming Master BL OCR tool can pre-fill and validate against
-- these instead of free-typed text.
CREATE TABLE IF NOT EXISTS companies (
  id                  TEXT PRIMARY KEY,
  created_by          TEXT,
  assigned_user_id    TEXT REFERENCES users(id) ON DELETE SET NULL,
  company_code        TEXT NOT NULL UNIQUE,
  company_name        TEXT NOT NULL,
  city_name           TEXT,
  state_region        TEXT,
  country_name        TEXT NOT NULL,
  company_address     TEXT,
  zip_code            TEXT,
  phone               TEXT,
  email_id            TEXT,
  pan_no              TEXT NOT NULL,
  gstin_no            TEXT NOT NULL,
  company_group_name  TEXT,
  credit_period       TEXT,
  currency            TEXT,
  iec_no              TEXT,
  website             TEXT,
  remarks             TEXT,
  updated_by          TEXT,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_branches (
  id              TEXT PRIMARY KEY,
  company_id      TEXT NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  sort_order      INTEGER NOT NULL DEFAULT 0,
  branch_code     TEXT NOT NULL,
  branch_name     TEXT NOT NULL,
  branch_address  TEXT NOT NULL,
  city            TEXT,
  state           TEXT,
  country         TEXT,
  gstin_no        TEXT,
  zipcode         TEXT NOT NULL,
  telephone_no    TEXT NOT NULL,
  email_id        TEXT NOT NULL,
  remarks         TEXT
);

CREATE TABLE IF NOT EXISTS ports (
  id             TEXT PRIMARY KEY,
  created_by     TEXT,
  company_id     TEXT REFERENCES companies(id) ON DELETE SET NULL,
  port_type      TEXT NOT NULL DEFAULT 'SEA PORT',
  port_code      TEXT NOT NULL UNIQUE,
  edi_port_code  TEXT,
  port_name      TEXT NOT NULL,
  country        TEXT NOT NULL,
  active         INTEGER NOT NULL DEFAULT 1,
  sez            INTEGER NOT NULL DEFAULT 0,
  updated_by     TEXT,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS port_berths (
  id          TEXT PRIMARY KEY,
  port_id     TEXT NOT NULL REFERENCES ports(id) ON DELETE CASCADE,
  sort_order  INTEGER NOT NULL DEFAULT 0,
  berth       TEXT,
  fpd_code    TEXT
);

CREATE TABLE IF NOT EXISTS vessels (
  id                   TEXT PRIMARY KEY,
  created_by           TEXT,
  name                 TEXT NOT NULL,
  imo_code             TEXT NOT NULL UNIQUE,
  call_sign            TEXT NOT NULL,
  build_year           TEXT,
  gross_tonnage        TEXT,
  net_tonnage          TEXT,
  ship_type            TEXT,
  company_id           TEXT REFERENCES companies(id) ON DELETE SET NULL,
  departure_port_id    TEXT REFERENCES ports(id) ON DELETE SET NULL,
  destination_port_id  TEXT REFERENCES ports(id) ON DELETE SET NULL,
  updated_by           TEXT,
  created_at           TEXT NOT NULL,
  updated_at           TEXT NOT NULL
);

-- Master BL / House BL hierarchy (Import category). Mirrors bl_sb_links —
-- one Master BL can have many linked House BLs. No field catalog or
-- extraction logic exists for these two doc_types yet; until real samples
-- are available to design that against, they're stored and reviewed as
-- plain uploaded PDFs through the same documents table (doc_type =
-- 'master_bl' / 'house_bl'), linked here the same BL-first way SBs are.
CREATE TABLE IF NOT EXISTS master_house_bl_links (
  id            TEXT PRIMARY KEY,
  master_bl_id  TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  house_bl_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  link_source   TEXT NOT NULL DEFAULT 'manual',
  created_at    TEXT NOT NULL,
  UNIQUE (master_bl_id, house_bl_id)
);

-- Who did what, when. ``category`` ('export' | 'import' | NULL for an
-- account-level action like login that isn't tied to either side) is how
-- the Export and Import analytics dashboards stay completely separate even
-- though they share one activity_log table and one login system — see
-- api._category_of. The admin's dashboard is just this table with no
-- user_id filter; a regular user's is the same query filtered to their own.
CREATE TABLE IF NOT EXISTS activity_log (
  id          TEXT PRIMARY KEY,
  user_id     TEXT REFERENCES users(id) ON DELETE SET NULL,
  username    TEXT NOT NULL,
  action      TEXT NOT NULL,      -- 'login' | 'upload' | 'submit' | 'export' | ...
  doc_type    TEXT,
  category    TEXT,               -- 'export' | 'import' | NULL
  detail      TEXT,
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_extractions_doc ON extractions(doc_id);
CREATE INDEX IF NOT EXISTS idx_corrections_lookup
  ON corrections(format_fingerprint, field_key);
CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_parent ON documents(parent_id);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_bl_sb_links_bl ON bl_sb_links(bl_id);
CREATE INDEX IF NOT EXISTS idx_bl_sb_links_sb ON bl_sb_links(sb_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_company_branches_company ON company_branches(company_id);
CREATE INDEX IF NOT EXISTS idx_port_berths_port ON port_berths(port_id);
CREATE INDEX IF NOT EXISTS idx_vessels_company ON vessels(company_id);
CREATE INDEX IF NOT EXISTS idx_master_house_links_master ON master_house_bl_links(master_bl_id);
CREATE INDEX IF NOT EXISTS idx_master_house_links_house ON master_house_bl_links(house_bl_id);
CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at DESC);
"""

# Columns added after the first release — applied to pre-existing databases.
_MIGRATIONS = [
    ("documents", "doc_type", "TEXT NOT NULL DEFAULT 'bill_of_lading'"),
    ("documents", "parent_id", "TEXT"),
    ("documents", "link_source", "TEXT"),
    ("documents", "submitted", "INTEGER NOT NULL DEFAULT 0"),
    ("documents", "submitted_at", "TEXT"),
    ("documents", "created_by", "TEXT"),
    ("users", "role", "TEXT NOT NULL DEFAULT 'user'"),
    # companies/ports/vessels existed (without `created_by`) on some local
    # dev databases from before per-user ownership was added — same
    # CREATE-TABLE-IF-NOT-EXISTS-is-a-no-op situation as activity_log below.
    ("companies", "created_by", "TEXT"),
    ("ports", "created_by", "TEXT"),
    ("vessels", "created_by", "TEXT"),
    # Port now registers under a Company (Company -> Vessel/Port workflow).
    ("ports", "company_id", "TEXT"),
    # activity_log existed (without `category`) in an earlier build of the
    # Analytics feature on some local dev databases — CREATE TABLE IF NOT
    # EXISTS is a no-op there, so this column only ever actually gets added
    # through this migration, never through the schema script itself.
    ("activity_log", "category", "TEXT"),
    # Company Master access model: a company is now assigned to exactly one
    # user login (besides the admin, who always sees everything) rather than
    # being visible to whoever happened to create it.
    ("companies", "assigned_user_id", "TEXT"),
    # Screen-level rights — default 1 (both) so every existing login keeps
    # seeing exactly what it sees today; only deliberately set is rights
    # narrower for someone.
    ("users", "can_export", "INTEGER NOT NULL DEFAULT 1"),
    ("users", "can_import", "INTEGER NOT NULL DEFAULT 1"),
    # Import workflow: a Master BL (and, transitively, its linked House BLs)
    # belongs to one Vessel — the Vessel Workspace is what scopes uploads
    # and the records list, the same way Export never needed this.
    ("documents", "vessel_id", "TEXT"),
    # Export workflow: Company Master is now shared infrastructure — a Bill
    # of Lading / Shipping Bill belongs directly to one Company (Export has
    # no Vessel tier), the same way Import documents belong to a Vessel.
    ("documents", "company_id", "TEXT"),
]

# Indexes on a column that's added via _MIGRATIONS (rather than always being
# in the CREATE TABLE text) can't live in SCHEMA — on a database where the
# table already existed pre-migration, SCHEMA's CREATE TABLE IF NOT EXISTS
# is a no-op and the index would run (and fail) before the ALTER TABLE
# below ever adds the column. Created here, after migrations, instead.
_POST_MIGRATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_ports_company ON ports(company_id)",
    "CREATE INDEX IF NOT EXISTS idx_companies_assigned_user ON companies(assigned_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_documents_vessel ON documents(vessel_id)",
    "CREATE INDEX IF NOT EXISTS idx_documents_company ON documents(company_id)",
]


def _ensure_bootstrap_admin(conn: sqlite3.Connection) -> None:
    """Every install needs at least one admin to manage users/companies —
    but the `role` column defaults new AND migrated rows to 'user', so a
    database with users and no admin yet (e.g. one migrated from before
    roles existed) has no way to create one through the app itself (/users
    is admin-only). Promote the earliest-created account automatically so
    that deadlock can't happen."""
    has_admin = conn.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    if has_admin:
        return
    first = conn.execute("SELECT id FROM users ORDER BY created_at LIMIT 1").fetchone()
    if first:
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (first["id"],))


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for table, column, decl in _MIGRATIONS:
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        for stmt in _POST_MIGRATION_INDEXES:
            conn.execute(stmt)
        _ensure_bootstrap_admin(conn)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    # WAL's own docs recommend NORMAL over the default FULL: FULL fsyncs on
    # every single commit (fine for occasional writes, a real bottleneck
    # once a bulk batch is doing hundreds of small transactions back to
    # back — a 100-document bulk upload measured ~650ms/doc before this,
    # nearly all of it fsync wait, not actual work). NORMAL still fsyncs at
    # each WAL checkpoint, so a committed transaction is never lost to an
    # application or OS crash — only an OS-level crash or power loss in the
    # narrow window before the next checkpoint could lose the most recent
    # commits, and even then the database itself can't be corrupted.
    conn.execute("PRAGMA synchronous = NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
