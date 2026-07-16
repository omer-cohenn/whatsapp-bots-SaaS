'use strict';

// סוקט Baileys: חיבור/חיבור-מחדש, זיהוי צ'אט-עצמי, טיפול בהודעות נכנסות, מניעת לולאה.

const fs = require('fs');
const path = require('path');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  jidNormalizedUser,
  WAMessageStubType,
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

// Absolute path to the Baileys auth dir. Used both to start the socket and to
// clear a single contact's stale Signal session on decrypt failure (see below).
const AUTH_PATH = path.resolve(config.authDir);

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

// SEND RELIABILITY (getMessage): when a recipient can't decrypt a message WE
// sent, WhatsApp asks us to resend it — Baileys calls getMessage(key) to look up
// the original content and re-encrypt it. Without this the message is lost. We
// keep the last few OUTGOING message bodies (proto.IMessage) keyed by message id.
// Bounded; content only (no phone / jid). Populated by rememberSentMessage below.
const SENT_MSG_CAP = 500;
const sentMessages = new Map(); // message id -> proto.IMessage we sent
function rememberSentMessage(id, message) {
  // Always record the id for loop-prevention (self-chat echo guard).
  rememberSentId(id);
  if (!id || !message) return;
  sentMessages.set(id, message);
  if (sentMessages.size > SENT_MSG_CAP) {
    // Evict the oldest (first-inserted) entry.
    const oldest = sentMessages.keys().next().value;
    sentMessages.delete(oldest);
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

// ── Bad-MAC / stale-session recovery ─────────────────────────────────────────
// After a re-link (fresh QR), contacts who messaged us before still hold the OLD
// Signal session. Their next message is encrypted with it and fails to decrypt
// ("Bad MAC") — Baileys surfaces this as a message with messageStubType=CIPHERTEXT
// and NO content, so the bot never sees it. Baileys auto-asks the sender to
// resend, but a truly stale session keeps failing (we saw ~99 dead retries).
//
// The cure: DELETE our session for that one contact. With no session on our side,
// their next message triggers a clean PreKey handshake and a fresh session — and
// the bot starts receiving again. We clear ONLY the failing contact (never the
// whole auth), through Baileys' own key store (mutex-safe), after a couple of
// failures, with a cooldown so we don't thrash.
const _DECRYPT_CLEAR_THRESHOLD = 2; // clear on the 2nd failure from a contact
const _DECRYPT_CLEAR_COOLDOWN_MS = 60_000; // then wait 60s before clearing again
const _DECRYPT_FAIL_CAP = 500; // bound the tracking map
const decryptFailures = new Map(); // user id -> { count, clearedAt }

// Pull the bare numeric "user" out of any jid form: "9725...@s.whatsapp.net",
// "142958...@lid", "9725...:12@s.whatsapp.net" -> the digits before @ / : / device.
function jidUser(jid) {
  if (!jid) return null;
  const user = String(jid).split('@')[0].split(':')[0].split('.')[0].replace(/[^0-9]/g, '');
  return user || null;
}

// Delete every stored Signal session belonging to the given user id(s). Session
// files are named "session-<user>.<device>.json"; we match by user so ALL of the
// contact's devices are cleared. Uses authState.keys.set({session:{id:null}}),
// which routes through Baileys' own locked writes (same as normal session saves).
async function clearSessionsForUsers(authState, userIds) {
  let files = [];
  try {
    files = await fs.promises.readdir(AUTH_PATH);
  } catch {
    return; // auth dir unreadable — nothing we can safely do
  }
  const sessionUpdate = {};
  for (const file of files) {
    if (!file.startsWith('session-') || !file.endsWith('.json')) continue;
    const id = file.slice('session-'.length, -'.json'.length); // "<user>.<device>"
    const user = id.split('.')[0].split(':')[0];
    if (userIds.has(user)) sessionUpdate[id] = null; // null => delete via the store
  }
  const count = Object.keys(sessionUpdate).length;
  if (count === 0) return;
  await authState.keys.set({ session: sessionUpdate });
  // SAFE log: how many sessions were cleared. Never the user/phone/jid (PII).
  log.warn({ cleared: count }, 'cleared stale Signal session(s) after decrypt failure');
}

// One decrypt failure (CIPHERTEXT stub). Count it per contact and, once a contact
// crosses the threshold (and isn't in cooldown), clear its session(s). Never
// throws into the Baileys event loop; logs are SAFE (no PII).
async function handleDecryptFailure(authState, msg) {
  try {
    const users = new Set();
    for (const jid of [msg.key?.remoteJid, msg.key?.senderPn, msg.key?.participant]) {
      const u = jidUser(jid);
      if (u) users.add(u);
    }
    if (users.size === 0) return;

    const now = Date.now();
    let shouldClear = false;
    for (const user of users) {
      const rec = decryptFailures.get(user) || { count: 0, clearedAt: 0 };
      rec.count += 1;
      if (rec.count >= _DECRYPT_CLEAR_THRESHOLD && now - rec.clearedAt > _DECRYPT_CLEAR_COOLDOWN_MS) {
        shouldClear = true;
        rec.clearedAt = now;
        rec.count = 0; // reset the streak once we act
      }
      decryptFailures.set(user, rec);
    }

    // Keep the tracking map bounded (evict oldest insertion).
    if (decryptFailures.size > _DECRYPT_FAIL_CAP) {
      const oldest = decryptFailures.keys().next().value;
      decryptFailures.delete(oldest);
    }

    if (shouldClear) await clearSessionsForUsers(authState, users);
  } catch (err) {
    log.error({ err: err.message }, 'failed to handle decrypt failure');
  }
}

// ── Start / maintain the Baileys socket ──────────────────────────────────────
async function startSocket() {
  // Upstream Baileys is flaky — wrap startup in try/catch (B22).
  try {
    // Persist creds in a gitignored ./auth dir for the spike.
    // Real design encrypts these in the DB (crown jewel, M6).
    const { state: authState, saveCreds } = await useMultiFileAuthState(AUTH_PATH);

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
      // SEND RELIABILITY: when a recipient couldn't decrypt a message we sent,
      // WhatsApp asks us to resend and Baileys calls this to fetch the original
      // content and re-encrypt it. We serve it from our small outgoing-message
      // cache (rememberSentMessage). Returning undefined (cache miss / old
      // message) is safe — Baileys just can't resend that particular one.
      getMessage: async (key) => sentMessages.get(key?.id) || undefined,
      // Don't sync full history on connect — we only want live notifications.
      syncFullHistory: false,
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
          // Permanent logout (401): the creds are DEAD — WhatsApp unlinked this
          // device. Parking here forever forces a manual `rm -rf auth`, and the
          // owner/customer just sees a broken "disconnected" page. Instead we WIPE
          // the dead auth and restart the socket, so Baileys immediately issues a
          // FRESH QR to re-link. The dashboard (which polls) then shows that QR
          // automatically — no dead-end, no manual step.
          state.status = 'logged_out';
          log.warn('logged out — wiping dead auth and restarting to surface a fresh QR');
          wipeAuthAndReconnect();
        }
      }
    });

    // Forward inbound messages to the backend, and (M6a) reply into self-chat.
    sock.ev.on('messages.upsert', ({ messages, type }) => {
      // Log every upsert event so we can diagnose missing messages in dev.
      log.info({ type, count: (messages || []).length }, 'messages.upsert event');
      for (const msg of messages || []) {
        // DECRYPT FAILURE (Bad MAC): Baileys delivers the envelope with
        // messageStubType=CIPHERTEXT and no content. The contact's Signal session
        // is stale (usually after a re-link). Clear it so their next message
        // negotiates a fresh session, then skip — there's nothing to run.
        if (msg.messageStubType === WAMessageStubType.CIPHERTEXT) {
          handleDecryptFailure(authState, msg);
          continue;
        }
        // Only act on live notifications; skip history-sync / append noise.
        if (type !== 'notify') continue;
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

// On a permanent logout (401) the creds are dead — delete EVERY auth file (dead
// creds + all stale sessions) and restart the socket so Baileys issues a fresh
// QR to re-link. We also drop our cached identity, because a re-link may be to a
// DIFFERENT account (unlike a transient reconnect, where the ids are stable and
// we deliberately keep them). Guarded by `reconnecting` so it can't overlap a
// scheduled reconnect. Never throws — a wipe failure still tries to restart.
async function wipeAuthAndReconnect() {
  if (reconnecting) return;
  reconnecting = true;
  try {
    const files = await fs.promises.readdir(AUTH_PATH).catch(() => []);
    await Promise.all(
      files.map((f) => fs.promises.unlink(path.join(AUTH_PATH, f)).catch(() => {}))
    );
    // New account possible on re-link → forget the old identity.
    ownJid = null;
    ownLid = null;
    log.info({ removed: files.length }, 'wiped dead auth; restarting for a fresh QR');
  } catch (err) {
    log.error({ err: err.message }, 'failed to wipe dead auth');
  } finally {
    reconnecting = false;
    startSocket();
  }
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
  rememberSentMessage,
  getSock,
  startSocket,
  scheduleReconnect,
  isSelfChat,
  captureOwnIds,
  normalizeJidSafe,
  handleInbound,
  getOwnJid: () => ownJid,
});
