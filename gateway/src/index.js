'use strict';

// בוטסטרפ דק: טעינת config+logger, הקמת express, חיווט ראוטים, הרמת שרת, הדלקת סוקט.

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
 *
 * This file is a THIN bootstrap — the real work lives in:
 *   socket.js  — the Baileys socket, self-chat detection, inbound handling.
 *   webhook.js — forward-to-backend + send-replies.
 *   routes.js  — the HTTP routes (/healthz /info /qr /qr.json /send-bot /inbox /send).
 */

const express = require('express');

const { loadConfig } = require('./config');
const { createLogger } = require('./logger');

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

// Loaded AFTER the fail-closed config check above so a missing secret exits with
// the clean console.error message (these modules call loadConfig too, but it is
// idempotent — env-only, already validated here).
const { registerRoutes } = require('./routes');
const { startManager } = require('./manager');

// ── HTTP server ──────────────────────────────────────────────────────────────
const app = express();
// Parse JSON + form bodies (needed for the dev-only POST /send form).
app.use(express.json());
app.use(express.urlencoded({ extended: false }));

// Wire every route (/healthz /info /qr /qr.json /send-bot /inbox /send).
registerRoutes(app);

app.listen(config.port, () => {
  log.info(
    { port: config.port, backendWebhookUrl: config.backendWebhookUrl },
    'gateway HTTP server listening'
  );
  // Kick off the per-business session manager after the server is up so /healthz
  // responds immediately. The manager polls the backend for which businesses to
  // connect and opens one WhatsApp socket per business.
  startManager();
});

// Never crash silently on an unhandled rejection (Baileys can throw async).
process.on('unhandledRejection', (reason) => {
  log.error({ err: reason instanceof Error ? reason.message : String(reason) }, 'unhandledRejection');
});
