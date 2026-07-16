'use strict';

// וובהוק: העברת הודעה נכנסת לבקאנד. (שליחת התשובות עברה ל-session.js, פר-עסק.)

const { request } = require('undici');

const { loadConfig } = require('./config');
const { createLogger } = require('./logger');

const config = loadConfig();
const log = createLogger(config.logLevel);

// ── Forward one inbound message to the backend webhook ───────────────────────
// Returns the parsed backend response { status, replies: [...] } on success, or
// null on any failure. replies=[] means the bot is silent — the caller just sends
// back whatever replies come. NEVER logs the phone / message text / token.
async function forwardToBackend(payload) {
  try {
    const res = await request(config.backendWebhookUrl, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-gateway-token': config.gatewayApiToken,
      },
      body: JSON.stringify(payload),
      headersTimeout: 8000,
      bodyTimeout: 8000,
    });

    let parsed = null;
    try {
      parsed = await res.body.json();
    } catch {
      await res.body.text().catch(() => {});
    }

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
    log.error({ err: err.message }, 'failed to forward inbound message to backend');
    return null;
  }
}

module.exports = { forwardToBackend };
