'use strict';

/**
 * Fail-closed configuration.
 *
 * SHARED SPEC: refuse to boot if a required secret is missing. NO "change-me" /
 * constant defaults for secrets. Required for this minimal run:
 *   - GATEWAY_API_TOKEN  (shared service token, both sides — gateway sends it,
 *                         backend verifies it on every webhook call)
 *   - BACKEND_WEBHOOK_URL (where to forward inbound messages; defaults to the
 *                          docker-compose service URL, which is a safe non-secret)
 *
 * In dev, values come from a git-ignored .env. We do NOT depend on a
 * dotenv loader inside the image — compose / `--env-file` inject these. For
 * local `node src/index.js` runs, export them in your shell (see README).
 */

function requireEnv(name) {
  const raw = process.env[name];
  const value = typeof raw === 'string' ? raw.trim() : '';
  if (!value) {
    // FAIL CLOSED — never start without the secret. Do not print the value.
    throw new Error(
      `[config] Missing required env var ${name}. Refusing to boot. ` +
        `Set it in gateway/.env (dev) or your secret manager (prod).`
    );
  }
  // Guard against the classic placeholder-as-secret bug.
  const lowered = value.toLowerCase();
  if (lowered === 'change-me' || lowered === 'changeme' || lowered === 'my-secret-token') {
    throw new Error(
      `[config] Env var ${name} is set to a forbidden placeholder value. ` +
        `Use a real high-entropy secret. Refusing to boot.`
    );
  }
  return value;
}

function loadConfig() {
  // Backend base URL (internal Docker network). Both the webhook and the M6b
  // internal WA API live under it. Derived from BACKEND_WEBHOOK_URL when only that
  // is set, so a single override keeps them in sync. Not a secret → safe default.
  const backendBaseUrl =
    (process.env.BACKEND_BASE_URL || '').trim() ||
    (process.env.BACKEND_WEBHOOK_URL || '').trim().replace(/\/webhook\/whatsapp\/?$/, '') ||
    'http://backend:8000';

  const config = {
    port: Number(process.env.PORT) || 3000,

    // Required secret — shared with the backend, sent as X-Gateway-Token (both on
    // the inbound webhook AND every internal WA API call).
    gatewayApiToken: requireEnv('GATEWAY_API_TOKEN'),

    // Base URL of the backend (internal network).
    backendBaseUrl,

    // Where inbound messages are POSTed. Default is the compose service URL
    // (NOT a secret), so this is allowed to have a constant default.
    backendWebhookUrl:
      (process.env.BACKEND_WEBHOOK_URL || '').trim() ||
      `${backendBaseUrl}/webhook/whatsapp`,

    // M6b: how often the session manager re-polls the backend for the set of
    // businesses that should have a live WhatsApp socket (picks up new links /
    // removals). Milliseconds.
    sessionPollMs: Number(process.env.SESSION_POLL_MS) || 15000,

    logLevel: (process.env.LOG_LEVEL || '').trim() || 'info',
  };

  return Object.freeze(config);
}

module.exports = { loadConfig };
