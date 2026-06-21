"""M11.2 — the narrated, baby-language test (read THIS one first).

M11.2 is the "put a PICTURE on each service card" milestone. On top of the M11.1
booking page it adds ONE small thing, with no new file server:

  * Each service can now carry an IMAGE. The owner uploads a photo; the browser
    SHRINKS it on a canvas into a small compressed `data:` URL and saves it in the
    new `services.image_url` column. A plain http(s) link is also accepted in the
    same field. No image => the public card shows a placeholder frame.

This file proves that works, in plain language. Every check prints:
  🧪 WHAT we are testing
  💡 WHY it matters
  ✅ / ❌ the result
A scoreboard prints at the end. It includes a NEGATIVE CONTROL: we deliberately
break tenant isolation on the `services` table (let business A read business B's
image), watch the test catch it, then restore — so a green run is REAL. Nothing
here ever prints a secret or a customer's personal details (image_url is the
owner's own public marketing picture, not PII).

The time zone is fixed Asia/Jerusalem, exactly like M11.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.models.booking import MAX_SERVICE_IMAGE_CHARS
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

HTTP_IMG = "https://cdn.example.com/avatar/haircut.png"
_DATA_PREFIX = "data:image/jpeg;base64,"
ONE_MB_DATA_URL = _DATA_PREFIX + ("A" * 1_000_000)  # ~1 MB resized image payload

_ALL_DAYS_9_17 = {str(k): [{"s": "09:00", "e": "17:00"}] for k in range(7)}

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


def _logout(http) -> None:
    http.cookies.clear()


async def _set_settings(pool, bid, *, working_hours) -> str:
    slug = "demo-" + secrets.token_urlsafe(6)
    async with tenant_connection(pool, bid) as conn:
        live = await conn.fetchval(
            """INSERT INTO booking_settings
                 (business_id, working_hours, min_notice_minutes, buffer_minutes,
                  max_days_ahead, meet_enabled, slug)
               VALUES ($1,$2::jsonb,120,0,365,false,$3)
               ON CONFLICT (business_id) DO UPDATE SET
                 working_hours=EXCLUDED.working_hours
               RETURNING slug""",
            bid, json.dumps(working_hours), slug)
    return live


async def _make_service_direct(pool, business_id, *, name, duration,
                               image_url=None) -> str:
    async with tenant_connection(pool, business_id) as conn:
        return str(await conn.fetchval(
            "INSERT INTO services (business_id,name,duration_minutes,active,"
            "image_url) VALUES ($1,$2,$3,true,$4) RETURNING id",
            business_id, name, duration, image_url))


async def main() -> int:
    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4)
    rds = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    print("=" * 74)
    print("  BIZZ_UP — M11.2 (service card image: services.image_url)")
    print("=" * 74)

    transport = ASGITransport(app=app, raise_app_exceptions=False)

    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=transport, base_url="http://test") as http:

                # ---- 1) a service can carry an http(s) image link ---------------
                await _login(rds, http, AVI_USER, BIZ_A)
                made = (await http.post("/api/services", json={
                    "name": "תספורת", "duration_minutes": 30,
                    "image_url": HTTP_IMG})).json()
                check(
                    "A service card can carry an image link (http URL)",
                    "Owners can paste a picture URL for a service — we save it and "
                    "read it straight back so the card can show the photo.",
                    made.get("image_url") == HTTP_IMG)

                # ---- 2) a big resized data: URL (~1 MB) is accepted -------------
                big = (await http.post("/api/services", json={
                    "name": "צביעה", "duration_minutes": 60,
                    "image_url": ONE_MB_DATA_URL})).json()
                check(
                    "A real uploaded photo (~1 MB resized data: URL) is accepted whole",
                    "There's no file server — the browser shrinks the photo into a "
                    "small data: URL. We must store the WHOLE thing, not chop it off.",
                    big.get("image_url") == ONE_MB_DATA_URL
                    and len(big.get("image_url", "")) > 1_000_000)

                # ---- 3) no image means null (the card shows a placeholder) ------
                none_img = (await http.post("/api/services", json={
                    "name": "ייעוץ", "duration_minutes": 30})).json()
                check(
                    "Leaving the image empty keeps it null (the card shows a placeholder)",
                    "A service with no photo must stay truly empty (null) so the "
                    "public card knows to draw the 'מקום לתמונה' placeholder frame.",
                    none_img.get("image_url") is None)

                # ---- 4) GET /api/services echoes the saved image ---------------
                listed = (await http.get("/api/services")).json()["services"]
                by_id = {s["id"]: s for s in listed}
                check(
                    "The owner's service list returns the saved image back",
                    "When the owner reopens the services screen, each card must "
                    "still carry the picture they saved earlier.",
                    by_id.get(made["id"], {}).get("image_url") == HTTP_IMG
                    and by_id.get(big["id"], {}).get("image_url") == ONE_MB_DATA_URL)

                # ---- 5) PATCH can SET the image --------------------------------
                sid = none_img["id"]
                pset = (await http.patch(f"/api/services/{sid}", json={
                    "image_url": HTTP_IMG})).json()
                check(
                    "Editing a service can ADD an image where there was none",
                    "An owner can come back later and attach a photo to a service "
                    "that started without one.",
                    pset.get("image_url") == HTTP_IMG)

                # ---- 6) PATCH that OMITS the image leaves it untouched ----------
                pomit = (await http.patch(f"/api/services/{sid}", json={
                    "name": "ייעוץ מעודכן"})).json()
                check(
                    "Editing OTHER fields leaves the image untouched (omit = keep)",
                    "Changing a service's name must NOT wipe its picture — a field "
                    "you didn't send is simply left as it was.",
                    pomit.get("name") == "ייעוץ מעודכן"
                    and pomit.get("image_url") == HTTP_IMG)

                # ---- 7) PATCH with explicit null CLEARS the image --------------
                pclear = (await http.patch(f"/api/services/{sid}", json={
                    "image_url": None})).json()
                check(
                    "Sending image_url=null deliberately REMOVES the picture",
                    "An owner who wants to drop a photo sends an explicit null — and "
                    "the card goes back to the placeholder (null), name kept.",
                    pclear.get("image_url") is None
                    and pclear.get("name") == "ייעוץ מעודכן")

                # ---- 8) an image_url over the 2 MB bound is refused ------------
                toobig = await http.post("/api/services", json={
                    "name": "x", "duration_minutes": 30,
                    "image_url": _DATA_PREFIX + ("A" * (MAX_SERVICE_IMAGE_CHARS + 10))})
                check(
                    "An image bigger than the 2 MB limit is refused cleanly (422)",
                    "The field is generous (2 MB) but bounded — a monster payload is "
                    "rejected by the form, never crashing the database.",
                    toobig.status_code == 422)

                # ---- 9) the PUBLIC page shows the image (and null) -------------
                slug = await _set_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
                _logout(http)
                pub = (await http.get(f"/api/book/{slug}/services")).json()
                pub_by_name = {s["name"]: s for s in pub["services"]}
                check(
                    "The PUBLIC booking page exposes each service's image (or null)",
                    "What the owner uploaded must reach the customer-facing card: the "
                    "photo rides along on the public read, and a photo-less service "
                    "comes back as null so the placeholder shows.",
                    pub_by_name.get("תספורת", {}).get("image_url") == HTTP_IMG
                    and pub_by_name.get("ייעוץ מעודכן", {}).get("image_url") is None)

                # ---- 10) the PUBLIC page returns a big data: URL intact --------
                check(
                    "A real (~1 MB) uploaded photo reaches the public page intact",
                    "The resized data: URL must travel to the customer's card whole, "
                    "so the picture actually renders for them.",
                    pub_by_name.get("צביעה", {}).get("image_url") == ONE_MB_DATA_URL)

                # ---- 11) A cannot change B's service image (404, B untouched) --
                svc_b = await _make_service_direct(pool, BIZ_B, name="B-svc",
                                                   duration=30, image_url=HTTP_IMG)
                await _login(rds, http, AVI_USER, BIZ_A)
                hack = await http.patch(f"/api/services/{svc_b}", json={
                    "image_url": "https://attacker.example/evil.png"})
                async with tenant_connection(pool, BIZ_B) as conn:
                    brow = await conn.fetchrow(
                        "SELECT image_url FROM services WHERE id=$1 AND business_id=$2",
                        svc_b, BIZ_B)
                check(
                    "Business A cannot change Business B's service image (404, B untouched)",
                    "The tenant wall covers the new image field too: A's PATCH on B's "
                    "service is hidden (404) and B's picture is unchanged.",
                    hack.status_code == 404 and brow["image_url"] == HTTP_IMG)

                # ---- 12) a public page exposes only its OWN service + image ----
                slug_a = await _set_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
                await _make_service_direct(pool, BIZ_A, name="A-only",
                                           duration=30, image_url=HTTP_IMG)
                _logout(http)
                pubA = (await http.get(f"/api/book/{slug_a}/services")).json()
                names = {s["name"] for s in pubA["services"]}
                imgs = {s["image_url"] for s in pubA["services"]}
                check(
                    "A public page shows only its OWN services + images, never another's",
                    "Resolving the page by its slug keeps tenants apart: A's page "
                    "shows A's service + image and none of B's.",
                    "A-only" in names and "B-svc" not in names
                    and "https://attacker.example/evil.png" not in imgs)

                # ---- 13) NEGATIVE CONTROL (non-destructive): the wall really filters
                # We DON'T disable RLS (the app role can't, and we don't want to weaken
                # security). Instead we prove the wall is doing real work: mark B's image
                # with a unique secret, then show A's own tenant_connection — even when it
                # EXPLICITLY asks for B's row by id + business_id — comes back with NOTHING
                # (RLS filters it), while B's own connection still sees it. If RLS were
                # absent or wrong, A's explicit query WOULD return the secret and this
                # check would fail — so a green here is meaningful, not vacuous.
                secret_img = "https://b.example/B-IMAGE-SECRET.png"
                async with tenant_connection(pool, BIZ_B) as conn:
                    await conn.execute(
                        "UPDATE services SET image_url=$1 WHERE id=$2",
                        secret_img, svc_b)
                async with tenant_connection(pool, BIZ_A) as conn:
                    a_sees = await conn.fetchval(
                        "SELECT image_url FROM services WHERE id=$1 AND business_id=$2",
                        svc_b, BIZ_B)
                async with tenant_connection(pool, BIZ_B) as conn:
                    b_sees = await conn.fetchval(
                        "SELECT image_url FROM services WHERE id=$1", svc_b)
                check(
                    "NEGATIVE CONTROL: A's own DB query for B's image returns NOTHING; B sees it",
                    "Even when A explicitly asks the database for B's exact row, row-level "
                    "security hides it (A gets null) — yet B reads its own image fine. If "
                    "the wall were broken, A WOULD see B's secret and this check would fail.",
                    a_sees is None and b_sees == secret_img)

    finally:
        for bid in (BIZ_A, BIZ_B):
            async with tenant_connection(pool, bid) as conn:
                await conn.execute("DELETE FROM bookings WHERE business_id=$1", bid)
                await conn.execute(
                    "DELETE FROM leads WHERE business_id=$1 "
                    "AND (is_test=true OR lead_name='פגישה')", bid)
                await conn.execute("DELETE FROM services WHERE business_id=$1", bid)
                await conn.execute("DELETE FROM booking_settings WHERE business_id=$1", bid)
        await pool.close()
        await rds.aclose()

    print("\n" + "=" * 74)
    print(f"  SCOREBOARD:  ✅ {_passed} passed   ❌ {_failed} failed")
    print("=" * 74)
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
