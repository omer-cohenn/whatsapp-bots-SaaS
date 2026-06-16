'use strict';

/**
 * Bizz_up WhatsApp gateway — M0+M1 MINIMAL build.
 *
 * Purpose: boot a Baileys session and PROVE the RECEIVE path — an inbound
 * WhatsApp message travels messages.upsert -> normalized payload -> the backend
 * webhook. NO real features (no multi-tenant, no DB, no send, no encryption).
 *
 * Endpoints:
 *   GET /healthz  -> 200, no QR / no secret (used by docker healthcheck).
 *   GET /qr       -> SPIKE/DEV-ONLY HTML page rendering the current QR as an
 *                    image for easy scanning. The real design streams the QR
 *                    over an authed channel and never exposes it unauth'd (M6).
 *
 * Frozen webhook contract (gateway -> backend), POST BACKEND_WEBHOOK_URL with
 * header "X-Gateway-Token: <GATEWAY_API_TOKEN>" and JSON body:
 *   { gateway_account_id, from, push_name, message_id, timestamp, type, text, raw }
 */

const path = require('path');
const express = require('express');
const qrcode = require('qrcode');
const { request } = require('undici');
const { Boom } = require('@hapi/boom');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
} = require('@whiskeysockets/baileys');

const { loadConfig } = require('./config');
const { createLogger } = require('./logger');
const { buildWebhookPayload } = require('./contract');

// FAIL CLOSED: loadConfig throws if a required secret is missing -> process exits.
let config;
try {
  config = loadConfig();
} catch (err) {
  // Use console here (logger not built yet). The error message contains no secret.
  console.error(err.message);
  process.exit(1);
}

const log = createLogger(config.logLevel);

// ── Live connection state (in-RAM; spike only) ──────────────────────────────
// Real design: state machine persisted + QR streamed over authed channel (M6).
const state = {
  status: 'starting', // starting | qr_pending | connected | disconnected
  qrDataUrl: null, // data: URL of the current QR PNG (DEV-ONLY, never logged)
};

// DEV-ONLY: keep the last few INBOUND messages in memory so you can eyeball the
// content during the connection test via GET /inbox. NOT logged, NOT persisted.
// Remove this (and the /inbox, /send routes) before production.
const recentMessages = [];
function rememberMessage(m) {
  recentMessages.unshift(m);
  if (recentMessages.length > 20) recentMessages.length = 20;
}
function escapeHtml(s) {
  return String(s == null ? '' : s).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]),
  );
}

let sock = null;
let reconnecting = false;

// ── Forward one inbound message to the backend webhook ───────────────────────
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
    // Drain the body so the socket can be reused / closed cleanly.
    await res.body.text().catch(() => {});

    // SAFE logging only: status + a truncated message id + whether text existed.
    // No phone number, no message body, no token, no QR.
    log.info(
      {
        webhookStatus: res.statusCode,
        messageIdSuffix: payload.message_id ? payload.message_id.slice(-6) : null,
        msgType: payload.type,
        hasText: Boolean(payload.text),
      },
      'forwarded inbound message to backend'
    );
  } catch (err) {
    // err.message from undici contains no secret/PII (connection-level error).
    log.error({ err: err.message }, 'failed to forward inbound message to backend');
  }
}

// ── Start / maintain the Baileys socket ──────────────────────────────────────
async function startSocket() {
  // Upstream Baileys is flaky — wrap startup in try/catch (B22).
  try {
    // Persist creds in a gitignored ./auth dir for the spike.
    // Real design encrypts these in the DB (crown jewel, M6).
    const authPath = path.resolve(config.authDir);
    const { state: authState, saveCreds } = await useMultiFileAuthState(authPath);

    // fetchLatestBaileysVersion can fail at boot; tolerate it and let Baileys
    // fall back to its bundled version.
    let version;
    try {
      ({ version } = await fetchLatestBaileysVersion());
    } catch (e) {
      log.warn({ err: e.message }, 'fetchLatestBaileysVersion failed; using bundled version');
      version = undefined;
    }

    sock = makeWASocket({
      version,
      auth: authState,
      // Baileys' own logs are silenced — we never want it printing the QR or
      // session internals to stdout. We log our own safe, structured events.
      logger: require('pino')({ level: 'silent' }),
      printQRInTerminal: false, // never render the QR to logs/terminal
      browser: ['Bizz_up Gateway (spike)', 'Chrome', '1.0'],
      markOnlineOnConnect: false,
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        // Render QR to a PNG data URL for the DEV-ONLY /qr page.
        // NOTE: never log `qr` or `qrDataUrl` — it is session-hijack material.
        qrcode
          .toDataURL(qr, { margin: 1, width: 320 })
          .then((dataUrl) => {
            state.qrDataUrl = dataUrl;
            state.status = 'qr_pending';
            log.info('QR ready — open GET /qr to scan (dev-only)');
          })
          .catch((e) => log.error({ err: e.message }, 'failed to render QR'));
      }

      if (connection === 'open') {
        state.status = 'connected';
        state.qrDataUrl = null; // drop the QR once linked
        log.info('WhatsApp connection open (linked)');
      }

      if (connection === 'close') {
        state.status = 'disconnected';
        state.qrDataUrl = null;
        const statusCode =
          lastDisconnect?.error instanceof Boom
            ? lastDisconnect.error.output?.statusCode
            : undefined;
        const loggedOut = statusCode === DisconnectReason.loggedOut;
        log.warn({ statusCode, loggedOut }, 'WhatsApp connection closed');

        // Spike reconnect policy: reconnect on transient closes; on loggedOut
        // stop (creds are dead — re-link would need a fresh QR). Real design
        // uses exponential backoff + owner-visible re-link (M6 / WA-1.6).
        if (!loggedOut) {
          scheduleReconnect();
        } else {
          log.error('logged out — delete the ./auth dir and restart to re-link');
        }
      }
    });

    // THE RECEIVE SPIKE: forward inbound messages to the backend.
    sock.ev.on('messages.upsert', ({ messages, type }) => {
      // Only act on live notifications; skip history-sync / append noise.
      if (type !== 'notify') return;
      for (const msg of messages || []) {
        if (!msg?.message) continue; // skip receipts / empty envelopes
        if (msg.key?.fromMe) continue; // skip our own outgoing
        const payload = buildWebhookPayload(msg, config.gatewayAccountId);
        forwardToBackend(payload);
        // DEV-ONLY: stash the content so GET /inbox can show it.
        rememberMessage({
          from: payload.from,
          pushName: payload.push_name,
          text: payload.text,
          type: payload.type,
          at: new Date().toISOString(),
        });
      }
    });
  } catch (err) {
    log.error({ err: err.message }, 'failed to start Baileys socket; retrying');
    state.status = 'disconnected';
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (reconnecting) return;
  reconnecting = true;
  // Fixed short delay is fine for the spike (single session, dev).
  setTimeout(() => {
    reconnecting = false;
    startSocket();
  }, 3000);
}

// ── HTTP server ──────────────────────────────────────────────────────────────
const app = express();
// Parse JSON + form bodies (needed for the dev-only POST /send form).
app.use(express.json());
app.use(express.urlencoded({ extended: false }));

// Health: 200, NO QR / NO secret. Used by the docker-compose healthcheck.
app.get('/healthz', (_req, res) => {
  res.status(200).json({ ok: true, service: 'gateway', status: state.status });
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

app.listen(config.port, () => {
  log.info(
    { port: config.port, backendWebhookUrl: config.backendWebhookUrl },
    'gateway HTTP server listening'
  );
  // Kick off the WhatsApp connection after the server is up so /healthz and /qr
  // respond immediately.
  startSocket();
});

// Never crash silently on an unhandled rejection (Baileys can throw async).
process.on('unhandledRejection', (reason) => {
  log.error({ err: reason instanceof Error ? reason.message : String(reason) }, 'unhandledRejection');
});
