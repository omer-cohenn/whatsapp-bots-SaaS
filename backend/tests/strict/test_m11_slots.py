"""M11 strict — SLOT ALGORITHM + RULES (compute_slots, driven directly).

Split out of the original test_m11.py (shared fixtures/helpers live in
_m11_helpers.py). Per decision 0011.

  2. SLOT ALGORITHM — split working-hours ranges yield exactly the right slots;
     two services with different durations differ; a closed weekday → [].
  3. RULES — min_notice / max_days_ahead / buffer filter correctly; computed in
     Asia/Jerusalem, stored UTC (DST offset).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest

from _m11_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    BIZ_A,
    FIXED_NOW,
    JLM,
    _future_date,
    _make_service,
    _set_settings,
    _wd_key,
    cleanup,
    pool,
    rds,
)
from app.db.session import tenant_connection
from app.services import booking as booking_service


# ============================================================================
#  GOAL 2 — SLOT ALGORITHM: split ranges + multi-service durations
# ============================================================================

@pytest.mark.asyncio
async def test_split_ranges_yield_exact_slots(pool, cleanup):
    """A weekday with TWO ranges 09-13 + 16-19 and a 60-min service yields exactly
    the morning starts 09..12 and the evening starts 16..18 (no buffer)."""
    # Use a date far enough out that min_notice never trims it, and a weekday that
    # is OPEN. We open only Wednesday (local weekday 2) with the split ranges.
    date = _future_date(7, weekday_local=2)  # a Wednesday
    wd = str((datetime.fromisoformat(date).weekday() + 1) % 7)  # our Sun=0 key
    await _set_settings(pool, BIZ_A, working_hours={
        wd: [{"s": "09:00", "e": "13:00"}, {"s": "16:00", "e": "19:00"}]
    }, min_notice=0, buffer=0)
    svc = await _make_service(pool, BIZ_A, duration=60)

    async with tenant_connection(pool, BIZ_A) as conn:
        slots = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date, now=FIXED_NOW)

    assert slots == ["09:00", "10:00", "11:00", "12:00",
                     "16:00", "17:00", "18:00"], slots


@pytest.mark.asyncio
async def test_multi_service_durations_differ(pool, cleanup):
    """Two services with different durations produce different slot grids on the
    same day/hours: a 30-min service has twice as many starts as a 60-min one."""
    date = _future_date(7, weekday_local=2)
    wd = str((datetime.fromisoformat(date).weekday() + 1) % 7)
    await _set_settings(pool, BIZ_A, working_hours={
        wd: [{"s": "09:00", "e": "12:00"}]
    }, min_notice=0, buffer=0)
    svc30 = await _make_service(pool, BIZ_A, name="קצר", duration=30)
    svc60 = await _make_service(pool, BIZ_A, name="ארוך", duration=60)

    async with tenant_connection(pool, BIZ_A) as conn:
        s30 = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc30, date_str=date, now=FIXED_NOW)
        s60 = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc60, date_str=date, now=FIXED_NOW)

    assert s30 == ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30"], s30
    assert s60 == ["09:00", "10:00", "11:00"], s60


@pytest.mark.asyncio
async def test_closed_weekday_returns_no_slots(pool, cleanup):
    """A weekday with no ranges configured → [] (the day is closed)."""
    date = _future_date(7, weekday_local=2)  # Wednesday
    # Only open MONDAY (local weekday 0 → our key); the requested Wed is closed.
    await _set_settings(pool, BIZ_A, working_hours={
        "1": [{"s": "09:00", "e": "17:00"}]  # our "1" = Monday
    }, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=30)

    async with tenant_connection(pool, BIZ_A) as conn:
        slots = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date, now=FIXED_NOW)
    assert slots == []


# ============================================================================
#  GOAL 3 — RULES: min_notice / max_days_ahead / buffer (Asia/Jerusalem → UTC)
# ============================================================================

@pytest.mark.asyncio
async def test_min_notice_trims_early_slots(pool, cleanup):
    """With now=09:00 local and min_notice=120, slots before 11:00 local on TODAY
    are removed; 11:00 onward survive."""
    # FIXED_NOW is 06:00 UTC = 09:00 local (summer DST). Book TODAY (same local day).
    today_local = FIXED_NOW.astimezone(JLM).date().isoformat()
    wd = str((datetime.fromisoformat(today_local).weekday() + 1) % 7)
    await _set_settings(pool, BIZ_A, working_hours={
        wd: [{"s": "09:00", "e": "14:00"}]
    }, min_notice=120, buffer=0)
    svc = await _make_service(pool, BIZ_A, duration=60)

    async with tenant_connection(pool, BIZ_A) as conn:
        slots = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=today_local, now=FIXED_NOW)

    # earliest bookable = 09:00 + 120min = 11:00 local. So 09:00/10:00 are gone.
    assert "09:00" not in slots and "10:00" not in slots
    assert slots[0] == "11:00", slots


@pytest.mark.asyncio
async def test_max_days_ahead_excludes_far_future(pool, cleanup):
    """A date beyond max_days_ahead yields [] even though the weekday is open."""
    await _set_settings(pool, BIZ_A, working_hours={
        "0": [{"s": "09:00", "e": "17:00"}],
        "1": [{"s": "09:00", "e": "17:00"}],
        "2": [{"s": "09:00", "e": "17:00"}],
        "3": [{"s": "09:00", "e": "17:00"}],
        "4": [{"s": "09:00", "e": "17:00"}],
        "5": [{"s": "09:00", "e": "17:00"}],
        "6": [{"s": "09:00", "e": "17:00"}],
    }, min_notice=0, max_days=7)
    svc = await _make_service(pool, BIZ_A, duration=60)

    far = _future_date(30)  # well beyond the 7-day window
    near = _future_date(3)
    async with tenant_connection(pool, BIZ_A) as conn:
        far_slots = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=far, now=FIXED_NOW)
        near_slots = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=near, now=FIXED_NOW)
    assert far_slots == []
    assert near_slots, "a within-window day should have slots"


@pytest.mark.asyncio
async def test_buffer_widens_step_and_blocks_neighbours(pool, cleanup):
    """A 30-min service with a 30-min buffer steps every 60 min (duration+buffer):
    the grid is 09:00/10:00/11:00/12:00. Booking 10:00 then removes ONLY 10:00 —
    the neighbours 09:00 and 11:00 sit exactly the buffer gap away and survive
    (back-to-back-with-gap is allowed; that's the point of the buffer)."""
    date = _future_date(7, weekday_local=2)
    wd = _wd_key(date)
    await _set_settings(pool, BIZ_A, working_hours={
        wd: [{"s": "09:00", "e": "13:00"}]
    }, min_notice=0, buffer=30)
    svc = await _make_service(pool, BIZ_A, duration=30)

    async with tenant_connection(pool, BIZ_A) as conn:
        before = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date, now=FIXED_NOW)
        # step = 30 (dur) + 30 (buffer) = 60 → 09:00,10:00,11:00,12:00
        assert before == ["09:00", "10:00", "11:00", "12:00"], before

        # Book 10:00. Its buffer-padded block is [09:30, 11:00]; the 09:00 and
        # 11:00 candidates touch that edge but do not OVERLAP it → they survive.
        start_utc = booking_service.local_to_utc(date, "10:00")
        await conn.execute(
            """
            INSERT INTO bookings
              (business_id, service_id, scheduled_at, duration_minutes, status,
               cancel_token, is_test)
            VALUES ($1, $2, $3, 30, 'confirmed', $4, true)
            """,
            BIZ_A, svc, start_utc, secrets.token_urlsafe(8))

        after = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date, now=FIXED_NOW)
    assert "10:00" not in after, "the booked slot was still offered"
    assert after == ["09:00", "11:00", "12:00"], after


@pytest.mark.asyncio
async def test_local_to_utc_dst_offset(pool, cleanup):
    """09:00 local on a summer date == 06:00 UTC (Asia/Jerusalem DST = +3)."""
    date = _future_date(7, weekday_local=2)  # June → IDT (+3)
    start_utc = booking_service.local_to_utc(date, "09:00")
    assert start_utc.tzinfo == timezone.utc
    assert start_utc.hour == 6 and start_utc.minute == 0, start_utc
