'use strict';

/**
 * The FROZEN gateway -> backend webhook contract mapping.
 *
 * Kept in its own module so it can be unit-tested and reused, and so the wire
 * shape lives in exactly one place. Body shape (do not change without updating
 * the backend + the shared spec):
 *   { gateway_account_id, from, push_name, message_id, timestamp, type, text, raw }
 */

function extractText(message) {
  if (!message) return '';
  return (
    message.conversation ||
    message.extendedTextMessage?.text ||
    message.imageMessage?.caption ||
    message.videoMessage?.caption ||
    ''
  );
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

function buildWebhookPayload(msg, gatewayAccountId) {
  const messageContent = msg.message || {};
  // The backend requires gateway_account_id / from / message_id / type to be
  // non-null STRINGS — always send strings (never null) to honor the contract (fixes the B1-class mismatch).
  return {
    gateway_account_id: gatewayAccountId,
    from: jidToE164(msg.key?.remoteJid),
    push_name: msg.pushName || '',
    message_id: msg.key?.id || '',
    timestamp: Number(msg.messageTimestamp) || null,
    type: Object.keys(messageContent)[0] || 'unknown',
    text: extractText(messageContent),
    raw: msg,
  };
}

module.exports = { buildWebhookPayload, extractText };
