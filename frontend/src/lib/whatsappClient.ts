// Typed wrappers around the three M6a WhatsApp admin endpoints.
//
// Everything goes through `api` (src/lib/apiClient.ts), which sends the session
// cookie same-origin with `credentials: 'include'`. The tenant (business_id) is
// derived entirely from that server session — we NEVER send it from the client,
// and the client never sees the gateway token or any WhatsApp credentials.

import { api } from './apiClient'

/**
 * Coarse connection state of the business's WhatsApp account, mirroring the
 * gateway's own status string. The UI maps these to its three real states:
 *   - connected      → linked + the gateway socket is up (show "מחובר" + phone)
 *   - qr_pending     → a QR is ready to scan (show the QR image)
 *   - disconnected   → nothing linked / socket down (offer QR + link)
 */
export type GatewayStatus =
  | 'connected'
  | 'qr_pending'
  | 'disconnected'
  | string // tolerate any extra gateway-supplied value without a type break

/** Shape returned by GET /api/whatsapp/status and POST /api/whatsapp/link. */
export type WhatsAppStatus = {
  /** Has this business recorded a mapping (business_id ↔ gateway account)? */
  linked: boolean
  /** Is the gateway socket currently up for that account? */
  connected: boolean
  /** The linked own-number digits, or null when not connected. */
  phone: string | null
  /** Raw gateway status string (connected | qr_pending | disconnected | …). */
  gateway_status: GatewayStatus
}

/** Shape returned by GET /api/whatsapp/qr. */
export type WhatsAppQr = {
  /** Gateway status string at the time the QR was fetched. */
  status: GatewayStatus
  /** A data: URL for the QR image, or null when there is nothing to scan. */
  qr_data_url: string | null
}

/**
 * GET /api/whatsapp/status — the current link/connection state for the
 * session's business. Polled while the page is open.
 */
export function getStatus(): Promise<WhatsAppStatus> {
  return api.get<WhatsAppStatus>('/api/whatsapp/status')
}

/**
 * POST /api/whatsapp/link — record the mapping (business_id ↔ gateway account +
 * phone) once the gateway reports a connected own-number. Returns the refreshed
 * status shape. No body: the gateway account + phone are resolved server-side.
 */
export function link(): Promise<WhatsAppStatus> {
  return api.post<WhatsAppStatus>('/api/whatsapp/link')
}

/**
 * GET /api/whatsapp/qr — proxy the gateway's current QR (a data: URL) so the
 * owner can scan it to connect their WhatsApp. null once connected.
 */
export function getQr(): Promise<WhatsAppQr> {
  return api.get<WhatsAppQr>('/api/whatsapp/qr')
}
