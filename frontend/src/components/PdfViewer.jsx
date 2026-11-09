import { useEffect, useRef, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl

// Render resolution (canvas px per PDF point). Display size is independent of
// this — pages are laid out relative to the panel width and the zoom control —
// so a high value just keeps the page crisp when zoomed in.
const RENDER_SCALE = 2
const ZOOM_MIN = 0.5
const ZOOM_MAX = 4
const ZOOM_STEP = 1.25

const clampZoom = (z) => Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z))

/**
 * Renders every page of the PDF stacked vertically, scaled to the panel width
 * times an internal zoom factor (so zooming the document never zooms the app).
 * When `selected` carries a page + bbox (PDF points, top-left origin) the
 * matching page gets a highlight rectangle — positioned as a percentage of the
 * page so it stays aligned at any zoom — and is scrolled into view.
 */
export default function PdfViewer({ fileUrl, selected }) {
  const containerRef = useRef(null)
  const [pages, setPages] = useState([])
  const [error, setError] = useState(null)
  const [zoom, setZoom] = useState(1)

  useEffect(() => {
    let cancelled = false
    setPages([])
    setError(null)
    setZoom(1)

    ;(async () => {
      try {
        // withCredentials so the session cookie rides along even when the
        // API is on a different origin (npm run dev talking to uvicorn) —
        // same-origin production deployments send it either way.
        const pdf = await pdfjsLib.getDocument({ url: fileUrl, withCredentials: true }).promise
        const rendered = []
        for (let n = 1; n <= pdf.numPages; n++) {
          const page = await pdf.getPage(n)
          const base = page.getViewport({ scale: 1 })
          const viewport = page.getViewport({ scale: RENDER_SCALE })
          const canvas = document.createElement('canvas')
          canvas.width = Math.ceil(viewport.width)
          canvas.height = Math.ceil(viewport.height)
          await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise
          if (cancelled) return
          rendered.push({
            num: n,
            dataUrl: canvas.toDataURL('image/png'),
            pw: base.width,
            ph: base.height,
          })
          setPages([...rendered])
        }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e))
      }
    })()

    return () => {
      cancelled = true
    }
  }, [fileUrl])

  useEffect(() => {
    if (!selected?.page) return
    const el = containerRef.current?.querySelector(`#pdfpage-${selected.page}`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [selected, pages.length])

  // Ctrl/⌘ + wheel zooms the document (like a native PDF viewer)
  function onWheel(e) {
    if (!(e.ctrlKey || e.metaKey)) return
    e.preventDefault()
    setZoom((z) => clampZoom(z * (e.deltaY < 0 ? 1.1 : 1 / 1.1)))
  }

  if (error) return <div className="pdfviewer error">Could not render PDF: {error}</div>

  return (
    <div className="pdfwrap">
      <div className="pdf-zoom" role="toolbar" aria-label="PDF zoom">
        <button
          className="zbtn"
          onClick={() => setZoom((z) => clampZoom(z / ZOOM_STEP))}
          disabled={zoom <= ZOOM_MIN + 0.001}
          title="Zoom out"
        >
          −
        </button>
        <button className="zval" onClick={() => setZoom(1)} title="Reset to fit width">
          {Math.round(zoom * 100)}%
        </button>
        <button
          className="zbtn"
          onClick={() => setZoom((z) => clampZoom(z * ZOOM_STEP))}
          disabled={zoom >= ZOOM_MAX - 0.001}
          title="Zoom in"
        >
          +
        </button>
      </div>

      <div className="pdfviewer" ref={containerRef} onWheel={onWheel}>
        {pages.length === 0 && <div className="muted pad">Rendering PDF…</div>}
        <div
          className="pdfpages"
          style={{ width: `${zoom * 100}%`, maxWidth: zoom === 1 ? 980 : 'none' }}
        >
          {pages.map((p) => {
            const hl =
              selected?.page === p.num && Array.isArray(selected.bbox)
                ? selected.bbox
                : null
            const pct = (n, span) => `${(n / span) * 100}%`
            return (
              <div
                className="pdfpage"
                id={`pdfpage-${p.num}`}
                key={p.num}
                style={{ aspectRatio: `${p.pw} / ${p.ph}` }}
              >
                <img src={p.dataUrl} alt={`page ${p.num}`} />
                {hl && (
                  <div
                    className="highlight"
                    style={{
                      left: pct(hl[0], p.pw),
                      top: pct(hl[1], p.ph),
                      width: pct(Math.max(4, hl[2] - hl[0]), p.pw),
                      height: pct(Math.max(4, hl[3] - hl[1]), p.ph),
                    }}
                  />
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
