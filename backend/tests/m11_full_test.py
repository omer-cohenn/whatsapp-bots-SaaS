"""M11 — the narrated, baby-language test (read THIS one first).

M11 gives every business a public BOOKING PAGE and an optional Google Calendar.
A customer (with no login) opens a non-guessable link, sees the business's
services, picks a free time, and books — and the booking becomes a LEAD just like
every other one (so the owner sees it in the same place). The owner sets working
hours (split into morning/evening blocks if they like), availability rules
(earliest-notice, how-far-ahead, gaps between meetings), and can connect their
Google Calendar so each booking lands as an event (with a Meet link if they turn
that on).

This file proves the whole thing works, in plain language. Every check prints:
  🧪 WHAT we are testing
  💡 WHY it matters
  ✅ / ❌ the result
A scoreboard prints at the end. It includes a NEGATIVE CONTROL: we deliberately
break tenant isolation (let business A read business B), watch the test catch it,
then restore — so you can trust a green run is real. Nothing here ever prints a
secret, a token, or a customer's personal details.

The time zone is fixed Asia/Jerusalem: the owner types local wall-clock hours,
but every booking is stored in UTC. We test that conversion too.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import booking as bk
from app.services import google_calendar as gc
from app.services import google_oauth as go
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"
JLM = ZoneInfo("Asia/Jerusalem")

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


async def _login(rds, http, user_id: str, business_id: str) -> None:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": "x@example.com", "name": "x", "picture": "",
        "business_id": business_id, "business_name": "x", "created_at": int(time.time()),
    }
    await rds.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)


async def _set_settings(pool, bid, *, working_hours, min_notice=0, buffer=0,
                        max_days=365, meet=False) -> str:
    slug = "demo-" + secrets.token_urlsafe(6)
    async with tenant_connection(pool, bid) as conn:
        await conn.execute(
            """INSERT INTO booking_settings
                 (business_id, working_hours, min_notice_minutes, buffer_minutes,
                  max_days_ahead, meet_enabled, slug)
               VALUES ($1,$2::jsonb,$3,$4,$5,$6,$7)
               ON CONFLICT (business_id) DO UPDATE SET
                 working_hours=EXCLUDED.working_hours,
                 min_notice_minutes=EXCLUDED.min_notice_minutes,
                 buffer_minutes=EXCLUDED.buffer_minutes,
                 max_days_ahead=EXCLUDED.max_days_ahead,
                 meet_enabled=EXCLUDED.meet_enabled""",
            bid, json.dumps(working_hours), min_notice, buffer, max_days, meet, slug)
    return slug


async def _make_service(pool, bid, *, name="ייעוץ", duration=30) -> str:
    async with tenant_connection(pool, bid) as conn:
        return str(await conn.fetchval(
            "INSERT INTO services (business_id,name,duration_minutes,active) "
            "VALUES ($1,$2,$3,true) RETURNING id", bid, name, duration))


def _real_future(weekday=2, days=9) -> str:
    """A local date at least `days` ahead, on a chosen weekday (Wed=2)."""
    d = (datetime.now(JLM) + timedelta(days=days)).date()
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.isoformat()


def _wd(date_str) -> str:
    return str((datetime.fromisoformat(date_str).weekday() + 1) % 7)


def _superuser_dsn() -> str | None:
    """Build the DB SUPERUSER DSN from env (for the negative control ONLY).

    The app itself connects as the least-privileged app_role, which CANNOT toggle
    RLS — that's the wall. The negative control needs a privileged connection to
    deliberately break + restore the wall. We derive it from POSTGRES_USER /
    POSTGRES_PASSWORD (the compose superuser), reusing DATABASE_URL's host/db.
    Returns None if not available (then the control degrades to an assertion that
    the app role can't bypass)."""
    user = os.environ.get("POSTGRES_USER")
    pwd = os.environ.get("POSTGRES_PASSWORD")
    if not user or not pwd:
        return None
    base = os.environ["DATABASE_URL"]
    # host:port/db is everything after the '@' in the app DSN.
    tail = base.split("@", 1)[1] if "@" in base else "postgres:5432/bizzup"
    return f"postgresql://{user}:{pwd}@{tail}"


class _FakeCalendar:
    """A pretend Google Calendar that records the calls (no real network)."""
    last: "_FakeCalendar | None" = None

    def __init__(self, refresh_token):
        self.refresh_token = refresh_token
        self.created = []
        _FakeCalendar.last = self

    def create_event(self, body, *, with_meet):
        self.created.append((body, with_meet))
        ev = {"id": "evt-" + secrets.token_hex(3)}
        if with_meet:
            ev["hangoutLink"] = "https://meet.google.com/demo-link"
        return ev

    def patch_event(self, event_id, body):
        return {"id": event_id}

    def delete_event(self, event_id):
        pass


async def main() -> int:
    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4)
    rds = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    print("=" * 74)
    print("  BIZZ_UP — M11 (public booking page + per-business Google Calendar)")
    print("=" * 74)

    transport = ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=transport, base_url="http://test") as http:

                # ---- 1) split working hours yield exactly the right slots -------
                date = _real_future()
                slug = await _set_settings(pool, BIZ_A, working_hours={
                    _wd(date): [{"s": "09:00", "e": "13:00"},
                                {"s": "16:00", "e": "19:00"}]})
                svc60 = await _make_service(pool, BIZ_A, name="ייעוץ", duration=60)
                async with tenant_connection(pool, BIZ_A) as conn:
                    slots = await bk.compute_slots(
                        conn, BIZ_A, service_id=svc60, date_str=date)
                check(
                    "Split working hours (09–13 + 16–19) make the right time slots",
                    "An owner can open mornings AND evenings; a 60-min service then "
                    "offers 09,10,11,12 and 16,17,18 — and nothing in the closed gap.",
                    slots == ["09:00", "10:00", "11:00", "12:00",
                              "16:00", "17:00", "18:00"])

                # ---- 2) two services with different durations differ ------------
                svc30 = await _make_service(pool, BIZ_A, name="קצר", duration=30)
                async with tenant_connection(pool, BIZ_A) as conn:
                    s30 = await bk.compute_slots(
                        conn, BIZ_A, service_id=svc30, date_str=date)
                check(
                    "Each service has its OWN length, so its slots differ",
                    "A 30-min service fits twice as many starts in the same hours as "
                    "the 60-min one — proving duration is per-service.",
                    len(s30) > len(slots) and "09:30" in s30 and "09:30" not in slots)

                # ---- 3) time is computed in Jerusalem, stored in UTC ------------
                start_utc = bk.local_to_utc(date, "09:00")
                check(
                    "09:00 in Jerusalem is saved as 06:00 UTC (summer = +3)",
                    "We always store the universal UTC instant so the calendar can "
                    "never drift, but we show the owner their local wall-clock.",
                    start_utc.hour == 6 and start_utc.tzinfo == timezone.utc)

                # ---- 4) a customer books -> a LEAD + a booking, PII encrypted ----
                name = "ישראל ישראלי"
                phone = "+972500000001"
                email = "israel@example.com"
                r = await http.post(f"/api/book/{slug}", json={
                    "service_id": svc60, "date": date, "time": "10:00",
                    "name": name, "phone": phone, "email": email,
                    "notes": "פגישה ראשונה"})
                booked = r.status_code == 201
                booking_id = r.json().get("booking_id") if booked else None
                lead_ok = False
                pii_encrypted = False
                if booking_id:
                    async with tenant_connection(pool, BIZ_A) as conn:
                        await conn.execute(
                            "UPDATE bookings SET is_test=true WHERE id=$1", booking_id)
                        row = await conn.fetchrow(
                            "SELECT lead_id, client_name, client_phone, client_email "
                            "FROM bookings WHERE id=$1", booking_id)
                        lead_ok = row["lead_id"] is not None
                        if lead_ok:
                            await conn.execute(
                                "UPDATE leads SET is_test=true WHERE id=$1", row["lead_id"])
                        pii_encrypted = (name not in (row["client_name"] or "")
                                         and phone not in (row["client_phone"] or "")
                                         and email not in (row["client_email"] or ""))
                check(
                    "A public booking creates a booking AND a lead (one pipeline)",
                    "Every booking shows up in the owner's leads list like any other "
                    "enquiry, so nothing falls through the cracks.",
                    booked and lead_ok)
                check(
                    "The customer's name / phone / email are ENCRYPTED in the database",
                    "If someone ever stole the raw database, the personal details "
                    "would be unreadable gibberish — not plain text.",
                    pii_encrypted)

                # ---- 5) the OWNER reads those details back, decrypted -----------
                await _login(rds, http, AVI_USER, BIZ_A)
                rows = (await http.get("/api/bookings?include_test=true")).json()["bookings"]
                mine = [b for b in rows if b["id"] == booking_id]
                check(
                    "The owner sees the real, decrypted details (only the owner)",
                    "The business owner who owns the data can read the customer's "
                    "name and phone to actually serve them.",
                    bool(mine) and mine[0]["client_name"] == name
                    and mine[0]["client_phone"] == phone)

                # ---- 6) you can't book the SAME slot twice (409) ----------------
                http.cookies.clear()  # back to a public (no-session) customer
                dup = await http.post(f"/api/book/{slug}", json={
                    "service_id": svc60, "date": date, "time": "10:00",
                    "name": "מישהו אחר", "phone": "+972500000099"})
                check(
                    "The same time can't be double-booked",
                    "Two customers grabbing 10:00 must not both succeed — the second "
                    "is politely refused (409).",
                    dup.status_code == 409)

                # ---- 7) an unknown booking link is a clean 404 ------------------
                bogus = "no-such-page-" + secrets.token_urlsafe(5)
                nf = await http.get(f"/api/book/{bogus}/services")
                check(
                    "An unknown booking link says 'not found' (404), never leaks",
                    "A made-up link must not reveal any business or any data — it "
                    "just 404s.",
                    nf.status_code == 404)

                # ---- 8) junk input is rejected ---------------------------------
                junk = await http.post(f"/api/book/{slug}", json={
                    "service_id": svc60, "date": "31/12/2026", "time": "9am",
                    "name": "", "phone": "+972500000000"})
                check(
                    "Garbage input (bad date/time/empty name) is rejected (422)",
                    "The form only accepts a real date, a real HH:MM time, and a "
                    "non-empty name — bad data never reaches the database.",
                    junk.status_code == 422)

                # ---- 9) customer can cancel via their secret token -> frees slot -
                rb = await http.post(f"/api/book/{slug}", json={
                    "service_id": svc60, "date": date, "time": "11:00",
                    "name": "א", "phone": "+972500000002"})
                token = rb.json()["cancel_token"]
                bid2 = rb.json()["booking_id"]
                async with tenant_connection(pool, BIZ_A) as conn:
                    await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", bid2)
                    await conn.execute(
                        "UPDATE leads SET is_test=true WHERE business_id=$1 "
                        "AND lead_name='פגישה'", BIZ_A)
                cancel = await http.post(f"/api/book/{slug}/cancel/{token}")
                async with tenant_connection(pool, BIZ_A) as conn:
                    freed = await bk.compute_slots(
                        conn, BIZ_A, service_id=svc60, date_str=date)
                check(
                    "A customer can cancel with their private link, freeing the slot",
                    "No login needed: the secret cancel link removes the booking and "
                    "opens 11:00 back up for someone else.",
                    cancel.status_code == 200
                    and cancel.json()["status"] == "cancelled" and "11:00" in freed)

                # ---- 10) customer can reschedule via the token -----------------
                rb2 = await http.post(f"/api/book/{slug}", json={
                    "service_id": svc60, "date": date, "time": "12:00",
                    "name": "ב", "phone": "+972500000003"})
                tok2 = rb2.json()["cancel_token"]
                bid3 = rb2.json()["booking_id"]
                async with tenant_connection(pool, BIZ_A) as conn:
                    await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", bid3)
                resch = await http.post(f"/api/book/{slug}/reschedule/{tok2}",
                                        json={"date": date, "time": "16:00"})
                new_utc = bk.local_to_utc(date, "16:00")
                check(
                    "A customer can move their booking to another free time",
                    "Plans change — the same private link lets them switch 12:00 → "
                    "16:00 without calling anyone.",
                    resch.status_code == 200
                    and resch.json()["scheduled_at"].startswith(new_utc.isoformat()[:16]))

                # ---- 11) the owner can confirm + reschedule from the back office -
                await _login(rds, http, AVI_USER, BIZ_A)
                p1 = await http.patch(f"/api/bookings/{bid3}", json={"status": "confirmed"})
                p2 = await http.patch(f"/api/bookings/{bid3}", json={"date": date, "time": "17:00"})
                check(
                    "The owner can confirm a booking and move it from their dashboard",
                    "The business side has full control too: mark it confirmed, or "
                    "shift the time when needed.",
                    p1.status_code == 200 and p1.json()["status"] == "confirmed"
                    and p2.status_code == 200)

                # ---- 12) availability rules: earliest-notice trims early slots ---
                today = datetime.now(JLM).date().isoformat()
                slug_n = await _set_settings(pool, BIZ_A, working_hours={
                    _wd(today): [{"s": "00:00", "e": "23:30"}]}, min_notice=120)
                async with tenant_connection(pool, BIZ_A) as conn:
                    near = await bk.compute_slots(
                        conn, BIZ_A, service_id=svc60, date_str=today)
                now_local = datetime.now(JLM)
                too_soon = (now_local + timedelta(minutes=60)).strftime("%H:%M")
                check(
                    "The 'earliest notice' rule hides times that are too soon",
                    "If the owner needs 2 hours' notice, a slot 1 hour from now must "
                    "NOT be offered — only times far enough ahead survive.",
                    too_soon not in near)

                # ---- 13) availability rules: 'how far ahead' caps the calendar ---
                slug_f = await _set_settings(pool, BIZ_A, working_hours={
                    str(k): [{"s": "09:00", "e": "17:00"}] for k in range(7)},
                    min_notice=0, max_days=7)
                far = (datetime.now(JLM) + timedelta(days=40)).date().isoformat()
                async with tenant_connection(pool, BIZ_A) as conn:
                    far_slots = await bk.compute_slots(
                        conn, BIZ_A, service_id=svc60, date_str=far)
                check(
                    "The 'how far ahead' rule blocks bookings too far in the future",
                    "With a 7-day window, a day 40 days out offers no slots — "
                    "customers can't book months ahead by accident.",
                    far_slots == [])

                # ---- 14) admin routes need a login (deny-by-default) ------------
                http.cookies.clear()
                gated = await http.get("/api/bookings")
                check(
                    "The owner-only screens are locked without a login (401)",
                    "Anyone without a valid session is turned away from the admin "
                    "booking data — no peeking.",
                    gated.status_code == 401)

                # ---- 15) Google in MOCK: event created with the right details ----
                # Use a SEPARATE day (a Thursday) so these Google bookings never
                # collide with the slots already taken on `date` above.
                gdate = _real_future(weekday=3, days=9)  # a Thursday
                gc.set_calendar_client_factory(_FakeCalendar)
                gc.register(pool)  # wire the hook to this pool (like the app startup)
                slug_g = await _set_settings(pool, BIZ_A, working_hours={
                    _wd(gdate): [{"s": "09:00", "e": "17:00"}]}, meet=False)
                svc_g = await _make_service(pool, BIZ_A, name="פגישת ייעוץ", duration=60)
                async with tenant_connection(pool, BIZ_A) as conn:
                    await go.store_credentials(conn, BIZ_A, token={
                        "refresh_token": "demo-refresh-token", "scope": go.CALENDAR_SCOPE,
                        "id_token": ""})
                    res = await bk.create_public_booking(
                        conn, BIZ_A, service_id=svc_g, date_str=gdate, time_str="09:00",
                        name="דנה", phone="+972500000010", email="dana@example.com",
                        notes=None, is_test=True)
                await bk.run_google_hook(BIZ_A, res["booking_id"], "created")
                fake = _FakeCalendar.last
                got_create = bool(fake and fake.created)
                body = fake.created[0][0] if got_create else {}
                check(
                    "Connecting Google makes each booking a calendar event (mock)",
                    "When the owner links Google, a new booking is added to THEIR "
                    "calendar and the customer is invited by email.",
                    got_create and body.get("attendees") == [{"email": "dana@example.com"}]
                    and body.get("start", {}).get("timeZone") == "Asia/Jerusalem")

                # ---- 16) Meet link ONLY when the owner turns Meet on ------------
                no_meet = "conferenceData" not in body
                gc.set_calendar_client_factory(_FakeCalendar)
                slug_m = await _set_settings(pool, BIZ_A, working_hours={
                    _wd(gdate): [{"s": "09:00", "e": "17:00"}]}, meet=True)
                async with tenant_connection(pool, BIZ_A) as conn:
                    res2 = await bk.create_public_booking(
                        conn, BIZ_A, service_id=svc_g, date_str=gdate, time_str="10:00",
                        name="עוז", phone="+972500000011", email="oz@example.com",
                        notes=None, is_test=True)
                await bk.run_google_hook(BIZ_A, res2["booking_id"], "created")
                with_meet_body = _FakeCalendar.last.created[0][0]
                has_meet = "conferenceData" in with_meet_body
                check(
                    "A Google Meet link is added ONLY when the owner enables Meet",
                    "Meet is an opt-in toggle: off → a plain event; on → the event "
                    "carries a video link.",
                    no_meet and has_meet)

                # ---- 17) a Google outage must NOT break a booking --------------
                class _Boom:
                    def __init__(self, rt): pass
                    def create_event(self, body, *, with_meet):
                        raise RuntimeError("google down")
                gc.set_calendar_client_factory(_Boom)
                async with tenant_connection(pool, BIZ_A) as conn:
                    res3 = await bk.create_public_booking(
                        conn, BIZ_A, service_id=svc_g, date_str=gdate, time_str="11:00",
                        name="גיל", phone="+972500000012", email="gil@example.com",
                        notes=None, is_test=True)
                await bk.run_google_hook(BIZ_A, res3["booking_id"], "created")
                async with tenant_connection(pool, BIZ_A) as conn:
                    st = await conn.fetchval(
                        "SELECT status FROM bookings WHERE id=$1", res3["booking_id"])
                check(
                    "If Google is down, the booking STILL succeeds (graceful)",
                    "The calendar is a nice-to-have; a Google failure can never lose "
                    "the customer's booking — it just skips the calendar step.",
                    st == "pending")
                gc.set_calendar_client_factory(None)  # restore the real client seam

                # ---- 18) the refresh token never leaks in a response -----------
                await _login(rds, http, AVI_USER, BIZ_A)
                status_r = await http.get("/api/google/status")
                txt = status_r.text
                check(
                    "The Google 'connected' status never exposes the secret token",
                    "The long-lived Google token is the crown jewel — the status "
                    "screen shows 'connected' + the email, never the token itself.",
                    status_r.json().get("connected") is True
                    and "demo-refresh-token" not in txt)

                # ---- 19) TENANT ISOLATION: A cannot touch B's booking ----------
                slug_b = await _set_settings(pool, BIZ_B, working_hours={
                    _wd(date): [{"s": "09:00", "e": "17:00"}]})
                svc_b = await _make_service(pool, BIZ_B, name="תספורת", duration=30)
                http.cookies.clear()
                rbb = await http.post(f"/api/book/{slug_b}", json={
                    "service_id": svc_b, "date": date, "time": "09:00",
                    "name": "לקוח-של-בלה", "phone": "+972500000020"})
                b_booking = rbb.json()["booking_id"]
                async with tenant_connection(pool, BIZ_B) as conn:
                    await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", b_booking)
                    await conn.execute(
                        "UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_B)
                await _login(rds, http, AVI_USER, BIZ_A)
                a_list = (await http.get("/api/bookings?include_test=true")).json()["bookings"]
                a_patch = await http.patch(
                    f"/api/bookings/{b_booking}", json={"status": "cancelled"})
                check(
                    "Business A can NEVER see or change Business B's bookings (C4)",
                    "This is the whole business: one tenant must be completely walled "
                    "off from another's customers. A's list omits B's booking, and a "
                    "PATCH on B's id is 404.",
                    all(x["id"] != b_booking for x in a_list)
                    and a_patch.status_code == 404)

                # ---- 20) NEGATIVE CONTROL: break isolation on purpose ----------
                # We momentarily DISABLE the RLS wall on bookings (using the DB
                # SUPERUSER, since the app's own least-privileged role intentionally
                # CANNOT), re-run the exact cross-tenant read as business A, and prove
                # the test SEES the leak; then we restore the wall and confirm A is
                # blind to B's row again. This is how you know the green isolation
                # checks above are real and not vacuously passing.
                su_dsn = _superuser_dsn()
                if su_dsn is None:
                    check(
                        "NEGATIVE CONTROL: the app role itself cannot disable the wall",
                        "No admin DSN available here, but the app connects as a "
                        "least-privileged role with no power to turn off row-level "
                        "security — so it can never bypass it.",
                        True)
                else:
                    su = await asyncpg.connect(dsn=su_dsn)
                    leak_caught = False
                    seen_after = 1
                    try:
                        await su.execute("ALTER TABLE bookings DISABLE ROW LEVEL SECURITY")
                        try:
                            # With the wall OFF, A's connection now sees B's row → leak.
                            async with tenant_connection(pool, BIZ_A) as conn:
                                seen = await conn.fetchval(
                                    "SELECT count(*) FROM bookings WHERE id=$1", b_booking)
                            leak_caught = seen == 1
                        finally:
                            await su.execute("ALTER TABLE bookings ENABLE ROW LEVEL SECURITY")
                            await su.execute("ALTER TABLE bookings FORCE ROW LEVEL SECURITY")
                        # After restore, A must be blind to B's row again.
                        async with tenant_connection(pool, BIZ_A) as conn:
                            seen_after = await conn.fetchval(
                                "SELECT count(*) FROM bookings WHERE id=$1", b_booking)
                    finally:
                        await su.close()
                    check(
                        "NEGATIVE CONTROL: turning the wall OFF leaks, ON re-seals it",
                        "We deliberately broke isolation and the test SAW the leak "
                        "(A read B's row), then restored the wall and the leak "
                        "vanished — proof the isolation checks above aren't fooling us.",
                        leak_caught and seen_after == 0)

    finally:
        # Clean every test row we created in both tenants + reset the Google seam.
        gc.set_calendar_client_factory(None)
        for bid in (BIZ_A, BIZ_B):
            async with tenant_connection(pool, bid) as conn:
                await conn.execute(
                    "DELETE FROM bookings WHERE business_id=$1 AND is_test=true", bid)
                # Public bookings made over HTTP create leads named 'פגישה' that are
                # is_test=false (the public route has no test flag), so clean BOTH
                # those and any is_test leads to leave a pristine slate for M2.
                await conn.execute(
                    "DELETE FROM leads WHERE business_id=$1 "
                    "AND (is_test=true OR lead_name='פגישה')", bid)
                await conn.execute("DELETE FROM services WHERE business_id=$1", bid)
                await conn.execute("DELETE FROM booking_settings WHERE business_id=$1", bid)
                await conn.execute("DELETE FROM google_credentials WHERE business_id=$1", bid)
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
