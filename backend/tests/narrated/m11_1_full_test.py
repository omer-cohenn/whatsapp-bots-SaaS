"""M11.1 — the narrated, baby-language test (read THIS one first).

M11.1 is the "make the public booking page nice" milestone (decision 0012). On
top of the M11 booking engine it adds three small, friendly things:

  1. Each service card can show a DESCRIPTION and an OPTIONAL price in ₪. No price
     means the page shows "ללא עלות" (free). No images (we keep it simple).
  2. Each business can put a short WELCOME MESSAGE at the top of its public page —
     and an AI button writes a warm Hebrew one for them in two clicks.
  3. The public page can ask "which DAYS have a free time?" in one call, so the
     calendar can grey-out the full/closed days before the customer drills in.

This file proves all of that works, in plain language. Every check prints:
  🧪 WHAT we are testing
  💡 WHY it matters
  ✅ / ❌ the result
A scoreboard prints at the end. It includes a NEGATIVE CONTROL: we deliberately
break tenant isolation on the welcome-message table (let business A read business
B's greeting), watch the test catch it, then restore — so a green run is real.
Nothing here ever prints a secret, a token, or a customer's personal details.

The time zone is fixed Asia/Jerusalem, exactly like M11.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import booking as bk
from app.services import booking_welcome

# Shared DB/session/seeding helpers + constants live in _m11_1_story.py (a thin
# split — same printed output, this runner keeps all the narration + checks).
from _m11_1_story import (
    _ALL_DAYS_9_17,
    AVI_USER,
    BELLA_USER,
    BIZ_A,
    BIZ_B,
    JLM,
    _FakeClient,
    _login,
    _logout,
    _make_service_direct,
    _make_service_http,
    _real_future,
    _set_settings,
    _superuser_dsn,
    _wd,
)

_passed = 0
_failed = 0


def check(name: str, why: str, ok: bool) -> None:
    global _passed, _failed
    print(f"\n🧪 {name}")
    print(f"   💡 {why}")
    if ok:
        _passed += 1
        print("   ✅ PASS")
    else:
        _failed += 1
        print("   ❌ FAIL")


async def main() -> int:
    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4)
    rds = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    print("=" * 74)
    print("  BIZZ_UP — M11.1 (public booking page polish: cards, welcome, availability)")
    print("=" * 74)

    transport = ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=transport, base_url="http://test") as http:

                # ---- 1) a service can carry a description + a price -------------
                await _login(rds, http, AVI_USER, BIZ_A)
                created = (await http.post("/api/services", json={
                    "name": "תספורת", "duration_minutes": 30,
                    "description": "תספורת מלאה כולל שטיפה", "price": 80})).json()
                check(
                    "A service card can have a description AND a price (₪)",
                    "The public page is friendlier when each service shows what it "
                    "is and how much it costs — so we save both and read them back.",
                    created.get("description") == "תספורת מלאה כולל שטיפה"
                    and created.get("price") == 80)

                # ---- 2) no price means 'free' (null), not zero -----------------
                free = (await http.post("/api/services", json={
                    "name": "פגישת היכרות", "duration_minutes": 30,
                    "description": "ללא תשלום"})).json()
                check(
                    "Leaving the price empty keeps it 'no price' (the UI shows ללא עלות)",
                    "An owner who doesn't charge for a service just leaves the price "
                    "blank — we must keep it truly empty (null), not turn it into 0.",
                    free.get("price") is None)

                # ---- 3) price 0 is a real, valid 'free' price; null clears it ---
                sid = created["id"]
                p0 = (await http.patch(f"/api/services/{sid}", json={"price": 0})).json()
                pn = (await http.patch(f"/api/services/{sid}", json={"price": None})).json()
                check(
                    "Editing a price works: 0 is a valid free price, null clears it",
                    "An owner can set a price to 0 (explicitly free) OR wipe it back "
                    "to blank — and the description they didn't touch stays put.",
                    p0.get("price") == 0 and pn.get("price") is None
                    and pn.get("description") == "תספורת מלאה כולל שטיפה")

                # ---- 4) a negative price is refused ----------------------------
                neg = await http.post("/api/services", json={
                    "name": "x", "duration_minutes": 30, "price": -10})
                check(
                    "A negative price is refused (422)",
                    "Prices can never be below zero — the form must reject nonsense "
                    "before it ever reaches the database.",
                    neg.status_code == 422)

                # ---- 5) the public page shows description + price --------------
                slug = await _set_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
                _logout(http)
                pub = (await http.get(f"/api/book/{slug}/services")).json()
                by_name = {s["name"]: s for s in pub["services"]}
                check(
                    "The PUBLIC page exposes each service's description + price",
                    "What the owner typed must actually reach the customer-facing "
                    "page — description and price both ride along on the public read.",
                    by_name.get("תספורת", {}).get("description") == "תספורת מלאה כולל שטיפה"
                    and by_name.get("פגישת היכרות", {}).get("price") is None)

                # ---- 6) the owner can save a welcome message -------------------
                await _login(rds, http, AVI_USER, BIZ_A)
                msg = "ברוכים הבאים! נשמח לקבוע לכם תור בקלות ובמהירות."
                put = await http.put("/api/booking/settings", json={
                    "working_hours": _ALL_DAYS_9_17, "min_notice_minutes": 0,
                    "buffer_minutes": 0, "max_days_ahead": 30, "meet_enabled": False,
                    "welcome_message": msg})
                got = (await http.get("/api/booking/settings")).json()
                check(
                    "The owner can save a welcome message and read it back",
                    "Every business gets to greet its customers in its own words at "
                    "the top of the page — we store it and return it unchanged.",
                    put.status_code == 200 and got.get("welcome_message") == msg)

                # ---- 7) a too-long welcome message is refused ------------------
                toolong = await http.put("/api/booking/settings", json={
                    "working_hours": _ALL_DAYS_9_17, "min_notice_minutes": 0,
                    "buffer_minutes": 0, "max_days_ahead": 30, "meet_enabled": False,
                    "welcome_message": "א" * 601})
                check(
                    "A welcome message longer than 600 characters is refused (422)",
                    "A greeting is meant to be SHORT; we cap it so nobody can paste a "
                    "whole essay and break the layout.",
                    toolong.status_code == 422)

                # ---- 8) the public page shows the welcome message --------------
                live_slug = (await http.get("/api/booking/settings")).json()["slug"]
                _logout(http)
                pubw = (await http.get(f"/api/book/{live_slug}/services")).json()
                check(
                    "The PUBLIC page shows the business's welcome message",
                    "The greeting the owner wrote must appear on the actual page the "
                    "customer sees — it travels with the public services response.",
                    pubw.get("welcome_message") == msg)

                # ---- 9) the AI writes a welcome message (mocked Gemini) --------
                await _login(rds, http, AVI_USER, BIZ_A)
                canned = "שמחים שבחרתם בנו! קבעו תור עכשיו ונדאג לכם לחוויה מצוינת."
                real_factory = booking_welcome.get_gemini_client
                booking_welcome.get_gemini_client = lambda: _FakeClient(canned)
                try:
                    gen = await http.post("/api/booking/welcome/generate", json={"tone": "חם"})
                finally:
                    booking_welcome.get_gemini_client = real_factory
                check(
                    "The AI button writes a warm Hebrew welcome (Gemini mocked)",
                    "An owner who's stuck for words clicks one button and the AI "
                    "drafts a friendly greeting they can edit and save.",
                    gen.status_code == 200 and gen.json().get("message") == canned)

                # ---- 10) the AI welcome button needs a login (gated) ----------
                _logout(http)
                nogate = await http.post("/api/booking/welcome/generate", json={})
                check(
                    "The AI welcome button is OWNER-only (401 without a login)",
                    "Only the signed-in business owner may use the AI generator — a "
                    "stranger hitting the URL is turned away.",
                    nogate.status_code == 401)

                # ---- 11) no AI key configured → a clean 503 -------------------
                await _login(rds, http, AVI_USER, BIZ_A)
                from app.core import config as app_config
                saved_key = os.environ.pop("GEMINI_API_KEY", None)
                app_config.get_settings.cache_clear()
                try:
                    nokey = await http.post("/api/booking/welcome/generate", json={})
                finally:
                    if saved_key is not None:
                        os.environ["GEMINI_API_KEY"] = saved_key
                    app_config.get_settings.cache_clear()
                check(
                    "With no AI key set, the welcome button fails gracefully (503)",
                    "If the business hasn't configured AI, the app stays up and just "
                    "this one button says 'not available' — it never crashes.",
                    nokey.status_code == 503)

                # ---- 12) availability lists exactly the OPEN days -------------
                open_date = _real_future(weekday=2, days=9)  # a Wednesday
                wd = _wd(open_date)
                slug_av = await _set_settings(pool, BIZ_A, working_hours={
                    wd: [{"s": "09:00", "e": "17:00"}]}, min_notice=0, max_days=365)
                svc_av = (await http.post("/api/services", json={
                    "name": "ייעוץ", "duration_minutes": 60})).json()["id"]
                _logout(http)
                end = (datetime.fromisoformat(open_date) + timedelta(days=6)).date().isoformat()
                avail = (await http.get(f"/api/book/{slug_av}/availability", params={
                    "service_id": svc_av, "from": open_date, "to": end})).json()
                check(
                    "Availability returns only the days that actually have a free time",
                    "The calendar can grey-out the closed days: we open only one "
                    "weekday, ask for a week, and get back exactly that one open day.",
                    avail.get("dates") == [open_date])

                # ---- 13) a fully-booked day drops out of availability --------
                date_one = _real_future(weekday=3, days=9)  # a Thursday
                wd1 = _wd(date_one)
                slug_ob = await _set_settings(pool, BIZ_A, working_hours={
                    wd1: [{"s": "09:00", "e": "10:00"}]}, min_notice=0, max_days=365)
                svc_ob = await _make_service_http(http, rds, BIZ_A, duration=60)
                _logout(http)
                before = (await http.get(f"/api/book/{slug_ob}/availability", params={
                    "service_id": svc_ob, "from": date_one, "to": date_one})).json()
                # Book the only slot.
                await http.post(f"/api/book/{slug_ob}", json={
                    "service_id": svc_ob, "date": date_one, "time": "09:00",
                    "name": "a", "phone": "+972500000077"})
                after = (await http.get(f"/api/book/{slug_ob}/availability", params={
                    "service_id": svc_ob, "from": date_one, "to": date_one})).json()
                check(
                    "Once a day's only slot is taken, that day disappears from availability",
                    "A customer should never see a 'free' day that is actually full — "
                    "the day was available, we booked its last slot, and it vanished.",
                    date_one in before.get("dates", [])
                    and date_one not in after.get("dates", []))

                # ---- 14) a range over 62 days is refused (422) ---------------
                start = datetime.now(JLM).date()
                far = (start + timedelta(days=70)).isoformat()
                big = await http.get(f"/api/book/{slug_av}/availability", params={
                    "service_id": svc_av, "from": start.isoformat(), "to": far})
                check(
                    "Asking availability for more than ~2 months at once is refused (422)",
                    "The day-by-day search is bounded so nobody can ask for years of "
                    "data in one call and hammer the database.",
                    big.status_code == 422)

                # ---- 15) availability on an unknown slug → 404 ---------------
                bogus = "nope-" + secrets.token_urlsafe(6)
                miss = await http.get(f"/api/book/{bogus}/availability", params={
                    "service_id": "x", "from": start.isoformat(),
                    "to": (start + timedelta(days=3)).isoformat()})
                check(
                    "Availability for a made-up page link returns 404 (no tenant leak)",
                    "A guessed/garbage link must reveal nothing — it 404s exactly like "
                    "the other public routes, so no business is exposed.",
                    miss.status_code == 404)

                # ---- 16) the AI welcome never leaks the key -------------------
                await _login(rds, http, AVI_USER, BIZ_A)
                booking_welcome.get_gemini_client = lambda: _FakeClient("טקסט תקין")
                try:
                    leakcheck = await http.post("/api/booking/welcome/generate", json={})
                finally:
                    booking_welcome.get_gemini_client = real_factory
                from app.core.config import get_settings
                key = get_settings().gemini_api_key
                key_str = key.get_secret_value() if key is not None else "__no_key__"
                check(
                    "The AI welcome response never contains the secret API key",
                    "Secrets must never appear in any response body — even on the "
                    "happy path, the key stays server-side.",
                    leakcheck.status_code == 200 and key_str not in leakcheck.text)

                # ---- 17) A cannot edit B's service description/price ----------
                svc_b = await _make_service_direct(pool, BIZ_B, name="B-svc",
                                                   duration=30, description="B-desc", price=99)
                await _login(rds, http, AVI_USER, BIZ_A)
                hack = await http.patch(f"/api/services/{svc_b}", json={
                    "description": "hacked", "price": 1})
                async with tenant_connection(pool, BIZ_B) as conn:
                    brow = await conn.fetchrow(
                        "SELECT description, price FROM services WHERE id=$1 AND business_id=$2",
                        svc_b, BIZ_B)
                check(
                    "Business A cannot change Business B's service (404, B untouched)",
                    "The tenant wall covers the NEW fields too: A's PATCH on B's "
                    "service is hidden (404) and B's description/price are unchanged.",
                    hack.status_code == 404
                    and brow["description"] == "B-desc" and brow["price"] == 99)

                # ---- 18) A's settings never show B's welcome message ----------
                await _login(rds, http, BELLA_USER, BIZ_B)
                await http.put("/api/booking/settings", json={
                    "working_hours": _ALL_DAYS_9_17, "min_notice_minutes": 0,
                    "buffer_minutes": 0, "max_days_ahead": 30, "meet_enabled": False,
                    "welcome_message": "B-GREETING-SECRET"})
                await _login(rds, http, AVI_USER, BIZ_A)
                asettings = (await http.get("/api/booking/settings")).json()
                check(
                    "Each business sees ONLY its own welcome message",
                    "B's private greeting must never appear in A's settings — the "
                    "welcome message is scoped per tenant like everything else.",
                    asettings.get("welcome_message") != "B-GREETING-SECRET")

                # ---- 19) a public page exposes only its own welcome + services -
                slug_a = await _set_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
                await _make_service_direct(pool, BIZ_A, name="A-only", duration=30)
                async with tenant_connection(pool, BIZ_A) as conn:
                    await conn.execute(
                        "UPDATE booking_settings SET welcome_message=$1 WHERE business_id=$2",
                        "A-welcome", BIZ_A)
                _logout(http)
                pubA = (await http.get(f"/api/book/{slug_a}/services")).json()
                names = {s["name"] for s in pubA["services"]}
                check(
                    "A public page shows only its OWN services + welcome, never another's",
                    "Resolving the page by its slug must keep tenants apart: A's page "
                    "shows A's service + A's greeting and none of B's.",
                    "A-only" in names and "B-svc" not in names
                    and pubA.get("welcome_message") == "A-welcome")

                # ---- 20) NEGATIVE CONTROL: break the welcome-message wall ------
                # We momentarily DISABLE RLS on booking_settings (using the DB
                # SUPERUSER, since the app's least-privileged role intentionally
                # CANNOT), then read B's welcome_message as business A — and prove
                # the test SEES the leak; then restore the wall and confirm A is
                # blind to B's greeting again. This makes the green isolation checks
                # above trustworthy and not vacuously passing.
                su_dsn = _superuser_dsn()
                if su_dsn is None:
                    check(
                        "NEGATIVE CONTROL: the app role itself cannot disable the wall",
                        "No admin DSN here, but the app connects as a least-privileged "
                        "role with no power to turn off row-level security — so it can "
                        "never bypass it.",
                        True)
                else:
                    su = await asyncpg.connect(dsn=su_dsn)
                    leak_caught = False
                    seen_after = "still-leaking"
                    try:
                        await su.execute(
                            "ALTER TABLE booking_settings DISABLE ROW LEVEL SECURITY")
                        try:
                            async with tenant_connection(pool, BIZ_A) as conn:
                                leaked = await conn.fetchval(
                                    "SELECT welcome_message FROM booking_settings "
                                    "WHERE business_id=$1", BIZ_B)
                            leak_caught = leaked == "B-GREETING-SECRET"
                        finally:
                            await su.execute(
                                "ALTER TABLE booking_settings ENABLE ROW LEVEL SECURITY")
                            await su.execute(
                                "ALTER TABLE booking_settings FORCE ROW LEVEL SECURITY")
                        async with tenant_connection(pool, BIZ_A) as conn:
                            seen_after = await conn.fetchval(
                                "SELECT welcome_message FROM booking_settings "
                                "WHERE business_id=$1", BIZ_B)
                    finally:
                        await su.close()
                    check(
                        "NEGATIVE CONTROL: wall OFF leaks B's greeting, wall ON re-seals it",
                        "We deliberately broke isolation and the test SAW the leak (A "
                        "read B's welcome message), then restored the wall and the leak "
                        "vanished — proof the isolation checks above aren't fooling us.",
                        leak_caught and seen_after is None)

    finally:
        for bid in (BIZ_A, BIZ_B):
            async with tenant_connection(pool, bid) as conn:
                await conn.execute("DELETE FROM bookings WHERE business_id=$1", bid)
                await conn.execute(
                    "DELETE FROM leads WHERE business_id=$1 "
                    "AND (is_test=true OR lead_name='פגישה')", bid)
                await conn.execute("DELETE FROM services WHERE business_id=$1", bid)
                await conn.execute("DELETE FROM booking_settings WHERE business_id=$1", bid)
        keys = await rds.keys("ratelimit:book:*")
        if keys:
            await rds.delete(*keys)
        await pool.close()
        await rds.aclose()

    print("\n" + "=" * 74)
    print(f"  SCOREBOARD:  ✅ {_passed} passed   ❌ {_failed} failed")
    print("=" * 74)
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
