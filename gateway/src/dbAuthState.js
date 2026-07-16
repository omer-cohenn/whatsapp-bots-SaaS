'use strict';

// חנות auth של Baileys מגובה-DB (M6b): טוענת/שומרת את מצב ה-session כ-blob מוצפן דרך הבקאנד.

// Drop-in replacement for Baileys' `useMultiFileAuthState`, but instead of files
// on disk it persists the WHOLE auth state ({creds, keys}) as ONE JSON blob,
// base64-encoded, through the backend internal API — which envelope-encrypts it
// with the crown KEK into whatsapp_credentials (per business). The gateway itself
// never sees the encryption key.
//
// Why a single blob (not per-key rows): Baileys touches signal keys constantly;
// round-tripping each key to the DB would be far too chatty. We keep the state in
// memory and DEBOUNCE-write the blob after changes. The rare loss of the last few
// keys on a hard crash is self-healing — our Bad-MAC recovery clears the affected
// contact's session and it renegotiates.

const {
  initAuthCreds,
  BufferJSON,
  proto,
} = require('@whiskeysockets/baileys');

const internalApi = require('./internalApi');
const { loadConfig } = require('./config');
const { createLogger } = require('./logger');

const config = loadConfig();
const log = createLogger(config.logLevel);

// Coalesce bursts of key writes into one PUT.
const SAVE_DEBOUNCE_MS = 800;

/**
 * Build a DB-backed auth state for one business.
 * @param {string} businessId
 * @returns {Promise<{state: object, saveCreds: () => void, flush: () => Promise<void>}>}
 */
async function useDbAuthState(businessId) {
  // 1) Load the existing blob (or start fresh). A hard load failure THROWS so the
  //    caller doesn't start a session on empty creds while the backend is down.
  const { authState } = await internalApi.loadCreds(businessId);

  let creds;
  /** keys[type][id] = value */
  let keys = {};

  if (authState) {
    try {
      const json = Buffer.from(authState, 'base64').toString('utf-8');
      const parsed = JSON.parse(json, BufferJSON.reviver);
      creds = parsed.creds;
      keys = parsed.keys || {};
    } catch (err) {
      // Corrupt blob → treat as no creds (fresh QR) rather than crash. Safe log.
      log.error({ err: err.message }, 'dbAuthState: corrupt blob; starting fresh');
      creds = initAuthCreds();
      keys = {};
    }
  } else {
    creds = initAuthCreds();
  }

  // 2) Debounced blob save. Serializes {creds, keys} exactly like the file store.
  let saveTimer = null;
  let saving = Promise.resolve();

  async function doSave() {
    saveTimer = null;
    const blob = JSON.stringify({ creds, keys }, BufferJSON.replacer);
    const b64 = Buffer.from(blob, 'utf-8').toString('base64');
    saving = internalApi.saveCreds(businessId, b64);
    await saving;
  }

  function scheduleSave() {
    if (saveTimer) return;
    saveTimer = setTimeout(() => {
      doSave().catch((err) =>
        log.error({ err: err.message }, 'dbAuthState: save failed')
      );
    }, SAVE_DEBOUNCE_MS);
  }

  // Force any pending write out now (used on shutdown / logout).
  async function flush() {
    if (saveTimer) {
      clearTimeout(saveTimer);
      await doSave().catch((err) =>
        log.error({ err: err.message }, 'dbAuthState: flush failed')
      );
    }
    await saving;
  }

  const state = {
    creds,
    keys: {
      // Mirror useMultiFileAuthState.get: return {id: value} for the requested
      // ids, reconstructing app-state-sync-key values into their proto form.
      get: async (type, ids) => {
        const data = {};
        const bucket = keys[type] || {};
        for (const id of ids) {
          let value = bucket[id];
          if (type === 'app-state-sync-key' && value) {
            value = proto.Message.AppStateSyncKeyData.fromObject(value);
          }
          data[id] = value;
        }
        return data;
      },
      // Mirror useMultiFileAuthState.set: merge (null => delete), then persist.
      set: async (data) => {
        for (const category in data) {
          if (!keys[category]) keys[category] = {};
          for (const id in data[category]) {
            const value = data[category][id];
            if (value) {
              keys[category][id] = value;
            } else {
              delete keys[category][id];
            }
          }
        }
        scheduleSave();
      },
    },
  };

  // saveCreds persists the top-level creds (Baileys calls it on creds.update).
  function saveCreds() {
    scheduleSave();
  }

  // Bad-MAC recovery helper: delete every stored Signal session for the given
  // user id(s) so their next message negotiates a fresh session. Session keys are
  // stored under keys.session as "<user>.<device>"; we match by user to clear ALL
  // devices. Returns how many were cleared, and persists if anything changed.
  function clearSessionsForUsers(userIds) {
    const bucket = keys.session || {};
    let cleared = 0;
    for (const id of Object.keys(bucket)) {
      const user = id.split('.')[0].split(':')[0];
      if (userIds.has(user)) {
        delete bucket[id];
        cleared += 1;
      }
    }
    if (cleared) scheduleSave();
    return cleared;
  }

  return { state, saveCreds, flush, clearSessionsForUsers };
}

module.exports = { useDbAuthState };
