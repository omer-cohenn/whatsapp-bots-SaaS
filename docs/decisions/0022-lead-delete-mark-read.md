# 0022 — מחיקת ליד + סימון התראה כנקראה + סדר טאבים

> Status: **done** · Date: 2026-07-15 · Owner: Omer

## מה נבנה

### 1. מחיקת ליד לצמיתות (עמוד לידים)
בעל העסק יכול למחוק ליד ישן לגמרי מה-DB. לחיצה על "מחק" בכרטיס ליד פותחת
Modal לאישור — לחיצה שנייה על "כן, מחק לצמיתות" מבצעת `DELETE` אמיתי.

**גרום-cascade:** `flow_events` מחובר ל-`leads` עם `ON DELETE CASCADE` — לא נשארים שורות יתומות.

### 2. סימון התראות כנקראות (עמוד בית)
התראות ה"פיד" בבית מבוססות על לידים. שתי אפשרויות:
- **X על כל התראה** — מסמן ליד אחד כנקרא.
- **"סמן הכל כנקרא"** — מסמן את כל ההתראות הגלויות בבת אחת.

הנתון נשמר ב-DB (עמודה `leads.feed_seen_at`), לכן שרידותי לרענון עמוד.
התראות עם `feed_seen_at IS NOT NULL` מסוננות בצד הלקוח ולא מוצגות יותר.
הלידים עצמם **לא נמחקים** — רק לא מוצגים בפיד.

### 3. סדר טאבים — "הכול" לסוף
בעמוד **לידים**: הטאב "הכול" הועבר למקום האחרון (אחרי "נטשו").
בעמוד **שיחות**: הטאב "הכול" הועבר למקום האחרון (אחרי "סגורות").

## הגנה והפרדת שוכרים
- כל endpoint מסופק ב-`business_id` מ-session בלבד (לא מה-path/body).
- ה-`DELETE` ו-`UPDATE` מסוננים ב-`business_id = $2` — RLS + WHERE כפול.
- לא נרשם PII בשום log.

## Contract (API)

| Method | Path | קוד | תיאור |
|---|---|---|---|
| `DELETE` | `/api/leads/{lead_id}` | 204/404 | מחיקת ליד לצמיתות |
| `POST` | `/api/leads/{lead_id}/seen` | 200/404 | סימון ליד בודד כנקרא |
| `POST` | `/api/leads/seen-all` | 200 | סימון כל הלידים כנקראו |

## שינויי DB
- **Migration `0024_lead_feed_seen.sql`**: `ALTER TABLE leads ADD COLUMN IF NOT EXISTS feed_seen_at TIMESTAMPTZ`

## קבצים שהשתנו
- `supabase/migrations/0024_lead_feed_seen.sql` — migration
- `backend/app/services/leads/crud.py` — `delete_lead`, `mark_lead_feed_seen`, `mark_all_leads_feed_seen`
- `backend/app/services/leads/query.py` — `feed_seen_at` ב-SELECT + return dict
- `backend/app/services/leads/__init__.py` — export 3 פונקציות חדשות
- `backend/app/models/dashboard.py` — `feed_seen_at` ב-`LeadItem` + 3 response models
- `backend/app/api/dashboard.py` — 3 endpoints חדשים
- `frontend/src/dashboard/types.ts` — `feed_seen_at` ב-`Lead` type
- `frontend/src/lib/dashboardClient.ts` — `deleteLead`, `markLeadSeen`, `markAllLeadsSeen`
- `frontend/src/components/dashboard/ActivityFeed.tsx` — סינון + כפתורי סימון
- `frontend/src/pages/DashboardHome.tsx` — callbacks למחיקה/סימון
- `frontend/src/components/dashboard/LeadCard.tsx` — כפתור מחיקה + Modal אישור
- `frontend/src/pages/LeadsPage.tsx` — `onDelete` + סדר טאבים
- `frontend/src/pages/ConversationsPage.tsx` — סדר טאבים
