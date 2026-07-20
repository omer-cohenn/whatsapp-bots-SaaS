'use strict';

// לקוח ה-API הפנימי בבקאנד (M6b): רשימת שיחות, טעינת/שמירת creds מוצפנים, דיווח סטטוס.

// The gateway is DB-free and holds NO encryption key: it persists each business's
// Baileys auth state THROUGH the backend, which encrypts it with the crown KEK
// and stores it in whatsapp_credentials. Every call carries the shared
// X-Gateway-Token (the same secret the inbound webhook is checked against).
//
// Contract (see backend/app/api/internal_wa.py):
//   GET  /internal/wa/sessions              -> { sessions: ["<business_id>", ...] }
//   GET  /internal/wa/creds/{business_id}   -> { auth_state: "<base64>"|null, key_version: int|null }
//   PUT  /internal/wa/creds/{business_id}   body { auth_state: "<base64>" } -> { ok: true }
//   POST /internal/wa/status/{business_id}  body { status, phone, qr_data_url } -> { ok: true }
//   POST /internal/wa/media                 multipart -> { file_id, mime_type, size_bytes }

const { request, FormData } = require('undici');

const { loadConfig } = require('./config');
const { createLogger } = require('./logger');

const config = loadConfig();
const log = createLogger(config.logLevel);

const _base = config.backendBaseUrl.replace(/\/$/, '');
const _headers = {
  'content-type': 'application/json',
  'x-gateway-token': config.gatewayApiToken,
};
// Internal calls are same-network; fail fast rather than hang a session.
const _TIMEOUT = 8000;

async function _json(res) {
  try {
    return await res.body.json();
  } catch {
    // Drain so the socket is reusable even on a bad/empty body.
    await res.body.text().catch(() => {});
    return null;
  }
}

// GET the set of business ids that should currently have a live WhatsApp socket.
// Returns [] on any failure (the manager simply retries next poll).
async function listSessions() {
  try {
    const res = await request(`${_base}/internal/wa/sessions`, {
      method: 'GET',
      headers: _headers,
      headersTimeout: _TIMEOUT,
      bodyTimeout: _TIMEOUT,
    });
    const data = await _json(res);
    const arr = Array.isArray(data?.sessions) ? data.sessions : [];
    return arr.filter((id) => typeof id === 'string' && id);
  } catch (err) {
    log.error({ err: err.message }, 'internal: listSessions failed');
    return [];
  }
}

// GET a business's stored auth state. Returns { authState: <base64>|null } —
// null means "no creds yet" (the session will produce a fresh QR). Throws on a
// hard failure so the caller can decide (we do NOT want to silently start a
// session with empty creds if the backend is merely down).
async function loadCreds(businessId) {
  const res = await request(`${_base}/internal/wa/creds/${encodeURIComponent(businessId)}`, {
    method: 'GET',
    headers: _headers,
    headersTimeout: _TIMEOUT,
    bodyTimeout: _TIMEOUT,
  });
  if (res.statusCode >= 400) {
    await res.body.text().catch(() => {});
    throw new Error(`loadCreds ${res.statusCode}`);
  }
  const data = await _json(res);
  return { authState: data?.auth_state ?? null };
}

// PUT a business's updated auth state (base64). Best-effort: logs + returns false
// on failure so a save miss can't crash the socket (our Bad-MAC recovery covers
// the rare lost key). Never logs the blob.
async function saveCreds(businessId, authStateB64) {
  try {
    const res = await request(`${_base}/internal/wa/creds/${encodeURIComponent(businessId)}`, {
      method: 'PUT',
      headers: _headers,
      body: JSON.stringify({ auth_state: authStateB64 }),
      headersTimeout: _TIMEOUT,
      bodyTimeout: _TIMEOUT,
    });
    await res.body.text().catch(() => {});
    return res.statusCode < 400;
  } catch (err) {
    log.error({ err: err.message }, 'internal: saveCreds failed');
    return false;
  }
}

// POST a business's live status (+ QR while linking). Best-effort. Never logs the
// phone or QR. status: starting|qr_pending|connected|disconnected|logged_out.
// Returns the backend's parsed body ({ok, conflict}) or null on failure — the
// session checks `conflict` to enforce "one number = one business".
async function reportStatus(businessId, { status, phone = null, qrDataUrl = null }) {
  try {
    const res = await request(`${_base}/internal/wa/status/${encodeURIComponent(businessId)}`, {
      method: 'POST',
      headers: _headers,
      body: JSON.stringify({ status, phone, qr_data_url: qrDataUrl }),
      headersTimeout: _TIMEOUT,
      bodyTimeout: _TIMEOUT,
    });
    const data = await _json(res);
    return res.statusCode < 400 ? data : null;
  } catch (err) {
    log.error({ err: err.message }, 'internal: reportStatus failed');
    return null;
  }
}

// ── M16: upload ONE customer attachment to the backend ───────────────────────
// POST multipart/form-data /internal/wa/media. The backend is the ONLY place
// bytes are allowed to land: it re-checks the size (413), SNIFFS the real type
// from the content (415), envelope-encrypts the file and records the row.
//
// Idempotency: `message_id` is the key. Baileys re-emits the same message after
// a reconnect, and the backend answers a repeat with the EXISTING file_id — so
// retrying here can never create a second object or a second bill.
//
// Returns { file_id, mime_type, name } on success (mime_type is the SERVER's
// sniffed value — always prefer it over what we declared) or null on any
// failure, so the caller can tell the customer something went wrong instead of
// crashing the socket.
//
// NEVER logs: the bytes, the file name, the token. Only the status code, the
// declared mime type and the byte count.
async function uploadMedia(businessId, { bytes, mimeType, fileName, conversationId, messageId }) {
  // A longer budget than the JSON calls: this one carries up to 10 MiB and the
  // backend encrypts + PUTs to object storage before it answers.
  const MEDIA_TIMEOUT = 60000;
  try {
    const form = new FormData();
    form.set('business_id', String(businessId));
    if (conversationId) form.set('conversation_id', String(conversationId));
    if (messageId) form.set('message_id', String(messageId));
    if (mimeType) form.set('mime_type', String(mimeType));
    if (fileName) form.set('file_name', String(fileName));
    // The upload part's own filename is a fixed placeholder on purpose — the
    // REAL (PII) name travels in the `file_name` field, which the backend
    // sanitizes and stores encrypted.
    form.set(
      'file',
      new Blob([bytes], { type: mimeType || 'application/octet-stream' }),
      'upload.bin'
    );

    const res = await request(`${_base}/internal/wa/media`, {
      method: 'POST',
      // NOTE: no content-type here — undici derives the multipart boundary from
      // the FormData body. Sending _headers (application/json) would corrupt it.
      headers: { 'x-gateway-token': config.gatewayApiToken },
      body: form,
      headersTimeout: MEDIA_TIMEOUT,
      bodyTimeout: MEDIA_TIMEOUT,
    });

    if (res.statusCode >= 400) {
      await res.body.text().catch(() => {});
      log.error(
        { uploadStatus: res.statusCode, declaredMime: mimeType || null },
        'internal: uploadMedia rejected by backend'
      );
      return null;
    }

    const data = await _json(res);
    if (!data?.file_id) {
      log.error({ uploadStatus: res.statusCode }, 'internal: uploadMedia returned no file_id');
      return null;
    }
    log.info(
      { uploadStatus: res.statusCode, storedMime: data.mime_type, sizeBytes: data.size_bytes },
      'internal: media uploaded'
    );
    return {
      file_id: String(data.file_id),
      // Trust the SNIFFED type over the one we declared.
      mime_type: String(data.mime_type || mimeType || ''),
      name: fileName ? String(fileName) : '',
    };
  } catch (err) {
    log.error({ err: err.message }, 'internal: uploadMedia failed');
    return null;
  }
}

module.exports = { listSessions, loadCreds, saveCreds, reportStatus, uploadMedia };
