# supabase/ — 🗄️ מסד הנתונים (Postgres)

מיגרציות SQL גרסאתיות — איפה כל הנתונים נשמרים. **ה-RLS (חומת הטננטים) חיה באותן מיגרציות** כמו
הטבלאות עצמן: עסק אחד לעולם לא רואה נתוני עסק אחר, וזה נאכף ב-DB, לא רק בקוד.
המפה המלאה: [`../STRUCTURE.md`](../STRUCTURE.md).

## מה יש כאן
```
supabase/
├── migrations/   # NNNN_*.sql בסדר עולה: טבלאות + RLS (USING+WITH CHECK) + grants + פונקציות
└── seed.sql      # נתוני דמו מודעי-טננט (2 עסקים), נזרעים דרך ה-roles האמיתיים
```

## מפת המיגרציות (0001…0021)
| טווח | מה נוסף |
|---|---|
| 0001–0002 | roles + extensions (pgcrypto), גשר ה-RLS (`current_business_id()`) |
| 0003–0004 | 9 הטבלאות + מדיניות RLS + grants לשני ה-roles הלא-service |
| 0005 | bootstrap לאימות (`provision_owner` / `get_user_businesses`, SECURITY DEFINER) |
| 0006–0007 | מטאטא לידים נטושים · הערת תוצאה מוצפנת |
| 0008–0012 | תורים (booking) + RLS + פתרון slug + תוספות שירות (תיאור/מחיר) + תמונה |
| 0013–0014 | פתרון חשבון וואטסאפ (`resolve_wa_account`) · מספרי בדיקה (allow-list, מוצפן) |
| 0015–0017 | בק-אופיס: plans/subscriptions · usage+audit · 5 פונקציות אדמין (SECURITY DEFINER) |
| 0018–0021 | M13: טבלאות snapshot/CRM · פונקציות אנליטיקה · פונקציות CRM · מחיקת עסק |

## איך מיגרציות מוחלות
שירות `migrate` ב-`infra/docker-compose.yml` מריץ את כל הקבצים מ-`migrations/` **בסדר** לפני שה-backend
עולה (חלק מ-`run.bat`). הקבצים **אדיטיביים ו-idempotent** (`IF NOT EXISTS` וכו') — אפשר להריץ שוב בבטחה.

## חוקים (חומת הטננטים)
- כל טבלה טננטית נושאת `business_id` + RLS עם `USING` **וגם** `WITH CHECK`.
- ה-`gateway_role` מקבל **אפס grant** על `whatsapp_credentials` (תכשיט הכתר).
- פונקציות חוצות-טננט (admin) הן `SECURITY DEFINER` עם `REVOKE ALL FROM PUBLIC` + `search_path` נעוץ — הדלת היחידה שחוצה את החומה, ובכוונה נעולה.

מפרט: [`../docs/spec/data-model.md`](../docs/spec/data-model.md) · חוזה החיבור: [`connection-contract.md`](connection-contract.md).
