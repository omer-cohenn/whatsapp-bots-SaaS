"""M11 strict — PUBLIC BOOKING + GUARDS + CANCEL/RESCHEDULE.

Split out of the original test_m11.py (shared fixtures/helpers live in
_m11_helpers.py). Per decision 0011.

  4. PUBLIC BOOKING — creates a LEAD + a booking; the RAW client PII columns are
     NOT plaintext (encrypted at rest) and decrypt for the owner.
  5. GUARDS — double-booking → 409; unknown slug → 404; junk fields rejected;
     off-grid time refused (never silently booked).
  6. CANCEL / RESCHEDULE — via cancel_token AND via owner PATCH both work.
"""

from __future__ import annotations

import secrets

import pytest

from _m11_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    AVI_USER,
    BIZ_A,
    _ALL_DAYS_9_17,
    _login,
    _make_service,
    _real_future_date,
    _set_settings,
    _wd_key,
    cleanup,
    http,
    lifespan_app,
    pool,
    rds,
)
from app.db.session import tenant_connection
from app.services import booking as booking_service


# ============================================================================
#  GOAL 4 — PUBLIC BOOKING: creates a lead + booking; PII encrypted at rest
# ============================================================================

@pytest.mark.asyncio
async def test_public_booking_creates_lead_and_encrypts_pii(http, rds, pool, cleanup):
    """POST /api/book/{slug} creates a lead + a booking; the RAW client_* DB
    columns are NOT plaintext, and the owner reads them back decrypted."""
    date = _real_future_date()
    slug = await _set_settings(pool, BIZ_A, working_hours={
        _wd_key(date): [{"s": "09:00", "e": "17:00"}],
    }, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)

    name = "ישראל ישראלי"
    phone = "+972500000001"
    email = "israel@example.com"
    notes = "מבקש פגישה בהקדם"

    r = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "09:00",
        "name": name, "phone": phone, "email": email, "notes": notes,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    booking_id = body["booking_id"]
    assert body["cancel_token"] and body["scheduled_at"]

    # Mark the created rows is_test so the cleanup fixture removes them.
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute(
            "UPDATE bookings SET is_test = true WHERE id = $1 AND business_id = $2",
            booking_id, BIZ_A)
        # The booking must link a LEAD.
        row = await conn.fetchrow(
            """SELECT lead_id, client_name, client_phone, client_email, notes
               FROM bookings WHERE id = $1 AND business_id = $2""",
            booking_id, BIZ_A)
        assert row["lead_id"] is not None, "booking did not link a lead"
        await conn.execute(
            "UPDATE leads SET is_test = true WHERE id = $1 AND business_id = $2",
            row["lead_id"], BIZ_A)
        lead = await conn.fetchrow(
            "SELECT id, status FROM leads WHERE id = $1", row["lead_id"])
        assert lead is not None, "linked lead row missing"

        # RAW columns must be ciphertext — NOT the plaintext PII.
        assert name not in (row["client_name"] or "")
        assert phone not in (row["client_phone"] or "")
        assert email not in (row["client_email"] or "")
        assert notes not in (row["notes"] or "")

    # The OWNER reads it back decrypted via the admin list.
    await _login(rds, http, AVI_USER, BIZ_A)
    rows = (await http.get("/api/bookings?include_test=true")).json()["bookings"]
    match = [b for b in rows if b["id"] == booking_id]
    assert match, "owner did not see the booking"
    b = match[0]
    assert b["client_name"] == name
    assert b["client_phone"] == phone
    assert b["client_email"] == email
    assert b["notes"] == notes


# ============================================================================
#  GOAL 5 — GUARDS: 409 double-booking, 404 unknown slug, junk-field rejection
# ============================================================================

@pytest.mark.asyncio
async def test_double_booking_returns_409(http, rds, pool, cleanup):
    """Booking the same free slot twice: the second attempt → 409."""
    date = _real_future_date()
    slug = await _set_settings(pool, BIZ_A, working_hours={
        _wd_key(date): [{"s": "09:00", "e": "17:00"}],
    }, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)

    base = {"service_id": svc, "date": date, "time": "10:00",
            "name": "א", "phone": "+972500000002"}
    r1 = await http.post(f"/api/book/{slug}", json=base)
    assert r1.status_code == 201, r1.text
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute(
            "UPDATE bookings SET is_test=true WHERE id=$1", r1.json()["booking_id"])
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_A)

    r2 = await http.post(f"/api/book/{slug}", json=base)
    assert r2.status_code == 409, r2.text


@pytest.mark.asyncio
async def test_unknown_slug_returns_404(http, cleanup):
    """An unprovisioned slug → 404 on every public route (no tenant leak)."""
    bogus = "does-not-exist-" + secrets.token_urlsafe(6)
    assert (await http.get(f"/api/book/{bogus}/services")).status_code == 404
    assert (await http.get(
        f"/api/book/{bogus}/slots?service_id=x&date=2099-06-10")).status_code == 404
    r = await http.post(f"/api/book/{bogus}", json={
        "service_id": "x", "date": "2099-06-10", "time": "09:00",
        "name": "a", "phone": "+972500000000"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_field_validation_rejects_junk(http, pool, cleanup):
    """Malformed date/time/phone in the public create body → 422 (Pydantic)."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)

    bad_date = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": "10/06/2099", "time": "09:00",
        "name": "a", "phone": "+972500000000"})
    assert bad_date.status_code == 422

    bad_time = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": "2099-06-10", "time": "9am",
        "name": "a", "phone": "+972500000000"})
    assert bad_time.status_code == 422

    empty_name = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": "2099-06-10", "time": "09:00",
        "name": "", "phone": "+972500000000"})
    assert empty_name.status_code == 422


@pytest.mark.asyncio
async def test_off_grid_time_rejected(http, pool, cleanup):
    """A well-formed time that is NOT an offered slot (off the grid) is rejected —
    never silently booked. The service re-derives the offered grid and refuses a
    time that isn't on it: a still-in-the-future off-grid time maps to 409 ("slot
    no longer available"), a past/closed one to 422. Either way: NOT 201, and no
    row is created."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)
    date = _real_future_date()
    # 09:17 is well-formed but never an offered start for a 60-min grid.
    r = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "09:17",
        "name": "a", "phone": "+972500000000"})
    assert r.status_code in (409, 422), r.text
    assert r.status_code != 201, "an off-grid time was silently booked!"
    async with tenant_connection(pool, BIZ_A) as conn:
        cnt = await conn.fetchval(
            "SELECT count(*) FROM bookings WHERE business_id=$1", BIZ_A)
    assert cnt == 0, "an off-grid booking row was created"


# ============================================================================
#  GOAL 6 — CANCEL / RESCHEDULE: via cancel_token AND via owner PATCH
# ============================================================================

@pytest.mark.asyncio
async def test_cancel_via_token_frees_slot(http, pool, cleanup):
    """Public cancel via cancel_token sets status=cancelled and frees the slot."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)
    date = _real_future_date()

    r = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "11:00",
        "name": "a", "phone": "+972500000003"})
    token = r.json()["cancel_token"]
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute(
            "UPDATE bookings SET is_test=true WHERE id=$1", r.json()["booking_id"])
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_A)
        # 11:00 is now taken (real-clock date → use the real now in compute_slots).
        taken = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date)
        assert "11:00" not in taken

    c = await http.post(f"/api/book/{slug}/cancel/{token}")
    assert c.status_code == 200 and c.json()["status"] == "cancelled"

    async with tenant_connection(pool, BIZ_A) as conn:
        freed = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date)
    assert "11:00" in freed, "cancelling did not free the slot"


@pytest.mark.asyncio
async def test_reschedule_via_token_moves_time(http, pool, cleanup):
    """Public reschedule via cancel_token moves scheduled_at to the new slot."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)
    date = _real_future_date()

    r = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "09:00",
        "name": "a", "phone": "+972500000004"})
    token = r.json()["cancel_token"]
    bid = r.json()["booking_id"]
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", bid)
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_A)

    rs = await http.post(f"/api/book/{slug}/reschedule/{token}",
                         json={"date": date, "time": "14:00"})
    assert rs.status_code == 200, rs.text
    new_utc = booking_service.local_to_utc(date, "14:00")
    assert rs.json()["scheduled_at"].startswith(new_utc.isoformat()[:16])


@pytest.mark.asyncio
async def test_owner_patch_status_and_reschedule(http, rds, pool, cleanup):
    """Owner PATCH /api/bookings/{id} sets status and reschedules the time."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)
    date = _real_future_date()
    r = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "09:00",
        "name": "a", "phone": "+972500000005"})
    bid = r.json()["booking_id"]
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", bid)
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_A)

    await _login(rds, http, AVI_USER, BIZ_A)
    # Confirm it.
    p1 = await http.patch(f"/api/bookings/{bid}", json={"status": "confirmed"})
    assert p1.status_code == 200 and p1.json()["status"] == "confirmed"
    # Reschedule it to 15:00.
    p2 = await http.patch(f"/api/bookings/{bid}", json={"date": date, "time": "15:00"})
    assert p2.status_code == 200
    new_utc = booking_service.local_to_utc(date, "15:00")
    assert p2.json()["scheduled_at"].startswith(new_utc.isoformat()[:16])


@pytest.mark.asyncio
async def test_cancel_unknown_token_404(http, pool, cleanup):
    """A cancel_token that isn't this page's → 404 (never touches a row)."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    r = await http.post(f"/api/book/{slug}/cancel/nope-{secrets.token_urlsafe(6)}")
    assert r.status_code == 404
