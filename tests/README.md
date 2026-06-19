# Tests — how to check the M2 "tenant wall"

**The tenant wall = the locks that stop one business from seeing another business's data.**
This folder is your one-click way to prove those locks work.

## The easy way (recommended)

1. Start Docker Desktop.
2. Double-click **`test_m2.bat`**.

It does everything for you and prints, in plain language, every lock it tries to
break and whether the lock held. At the end you want to see:

```
🎉 RESULT: 12/12 locks held. One business CANNOT see another's data. 🧱🔒
```

`test_m2.bat` runs five steps:
1. brings the app up (and applies the database migrations),
2. adds two pretend businesses (Avi Insurance + Bella Barber),
3. runs the **full explained test** — 12 checks, each with *what we try* / *why it matters* / *result*,
4. runs the **strict pass/fail gate** (the pytest version CI uses),
5. **breaks one lock on purpose** to prove the test would catch a real bug, then fixes it.

## What each test covers (the 12 checks)

| # | In plain words | The bug it prevents |
|---|---|---|
| 1 | the app is NOT the all-powerful master user | old app used a master key that saw everything |
| 2 | a business sees its OWN leads | (the normal allowed case) |
| 3 | a business CANNOT read another's leads | the core data leak |
| 4 | a business CANNOT plant a row in another | data poisoning |
| 5 | no login = no data at all | old "shared tenant" fallback leak |
| 6 | the app key can't touch the WhatsApp key | full WhatsApp-account takeover |
| 7 | stored phones are scrambled | a stolen DB copy stays unreadable |
| 8 | the right key still unlocks them | the business can read its own data |
| 9 | a wrong key SCREAMS, never fakes success | old app silently returned gibberish |
| 10 | phone "fingerprint" is steady but un-reversible | find a customer without storing the phone |
| 11 | the live-chat store keeps businesses apart | Redis has no built-in wall — our code is the wall |
| 12 | many users at once never get mixed up | the scariest bug: identity leaking between requests |

## Where the test code lives

The actual test code is in **`backend/tests/`** (it has to run *inside* the backend
container, which is where the database keys and code live):

- `m2_full_test.py` — the full explained 12-check test (what `test_m2.bat` step 3 runs).
- `isolation/test_tenant_wall.py` — the strict pytest gate (step 4).
- `test_secret_guard.py` — checks secrets never leak into text/logs.
- `demo_isolation.py` — the shorter 9-line "story" version.

## Running by hand (no .bat)

From the project root, with the stack running:

```bash
# the full explained test
docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
  run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m2_full_test.py"

# the strict pytest gate
docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
  run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && \
  PYTHONPATH=/app python -m pytest tests/isolation tests/test_secret_guard.py -q"
```

(If you have `make` available — e.g. via WSL — `make demo-isolation`, `make isolation`,
and `make demo-break` are the same things.)

---

# M3 — login & accounts

**M2 built the wall between businesses. M3 builds the front door:** how a person
proves who they are (Google login), how they automatically get their *own*
business, and how the app keeps every `/api` door locked until they're in.

## The easy way

1. Start Docker Desktop.
2. Double-click **`test_m3.bat`**.

At the end you want to see, in order:

```
🎉 RESULT: 5/5 checks held. The front door is safe ...   (the M3 test)
... passed ...                                            (the strict pytest gate)
🎉 RESULT: 12/12 locks held. ...                          (the M2 wall, still green)
```

`test_m3.bat` runs five steps: (1) bring the stack up + migrate, (2) seed the
pretend businesses, (3) the **full explained M3 test** (5 checks), (4) the
**strict pytest gate**, and (5) **re-runs the M2 tenant wall** to prove M3 did
not weaken it (must still print 12/12).

## What the 5 M3 checks mean

| # | In plain words | The bug it prevents |
|---|---|---|
| 1 | a logged-OUT stranger is locked out of every `/api` door | a page answering without a login |
| 2 | a brand-new Google user auto-gets ONE business (twice = same one) | duplicate businesses / no tenant on signup |
| 3 | a logged-IN owner sees ONLY their own business + leads | one owner seeing another's data |
| 4 | logging OUT truly destroys the session (401 again after) | a "logged out" cookie that still works |
| 5 | `/healthz` stays public | breaking uptime monitoring by gating it |

## Where the M3 test code lives

- `backend/tests/m3_full_test.py` — the full explained 5-check test (step 3).
- `backend/tests/test_auth_gate.py` — the strict pytest gate (step 4): the
  deny-by-default `/api` gate, valid/forged/destroyed sessions, the
  `/auth/google` redirect + Redis state, and `provision_owner` idempotency.

Both run the real ASGI app in-process (httpx `ASGITransport`) against the real
Redis + Postgres, so nothing is mocked.

## ⚠️ The one thing the script CANNOT test: a real Google login

The automated tests inject a real session the way login does, but they do **not**
click through Google's consent screen — OAuth needs a real Google account and a
real browser, which a script can't drive. **Test that part by hand once:**

1. Open **http://localhost:5173** and click **Sign in with Google**.
2. You should land back logged in, seeing your own business name.
3. Click **Log out** — you should be bounced back to the login page.

(Requires the `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI`
/ `SESSION_SECRET` values to be filled in `infra/.env.local`; the backend
refuses to boot without them.)

## Running by hand (no .bat)

```bash
# the full explained M3 test
docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
  run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m3_full_test.py"

# the strict M3 pytest gate
docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
  run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && \
  PYTHONPATH=/app python -m pytest tests/test_auth_gate.py -q"
```

---

# M4 — the AI bot builder

**M2 built the wall, M3 built the front door, and M4 adds the bot builder:** the
owner-facing screen + API where a business designs its WhatsApp bot — the
question flows it asks customers and the bot's name/personality — optionally with
an **AI helper** that suggests config changes.

## The easy way

1. Start Docker Desktop.
2. Double-click **`test_m4.bat`**.

At the end you want to see, in order:

```
🎉 RESULT: 9/9 checks held. The bot builder is safe ...   (the M4 test)
... passed ...                                            (the strict M4 pytest gate)
🎉 RESULT: 12/12 locks held. ...                          (the M2 wall, still green)
... passed ...                                            (the isolation suite, now incl. M4 tables)
```

`test_m4.bat` runs five steps: (1) bring the stack up + migrate, (2) seed the
two pretend businesses **and their bot configs**, (3) the **full explained M4
test** (9 checks), (4) the **strict M4 pytest gate**, and (5) **re-runs the M2
tenant wall + the isolation suite** to prove M4 did not weaken anything.

## The one thing to understand: the AI is FAKED in the tests

The AI helper talks to Google's **Gemini**. Calling the real Gemini in a test
would need an internet key, cost money, and be flaky. So the tests plug in a
tiny **pretend Gemini** using the seam the backend left open
(`app.services.bot_builder_ai.get_gemini_client`):

- The **narrated test** (`m4_full_test.py`) sets `get_gemini_client` to a fake
  that returns a canned answer.
- The **pytest gate** (`test_bot_builder.py`) does the same with
  `monkeypatch.setattr(bot_builder_ai, "get_gemini_client", lambda: FakeClient())`.

So **you do NOT need a real `GEMINI_API_KEY`** to run the M4 tests, and nothing
hits the internet. One check on purpose runs with **no key at all** to prove the
AI door answers `503` ("AI helper not set up") while the rest of the app stays up.

## What the 9 M4 checks mean

| # | In plain words | The bug it prevents |
|---|---|---|
| 1 | a logged-OUT stranger is locked out of every `/api/bot/*` door | anyone reading/rewriting a business's bot |
| 2 | a logged-in owner sees their OWN bot config | (the normal allowed case) |
| 3 | one owner CANNOT see another's bot config | the core tenant leak, now for bot configs |
| 4 | a saved bot loads back exactly as saved | "save" silently losing/changing the config |
| 5 | a broken bot config is refused with 422 | a dead-end bot (e.g. a choice with no options) |
| 6 | the AI replies AND applies a good suggestion + remembers the chat | the AI assist being useless or forgetful |
| 7 | the AI's BAD idea is dropped, chat still flows | trusting raw AI output → a broken/poisoned bot |
| 8 | the build-chat history is private to each business | one owner reading another's AI conversation |
| 9 | with NO AI key, the AI door says 503 (app still up) | the whole app crashing just because AI isn't set up |

## What the strict pytest gate adds (`test_bot_builder.py`)

The 25 pytest cases are the CI version of the above, plus extra edge cases:
all four routes 401 without a session (parametrized) and reject a forged cookie;
settings round-trip + tenant isolation over HTTP; **six** out-of-bounds bodies
each rejected with 422 (missing profile, choice-without-options, lead-with-0-steps,
human_handoff-with-steps, non-snake_case flow name, >20 flows); an over-long AI
message → 422; the mocked AI applies a valid change and persists exactly two rows
(`user`+`assistant`) **for that tenant only**; an invalid AI change is dropped but
the reply + chat persist; history is oldest→newest and tenant-scoped; no key → 503;
and pure-function unit checks for `extract_changes` / `merge_changes` (including
that the reserved `knowledge` key for Phase-3 RAG is stripped, never written).

## Where the M4 test code lives

- `backend/tests/m4_full_test.py` — the full explained 9-check test (step 3).
- `backend/tests/test_bot_builder.py` — the strict pytest gate (step 4).
- `backend/tests/isolation/test_tenant_wall.py` — **extended**: now also proves
  `bot_settings` and `bot_builder_messages` are tenant-isolated, run as the
  non-service `app_role` (so RLS is really exercised).

## Running by hand (no .bat)

```bash
# the full explained M4 test (uses the PRETEND Gemini; no key needed)
docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
  run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m4_full_test.py"

# the strict M4 pytest gate (Gemini mocked via monkeypatch; one case = no key → 503)
docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
  run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && \
  PYTHONPATH=/app python -m pytest tests/test_bot_builder.py -q"
```

## ⚠️ The one thing the script CANNOT test: the REAL Gemini + the browser UI

The automated tests fake the AI and drive the API directly. To see the **real**
AI helper and the **builder screen** in a browser, do this by hand once:

1. Put a real `GEMINI_API_KEY` in `infra/.env.local`, then restart the stack
   (`stop.bat` then `run.bat`). *(Without a key, the AI panel correctly shows
   "unavailable" — that is the 503 path, by design.)*
2. Open **http://localhost:5173**, sign in, and open **בונה הבוט** (the bot builder).
3. Add a flow, add a step (try a "choice" step — it must demand 2–12 options),
   and click **שמור שינויים** (save). Reload — your changes should still be there.
4. Click **עוזר ה-AI שלך** (the AI assistant button), send a message, and confirm
   it replies in Hebrew; if it proposes a change, confirm it appears in the editor.
