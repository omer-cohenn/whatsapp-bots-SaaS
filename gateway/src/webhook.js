'use strict';

// וובהוק: העברת הודעה נכנסת לבקאנד + שליחת התשובות שחזרו חזרה לצ'אט.

const { request } = require('undici');

const { loadConfig } = require('./config');
const { createLogger } = require('./logger');

// Same config + logger instances used across the gateway (loadConfig is
// fail-closed and returns a frozen object; the level matches index.js).
const config = loadConfig();
const log = createLogger(config.logLevel);

// Loop-guard + live socket live in socket.js. We require it lazily-by-reference
// (CommonJS) and only TOUCH its exports inside function bodies — never at module
// load time — so the socket<->webhook require cycle resolves cleanly.
const socketModule = require('./socket');

// ── Forward one inbound message to the backend webhook ───────────────────────
// Returns the parsed backend response { status, replies: [...] } on success, or
// null on any failure. The contract: replies=[] when the bot is silent / not
// published / no mapping — so the caller just sends whatever replies come back.
async function forwardToBackend(payload) {
  try {
    const res = await request(config.backendWebhookUrl, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        // Header-only auth. The token value is NEVER logged (redacted + we only
        // ever log res.statusCode, never the headers object).
        'x-gateway-token': config.gatewayApiToken,
      },
      body: JSON.stringify(payload),
      headersTimeout: 8000,
      bodyTimeout: 8000,
    });

    // Read the JSON response body. The backend returns { status, replies[] }.
    // Be defensive: on non-JSON / parse failure, treat as no replies.
    let parsed = null;
    try {
      parsed = await res.body.json();
    } catch {
      // Drain so the socket can be reused / closed cleanly even on bad JSON.
      await res.body.text().catch(() => {});
    }

    // SAFE logging only: status + a truncated message id + whether text existed
    // + how many replies came back. No phone number, no message body (the reply
    // text is NEVER logged), no token, no QR.
    log.info(
      {
        webhookStatus: res.statusCode,
        messageIdSuffix: payload.message_id ? payload.message_id.slice(-6) : null,
        msgType: payload.type,
        hasText: Boolean(payload.text),
        selfTest: Boolean(payload.self_test),
        replyCount: Array.isArray(parsed?.replies) ? parsed.replies.length : 0,
      },
      'forwarded inbound message to backend'
    );

    return parsed;
  } catch (err) {
    // err.message from undici contains no secret/PII (connection-level error).
    log.error({ err: err.message }, 'failed to forward inbound message to backend');
    return null;
  }
}

// ── Send the bot's replies back into the self-chat ───────────────────────────
// Sends each reply IN ORDER and records the resulting message id in the loop
// guard so the echoed fromMe upsert does not re-trigger the bot. Wrapped so a
// single bad send can't take down the socket; logs are SAFE (no text/phone).
async function sendReplies(remoteJid, replies) {
  const sock = socketModule.getSock();
  if (!sock || !Array.isArray(replies) || replies.length === 0) return;
  for (const reply of replies) {
    const text = typeof reply === 'string' ? reply : '';
    if (!text.trim()) continue; // skip empty/blank replies
    try {
      const sent = await sock.sendMessage(remoteJid, { text });
      // Record the id of OUR outgoing message so its fromMe echo is ignored.
      socketModule.rememberSentId(sent?.key?.id);
      log.info({ textLen: text.length }, 'sent bot reply into self-chat');
    } catch (err) {
      // Never log the reply text or the jid (PII) — message only.
      log.error({ err: err.message }, 'failed to send bot reply');
    }
  }
}

module.exports = { forwardToBackend, sendReplies };
