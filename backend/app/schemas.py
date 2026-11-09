"""HTTP request/response models (separate from the internal extraction models)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: str
    username: str
    role: str = "user"
    # Screen-level rights — an admin ignores these and always sees both; the
    # frontend uses them to show only the Export screen, only Import, or
    # both, for a regular user.
    can_export: bool = True
    can_import: bool = True


class UserCreateIn(BaseModel):
    username: str
    password: str
    role: str = "user"          # 'admin' | 'user'
    can_export: bool = True
    can_import: bool = True


class UserUpdateIn(BaseModel):
    role: Optional[str] = None            # 'admin' | 'user'
    password: Optional[str] = None        # set to reset it (also kills existing sessions)
    can_export: Optional[bool] = None
    can_import: Optional[bool] = None


class UserAdminOut(BaseModel):
    """Full account row, for the admin-only User Master / Rights Management
    screens (UserOut is the smaller shape /auth/me and /auth/login hand back
    to any logged-in user about themselves)."""
    id: str
    username: str
    role: str
    can_export: bool
    can_import: bool
    created_at: str


class CatalogField(BaseModel):
    key: str
    label: str
    group: str
    type: str
    aliases: list[str]
    example: str


class FieldOut(BaseModel):
    key: str
    label: str
    group: str
    type: str
    value: Optional[str]
    confidence: float
    ai_value: Optional[str]
    page: Optional[int]
    bbox: Optional[list[float]]
    source: str


class DocumentOut(BaseModel):
    id: str
    filename: str
    doc_type: str
    parent_id: Optional[str] = None
    link_source: Optional[str] = None      # 'auto' | 'manual'
    submitted: bool = False
    status: str
    engine: Optional[str]
    page_count: Optional[int]
    has_scanned_pages: bool
    format_fingerprint: Optional[str]
    created_by: Optional[str] = None
    # Import workflow only — which Vessel Workspace this Master BL (and its
    # House BLs, which inherit their master's vessel) belongs to.
    vessel_id: Optional[str] = None
    vessel_name: Optional[str] = None
    # Export workflow only — which Company Workspace this Bill of Lading /
    # Shipping Bill belongs to (a linked Shipping Bill inherits its BL's
    # company, the same way a House BL inherits its Master BL's vessel).
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    created_at: str
    updated_at: str


class LinkedSbOut(BaseModel):
    """One Shipping Bill linked to a BL via the BL-first flow — a BL can have
    many of these (50+ supported)."""
    id: str
    filename: str
    status: str
    sb_number: Optional[str] = None
    # True/False once both this SB's own number and the BL's own reference
    # list have been extracted; None while either side is still pending (or
    # the BL simply has no SB numbers to check against).
    sb_number_match: Optional[bool] = None
    # True when another linked Shipping Bill on this same BL shares this
    # exact number — lets the UI highlight every row involved in the
    # duplicate, not just list the number once in the summary.
    is_duplicate: bool = False
    link_source: Optional[str] = None
    # The fixed curated field set (see field_catalog.SB_EXPORT_FIELDS) — the
    # only set shown/exported alongside a linked BL.
    fields: list[FieldOut] = []


class SbReconciliation(BaseModel):
    """How the BL's own referenced Shipping Bill numbers (extracted from its
    ``shipping_bill_number_and_date`` field) line up against what's actually
    been uploaded and linked to it."""
    total_referenced: int = 0
    total_uploaded: int = 0
    # referenced by the BL but no matching upload exists yet
    missing_numbers: list[str] = []
    # the same Shipping Bill number was uploaded/linked more than once
    duplicate_numbers: list[str] = []
    # uploaded and linked, but this number isn't among the BL's own
    # references at all — may be an incorrect upload
    unrelated_numbers: list[str] = []


class LinkedHouseBlOut(BaseModel):
    """One House BL linked to a Master BL, in the list view. House BL does
    have its own field catalog now (field_catalog.HOUSE_BL) — deliberately
    kept out of this row anyway: a Master BL can carry hundreds of House
    BLs in one bulk batch, and this list is rebuilt on every document
    detail fetch, so it stays light. The full 45-field set is fetched
    separately, per document, only when that one House BL is opened.

    container_numbers / has_* flags are the Import-side counterpart of
    LinkedSbOut's sb_number / sb_number_match / is_duplicate — see
    ContainerReconciliation below for what they're checked against."""
    id: str
    filename: str
    status: str
    link_source: Optional[str] = None
    container_numbers: list[str] = []
    has_unrelated_container: bool = False
    has_duplicate_container: bool = False


class ContainerReconciliation(BaseModel):
    """How the Master BL's own container numbers (scanned directly off its
    PDF — Master BL has no field catalog yet, see field_catalog.MASTER_BL)
    line up against what's actually been extracted from its linked House
    BLs. The Import-side counterpart of SbReconciliation, keyed on
    container numbers instead of Shipping Bill numbers."""
    total_master: int = 0
    total_uploaded: int = 0
    # on the Master BL, not found on any linked House BL
    missing_containers: list[str] = []
    # the same container number appears on more than one House BL (or more
    # than once within one)
    duplicate_containers: list[str] = []
    # found on a House BL but not among the Master BL's own containers —
    # may be an incorrect upload
    unrelated_containers: list[str] = []


class DocumentDetail(DocumentOut):
    fields: list[FieldOut]
    warnings: list[str] = []
    suggested_export_fields: list[str] = []
    # Populated only for a Bill of Lading — every Shipping Bill linked to it
    # via the BL-first flow (see service.link_shipping_bill_to_bl).
    linked_shipping_bills: list[LinkedSbOut] = []
    # Populated only for a Bill of Lading that references at least one
    # Shipping Bill number — None otherwise (nothing to reconcile against).
    sb_reconciliation: Optional[SbReconciliation] = None
    # Populated only for a Master BL — every House BL linked to it.
    linked_house_bls: list[LinkedHouseBlOut] = []
    # Populated only for a Master BL whose own container numbers have been
    # OCR'd and found at least one — None otherwise (nothing to reconcile
    # against yet, or still being OCR'd — see _linked_house_bls).
    container_reconciliation: Optional[ContainerReconciliation] = None


class ShippingBillOut(DocumentOut):
    bl_count: int = 0


class LinkedBlOut(DocumentOut):
    bl_number: Optional[str] = None
    port_of_discharge: Optional[str] = None


class ShippingBillDetail(DocumentDetail):
    linked_bls: list[LinkedBlOut] = []


class HierarchySbOut(ShippingBillOut):
    sb_number: Optional[str] = None
    linked_bls: list[LinkedBlOut] = []


class HierarchyOut(BaseModel):
    shipping_bills: list[HierarchySbOut] = []
    unlinked_bls: list[LinkedBlOut] = []


class LinkIn(BaseModel):
    doc_ids: list[str]


class FieldEdit(BaseModel):
    key: str
    value: Optional[str] = None


class FieldsUpdateIn(BaseModel):
    fields: list[FieldEdit]


class ExtractIn(BaseModel):
    engine: Optional[str] = None            # defaults to settings.extraction_engine


class CorrectionOut(BaseModel):
    id: str
    doc_id: str
    field_key: str
    ai_value: Optional[str]
    corrected_value: Optional[str]
    format_fingerprint: Optional[str]
    page: Optional[int]
    created_at: str


class ExportTemplateIn(BaseModel):
    name: str
    selected_fields: list[str]
    column_order: Optional[list[str]] = None
    output_type: str = "xlsx"
    format_fingerprint: Optional[str] = None
    owner: Optional[str] = None


class ExportTemplateOut(ExportTemplateIn):
    id: str
    created_at: str


class BatchExportIn(BaseModel):
    doc_ids: list[str]
    fmt: str = "xlsx"                       # xlsx | pdf
    template_id: Optional[str] = None
    fields: Optional[list[str]] = None      # explicit selection overrides template


class RecordOut(BaseModel):
    id: str
    job_id: str
    doc_type: str
    doc_number: Optional[str] = None        # bl_number or sb_number
    filename: str
    status: str
    submitted: bool = False
    field_count: int = 0
    issue_count: int = 0
    parent_id: Optional[str] = None
    link_source: Optional[str] = None
    linked_sb_count: int = 0                # Shipping Bills nested under this BL
    linked_house_bl_count: int = 0          # House BLs nested under this Master BL
    sb_referenced_count: int = 0            # distinct SB numbers this BL's own text names
    sb_missing_count: int = 0               # referenced but not yet uploaded (shortage)
    sb_duplicate_count: int = 0             # same SB number uploaded more than once
    vessel_id: Optional[str] = None
    vessel_name: Optional[str] = None
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    created_at: str
    updated_at: str


class SubmitIn(BaseModel):
    doc_ids: list[str]


class BulkDeleteIn(BaseModel):
    doc_ids: list[str]


class DeleteOut(BaseModel):
    deleted: list[str]


class BulkUploadOut(BaseModel):
    uploaded: list[str]
    failed: list[str]


class RecordStats(BaseModel):
    total: int = 0
    complete: int = 0
    needs_review: int = 0
    by_status: dict[str, int] = {}
    last_saved: Optional[str] = None


class CompanyBranchIn(BaseModel):
    branch_code: str
    branch_name: str
    branch_address: str
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    gstin_no: Optional[str] = None
    zipcode: str
    telephone_no: str
    email_id: str
    remarks: Optional[str] = None


class CompanyBranchOut(CompanyBranchIn):
    id: str


class CompanyIn(BaseModel):
    # Access-control: a company is only visible/usable to the one user login
    # an admin assigns it to (None = unassigned, admin-only until assigned).
    assigned_user_id: Optional[str] = None
    company_code: str
    company_name: str
    city_name: Optional[str] = None
    state_region: Optional[str] = None
    country_name: str
    company_address: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    email_id: Optional[str] = None
    pan_no: str
    gstin_no: str
    company_group_name: Optional[str] = None
    credit_period: Optional[str] = None
    currency: Optional[str] = None
    iec_no: Optional[str] = None
    website: Optional[str] = None
    remarks: Optional[str] = None
    branches: list[CompanyBranchIn] = []


class CompanyOut(CompanyIn):
    id: str
    branches: list[CompanyBranchOut] = []
    assigned_username: Optional[str] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: str
    updated_at: str


class PortBerthIn(BaseModel):
    berth: Optional[str] = None
    fpd_code: Optional[str] = None


class PortBerthOut(PortBerthIn):
    id: str


class PortIn(BaseModel):
    # Registration workflow: a Company must already exist and be picked
    # before a Port can be created — Port is always registered under a
    # Company, never standalone.
    company_id: str
    port_type: str = "SEA PORT"
    port_code: str
    edi_port_code: Optional[str] = None
    port_name: str
    country: str
    active: bool = True
    sez: bool = False
    berths: list[PortBerthIn] = []


class PortOut(BaseModel):
    id: str
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    port_type: str
    port_code: str
    edi_port_code: Optional[str] = None
    port_name: str
    country: str
    active: bool
    sez: bool
    berths: list[PortBerthOut] = []
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: str
    updated_at: str


class VesselIn(BaseModel):
    name: str
    imo_code: str
    call_sign: str
    build_year: Optional[str] = None
    gross_tonnage: Optional[str] = None
    net_tonnage: Optional[str] = None
    ship_type: Optional[str] = None
    # Registration workflow: a Company must already exist and be picked
    # before a Vessel can be created — Vessel is always registered under a
    # Company, never standalone.
    company_id: str
    departure_port_id: Optional[str] = None
    destination_port_id: Optional[str] = None


class VesselOut(VesselIn):
    id: str
    company_name: Optional[str] = None
    departure_port_name: Optional[str] = None
    destination_port_name: Optional[str] = None
    # Vessel Workspace list: how many Master BLs have been uploaded under
    # this vessel so far — lets the list show activity without a click-through.
    master_bl_count: int = 0
    # Export's own Vessel Workspace counterpart — a vessel is shared
    # infrastructure between both sides now, so these stay 0 for a
    # vessel only ever used from Import, same as master_bl_count stays 0
    # for one only ever used from Export.
    bl_count: int = 0
    sb_count: int = 0
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    created_at: str
    updated_at: str


class ActivityOut(BaseModel):
    id: str
    user_id: Optional[str] = None
    username: str
    action: str
    doc_type: Optional[str] = None
    category: Optional[str] = None
    detail: Optional[str] = None
    created_at: str


class ActivitySummaryRow(BaseModel):
    user_id: Optional[str] = None
    username: str
    action: str
    count: int


class LocationCountRow(BaseModel):
    location: str
    count: int


class RecordsExportIn(BaseModel):
    doc_ids: list[str]
    fmt: str = "xlsx"                       # xlsx | pdf
    # False (default): one file per document, zipped when there's more than
    # one. True: merge every selected Bill of Lading (+ its linked Shipping
    # Bills) into a single xlsx workbook instead — xlsx only.
    combine: bool = False
