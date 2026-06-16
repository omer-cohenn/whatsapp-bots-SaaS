# WhatsApp Gateway — System Map

Scope: two read-only locations were scanned.

- `C:\Users\עמר כהן\Desktop\qr_wa_scanner` — Node.js / Baileys gateway (`index.js`) plus a React/Vite UI (`frontend/`, `App.jsx`).
- `C:\Users\עמר כהן\Desktop\last_bo` — Python FastAPI backend (`main.py`) and the WhatsApp client helper `wapy_client/client.py`.

> **Headline architectural finding (needs flagging):** The two halves do **not** talk to each other. The Baileys gateway and the Python backend are **two independent, alternative WhatsApp integrations**. The Python backend (`last_bo`) sends and receives messages through **Meta's official WhatsApp Cloud API via the `pywa` library** — it never calls the Baileys gateway's REST API. The Baileys gateway (`qr_wa_scanner`) is a self-contained service with its own React UI and its own webhook-forwarding mechanism; nothing in `last_bo` registers itself as that gateway's webhook or calls its `/send` endpoint. Details and evidence below.

---

## 0. How the pieces actually relate

`wapy_client/client.py` (the file the task names as "the Python side that talks to the gateway") does **not** talk to the Baileys gateway:

```python
# C:\Users\עמר כהן\Desktop\last_bo\wapy_client\client.py:1-16
from pywa import WhatsApp
wa = WhatsApp(
    token=os.environ["WHATSAPP_TOKEN"],
    phone_id=os.environ["WHATSAPP_PHONE_NUMBER_ID"],
    app_id=os.environ["WHATSAPP_APP_ID"],
    app_secret=os.environ["WHATSAPP_APP_SECRET"],
)
def send_message(phone: str, text: str) -> None:
    wa.send_message(to=phone, text=text)
```

`pywa` is a client for **Meta's WhatsApp Cloud API** (confirmed in `last_bo/requirements.txt:8` and `last_bo/.env:5-10`, which holds `WHATSAPP_TOKEN`, `WHATSAPP_APP_ID`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WEBHOOK_VERIFY_TOKEN`). It does not point at `localhost:3000` and contains no Baileys/gateway reference.

Correspondingly, `last_bo/main.py`'s inbound `/webhook` parses the **Meta Cloud API** envelope, not the Baileys gateway payload:

```python
# C:\Users\עמר כהן\Desktop\last_bo\main.py:329-333
entry   = body["entry"][0]
change  = entry["changes"][0]["value"]
message = change["messages"][0]
phone   = message["from"]
text    = message["text"]["body"]
```

That shape (`entry[0].changes[0].value.messages[0]`) is Meta's. It is **incompatible** with what the Baileys gateway POSTs (a flat object with `from`, `text`, `accountId`, `raw`, etc. — see §3). So even if the Baileys gateway were pointed at `main.py:/webhook`, every message would fall into the `except (KeyError, IndexError): return {"status":"ignored"}` branch (`main.py:335-336`).

The only consumer of the Baileys gateway found in either tree is the gateway's **own** React UI (`qr_wa_scanner/frontend/src/App.jsx`, `qr_wa_scanner/App.jsx`), which hits `http://localhost:3000` (`App.jsx:3 const API_BASE = "http://localhost:3000";`).

**Conclusion:** The Baileys gateway is a standalone / alternative path; the live bot in `last_bo` runs on Meta Cloud API. The sections below document the Baileys gateway as requested and note where the Python side diverges. (Whether `qr_wa_scanner` is intended to eventually replace the Meta path is *needs verification*.)

---

## 1. Connection approach (Baileys)

File: `qr_wa_scanner/index.js`.

- Built on `@whiskeysockets/baileys` `^6.7.8` (`package.json:12`). Socket created in `startAccount()` via `makeWASocket({ version, logger, printQRInTerminal:false, auth: state, browser:['WA Gateway','Chrome','1.0'] })` (`index.js:96-102`).
- Baileys version is fetched once at startup with `fetchLatestBaileysVersion()` and cached in `waVersion` (`index.js:89-92`).
- **Login is QR-based** (not pairing-code). On `connection.update`, when a `qr` field arrives it is rendered to a base64 PNG data-URL via `qrcode.toDataURL(qr)` and stored on the account as `account.qr`, with `account.status='qr'` (`index.js:112-116`). The QR is exposed through `GET /status` and the `/accounts` endpoints for the UI to display (`index.js:195-205`, `index.js:265-286`). The user scans it from WhatsApp → Linked Devices (README:87-94).
- **Staying connected:** on `connection==='open'` the status flips to `connected` and the phone number is derived from `state.creds.me.id` (`index.js:133-138`). Baileys maintains the WebSocket; credential refreshes are persisted via the `creds.update` event handler (`index.js:107`).
- Connection lifecycle states surfaced to clients: `connecting` | `qr` | `connected` | `disconnected` (`index.js:104`, `:122`, `:133`; README:119).

## 2. Credential storage — SECURITY FLAG

Files: `qr_wa_scanner/index.js:11`, `:16-69`; directory `qr_wa_scanner/credentials/`.

- Custom auth store `useSingleFileAuthState(accountId)` writes the entire Baileys auth state (creds + signal keys) to **one plaintext JSON file** per account:
  `credentials/<accountId>/creds.json` (`index.js:17-19`).
- Saving: `fs.writeFileSync(file, JSON.stringify(state, BufferJSON.replacer, 2))` (`index.js:35`). `BufferJSON.replacer` only base64-encodes binary buffers — it is **serialization, not encryption**. The file is human-readable JSON.
- Loading: `JSON.parse(fs.readFileSync(file,'utf8'), BufferJSON.reviver)` (`index.js:24`).
- **Confirmed: session credentials are stored as UNENCRYPTED JSON on disk.** No encryption-at-rest, no OS keychain, no passphrase. Anyone with read access to `credentials/<id>/creds.json` obtains the full WhatsApp session (`noiseKey`, identity keys, signal keys, `me.id`) and can impersonate / hijack the linked number.
- `credentials/` is gitignored (`.gitignore:3`), which prevents accidental commit but does nothing for on-disk protection.
- **Current state on disk:** `credentials/default/` exists but is **empty** — no `creds.json` is present (verified by directory listing). So no live session is persisted right now; the format finding is established from the code, not from an existing file. (Whether a session was ever scanned is *needs verification*.)

## 3. Message flow IN (Baileys gateway → webhook)

File: `qr_wa_scanner/index.js:141-163`.

- Handler on `sock.ev.on('messages.upsert', ...)`. Guards: only `type==='notify'` (`:142`), only if a `webhookUrl` is registered for that account (`:143`), and skips `msg.key.fromMe` (`:145`).
- For each inbound message it builds this payload and `axios.post`s it to the registered webhook with an 8s timeout (`:146-158`):

```json
{
  "accountId": "default",
  "phone": "972501234567",
  "from": "972509999999@s.whatsapp.net",
  "pushName": "John",
  "messageId": "ABC...",
  "timestamp": 1718000000,
  "text": "Hello!",
  "type": "conversation",
  "raw": { /* full Baileys msg object */ }
}
```

(`index.js:146-156`; documented identically in README:170-184.)

- The webhook URL is **runtime-registered** via `POST /webhook { url, accountId }` and stored in-memory on the account object (`index.js:234-241`, `account.webhookUrl`). It is **not** persisted; it is lost on restart, and the `.env` `WEBHOOK_URL` (`.env:9`) is **never read by `index.js`** (no reference to it anywhere in the file).
- **Divergence from the Python side:** as shown in §0, `last_bo/main.py:/webhook` expects the Meta Cloud API envelope, not this flat payload. So this flow currently delivers to the gateway's own webhook consumer / a user-supplied URL, **not** to `last_bo`.

## 4. Message flow OUT (backend → user)

Two distinct outbound paths exist, matching the two integrations:

**A. Baileys gateway path (`qr_wa_scanner`):**
- `POST /send { to, message, accountId }` (auth-protected) → resolves target account (explicit `accountId` or first connected), normalizes the number, then `sock.sendMessage(jid, { text })` (`index.js:207-219`).
- Number normalization is **hardcoded to Israel**: `` `972${to.replace(/^0/, '')}@s.whatsapp.net` `` when `to` has no `@` (`index.js:213`). Non-Israeli local numbers would be mis-prefixed.
- `POST /send-group { groupId, message, accountId }` for group JIDs (`index.js:221-232`).

**B. The path the live Python bot actually uses (`last_bo`):**
- `last_bo/main.py` imports `send_message` from `wapy_client.client` at each reply site and calls it (`main.py:315-316`, `:364-365`, `:381-382`, `:389-390`; also `bot/graph.py:7`). That function calls `wa.send_message()` on the **Meta Cloud API** (`wapy_client/client.py:15-16`). This bypasses the Baileys gateway entirely.

## 5. Multi-tenant routing

**Baileys gateway:** It *does* support multiple accounts technically:
- An `accounts` Map keyed by `accountId` holds `{ sock, status, qr, phone, webhookUrl }` (`index.js:73`, `:104`).
- `POST /accounts`, `GET /accounts`, `GET /accounts/:id`, `DELETE /accounts/:id` manage slots (`index.js:264-299`). Each account is one linked WhatsApp number with its own session dir under `credentials/<accountId>/`.
- Routing of *sends* is by `accountId` in the request body, or falls back to `firstConnected()` (`index.js:210`, `:224`, `:237`, `:251`).
- **Routing of *inbound* messages is per-account too** — the payload carries `accountId` and `phone` (`index.js:147-149`), and each account forwards to **its own** `webhookUrl`. So in principle this is multi-tenant (one number = one business via separate accountIds + separate webhook URLs).
- **But the default deployment is effectively single-tenant:** `loadSavedAccounts()` restores whatever dirs exist, and if none exist it auto-creates a single slot literally named `'default'` (`index.js:166-180`, `:177-179`). The shipped/default state is a single shared `credentials/default` session. There is no `business_id` concept in the gateway; "tenancy" is only as granular as how many `accountId` slots an operator manually creates, and the legacy endpoints (`/status`, `/send` without `accountId`) silently target "first connected", collapsing multi-account behavior to one. **Net: the gateway as configured is single-tenant (`credentials/default` shared session); multi-tenant is possible but opt-in and unused here.**

**Python backend (`last_bo`) — the live system:** Tenancy is by `business_id`, derived two ways:
- Per logged-in user (email) for the admin/config UI: `_business_id(request)` → session user email (`main.py:95-99`).
- For the **inbound webhook**, there is **no per-message tenant routing** — it calls `_business_id_from_config()` which reads a single global `client_config/system_prompt.json`'s `business_id` (`main.py:87-92`, `:338`). Config dirs are per-business (`_config_dir` / `_config_dir_create`, `main.py:36-49`) but the webhook always resolves to the one config-file business. Since there is a single Meta `WHATSAPP_PHONE_NUMBER_ID` in `.env`, the inbound bot path is **single-tenant in practice** (one Meta number → one business). Multi-tenant inbound routing by the receiving phone number is not implemented (*needs verification* if intended).

## 6. Reliability

Baileys gateway (`index.js`):
- **Reconnection:** on `connection==='close'` it always schedules `setTimeout(() => startAccount(accountId), 3000)` (`index.js:129-130`). It reconnects on *any* close, not only transient ones.
- **Logout / session loss:** if the close reason is `DisconnectReason.loggedOut` (Boom statusCode check, `index.js:119-120`), it calls `deleteCredentials()` to wipe `credentials/<id>/` (`:126-128`) and then still restarts → a fresh QR is generated for re-linking. Correct behavior, but the wipe is unconditional on logout and irreversible.
- **Error handling:** webhook POST failures are caught and only logged (`index.js:159-161`) — **no retry, no queue, no dead-letter.** A webhook that is briefly down loses the message permanently. Same for the 8s axios timeout.
- `/send` and `/send-group` wrap `sendMessage` in try/catch and return 500 on failure (`index.js:216-218`, `:229-231`); no retry.
- **Single points of failure:**
  - In-memory only: the `accounts` Map and each `webhookUrl` are RAM-resident. A process restart loses all registered webhook URLs (sessions survive on disk, webhooks do not). The bot would go silent until `POST /webhook` is re-issued.
  - One process, one port (3000); no clustering. If it crashes, all accounts go down.
  - `waVersion` fetched once at boot; if `fetchLatestBaileysVersion()` fails at startup the first `startAccount` rejects (no catch around `loadSavedAccounts()` → `startAccount()` at `index.js:307`).
  - Hardcoded Israel prefix (`index.js:213`) breaks non-IL numbers.
  - Default API token `'my-secret-token'` (`index.js:12`, `.env:7`) — see security flags.

Python backend (`last_bo/main.py`), for completeness:
- Inbound webhook swallows parse errors as `{"status":"ignored"}` (`main.py:335-336`); each send is individually try/except-wrapped (`main.py:317-318`, `:366-367`).
- Reliability of outbound depends on Meta Cloud API; no retry/queue here either.

## 7. `.env`, `package.json`, ports

`qr_wa_scanner/package.json`:
- name `whatsapp-gateway`, `main: index.js`.
- scripts: `start: node index.js`, `dev: nodemon index.js` (`package.json:6-9`).
- deps: `@whiskeysockets/baileys ^6.7.8`, `@hapi/boom ^10.0.1`, `express ^4.18.3`, `axios ^1.6.8`, `cors ^2.8.5`, `pino ^8.19.0`, `qrcode ^1.5.3`, `dotenv ^16.4.5`; devDep `nodemon ^3.1.0` (`package.json:10-22`).

`qr_wa_scanner/.env`:
- `PORT=3000` (`.env:3`) — backend port (default 3000 if unset, `index.js:14`).
- `API_TOKENS=my-secret-token` (`.env:7`) — comma-split into a valid-token list; falls back to `API_TOKEN` then literal `'my-secret-token'` (`index.js:12-13`).
- `WEBHOOK_URL=` (`.env:9`) — present but **unused by `index.js`**.
- Auth: `authMiddleware` checks `x-api-token` header or `?token=` query against `API_TOKENS` (`index.js:187-191`). CORS is wide open: `app.use(cors())` with no origin restriction (`index.js:184`).
- Frontend (Vite) runs separately on port **5173** (`start.bat:55,63`); UI base URL is `http://localhost:3000` (`App.jsx:3`).

For reference, `last_bo` runs FastAPI on `APP_PORT=8000` (`last_bo/.env:13`) and uses Meta Cloud API creds (`last_bo/.env:5-10`).

---

## Flags for security-issues.md

1. **Unencrypted WhatsApp session credentials on disk (HIGH).** `credentials/<accountId>/creds.json` is plaintext JSON (`index.js:34-35`, `:24`). Full session theft → number hijack/impersonation. No encryption-at-rest, no keychain.
2. **Default / weak API token (HIGH).** Ships with `API_TOKENS=my-secret-token` (`.env:7`) and the same value is hardcoded as the fallback (`index.js:12`). If deployed unchanged, the send/webhook/account-management API is effectively unauthenticated.
3. **Unauthenticated `GET /status` exposes the QR code (MEDIUM).** `/status` has no auth and returns the live login QR data-URL when status is `qr` (`index.js:195-205`). Anyone reaching the port during a (re)link window can scan the QR and link *their* device to the number.
4. **Wide-open CORS (MEDIUM).** `app.use(cors())` with no allow-list (`index.js:184`) lets any web origin call the API (token still required for protected routes, but combined with the default token this is dangerous).
5. **Token accepted via query string (LOW/MEDIUM).** `?token=` (`index.js:188`) leaks the API token into server/proxy logs and browser history.
6. **Secrets committed in plaintext `.env` (HIGH, cross-repo, `last_bo`).** `last_bo/.env` contains a live Meta `WHATSAPP_TOKEN`, `WHATSAPP_APP_SECRET`, a Gemini API key, a Supabase service key + DB password, a Google OAuth client secret, and `ENCRYPTION_KEY`/`SESSION_SECRET` (`last_bo/.env:2-32`). Read-only here, but these are real-looking credentials on disk and should be rotated / secret-managed. (Reported as observed, not modified.)
7. **`WEBHOOK_VERIFY_TOKEN=secret` (MEDIUM, `last_bo`).** Trivial Meta webhook verify token (`last_bo/.env:10`).

## Flags for bugs.md

1. **Gateway and Python backend are not wired together (HIGH / architectural).** `last_bo` uses Meta Cloud API via `pywa`; nothing registers `last_bo` as the Baileys gateway's webhook, and the payload shapes are incompatible (Baileys flat payload §3 vs Meta envelope `main.py:329-333`). The Baileys gateway forwards a payload that `last_bo` would parse as `{"status":"ignored"}`. If the intent is for the Baileys gateway to feed the bot, an adapter/translation layer is missing. (Intent: *needs verification*.)
2. **Registered webhook URL is not persisted (HIGH).** `account.webhookUrl` lives only in the in-memory `accounts` Map (`index.js:104`, `:239`). Any restart drops it and inbound forwarding silently stops until `POST /webhook` is re-sent. `.env WEBHOOK_URL` is defined but never read to seed it.
3. **No retry / no durability on inbound webhook delivery (MEDIUM).** A failed/timed-out `axios.post` is only logged (`index.js:159-161`); the message is lost. No queue, retry, or dead-letter.
4. **Hardcoded Israel (`972`) phone normalization (MEDIUM).** `/send` prefixes any non-JID number with `972` (`index.js:213`), corrupting non-Israeli numbers despite the README claiming international support (README:138).
5. **Unconditional reconnect can hot-loop (LOW/MEDIUM).** `connection==='close'` always reschedules `startAccount` after 3s regardless of cause (`index.js:129-130`); a persistently failing/banned session retries forever every 3s with no backoff.
6. **Startup path has no error handling (LOW).** If `fetchLatestBaileysVersion()` rejects at boot, the initial account start fails uncaught (`index.js:88-92`, `:307`).
7. **Inbound bot path is single-tenant despite per-business config dirs (MEDIUM, `last_bo`).** `/webhook` resolves tenant from one global `client_config/system_prompt.json` via `_business_id_from_config()` (`main.py:338`, `:87-92`), so a single Meta number maps to a single business; per-business config dirs exist but inbound routing ignores the recipient number. (Intent: *needs verification*.)
8. **Empty `credentials/default/` (INFO).** The default account dir exists but has no `creds.json` (verified by listing), so the gateway currently has no persisted session — first run will require a fresh QR scan.
