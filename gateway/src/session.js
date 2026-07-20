'use strict';

// session יחיד לכל עסק (M6b): סוקט Baileys, creds מוצפנים ב-DB, זיהוי צ'אט-עצמי,
// התאוששות Bad-MAC, reconnect עם backoff, שליחה מוגבלת-קצב, דיווח סטטוס לבקאנד.

const {
  default: makeWASocket,
  fetchLatestBaileysVersion,
  DisconnectReason,
  jidNormalizedUser,
  WAMessageStubType,
  initAuthCreds,
  BufferJSON,
  downloadMediaMessage,
} = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const qrcode = require('qrcode');

const { loadConfig } = require('./config');
const { createLogger } = require('./logger');
const {
  buildWebhookPayload,
  extractText,
  extractMedia,
  checkMediaAllowed,
  mediaMime,
  MAX_MEDIA_BYTES,
  MEDIA_TOO_BIG_MSG,
  MEDIA_FAILED_MSG,
} = require('./contract');
const { forwardToBackend } = require('./webhook');
const internalApi = require('./internalApi');
const { useDbAuthState } = require('./dbAuthState');

const config = loadConfig();
const log = createLogger(config.logLevel);

// Reconnect backoff (exponential, capped). A logged-out session does NOT auto-
// reconnect on the same creds — it wipes them and re-links (fresh QR).
const RECONNECT_BASE_MS = 3000;
const RECONNECT_MAX_MS = 60000;

// Bad-MAC recovery tuning (per contact, per session).
const DECRYPT_CLEAR_THRESHOLD = 2;
const DECRYPT_CLEAR_COOLDOWN_MS = 60000;

// Loop-guard + getMessage cache bounds.
const SENT_ID_CAP = 200;
const SENT_MSG_CAP = 500;

// Send rate-limit: minimum gap between outgoing messages on ONE session (ban
// safety). Sends are serialized per session.
const SEND_MIN_GAP_MS = 1000;

// Baileys wants a pino-like logger for the media download. We hand it a SILENT
// one on purpose — its debug output includes media urls and keys, which must
// never reach our logs.
const mediaLogger = require('pino')({ level: 'silent' });

// A fresh (unregistered) auth blob — used to wipe dead creds on logout so the
// next start produces a new QR.
function freshCredsBlob() {
  const json = JSON.stringify({ creds: initAuthCreds(), keys: {} }, BufferJSON.replacer);
  return Buffer.from(json, 'utf-8').toString('base64');
}

function normalizeJidSafe(jid) {
  if (!jid) return null;
  try {
    return jidNormalizedUser(jid);
  } catch {
    return null;
  }
}

// Bare numeric "user" from any jid form (phone jid, @lid, with :device).
function jidUser(jid) {
  if (!jid) return null;
  const user = String(jid).split('@')[0].split(':')[0].split('.')[0].replace(/[^0-9]/g, '');
  return user || null;
}

/**
 * Create (but do not yet start) a session for one business.
 * @param {string} businessId
 */
function createSession(businessId) {
  // ── live state (per session) ──────────────────────────────────────────────
  const state = {
    businessId,
    status: 'starting', // starting | qr_pending | connected | disconnected | logged_out
    qrDataUrl: null,
  };

  let sock = null;
  let authStore = null; // { state, saveCreds, flush, clearSessionsForUsers }
  let ownJid = null;
  let ownLid = null;
  let stopped = false; // set by stop(): suppress reconnects
  let reconnectAttempts = 0;
  let reconnectTimer = null;

  // loop-prevention + getMessage cache + Bad-MAC tracking (all per session).
  const sentMessageIds = new Set();
  const sentMessages = new Map();
  const decryptFailures = new Map();

  // ── send rate-limit: serialize + min-gap ──────────────────────────────────
  let sendChain = Promise.resolve();
  let lastSentAt = 0;
  function enqueueSend(fn) {
    const run = sendChain.then(async () => {
      const wait = Math.max(0, lastSentAt + SEND_MIN_GAP_MS - Date.now());
      if (wait) await new Promise((r) => setTimeout(r, wait));
      try {
        return await fn();
      } finally {
        lastSentAt = Date.now();
      }
    });
    // Keep the chain alive even if one send rejects.
    sendChain = run.catch(() => {});
    return run;
  }

  function rememberSentMessage(id, message) {
    if (!id) return;
    sentMessageIds.add(id);
    if (sentMessageIds.size > SENT_ID_CAP) {
      sentMessageIds.delete(sentMessageIds.values().next().value);
    }
    if (message) {
      sentMessages.set(id, message);
      if (sentMessages.size > SENT_MSG_CAP) {
        sentMessages.delete(sentMessages.keys().next().value);
      }
    }
  }

  // ── identity (self-chat detection) ────────────────────────────────────────
  function captureOwnIds() {
    try {
      const me = sock?.authState?.creds?.me;
      const jid = normalizeJidSafe(sock?.user?.id || me?.id);
      if (jid) ownJid = jid;
      const lid = normalizeJidSafe(sock?.user?.lid || me?.lid || sock?.authState?.creds?.lid);
      if (lid) ownLid = lid;
    } catch {
      /* keep whatever we have */
    }
  }

  function isSelfChat(remoteJid) {
    const n = normalizeJidSafe(remoteJid);
    if (!n) return false;
    return (ownJid && n === ownJid) || (ownLid && n === ownLid);
  }

  function ownPhoneDigits() {
    if (!ownJid) return null;
    const d = String(ownJid).split('@')[0].split(':')[0].replace(/[^0-9]/g, '');
    return d || null;
  }

  // ── status reporting to the backend (per business) ────────────────────────
  async function report() {
    const resp = await internalApi.reportStatus(businessId, {
      status: state.status,
      phone: ownPhoneDigits(),
      qrDataUrl: state.qrDataUrl,
    });
    // ONE NUMBER = ONE BUSINESS: the backend refused this link because the
    // scanned number already belongs to ANOTHER business. Log the device out —
    // this unlinks it on the phone too and triggers our loggedOut recovery
    // (wipe creds → fresh QR), so the owner can scan with a DIFFERENT number.
    if (resp?.conflict && sock) {
      log.warn({ businessId }, 'phone already linked to another business — logging out this session');
      try {
        await sock.logout();
      } catch (err) {
        log.error({ err: err.message, businessId }, 'conflict logout failed');
      }
    }
  }

  // ── send helpers ──────────────────────────────────────────────────────────
  // Rate-limited send that also records the id (loop guard) + content (resend).
  async function sendText(to, text) {
    if (!sock || state.status !== 'connected') {
      throw new Error('not connected');
    }
    const sent = await enqueueSend(() => sock.sendMessage(String(to), { text: String(text) }));
    rememberSentMessage(sent?.key?.id, sent?.message);
    return sent?.key?.id || null;
  }

  // Send the backend's replies in order (bot auto-replies). Never throws.
  async function sendReplies(remoteJid, replies) {
    if (!Array.isArray(replies) || replies.length === 0) return;
    for (const reply of replies) {
      const text = typeof reply === 'string' ? reply : '';
      if (!text.trim()) continue;
      try {
        await sendText(remoteJid, text);
      } catch (err) {
        log.error({ err: err.message, businessId }, 'failed to send bot reply');
      }
    }
  }

  // ── Bad-MAC recovery ──────────────────────────────────────────────────────
  async function handleDecryptFailure(msg) {
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
        if (rec.count >= DECRYPT_CLEAR_THRESHOLD && now - rec.clearedAt > DECRYPT_CLEAR_COOLDOWN_MS) {
          shouldClear = true;
          rec.clearedAt = now;
          rec.count = 0;
        }
        decryptFailures.set(user, rec);
      }
      if (shouldClear && authStore) {
        const cleared = authStore.clearSessionsForUsers(users);
        if (cleared) log.warn({ businessId, cleared }, 'cleared stale Signal session(s) after decrypt failure');
      }
    } catch (err) {
      log.error({ err: err.message, businessId }, 'failed to handle decrypt failure');
    }
  }

  // ── inbound media (M16) ───────────────────────────────────────────────────
  // Download ONE already-guarded attachment and hand it to the backend.
  // Returns { media } on success or { error: <Hebrew reply> } on failure — it
  // NEVER throws, so a hostile or broken attachment can't kill the socket.
  // Nothing here logs the file name or a single byte of the file.
  async function fetchAndStoreMedia(msg, media) {
    let bytes;
    try {
      // `reuploadRequest` is REQUIRED: WhatsApp media urls expire, and without it
      // an older message's download fails outright. Baileys asks the phone to
      // re-upload the file and then retries.
      bytes = await downloadMediaMessage(
        msg,
        'buffer',
        {},
        { reuploadRequest: sock.updateMediaMessage, logger: mediaLogger }
      );
    } catch (err) {
      log.error({ err: err.message, businessId }, 'media download failed');
      return { error: MEDIA_FAILED_MSG };
    }

    if (!bytes || !bytes.length) {
      log.error({ businessId }, 'media download returned no bytes');
      return { error: MEDIA_FAILED_MSG };
    }
    // Second size check, now on the REAL length: `fileLength` is sender-supplied
    // metadata and can lie, so the pre-download guard alone is not a limit.
    if (bytes.length > MAX_MEDIA_BYTES) {
      log.warn({ businessId, sizeBytes: bytes.length }, 'media exceeds cap after download');
      return { error: MEDIA_TOO_BIG_MSG };
    }

    const stored = await internalApi.uploadMedia(businessId, {
      bytes,
      mimeType: mediaMime(media.node),
      fileName: media.node?.fileName || null,
      conversationId: msg.key?.remoteJid,
      // The idempotency key: a Baileys re-emit of the same message reuses the
      // file already stored instead of paying for a second copy.
      messageId: msg.key?.id,
    });
    if (!stored) return { error: MEDIA_FAILED_MSG };
    return { media: stored };
  }

  // ── inbound ───────────────────────────────────────────────────────────────
  async function handleInbound(msg) {
    try {
      if (!msg?.message) return;
      const remoteJid = msg.key?.remoteJid;
      const selfChat = isSelfChat(remoteJid);

      const msgId = msg.key?.id;
      if (msgId && sentMessageIds.has(msgId)) return; // our own echo
      if (msg.key?.fromMe && !selfChat) return;

      const content = msg.message || {};
      const text = extractText(content);
      const media = extractMedia(content);

      // Drop only messages that carry NEITHER text NOR an attachment. Before M16
      // this early-return fired on every media message (a photo has no
      // `conversation` field), which is why files never reached the bot at all.
      if (media === null && (!text || !text.trim())) return;

      let storedMedia = null;
      if (media !== null) {
        // PRE-DOWNLOAD guard: size + type are read from the message metadata, so
        // an oversized or unsupported file costs us nothing. We tell the customer
        // WHY in Hebrew and stop here — we do NOT forward the webhook, so the bot
        // stays on the same step and the customer can simply resend a valid file.
        const allowed = checkMediaAllowed(media.node);
        if (!allowed.ok) {
          log.info({ businessId, mediaType: media.type }, 'media refused before download');
          await sendReplies(remoteJid, [allowed.reason]);
          return;
        }
        const outcome = await fetchAndStoreMedia(msg, media);
        if (outcome.error) {
          await sendReplies(remoteJid, [outcome.error]);
          return;
        }
        storedMedia = outcome.media;
      }

      // gateway_account_id = businessId (the backend resolves the tenant from it).
      const payload = buildWebhookPayload(msg, businessId, {
        conversationId: remoteJid,
        ...(selfChat ? { selfTest: true } : {}),
        ...(storedMedia ? { media: storedMedia } : {}),
      });
      const response = await forwardToBackend(payload);
      await sendReplies(remoteJid, response?.replies);
    } catch (err) {
      log.error({ err: err.message, businessId }, 'failed to handle inbound message');
    }
  }

  // ── socket lifecycle ──────────────────────────────────────────────────────
  async function start(fresh = false) {
    if (stopped) return;
    try {
      if (fresh) {
        // Wipe dead creds so we re-link with a new QR, and forget the old
        // identity — the re-link may be to a DIFFERENT number.
        ownJid = null;
        ownLid = null;
        await internalApi.saveCreds(businessId, freshCredsBlob());
      } else if (authStore) {
        // Reconnect: flush any pending debounced save so the reload below picks up
        // the latest keys instead of stale ones.
        await authStore.flush().catch(() => {});
      }
      authStore = await useDbAuthState(businessId);

      let version;
      try {
        ({ version } = await fetchLatestBaileysVersion());
      } catch (e) {
        log.warn({ err: e.message, businessId }, 'fetchLatestBaileysVersion failed; using bundled');
        version = undefined;
      }

      sock = makeWASocket({
        version,
        auth: authStore.state,
        logger: require('pino')({ level: 'silent' }),
        printQRInTerminal: false,
        browser: ['Bizz_up Gateway', 'Chrome', '1.0'],
        markOnlineOnConnect: false,
        getMessage: async (key) => sentMessages.get(key?.id) || undefined,
        syncFullHistory: false,
      });

      sock.ev.on('creds.update', () => {
        captureOwnIds();
        authStore.saveCreds();
      });

      sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
          qrcode
            .toDataURL(qr, { margin: 1, width: 320 })
            .then((dataUrl) => {
              state.qrDataUrl = dataUrl;
              state.status = 'qr_pending';
              log.info({ businessId }, 'QR ready for business');
              void report();
            })
            .catch((e) => log.error({ err: e.message, businessId }, 'failed to render QR'));
        }

        if (connection === 'open') {
          state.status = 'connected';
          state.qrDataUrl = null;
          reconnectAttempts = 0;
          captureOwnIds();
          log.info({ businessId, hasOwnJid: Boolean(ownJid), hasOwnLid: Boolean(ownLid) }, 'business WhatsApp open');
          void report();
        }

        if (connection === 'close') {
          const statusCode =
            lastDisconnect?.error instanceof Boom
              ? lastDisconnect.error.output?.statusCode
              : undefined;
          const loggedOut = statusCode === DisconnectReason.loggedOut;
          log.warn({ businessId, statusCode, loggedOut }, 'business WhatsApp closed');

          if (stopped) return;
          if (loggedOut) {
            // Dead creds — wipe + re-link with a fresh QR (auto-recovery).
            state.status = 'logged_out';
            state.qrDataUrl = null;
            void report();
            restart(true);
          } else {
            state.status = 'disconnected';
            void report();
            restart(false);
          }
        }
      });

      sock.ev.on('messages.upsert', ({ messages, type }) => {
        for (const msg of messages || []) {
          if (msg.messageStubType === WAMessageStubType.CIPHERTEXT) {
            handleDecryptFailure(msg);
            continue;
          }
          if (type !== 'notify') continue;
          handleInbound(msg);
        }
      });
    } catch (err) {
      log.error({ err: err.message, businessId }, 'failed to start session; retrying');
      state.status = 'disconnected';
      restart(false);
    }
  }

  function restart(fresh) {
    if (stopped || reconnectTimer) return;
    const delay = fresh
      ? RECONNECT_BASE_MS
      : Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** reconnectAttempts);
    reconnectAttempts += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      start(fresh);
    }, delay);
  }

  async function stop() {
    stopped = true;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    try {
      if (authStore) await authStore.flush();
    } catch {
      /* best-effort */
    }
    try {
      sock?.end?.(undefined);
    } catch {
      /* best-effort */
    }
    sock = null;
  }

  return {
    businessId,
    start,
    stop,
    sendText,
    getState: () => state,
  };
}

module.exports = { createSession };
