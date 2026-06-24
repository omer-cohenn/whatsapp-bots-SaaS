"""M13 narrated — phases 9–16 (split from _m13_story.py to keep each file < 500).

Not run directly. m13_full_test.py calls run_phases() (1–8, in _m13_story.py)
then run_phases_b() here, on the SAME client/lifespan — same printed output. The
shared seeding helpers + constants come from _m13_story.py. No secrets/PII.
"""

from __future__ import annotations

import json
from datetime import date

import asyncpg

from _m13_story import (
    ADMIN_EMAIL,
    BIZ_A,
    BIZ_B,
    UNKNOWN_BIZ,
    _bump,
    _login,
    _logout,
    _seed_booking,
    _seed_lead,
    _wipe,
)
from app.db.session import tenant_connection
from app.services import usage as usage_service


async def run_phases_b(story, http, redis, su, pool, admin_user) -> None:
    """מריץ את בדיקות 9–16 בסדר, על אותו client/lifespan, ומעדכן את ה‑Story."""
    banner, explain, result = story.banner, story.explain, story.result

    # ── בדיקה 9 — בליעת ai_call (החיווט האמיתי) ─────────────────────
    banner("9", "מונה ה‑ai_call באמת מתעדכן (החיווט של bot‑builder/booking)")
    explain(
        "מריצים את אותו bump_safe(ai_call) שה‑endpoint מריץ אחרי קריאת Gemini, "
        "וקוראים את usage_daily של היום",
        "המספרים בלוח טובים רק אם המונה באמת תופס כל פעולת AI. הקפצה אחת חייבת "
        "לנחות על שורת היום של העסק הנכון.")
    async with su.acquire() as conn:
        before = (await conn.fetchval(
            "SELECT count FROM usage_daily WHERE business_id=$1 AND "
            "day=current_date AND metric='ai_call'", BIZ_A)) or 0
    async with tenant_connection(pool, BIZ_A) as conn:
        await usage_service.bump_safe(conn, BIZ_A, usage_service.METRIC_AI_CALL)
    async with su.acquire() as conn:
        after_cnt = await conn.fetchval(
            "SELECT count FROM usage_daily WHERE business_id=$1 AND "
            "day=current_date AND metric='ai_call'", BIZ_A)
    result(after_cnt == before + 1,
           f"ai_call {before}→{after_cnt} (+1) — החיווט תופס")
    await _wipe(su)

    # ── בדיקה 10 — ה‑snapshot נחתם, ואידמפוטנטי ─────────────────────
    banner("10", "כל טעינת overview חותמת snapshot של היום — ואידמפוטנטי")
    explain(
        "קוראים overview פעמיים ובודקים שיש בדיוק שורת snapshot אחת להיום, "
        "ושה‑body מחזיר avg_ltv",
        "אין scheduler, אז ההיסטוריה למגמות נצברת בכל טעינה. אבל שתי טעינות "
        "באותו יום חייבות להשאיר שורה אחת — לא להכפיל את ההיסטוריה.")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    b1 = (await http.get("/api/admin/overview")).json()
    await http.get("/api/admin/overview")
    await _logout(redis, http, sid)
    async with su.acquire() as conn:
        rows = await conn.fetchval(
            "SELECT count(*) FROM platform_snapshots WHERE day=current_date")
    snap_ok = rows == 1 and "avg_ltv" in b1 and "total_ltv" in b1
    result(snap_ok,
           f"שורות snapshot להיום={rows} (אחת), overview כולל avg_ltv "
           f"({b1.get('avg_ltv')})")

    # ── בדיקה 11 — מגמות: הסדרה מכילה את היום ───────────────────────
    banner("11", "סדרת המגמות (trends) מכילה את ה‑snapshot של היום")
    explain(
        "אחרי שה‑overview חתם את היום, קוראים את סדרת המגמות",
        "גרפי ה‑MRR/פעילים/נטישה ניזונים מה‑snapshots. אחרי חתימה, היום חייב "
        "להופיע בסדרה עם מספרים שתואמים את ה‑overview.")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    overview = (await http.get("/api/admin/overview")).json()
    trends = (await http.get("/api/admin/analytics/trends")).json()
    await _logout(redis, http, sid)
    today_pt = next((p for p in trends["series"]
                     if p["day"] == date.today().isoformat()), None)
    trends_ok = (today_pt is not None
                 and today_pt["total_businesses"] == overview["total_businesses"]
                 and today_pt["active_count"] == overview["active_count"])
    result(trends_ok,
           f"היום בסדרה: עסקים={today_pt and today_pt['total_businesses']}, "
           f"פעילים={today_pt and today_pt['active_count']} — תואם overview")

    # ── בדיקה 12 — CRM: הזזת שלב + שובל אודיט ────────────────────────
    banner("12", "מזיזים עסק בצינור המכירות → השלב נשמר ונכתב אודיט עם זהות ה‑admin")
    explain(
        "כ‑admin מזיזים את אבי לשלב 'warming' עם תזכורת חזרה, ומציצים בלוח "
        "ובאודיט",
        "כל פעולת CRM היא חצייה של החומה — חייבת להשאיר טביעת אצבע: מי (ה‑Google "
        "sub + אימייל האמיתיים), מה (crm_stage), על איזה עסק.")
    await _wipe(su)
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    patch = await http.patch(
        f"/api/admin/businesses/{BIZ_A}/crm",
        json={"stage": "warming", "next_followup": "2026-07-01T09:00:00+00:00"})
    board = (await http.get("/api/admin/crm")).json()
    await _logout(redis, http, sid)
    row = next((c for c in board["businesses"] if c["business_id"] == BIZ_A), None)
    async with su.acquire() as conn:
        audit = await conn.fetchrow(
            "SELECT admin_user_id, admin_email, action, target_business_id, "
            "detail FROM admin_audit WHERE target_business_id=$1 "
            "AND action='crm_stage' ORDER BY created_at DESC LIMIT 1", BIZ_A)
    d = (audit["detail"] if isinstance(audit["detail"], dict)
         else json.loads(audit["detail"])) if audit else {}
    crm_ok = (
        patch.status_code == 200
        and patch.json()["stage"] == "warming"
        and row is not None and row["stage"] == "warming"
        and audit is not None
        and audit["admin_user_id"] == admin_user
        and audit["admin_email"] == ADMIN_EMAIL
        and audit["action"] == "crm_stage"
        and str(audit["target_business_id"]) == BIZ_A
        and d == {"stage": "warming"})
    result(crm_ok,
           "אבי עבר ל‑'warming' בלוח; אודיט נחתם עם ה‑admin id+email האמיתיים, "
           "action=crm_stage, על העסק הנכון")

    # ── בדיקה 13 — פתקי CRM: הלוך‑ושוב + ספירה + קלט שגוי ────────────
    banner("13", "פתק CRM נכתב (201), חוזר חדש‑קודם, וספירת הפתקים עולה")
    explain(
        "כ‑admin מוסיפים שני פתקים, קוראים את היומן, ובודקים את ספירת הפתקים "
        "בלוח; וגם פתק ריק וענק‑לא‑קיים",
        "היומן מאפשר ל‑Omer לזכור מה דובר מול כל לקוח. פתק חייב לחזור חדש‑קודם, "
        "הספירה חייבת לעלות, וקלט שגוי חייב להידחות נקי (422/404).")
    await _wipe(su)
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    board0 = (await http.get("/api/admin/crm")).json()
    base_count = next((c["note_count"] for c in board0["businesses"]
                       if c["business_id"] == BIZ_A), 0)
    r1 = await http.post(f"/api/admin/businesses/{BIZ_A}/crm/notes",
                         json={"note": "התקשרתי לבעלים; ליד חם"})
    r2 = await http.post(f"/api/admin/businesses/{BIZ_A}/crm/notes",
                         json={"note": "נגיעה שנייה; שלחתי מחירון"})
    notes = (await http.get(
        f"/api/admin/businesses/{BIZ_A}/crm/notes")).json()["notes"]
    board1 = (await http.get("/api/admin/crm")).json()
    new_count = next((c["note_count"] for c in board1["businesses"]
                      if c["business_id"] == BIZ_A), 0)
    blank = (await http.post(f"/api/admin/businesses/{BIZ_A}/crm/notes",
                             json={"note": "   "})).status_code
    unknown = (await http.post(f"/api/admin/businesses/{UNKNOWN_BIZ}/crm/notes",
                               json={"note": "x"})).status_code
    await _logout(redis, http, sid)
    ids = [n["id"] for n in notes]
    notes_ok = (
        r1.status_code == 201 and r2.status_code == 201
        and r1.json()["note_id"] in ids and r2.json()["note_id"] in ids
        and ids.index(r2.json()["note_id"]) < ids.index(r1.json()["note_id"])
        and notes[0]["note"] == "נגיעה שנייה; שלחתי מחירון"
        and notes[0]["admin_email"] == ADMIN_EMAIL
        and new_count == base_count + 2
        and blank == 422 and unknown == 404)
    result(notes_ok,
           f"שני פתקים נכתבו (201), חזרו חדש‑קודם, ספירה {base_count}→{new_count} "
           f"(+2); פתק ריק→{blank}, עסק לא‑קיים→{unknown}")
    await _wipe(su)

    # ── בדיקה 14 — בידוד: טבלאות ה‑CRM/snapshots מחוץ לתחום ─────────
    banner("14", "עסק רגיל לא יכול לקרוא ישירות business_crm / crm_notes / snapshots")
    explain(
        "ב‑app role רגיל מנסים לקרוא ישירות את שלוש טבלאות חדר‑הבקרה החדשות; "
        "ואז אבי מנסה לקרוא את שורות ה‑usage של בלה",
        "חציית החומה אפשרית רק דרך פונקציות ה‑SD הצרות. שלוש הטבלאות נותנות "
        "ל‑app role אפס גישה ישירה, ו‑usage עדיין מציית לחומה — אבי לא רואה את בלה.")
    crm_denied = notes_denied = snap_denied = False
    try:
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.fetch("SELECT * FROM business_crm")
    except asyncpg.InsufficientPrivilegeError:
        crm_denied = True
    try:
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.fetch("SELECT * FROM crm_notes")
    except asyncpg.InsufficientPrivilegeError:
        notes_denied = True
    try:
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.fetch("SELECT * FROM platform_snapshots")
    except asyncpg.InsufficientPrivilegeError:
        snap_denied = True
    async with tenant_connection(pool, BIZ_A) as conn:
        b_rows = await conn.fetch(
            "SELECT * FROM usage_daily WHERE business_id=$1", BIZ_B)
    # הדלת המורשית (פונקציית ה‑SD) עדיין עובדת על conn רגיל.
    async with pool.acquire() as conn:
        crm_list = await conn.fetch("SELECT * FROM admin_crm_list()")
    iso_ok = (crm_denied and notes_denied and snap_denied
              and b_rows == [] and len(crm_list) >= 2)
    result(iso_ok,
           f"business_crm denied={crm_denied}, crm_notes denied={notes_denied}, "
           f"snapshots denied={snap_denied}; אבי רואה {len(b_rows)} משורות בלה; "
           f"פונקציית ה‑SD עדיין עובדת (הדלת היחידה)")

    # ── בדיקה 15 — NEGATIVE CONTROL: שוברים את החומה, רואים שנתפס ────
    banner("15", "NEGATIVE CONTROL: נותנים grant ידני, רואים שנפתח — ואז מחזירים")
    explain(
        "נותנים ל‑app role GRANT SELECT ישיר על crm_notes, מוודאים שהקריאה "
        "מצליחה (כלומר הבדיקה מסוגלת לתפוס דליפה) — ואז REVOKE ומוודאים שוב חסום",
        "בדיקה טובה חייבת להיות מסוגלת להיכשל. אם נשלול את ה‑grant ושום דבר "
        "לא ישתנה — החומה פתוחה. מוכיחים שהחסימה היא grant אמיתי וניתן‑להסרה, "
        "ומחזירים את הכול.")
    opened = restored = False
    async with su.acquire() as conn:
        await conn.execute("GRANT SELECT ON crm_notes TO app_role")
    try:
        async with tenant_connection(pool, BIZ_A) as conn:
            leaked = await conn.fetch("SELECT * FROM crm_notes")
        opened = isinstance(leaked, list)  # הדלת נפתחה — אפשר לראות דליפה
    except asyncpg.InsufficientPrivilegeError:
        opened = False
    async with su.acquire() as conn:
        await conn.execute("REVOKE SELECT ON crm_notes FROM app_role")
    try:
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.fetch("SELECT * FROM crm_notes")
    except asyncpg.InsufficientPrivilegeError:
        restored = True
    result(opened and restored,
           "grant ידני → הקריאה הצליחה (הבדיקה מסוגלת לתפוס דליפה); "
           "REVOKE → חסום שוב (שוחזר)")

    # ── בדיקה 16 — בלי דליפת PII ────────────────────────────────────
    banner("16", "אף תגובת אנליטיקה/CRM לא מחזירה PII של לקוח‑קצה")
    explain(
        "זורעים פנייה‑לנציג + פגישה (כדי שהדליים לא יהיו אפס), וסורקים את כל "
        "מפתחות התגובות מול רשימה אסורה (טלפון/שם/תשובות/טקסט הודעה)",
        "חדר הבקרה מציג זהות + מספרים + הקשר מכירות — לעולם לא תוכן של לקוח‑קצה. "
        "טקסט הפתק של ה‑CRM הוא נתון מכירות של Omer, אבל גם הוא לא דולף החוצה.")
    await _seed_lead(su, BIZ_A, handoff=True)
    await _seed_booking(su, BIZ_A)
    forbidden = {"phone", "client_phone", "contact_name", "client_name",
                 "lead_name", "message", "text", "answers", "client_email",
                 "meet_link"}
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    lbt = (await http.get(
        "/api/admin/analytics/leads-by-type?period=all")).json()
    msgs = (await http.get("/api/admin/analytics/messages?period=all")).json()
    crm = (await http.get("/api/admin/crm")).json()
    detail = (await http.get(f"/api/admin/businesses/{BIZ_A}")).json()
    await _logout(redis, http, sid)
    leak = False
    if set(lbt.keys()) != {"booking", "lead", "handoff"}:
        leak = True
    for r in msgs["businesses"]:
        if set(r.keys()) & forbidden:
            leak = True
    for c in crm["businesses"]:
        if set(c.keys()) & forbidden:
            leak = True
    if set(detail.keys()) & forbidden:
        leak = True
    result(not leak,
           "כל מפתחות התגובות הם זהות/מספרים/הקשר‑מכירות — אפס מפתח של "
           "לקוח‑קצה (טלפון/שם/תשובות) דלף")
    await _wipe(su)
