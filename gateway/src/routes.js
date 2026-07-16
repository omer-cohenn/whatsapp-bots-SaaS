'use strict';

// ראוטים (M6b): /healthz + /send-bot בלבד. הנתיבים הישנים /qr /inbox /send /info
// /qr.json הוסרו — ה-QR והסטטוס מדווחים לבקאנד פר-עסק, והדבאג-נתיבים היו ללא auth.

const crypto = require('crypto');

const { loadConfig } = require('./config');
const { createLogger } = require('./logger');
const { getSession, sessionCount } = require('./manager');

const config = loadConfig();
const log = createLogger(config.logLevel);

// ── Constant-time gateway-token check (backend -> gateway auth) ──────────────
function gatewayTokenValid(provided) {
  if (typeof provided !== 'string' || provided.length === 0) return false;
  const a = crypto.createHash('sha256').update(provided).digest();
  const b = crypto.createHash('sha256').update(config.gatewayApiToken).digest();
  return crypto.timingSafeEqual(a, b);
}

function registerRoutes(app) {
  // Health: 200, no secret. Used by the docker-compose healthcheck.
  app.get('/healthz', (_req, res) => {
    res.status(200).json({ ok: true, service: 'gateway', sessions: sessionCount() });
  });

  /*
   * POST /send-bot — INTERNAL (backend -> gateway). Delivers an owner's manual
   * reply / a system message to a customer over WhatsApp, on the CORRECT
   * business's socket (M6b: multi-session, so the business must be named).
   *
   *   header: X-Gateway-Token (REQUIRED, constant-time)
   *   body:   { business_id, to, text }
   *   -> 401 bad/missing token · 400 missing field · 503 that business has no
   *      live/connected session · 200 { ok:true, message_id } on success.
   * SAFE logging only: never log business_id-as-PII (it's not), `to`, `text`, token.
   */
  app.post('/send-bot', async (req, res) => {
    if (!gatewayTokenValid(req.get('x-gateway-token'))) {
      return res.status(401).json({ ok: false, error: 'unauthorized' });
    }
    const businessId = typeof req.body?.business_id === 'string' ? req.body.business_id.trim() : '';
    const to = typeof req.body?.to === 'string' ? req.body.to.trim() : '';
    const text = typeof req.body?.text === 'string' ? req.body.text : '';
    if (!businessId || !to || !text.trim()) {
      return res.status(400).json({ ok: false, error: 'missing business_id, to or text' });
    }

    const session = getSession(businessId);
    if (!session || session.getState().status !== 'connected') {
      return res.status(503).json({ ok: false, error: 'not connected' });
    }

    try {
      const messageId = await session.sendText(to, text);
      log.info({ textLen: text.length, hasMessageId: Boolean(messageId) }, 'sent reply via /send-bot');
      return res.status(200).json({ ok: true, message_id: messageId });
    } catch (err) {
      log.error({ err: err.message }, 'failed to send reply via /send-bot');
      return res.status(500).json({ ok: false, error: 'send failed' });
    }
  });
}

module.exports = { registerRoutes, gatewayTokenValid };
