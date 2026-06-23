# 0017 — M13: Back-Office analytics + sales CRM (platform-operator)

> סטטוס: **מאושר (יאללה, רמת פלטפורמה), בבנייה** · תאריך: 2026-06-23 · קודם: 0016 (M12 back-office).
> הרחבה גדולה של M12: לוח מחוונים אמיתי לבעל ה‑SaaS — LTV, הודעות‑לחיוב, סוגי לידים, פעולות AI,
> פילוח לפי תוכנית — **ועוד שכבת CRM ברמת הפלטפורמה** (Omer מנהל צינור מכירות מול הלקוחות‑עסקים שלו).
> נבנה ב‑2 גלים: A) אנליטיקה · B) CRM. כל מה ש‑M12 קבע נשאר (השער, ה‑SD functions, RLS לא נחלש).

## הכרעה נעולה
ה‑CRM = **רמת פלטפורמה** (Omer מסמן/מחמם את הלקוחות‑עסקים שלו), לא ניהול לידים פר‑עסק (זה כבר M9/M10).

## הסיפור (בן 5)
חדר הבקרה הופך ללוח מחוונים של בעל SaaS: כמה כל לקוח שווה (LTV), כמה הודעות שולח (בסיס לחיוב), כמה לידים
מכל סוג (פגישה/ליד/נציג), כמה פעולות AI — והכל לפי תוכנית. ובנוסף **טבלת מכירות**: כל עסק כרטיס שנע
בעמודות *חדש→יצרתי קשר→מחמם→נסגר/אבד*, עם פתקים ותזכורת חזרה — כדי לדעת על מי לעבוד עד שמשלם.

## תלות וסיכונים
- בנוי על M12. **LTV = הערכה** (מחיר תוכנית × ותק) — אין billing אמיתי עדיין; מסומן "הערכה".
- גרפי מגמה (MRR/נטישה/פעילים) דורשים **snapshot יומי** — נצבר מהיום, לא ניתן לשחזר אחורה.
- `ai_call` + הודעות: `msg_in/out` כבר נספרים; `ai_call` חדש, מצטבר קדימה.
- leads‑by‑type **נגזר** (leads/bookings/flow_events) — בלי שינוי סכמה.
- אין scheduler → snapshot נחתם **בכל טעינת overview** (cron אמיתי בהמשך).

## ארכיטקטורה
| רכיב | חדש/קיים | תיאור |
|---|---|---|
| `usage_daily` + מטריקה `ai_call` | קיים + מטריקה | `bump_safe` בכל קריאת Gemini מוצלחת (bot builder + booking welcome) |
| `platform_snapshots` | טבלה חדשה | שורה ליום: total_businesses/active/paid/mrr/churn — היסטוריית מגמות |
| `business_crm` | טבלה חדשה | פר עסק: stage, last_contacted_at, next_followup_at — **admin בלבד (SD)** |
| `crm_notes` | טבלה חדשה | יומן פעולות פר עסק: note, admin_user_id, created_at — **admin בלבד (SD)** |
| LTV | מחושב | plan.price × months(started_at) בתוך SD function — אין טבלה |
| admin_* SD חדשות | חדש | analytics + CRM, EXECUTE ל‑app_role בלבד, מאחורי השער |
| `/api/admin/analytics/*` + `/crm/*` | חדש | endpoints מאחורי current_admin |
| frontend | חדש | AdminHome עשיר + עמוד billing/שימוש + לוח CRM + BusinessDetail מורחב |

## הלוגיקה
- שלבי CRM: `new → contacted → warming → won` / `lost` (הפיך; כל מעבר → admin_audit).
- LTV: price(plan) × חודשים מאז started_at (free → 0). מסומן "הערכה".
- סוגי לידים: פגישה = bookings · נציג = leads(lead_name='פנייה לנציג') · ליד = שאר ה‑leads הלא‑test.
- snapshot: בכל GET overview → upsert שורת היום (אידמפוטנטי).
- `ai_call`: אחרי קריאת Gemini מוצלחת ב‑endpoint, bump_safe בתוך tenant_connection.

## חוזה API (מאחורי current_admin)
| מסלול | מחזיר |
|---|---|
| `GET /api/admin/analytics/leads-by-type?period=&plan=` | ספירות פגישה/ליד/נציג |
| `GET /api/admin/analytics/messages?period=` | סך הודעות לכל עסק (חיוב) |
| `GET /api/admin/analytics/ai-ops?from=&to=` | ai_call ליום (+ פר עסק) |
| `GET /api/admin/analytics/by-plan?metric=&period=` | פילוח מטריקה לפי free/basic/pro |
| `GET /api/admin/analytics/trends?from=&to=` | סדרת snapshots (MRR/פעילים/נטישה) |
| `GET /api/admin/businesses/{id}` (הרחבה) | + ltv_estimate + ai_calls + crm |
| `GET /api/admin/crm` | לוח צינור (עסקים לפי שלב) |
| `PATCH /api/admin/businesses/{id}/crm` `{stage, next_followup?}` | מעדכן שלב + audit |
| `POST /api/admin/businesses/{id}/crm/notes` `{note}` | מוסיף פתק |

## עשרת ה‑Goals
1. Migration: platform_snapshots + business_crm + crm_notes (SD‑only, ללא grant ישיר ל‑app_role).
2. Migration: SD analytics (leads‑by‑type, messages, ai‑ops, by‑plan, trends, LTV ב‑detail/list).
3. Migration: SD CRM (list, set‑stage, add‑note, upsert‑today‑snapshot) + audit.
4. Backend: METRIC_AI_CALL + bump_safe בשתי נקודות Gemini.
5. Backend: analytics endpoints + models.
6. Backend: CRM endpoints + models; overview חותם snapshot היום.
7. Frontend: AdminHome עשיר (trends, donut סוגי לידים, by‑plan, ai‑ops).
8. Frontend: עמוד שימוש/חיוב (הודעות לכל עסק).
9. Frontend: לוח CRM + פאנל LTV/AI/CRM ב‑BusinessDetail.
10. QA + Security: בדיקות (403, צבירה, ai_call, סוגי לידים, by‑plan, CRM+audit, snapshot, negative‑control בידוד) + רגרסיה M2–M12.

## הסוכנים
data → backend → frontend (טורי) → QA (bizzup-test-runner) ∥ security review (מקבילי) → אימות+תיקון ב‑main loop → checkpoint. data מחזיר חוזה הדאטה; backend מחזיר חוזה ה‑API; frontend צורך אותו.

## אבטחה ובידוד
current_admin על הכל · business_crm/crm_notes/platform_snapshots רק דרך SD (אין grant ישיר) · כל כתיבת CRM → admin_audit · usage_daily = מספרים בלבד · LTV/CRM ללא PII של לקוחות‑קצה · negative‑control בידוד · חומת הטננטים לא נחלשת.
