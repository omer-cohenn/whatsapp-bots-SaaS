// Typed wrappers around the M20 OWNER endpoints for the business page: the page
// settings (text, links, theme) and the image gallery. Mirrors
// `docs/spec/business-page-contract.md` — that document is authoritative.
//
// Everything here is session-gated and same-origin, so the tenant (business_id)
// is derived entirely from the server session. We NEVER send it from the client.
//
// Two deliberate departures from `lib/apiClient.ts`:
//   1. the upload is multipart, so it must NOT get a JSON Content-Type header;
//   2. it uses XMLHttpRequest, because that is the only way to get real upload
//      progress — a 5MB photo on a phone is not instant and the owner needs to
//      see that something is happening.
// Both still throw `ApiError`, so `toFriendlyError` keeps working unchanged.

import { api, ApiError } from './apiClient'
import { toFriendlyError } from './friendlyError'
import type {
  BusinessImage,
  BusinessPage,
  BusinessPageUpdate,
} from '../dashboard/businessPageTypes'

/** Uploads get a far longer budget than the 8s the JSON client uses. */
const UPLOAD_TIMEOUT_MS = 120_000

// --- page settings -----------------------------------------------------------

/**
 * GET /api/booking/page — the owner's page settings + the whole gallery.
 * The first call creates the row and the slug, so this never 404s for a
 * logged-in owner.
 */
export function getBusinessPage(): Promise<BusinessPage> {
  return api.get<BusinessPage>('/api/booking/page')
}

/**
 * PUT /api/booking/page — PARTIAL update. Read this before calling it:
 *
 *   key omitted  → the column is left alone
 *   key = null   → the column is CLEARED
 *   key = ''     → normalised to null (also clears)
 *
 * Clearing is the only way to remove a hero button, so callers must build the
 * body from what actually changed. Never spread a whole `BusinessPage` in here
 * or you will rewrite fields the owner never touched.
 *
 * The response is the full page (gallery included), so the screen can be
 * refreshed straight from it with no extra GET.
 */
export function updateBusinessPage(body: BusinessPageUpdate): Promise<BusinessPage> {
  return api.put<BusinessPage>('/api/booking/page', body)
}

// --- logo --------------------------------------------------------------------

/**
 * POST /api/booking/logo — multipart upload of the round hero logo.
 *
 * `logo_url` used to be a text box the owner pasted a URL into, which quietly
 * assumed they host an image somewhere. They don't. This uploads the file the
 * same way a gallery photo goes up and the server writes the resulting
 * `/media/...` path into `logo_url` itself.
 *
 * It is NOT a gallery row, so it does not count against the 40-image cap and it
 * never appears in the mosaic. Resolves with the WHOLE page object, so the
 * caller refreshes its screen straight from the response with no extra GET.
 */
export function uploadBusinessLogo(
  file: File,
  opts: { onProgress?: (fraction: number) => void } = {},
): Promise<BusinessPage> {
  const form = new FormData()
  form.append('file', file)

  return new Promise<BusinessPage>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/booking/logo')
    // Same-origin, so the HttpOnly session cookie rides along; we never read it.
    xhr.withCredentials = true
    xhr.timeout = UPLOAD_TIMEOUT_MS
    xhr.setRequestHeader('Accept', 'application/json')
    // No Content-Type header on purpose — the browser must set the multipart
    // boundary itself, and overriding it breaks the parse server-side.

    if (opts.onProgress) {
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && ev.total > 0) opts.onProgress?.(ev.loaded / ev.total)
      }
    }

    xhr.onload = () => {
      let body: unknown = null
      try {
        body = JSON.parse(xhr.responseText) as unknown
      } catch {
        body = null
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as BusinessPage)
      } else {
        reject(new ApiError(xhr.status, `HTTP ${xhr.status}`, body))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, 'unreachable', null))
    xhr.ontimeout = () => reject(new ApiError(0, 'timeout', null))
    xhr.onabort = () => reject(new ApiError(0, 'aborted', null))

    xhr.send(form)
  })
}

// --- gallery images ----------------------------------------------------------

/**
 * POST /api/booking/images — multipart upload; resolves with the created row.
 * The new image always lands at the END of the gallery (the server assigns
 * `max(sort_order)+1`); ordering is done afterwards with PATCH.
 *
 * `onProgress` is called with 0..1 while the bytes are going up.
 * Rejects with `ApiError` — 415 wrong type, 413 too big, 422 cap/empty file.
 */
export function uploadBusinessImage(
  file: File,
  opts: { caption?: string; onProgress?: (fraction: number) => void } = {},
): Promise<BusinessImage> {
  const form = new FormData()
  form.append('file', file)
  if (opts.caption) form.append('caption', opts.caption)

  return new Promise<BusinessImage>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/booking/images')
    // Same-origin, so the HttpOnly session cookie rides along; we never read it.
    xhr.withCredentials = true
    xhr.timeout = UPLOAD_TIMEOUT_MS
    xhr.setRequestHeader('Accept', 'application/json')
    // No Content-Type header on purpose: the browser must set the multipart
    // boundary itself, and overriding it breaks the parse server-side.

    if (opts.onProgress) {
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && ev.total > 0) opts.onProgress?.(ev.loaded / ev.total)
      }
    }

    xhr.onload = () => {
      let body: unknown = null
      try {
        body = JSON.parse(xhr.responseText) as unknown
      } catch {
        body = null
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as BusinessImage)
      } else {
        reject(new ApiError(xhr.status, `HTTP ${xhr.status}`, body))
      }
    }
    // Status 0 = never reached the server (same convention as apiClient).
    xhr.onerror = () => reject(new ApiError(0, 'unreachable', null))
    xhr.ontimeout = () => reject(new ApiError(0, 'timeout', null))
    xhr.onabort = () => reject(new ApiError(0, 'aborted', null))

    xhr.send(form)
  })
}

/**
 * PATCH /api/booking/images/{id} — caption and/or sort_order.
 * Same omitted-vs-null rule as the page PUT: an omitted `caption` is left
 * alone, `caption: null` deletes it.
 *
 * For reordering, give every moved image its own UNIQUE sort_order — two images
 * sharing one value fall back to created_at and the reorder looks like it never
 * took.
 */
export function updateBusinessImage(
  id: string,
  body: { caption?: string | null; sort_order?: number },
): Promise<BusinessImage> {
  return api.patch<BusinessImage>(
    `/api/booking/images/${encodeURIComponent(id)}`,
    body,
  )
}

/** DELETE /api/booking/images/{id} — 204, and the file leaves the disk too. Irreversible. */
export function deleteBusinessImage(id: string): Promise<void> {
  return api.delete<void>(`/api/booking/images/${encodeURIComponent(id)}`)
}

// --- errors ------------------------------------------------------------------

/**
 * Friendly Hebrew for the upload-specific failures. The server's `detail` for
 * 413/415/422 is already written for the owner's eyes and never echoes anything
 * the client sent (no filename, no caption), so it is safe to show verbatim —
 * see §6 of the contract. Anything else falls through to the shared helper.
 */
export function toUploadError(err: unknown, fallback: string): string {
  if (err instanceof ApiError && (err.status === 413 || err.status === 415 || err.status === 422)) {
    const detail = (err.body as { detail?: unknown } | null)?.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (err.status === 413) return 'התמונה גדולה מדי (עד 5MB לתמונה).'
    if (err.status === 415) return 'אפשר להעלות רק תמונות מסוג JPG, PNG או WEBP.'
    return 'אפשר להעלות עד 40 תמונות. מחקו תמונה קיימת כדי להוסיף חדשה.'
  }
  return toFriendlyError(err, fallback)
}
