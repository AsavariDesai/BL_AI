"""FastAPI surface for the BL reader.

Run:  uvicorn app.api:app --reload --port 8000   (from backend/)
Docs: http://localhost:8000/docs
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from . import auth
from . import config
from . import repository as repo
from . import service
from .config import settings
from .db import init_db
from .field_catalog import DEFAULT_DOC_TYPE, DOC_TYPE_LABELS, DOC_TYPES, catalog, groups
from .schemas import (
    ActivityOut,
    ActivitySummaryRow,
    BatchExportIn,
    BulkDeleteIn,
    BulkUploadOut,
    CatalogField,
    CompanyIn,
    CompanyOut,
    CorrectionOut,
    DeleteOut,
    DocumentDetail,
    DocumentOut,
    ExportTemplateIn,
    ExportTemplateOut,
    ExtractIn,
    FieldsUpdateIn,
    HierarchyOut,
    LinkIn,
    LoginIn,
    PortIn,
    PortOut,
    RecordOut,
    RecordsExportIn,
    RecordStats,
    ShippingBillDetail,
    ShippingBillOut,
    SubmitIn,
    UserAdminOut,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
    VesselIn,
    VesselOut,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    service.recover_stale_jobs()  # re-open extractions a previous run left half-done
    yield


app = FastAPI(title="BL-AI", version="0.2.0", lifespan=lifespan)

# Every path whose first segment is in here requires a valid session — every
# API prefix this app defines except /health and /auth itself. Add new ones
# here when a new top-level route prefix is added; anything not listed here
# (the SPA's own static HTML/JS/CSS, once SERVE_FRONTEND mounts it) is left
# public since it carries no data — only these JSON endpoints do.
_PROTECTED_PREFIXES = {
    "doc-types", "fields", "documents", "ingest", "uploads", "records",
    "hierarchy", "shipping-bills", "corrections", "anchor-rules",
    "export-templates", "exports", "vessels", "companies", "ports",
    "users", "master-bls", "house-bls", "activity", "analytics",
}


@app.middleware("http")
async def require_login(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    segment = request.url.path.strip("/").split("/", 1)[0]
    if segment not in _PROTECTED_PREFIXES:
        return await call_next(request)
    user = auth.user_for_session(request.cookies.get(auth.SESSION_COOKIE))
    if user is None:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    request.state.user = user
    return await call_next(request)


# Added *after* the auth middleware so it ends up outermost (Starlette wraps
# in reverse registration order) — CORS preflight (OPTIONS) must be answered
# before the auth check ever runs, or cross-origin dev (`npm run dev` on a
# different port than uvicorn) breaks.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:3000", "http://127.0.0.1:3000",
        *config.ALLOWED_ORIGINS,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --------------------------------------------------------------- role scope
# Every list view in the app is scoped by these two helpers: an admin sees
# everything, a regular user only their own records. Detail/action routes
# on a single document are intentionally NOT ownership-checked here (that
# would mean auditing every document route); only list views and the
# masters' own update/delete are scoped. See the User Management section
# below for why.
def _owner_scope(request: Request) -> str | None:
    """None (admin, sees all) or the current user's id (regular user, sees
    only what they created)."""
    return None if request.state.user["role"] == "admin" else request.state.user["id"]


def _require_admin(request: Request) -> None:
    if request.state.user["role"] != "admin":
        raise HTTPException(403, "Admin access required.")


def _require_category_rights(request: Request, category: str | None) -> None:
    """Screen-level access (Rights Management): an admin always has both;
    a regular user needs can_export / can_import set for the category they're
    touching. ``category`` is None for something not yet resolvable to a
    side (e.g. auto-detect before extraction runs) — nothing to check yet."""
    if category is None:
        return
    user = request.state.user
    if user["role"] == "admin":
        return
    key = "can_export" if category == "export" else "can_import"
    if not user[key]:
        raise HTTPException(403, f"You don't have {category} access.")


def _require_any_category_rights(request: Request) -> None:
    """Company Master is shared infrastructure, reachable from either the
    Export or the Import Company Workspace — unlike every other master
    screen, it isn't gated to one category, only to having *some* screen
    access at all (an admin, or a user with can_export or can_import)."""
    user = request.state.user
    if user["role"] == "admin":
        return
    if not user["can_export"] and not user["can_import"]:
        raise HTTPException(403, "You don't have access to Company Master.")


def _assert_owns_or_admin(request: Request, created_by: str | None) -> None:
    """A master record with no owner (created before this feature existed,
    or seeded by the CLI) stays editable by any logged-in user rather than
    being locked out of the app."""
    if created_by and request.state.user["role"] != "admin" and created_by != request.state.user["id"]:
        raise HTTPException(403, "You don't have access to this record.")


# One doc_type set per top-level nav category — Export is the original BL +
# Shipping Bill tool, Import is the Master BL / House BL tool. Both the
# unified record list (/records/overview) and the activity/analytics
# endpoints use this so Export's and Import's data never mix, even though
# they share one documents table, one activity_log table, and one login.
_CATEGORY_DOC_TYPES = {
    "export": ["bill_of_lading", "shipping_bill"],
    "import": ["master_bl", "house_bl"],
}


def _category_of(doc_type: str | None) -> str | None:
    for cat, types in _CATEGORY_DOC_TYPES.items():
        if doc_type in types:
            return cat
    return None


def _category_for_doc_ids(doc_ids: list[str]) -> str | None:
    """Every doc_id in one submit/export call is always the same category in
    practice (each screen only ever selects within its own category) — look
    at the first one."""
    if not doc_ids:
        return None
    row = repo.get_document(doc_ids[0])
    return _category_of(row["doc_type"]) if row else None


def _log(
    request: Request, action: str, *,
    doc_type: str | None = None, category: str | None = None, detail: str | None = None,
) -> None:
    user = request.state.user
    repo.log_activity(
        user_id=user["id"], username=user["username"], action=action,
        doc_type=doc_type, category=category or _category_of(doc_type), detail=detail,
    )


# ------------------------------------------------------------------- auth
@app.post("/auth/login", response_model=UserOut)
def login(body: LoginIn, response: Response) -> UserOut:
    row = repo.get_user_by_username(body.username)
    if row is not None:
        remaining = auth.lockout_remaining(row)
        if remaining > 0:
            raise HTTPException(
                423,
                f"Too many failed login attempts. Try again in "
                f"{max(1, round(remaining / 60))} minute(s).",
            )
    if row is None or not auth.verify_password(body.password, row["password_hash"]):
        # Same generic message either way — this never reveals whether the
        # username itself exists, only (via the 423 above) that it's locked.
        if row is not None:
            auth.register_failed_login(row["id"])
        raise HTTPException(401, "Invalid username or password")
    repo.clear_failed_logins(row["id"])
    token = auth.create_session(row["id"])
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        httponly=True, samesite="lax", secure=settings.cookie_secure,
        max_age=60 * 60 * 24 * 14, path="/",
    )
    repo.log_activity(user_id=row["id"], username=row["username"], action="login")
    return UserOut(
        id=row["id"], username=row["username"], role=row["role"],
        can_export=bool(row["can_export"]), can_import=bool(row["can_import"]),
    )


@app.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    auth.logout(request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok"}


@app.get("/auth/me", response_model=UserOut)
def me(request: Request) -> UserOut:
    user = auth.user_for_session(request.cookies.get(auth.SESSION_COOKIE))
    if user is None:
        raise HTTPException(401, "Not authenticated")
    return UserOut(
        id=user["id"], username=user["username"], role=user["role"],
        can_export=bool(user["can_export"]), can_import=bool(user["can_import"]),
    )


def _user_admin_out(row: sqlite3.Row) -> UserAdminOut:
    return UserAdminOut(
        id=row["id"], username=row["username"], role=row["role"],
        can_export=bool(row["can_export"]), can_import=bool(row["can_import"]),
        created_at=row["created_at"],
    )


# ------------------------------------------------------------- user management
@app.get("/users", response_model=list[UserAdminOut])
def list_users(request: Request) -> list[UserAdminOut]:
    _require_admin(request)
    return [_user_admin_out(r) for r in repo.list_users()]


@app.post("/users", response_model=UserAdminOut, status_code=201)
def create_user(body: UserCreateIn, request: Request) -> UserAdminOut:
    _require_admin(request)
    if body.role not in ("admin", "user"):
        raise HTTPException(400, "role must be 'admin' or 'user'")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if repo.get_user_by_username(body.username):
        raise HTTPException(400, f"Username {body.username!r} already exists.")
    uid = repo.create_user(
        username=body.username, password_hash=auth.hash_password(body.password), role=body.role,
        can_export=body.can_export, can_import=body.can_import,
    )
    return _user_admin_out(repo.get_user(uid))


@app.put("/users/{user_id}", response_model=UserAdminOut)
def update_user(user_id: str, body: UserUpdateIn, request: Request) -> UserAdminOut:
    _require_admin(request)
    row = repo.get_user(user_id)
    if row is None:
        raise HTTPException(404, "user not found")
    if body.role is not None:
        if body.role not in ("admin", "user"):
            raise HTTPException(400, "role must be 'admin' or 'user'")
        repo.update_user_role(user_id, body.role)
    if body.can_export is not None or body.can_import is not None:
        row = repo.get_user(user_id)
        repo.update_user_rights(
            user_id,
            can_export=body.can_export if body.can_export is not None else bool(row["can_export"]),
            can_import=body.can_import if body.can_import is not None else bool(row["can_import"]),
        )
    if body.password is not None:
        if len(body.password) < 8:
            raise HTTPException(400, "Password must be at least 8 characters.")
        repo.set_user_password(user_id, auth.hash_password(body.password))
        repo.delete_sessions_for_user(user_id)  # force re-login everywhere
        repo.clear_failed_logins(user_id)  # a password reset also lifts any lockout
    return _user_admin_out(repo.get_user(user_id))


@app.delete("/users/{user_id}")
def delete_user(user_id: str, request: Request) -> dict:
    _require_admin(request)
    if user_id == request.state.user["id"]:
        raise HTTPException(400, "You can't delete your own account.")
    if not repo.delete_user(user_id):
        raise HTTPException(404, "user not found")
    return {"status": "ok"}


@app.get("/doc-types", response_model=list[dict])
def doc_types() -> list[dict]:
    return [{"key": k, "label": DOC_TYPE_LABELS[k]} for k in DOC_TYPES]


@app.get("/fields", response_model=list[CatalogField])
def canonical_fields(doc_type: str = DEFAULT_DOC_TYPE) -> list[CatalogField]:
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, f"unknown doc_type: {doc_type}")
    return [CatalogField(**f) for f in catalog(doc_type)]


@app.get("/fields/groups", response_model=list[str])
def field_groups(doc_type: str = DEFAULT_DOC_TYPE) -> list[str]:
    if doc_type not in DOC_TYPES:
        raise HTTPException(400, f"unknown doc_type: {doc_type}")
    return groups(doc_type)


# ------------------------------------------------------------------- documents
def _form_doc_type(value: str | None) -> str | None:
    """'', 'auto' or missing -> None (auto-detect)."""
    return value if value not in (None, "", "auto") else None


@app.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile,
    doc_type: str | None = Form(None),
    parent_id: str | None = Form(None),
    vessel_id: str | None = Form(None),
    company_id: str | None = Form(None),
) -> DocumentOut:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf uploads are supported.")
    _require_category_rights(request, _category_of(_form_doc_type(doc_type) or "bill_of_lading"))
    if vessel_id:
        vessel = repo.get_vessel(vessel_id)
        if vessel is None:
            raise HTTPException(400, "Vessel not found.")
        company = repo.get_company(vessel["company_id"]) if vessel["company_id"] else None
        if company is None:
            raise HTTPException(400, "This vessel's company no longer exists.")
        _assert_company_access(request, company)
    if company_id:
        company = repo.get_company(company_id)
        if company is None:
            raise HTTPException(400, "Company not found.")
        _assert_company_access(request, company)
    content = await file.read()
    try:
        doc_id = service.ingest_upload(
            file.filename, content,
            doc_type=_form_doc_type(doc_type), parent_id=parent_id or None,
            created_by=request.state.user["id"], vessel_id=vessel_id or None,
            company_id=company_id or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    row = repo.get_document(doc_id)
    _log(request, "upload", doc_type=row["doc_type"], detail=file.filename)
    return DocumentOut(**service.document_row_to_out(row))


@app.post("/ingest", response_model=DocumentDetail, status_code=201)
async def ingest(
    request: Request,
    file: UploadFile,
    doc_type: str | None = Form(None),
    parent_id: str | None = Form(None),
    background: bool = Form(False),
    company_id: str | None = Form(None),
    vessel_id: str | None = Form(None),
) -> DocumentDetail:
    """Upload → auto-detect type → extract → auto-link.

    ``background=true`` returns as soon as the file is stored (status
    ``queued``) and runs OCR on a worker thread, so a slow scanned PDF never
    blocks — or times out — the HTTP request. Poll ``GET /documents/{id}``.
    ``company_id`` scopes the upload to one Export Company Workspace, the
    same way Import's ``vessel_id`` scopes a Master BL upload — Export now
    has that same Vessel Workspace too, so ``vessel_id`` works here as well
    (company_id is then optional; it's carried over from the vessel).
    """
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf uploads are supported.")
    # /ingest (auto-detect + extract) only ever produces Export doc_types —
    # Master BL / House BL always go through POST /documents with an
    # explicit doc_type instead — so this is unconditionally Export rights.
    _require_category_rights(request, "export")
    if vessel_id:
        vessel = repo.get_vessel(vessel_id)
        if vessel is None:
            raise HTTPException(400, "Vessel not found.")
        company = repo.get_company(vessel["company_id"]) if vessel["company_id"] else None
        if company is None:
            raise HTTPException(400, "This vessel's company no longer exists.")
        _assert_company_access(request, company)
    if company_id:
        company = repo.get_company(company_id)
        if company is None:
            raise HTTPException(400, "Company not found.")
        _assert_company_access(request, company)
    content = await file.read()
    run = service.process_upload_async if background else service.process_upload
    try:
        detail = run(
            file.filename, content,
            doc_type=_form_doc_type(doc_type), parent_id=parent_id or None,
            created_by=request.state.user["id"], company_id=company_id or None,
            vessel_id=vessel_id or None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _log(request, "upload", doc_type=detail.doc_type, detail=file.filename)
    return detail


def _record_filters(q, status, doc_type, date_from, date_to, limit) -> dict:
    return {
        "q": q, "status": status, "doc_type": doc_type,
        "date_from": date_from, "date_to": date_to, "limit": limit,
    }


@app.get("/uploads", response_model=list[RecordOut])
def list_uploads(
    request: Request,
    q: str | None = None, status: str | None = None, doc_type: str | None = None,
    date_from: str | None = None, date_to: str | None = None, limit: int = 200,
) -> list[RecordOut]:
    """Pending records — everything not yet submitted (the Upload Data page)."""
    return service.list_records(
        submitted=False, owner_id=_owner_scope(request),
        **_record_filters(q, status, doc_type, date_from, date_to, limit),
    )


@app.get("/uploads/stats", response_model=RecordStats)
def upload_stats(request: Request) -> RecordStats:
    return service.record_stats(submitted=False, owner_id=_owner_scope(request))


@app.get("/records", response_model=list[RecordOut])
def list_records(
    request: Request,
    q: str | None = None, status: str | None = None, doc_type: str | None = None,
    date_from: str | None = None, date_to: str | None = None, limit: int = 200,
) -> list[RecordOut]:
    """Submitted records only (the Submitted Data page)."""
    return service.list_records(
        submitted=True, owner_id=_owner_scope(request),
        **_record_filters(q, status, doc_type, date_from, date_to, limit),
    )


@app.get("/records/stats", response_model=RecordStats)
def record_stats(request: Request) -> RecordStats:
    return service.record_stats(submitted=True, owner_id=_owner_scope(request))


@app.get("/records/overview", response_model=list[RecordOut])
def list_records_overview(
    request: Request,
    category: str = "export",
    q: str | None = None, status: str | None = None, doc_type: str | None = None,
    date_from: str | None = None, date_to: str | None = None, limit: int = 200,
    submitted: bool | None = None, vessel_id: str | None = None, company_id: str | None = None,
) -> list[RecordOut]:
    """Every record in one list, pending and submitted together — the single
    Export screen and single Import screen both read this (``category``
    picks which side's doc_types to include), filtering by ``submitted``
    only when the caller actually wants just one stage, not as a forced
    page split. ``vessel_id`` scopes Import's list to one Vessel Workspace;
    ``company_id`` scopes Export's list to one Company Workspace."""
    if category not in _CATEGORY_DOC_TYPES:
        raise HTTPException(400, f"unknown category: {category}")
    _require_category_rights(request, category)
    if vessel_id:
        vessel = repo.get_vessel(vessel_id)
        if vessel is not None and vessel["company_id"]:
            company = repo.get_company(vessel["company_id"])
            if company is not None:
                _assert_company_access(request, company)
    if company_id:
        company = repo.get_company(company_id)
        if company is not None:
            _assert_company_access(request, company)
    types = doc_type if doc_type else _CATEGORY_DOC_TYPES[category]
    return service.list_records(
        submitted=submitted, owner_id=_owner_scope(request), vessel_id=vessel_id,
        company_id=company_id,
        **_record_filters(q, status, types, date_from, date_to, limit),
    )


@app.post("/records/submit", response_model=dict)
def submit_records(body: SubmitIn, request: Request) -> dict:
    category = _category_for_doc_ids(body.doc_ids)
    _require_category_rights(request, category)
    n = service.submit_records(body.doc_ids)
    _log(request, "submit", category=category, detail=f"{n} record(s)")
    return {"submitted": n}


@app.post("/records/export")
def export_records(body: RecordsExportIn, request: Request) -> Response:
    category = _category_for_doc_ids(body.doc_ids)
    _require_category_rights(request, category)
    try:
        if body.combine:
            if body.fmt != "xlsx":
                raise ValueError("combine is only available for xlsx exports")
            resp = _file_response(service.export_records_combined(body.doc_ids))
        else:
            resp = _file_response(service.export_records(body.doc_ids, body.fmt))
    except KeyError:
        raise HTTPException(404, "one or more records not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _log(request, "export", category=category, detail=f"{len(body.doc_ids)} record(s), {body.fmt}")
    return resp


@app.post("/records/export-split")
def export_records_split(body: RecordsExportIn, request: Request) -> Response:
    """Three files in one .zip, in whichever format was asked for: every
    selected Bill of Lading's own details, every one of their linked
    Shipping Bills' details, and a Summary of each BL's SB reconciliation
    and cargo totals — the alternative to merging BL and SB rows into one
    file's two sheets/sections (``/records/export`` with ``combine``).
    Always a .zip, whether one BL or many were selected."""
    _require_category_rights(request, "export")
    try:
        resp = _file_response(service.export_records_split(body.doc_ids, body.fmt))
    except KeyError:
        raise HTTPException(404, "one or more records not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _log(request, "export", category="export", detail=f"{len(body.doc_ids)} record(s) split, {body.fmt}")
    return resp


@app.post("/records/export-master-bl-split")
def export_master_bl_split(body: RecordsExportIn, request: Request) -> Response:
    """Import's mirror of /records/export-split: three files in one .zip —
    every selected Master BL's own metadata, every one of their linked
    House BLs, and a per-vessel Summary. xlsx only (no field catalog yet to
    lay out a PDF page around — see field_catalog.py)."""
    _require_category_rights(request, "import")
    try:
        resp = _file_response(service.export_master_bl_split(body.doc_ids))
    except KeyError:
        raise HTTPException(404, "one or more records not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _log(request, "export", category="import", detail=f"{len(body.doc_ids)} record(s) split, xlsx")
    return resp


@app.get("/documents", response_model=list[DocumentOut])
def list_documents(
    request: Request,
    limit: int = 50,
    doc_type: str | None = None,
    parent_id: str | None = None,
    unlinked: bool = False,
) -> list[DocumentOut]:
    kwargs: dict = {"doc_type": doc_type, "unlinked": unlinked, "owner_id": _owner_scope(request)}
    if parent_id is not None:
        kwargs["parent_id"] = parent_id
    return [
        DocumentOut(**service.document_row_to_out(r))
        for r in repo.list_documents(limit, **kwargs)
    ]


@app.get("/documents/{doc_id}", response_model=DocumentDetail)
def get_document(doc_id: str) -> DocumentDetail:
    try:
        return service.get_document_detail(doc_id)
    except KeyError:
        raise HTTPException(404, "document not found")


@app.get("/documents/{doc_id}/file")
def get_document_file(doc_id: str) -> FileResponse:
    row = repo.get_document(doc_id)
    if row is None:
        raise HTTPException(404, "document not found")
    return FileResponse(row["stored_path"], media_type="application/pdf",
                        filename=row["filename"])


@app.post("/documents/{doc_id}/extract", response_model=DocumentDetail)
def extract_document(
    doc_id: str, background: bool = False, body: ExtractIn | None = None
) -> DocumentDetail:
    engine = body.engine if body else None
    try:
        if background:
            if repo.get_document(doc_id) is None:
                raise KeyError(doc_id)
            service.schedule_extraction(doc_id, engine)
            return service.get_document_detail(doc_id)
        return service.run_extraction(doc_id, engine)
    except KeyError:
        raise HTTPException(404, "document not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/documents/{doc_id}/fields", response_model=DocumentDetail)
def update_fields(doc_id: str, body: FieldsUpdateIn) -> DocumentDetail:
    edits = {e.key: e.value for e in body.fields}
    try:
        return service.save_field_edits(doc_id, edits)
    except KeyError:
        raise HTTPException(404, "document not found")


@app.post("/documents/{bl_id}/link-shipping-bill", response_model=DocumentDetail,
          status_code=201)
async def link_shipping_bill(
    bl_id: str, request: Request, response: Response, files: list[UploadFile], background: bool = Form(True)
) -> DocumentDetail:
    """BL-first flow: upload one or more Shipping Bills (50+ supported in one
    call) and link them all straight to this BL — each adds to the BL's
    linked set, none replace what's already there.

    Each file is processed independently: one unreadable PDF in a batch of
    50 doesn't take the other 49 down with it. Any that fail are listed in
    the X-Failed-Files response header (comma-separated filenames) rather
    than changing the response body shape.
    """
    _require_category_rights(request, "export")
    bl = repo.get_document(bl_id)
    if bl is not None and bl["company_id"]:
        company = repo.get_company(bl["company_id"])
        if company is not None:
            _assert_company_access(request, company)
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, f"Only .pdf uploads are supported ({f.filename}).")

    detail: DocumentDetail | None = None
    failed: list[str] = []
    for f in files:
        content = await f.read()
        try:
            detail = service.link_shipping_bill_to_bl(
                bl_id, f.filename, content, background=background
            )
        except KeyError:
            raise HTTPException(404, "bill of lading not found")
        except ValueError:
            failed.append(f.filename)

    if detail is None:
        try:
            detail = service.get_document_detail(bl_id)
        except KeyError:
            raise HTTPException(404, "bill of lading not found")
    if failed:
        response.headers["X-Failed-Files"] = ",".join(failed)
    return detail


@app.post("/documents/{bl_id}/link-existing-sb", response_model=DocumentDetail)
def link_existing_sbs(bl_id: str, body: LinkIn, request: Request) -> DocumentDetail:
    """Link one or more already-uploaded Shipping Bills to this BL."""
    _require_category_rights(request, "export")
    bl = repo.get_document(bl_id)
    if bl is not None and bl["company_id"]:
        company = repo.get_company(bl["company_id"])
        if company is not None:
            _assert_company_access(request, company)
    try:
        detail: DocumentDetail | None = None
        for sb_id in body.doc_ids:
            detail = service.link_existing_sb_to_bl(bl_id, sb_id)
        return detail if detail is not None else service.get_document_detail(bl_id)
    except KeyError:
        raise HTTPException(404, "bill of lading not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/documents/{bl_id}/unlink-sb/{sb_id}", response_model=DocumentDetail)
def unlink_sb(bl_id: str, sb_id: str, request: Request) -> DocumentDetail:
    """Remove one Shipping Bill from this BL's linked set."""
    _require_category_rights(request, "export")
    try:
        return service.unlink_sb_from_bl(bl_id, sb_id)
    except KeyError:
        raise HTTPException(404, "bill of lading not found")


# ------------------------------------------------- Master BL / House BL (Import)
@app.post("/documents/{master_id}/link-house-bl", response_model=DocumentDetail, status_code=201)
async def link_house_bl(master_id: str, request: Request, response: Response, files: list[UploadFile]) -> DocumentDetail:
    """Upload one or more House BLs and link them to this Master BL — the
    Import-category counterpart of /documents/{bl_id}/link-shipping-bill.
    Each one auto-extracts in the background (see field_catalog.HOUSE_BL /
    parsers.yusen_hbl). A bulk batch can run into the hundreds, so the
    (potentially large) DocumentDetail response — including every currently
    linked House BL — is built once at the end, not per file."""
    _require_category_rights(request, "import")
    master = repo.get_document(master_id)
    if master is not None and master["vessel_id"]:
        vessel = repo.get_vessel(master["vessel_id"])
        if vessel is not None and vessel["company_id"]:
            company = repo.get_company(vessel["company_id"])
            if company is not None:
                _assert_company_access(request, company)
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, f"Only .pdf uploads are supported ({f.filename}).")

    linked = 0
    failed: list[str] = []
    for f in files:
        content = await f.read()
        try:
            service.link_house_bl_to_master(
                master_id, f.filename, content, created_by=request.state.user["id"]
            )
            linked += 1
        except KeyError:
            raise HTTPException(404, "master bill of lading not found")
        except ValueError:
            failed.append(f.filename)

    try:
        detail = service.get_document_detail(master_id)
    except KeyError:
        raise HTTPException(404, "master bill of lading not found")
    if failed:
        response.headers["X-Failed-Files"] = ",".join(failed)
    _log(request, "upload", doc_type="house_bl", detail=f"{linked} linked to {master_id}")
    return detail


@app.post("/documents/{master_id}/unlink-house-bl/{house_id}", response_model=DocumentDetail)
def unlink_house_bl(master_id: str, house_id: str, request: Request) -> DocumentDetail:
    """Remove one House BL from this Master BL's linked set."""
    _require_category_rights(request, "import")
    try:
        return service.unlink_house_bl_from_master(master_id, house_id)
    except KeyError:
        raise HTTPException(404, "master bill of lading not found")


def _assert_document_access(request: Request, row: sqlite3.Row) -> None:
    """Company-level check for one document: a Bill of Lading/Shipping Bill
    carries company_id directly; a Master BL/House BL carries vessel_id
    instead — one hop to that vessel's company."""
    company_id = row["company_id"]
    if not company_id and row["vessel_id"]:
        vessel = repo.get_vessel(row["vessel_id"])
        company_id = vessel["company_id"] if vessel else None
    if company_id:
        company = repo.get_company(company_id)
        if company is not None:
            _assert_company_access(request, company)


@app.delete("/documents/{doc_id}", response_model=DeleteOut)
def delete_document(doc_id: str, request: Request) -> DeleteOut:
    """Delete one Bill of Lading / Shipping Bill / Master BL / House BL —
    lets a bad upload be removed and re-uploaded without touching the
    Company/Vessel it lives under. A Master BL also deletes its linked
    House BLs (see service.delete_document); a Shipping Bill only unlinks
    its BLs, which stay exactly as deletable/re-uploadable on their own."""
    row = repo.get_document(doc_id)
    if row is None:
        raise HTTPException(404, "document not found")
    category = _category_of(row["doc_type"])
    _require_category_rights(request, category)
    _assert_document_access(request, row)
    deleted = service.delete_document(doc_id)
    _log(request, "delete", doc_type=row["doc_type"], category=category,
         detail=f"{len(deleted)} record(s) ({row['filename']})")
    return DeleteOut(deleted=deleted)


@app.post("/documents/bulk-delete", response_model=DeleteOut)
def bulk_delete_documents(body: BulkDeleteIn, request: Request) -> DeleteOut:
    """Bulk counterpart of DELETE /documents/{id} — same rights check as
    every other bulk action here (/records/submit, /records/export):
    category-level only, not a per-id company check, since each screen
    only ever selects ids within its own category and company/vessel."""
    category = _category_for_doc_ids(body.doc_ids)
    _require_category_rights(request, category)
    deleted = service.delete_documents(body.doc_ids)
    _log(request, "delete", category=category, detail=f"{len(deleted)} record(s)")
    return DeleteOut(deleted=deleted)


# --------------------------------------------------------------------- export
def _file_response(payload: tuple[bytes, str, str]) -> Response:
    data, media, name = payload
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/documents/{doc_id}/export")
def export_document(
    doc_id: str,
    fmt: str = "xlsx",
    template_id: str | None = None,
    fields: str | None = None,
) -> Response:
    keys = [k for k in fields.split(",") if k] if fields else None
    try:
        return _file_response(
            service.export_documents([doc_id], fmt, keys, template_id)
        )
    except KeyError:
        raise HTTPException(404, "document not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/documents/{bl_id}/export-with-sb")
def export_bl_with_sb(bl_id: str, fmt: str = "xlsx") -> Response:
    """One file for a linked pair: the BL's fields on top, its Shipping
    Bill's fields below (the fixed curated field set — see
    field_catalog.SB_EXPORT_FIELDS)."""
    try:
        return _file_response(service.export_bl_with_sb(bl_id, fmt))
    except KeyError:
        raise HTTPException(404, "document not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/exports")
def export_batch(body: BatchExportIn) -> Response:
    try:
        return _file_response(
            service.export_documents(
                body.doc_ids, body.fmt, body.fields, body.template_id
            )
        )
    except KeyError:
        raise HTTPException(404, "one or more documents not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ------------------------------------------------- Shipping Bill → BL hierarchy
@app.get("/hierarchy", response_model=HierarchyOut)
def hierarchy() -> HierarchyOut:
    return service.list_hierarchy()


@app.get("/shipping-bills", response_model=list[ShippingBillOut])
def list_shipping_bills(limit: int = 50) -> list[ShippingBillOut]:
    return service.list_shipping_bills(limit)


@app.get("/shipping-bills/{sb_id}", response_model=ShippingBillDetail)
def get_shipping_bill(sb_id: str) -> ShippingBillDetail:
    try:
        return service.get_shipping_bill_detail(sb_id)
    except KeyError:
        raise HTTPException(404, "shipping bill not found")


@app.post("/shipping-bills/{sb_id}/link", response_model=ShippingBillDetail)
def link_bls(sb_id: str, body: LinkIn) -> ShippingBillDetail:
    try:
        return service.link_bls(sb_id, body.doc_ids)
    except KeyError:
        raise HTTPException(404, "shipping bill not found")


@app.post("/shipping-bills/{sb_id}/unlink", response_model=ShippingBillDetail)
def unlink_bls(sb_id: str, body: LinkIn) -> ShippingBillDetail:
    try:
        return service.unlink_bls(sb_id, body.doc_ids)
    except KeyError:
        raise HTTPException(404, "shipping bill not found")


@app.get("/shipping-bills/{sb_id}/export")
def export_shipping_bill(
    sb_id: str,
    fmt: str = "xlsx",
    sb_fields: str | None = None,
    bl_fields: str | None = None,
) -> Response:
    def split(v: str | None) -> list[str] | None:
        return [k for k in v.split(",") if k] if v else None

    try:
        return _file_response(
            service.export_hierarchy(sb_id, fmt, split(sb_fields), split(bl_fields))
        )
    except KeyError:
        raise HTTPException(404, "shipping bill not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ----------------------------------------------------------------- corrections
@app.get("/corrections", response_model=list[CorrectionOut])
def list_corrections(limit: int = 200, field_key: str | None = None) -> list[CorrectionOut]:
    rows = repo.list_corrections(limit=limit, field_key=field_key)
    return [
        CorrectionOut(
            id=r["id"], doc_id=r["doc_id"], field_key=r["field_key"],
            ai_value=r["ai_value"], corrected_value=r["corrected_value"],
            format_fingerprint=r["format_fingerprint"], page=r["page"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@app.get("/corrections/stats", response_model=dict)
def correction_stats() -> dict:
    rules = repo.list_anchor_rules()
    return {
        "by_field": repo.correction_counts(),
        "learned_rules": len(rules),
        "learned_formats": len({r["format_fingerprint"] for r in rules}),
    }


@app.get("/anchor-rules", response_model=list[dict])
def list_anchor_rules() -> list[dict]:
    return [
        {
            "format": r["format_fingerprint"],
            "field_key": r["field_key"],
            "label_text": r["label_text"],
            "rel_dx": r["rel_dx"],
            "rel_dy": r["rel_dy"],
            "page": r["page"],
            "hit_count": r["hit_count"],
            "updated_at": r["updated_at"],
        }
        for r in repo.list_anchor_rules()
    ]


# ------------------------------------------------------------------- masters
def _company_out(row: sqlite3.Row) -> CompanyOut:
    branches = [dict(b) for b in repo.get_company_branches(row["id"])]
    return CompanyOut(**dict(row), branches=branches)


def _assert_company_access(request: Request, row: sqlite3.Row) -> None:
    """A regular user may only read a company an admin has assigned to
    them — unlike _assert_owns_or_admin, an unassigned company is NOT open
    to everyone, since the whole point here is admin-controlled access."""
    if request.state.user["role"] == "admin":
        return
    if row["assigned_user_id"] != request.state.user["id"]:
        raise HTTPException(403, "You don't have access to this company.")


@app.get("/companies", response_model=list[CompanyOut])
def list_companies(request: Request, q: str | None = None, limit: int = 200) -> list[CompanyOut]:
    _require_any_category_rights(request)
    return [_company_out(r) for r in repo.list_companies(q, limit, owner_id=_owner_scope(request))]


@app.get("/companies/{company_id}", response_model=CompanyOut)
def get_company(company_id: str, request: Request) -> CompanyOut:
    _require_any_category_rights(request)
    row = repo.get_company(company_id)
    if row is None:
        raise HTTPException(404, "company not found")
    _assert_company_access(request, row)
    return _company_out(row)


@app.post("/companies", response_model=CompanyOut, status_code=201)
def create_company(body: CompanyIn, request: Request) -> CompanyOut:
    # Company Master is admin-only: the admin creates companies and assigns
    # each one to the specific user login that should have access to it.
    _require_admin(request)
    fields = body.model_dump(exclude={"branches"})
    branches = [b.model_dump() for b in body.branches]
    try:
        cid = repo.create_company(
            fields, branches,
            updated_by=request.state.user["username"], created_by=request.state.user["id"],
        )
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Company code {body.company_code!r} already exists.")
    return _company_out(repo.get_company(cid))


@app.put("/companies/{company_id}", response_model=CompanyOut)
def update_company(company_id: str, body: CompanyIn, request: Request) -> CompanyOut:
    _require_admin(request)
    row = repo.get_company(company_id)
    if row is None:
        raise HTTPException(404, "company not found")
    fields = body.model_dump(exclude={"branches"})
    branches = [b.model_dump() for b in body.branches]
    try:
        repo.update_company(company_id, fields, branches, updated_by=request.state.user["username"])
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Company code {body.company_code!r} already exists.")
    return _company_out(repo.get_company(company_id))


@app.delete("/companies/{company_id}")
def delete_company(company_id: str, request: Request) -> dict:
    _require_admin(request)
    row = repo.get_company(company_id)
    if row is None:
        raise HTTPException(404, "company not found")
    repo.delete_company(company_id)
    return {"status": "ok"}


def _port_out(row: sqlite3.Row) -> PortOut:
    berths = [dict(b) for b in repo.get_port_berths(row["id"])]
    return PortOut(**dict(row), berths=berths)


@app.get("/ports", response_model=list[PortOut])
def list_ports(
    request: Request, q: str | None = None, limit: int = 200, company_id: str | None = None,
) -> list[PortOut]:
    _require_any_category_rights(request)
    return [
        _port_out(r)
        for r in repo.list_ports(q, limit, owner_id=_owner_scope(request), company_id=company_id)
    ]


@app.get("/ports/{port_id}", response_model=PortOut)
def get_port(port_id: str, request: Request) -> PortOut:
    _require_any_category_rights(request)
    row = repo.get_port(port_id)
    if row is None:
        raise HTTPException(404, "port not found")
    return _port_out(row)


@app.post("/ports", response_model=PortOut, status_code=201)
def create_port(body: PortIn, request: Request) -> PortOut:
    _require_any_category_rights(request)
    company = repo.get_company(body.company_id)
    if company is None:
        raise HTTPException(400, "Company not found — register the company first.")
    _assert_company_access(request, company)
    fields = body.model_dump(exclude={"berths"})
    berths = [b.model_dump() for b in body.berths]
    try:
        pid = repo.create_port(
            fields, berths,
            updated_by=request.state.user["username"], created_by=request.state.user["id"],
        )
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Port code {body.port_code!r} already exists.")
    return _port_out(repo.get_port(pid))


@app.put("/ports/{port_id}", response_model=PortOut)
def update_port(port_id: str, body: PortIn, request: Request) -> PortOut:
    # Also how the Ports list's Activate/Deactivate toggle is implemented on
    # the frontend: it resends the full port with only `active` flipped —
    # there's no separate toggle endpoint.
    _require_any_category_rights(request)
    row = repo.get_port(port_id)
    if row is None:
        raise HTTPException(404, "port not found")
    if row["company_id"]:
        existing_company = repo.get_company(row["company_id"])
        if existing_company is not None:
            _assert_company_access(request, existing_company)
    company = repo.get_company(body.company_id)
    if company is None:
        raise HTTPException(400, "Company not found — register the company first.")
    _assert_company_access(request, company)
    fields = body.model_dump(exclude={"berths"})
    berths = [b.model_dump() for b in body.berths]
    try:
        repo.update_port(port_id, fields, berths, updated_by=request.state.user["username"])
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"Port code {body.port_code!r} already exists.")
    return _port_out(repo.get_port(port_id))


@app.delete("/ports/{port_id}")
def delete_port(port_id: str, request: Request) -> dict:
    _require_any_category_rights(request)
    row = repo.get_port(port_id)
    if row is None:
        raise HTTPException(404, "port not found")
    if row["company_id"]:
        company = repo.get_company(row["company_id"])
        if company is not None:
            _assert_company_access(request, company)
    repo.delete_port(port_id)
    return {"status": "ok"}


@app.get("/vessels", response_model=list[VesselOut])
def list_vessels(
    request: Request, q: str | None = None, limit: int = 200, company_id: str | None = None,
) -> list[VesselOut]:
    _require_any_category_rights(request)
    master_counts = repo.document_counts_by_vessel("master_bl")
    bl_counts = repo.document_counts_by_vessel("bill_of_lading")
    sb_counts = repo.document_counts_by_vessel("shipping_bill")
    return [
        VesselOut(
            **dict(r), master_bl_count=master_counts.get(r["id"], 0),
            bl_count=bl_counts.get(r["id"], 0), sb_count=sb_counts.get(r["id"], 0),
        )
        for r in repo.list_vessels(q, limit, owner_id=_owner_scope(request), company_id=company_id)
    ]


@app.get("/vessels/{vessel_id}", response_model=VesselOut)
def get_vessel(vessel_id: str, request: Request) -> VesselOut:
    _require_any_category_rights(request)
    row = repo.get_vessel(vessel_id)
    if row is None:
        raise HTTPException(404, "vessel not found")
    if row["company_id"]:
        company = repo.get_company(row["company_id"])
        if company is not None:
            _assert_company_access(request, company)
    master_count = repo.document_counts_by_vessel("master_bl").get(vessel_id, 0)
    bl_count = repo.document_counts_by_vessel("bill_of_lading").get(vessel_id, 0)
    sb_count = repo.document_counts_by_vessel("shipping_bill").get(vessel_id, 0)
    return VesselOut(**dict(row), master_bl_count=master_count, bl_count=bl_count, sb_count=sb_count)


def _assert_distinct_ports(body: VesselIn) -> None:
    if (
        body.departure_port_id
        and body.destination_port_id
        and body.departure_port_id == body.destination_port_id
    ):
        raise HTTPException(400, "Port of Loading and Port of Destination cannot be the same.")


@app.post("/vessels", response_model=VesselOut, status_code=201)
def create_vessel(body: VesselIn, request: Request) -> VesselOut:
    _require_any_category_rights(request)
    company = repo.get_company(body.company_id)
    if company is None:
        raise HTTPException(400, "Company not found — register the company first.")
    _assert_company_access(request, company)
    _assert_distinct_ports(body)
    fields = body.model_dump()
    try:
        vid = repo.create_vessel(
            fields, updated_by=request.state.user["username"], created_by=request.state.user["id"]
        )
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"IMO code {body.imo_code!r} already exists.")
    return VesselOut(**dict(repo.get_vessel(vid)))


@app.put("/vessels/{vessel_id}", response_model=VesselOut)
def update_vessel(vessel_id: str, body: VesselIn, request: Request) -> VesselOut:
    _require_any_category_rights(request)
    row = repo.get_vessel(vessel_id)
    if row is None:
        raise HTTPException(404, "vessel not found")
    if row["company_id"]:
        existing_company = repo.get_company(row["company_id"])
        if existing_company is not None:
            _assert_company_access(request, existing_company)
    company = repo.get_company(body.company_id)
    if company is None:
        raise HTTPException(400, "Company not found — register the company first.")
    _assert_company_access(request, company)
    _assert_distinct_ports(body)
    fields = body.model_dump()
    try:
        repo.update_vessel(vessel_id, fields, updated_by=request.state.user["username"])
    except sqlite3.IntegrityError:
        raise HTTPException(400, f"IMO code {body.imo_code!r} already exists.")
    return VesselOut(**dict(repo.get_vessel(vessel_id)))


@app.post("/vessels/{vessel_id}/bulk-upload", response_model=BulkUploadOut, status_code=201)
async def bulk_upload_vessel_documents(
    vessel_id: str, request: Request, files: list[UploadFile]
) -> BulkUploadOut:
    """Export's bulk upload — the counterpart of Import's
    /documents/{master_id}/link-house-bl, built for the same scale (up to
    ~400 files in one batch): each file's type (Bill of Lading / Shipping
    Bill) is auto-detected, same as /ingest, and extraction is scheduled
    per file without rebuilding any growing response in between — see
    service.bulk_upload_to_vessel's docstring.
    """
    _require_category_rights(request, "export")
    vessel = repo.get_vessel(vessel_id)
    if vessel is None:
        raise HTTPException(404, "vessel not found")
    if vessel["company_id"]:
        company = repo.get_company(vessel["company_id"])
        if company is not None:
            _assert_company_access(request, company)
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(400, f"Only .pdf uploads are supported ({f.filename}).")

    payload = [(f.filename, await f.read()) for f in files]
    try:
        result = service.bulk_upload_to_vessel(
            vessel_id, payload, created_by=request.state.user["id"]
        )
    except KeyError:
        raise HTTPException(404, "vessel not found")
    _log(request, "upload", category="export",
         detail=f"{len(result['uploaded'])} uploaded to vessel {vessel_id}")
    return BulkUploadOut(**result)


@app.delete("/vessels/{vessel_id}")
def delete_vessel(vessel_id: str, request: Request) -> dict:
    # Neither Vessel Workspace (Import or Export) offers Delete from the UI
    # any more — delete the Master BL/House BL or BL/Shipping Bill(s) under
    # a vessel instead (DELETE /documents/{id}, POST /documents/bulk-delete)
    # and re-upload; the vessel itself stays put. This endpoint remains as
    # a guarded fallback (e.g. removing a vessel created by mistake that
    # was never actually used) — still refuses to delete one with any
    # documents under it, Import's or Export's, so it can never silently
    # orphan extracted data.
    _require_any_category_rights(request)
    row = repo.get_vessel(vessel_id)
    if row is None:
        raise HTTPException(404, "vessel not found")
    if row["company_id"]:
        company = repo.get_company(row["company_id"])
        if company is not None:
            _assert_company_access(request, company)
    if repo.any_document_count_for_vessel(vessel_id) > 0:
        raise HTTPException(
            400,
            "This vessel has uploaded document(s) — delete those first "
            "(DELETE /documents/{id} or bulk-delete), not the vessel.",
        )
    repo.delete_vessel(vessel_id)
    return {"status": "ok"}


# ------------------------------------------------------------------ activity
@app.get("/activity", response_model=list[ActivityOut])
def list_activity(
    request: Request, category: str = "export", user_id: str | None = None, limit: int = 200
) -> list[ActivityOut]:
    """Every logged-in user's own activity feed for one side of the app; an
    admin may also pass ``user_id`` to look at one specific user's (omit it
    to see everyone's). Export's and Import's feeds never mix — login is the
    only action that appears in both, since it isn't tied to either side."""
    if category not in _CATEGORY_DOC_TYPES:
        raise HTTPException(400, f"unknown category: {category}")
    _require_category_rights(request, category)
    scope = _owner_scope(request)
    uid = scope if scope else user_id  # non-admin is always forced to their own
    return [
        ActivityOut(id=r["id"], user_id=r["user_id"], username=r["username"], action=r["action"],
                     doc_type=r["doc_type"], category=r["category"], detail=r["detail"],
                     created_at=r["created_at"])
        for r in repo.list_activity(user_id=uid, category=category, limit=limit)
    ]


@app.get("/activity/summary", response_model=list[ActivitySummaryRow])
def activity_summary(request: Request, category: str = "export") -> list[ActivitySummaryRow]:
    """Per-user, per-action totals, scoped to one side of the app — a
    regular user's dashboard is just their own row of this; an admin's is
    everyone's (see /analytics/overview for the rest of the admin dashboard)."""
    if category not in _CATEGORY_DOC_TYPES:
        raise HTTPException(400, f"unknown category: {category}")
    _require_category_rights(request, category)
    scope = _owner_scope(request)
    rows = repo.activity_counts_by_user(category=category)
    if scope:
        rows = [r for r in rows if r["user_id"] == scope]
    return [
        ActivitySummaryRow(user_id=r["user_id"], username=r["username"], action=r["action"], count=r["n"])
        for r in rows
    ]


@app.get("/analytics/overview", response_model=dict)
def analytics_overview(request: Request, category: str = "export") -> dict:
    """Admin-only: document counts by type/status within one side of the
    app, plus total user count and (Export only — Import has no extracted
    fields yet) a "by location" breakdown using the Bill of Lading's own
    Port of Loading / Port of Discharge fields."""
    _require_admin(request)
    if category not in _CATEGORY_DOC_TYPES:
        raise HTTPException(400, f"unknown category: {category}")
    types = list(_CATEGORY_DOC_TYPES[category])
    by_type: dict[str, dict[str, int]] = {}
    for r in repo.document_counts_by_type():
        if r["doc_type"] in types:
            by_type.setdefault(r["doc_type"], {})[r["status"]] = r["n"]
    # Ground truth, straight from the documents table — unlike activity_log
    # (which only has entries from the point login/upload logging went
    # live), this always reflects every existing record, so historical data
    # a user uploaded before logging existed still shows up here.
    by_user = [
        {"user_id": r["user_id"], "username": r["username"], "n": r["n"]}
        for r in repo.document_counts_by_user(types)
    ]
    # Company-wise analytics: shared across Export (document.company_id
    # directly) and Import (resolved through the document's vessel) — see
    # repo.document_counts_by_company.
    by_company = [
        {"company_id": r["company_id"], "company_name": r["company_name"], "n": r["n"]}
        for r in repo.document_counts_by_company(types)
    ]
    out: dict = {
        "total_users": len(repo.list_users()),
        "total_documents": sum(r["n"] for r in by_user),
        "documents_by_type": by_type,
        "documents_by_user": by_user,
        "documents_by_company": by_company,
    }
    if category == "export":
        out["by_port_of_loading"] = [dict(r) for r in repo.document_counts_by_location("port_of_loading")]
        out["by_port_of_discharge"] = [dict(r) for r in repo.document_counts_by_location("port_of_discharge")]
    return out


# ------------------------------------------------------------ export templates
@app.get("/export-templates", response_model=list[ExportTemplateOut])
def list_export_templates() -> list[ExportTemplateOut]:
    out = []
    for r in repo.list_export_templates():
        out.append(
            ExportTemplateOut(
                id=r["id"], name=r["name"], owner=r["owner"],
                selected_fields=json.loads(r["selected_fields"]),
                column_order=json.loads(r["column_order"]) if r["column_order"] else None,
                output_type=r["output_type"],
                format_fingerprint=r["format_fingerprint"],
                created_at=r["created_at"],
            )
        )
    return out


@app.post("/export-templates", response_model=ExportTemplateOut, status_code=201)
def create_export_template(body: ExportTemplateIn) -> ExportTemplateOut:
    tid = repo.create_export_template(
        name=body.name, selected_fields=body.selected_fields,
        column_order=body.column_order, output_type=body.output_type,
        format_fingerprint=body.format_fingerprint, owner=body.owner,
    )
    row = next(r for r in repo.list_export_templates() if r["id"] == tid)
    return ExportTemplateOut(
        id=row["id"], name=row["name"], owner=row["owner"],
        selected_fields=json.loads(row["selected_fields"]),
        column_order=json.loads(row["column_order"]) if row["column_order"] else None,
        output_type=row["output_type"], format_fingerprint=row["format_fingerprint"],
        created_at=row["created_at"],
    )


# ------------------------------------------------------------------ frontend
# Opt-in (SERVE_FRONTEND=1): serve the built React app from the same process
# and port as the API, so a single service handles both. Mounted last so it
# only catches requests that don't match an API route above.
if settings.serve_frontend:
    from fastapi.staticfiles import StaticFiles

    class _FrontendFiles(StaticFiles):
        """index.html must be revalidated on every load — with no cache header
        Chrome may keep serving a stale copy after a redeploy, so users keep
        seeing the old UI. The hashed files under /assets never change, so
        those can be cached indefinitely."""

        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            path = path.replace("\\", "/")  # Starlette hands us OS-style paths on Windows
            if path.startswith("assets/"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif path in ("", ".") or path.endswith(".html"):
                response.headers["Cache-Control"] = "no-cache"
            return response

    _dist = config.PROJECT_DIR / "frontend" / "dist"
    if _dist.is_dir():
        app.mount("/", _FrontendFiles(directory=str(_dist), html=True), name="frontend")
