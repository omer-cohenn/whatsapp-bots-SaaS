'use strict';

// סוקט Baileys: חיבור/חיבור-מחדש, זיהוי צ'אט-עצמי, טיפול בהודעות נכנסות, מניעת לולאה.

const path = require('path');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  jidNormalizedUser,
} = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const qrcode = require('qrcode');

const { loadConfig } = require('./config');
const { createLogger } = require('./logger');
const { buildWebhookPayload, extractText } = require('./contract');
// forward->reply core. Required here so handleInbound can use it; webhook.js
// requires THIS module back (for getSock/rememberSentId), but only inside its
// function bodies, so the require cycle resolves cleanly.
const { forwardToBackend, sendReplies } = require('./webhook');

const config = loadConfig();
const log = createLogger(config.logLevel);

// ── Live connection state (in-RAM; spike only) ──────────────────────────────
// Real design: state machine persisted + QR streamed over authed channel (M6).
// Exported BY REFERENCE so routes.js reads the same live object.
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

/**
 * Capture our own identity (phone-jid + the @lid form) from whatever Baileys has
 * populated. Two robustness rules learned the hard way:
 *   1. Baileys does NOT reliably set `sock.user.lid` on every connect — it often
 *      lands a moment later via a `creds.update`. So we read it from several
 *      sources and also re-run this on creds.update.
 *   2. The lid is STABLE for an account, so once captured we KEEP it (we only
 *      ever overwrite with a real value, and we do NOT clear it on disconnect).
 *      Otherwise a reconnect that omits the lid would silently break self-chat
 *      (@lid) detection — the bot would treat the owner's own messages as a
 *      stranger's and stay silent.
 */
function captureOwnIds() {
  try {
    const me = sock?.authState?.creds?.me;
    const jid = normalizeJidSafe(sock?.user?.id || me?.id);
    if (jid) ownJid = jid;
    const lid = normalizeJidSafe(
      sock?.user?.lid || me?.lid || sock?.authState?.creds?.lid
    );
    if (lid) ownLid = lid;
  } catch {
    // Keep whatever identity we already have.
  }
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
// Exported BY REFERENCE so routes.js reads the same live array.
const recentMessages = [];
function rememberMessage(m) {
  recentMessages.unshift(m);
  if (recentMessages.length > 20) recentMessages.length = 20;
}

let sock = null;
let reconnecting = false;

// Accessor for the live socket. webhook.js / routes.js call this at runtime
// (not at load time) because `sock` is reassigned on every (re)connect.
function getSock() {
  return sock;
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

    sock.ev.on('creds.update', () => {
      // The own @lid frequently lands here (a moment after 'open'), so refresh
      // our identity whenever creds change — then persist.
      captureOwnIds();
      saveCreds();
    });

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
        // Capture the linked account's OWN ids (phone-jid + @lid) from all
        // available sources, now that sock.user exists. Used to detect self-chat.
        // Never logged (embeds the phone). May be completed later via creds.update.
        captureOwnIds();
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
        // Do NOT clear ownJid/ownLid here: the identity is STABLE for the account,
        // and a reconnect sometimes omits the @lid. Clearing it would break
        // self-chat (@lid) detection until a lucky reconnect repopulates it —
        // the root cause of the bot "randomly" going silent. We keep the last
        // known ids and only ever overwrite them with a real value.
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
          // Permanent logout: surface a distinct status so the dashboard can
          // show a clear "re-scan QR" message instead of the generic loading text.
          state.status = 'logged_out';
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

// Mutate the EXISTING exports object instead of reassigning it. webhook.js does
// `const socketModule = require('./socket')` at load time — during the
// socket<->webhook require cycle it captures THIS object before we get here, so
// a fresh `module.exports = {…}` would leave webhook holding the old empty
// reference (→ "socketModule.getSock is not a function" at reply time).
// Object.assign keeps the same reference both modules share.
Object.assign(module.exports, {
  state,
  recentMessages,
  rememberSentId,
  getSock,
  startSocket,
  scheduleReconnect,
  isSelfChat,
  captureOwnIds,
  normalizeJidSafe,
  handleInbound,
  getOwnJid: () => ownJid,
});
