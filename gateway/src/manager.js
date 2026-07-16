'use strict';

// מנהל ה-sessions (M6b): socket אחד לכל עסק. סורק את הבקאנד מדי כמה שניות ומתאים
// את קבוצת ה-sessions הפעילים — מפעיל חדשים, עוצר כאלה שהוסרו.

const { loadConfig } = require('./config');
const { createLogger } = require('./logger');
const internalApi = require('./internalApi');
const { createSession } = require('./session');

const config = loadConfig();
const log = createLogger(config.logLevel);

// businessId -> session
const sessions = new Map();
let pollTimer = null;
let syncing = false;

// Reconcile the live sessions with the backend's desired set. Idempotent and
// self-guarded so overlapping ticks can't double-start a session.
async function syncSessions() {
  if (syncing) return;
  syncing = true;
  try {
    const desired = await internalApi.listSessions();
    // Empty list from a transient backend error must NOT tear down live sessions:
    // only ADD on an empty result, never remove. (A real "no businesses" state is
    // indistinguishable from a blip, so we err on keeping sockets alive.)
    const desiredSet = new Set(desired);

    // Start any newly-desired business.
    for (const businessId of desiredSet) {
      if (!sessions.has(businessId)) {
        const session = createSession(businessId);
        sessions.set(businessId, session);
        log.info({ businessId }, 'starting session');
        void session.start();
      }
    }

    // Stop sessions no longer desired — but only when the backend actually
    // returned a non-empty list (guard against a transient empty response).
    if (desiredSet.size > 0) {
      for (const [businessId, session] of sessions) {
        if (!desiredSet.has(businessId)) {
          log.info({ businessId }, 'stopping session (no longer listed)');
          sessions.delete(businessId);
          void session.stop();
        }
      }
    }
  } catch (err) {
    log.error({ err: err.message }, 'session sync failed');
  } finally {
    syncing = false;
  }
}

function startManager() {
  log.info('session manager started');
  void syncSessions();
  pollTimer = setInterval(() => void syncSessions(), config.sessionPollMs);
}

async function stopManager() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  const all = [...sessions.values()];
  sessions.clear();
  await Promise.all(all.map((s) => s.stop().catch(() => {})));
}

function getSession(businessId) {
  return sessions.get(businessId);
}

function sessionCount() {
  return sessions.size;
}

module.exports = { startManager, stopManager, getSession, sessionCount };
