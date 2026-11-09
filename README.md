# BL-AI — local AI Bill of Lading reader

Upload any company's Bill of Lading → local OCR reads the whole document → a
local model maps it onto a fixed set of business fields → you edit/confirm →
export to Excel/PDF → the system learns from your corrections for the next BL.

**No cloud LLM. No per-document API cost.** Everything runs on your own hardware.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design, licensing,
scaling and cost breakdown.

## Status

| Step | Scope | State |
|------|-------|-------|
| **1** | Local extraction core: canonical schema, OCR ingestion (digital + scanned), Tier A anchor engine, validators, CLI | ✅ done |
| **2** | FastAPI service + SQLite storage; upload → extract → review → corrections capture | ✅ done |
| **3** | React + PDF.js review/edit screen with bbox highlighting | ✅ done |
| **4** | Export to Excel / PDF, batch export, saved & applied field templates | ✅ done |
| **5** | Learning loop v1: corrections → per-format anchor rules; field-selection presets auto-applied | ✅ done |
| **6** | Multi-doc-type: Shipping Bill (15 fields) + **Shipping Bill → many BLs** hierarchy, managed from the SB | ✅ done |
| **7** | Auto pipeline: auto-detect doc type on upload, auto-link BL↔SB by SB number, hierarchy export (Excel/PDF) | ✅ done |
| **8** | Dedicated **ICEGATE Shipping Bill parser** (grid-aware, 19 fields); multi-file upload; hierarchy shows BL no. + POD | ✅ done |
| 9 | Format detection (fingerprint + vector search); Tier B model | ⬜ next |

### Template parsers ([app/parsers/](backend/app/parsers/))

Known fixed forms are read by their **structure**, not label matching. Each
parser has a tight `matches()` and returns `{field: (value, confidence)}`; the
first to match **owns** the document.

- [icegate_sb.py](backend/app/parsers/icegate_sb.py) — Indian Customs EDI
  Shipping Bill: top `Port Code | SB No | SB Date` grid, `PKG … G.WT MTS` row,
  exporter/consignee blocks (drops a leading `TO THE` to get the buyer), the
  numbered inline fields (`CIN NO.`, `LEO NO./Date`, `NATURE OF CARGO`,
  `COUNTRY/PORT OF FINAL DESTINATION`), and **every unique 8-digit HS/RITC code +
  description, de-duplicated across all pages**.
- [aof_bl.py](backend/app/parsers/aof_bl.py) — AOF Cargo "Multimodal Transport
  Bill of Lading": pattern extraction for BL no., SO no., carrier, gross/CBM,
  packages, freight terms, movement, on-board date, originals, IEC, containers
  (+size), notify parties; geometry for the shipper/consignee/routing boxes.
- [container_bl.py](backend/app/parsers/container_bl.py) — **Container BL**
  (combined-transport / port-to-port form, e.g. WINCO): booking + BL no., move
  type, originals, packages, gross/CBM, container+size+seal, parties, routing,
  and **every unique HS Code lifted from the description block**.
- [breakbulk_bl.py](backend/app/parsers/breakbulk_bl.py) — **Break Bulk (Liner)
  BL**: BL no., parties, vessel, ports, marks, packages, and — pulled from the
  "Description of Packages & Goods" — the **Shipping Bill No. & date** and the
  **Net Weight + unit** (distinguished from gross).
- [jeena_bl.py](backend/app/parsers/jeena_bl.py) — **adaptive house BL** for
  shipments routed through **JEENA & COMPANY** as India agent (SupplyX,
  Multitrade / Balguerie, Italsempione, Yang Ming / WINCO, …). Reads the standard
  English boxes by geometry; when the box labels are baked into a background
  image it falls back to shape-based regex + left-column block clustering. Splits
  **Shipper / Consignee / Notify** into separate **Name / Address / State**
  fields (country as State for foreign parties), takes **Booking No. only from a
  Booking No. box** (never the BL no.), normalises European decimals, and drops
  vertical watermark stamps ("ORIGINAL", "SURRENDERED"). Registered last, so a
  carrier-specific parser still wins.

The `bill_of_lading` type is one catalog; the matched parser sets
`document_type` to "Container Bill of Lading" / "Break Bulk Bill of Lading" and
the UI shows it as a chip. `_common.py` holds the shared geometry helpers.
Add a parser per new fixed form; nothing else changes. A matched template
**owns** the document — the extractor trusts only its values and leaves the rest
blank (never the generic garbage), and your corrections on those blanks feed the
learning loop.

The ICEGATE parser is **per-page and coordinate-based** (list order in the PDF's
text layer is not visual order): the SB summary is read from page 1 only,
HS/RITC codes are collected unique across all pages, and each value is found by
projecting a **column** below/above its label (top grid, CIN, Nature of Cargo)
or reading **beside** it (LEO, Final Destination) — whichever that cell uses.

**Debugging a mis-read layout:** every ICEGATE PDF's text layer is slightly
different. Dump the token grid and share it to get the parser tuned:

```powershell
npm run cli -- "path\to\shipping_bill.pdf" --tokens
```

### The automatic pipeline (`POST /ingest`)

Upload a PDF → the system **classifies** it (BL vs Shipping Bill, keyword scoring —
[classify.py](backend/app/classify.py)) → OCR + extract the right field set →
**auto-links** it. Extraction collects **every** Shipping Bill number a BL
mentions (`SHIPPING BILL NOS: 7412580, 7412581 & 7412599`, `SB NO. 5778867 DT …`)
into `shipping_bill_number_and_date`; the BL attaches to the first of those
Shipping Bills that exists, and a newly-added Shipping Bill adopts every earlier
unlinked BL that lists its number (match is on *any* referenced number, not just
the first). The Shipping Bill review screen shows its linked BLs live as each
one finishes extracting. A manually-set link is never overridden (`link_source`
= `auto` | `manual`). `GET /shipping-bills/{id}/export?fmt=xlsx|pdf` emits the
whole hierarchy — an **"SB + Linked BLs" sheet** (one row per BL, Shipping Bill
fields repeated as leading `SB: …` columns) plus per-doc sheets/pages.
| 7 | Tier B: LiLT/Donut fine-tune + model registry + eval gate | ⬜ |
| 8 | Scale-out: queue + inference service + GPU + Docker | ⬜ |

### How the learning loop works (v1)

1. Reviewer fixes a field and saves. The correction is logged **and**
   [`app/learning.py`](backend/app/learning.py) re-opens the document, locates the
   corrected value's tokens, finds the nearest matching label, and stores the
   value's position *relative to that label* as an **anchor rule** keyed by
   `(format, field)` in the `anchor_rules` table.
2. Next time a BL of the same format is extracted, `AnchorExtractor` re-finds the
   label and reads the value at the learned offset — overriding the generic
   guess. No model training.
3. Saving an export field selection with a format tag makes it the
   **suggested selection** (`suggested_export_fields`) for every future BL of
   that format; the UI pre-ticks it automatically.
4. `GET /anchor-rules` and `GET /corrections/stats` show what's been learned.

## Project structure

One repo, two apps, one set of commands.

```
BL-AI/
  package.json            # root: workspaces + unified dev/test/build scripts
  scripts/
    setup.mjs             # venv + all deps  (runs automatically before dev)
    ensure-setup.mjs      # predev hook: install deps on first run
    open-when-ready.mjs   # opens the browser once the web server is up
    py.mjs               # runs backend Python from backend/.venv, any OS
  backend/                # Python — FastAPI + local OCR/KIE
    pyproject.toml        # pytest + ruff config
    requirements.txt · requirements-dev.txt
    .env.example
    app/
      field_catalog.py    # canonical fields per doc type: 40 for BL, 15 for Shipping Bill
      models.py           # FieldValue / ExtractionResult
      document.py         # unified loader: digital PDF text OR rasterise+OCR -> tokens+boxes
      ocr.py              # local OCR backends: RapidOCR (default), Tesseract
      extraction/
        anchor_extractor.py# Tier A: label-anchor + geometry + learned anchor rules
        validate.py        # ISO 6346 check digit, date/quantity parsing, cross-field checks
      classify.py          # auto doc-type detection (BL vs Shipping Bill)
      parsers/             # template parsers per fixed form: icegate_sb, aof_bl,
                           #   container_bl, breakbulk_bl, jeena_bl (+ _common.py)
      formats.py           # normalise a detected layout into a stable format key
      learning.py          # corrections -> anchor rules (the learning loop)
      db.py · repository.py # SQLite schema + typed CRUD (Postgres-portable SQL)
      service.py           # orchestration: ingest -> extract -> review -> learn
      schemas.py · api.py   # HTTP models + FastAPI app
      cli.py               # command-line extractor
    tests/                # pytest: extraction + API
  frontend/                # React + Vite + PDF.js review UI
    src/
      App.jsx · api.js · styles.css
      components/PdfViewer.jsx
      api.test.js          # vitest
  docs/ARCHITECTURE.md
  samples/                 # put BL PDFs here
  data/                    # uploads, sqlite db, model artifacts (git-ignored)
  deploy/windows/          # Windows Server install/service/backup/update scripts
```

## Run it — one command

```powershell
npm run dev          # or: npm start
```

From a **fresh clone** this is all you need. It:

1. runs setup automatically on first use — creates `backend/.venv`, installs all
   Python + Node dependencies (the `predev` hook; ~1 min once),
2. starts the **API** on :8000 (auto-reload) and the **review UI** on :5173,
3. **opens `http://localhost:5173` in your browser** as soon as it's ready.

Press `Ctrl+C` once to stop both. First run of the OCR path also downloads the
RapidOCR ONNX models (~15 MB) once. To tweak defaults, `copy backend\.env.example
backend\.env`.

## Deploying to Windows Server

That's the dev workflow. For a standing Windows Server install — running as a
real Windows Service that starts on boot, with firewall/backup/upgrade
scripts — see [docs/WINDOWS_DEPLOYMENT.md](docs/WINDOWS_DEPLOYMENT.md). Short
version:

```powershell
.\deploy\windows\install.ps1              # venv + deps + frontend build
.\deploy\windows\install-service.ps1      # elevated — installs & starts the service
.\deploy\windows\open-firewall.ps1        # elevated — opens the port
```

### Other commands (from the repo root)

| Command | What it does |
|---------|--------------|
| `npm run setup` | force the dependency install (normally automatic) |
| `npm run dev:api` / `npm run dev:web` | run just one side (no browser open) |
| `npm test` | backend `pytest` + frontend `vitest` |
| `npm run test:api` / `npm run test:web` | just one side |
| `npm run build` | production build of the frontend |
| `npm run cli -- "samples\HBL-H680557 (1).pdf"` | run the extractor on one PDF |

Open http://localhost:5173 (UI) or http://localhost:8000/docs (API).

**Layout:** an admin shell — left nav with two separate pages:

- **Upload Data** — upload PDF(s); a table of **pending** documents (stat cards,
  search / type / status / date filters). Review a row, then **Submit** it
  (single or bulk) — it leaves this page.
- **Submitted Data** — **submitted records only**; same filterable table, row
  checkboxes, and **Download Excel / PDF** that exports every selected record
  together (BL + Shipping Bill in one workbook, a sheet per type). Submitted
  records never appear back in Upload.

**Review** (opened from either page): fields grouped (Identity / Parties /
Routing / Cargo / …), each editable with a confidence badge; the PDF on the
right with click-to-highlight; for a Shipping Bill, a "Linked Bills of Lading"
card. **Save** persists edits (each logs a `correction`); **Submit** finalises.

**OCR speed:** the token model is cached on disk keyed by the file's content
hash (`data/tokcache/`), so re-extracting a document and every subsequent
save/correction reuse the OCR result instead of re-running it. Digital PDFs are
re-parsed directly (already instant) and never cached. Unknown layouts are
unaffected — same extraction, just not re-OCR'd.

### API surface

| Method | Route | Purpose |
|--------|-------|---------|
| `POST` | `/documents` | upload a BL PDF (multipart `file`) |
| `POST` | `/documents/{id}/extract` | run the local extractor, persist fields |
| `GET`  | `/doc-types` · `/fields?doc_type=` | the document types and each one's canonical field set |
| `POST` | `/ingest` (form: `file`, `doc_type?`, `parent_id?`) | **one call**: upload → auto-detect type → extract → auto-link |
| `POST` | `/documents` (form: `file`, `doc_type?`, `parent_id?`) | upload only (type auto-detected if omitted) |
| `GET`  | `/documents/{id}` | document + its canonical fields (value, confidence, ai_value, page, bbox, source) + warnings |
| `GET`  | `/uploads` · `/uploads/stats` | **pending** records (Upload Data page) — not yet submitted |
| `GET`  | `/records` · `/records/stats` | **submitted** records only (Submitted Data page) |
| `POST` | `/records/submit` `{doc_ids}` | finalise records — move them Upload → Submitted |
| `POST` | `/records/export` `{doc_ids, fmt}` | **bulk export** of selected BL + Shipping Bill records to one file (a sheet per type) |

Both list endpoints accept `q` / `status` / `doc_type` / `date_from` / `date_to` / `limit`.
| `GET`  | `/hierarchy` | the whole tree in one call: each Shipping Bill + its `linked_bls[]` + `unlinked_bls[]` |
| `GET`  | `/shipping-bills` · `/shipping-bills/{id}` | Shipping Bills with `bl_count`; detail with `linked_bls[]` |
| `POST` | `/shipping-bills/{id}/link` · `/unlink` | attach / detach BLs (`{doc_ids}`) under a Shipping Bill |
| `GET`  | `/shipping-bills/{id}/export?fmt=xlsx\|pdf` | the SB + all its linked BLs as one file |
| `GET`  | `/documents/{id}/file` | the original PDF (for the viewer) |
| `PUT`  | `/documents/{id}/fields` | save edits — every changed field logs a `correction` |
| `GET`  | `/documents/{id}/export?fmt=xlsx\|pdf&fields=…&template_id=…` | download one BL as Excel or PDF |
| `POST` | `/exports` | batch export `{doc_ids, fmt, fields?, template_id?}` → one file |
| `GET`  | `/corrections` · `/corrections/stats` | the accumulating learning signal + learned-rule counts |
| `GET`  | `/anchor-rules` | the layout rules learned from corrections |
| `GET`/`POST` | `/export-templates` | saved field selections, reusable & auto-suggested per format |

## Config (`backend/.env`)

| Var | Default | Meaning |
|-----|---------|---------|
| `OCR_BACKEND` | `rapidocr` | `rapidocr` \| `tesseract` \| `none` |
| `OCR_DPI` | `200` | rasterisation DPI for scanned pages |
| `EXTRACTION_ENGINE` | `rules` | `rules` (Tier A) \| `kie` (Tier B, once trained) |
| `KIE_MODEL_DIR` | — | path to the trained model when `EXTRACTION_ENGINE=kie` |
