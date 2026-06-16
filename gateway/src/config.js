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
 * In dev, values come from a git-ignored .env.local. We do NOT depend on a
 * dotenv loader inside the image — compose / `--env-file` inject these. For
 * local `node src/index.js` runs, export them in your shell (see README).
 */

/** A fixed account id for the spike. Real design assigns one per business (M6). */
const GATEWAY_ACCOUNT_ID = 'spike';

function requireEnv(name) {
  const raw = process.env[name];
  const value = typeof raw === 'string' ? raw.trim() : '';
  if (!value) {
    // FAIL CLOSED — never start without the secret. Do not print the value.
    throw new Error(
      `[config] Missing required env var ${name}. Refusing to boot. ` +
        `Set it in gateway/.env.local (dev) or your secret manager (prod).`
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
  const config = {
    port: Number(process.env.PORT) || 3000,
    gatewayAccountId: GATEWAY_ACCOUNT_ID,

    // Required secret — shared with the backend, sent as X-Gateway-Token.
    gatewayApiToken: requireEnv('GATEWAY_API_TOKEN'),

    // Where inbound messages are POSTed. Default is the compose service URL
    // (NOT a secret), so this is allowed to have a constant default.
    backendWebhookUrl:
      (process.env.BACKEND_WEBHOOK_URL || '').trim() ||
      'http://backend:8000/webhook/whatsapp',

    // Spike-only: where Baileys persists its auth state on disk.
    // Real design encrypts these creds in the DB (M6). This dir is gitignored.
    authDir: (process.env.GATEWAY_AUTH_DIR || '').trim() || './auth',

    logLevel: (process.env.LOG_LEVEL || '').trim() || 'info',
  };

  return Object.freeze(config);
}

module.exports = { loadConfig, GATEWAY_ACCOUNT_ID };
