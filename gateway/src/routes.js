'use strict';

// ראוטים: /healthz /info /qr /qr.json /send-bot /inbox /send + עוזרי טוקן/escape.

const crypto = require('crypto');
const express = require('express');

const { loadConfig } = require('./config');
const { createLogger } = require('./logger');
const socketModule = require('./socket');

const config = loadConfig();
const log = createLogger(config.logLevel);

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]),
  );
}

// ── Constant-time gateway-token check (internal backend -> gateway auth) ──────
// The backend calls our internal POST /send-bot with header X-Gateway-Token.
// Compare it to config.gatewayApiToken in CONSTANT TIME so we never leak token
// length / content via timing. crypto.timingSafeEqual throws on a length
// mismatch, so we hash BOTH sides to fixed-length digests first (the hash also
// makes the compare itself length-independent). The token is NEVER logged.
function gatewayTokenValid(provided) {
  if (typeof provided !== 'string' || provided.length === 0) return false;
  const a = crypto.createHash('sha256').update(provided).digest();
  const b = crypto.createHash('sha256').update(config.gatewayApiToken).digest();
  // Both are 32-byte buffers -> safe to compare directly.
  return crypto.timingSafeEqual(a, b);
}

/**
 * Register every HTTP route on the given express app. Reads live gateway state
 * (status / QR / own-jid / recent messages / socket) from socket.js at request
 * time, so the routes always see the current connection.
 */
function registerRoutes(app) {
  const { state, recentMessages } = socketModule;

  // Health: 200, NO QR / NO secret. Used by the docker-compose healthcheck.
  app.get('/healthz', (_req, res) => {
    res.status(200).json({ ok: true, service: 'gateway', status: state.status });
  });

  /*
   * GET /info — INTERNAL (backend -> gateway, Docker network). M6a contract:
   *   { account_id: <config account id>, status: <state.status>, phone: <digits|null> }
   * phone = the linked OWN number digits (E.164 without '+'), or null when not
   * connected. This is the gateway-side identity the backend uses to record /
   * verify the whatsapp_connections mapping. Not exposed publicly (internal net).
   */
  app.get('/info', (_req, res) => {
    res.set('Cache-Control', 'no-store');
    // Derive own-number digits from ownJid (e.g. "972501234567@s.whatsapp.net").
    // null when not connected (ownJid is cleared on disconnect).
    let phone = null;
    const ownJid = socketModule.getOwnJid();
    if (ownJid) {
      const digits = String(ownJid).split('@')[0].split(':')[0].replace(/[^0-9]/g, '');
      phone = digits || null;
    }
    res.status(200).json({
      account_id: config.gatewayAccountId,
      status: state.status,
      phone,
    });
  });

  /*
   * GET /qr.json — INTERNAL (backend -> gateway, Docker network). M6a contract:
   *   { status: <state.status>, qr_data_url: <data: URL | null> }
   * The backend's gated /api/whatsapp/qr proxies THIS (JSON) so the owner's
   * dashboard can render the QR as an image. The plain /qr route below returns
   * HTML (a dev convenience), which is why a separate JSON route is needed.
   * qr_data_url is null once linked (no QR needed) or before the QR is ready.
   */
  app.get('/qr.json', (_req, res) => {
    res.set('Cache-Control', 'no-store');
    res.status(200).json({
      status: state.status,
      qr_data_url: state.qrDataUrl,
    });
  });

  /*
   * POST /send-bot — INTERNAL (backend -> gateway, Docker network). M6a.2 contract.
   * Lets the backend deliver an OWNER's manual handoff reply to a customer over
   * WhatsApp (the bot's own auto-replies are sent inline via sendReplies; this is
   * the async human-reply path).
   *
   *   header: X-Gateway-Token: <GATEWAY_API_TOKEN>  (REQUIRED, constant-time check)
   *   body:   { "to": "<wa jid>", "text": "<reply text>" }
   *   ->  401 if the token is missing/bad (checked BEFORE any work)
   *   ->  400 if `to` or `text` is missing/blank
   *   ->  503 if WhatsApp is not connected (no live socket)
   *   ->  200 { ok: true, message_id: <id|null> } on a successful send
   *   ->  500 generic on an unexpected send failure (no PII echoed)
   *
   * `to` is a full WhatsApp jid (customer "<num>@s.whatsapp.net", or the owner's
   * "<id>@lid" for the self-chat) — sock.sendMessage handles both. We record the
   * sent id in the loop guard so its fromMe echo never re-triggers the bot.
   * SAFE logging only: never log `to`, `text`, or the token.
   */
  app.post('/send-bot', async (req, res) => {
    // 1) AUTH FIRST — constant-time token check before touching the body/socket.
    if (!gatewayTokenValid(req.get('x-gateway-token'))) {
      return res.status(401).json({ ok: false, error: 'unauthorized' });
    }

    // 2) Validate input. `to`/`text` must be present and non-blank.
    const to = typeof req.body?.to === 'string' ? req.body.to.trim() : '';
    const text = typeof req.body?.text === 'string' ? req.body.text : '';
    if (!to || !text.trim()) {
      return res.status(400).json({ ok: false, error: 'missing to or text' });
    }

    // 3) Require a live connection.
    const sock = socketModule.getSock();
    if (state.status !== 'connected' || !sock) {
      return res.status(503).json({ ok: false, error: 'not connected' });
    }

    // 4) Send and record the id in the loop guard.
    try {
      const sent = await sock.sendMessage(String(to), { text: String(text) });
      const messageId = sent?.key?.id || null;
      // LOOP PREVENTION: remember OUR sent id so its fromMe echo is skipped at the
      // top of handleInbound (matches sendReplies' behaviour for auto-replies).
      socketModule.rememberSentId(messageId);
      // SAFE log: length + whether we got an id back. Never the jid/text/token.
      log.info({ textLen: text.length, hasMessageId: Boolean(messageId) }, 'sent owner reply via /send-bot');
      return res.status(200).json({ ok: true, message_id: messageId });
    } catch (err) {
      // Generic 500 — err.message may reference internals, so do NOT echo it to
      // the client. Log it safely (no to/text/token).
      log.error({ err: err.message }, 'failed to send owner reply via /send-bot');
      return res.status(500).json({ ok: false, error: 'send failed' });
    }
  });

  /*
   * GET /qr — SPIKE / DEV-ONLY.
   * Renders the current QR as an <img> for easy phone scanning. This route is
   * intentionally unauthenticated for the dev spike ONLY. The real design (M6)
   * streams the QR to the dashboard over an authenticated channel and NEVER
   * exposes it on an open route (the old system leaked it via unauth GET /status).
   */
  app.get('/qr', (_req, res) => {
    res.set('Cache-Control', 'no-store');
    let inner;
    if (state.status === 'connected') {
      inner = '<p class="ok">Already linked. No QR needed.</p>';
    } else if (state.qrDataUrl) {
      inner =
        '<p>Scan with WhatsApp &rarr; Linked devices &rarr; Link a device</p>' +
        `<img alt="WhatsApp QR" src="${state.qrDataUrl}" width="320" height="320" />`;
    } else {
      inner = '<p>QR not ready yet. This page auto-refreshes…</p>';
    }
    res.status(200).send(
      `<!doctype html><html><head><meta charset="utf-8">` +
        `<meta http-equiv="refresh" content="5">` +
        `<title>Bizz_up Gateway QR (dev)</title>` +
        `<style>body{font-family:system-ui,sans-serif;text-align:center;padding:2rem}` +
        `.ok{color:#0a7d28;font-weight:600}img{margin-top:1rem;border:1px solid #ddd}</style>` +
        `</head><body><h1>WhatsApp Gateway — QR (dev only)</h1>${inner}` +
        `<p style="color:#888;margin-top:2rem">status: ${state.status}</p>` +
        `</body></html>`
    );
  });

  /*
   * GET /inbox — SPIKE/DEV-ONLY. Shows the CONTENT of the last inbound messages so
   * you can verify what's being received. In-memory only; not logged, not persisted.
   */
  app.get('/inbox', (_req, res) => {
    res.set('Cache-Control', 'no-store');
    const rows = recentMessages.length
      ? recentMessages
          .map(
            (m) =>
              `<tr><td>${escapeHtml(m.at)}</td><td>${escapeHtml(m.from)}</td>` +
              `<td>${escapeHtml(m.pushName)}</td><td>${escapeHtml(m.text)}</td></tr>`,
          )
          .join('')
      : '<tr><td colspan="4" style="color:#888">עדיין לא התקבלו הודעות. שלח הודעה למספר המקושר.</td></tr>';
    res.status(200).send(
      `<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="3">` +
        `<title>Inbox (dev)</title>` +
        `<style>body{font-family:system-ui,sans-serif;padding:1.5rem}table{border-collapse:collapse;width:100%}` +
        `th,td{border:1px solid #ddd;padding:.4rem .6rem;text-align:left;font-size:.9rem}th{background:#f4f4f4}</style>` +
        `<h1>📥 Inbox — הודעות שהתקבלו (dev only)</h1>` +
        `<p>מתרענן כל 3 שניות · החדש למעלה · <a href="/send">לשליחת הודעה →</a></p>` +
        `<table><tr><th>זמן (UTC)</th><th>מאת</th><th>שם</th><th>תוכן</th></tr>${rows}</table>`,
    );
  });

  /*
   * GET /send — SPIKE/DEV-ONLY. A tiny form to send a WhatsApp message (outbound test).
   * POST /send actually sends it via the connected Baileys socket.
   */
  app.get('/send', (_req, res) => {
    res.set('Cache-Control', 'no-store');
    res.status(200).send(
      `<!doctype html><meta charset="utf-8"><title>Send (dev)</title>` +
        `<style>body{font-family:system-ui,sans-serif;padding:1.5rem;max-width:34rem}` +
        `label{display:block;margin-top:.8rem;font-weight:600}input,textarea{width:100%;padding:.5rem;font-size:1rem}` +
        `button{margin-top:1rem;padding:.6rem 1.2rem;font-size:1rem;cursor:pointer}</style>` +
        `<h1>📤 שליחת הודעת וואטסאפ (dev only)</h1>` +
        `<p>status: ${escapeHtml(state.status)} · <a href="/inbox">← inbox</a></p>` +
        `<form method="POST" action="/send">` +
        `<label>אל (מספר בינלאומי מלא, ספרות בלבד, למשל 9725XXXXXXXX)</label>` +
        `<input name="to" inputmode="numeric" placeholder="9725XXXXXXXX" required>` +
        `<label>הודעה</label>` +
        `<textarea name="text" rows="3" placeholder="שלום מ-Bizz_up 👋" required></textarea>` +
        `<button type="submit">שלח</button></form>`,
    );
  });

  app.post('/send', async (req, res) => {
    const to = String(req.body?.to || '').replace(/[^0-9]/g, '');
    const text = String(req.body?.text || '');
    if (!to || !text) return res.status(400).send('חסר מספר או טקסט. <a href="/send">חזרה</a>');
    const sock = socketModule.getSock();
    if (state.status !== 'connected' || !sock) {
      return res.status(503).send('וואטסאפ עדיין לא מחובר. <a href="/send">חזרה</a>');
    }
    try {
      await sock.sendMessage(`${to}@s.whatsapp.net`, { text });
      // SAFE log: recipient suffix + length only — never the body or the full number.
      log.info({ toSuffix: to.slice(-4), textLen: text.length }, 'sent outbound message');
      res
        .status(200)
        .send(`✅ נשלח אל ${escapeHtml(to)}. <a href="/send">שלח עוד</a> · <a href="/inbox">inbox</a>`);
    } catch (err) {
      log.error({ err: err.message }, 'failed to send message');
      res.status(500).send(`❌ השליחה נכשלה: ${escapeHtml(err.message)}. <a href="/send">חזרה</a>`);
    }
  });
}

module.exports = { registerRoutes, gatewayTokenValid, escapeHtml };
