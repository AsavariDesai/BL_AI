# BL-AI — Local architecture (no cloud LLM)

Goal: upload any company's Bill of Lading → local OCR reads the whole document →
a local model maps it onto a fixed set of business fields → user edits/confirms →
export to Excel/PDF → the system learns from the user's corrections.

Everything runs on your own hardware. No per-document API cost.

---

## 1. Why "OCR" is not enough by itself

OCR converts pixels into text + coordinates. It cannot tell you which text is the
"consignee" or the "port of discharge". Mapping *any layout* onto your fixed
fields needs a second stage — **Key Information Extraction (KIE)**.

```
PDF/image ─▶ Preprocess ─▶ OCR ─▶ Layout/table ─▶ Format detect ─▶ KIE ─▶ Validate ─▶ Review UI ─▶ Export
                                                                    ▲                      │
                                                                    └──── corrections ◀────┘  (learning loop)
```

| Stage | Tool (local, open-source) | Licence | Notes |
|-------|---------------------------|---------|-------|
| Preprocess | OpenCV, Pillow | BSD / HPND | deskew, denoise, rasterise |
| OCR | **RapidOCR** (PaddleOCR models as ONNX) | Apache-2.0 | pure `pip`, CPU, no system deps — the default |
| OCR (alt) | PaddleOCR + PP-Structure | Apache-2.0 | adds table structure; needs `paddlepaddle` |
| OCR (alt) | Tesseract 5 via `pytesseract` | Apache-2.0 | needs the tesseract binary |
| Layout / tables | PP-Structure, or `pymupdf` blocks for digital PDFs | Apache-2.0 / AGPL* | *PyMuPDF is AGPL — fine for internal server use; buy a commercial licence if you redistribute the binary |
| Format detection | fingerprint + FAISS / pgvector | MIT | nearest-neighbour on a layout signature |
| **KIE — Tier A** | label-anchor + geometry rules (this repo) | your code | **no training, works day 1** |
| **KIE — Tier B** | fine-tuned **LiLT** or **Donut** | **MIT** | trained on *your* corrected BLs |
| Validation | rules + UN/LOCODE list + ISO 6346 | your code / ODbL | check digits, weight sanity, date parsing |

> ⚠️ **Do not use LayoutLMv3 for a commercial product.** The code is MIT but the
> pre-trained weights are CC-BY-NC (non-commercial). LiLT and Donut have no such
> restriction.

---

## 2. The cold-start problem, and how the learning loop solves it

A trained KIE model needs labelled examples. You have none yet. Sequence:

1. **Weeks 0-N — Tier A carries production.** The label-anchor engine
   (`app/extraction/anchor_extractor.py`) extracts fields with no training. It is
   ~60-80% accurate on clean digital BLs, less on poor scans. Every field the
   user edits in the review screen is captured as a labelled example
   (`corrections` table): `{doc_id, format_id, field_key, ocr_context, bbox,
   ai_value, corrected_value}`.

2. **Immediate learning — per-format anchor rules.** On each correction, snapshot
   the geometry of the corrected value and its nearest label token, and store it
   as a rule keyed by `(format_id, field_key)`. The next BL of that format uses
   the rule first, at high confidence. This is the "it learned my layout"
   behaviour, and it needs no ML.

3. **Immediate learning — field-selection presets.** Store which fields the user
   ticked for export, keyed by `format_id` / organisation. Pure lookup; applied
   automatically next time.

4. **Weeks N+ — Tier B model.** Once ~200-500 corrected BLs exist, a scheduled
   job fine-tunes LiLT/Donut (LoRA — minutes on one GPU, cheap). Output goes to a
   model registry (MLflow). An **offline eval gate** compares the candidate
   against the current model on a held-out corrected set; it is promoted only if
   per-field F1 improves and no field regresses beyond a threshold.

5. **Steady state.** Tier B handles known formats; Tier A is the fallback for
   never-seen layouts and still feeds new training data. Accuracy climbs as a
   function of corrections, not of spend.

---

## 3. Production shape

```
                    ┌───────────────┐
   React + PDF.js ──▶│  FastAPI (N)  │  stateless, behind a load balancer
                    └──────┬────────┘
                           │ enqueue
                    ┌──────▼────────┐      ┌──────────────────────┐
                    │ Redis + queue │─────▶│  Extraction workers   │
                    └───────────────┘      │  (Celery / RQ)        │
                                           │  OCR + KIE + validate │
                                           └───────┬──────────────┘
        ┌──────────────┬───────────────────────────┼───────────────┐
   ┌────▼────┐   ┌─────▼──────┐            ┌────────▼───────┐  ┌────▼─────┐
   │ Postgres│   │ MinIO / S3 │            │ Inference svc  │  │ MLflow   │
   │ metadata│   │ files +    │            │ (Triton/Bento) │  │ registry │
   │ + pgvec │   │ model arts │            │ GPU, batched   │  │ + eval   │
   └─────────┘   └────────────┘            └────────────────┘  └──────────┘
```

- **Scale out** = add workers. OCR is CPU-parallel; the inference service batches
  on GPU for throughput.
- **GPU** = one spot node (L4 / T4) shared between OCR acceleration and the
  nightly LoRA training job. Optional at low volume — RapidOCR on CPU handles
  modest throughput.
- **Files** in object storage, **metadata** in Postgres, **model artifacts**
  versioned in the registry. Nothing on local disk in prod.
- **Fully offline / air-gapped capable** — no outbound calls.

### Cost sketch

| Tier | Setup | ~Monthly |
|------|-------|----------|
| Dev | 1 laptop, CPU, RapidOCR | $0 |
| Small prod | 2 CPU VMs + managed Postgres + object storage | ~$70-110 |
| Growth | + 1 GPU spot node (OCR throughput + training) | + ~$60-150 |

Marginal cost per BL ≈ compute only (well under 1¢). No API metering.

---

## 4. Data model (Step 2)

| Table | Purpose |
|-------|---------|
| `documents` | upload record: file ref, uploader, `format_id`, status |
| `field_catalog` | the canonical fields (mirrors `app/field_catalog.py`) |
| `extractions` | one row per `(doc_id, field_key)`: value, confidence, page, bbox, source |
| `corrections` | `ai_value` vs `corrected_value` + OCR context + geometry — the training signal |
| `format_profiles` | layout fingerprint, embedding, sample refs |
| `anchor_rules` | `(format_id, field_key)` → learned label + relative geometry + value regex |
| `export_templates` | owner → selected field keys, column order, output type |
| `model_versions` | registry pointer, eval scores, active flag |

---

## 5. Build roadmap

| Step | Scope | State |
|------|-------|-------|
| **1** | Local extraction core: canonical schema, OCR ingestion (digital + scanned), Tier A anchor engine, validators, CLI | ✅ done |
| 2 | FastAPI service + SQLite→Postgres storage; corrections capture | ⬜ next |
| 3 | React + PDF.js review/edit screen with bbox highlighting | ⬜ |
| 4 | Export to Excel / PDF + saved export templates | ⬜ |
| 5 | Learning loop v1: per-format `anchor_rules` from corrections + field-selection presets | ⬜ |
| 6 | Format detection (fingerprint + FAISS/pgvector) | ⬜ |
| 7 | Tier B: LiLT/Donut fine-tune job + MLflow registry + eval gate | ⬜ |
| 8 | Scale-out: queue, separate inference service, GPU node, Docker/compose | ⬜ |
