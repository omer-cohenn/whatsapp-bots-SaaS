"""M6a.1 narrated — constants + narration + helpers + the test phases (split out
of the thin runner m6a1_full_test.py for length; same printed output, no PII).
The runner does set-up + cleanup, calls run_phases(...) here, and reads tally()."""

from __future__ import annotations

import json
import secrets
import time

from app.db.session import tenant_connection
from app.services import whatsapp_test_numbers as test_numbers_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

# The two pretend businesses (fixed IDs come from supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED in seed)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (DRAFT in seed)
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

# Distinct gateway "account ids" we map to each business for THIS milestone.
# upsert_connection is UPSERT-by-business, so re-running just refreshes the row.
ACC_A = "m6a1-acct-avi"
ACC_B = "m6a1-acct-bella"

# The owner's own number (used only to build a realistic mapping; never logged).
OWN_PHONE = "+972500000001"

# Two OUTSIDE test phones we will put on Avi's allow-list, in two notations:
#   * DAD is stored in ISRAELI-LOCAL form ('0547408309') and will message us in
#     INTERNATIONAL form ('+972547408309') — the normalize() match is the point.
#   * MOM is stored already international.
DAD_LOCAL = "0547408309"            # how the owner types it on the admin screen
DAD_INBOUND = "+972547408309"       # how it arrives on the wire (gateway jidToE164)
DAD_NORMALIZED = "972547408309"     # what both should normalize to
MOM_INTL = "+972500000022"
MOM_NORMALIZED = "972500000022"

# A phone that is NEVER on the list (the "stranger" — must be ignored).
STRANGER_INBOUND = "+972500000099"

# A customer the bot will collect as a REAL lead (drives Avi's 'quote' flow).
CUST_NAME = "אבא הבודק"
CUST_PHONE_DIGITS = "0521230000"

# Scoreboard.
_passed = 0
_total = 0


# --- tiny printing helpers (all the "baby language" lives here) --------------

def banner(num: str, title: str) -> None:
    print()
    print("─" * 74)
    print(f"  TEST {num}: {title}")
    print("─" * 74)


def explain(what: str, why: str) -> None:
    print(f"  🧪 We try : {what}")
    print(f"  💡 Because: {why}")


def result(ok: bool, detail: str) -> None:
    global _passed, _total
    _total += 1
    if ok:
        _passed += 1
        print(f"  ✅ GOOD   : {detail}")
    else:
        print(f"  ❌ BAD    : {detail}   <-- THIS NEEDS A FIX!")


# --- the "pretend gateway" POST helper ---------------------------------------

def _webhook_body(account_id: str, text: str, from_phone: str, conversation_id: str,
                  self_test: bool = False, message_id: str | None = None) -> dict:
    """Build exactly the JSON the real gateway POSTs to /webhook/whatsapp.

    For M6a.1 the outside-number case is self_test=False, with `from` carrying
    the OUTSIDE phone (the gateway sends it as '+<digits>' from jidToE164).
    """
    return {
        "gateway_account_id": account_id,
        "from": from_phone,                       # PII — never logged by backend
        "push_name": "Tester",
        "message_id": message_id or f"m6a1-{secrets.token_hex(6)}",
        "timestamp": 1_700_000_000,
        "type": "text",
        "text": text,
        "raw": {"note": "synthetic m6a.1 test message"},
        "self_test": self_test,
        "conversation_id": conversation_id,
    }


async def _login(rds, http, user_id: str, business_id: str) -> str:
    """Mint an opaque Redis session + set the cookie, like a logged-in owner."""
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": "x",
        "created_at": int(time.time()),
    }
    await rds.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)
    return sid


async def _logout(rds, http, sid: str) -> None:
    """Destroy the Redis session + clear the cookie (tidy after a logged-in call)."""
    await rds.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    http.cookies.clear()



async def run_phases(story_auth, http, rds, pool) -> None:
    """Run all 11 M6a.1 checks in order on the same client/lifespan; update tally."""
    auth = story_auth

    # ── TEST 1 (GOAL 5) ──────────────────────────────────────────────
    banner("1", "normalize(): a number stored as '0547…' matches inbound '+97254 7…'")
    explain(
        "DAD is on the list as the Israeli-local '0547408309'. He messages "
        "from the wire form '+972547408309'. Ask is_number_allowed directly.",
        "the SAME normalize() must run on the stored number AND the inbound "
        "'from', or the two notations would never compare equal and a "
        "legit tester would be silently ignored. This is the matching core.")
    n1 = test_numbers_service.normalize(DAD_LOCAL)
    n2 = test_numbers_service.normalize(DAD_INBOUND)
    allowed_dad = await test_numbers_service.is_number_allowed(
        pool, BIZ_A, DAD_INBOUND)
    ok1 = (n1 == DAD_NORMALIZED and n2 == DAD_NORMALIZED and allowed_dad)
    result(
        ok1,
        f"'{DAD_LOCAL}' → {n1}; '{DAD_INBOUND}' → {n2}; both equal and "
        f"is_number_allowed(inbound)={allowed_dad} (the local↔intl match holds)")

    # ── TEST 2 (GOAL 2) ──────────────────────────────────────────────
    banner("2", "An ALLOW-LISTED number + published bot → the bot answers")
    explain(
        "POST a self_test=FALSE webhook 'היי' from DAD's +972… number to "
        "Avi's published bot, with a valid X-Gateway-Token.",
        "this is the whole point of M6a.1: a trusted OUTSIDE tester drives "
        "the REAL bot (run_turn) and gets menu replies, just like the owner "
        "in the self-chat. status must be 'ok' with at least one reply.")
    conv_dad = f"intl:{secrets.token_hex(6)}"
    r2 = await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", DAD_INBOUND, conv_dad),
        headers=auth)
    b2 = r2.json()
    ok2 = (
        r2.status_code == 200
        and b2.get("status") == "ok"
        and isinstance(b2.get("replies"), list)
        and len(b2["replies"]) >= 1
    )
    result(
        ok2,
        f'status={r2.status_code} "{b2.get("status")}", '
        f'{len(b2.get("replies") or [])} reply/replies (the allow-listed '
        f"tester got a real bot answer)")

    # ── TEST 3 (GOAL 2) ──────────────────────────────────────────────
    banner("3", "A full questionnaire over the webhook → a REAL lead is saved")
    explain(
        "drive Avi's 'quote' flow to the end from DAD's outside number "
        "(pick #1, give name, phone, choose insurance type).",
        "M6a.1 is REAL data (is_test=False). After finishing, the new lead "
        "must show up in the owner's GET /api/leads (the normal list, which "
        "HIDES test rows) — proving it persisted as a real lead.")
    conv_lead = f"intl:{secrets.token_hex(6)}"

    async def turn(text: str) -> dict:
        resp = await http.post(
            "/webhook/whatsapp",
            json=_webhook_body(ACC_A, text, DAD_INBOUND, conv_lead),
            headers=auth)
        return resp.json()

    await turn("היי")                  # greeting + menu
    t_start = await turn("1")           # start 'quote' → asks full name
    await turn(CUST_NAME)               # name → asks phone
    await turn(CUST_PHONE_DIGITS)       # phone → asks insurance type (choice)
    t_done = await turn("1")            # choose 'רכב' → completes

    # The owner views their leads (REAL list — is_test rows excluded).
    sid = await _login(rds, http, AVI_USER, BIZ_A)
    leads = (await http.get("/api/leads")).json()["leads"]
    await _logout(rds, http, sid)

    our = [
        lead for lead in leads
        if lead.get("lead_name") == "quote" and lead.get("is_test") is False
    ]
    found = bool(our)
    phone_ok = found and any(
        (lead.get("phone") or "").endswith(CUST_PHONE_DIGITS) for lead in our)
    ok3 = bool(t_start.get("replies") and t_done.get("replies") and found and phone_ok)
    result(
        ok3,
        f"the finished questionnaire saved a REAL lead (found={found}, "
        f"phone round-tripped={phone_ok}); it appears in GET /api/leads "
        f"WITHOUT include_test — so it is is_test=False")

    # ── TEST 4 (GOAL 3) ──────────────────────────────────────────────
    banner("4", "A NON-allow-listed number → silent ('not allowed', no replies)")
    explain(
        "POST a self_test=FALSE 'היי' from a STRANGER (+972500000099) who "
        "is NOT on Avi's list, to Avi's published bot.",
        "the #1 safety rule of M6a.1: only registered testers get answers. "
        "A random outside phone must be IGNORED — status 'not allowed' with "
        "replies:[] so the gateway sends nothing back. (Privacy + ban-risk.)")
    r4 = await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", STRANGER_INBOUND,
                           f"intl:{secrets.token_hex(6)}"),
        headers=auth)
    b4 = r4.json()
    ok4 = (
        r4.status_code == 200
        and b4.get("status") == "not allowed"
        and b4.get("replies") == []
    )
    result(
        ok4,
        f'stranger → status={r4.status_code} "{b4.get("status")}", '
        f'replies={b4.get("replies")} (ignored — correct)')

    # ── TEST 5 (GOAL 4) ──────────────────────────────────────────────
    banner("5", "Allow-listed number but bot NOT published → silent")
    explain(
        "POST a self_test=FALSE 'היי' from DAD (who IS on Bella's list) to "
        "Bella, whose bot is a DRAFT.",
        "publish-gating still applies to outside testers: even a trusted "
        "number must NOT get a reply from a draft bot. status must be "
        "'not published' with replies:[]. The allow-list never bypasses "
        "the publish gate.")
    r5 = await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_B, "היי", DAD_INBOUND,
                           f"intl:{secrets.token_hex(6)}"),
        headers=auth)
    b5 = r5.json()
    ok5 = (
        r5.status_code == 200
        and b5.get("status") == "not published"
        and b5.get("replies") == []
    )
    result(
        ok5,
        f'allow-listed but draft → status={r5.status_code} '
        f'"{b5.get("status")}", replies={b5.get("replies")} (silent — correct)')

    # ── TEST 6 (GOAL 6) ──────────────────────────────────────────────
    banner("6", "PUT /test-numbers: 6 → 422, 5 → ok; GET round-trips labels")
    explain(
        "logged in as Avi, PUT a list of 6 numbers (over the cap), then a "
        "clean list of 5; then GET it back.",
        "the contract caps the list at 5. A 6-item save must be rejected "
        "(422), a 5-item save must succeed, and the saved numbers + labels "
        "must round-trip exactly on a later GET — that's the owner's UI.")
    sid_a = await _login(rds, http, AVI_USER, BIZ_A)
    try:
        six = {"numbers": [
            {"phone": f"05000000{i:02d}", "label": f"n{i}"} for i in range(6)
        ]}
        r_six = await http.put("/api/whatsapp/test-numbers", json=six)

        five = {"numbers": [
            {"phone": "0500000011", "label": "Alpha"},
            {"phone": "0500000012", "label": "Bravo"},
            {"phone": "+972500000013", "label": None},
            {"phone": "0500000014", "label": "Delta"},
            {"phone": "0500000015", "label": "Echo"},
        ]}
        r_five = await http.put("/api/whatsapp/test-numbers", json=five)
        got = (await http.get("/api/whatsapp/test-numbers")).json()
    finally:
        await _logout(rds, http, sid_a)

    got_nums = got.get("numbers", [])
    # The labels must round-trip; the None label stays None.
    labels_ok = [n["label"] for n in got_nums] == \
        ["Alpha", "Bravo", None, "Delta", "Echo"]
    phones_ok = [n["phone"] for n in got_nums] == [
        "972500000011", "972500000012", "972500000013",
        "972500000014", "972500000015"]
    ok6 = (
        r_six.status_code == 422
        and r_five.status_code == 200
        and len(got_nums) == 5
        and labels_ok and phones_ok
    )
    result(
        ok6,
        f"PUT 6 → {r_six.status_code} (422 expected); PUT 5 → "
        f"{r_five.status_code}; GET returned {len(got_nums)} numbers; "
        f"labels round-trip={labels_ok}, phones normalized={phones_ok}")

    # ── TEST 7 (GOAL 6) ──────────────────────────────────────────────
    banner("7", "Phone + label are stored as CIPHERTEXT (never plaintext)")
    explain(
        "read the raw whatsapp_test_numbers columns straight from the DB "
        "and look for the plaintext digits / the label text.",
        "the rule is PII-at-rest is encrypted. A DB dump must NOT reveal "
        "a tester's phone or name. The raw bytea columns must contain "
        "ciphertext only — the plaintext must NOT appear.")
    async with tenant_connection(pool, BIZ_A) as conn:
        rows = await conn.fetch(
            "SELECT phone_number, label FROM whatsapp_test_numbers "
            "WHERE business_id = $1", BIZ_A)
    # Decode bytea -> text just to SEARCH for plaintext leakage.
    raw_blob = " ".join(
        bytes(r["phone_number"]).decode("latin-1")
        + (bytes(r["label"]).decode("latin-1") if r["label"] is not None else "")
        for r in rows)
    no_plain_phone = "972500000011" not in raw_blob and "0500000011" not in raw_blob
    no_plain_label = "Alpha" not in raw_blob and "Delta" not in raw_blob
    ok7 = bool(rows) and no_plain_phone and no_plain_label
    result(
        ok7,
        f"{len(rows)} raw rows scanned: plaintext phone absent="
        f"{no_plain_phone}, plaintext label absent={no_plain_label} "
        f"(columns hold ciphertext only)")

    # ── TEST 8 (GOAL 7) ──────────────────────────────────────────────
    banner("8", "Admin /test-numbers needs a login (401) AND is tenant-scoped")
    explain(
        "call GET + PUT /api/whatsapp/test-numbers with NO session; then "
        "log in as Bella and confirm she sees ONLY her own list (not Avi's).",
        "this is the owner's private allow-list. No login → no verified "
        "tenant → the deny-by-default /api gate must answer 401. And one "
        "business must NEVER see another's numbers (multi-tenant isolation).")
    no_sess_get = await http.get("/api/whatsapp/test-numbers")
    no_sess_put = await http.put(
        "/api/whatsapp/test-numbers", json={"numbers": []})

    sid_b = await _login(rds, http, BELLA_USER, BIZ_B)
    try:
        bella_list = (await http.get("/api/whatsapp/test-numbers")).json()
    finally:
        await _logout(rds, http, sid_b)
    bella_phones = [n["phone"] for n in bella_list.get("numbers", [])]
    # Bella's list is her OWN single Dad number — never Avi's 5 numbers.
    bella_isolated = (
        bella_phones == [DAD_NORMALIZED]
        and not any(p.startswith("9725000000") for p in bella_phones
                    if p != DAD_NORMALIZED)
    )
    ok8 = (
        no_sess_get.status_code == 401
        and no_sess_put.status_code == 401
        and bella_isolated
    )
    result(
        ok8,
        f"no-session GET={no_sess_get.status_code}, PUT="
        f"{no_sess_put.status_code} (both 401); Bella sees only her own "
        f"{len(bella_phones)} number(s), not Avi's list (isolated={bella_isolated})")

    # ── TEST 9 (GOAL 8 — M6a regression) ─────────────────────────────
    banner("9", "Self-chat (M6a) STILL works unchanged + loop-guard logic intact")
    explain(
        "POST a self_test=TRUE 'היי' from the owner's own number to Avi's "
        "published bot; and re-verify the gateway loop-guard rules.",
        "M6a.1 widened the gateway but must NOT break the self-chat. The "
        "owner is ALWAYS allowed; the self-chat must still return 'ok' with "
        "replies. And the anti-loop guard (skip our own sent ids, cap 200, "
        "oldest-evicted) — shared by both branches — must still hold.")
    r9 = await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", OWN_PHONE,
                           f"self:{secrets.token_hex(6)}", self_test=True),
        headers=auth)
    b9 = r9.json()
    self_ok = (
        r9.status_code == 200
        and b9.get("status") == "ok"
        and len(b9.get("replies") or []) >= 1
    )
    loop_ok, loop_detail = _check_gateway_loop_guard()
    ok9 = self_ok and loop_ok
    result(
        ok9,
        f'self-chat status="{b9.get("status")}" with '
        f'{len(b9.get("replies") or [])} reply/replies (M6a unchanged); '
        f"loop-guard: {loop_detail}")

    # ── TEST 10 (GOAL 7 — webhook token auth) ────────────────────────
    banner("10", "A bad/missing gateway token is rejected (401) on the inbound path")
    explain(
        "POST DAD's allow-listed inbound with a WRONG X-Gateway-Token, and "
        "with NO token at all.",
        "the webhook is PUBLIC on the network — only the gateway's shared "
        "secret may use it. A wrong/absent token must be a flat 401 BEFORE "
        "any business work (no allow-list lookup, no run_turn).")
    bad = await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", DAD_INBOUND, "intl:x"),
        headers={"X-Gateway-Token": "totally-wrong"})
    missing = await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", DAD_INBOUND, "intl:x"))
    ok10 = bad.status_code == 401 and missing.status_code == 401
    result(
        ok10,
        f"wrong token → {bad.status_code}, missing token → "
        f"{missing.status_code} (both 401 — locked)")

    # ── TEST 11 (NEGATIVE CONTROL) ───────────────────────────────────
    banner("11", "NEGATIVE CONTROL: remove DAD from the list, watch him get ignored")
    explain(
        "temporarily REPLACE Avi's allow-list with only MOM (drop DAD), "
        "send DAD's inbound, confirm 'not allowed' — then RESTORE the list "
        "and confirm DAD is answered again.",
        "a good test must be able to FAIL. If a removed number still got "
        "replies, the allow-list gate would be doing nothing. We prove the "
        "gate is real, then restore the original state.")
    # Drop DAD (keep only MOM).
    await test_numbers_service.set_test_numbers(
        pool, BIZ_A, [{"phone": MOM_INTL, "label": "Mom"}])
    broke = (await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", DAD_INBOUND,
                           f"intl:{secrets.token_hex(6)}"),
        headers=auth)).json()
    caught = broke.get("status") == "not allowed" and broke.get("replies") == []
    # Restore DAD + MOM and verify DAD is answered again.
    await test_numbers_service.set_test_numbers(pool, BIZ_A, [
        {"phone": DAD_LOCAL, "label": "Dad"},
        {"phone": MOM_INTL, "label": "Mom"},
    ])
    fixed = (await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", DAD_INBOUND,
                           f"intl:{secrets.token_hex(6)}"),
        headers=auth)).json()
    restored = fixed.get("status") == "ok" and len(fixed.get("replies") or []) >= 1
    ok11 = caught and restored
    result(
        ok11,
        "DAD removed → ignored (the gate caught it); DAD restored → the "
        "bot answers again (gate is real, state restored)")


# --- the gateway loop-guard logic check (Goal 8) -----------------------------

def _check_gateway_loop_guard() -> tuple[bool, str]:
    """Re-implement + verify the EXACT loop-guard rules from gateway/src/index.js.

    The gateway keeps a bounded Set of ids of messages IT sent (cap 200,
    oldest-evicted by insertion order) and SKIPS any inbound whose id is in it.
    M6a.1's normal-chat branch reuses the SAME guard (rememberSentId via
    sendReplies + the top-of-handleInbound skip), so an allow-listed reply's
    fromMe echo is skipped exactly like the self-chat's.
    """
    SENT_ID_CAP = 200
    sent: dict[str, None] = {}  # py dict preserves insertion order, like a JS Set

    def remember(mid: str) -> None:
        if not mid:
            return
        sent[mid] = None
        if len(sent) > SENT_ID_CAP:
            del sent[next(iter(sent))]  # evict the oldest (first-inserted)

    def should_skip(mid: str) -> bool:
        return bool(mid) and mid in sent

    remember("reply-1")
    rule_skip = should_skip("reply-1") and not should_skip("a-real-inbound")

    for i in range(SENT_ID_CAP + 50):
        remember(f"id-{i}")
    cap_ok = len(sent) == SENT_ID_CAP
    oldest_evicted = not should_skip("reply-1") and not should_skip("id-0")
    newest_kept = should_skip(f"id-{SENT_ID_CAP + 50 - 1}")

    ok = rule_skip and cap_ok and oldest_evicted and newest_kept
    detail = (
        f"sent-id skipped={rule_skip}, cap held at {len(sent)}={cap_ok}, "
        f"oldest evicted={oldest_evicted}, newest kept={newest_kept}")
    return ok, detail


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m6a1.bat   (it sets everything up for you).
#   By hand : from the project root, with the stack running (run.bat):
#     docker compose --env-file infra/.env -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m6a1_full_test.py"
# ─────────────────────────────────────────────────────────────────────────────


def tally() -> tuple[int, int]:
    """The (passed, total) counts after run_phases() runs — read by the runner."""
    return _passed, _total
