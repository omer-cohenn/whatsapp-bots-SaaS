"""M12 narrated — shared constants + narration + helpers + the 13 test phases.

This module is NOT run directly. The thin runner m12_full_test.py opens the
pools + the app lifespan/client, then calls run_phases(...) here. Splitting the
phases + helpers out of the runner keeps each file under 500 lines WITHOUT
changing a single byte of printed output — narration goes through the local
banner/explain/result (English M12 wording), and the runner reads the final
counts via tally(). Nothing here prints a secret or PII.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import date

import asyncpg

from app.db.session import tenant_connection
from app.services import usage as usage_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

# The two pretend businesses (fixed IDs from supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (DRAFT)

# The mall owner (admin). ADMIN_EMAILS in infra/.env.local includes this email.
ADMIN_EMAIL = "oyc3333@gmail.com"
# A normal shop owner — NOT on the admin allow-list.
AVI_USER = "google-sub-avi"
NONADMIN_EMAIL = "avi@example.com"

# The gateway account we map to Avi so we can drive a webhook bot turn.
ACC_A = "m12-acct-avi"
OWN_PHONE = "+972500000001"

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


# --- session + webhook helpers -----------------------------------------------

async def _login(redis, http, user_id: str, email: str, business_id: str) -> str:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": email, "name": user_id, "picture": "",
        "business_id": business_id, "business_name": "x",
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)
    return sid


async def _logout(redis, http, sid: str) -> None:
    await redis.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    http.cookies.clear()


def _webhook_body(account_id: str, text: str, conv: str) -> dict:
    return {
        "gateway_account_id": account_id, "from": OWN_PHONE, "push_name": "Owner",
        "message_id": f"m12-{secrets.token_hex(6)}", "timestamp": 1_700_000_000,
        "type": "text", "text": text, "raw": {"note": "synthetic m12 test"},
        "self_test": True, "conversation_id": conv,
    }


def _superuser_dsn() -> str:
    """Build the superuser DSN from POSTGRES_* (present in the backend container).
    Used ONLY to peek at / reset the control-room tables the app role can't read."""
    return (f"postgresql://{os.environ['POSTGRES_USER']}:"
            f"{os.environ['POSTGRES_PASSWORD']}@postgres:5432/"
            f"{os.environ['POSTGRES_DB']}")


async def run_phases(http, auth, redis, su, pool, admin_user) -> None:
    """Run all 13 M12 checks in order, on the same client/lifespan; update the tally."""

    # ── TEST 1 — the locked door (no login) ──────────────────────────
    banner("1", "No login → the whole control room is shut (401)")
    explain(
        "call the admin pages (overview, businesses, one business, usage, "
        "plans) with NO login at all",
        "the control room crosses the tenant wall — if it were reachable "
        "without a login, anyone on the network could read every shop. It "
        "must be a flat 401 before any work happens.")
    routes = [
        "/api/admin/overview", "/api/admin/businesses",
        f"/api/admin/businesses/{BIZ_A}",
        f"/api/admin/businesses/{BIZ_A}/usage", "/api/admin/plans",
    ]
    codes = [(await http.get(r)).status_code for r in routes]
    result(all(c == 401 for c in codes),
           f"all admin pages without a login → {codes} (all 401 — shut)")

    # ── TEST 2 — a normal owner is NOT the mall owner (403) ──────────
    banner("2", "A normal shop owner logs in → control room says 403")
    explain(
        "log in as Avi (a normal shop owner, NOT on the admin list) and "
        "open every admin page",
        "a shop owner may manage THEIR shop, never the mall. The admin door "
        "checks the email against the allow-list LIVE on every request, so "
        "Avi must get 403 everywhere — even though he is logged in.")
    sid = await _login(redis, http, AVI_USER, NONADMIN_EMAIL, BIZ_A)
    codes = [(await http.get(r)).status_code for r in routes]
    patch_code = (await http.patch(
        f"/api/admin/businesses/{BIZ_A}/subscription",
        json={"plan_code": "pro", "status": "active"})).status_code
    await _logout(redis, http, sid)
    result(all(c == 403 for c in codes) and patch_code == 403,
           f"normal owner → reads {codes}, change-plan {patch_code} "
           f"(all 403 — not the mall owner)")

    # ── TEST 3 — the admin gets in, and /api/me knows who's boss ─────
    banner("3", "Omer (admin) logs in → 200 everywhere; /api/me says is_admin")
    explain(
        "log in as Omer (email on the admin list), open every admin page, "
        "and read /api/me; then read /api/me again as Avi",
        "the mall owner must get IN (200) — and the app needs a truthful "
        "is_admin flag so the UI shows the 'Management' tab to Omer ONLY. "
        "That flag is computed live, never a stored session field.")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    codes = [(await http.get(r)).status_code for r in routes]
    me_admin = (await http.get("/api/me")).json()
    await _logout(redis, http, sid)
    sid = await _login(redis, http, AVI_USER, NONADMIN_EMAIL, BIZ_A)
    me_user = (await http.get("/api/me")).json()
    await _logout(redis, http, sid)
    result(all(c == 200 for c in codes)
           and me_admin.get("is_admin") is True
           and me_user.get("is_admin") is False,
           f"admin reads {codes} (all 200); /api/me is_admin = "
           f"Omer:{me_admin.get('is_admin')} / Avi:{me_user.get('is_admin')}")

    # ── TEST 4 — the overview KPIs reconcile with the real numbers ───
    banner("4", "The overview KPIs add up to the real database truth")
    explain(
        "read the overview, then bump Avi's message counter by 3 and set "
        "Avi=suspended, Bella=cancelled, and read the overview again",
        "the control room's headline numbers must MATCH reality. We change "
        "known things by known amounts and check the totals move by exactly "
        "that much — no drift, no guessing.")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    base = (await http.get("/api/admin/overview")).json()
    await _logout(redis, http, sid)
    async with tenant_connection(pool, BIZ_A) as conn:
        await usage_service.bump(conn, BIZ_A, usage_service.METRIC_MSG_IN, 3)
    async with su.acquire() as conn:
        for biz, st in ((BIZ_A, "suspended"), (BIZ_B, "cancelled")):
            await conn.execute(
                "INSERT INTO subscriptions (business_id, plan_code, status) "
                "VALUES ($1,'basic',$2) ON CONFLICT ON CONSTRAINT "
                "subscriptions_pkey DO UPDATE SET status = EXCLUDED.status",
                biz, st)
            await conn.execute(
                "UPDATE businesses SET is_active=$2 WHERE id=$1",
                biz, st == "active")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    after = (await http.get("/api/admin/overview")).json()
    await _logout(redis, http, sid)
    kpi_ok = (
        after["total_businesses"] == base["total_businesses"]
        and after["suspended_count"] == base["suspended_count"] + 1
        and after["cancelled_count"] == base["cancelled_count"] + 1
        and after["active_count"] == base["active_count"] - 2
        and after["msgs_today"] == base["msgs_today"] + 3
    )
    result(kpi_ok,
           f"suspended {base['suspended_count']}→{after['suspended_count']}, "
           f"cancelled {base['cancelled_count']}→{after['cancelled_count']}, "
           f"active {base['active_count']}→{after['active_count']}, "
           f"msgs_today {base['msgs_today']}→{after['msgs_today']} "
           f"(moved by exactly +3) — all reconcile")
    # reset the subscriptions we seeded so the rest starts clean.
    async with su.acquire() as conn:
        await conn.execute(
            "DELETE FROM subscriptions WHERE business_id = ANY($1::uuid[])",
            [BIZ_A, BIZ_B])
        await conn.execute(
            "UPDATE businesses SET is_active=true WHERE id = ANY($1::uuid[])",
            [BIZ_A, BIZ_B])

    # ── TEST 5 — the businesses list: identity + defaults + search ───
    banner("5", "The businesses list shows owner + plan defaults + search works")
    explain(
        "as the admin, list the businesses and search for 'Bella'",
        "with no plan row yet, a shop should read as plan 'free' / status "
        "'active' (sensible defaults). The owner email + created date must "
        "be there. And search must narrow the table (Bella, not Avi).")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    listing = (await http.get("/api/admin/businesses?limit=200")).json()
    bella = (await http.get("/api/admin/businesses?search=Bella")).json()
    await _logout(redis, http, sid)
    rows = {r["business_id"]: r for r in listing["businesses"]}
    a = rows.get(BIZ_A, {})
    bella_ids = {r["business_id"] for r in bella["businesses"]}
    list_ok = (
        a.get("plan_code") == "free" and a.get("status") == "active"
        and a.get("owner_email") == NONADMIN_EMAIL
        and a.get("created_at") is not None
        and isinstance(a.get("leads_count"), int)
        and BIZ_B in bella_ids and BIZ_A not in bella_ids
    )
    result(list_ok,
           f"Avi shows plan={a.get('plan_code')}/{a.get('status')}, "
           f"owner={a.get('owner_email')}; search 'Bella' → "
           f"{len(bella_ids)} row(s), Avi excluded")

    # ── TEST 6 — pagination bounds are guarded ───────────────────────
    banner("6", "Page size is bounded (junk values are rejected, not crashed)")
    explain(
        "ask for limit=1 (OK), then limit=0, limit=999 and offset=-1 (junk)",
        "a back-office page must never let a caller pull unbounded rows or "
        "pass nonsense paging. In-range works; out-of-range is a clean 422.")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    ok1 = await http.get("/api/admin/businesses?limit=1&offset=0")
    c0 = (await http.get("/api/admin/businesses?limit=0")).status_code
    c999 = (await http.get("/api/admin/businesses?limit=999")).status_code
    cneg = (await http.get("/api/admin/businesses?offset=-1")).status_code
    await _logout(redis, http, sid)
    result(ok1.status_code == 200 and len(ok1.json()["businesses"]) <= 1
           and c0 == 422 and c999 == 422 and cneg == 422,
           f"limit=1 → 200 (≤1 row); limit=0→{c0}, limit=999→{c999}, "
           f"offset=-1→{cneg} (junk all 422)")

    # ── TEST 7 — one business profile, and an unknown id → 404 ───────
    banner("7", "A single-business profile loads; an unknown shop → 404")
    explain(
        "open Avi's profile, then open a made-up business id and a broken id",
        "the profile shows the WhatsApp connection status + counters for one "
        "shop. A shop that doesn't exist (or a garbage id) must be a clean "
        "404, not a crash or an empty 200.")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    detail = (await http.get(f"/api/admin/businesses/{BIZ_A}")).json()
    c_unknown = (await http.get(
        "/api/admin/businesses/cccccccc-cccc-cccc-cccc-cccccccccccc"
    )).status_code
    c_bad = (await http.get("/api/admin/businesses/not-a-uuid")).status_code
    await _logout(redis, http, sid)
    result(detail.get("business_id") == BIZ_A
           and detail.get("wa_status") in {"connected", "connecting", "disconnected"}
           and c_unknown == 404 and c_bad == 404,
           f"Avi profile wa_status={detail.get('wa_status')}; unknown id→"
           f"{c_unknown}, broken id→{c_bad} (both 404)")

    # ── TEST 8 — change the plan, and prove the audit trail is written ─
    banner("8", "Change a plan → it sticks, AND an audit row records WHO did it")
    explain(
        "as the admin, set Avi to plan 'pro' / status 'active', then peek at "
        "the audit log",
        "every admin action must leave a fingerprint: WHO (the real admin "
        "Google id + email), WHAT (set_subscription), and on WHICH shop. "
        "Without that trail there's no accountability for a cross-wall action.")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    patch = await http.patch(
        f"/api/admin/businesses/{BIZ_A}/subscription",
        json={"plan_code": "pro", "status": "active"})
    await _logout(redis, http, sid)
    async with su.acquire() as conn:
        audit = await conn.fetchrow(
            "SELECT admin_user_id, admin_email, action, target_business_id, "
            "detail FROM admin_audit WHERE target_business_id=$1 "
            "ORDER BY created_at DESC LIMIT 1", BIZ_A)
    d = (audit["detail"] if isinstance(audit["detail"], dict)
         else json.loads(audit["detail"])) if audit else {}
    audit_ok = (
        patch.status_code == 200
        and patch.json() == {"business_id": BIZ_A, "plan_code": "pro",
                             "status": "active", "is_active": True}
        and audit is not None
        and audit["admin_user_id"] == admin_user
        and audit["admin_email"] == ADMIN_EMAIL
        and audit["action"] == "set_subscription"
        and str(audit["target_business_id"]) == BIZ_A
        and d == {"plan_code": "pro", "status": "active"}
    )
    result(audit_ok,
           "plan saved as pro/active; audit row stamped with the real admin "
           "id+email, action=set_subscription, correct target shop")

    # ── TEST 9 — bad inputs are refused (status / plan / business) ───
    banner("9", "Bad inputs are refused: junk status, junk plan, unknown shop")
    explain(
        "try status='frozen', plan='platinum-unicorn', and a made-up shop id",
        "the one WRITE path must be strict: an unknown status or plan is the "
        "caller's mistake (422), and an unknown business is a not-found (404). "
        "It must never silently accept a value outside the catalog.")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    bad_status = (await http.patch(
        f"/api/admin/businesses/{BIZ_A}/subscription",
        json={"plan_code": "pro", "status": "frozen"})).status_code
    bad_plan = (await http.patch(
        f"/api/admin/businesses/{BIZ_A}/subscription",
        json={"plan_code": "platinum-unicorn", "status": "active"})).status_code
    bad_biz = (await http.patch(
        "/api/admin/businesses/cccccccc-cccc-cccc-cccc-cccccccccccc/subscription",
        json={"plan_code": "pro", "status": "active"})).status_code
    await _logout(redis, http, sid)
    result(bad_status == 422 and bad_plan == 422 and bad_biz == 404,
           f"junk status→{bad_status}, junk plan→{bad_plan}, unknown shop→"
           f"{bad_biz} (422/422/404 — all refused)")

    # ── TEST 10 — THE BIG ONE: suspend really silences the bot ───────
    banner("10", "Suspending a shop really SILENCES its WhatsApp bot (not a label)")
    explain(
        "send Avi's bot a message (it answers), then SUSPEND Avi from the "
        "control room and send again, then RE-ACTIVATE and send once more",
        "this is the whole point of 'suspend': a locked shop's bot must stop "
        "talking to customers on the real WhatsApp line. A label that doesn't "
        "actually mute the bot would be worse than useless.")
    r1 = (await http.post("/webhook/whatsapp",
          json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
          headers=auth)).json()
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    await http.patch(f"/api/admin/businesses/{BIZ_A}/subscription",
                     json={"plan_code": "free", "status": "suspended"})
    await _logout(redis, http, sid)
    r2 = (await http.post("/webhook/whatsapp",
          json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
          headers=auth)).json()
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    await http.patch(f"/api/admin/businesses/{BIZ_A}/subscription",
                     json={"plan_code": "free", "status": "active"})
    await _logout(redis, http, sid)
    r3 = (await http.post("/webhook/whatsapp",
          json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
          headers=auth)).json()
    suspend_ok = (
        r1.get("status") == "ok" and len(r1.get("replies") or []) >= 1
        and r2.get("status") == "suspended" and r2.get("replies") == []
        and r3.get("status") == "ok" and len(r3.get("replies") or []) >= 1
    )
    result(suspend_ok,
           f"before: '{r1.get('status')}' "
           f"({len(r1.get('replies') or [])} replies) → suspended: "
           f"'{r2.get('status')}' ({len(r2.get('replies') or [])}) → "
           f"active again: '{r3.get('status')}' "
           f"({len(r3.get('replies') or [])}) — the lock truly mutes the bot")

    # ── TEST 11 — usage counters count, and the chart series comes back ─
    banner("11", "Usage counters tick up, and the chart data comes back")
    explain(
        "bump Avi's incoming-message counter by 2, then read the usage chart "
        "endpoint for Avi; also send a broken date",
        "the charts in the control room are only as honest as the counters. "
        "A bump must land on today's row for the right metric, and the chart "
        "endpoint must return that day. A broken date is a clean 422.")
    async with su.acquire() as conn:
        before = (await conn.fetchval(
            "SELECT count FROM usage_daily WHERE business_id=$1 AND "
            "day=current_date AND metric=$2", BIZ_A,
            usage_service.METRIC_MSG_IN)) or 0
    async with tenant_connection(pool, BIZ_A) as conn:
        await usage_service.bump(conn, BIZ_A, usage_service.METRIC_MSG_IN, 2)
    async with su.acquire() as conn:
        after_cnt = await conn.fetchval(
            "SELECT count FROM usage_daily WHERE business_id=$1 AND "
            "day=current_date AND metric=$2", BIZ_A,
            usage_service.METRIC_MSG_IN)
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    series = (await http.get(f"/api/admin/businesses/{BIZ_A}/usage")).json()
    bad_date = (await http.get(
        f"/api/admin/businesses/{BIZ_A}/usage?from=nope")).status_code
    await _logout(redis, http, sid)
    today = next((p for p in series["series"]
                  if p["day"] == date.today().isoformat()), None)
    usage_ok = (
        after_cnt == before + 2
        and usage_service.METRIC_MSG_IN in series["metrics_present"]
        and today is not None
        and today["metrics"].get(usage_service.METRIC_MSG_IN, 0) >= after_cnt
        and bad_date == 422
    )
    result(usage_ok,
           f"msg_in {before}→{after_cnt} (+2); chart has today's msg_in; "
           f"broken date → {bad_date} (422)")

    # ── TEST 12 — ISOLATION: the control-room tables are off-limits ──
    banner("12", "A normal shop CANNOT read the control-room tables or its neighbor")
    explain(
        "as the normal app role, try to read the subscriptions table and the "
        "audit table directly; then have shop A try to read shop B's counters",
        "crossing the wall must ONLY be possible through the narrow admin "
        "functions. The plans/audit tables give the app role ZERO direct "
        "access, and the usage table still obeys the tenant wall — A can "
        "never see B's numbers.")
    subs_denied = audit_denied = False
    try:
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.fetch("SELECT * FROM subscriptions")
    except asyncpg.InsufficientPrivilegeError:
        subs_denied = True
    try:
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.fetch("SELECT * FROM admin_audit")
    except asyncpg.InsufficientPrivilegeError:
        audit_denied = True
    # A asks for B's usage rows explicitly → the wall returns nothing.
    async with tenant_connection(pool, BIZ_A) as conn:
        b_rows = await conn.fetch(
            "SELECT * FROM usage_daily WHERE business_id=$1", BIZ_B)
    # the sanctioned doorway (the SD function) DOES work on a plain conn.
    async with pool.acquire() as conn:
        overview_row = await conn.fetchrow("SELECT * FROM admin_overview()")
    result(subs_denied and audit_denied and b_rows == []
           and overview_row is not None,
           f"direct subscriptions read denied={subs_denied}, audit denied="
           f"{audit_denied}, A sees {len(b_rows)} of B's rows; the admin "
           f"function still works (the only doorway)")

    # ── TEST 13 — NEGATIVE CONTROL: break the lock, watch it catch it ─
    banner("13", "NEGATIVE CONTROL: flip the lock by hand, watch the bot go quiet")
    explain(
        "set Avi's is_active=false DIRECTLY in the DB (not via the panel), "
        "message the bot, confirm silence — then restore it and confirm the "
        "bot talks again",
        "a good test must be able to FAIL. If flipping the lock did nothing, "
        "the bot would keep replying. We prove the suspend GATE in the bot "
        "pipeline is real, then put everything back.")
    async with su.acquire() as conn:
        await conn.execute(
            "UPDATE businesses SET is_active=false WHERE id=$1", BIZ_A)
    broke = (await http.post("/webhook/whatsapp",
             json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
             headers=auth)).json()
    caught = broke.get("status") == "suspended" and broke.get("replies") == []
    async with su.acquire() as conn:
        await conn.execute(
            "UPDATE businesses SET is_active=true WHERE id=$1", BIZ_A)
    fixed = (await http.post("/webhook/whatsapp",
             json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
             headers=auth)).json()
    restored = fixed.get("status") == "ok" and len(fixed.get("replies") or []) >= 1
    result(caught and restored,
           "lock on → bot silent (the gate caught it); lock off → bot answers "
           "again (restored)")



def tally() -> tuple[int, int]:
    """The (passed, total) counts after main() runs — read by the runner's scoreboard."""
    return _passed, _total
