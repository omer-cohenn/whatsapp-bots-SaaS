# STRUCTURE.md — מפת הריפו של Bizz_up 🗺️

> המפה הראשית של הפרויקט. שומרים את **השמות הטכניים** של התיקיות (`api`/`services`/`models`/`core`/`db`
> הם קונבנציה אוניברסלית — לשנותם שובר imports ומבלבל כל מפתח/סוכן), ומוסיפים מעליהם **"שלטים בעברית"**:
> המסמך הזה, `README.md` בכל תחום, ושורת הסבר בעברית בראש כל קובץ קוד.
> כך מבינים את המבנה במבט — בלי לשבור כלום. (החלטה: [`docs/decisions/0019-m15-repo-cleanup.md`](docs/decisions/0019-m15-repo-cleanup.md).)

---

## מאיפה מתחילים 🚦

1. **לקרוא איפה אנחנו** → [`docs/STATUS.md`](docs/STATUS.md) (תמיד הקובץ הראשון בכל סשן חדש).
2. **להריץ את הכל** → דאבל-קליק על `run.bat` (צריך Docker Desktop פתוח). לעצור: `stop.bat`.
   * כתובות: ממשק `http://127.0.0.1:5173` · QR לוואטסאפ `http://127.0.0.1:3000/qr` · backend `:8000`.
3. **למלא מפתחות אמיתיים** → [`ENV_SETUP.md`](ENV_SETUP.md) (מה חובה למלא כדי לעבוד עם API אמיתיים).
4. **המפה הזאת** → להתמצא בכל תיקייה וקובץ.

---

## חמשת התחומים (ריפו אחד, 5 מגירות ברורות)

| תיקייה | בעברית | טכנולוגיה | README |
|---|---|---|---|
| `backend/` | 🧠 השרת — המוח של המערכת | Python / FastAPI | [`backend/README.md`](backend/README.md) |
| `gateway/` | 💬 וואטסאפ — החיבור לטלפון | Node.js / Baileys | [`gateway/README.md`](gateway/README.md) |
| `frontend/` | 🎨 הממשק — מה שהמשתמש רואה | React + Tailwind | [`frontend/README.md`](frontend/README.md) |
| `infra/` | 🧱 ההרצה — איך מרימים את הכל | Docker Compose | [`infra/README.md`](infra/README.md) |
| `supabase/` | 🗄️ מסד הנתונים — איפה הכל נשמר | Postgres (SQL) | [`supabase/README.md`](supabase/README.md) |
| `docs/` | 📚 התיעוד — למה החלטנו מה שהחלטנו | Markdown | [`docs/README.md`](docs/README.md) |

עוד בשורש: `tests/` = כפתורי הרצה (`.bat`) לבדיקות · `.claude/` = סוכני ה-AI · `run.bat`/`stop.bat`/`Makefile` = פקודות הרצה · `CLAUDE.md` = ספר החוקים לסוכנים.

---

## `backend/` — 🧠 השרת (FastAPI)

המוח: מקבל בקשות, מריץ את לוגיקת הבוט, שומר/קורא ממסד הנתונים, ומדבר עם וואטסאפ ועם Google.

```
backend/app/
├── main.py            # הרכבת האפליקציה: factory + lifespan (פותח pool ל-Postgres + Redis)
├── api/               # 🚪 הדלתות — נקודות הקצה (endpoints) שהעולם פונה אליהן
├── services/          # 🧩 המוח — כל הלוגיקה העסקית (הבוט, לידים, תורים, וואטסאפ...)
├── models/            # 📋 הטפסים — סכמות Pydantic לאימות קלט/פלט
├── core/              # 🔐 הכספת והחוקים — config, הצפנה, שערי-אימות, לוגים
└── db/                # 🔌 הצינור — חיבור למסד הנתונים בכפוף ל-RLS (טננט)
backend/tests/         # 🧪 הבדיקות — strict / narrated / isolation (ראה למטה)
```

### `api/` — 🚪 הדלתות
| קובץ | מה עושה |
|---|---|
| `health.py` | `GET /healthz` — בדיקת חיים + זמינות Postgres+Redis |
| `webhook.py` | `POST /webhook/whatsapp` — הדלת שהגייטוויי דופק עליה עם הודעה נכנסת |
| `auth.py` | `/auth/*` ציבורי — התחברות Google, callback, יציאה |
| `me.py` | קבוצת `/api/*` נעולה (deny-by-default) + `GET /api/me` |
| `bot_builder.py` | `/api/bot/*` — בונה הבוט עם עוזר ה-AI (M4) |
| `dashboard.py` | `/api/*` קריאה — לוח הבקרה של בעל העסק (M7) |
| `booking.py` | `/api/*` תורים — הצד הניהולי של היומן (M11) |
| `public_booking.py` | תורים **ציבורי** — עמוד הלקוח, בלי לוגין (M11) |
| `google_oauth.py` | `/api/google/*` — חיבור יומן Google של הבעלים (M11) |
| `whatsapp.py` | `/api/whatsapp/*` — חיבור/סטטוס/QR + מספרי בדיקה (M6a) |
| `admin/` | בק-אופיס המנהל — חבילה מאחורי שער `current_admin` (M12/M13): `businesses.py` (סקירה/רשימה/פרופיל/מנוי/מחיקה), `analytics.py` (גרפים), `crm.py` (צינור מכירות); `__init__.py` מרכיב את ה-router |

### `services/` — 🧩 המוח (הלוגיקה)
| קובץ/חבילה | מה עושה |
|---|---|
| `bot_engine.py` | מנוע השיחה — פונקציה **טהורה ודטרמיניסטית** (מה הבוט עונה) |
| `bot_runtime.py` | ה-runtime — מחבר את המנוע הטהור לשכבת השמירה (Redis+Postgres) |
| `bot_settings.py` | קריאה/כתיבה של הגדרות הבוט לעסק (tenant-scoped) |
| `bot_builder_ai.py` | תיווך דק ומרוסן ל-Gemini עבור בונה הבוט |
| `conversation_state.py` | הזיכרון הקצר של השיחה ב-Redis |
| `live_chat.py` | מטמון הצ'אט-החי ב-Redis (החלטה 0006) |
| `leads/` | **מחברת הלידים** (Postgres): `crud.py` (כתיבה), `query.py` (קריאה+פענוח לבעלים), `funnel.py` (אירועי משפך), `_common.py` (קבועים/הצפנה) |
| `abandoned_sweep.py` | מטאטא לידים נטושים — לולאת רקע (single-runner) |
| `booking/` | **לוגיקת התורים** (M11): `settings.py` (הגדרות+שירותים+slug), `slots.py` (חישוב זמנים פנויים), `crud.py` (יצירה/ביטול/שינוי תור + הליד המקושר), `google.py` (תפר סנכרון ליומן) |
| `booking_reminders.py` | מטאטא תזכורות — אישורים + תזכורת יום-לפני |
| `booking_alerts.py` | תיבת התראות לבעלים (Redis) על שינויי תור מצד לקוח |
| `booking_welcome.py` | מחולל הודעת פתיחה ב-AI לעמוד התורים הציבורי |
| `google_calendar.py` | סנכרון Google Calendar + Meet — מימוש ה-hook |
| `google_oauth.py` | חיבור OAuth ליומן Google של הבעלים |
| `whatsapp.py` | הגשר טננט ↔ חשבון-גייטוויי + שליחת הודעה יוצאת |
| `whatsapp_test_numbers.py` | רשימת מספרי הבדיקה החיצוניים של הבעלים (≤5, מוצפנים) |
| `auth.py` | מנוע ההתחברות — Google OAuth + sessions אטומים ב-Redis |
| `usage.py` | מוני שימוש — ספירה לכל-עסק / לכל-יום / לכל-מטריקה (M12) |

### `models/` — 📋 הטפסים (Pydantic)
`webhook.py` (חוזה הוובהוק הקפוא) · `auth.py` · `bot_builder.py` (שער האימות של תצורת הבוט) · `dashboard.py` (M7) · `booking.py` (M11, ניהולי+ציבורי) · `google.py` · `whatsapp.py` (M6a) · `admin.py` (M12) · `health.py`.

### `core/` — 🔐 הכספת והחוקים
`config.py` (טעינת הגדרות **fail-closed** — לא עולה בלי המפתחות) · `crypto.py` (הצפנה דו-מפתחית "fail-loud") · `deps.py` (תלויות האימות — שער deny-by-default) · `clients.py` (חיבורי Postgres/Redis + probes) · `logging.py` (לוגים JSON, בלי סודות/PII).

### `db/` — 🔌 הצינור
`session.py` — חיבורי DB מבוססי-טננט (`SET LOCAL`), הצד-האחורי של חוזה ה-RLS.

### `tests/` — 🧪 הבדיקות
| תת-תיקייה | מה יש בה |
|---|---|
| `strict/` | בדיקות pytest פס/נכשל (מה ש-CI מריץ) — חוזה קשיח לכל מיילסטון |
| `narrated/` | "סיפורי עברית" — בדיקות מוסברות שמדפיסות מה ניסינו / למה זה חשוב / תוצאה |
| `isolation/` | **חומת הטננטים** — מוכיחה שעסק אחד לא רואה נתוני עסק אחר (רץ כ-`app_role` האמיתי) |

---

## `gateway/` — 💬 וואטסאפ (Node / Baileys)

שירות Node נפרד שמתחבר לוואטסאפ דרך Baileys (ספריית QR לא-רשמית) ומעביר הודעות הלוך-ושוב עם ה-backend.

```
gateway/src/
├── index.js     # 🛗 הרמה — bootstrap דק: config+logger, express, חיווט ראוטים, הדלקת סוקט
├── socket.js    # 🔌 חיבור Baileys + הודעות נכנסות — חיבור/חיבור-מחדש, זיהוי צ'אט-עצמי, מניעת לולאה
├── webhook.js   # 📤 שליחה ל-backend + תשובות — מעביר הודעה נכנסת ושולח את התשובות חזרה לצ'אט
├── routes.js    # 🛣️ מסלולי HTTP — /healthz /info /qr /qr.json /send-bot /inbox /send
├── contract.js  # 📜 חוזה הוובהוק הקפוא gateway→backend (ממופה במקום אחד בלבד)
├── config.js    # 🔐 טעינת הגדרות fail-closed (חייב GATEWAY_API_TOKEN)
└── logger.js    # 📝 לוגר pino
```

> חוקים: **כותב יחיד לכל session**; ה-creds נשמרים מוצפנים (היעד: ב-DB, לא קבצים גלויים); ה-QR נזרם ולא נשמר;
> אימות header-only בלבד; קצב שליחה שמרני (סיכון חסימה ב-Baileys). הגייטוויי מכיר `accountId`, אף פעם לא `business_id`.
> ⚠️ `gateway/auth/` (קבצי ה-session של Baileys) ב-gitignore — לא נכנס ל-git.

---

## `frontend/` — 🎨 הממשק (React + Tailwind)

אפליקציית בעל-העסק (לוח בקרה, בונה בוט, נסה-אותי, חיבור QR), העמודים הציבוריים (נחיתה, תורים, תקנון/פרטיות),
והבק-אופיס של המנהל. **RTL עברית + נגישות (WCAG) מהיום הראשון.**

```
frontend/src/
├── main.tsx / App.tsx   # נקודת כניסה + הראוטר (מסלולים ציבוריים/מוגנים + AuthProvider)
├── pages/               # 📺 המסכים — עמוד שלם לכל מסלול
├── components/          # 🧱 הרכיבים — חלקי UI לפי תחום (ראה למטה)
├── lib/                 # 🛠️ קליינטים + עזר — עטיפות fetch לכל קבוצת endpoints + utils
├── i18n/                # 🌐 תרגומים — תשתית i18next (namespace ראשון: נגישות)
├── auth/                # context + טיפוסים של מצב ההתחברות
├── admin/ botbuilder/ dashboard/  # טיפוסים + labels התואמים לחוזי ה-backend
└── index.css            # סגנונות גלובליים
```

### `pages/` — 📺 המסכים
ציבוריים: `LandingPage` (נחיתה), `LoginPage`, `PublicBookingPage` (`/book/:slug`), `PublicManagePage` (ביטול/שינוי תור), `Terms/Privacy/AccessibilityPage` (דרך `LegalPage`).
בעלים: `Home` (שורש → spinner→דשבורד/נחיתה), `DashboardHome` (KPI+משפך), `LeadsPage`, `ConversationsPage` (צ'אט חי + handoff), `BotBuilderPage`, `TryMePage` (נסה-אותי), `AppointmentsPage`, `WhatsAppPage` (חיבור QR).
מנהל (`pages/admin/`): `AdminHome`, `BusinessesList`, `BusinessDetail`, `AdminCrm` (צינור מכירות), `AdminBilling`.

### `components/` — 🧱 הרכיבים (לפי תחום)
| תיקייה | מה יש בה |
|---|---|
| `ui/` | ערכת ה-UI המשותפת (Button, Card, Modal, Field, Select, Tabs, Badge, Alert...) |
| `landing/` | חלקי דף הנחיתה (Hero, Features, Pricing, FAQ, Industries, Counter...) |
| `whatsapp/` | חלקי חיבור וואטסאפ (ConnectView, ConnectedView, TestModeCard, TestNumbersCard) |
| `admin/` | כרטיסי וגרפי הבק-אופיס (DonutChart, LineChart, StackedBarChart, CrmPanel, SubscriptionPanel...) |
| `booking/` | חלקי זרימת התורים (BookingFlow, SlotGrid, ServicesEditor, WorkingHoursEditor, BookingsCalendar...) |
| `dashboard/` | כרטיסי הדשבורד (StatCard, ActivityFeed, ChatPanel, LeadCard, PublishToggle...) |
| `botbuilder/` | עורך הזרימות (AIChatPanel, FlowTabs, FlowTypeSelector, StepsEditor) |
| (שורש) | `AppGate`/`AuthGate`/`AdminGate` (שומרי מסלול), `DashboardLayout`, `OwnerHeader`, `SiteFooter`, `AccessibilityWidget`, `StackHealth` |

### `lib/` — 🛠️ קליינטים + עזר
קליינטים מוקלדים לכל קבוצת endpoints: `apiClient` (עטיפת fetch בסיסית), `dashboardClient`, `botClient`, `bookingClient`, `publicBookingClient`, `whatsappClient`, `adminClient`.
עזר: `friendlyError` (שגיאה→הודעה עברית רגועה), `formatDate`/`bookingDates`, `imageResize` (כיווץ תמונה בצד-לקוח), `waLink` (קישור wa.me), `health`, `useA11yPreferences` (hook נגישות).

---

## `infra/` — 🧱 ההרצה (Docker Compose)

כל מה שהופך את הפרויקט **לניתן-להרצה, חוזר-על-עצמו ובטוח לפיתוח**.

```
infra/
├── docker-compose.yml    # הסטאק המקומי: postgres + redis + migrate + backend + gateway + frontend (health-gated)
├── .env.example          # שמות כל הסודות (בלי ערכים) — חוזה
├── .env.local.example    # תבנית למילוי + גנרטורים → להעתיק ל-.env.local (git-ignored)
└── .env.local            # הקובץ האמיתי (git-ignored, נוצר אוטומטית ע"י run.bat)
```

* פורטים: backend `:8000` · gateway `:3000` · frontend `:5173`. Postgres/Redis **לא** חשופים החוצה (פנימי לרשת Docker).
* הרצה: `run.bat` (או `make dev`) מרים הכל; `stop.bat` עוצר.

---

## `supabase/` — 🗄️ מסד הנתונים (Postgres)

מיגרציות SQL גרסאתיות. **ה-RLS (חומת הטננטים) חיה באותן מיגרציות** — לעולם לא מחשבה שנייה.

```
supabase/
├── migrations/   # NNNN_*.sql בסדר: 0001…0021 — טבלאות + RLS (USING+WITH CHECK) + grants + פונקציות
└── seed.sql      # נתוני דמו מודעי-טננט (2 עסקים), נזרעים דרך ה-roles האמיתיים
```

* **0001–0005:** roles+extensions, גשר RLS, 9 טבלאות, מדיניות+grants, bootstrap לאימות.
* **0006–0014:** משפך נטוש, הערת תוצאה, תורים (booking) + RLS + slug, תוספות שירות+תמונה, פתרון חשבון וואטסאפ + מספרי בדיקה.
* **0015–0021:** בק-אופיס המנהל — plans/subscriptions, usage+audit, פונקציות אדמין (SECURITY DEFINER), טבלאות+אנליטיקה+CRM של M13, מחיקת עסק.

---

## `docs/` — 📚 התיעוד

```
docs/
├── STATUS.md      # 📍 "איפה אנחנו / איך ממשיכים" — הקובץ הראשון בכל סשן
├── decisions/     # החלטות ארכיטקטורה/מוצר (0001…0019) — למה בחרנו מה שבחרנו
├── spec/          # המפרט המלא: roadmap, mvp-checklist, architecture, data-model, חוזים
├── system-map/    # מפת המערכת המקורית (last_bo) שעליה התבסס השכתוב
└── bugs.md / security-issues.md / 00_overview.md / prototype/
```

---

## `.claude/` — 🤖 סוכני ה-AI
`agents/` (סוכני סריקה/בנייה ייעודיים) · `workflows/` (מתכונים שמריצים סוכנים בסדר) · `settings.json` (הגדרות + נעילת-כתיבה על `last_bo`).
