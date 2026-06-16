'use strict';

const pino = require('pino');

/**
 * Structured logger with a HARD redaction rule.
 *
 * SHARED SPEC (hard rule): NEVER log secrets, the gateway token, the QR, or
 * message bodies / phone numbers. This is the receive spike — it must not leak.
 *
 * We enforce this at the logger, not by discipline:
 *  - `redact.paths` censors these keys if they ever appear on a log object.
 *  - We never pass raw message bodies / phone numbers / the QR into log calls
 *    anywhere in this codebase (see index.js — only safe, derived metadata is
 *    logged, e.g. a truncated message id and a boolean "hasText").
 */
function createLogger(level) {
  return pino({
    level: level || 'info',
    base: { service: 'gateway' },
    timestamp: pino.stdTimeFunctions.isoTime,
    redact: {
      paths: [
        // secrets / auth
        'token',
        'gatewayApiToken',
        'GATEWAY_API_TOKEN',
        'authorization',
        'headers.authorization',
        'headers["x-gateway-token"]',
        'req.headers.authorization',
        'req.headers["x-gateway-token"]',
        // QR — session-hijack material, never log it
        'qr',
        'qrDataUrl',
        // message content / PII
        'text',
        'body',
        'message',
        'from',
        'phone',
        'pushName',
        'push_name',
        'raw',
      ],
      censor: '[REDACTED]',
    },
  });
}

module.exports = { createLogger };
