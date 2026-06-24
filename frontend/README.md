# frontend/ — 🎨 הממשק (React + Tailwind)

אפליקציית בעל-העסק (לוח בקרה, בונה בוט, נסה-אותי, חיבור QR), העמודים הציבוריים (נחיתה, תורים,
תקנון/פרטיות), והבק-אופיס של המנהל. **RTL עברית + נגישות (WCAG / נגישות) מהיום הראשון.**
המפה המלאה: [`../STRUCTURE.md`](../STRUCTURE.md).

## התיקיות (השלטים)
```
frontend/src/
├── main.tsx / App.tsx   # נקודת כניסה + הראוטר (מסלולים ציבוריים/מוגנים + AuthProvider) + אתחול i18n
├── pages/               # 📺 המסכים — עמוד שלם לכל מסלול (כולל pages/admin/ לבק-אופיס)
├── components/          # 🧱 הרכיבים — חלקי UI לפי תחום
├── lib/                 # 🛠️ קליינטים + עזר — עטיפות fetch מוקלדות לכל קבוצת endpoints + utils
├── i18n/                # 🌐 תרגומים — תשתית i18next (namespace ראשון: נגישות)
├── auth/                # context + טיפוסים של מצב ההתחברות
├── admin/ botbuilder/ dashboard/   # טיפוסים + labels התואמים לחוזי ה-backend
└── index.css            # סגנונות גלובליים
```

### `components/` לפי תחום
`ui/` (ערכת ה-UI המשותפת: Button/Card/Modal/Field/Select/Tabs/Badge/Alert...) · `landing/` (חלקי הנחיתה) · `whatsapp/` (Connect/Connected/TestMode/TestNumbers) · `admin/` (כרטיסי+גרפי בק-אופיס: Donut/Line/StackedBar/Crm/Subscription...) · `booking/` (זרימת התורים: BookingFlow/SlotGrid/ServicesEditor/WorkingHours...) · `dashboard/` (StatCard/ActivityFeed/ChatPanel/LeadCard...) · `botbuilder/` (AIChatPanel/FlowTabs/StepsEditor).
בשורש: `AuthGate`/`AdminGate` (שומרי מסלול), `DashboardLayout`, `OwnerHeader`, `SiteFooter`, `AccessibilityWidget`, `StackHealth`.

> `LandingPage.tsx` ו-`WhatsAppPage.tsx` היו קבצים ארוכים — פוצלו לרכיבים תחת `components/landing/*`
> ו-`components/whatsapp/*` בניקיון M15, בלי שינוי התנהגות.

## איך עובדים
חלק מהסטאק: `run.bat` מהשורש → לפתוח `http://127.0.0.1:5173`.
ה-dev server רץ בתוך הקונטיינר על `0.0.0.0:5173` ומפנה (proxy) את `/healthz`/`/api`/`/auth`/`/webhook` ל-`http://backend:8000`.

עצמאי (בלי Docker):
```bash
cd frontend
npm install          # נעול דרך package-lock.json
npm run dev          # http://localhost:5173
# להפנות את ה-proxy ל-backend על המחשב במקום שם הקומפוז:
BACKEND_ORIGIN=http://localhost:8000 npm run dev
```

בדיקת טיפוסים: `npm run build` (כולל `tsc`).

## חוקים
- **אין סודות בדפדפן** — מדבר רק עם ה-backend (same-origin דרך ה-proxy); לא רואה את טוקן הגייטוויי/creds.
- **RTL + נגישות** מהקומיט הראשון, לא retrofit.
- deps נעולים (`package-lock.json`).
