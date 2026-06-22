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

/**
 * @param {object} msg Baileys WAMessage (from messages.upsert)
 * @param {string} gatewayAccountId fixed routing key (e.g. "spike")
 * @param {object} [opts]
 * @param {boolean} [opts.selfTest] true ONLY for self-chat messages
 * @param {string}  [opts.conversationId] the self-chat jid (stable per chat)
 */
function buildWebhookPayload(msg, gatewayAccountId, opts = {}) {
  const messageContent = msg.message || {};
  // The backend requires gateway_account_id / from / message_id / type to be
  // non-null STRINGS — always send strings (never null) to honor the contract (fixes the B1-class mismatch).
  const payload = {
    gateway_account_id: gatewayAccountId,
    from: jidToE164(msg.key?.remoteJid),
    push_name: msg.pushName || '',
    message_id: msg.key?.id || '',
    timestamp: Number(msg.messageTimestamp) || null,
    type: Object.keys(messageContent)[0] || 'unknown',
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

  return payload;
}

module.exports = { buildWebhookPayload, extractText };
