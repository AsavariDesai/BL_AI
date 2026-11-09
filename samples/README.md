# Sample BLs

Drop your Bill of Lading PDFs here to test the extractor, e.g.:

- `181142608002- SEAWAY BL.pdf`   (LMT / Lloyds Maritime seaway BL + rider sheet)
- `HBL-H680557 (1).pdf`            (AOF Cargo multimodal transport BL)
- `SCO38032C.pdf`                  (Liner BL, MV Scoter, break-bulk pipes)

Then from `backend/`:

```
python -m app.cli "../samples/181142608002- SEAWAY BL.pdf"
```
