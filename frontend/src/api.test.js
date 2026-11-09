import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './api'

beforeEach(() => {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) }),
  )
})
afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('upload() posts multipart form data to /documents with doc_type', async () => {
    await api.upload(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), {
      docType: 'shipping_bill',
      parentId: 'sb1',
    })
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/documents$/)
    expect(opts.method).toBe('POST')
    expect(opts.body).toBeInstanceOf(FormData)
    expect(opts.body.get('doc_type')).toBe('shipping_bill')
    expect(opts.body.get('parent_id')).toBe('sb1')
  })

  it('ingest() posts to /ingest with optional doc_type + parent_id', async () => {
    await api.ingest(new Blob(['%PDF']), { parentId: 'sb9' })
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/ingest$/)
    expect(opts.body).toBeInstanceOf(FormData)
    expect(opts.body.get('parent_id')).toBe('sb9')
    expect(opts.body.get('doc_type')).toBeNull()
  })

  it('exportHierarchy() hits the shipping-bill export endpoint', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      blob: () => Promise.resolve(new Blob()),
      headers: { get: () => 'attachment; filename="shipping_bill_5778867.xlsx"' },
    })
    const { filename } = await api.exportHierarchy('sb1', { fmt: 'xlsx', blFields: ['bl_number'] })
    const [url] = fetch.mock.calls[0]
    expect(url).toContain('/shipping-bills/sb1/export?')
    expect(url).toContain('bl_fields=bl_number')
    expect(filename).toBe('shipping_bill_5778867.xlsx')
  })

  it('linkShippingBills() posts one or more files to the BL-first link endpoint', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ ok: true }),
      headers: { get: () => null },
    })
    await api.linkShippingBills('bl1', [new Blob(['%PDF']), new Blob(['%PDF2'])], { background: false })
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/documents\/bl1\/link-shipping-bill$/)
    expect(opts.method).toBe('POST')
    expect(opts.body).toBeInstanceOf(FormData)
    expect(opts.body.getAll('files')).toHaveLength(2)
    expect(opts.body.get('background')).toBe('false')
  })

  it('linkShippingBills() surfaces per-file failures from the X-Failed-Files header', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ id: 'bl1', linked_shipping_bills: [] }),
      headers: { get: (name) => (name === 'X-Failed-Files' ? 'bad.pdf,worse.pdf' : null) },
    })
    const data = await api.linkShippingBills('bl1', [new Blob(['%PDF'])])
    expect(data._failedFiles).toEqual(['bad.pdf', 'worse.pdf'])
  })

  it('exportBlWithSb() hits the BL+SB combined export endpoint', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      blob: () => Promise.resolve(new Blob()),
      headers: { get: () => 'attachment; filename="bl_sb_LNK001.xlsx"' },
    })
    const { filename } = await api.exportBlWithSb('bl1', { fmt: 'xlsx' })
    const [url] = fetch.mock.calls[0]
    expect(url).toContain('/documents/bl1/export-with-sb?fmt=xlsx')
    expect(filename).toBe('bl_sb_LNK001.xlsx')
  })

  it('linkBls() posts doc_ids to the shipping-bill link endpoint', async () => {
    await api.linkBls('sb1', ['a', 'b'])
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/shipping-bills\/sb1\/link$/)
    expect(opts.method).toBe('POST')
    expect(JSON.parse(opts.body)).toEqual({ doc_ids: ['a', 'b'] })
  })

  it('hierarchy() GETs /hierarchy', async () => {
    await api.hierarchy()
    expect(fetch.mock.calls[0][0]).toMatch(/\/hierarchy$/)
  })

  it('records() hits /uploads or /records by source', async () => {
    await api.records({ q: 'abc' }, 'uploads')
    expect(fetch.mock.calls[0][0]).toContain('/uploads?')
    expect(fetch.mock.calls[0][0]).toContain('q=abc')
    await api.records({}, 'records')
    expect(fetch.mock.calls[1][0]).toContain('/records?')
  })

  it('submitRecords() POSTs doc_ids to /records/submit', async () => {
    await api.submitRecords(['a', 'b'])
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/records\/submit$/)
    expect(JSON.parse(opts.body)).toEqual({ doc_ids: ['a', 'b'] })
  })

  it('extract() posts to /documents/:id/extract', async () => {
    await api.extract('abc123')
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/documents\/abc123\/extract$/)
    expect(opts.method).toBe('POST')
  })

  it('saveFields() PUTs JSON body to /documents/:id/fields', async () => {
    await api.saveFields('abc123', [{ key: 'bl_number', value: '42' }])
    const [url, opts] = fetch.mock.calls[0]
    expect(url).toMatch(/\/documents\/abc123\/fields$/)
    expect(opts.method).toBe('PUT')
    expect(opts.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(opts.body)).toEqual({ fields: [{ key: 'bl_number', value: '42' }] })
  })

  it('fileUrl() builds the PDF url', () => {
    expect(api.fileUrl('abc123')).toMatch(/\/documents\/abc123\/file$/)
  })

  it('exportDoc() requests the chosen format + fields and reads the filename', async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      blob: () => Promise.resolve(new Blob(['x'])),
      headers: { get: () => 'attachment; filename="bl_abc123_2026-09-07.xlsx"' },
    })
    const { filename } = await api.exportDoc('abc123', {
      fmt: 'xlsx',
      fields: ['bl_number', 'shipper'],
    })
    const [url] = fetch.mock.calls[0]
    expect(url).toContain('/documents/abc123/export?')
    expect(url).toContain('fmt=xlsx')
    expect(url).toContain('fields=bl_number%2Cshipper')
    expect(filename).toBe('bl_abc123_2026-09-07.xlsx')
  })

  it('throws on a non-ok response', async () => {
    fetch.mockResolvedValueOnce({ ok: false, status: 404, statusText: 'Not Found', text: () => Promise.resolve('nope') })
    await expect(api.getDoc('missing')).rejects.toThrow('nope')
  })
})
