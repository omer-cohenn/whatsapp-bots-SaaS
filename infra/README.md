# infra/ — 🧱 ההרצה (Docker Compose)

כל מה שהופך את הפרויקט **לניתן-להרצה, חוזר-על-עצמו ובטוח לפיתוח**: סטאק ה-docker-compose ותבניות
ה-env. פריסה לענן (AWS) היא נפרדת. המפה המלאה: [`../STRUCTURE.md`](../STRUCTURE.md).

## מה יש כאן
```
infra/
├── docker-compose.yml    # הסטאק המקומי (health-gated)
├── .env.example          # שמות כל הסודות (בלי ערכים) — חוזה
├── .env.example    # תבנית למילוי + גנרטורים → להעתיק ל-.env
└── .env            # הקובץ האמיתי (git-ignored, נוצר אוטומטית ע"י run.bat)
```

ה-compose מרים שישה שירותים, מסונכרנים לפי בריאות:
**postgres** → **redis** → **migrate** (מחיל את המיגרציות מ-`supabase/migrations/`) → **backend** → **gateway** → **frontend**.

## פורטים
| שירות | פורט | כתובת |
|---|---|---|
| frontend | 5173 | `http://127.0.0.1:5173` |
| gateway | 3000 | `http://127.0.0.1:3000/qr` (QR), `/inbox`, `/send` |
| backend | 8000 | `http://127.0.0.1:8000/healthz` |
| postgres / redis | — | **פנימי בלבד** (לא חשוף לרשת המארח) |

## איך מריצים
- **הרצה:** דאבל-קליק על `run.bat` (Docker Desktop חייב לרוץ). שקול-משווה: `make dev`.
  הוא מעביר אוטומטית `--env-file infra/.env`, ואם הקובץ חסר — מייצר אותו עם ערכים אקראיים.
- **עצירה:** `stop.bat` (או `make down`).
- **מילוי מפתחות אמיתיים** (Gemini / Google) → [`../ENV_SETUP.md`](../ENV_SETUP.md).

הפקודה הגולמית שמאחורי `run.bat`:
```bash
docker compose --env-file infra/.env -f infra/docker-compose.yml up --build
```

## חוקים
- **fail-closed:** ערך חובה חסר/ריק → האפליקציה מסרבת לעלות.
- אין ערכי "change-me" קבועים; הסודות האמיתיים רק ב-`.env` (git-ignored).
- בפרודקשן הסודות מגיעים מ-AWS Secrets Manager / KMS.
