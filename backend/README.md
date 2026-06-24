# backend/ — 🧠 השרת (FastAPI)

המוח של Bizz_up. שירות Python / FastAPI שמקבל בקשות, מריץ את לוגיקת הבוט, שומר/קורא ממסד הנתונים
(בכפוף ל-RLS), ומדבר עם וואטסאפ ועם Google. כל קובץ קוד נושא **שורת הסבר בעברית** בראשו.
המפה המלאה: [`../STRUCTURE.md`](../STRUCTURE.md).

## התיקיות (השלטים)
```
backend/app/
├── main.py      # הרכבת האפליקציה: factory + lifespan (פותח pool ל-Postgres + Redis)
├── api/         # 🚪 הדלתות — נקודות הקצה (endpoints) שהעולם פונה אליהן
├── services/    # 🧩 המוח — כל הלוגיקה העסקית (בוט, לידים, תורים, וואטסאפ, אדמין...)
├── models/      # 📋 הטפסים — סכמות Pydantic לאימות קלט/פלט
├── core/        # 🔐 הכספת והחוקים — config (fail-closed), crypto, deps (שערי-אימות), logging
└── db/          # 🔌 הצינור — חיבור למסד בכפוף ל-RLS (SET LOCAL לפי טננט)
backend/tests/   # 🧪 הבדיקות — strict / narrated / isolation
```

### `api/` — הדלתות
`health.py` (`/healthz`) · `webhook.py` (`/webhook/whatsapp`) · `auth.py` (`/auth/*`) · `me.py` (קבוצת `/api/*` נעולה + `/api/me`) · `bot_builder.py` (M4) · `dashboard.py` (M7) · `booking.py` + `public_booking.py` (M11) · `google_oauth.py` (M11) · `whatsapp.py` (M6a) · `admin/` (חבילת הבק-אופיס מאחורי שער `current_admin` — businesses/analytics/crm).

### `services/` — המוח
`bot_engine.py` (מנוע טהור) · `bot_runtime.py` (חיבור לשמירה) · `bot_settings.py` · `bot_builder_ai.py` · `conversation_state.py` (Redis) · `live_chat.py` · `leads/` (crud/query/funnel) · `abandoned_sweep.py` · `booking/` (settings/slots/crud/google) · `booking_reminders.py` · `booking_alerts.py` · `booking_welcome.py` · `google_calendar.py` · `google_oauth.py` · `whatsapp.py` · `whatsapp_test_numbers.py` · `auth.py` · `usage.py`.

> `booking/` ו-`leads/` הן **חבילות** שפוצלו מקובץ-יחיד ארוך (ניקיון M15) בלי שינוי התנהגות. ה-`__init__.py`
> שלהן עושה re-export של כל המשטח הציבורי, כך שכל import קיים ממשיך לעבוד.

### `core/` — הכספת והחוקים
`config.py` (לא עולה בלי המפתחות) · `crypto.py` (הצפנה דו-מפתחית fail-loud) · `deps.py` (שער deny-by-default + `current_admin`) · `clients.py` · `logging.py` (בלי סודות/PII).

## איך מריצים את הבדיקות 🧪
הבדיקות רצות **בתוך קונטיינר ה-backend** (שם נמצאים המפתחות והקוד). הדרך הקלה — דאבל-קליק על
ה-`.bat` המתאים בתיקיית `tests/` בשורש (למשל `tests/test_m12.bat`). הוא מרים את הסטאק, מחיל מיגרציות,
ומריץ את הסיפור + ה-pytest + בדיקות קודמות.

ידנית מהשורש, כשהסטאק רץ:
```bash
# הסיפור המוסבר (narrated)
docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
  run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m12_full_test.py"

# שער ה-pytest הקשיח (strict)
docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
  run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && \
  PYTHONPATH=/app python -m pytest tests/strict -q"

# חומת הטננטים (isolation)
docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
  run --rm backend sh -c "cd /app && pip install -q pytest pytest-asyncio && \
  PYTHONPATH=/app python -m pytest tests/isolation -q"
```

## הרצה ישירה (בלי Docker)
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.lock
# צריך infra/.env.local מלא (ראה ../ENV_SETUP.md)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```
ב-compose ה-backend מגיע לשכנים דרך שם השירות (`postgres`, `redis`, `gateway`).

## חוקי הזהב
- **כל query טננטי מסונן ב-`business_id`** (RLS) — חיבור כ-`app_role`, לא service.
- **PII מוצפן at-rest** (לידים, creds) — אף פעם לא בלוג.
- **config fail-closed** — חסר מפתח = האפליקציה מסרבת לעלות.

מפרט מלא: [`../docs/spec/`](../docs/spec/) · החלטות: [`../docs/decisions/`](../docs/decisions/).
