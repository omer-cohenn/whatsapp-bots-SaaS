'use strict';

/**
 * The FROZEN gateway -> backend webhook contract mapping.
 *
 * Kept in its own module so it can be unit-tested and reused, and so the wire
 * shape lives in exactly one place. Body shape (do not change without updating
 * the backend + the shared spec):
 *   { gateway_account_id, from, push_name, message_id, timestamp, type, text, raw }
 *
 * M6a (decision 0014) adds:
 *   conversation_id: string -> ALWAYS sent (the chat jid, stable per chat) so
 *                              both self-chat AND external test-number inbound
 *                              carry a stable conversation key for run_turn.
 *   self_test: bool        -> attached ONLY for the owner's self-chat messages,
 *                              so the backend keeps the owner-always-allowed gate
 *                              distinct from the external-number allowlist gate.
 *
 * M16 (customer file uploads) adds:
 *   media: { file_id, mime_type, name }
 *                          -> attached ONLY after the gateway has downloaded the
 *                             attachment AND stored it via POST /internal/wa/media.
 *                             `file_id` + `mime_type` are the SERVER's values (the
 *                             mime is sniffed from the bytes, never the sender's
 *                             declared type). It carries NO bytes. Absent on every
 *                             text-only message, so the existing shape is untouched.
 */

// ── message-wrapper unwrapping ───────────────────────────────────────────────
// WhatsApp nests the real content inside a wrapper for disappearing messages and
// view-once media; `documentWithCaptionMessage` wraps a plain documentMessage so
// it can carry a caption. Before M16 we read `Object.keys(msg.message)[0]` and
// the caption straight off the OUTER object, so every wrapped message reported
// type "ephemeralMessage" and lost its text. Unwrapping fixes both.
const WRAPPER_KEYS = new Set([
  'ephemeralMessage',
  'viewOnceMessage',
  'viewOnceMessageV2',
  'viewOnceMessageV2Extension',
  'documentWithCaptionMessage',
]);

// Keys that ride ALONG with real content and must never be mistaken for the
// message type (they are metadata, and they often sort first).
const META_KEYS = new Set(['messageContextInfo', 'senderKeyDistributionMessage']);

/**
 * Peel the wrappers off a Baileys message content object.
 * Bounded loop (never trusts remote nesting depth to terminate).
 * @param {object} message msg.message
 * @returns {object} the innermost real content object
 */
function unwrapMessage(message) {
  let current = message && typeof message === 'object' ? message : {};
  for (let i = 0; i < 5; i += 1) {
    const key = Object.keys(current).find((k) => WRAPPER_KEYS.has(k));
    if (!key) break;
    const inner = current[key]?.message;
    if (!inner || typeof inner !== 'object') break;
    current = inner;
  }
  return current;
}

/** The wire `type` for a message: the first REAL content key, unwrapped. */
function messageType(message) {
  const content = unwrapMessage(message);
  const key = Object.keys(content).find((k) => !META_KEYS.has(k));
  return key || 'unknown';
}

function extractText(message) {
  if (!message) return '';
  const content = unwrapMessage(message);
  return (
    content.conversation ||
    content.extendedTextMessage?.text ||
    content.imageMessage?.caption ||
    content.videoMessage?.caption ||
    content.documentMessage?.caption ||
    ''
  );
}

// ── media detection + the PRE-DOWNLOAD guard (M16) ───────────────────────────

// Mirrors backend/app/services/file_storage.py MAX_FILE_BYTES (10 MiB). Kept in
// lockstep by hand: exceeding it here means the backend would 413 anyway, so we
// refuse BEFORE spending bandwidth and memory on a download we cannot use.
const MAX_MEDIA_BYTES = 10 * 1024 * 1024;

// Mirrors backend/app/services/file_storage.py ALLOWED_MIME. The backend re-checks
// by SNIFFING the bytes; this list is only the cheap pre-download filter.
const ALLOWED_MEDIA_MIME = new Set([
  'image/jpeg',
  'image/png',
  'image/webp',
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.ms-powerpoint',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
]);

/**
 * Find the media node on an (already unwrappable) message.
 * @returns {{ node: object, type: string } | null}
 */
function extractMedia(message) {
  const content = unwrapMessage(message);
  if (content.imageMessage) return { node: content.imageMessage, type: 'imageMessage' };
  if (content.documentMessage) return { node: content.documentMessage, type: 'documentMessage' };
  return null;
}

/** Normalize Baileys' `fileLength` (number | string | protobuf Long) to a Number. */
function mediaSize(node) {
  const raw = node?.fileLength;
  if (raw == null) return 0;
  if (typeof raw === 'number') return raw;
  if (typeof raw === 'string') return Number(raw) || 0;
  if (typeof raw.toNumber === 'function') {
    try {
      return raw.toNumber();
    } catch {
      return 0;
    }
  }
  return Number(raw) || 0;
}

/** The declared mime type, lower-cased and stripped of any `; charset=` suffix. */
function mediaMime(node) {
  return String(node?.mimetype || '').split(';')[0].trim().toLowerCase();
}

// Customer-facing refusals (Hebrew). Deliberately vague about the limit's origin
// and never echo the file name back.
const MEDIA_TOO_BIG_MSG = 'הקובץ גדול מדי 😕 אפשר לשלוח קובץ עד 10MB.';
const MEDIA_BAD_TYPE_MSG =
  'סוג הקובץ הזה לא נתמך 😕 אפשר לשלוח תמונה, PDF, מסמך Word או מצגת.';
const MEDIA_FAILED_MSG = 'לא הצלחתי לקבל את הקובץ 😕 אפשר לנסות לשלוח אותו שוב?';

/**
 * The PRE-DOWNLOAD guard: decide from the METADATA alone whether this attachment
 * is worth downloading. Reading `fileLength`/`mimetype` off the message node is
 * free; downloading a 90 MB video only to throw it away is not.
 * @returns {{ ok: true } | { ok: false, reason: string }} reason = Hebrew reply
 */
function checkMediaAllowed(node) {
  const size = mediaSize(node);
  if (size > MAX_MEDIA_BYTES) return { ok: false, reason: MEDIA_TOO_BIG_MSG };
  if (!ALLOWED_MEDIA_MIME.has(mediaMime(node))) {
    return { ok: false, reason: MEDIA_BAD_TYPE_MSG };
  }
  return { ok: true };
}

/**
 * Map a Baileys message object -> the frozen webhook payload.
 * @param {object} msg Baileys WAMessage (from messages.upsert)
 * @param {string} gatewayAccountId fixed routing key (e.g. "spike")
 */
/**
 * Normalize a WhatsApp JID to E.164, e.g. "972501234567@s.whatsapp.net" -> "+972501234567".
 * Returns '' when absent — the backend requires `from` to be a non-null string.
 */
function jidToE164(jid) {
  if (!jid) return '';
  const user = String(jid).split('@')[0].split(':')[0].replace(/[^0-9]/g, '');
  return user ? `+${user}` : '';
}

/**
 * @param {object} msg Baileys WAMessage (from messages.upsert)
 * @param {string} gatewayAccountId fixed routing key (e.g. "spike")
 * @param {object} [opts]
 * @param {boolean} [opts.selfTest] true ONLY for self-chat messages
 * @param {string}  [opts.conversationId] the self-chat jid (stable per chat)
 * @param {object}  [opts.media] {file_id, mime_type, name} — set ONLY after the
 *                  attachment was successfully uploaded to the backend (M16).
 */
function buildWebhookPayload(msg, gatewayAccountId, opts = {}) {
  const messageContent = msg.message || {};
  // The backend requires gateway_account_id / from / message_id / type to be
  // non-null STRINGS — always send strings (never null) to honor the contract (fixes the B1-class mismatch).
  // LID → phone resolution (the real customer identity). Modern WhatsApp
  // addresses 1:1 chats by a hidden "@lid" id, so msg.key.remoteJid is often a
  // LID, NOT the phone number. Baileys (6.7.x) also puts the sender's REAL
  // phone-number jid on the key as `senderPn` (e.g. "972508648315@s.whatsapp.net").
  // We must report `from` as the phone so the backend's test-number allow-list
  // (and, later, real per-customer routing) can match it. Prefer senderPn; fall
  // back to remoteJid for plain @s.whatsapp.net chats where no LID is involved.
  // conversation_id below stays the remoteJid (the stable chat key replies route to).
  const payload = {
    gateway_account_id: gatewayAccountId,
    from: jidToE164(msg.key?.senderPn || msg.key?.remoteJid),
    push_name: msg.pushName || '',
    message_id: msg.key?.id || '',
    timestamp: Number(msg.messageTimestamp) || null,
    // `type` + `text` are derived from the UNWRAPPED content (M16), so a
    // disappearing / view-once / captioned-document message reports its REAL
    // type ("imageMessage") instead of the wrapper's ("ephemeralMessage").
    type: messageType(messageContent),
    text: extractText(messageContent),
    raw: msg,
  };

  // conversation_id is ALWAYS sent (a stable per-chat key) so non-self inbound
  // also carries a conversation key for run_turn. Falls back to the remoteJid.
  payload.conversation_id = opts.conversationId || msg.key?.remoteJid || '';

  // self_test marks ONLY the owner's "Message Yourself" path. It is attached
  // exclusively for the self-chat so the backend can keep the owner-always-allowed
  // gate distinct from the allowlist gate used for external test numbers.
  if (opts.selfTest) {
    payload.self_test = true;
  }

  // media is ADDED (never replaces an existing field) and only when a file was
  // actually stored. `text` stays the caption when the sender wrote one, so a
  // captioned photo delivers BOTH the caption and the file reference.
  if (opts.media && opts.media.file_id) {
    payload.media = {
      file_id: opts.media.file_id,
      mime_type: opts.media.mime_type || '',
      name: opts.media.name || '',
    };
  }

  return payload;
}

module.exports = {
  buildWebhookPayload,
  extractText,
  unwrapMessage,
  messageType,
  extractMedia,
  checkMediaAllowed,
  mediaMime,
  mediaSize,
  MAX_MEDIA_BYTES,
  ALLOWED_MEDIA_MIME,
  MEDIA_TOO_BIG_MSG,
  MEDIA_BAD_TYPE_MSG,
  MEDIA_FAILED_MSG,
};
