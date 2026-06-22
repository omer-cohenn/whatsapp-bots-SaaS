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
const crypto = require('crypto');
const express = require('express');
const qrcode = require('qrcode');
const { request } = require('undici');
const { Boom } = require('@hapi/boom');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  jidNormalizedUser,
} = require('@whiskeysockets/baileys');

const { loadConfig } = require('./config');
const { createLogger } = require('./logger');
const { buildWebhookPayload, extractText } = require('./contract');

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

// ── M6a "Message Yourself" support ───────────────────────────────────────────
// The linked account's OWN normalized jid. Computed once on connect (open) so we
// can recognize the owner's self-chat (the chat with themselves). Null until
// connected. Used by isSelfChat(); never logged (it embeds the phone number).
let ownJid = null;
// Modern WhatsApp also addresses our own identity by a "LID" (@lid — a hidden
// id distinct from the phone number). The self-chat live message arrives with
// remoteJid = our own @lid, NOT our @s.whatsapp.net jid, so we must recognize
// BOTH forms. Computed on connect alongside ownJid; null until connected.
let ownLid = null;

function normalizeJidSafe(jid) {
  if (!jid) return null;
  try {
    return jidNormalizedUser(jid);
  } catch {
    return null;
  }
}

/**
 * The self-chat is the conversation a user has with their OWN number. A message
 * is a self-chat message when its remoteJid normalizes to our own identity — in
 * EITHER addressing form: the phone-number jid (@s.whatsapp.net) or the modern
 * hidden id (@lid). Returns false until we are connected (own ids known).
 */
function isSelfChat(remoteJid) {
  const n = normalizeJidSafe(remoteJid);
  if (!n) return false;
  return (ownJid && n === ownJid) || (ownLid && n === ownLid);
}

// LOOP PREVENTION: ids of messages WE (the gateway) sent. In the self-chat,
// every send echoes back through messages.upsert with fromMe=true — without
// this guard the bot would reply to its own replies forever. We skip any upsert
// whose key.id is in this set. Bounded (~200) with oldest-evicted via insertion
// order (Set preserves it). Stores message id strings only — no PII.
const SENT_ID_CAP = 200;
const sentMessageIds = new Set();
function rememberSentId(id) {
  if (!id) return;
  sentMessageIds.add(id);
  if (sentMessageIds.size > SENT_ID_CAP) {
    // Evict the oldest (first-inserted) id.
    const oldest = sentMessageIds.values().next().value;
    sentMessageIds.delete(oldest);
  }
}

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

let sock = null;
let reconnecting = false;

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
  if (!sock || !Array.isArray(replies) || replies.length === 0) return;
  for (const reply of replies) {
    const text = typeof reply === 'string' ? reply : '';
    if (!text.trim()) continue; // skip empty/blank replies
    try {
      const sent = await sock.sendMessage(remoteJid, { text });
      // Record the id of OUR outgoing message so its fromMe echo is ignored.
      rememberSentId(sent?.key?.id);
      log.info({ textLen: text.length }, 'sent bot reply into self-chat');
    } catch (err) {
      // Never log the reply text or the jid (PII) — message only.
      log.error({ err: err.message }, 'failed to send bot reply');
    }
  }
}

// ── Handle one inbound message ───────────────────────────────────────────────
// Decides whether to skip, forward, and (for self-chat) reply. Wrapped so it
// never throws into the Baileys event loop. SAFE logging only.
async function handleInbound(msg) {
  try {
    if (!msg?.message) return; // skip receipts / empty envelopes

    const remoteJid = msg.key?.remoteJid;
    const selfChat = isSelfChat(remoteJid);

    // LOOP PREVENTION (must be at the very top of handling): skip any message
    // whose id is one WE sent. In the self-chat our replies echo back with
    // fromMe=true; without this the bot would answer its own messages forever.
    const msgId = msg.key?.id;
    if (msgId && sentMessageIds.has(msgId)) return;

    // fromMe policy: skip our own outgoing for NORMAL chats (unchanged), BUT
    // for the self-chat the owner's own typed input IS fromMe — process it.
    if (msg.key?.fromMe && !selfChat) return;

    if (selfChat) {
      // M6a "Message Yourself": run through the real bot pipeline and reply.
      const text = extractText(msg.message || {});
      if (!text || !text.trim()) return; // empty/blank -> skip (resilience)

      const payload = buildWebhookPayload(msg, config.gatewayAccountId, {
        selfTest: true,
        conversationId: remoteJid,
      });
      const response = await forwardToBackend(payload);
      // replies=[] when not published / no mapping / silent — sendReplies no-ops.
      await sendReplies(remoteJid, response?.replies);
      return;
    }

    // NORMAL chat (M6a allowlist): a non-self inbound from someone else. If there
    // is extractable text, run it through the same forward->reply core as the
    // self-chat — the ONLY difference is no self_test field, so the BACKEND decides
    // who is actually allowed (it returns replies:[] for anyone not on the owner's
    // test-number allowlist / unpublished bot, and sendReplies then no-ops).
    const text = extractText(msg.message || {});
    if (!text || !text.trim()) return; // empty/blank -> skip (same as self-chat)

    // No selfTest -> payload carries conversation_id but NOT self_test.
    const payload = buildWebhookPayload(msg, config.gatewayAccountId, {
      conversationId: remoteJid,
    });
    const response = await forwardToBackend(payload);
    // replies=[] when not allowed / not published / silent — sendReplies no-ops.
    // Same loop-prevention as self-chat: each sent id is remembered so its fromMe
    // echo is skipped at the top of handleInbound.
    await sendReplies(remoteJid, response?.replies);

    // DEV-ONLY: stash the content so GET /inbox can show it.
    rememberMessage({
      from: payload.from,
      pushName: payload.push_name,
      text: payload.text,
      type: payload.type,
      at: new Date().toISOString(),
    });
  } catch (err) {
    // err.message carries no PII here; the socket must survive.
    log.error({ err: err.message }, 'failed to handle inbound message');
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
        // Compute the linked account's OWN jid once, now that sock.user exists.
        // Used to detect self-chat messages. Never logged (embeds the phone).
        ownJid = normalizeJidSafe(sock?.user?.id);
        ownLid = normalizeJidSafe(sock?.user?.lid);
        // Safe: log only WHICH addressing forms we resolved (domains/booleans),
        // never the number/lid itself (PII / identity).
        log.info(
          {
            hasOwnJid: Boolean(ownJid),
            hasOwnLid: Boolean(ownLid),
          },
          'WhatsApp connection open (linked)'
        );
      }

      if (connection === 'close') {
        state.status = 'disconnected';
        state.qrDataUrl = null;
        ownJid = null; // identity is no longer valid until we reconnect
        ownLid = null;
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

    // Forward inbound messages to the backend, and (M6a) reply into self-chat.
    sock.ev.on('messages.upsert', ({ messages, type }) => {
      // Only act on live notifications; skip history-sync / append noise.
      if (type !== 'notify') return;
      for (const msg of messages || []) {
        // Each message is handled independently and async so one error / one
        // slow webhook can't block the others. handleInbound never throws.
        handleInbound(msg);
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
  if (state.status !== 'connected' || !sock) {
    return res.status(503).json({ ok: false, error: 'not connected' });
  }

  // 4) Send and record the id in the loop guard.
  try {
    const sent = await sock.sendMessage(String(to), { text: String(text) });
    const messageId = sent?.key?.id || null;
    // LOOP PREVENTION: remember OUR sent id so its fromMe echo is skipped at the
    // top of handleInbound (matches sendReplies' behaviour for auto-replies).
    rememberSentId(messageId);
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
