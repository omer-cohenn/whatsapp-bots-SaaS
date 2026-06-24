"""M13 strict — CRM stage move + audit; note round-trip; validation.

Split out of the original test_m13.py (shared fixtures/helpers live in
_m13_helpers.py). Authoritative contract:
docs/decisions/0017-m13-backoffice-analytics-crm.md.

  CRM  PATCH stage moves a business + writes an admin_audit row stamped with the
       REAL admin Google sub + email; bad stage → 422; unknown business → 404.
       POST note → 201 + GET notes returns it newest-first + the crm_list
       note_count increments; blank note → 422; unknown biz → 404.
"""

from __future__ import annotations

import json

import pytest

from _m13_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    ADMIN_EMAIL,
    BIZ_A,
    UNKNOWN_BIZ,
    _login,
    _logout,
    admin_user,
    clean_m13,
    http,
    lifespan_app,
    redis,
    su,
)


# ============================================================================
#  CRM — stage move + audit; note round-trip; validation
# ============================================================================


@pytest.mark.asyncio
async def test_crm_stage_moves_and_audits(http, redis, su, admin_user, clean_m13):
    """PATCH stage to 'warming' moves the business in admin_crm_list AND writes an
    admin_audit row stamped with the REAL admin Google sub + email."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/crm",
            json={"stage": "warming", "next_followup": "2026-07-01T09:00:00+00:00"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["business_id"] == BIZ_A
        assert body["stage"] == "warming"
        assert body["next_followup_at"] is not None

        board = (await http.get("/api/admin/crm")).json()
        row = next(
            (c for c in board["businesses"] if c["business_id"] == BIZ_A), None
        )
        assert row is not None and row["stage"] == "warming"
    finally:
        await _logout(redis, http, sid)

    # The audit row is verifiable only via the SD-owner path → read as superuser.
    async with su.acquire() as conn:
        audit = await conn.fetchrow(
            "SELECT admin_user_id, admin_email, action, target_business_id, detail "
            "FROM admin_audit WHERE target_business_id = $1 AND action = 'crm_stage' "
            "ORDER BY created_at DESC LIMIT 1",
            BIZ_A,
        )
    assert audit is not None
    assert audit["admin_user_id"] == admin_user  # the REAL Google sub
    assert audit["admin_email"] == ADMIN_EMAIL
    assert audit["action"] == "crm_stage"
    assert str(audit["target_business_id"]) == BIZ_A
    detail = audit["detail"]
    detail = detail if isinstance(detail, dict) else json.loads(detail)
    assert detail == {"stage": "warming"}


@pytest.mark.asyncio
async def test_crm_bad_stage_422(http, redis, admin_user):
    """A stage outside the vocabulary → 422 (the Literal rejects before the SD call)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/crm", json={"stage": "frozen"}
        )
        assert r.status_code == 422
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_crm_unknown_business_404(http, redis, admin_user, clean_m13):
    """An unknown (well-formed) business id → 404; a malformed uuid → 404 too."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        assert (
            await http.patch(
                f"/api/admin/businesses/{UNKNOWN_BIZ}/crm", json={"stage": "won"}
            )
        ).status_code == 404
        assert (
            await http.patch(
                "/api/admin/businesses/not-a-uuid/crm", json={"stage": "won"}
            )
        ).status_code == 404
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_crm_note_roundtrip_and_count(http, redis, su, admin_user, clean_m13):
    """POST a note → 201; GET notes returns it newest-first; the crm_list note_count
    increments; a second note comes back ahead of the first."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        # Baseline note_count from the board.
        board0 = (await http.get("/api/admin/crm")).json()
        base_count = next(
            (c["note_count"] for c in board0["businesses"] if c["business_id"] == BIZ_A),
            0,
        )

        r1 = await http.post(
            f"/api/admin/businesses/{BIZ_A}/crm/notes",
            json={"note": "called the owner; warm lead"},
        )
        assert r1.status_code == 201, r1.text
        note1 = r1.json()["note_id"]
        assert note1

        r2 = await http.post(
            f"/api/admin/businesses/{BIZ_A}/crm/notes",
            json={"note": "second touch; sent pricing"},
        )
        assert r2.status_code == 201
        note2 = r2.json()["note_id"]

        notes = (
            await http.get(f"/api/admin/businesses/{BIZ_A}/crm/notes")
        ).json()["notes"]
        ids = [n["id"] for n in notes]
        assert note1 in ids and note2 in ids
        # Newest first: note2 appears before note1.
        assert ids.index(note2) < ids.index(note1)
        assert notes[0]["note"] == "second touch; sent pricing"
        # The admin's display email is on the note (no end-customer PII).
        assert notes[0]["admin_email"] == ADMIN_EMAIL

        board1 = (await http.get("/api/admin/crm")).json()
        new_count = next(
            (c["note_count"] for c in board1["businesses"] if c["business_id"] == BIZ_A),
            0,
        )
        assert new_count == base_count + 2
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_crm_note_blank_422(http, redis, admin_user, clean_m13):
    """A whitespace-only note → 422 (the request model strips + min_length rejects)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        assert (
            await http.post(
                f"/api/admin/businesses/{BIZ_A}/crm/notes", json={"note": "   "}
            )
        ).status_code == 422
        # Empty body / missing note → 422 too.
        assert (
            await http.post(f"/api/admin/businesses/{BIZ_A}/crm/notes", json={})
        ).status_code == 422
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_crm_note_unknown_business_404(http, redis, admin_user, clean_m13):
    """A note on an unknown business → 404 (the SD FK violation maps to not-found)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        assert (
            await http.post(
                f"/api/admin/businesses/{UNKNOWN_BIZ}/crm/notes", json={"note": "x"}
            )
        ).status_code == 404
    finally:
        await _logout(redis, http, sid)
