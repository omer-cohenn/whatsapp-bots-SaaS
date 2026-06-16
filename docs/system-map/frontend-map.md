# Frontend Map — WhatsApp Bot Manager (last_bo)

> Blueprint for rebuilding the existing vanilla HTML/JS frontend as **React + Tailwind** without breaking the FastAPI backend.
> Source (READ-ONLY): `C:\Users\עמר כהן\Desktop\last_bo`
> Backend routes verified against `C:\Users\עמר כהן\Desktop\last_bo\main.py`.
> React/Vite structural reference: `C:\Users\עמר כהן\Desktop\qr_wa_scanner\frontend`.

## Scope & how pages are served

The FastAPI app serves static HTML files directly (no bundler today). Mapping from `main.py`:

| URL | Handler (main.py line) | File served | Auth |
|-----|------------------------|-------------|------|
| `GET /` | `setup_ui` (148-150) | `frontend/index.html` | none to serve; JS self-guards via `/api/me` |
| `GET /botbuilder` | `botbuilder_ui` (668-673) | `frontend/botbuilder.html` | **server-side**: redirects to `/` (303) if no session |
| `GET /book/{slug}` | `book_client_ui` (620-622) | `frontend/book_client.html` | **public** (no auth) |
| `GET /test-chat-status` | (676) | `frontend/test_chat_status.html` | needs verification (handler present; auth not confirmed) |

`bookslot.html` and `botybuilderFront.jsx` live at the project root and are **not wired into any route** (see final section).

The dashboard (`index.html`) embeds the bot builder via an **iframe** (`<iframe src="/botbuilder">`, index.html:444). In React this iframe should be replaced by a normal route/component.

---

# Page 1 — Dashboard / App Shell (`frontend/index.html`)

**Purpose:** The authenticated owner console. Single-page app shell with Google login gate, header (status pill + user chip + logout), and a 3-tab workspace: **Bot Builder** (iframe), **Leads management**, **Appointments management**.

**Public or behind login:** Behind login. On load, `init()` (index.html:590) calls `GET /api/me`; on `401` it shows `#login-screen` (Google OAuth button linking to `/auth/google`). Logout is a `POST /auth/logout` form (index.html:420).

**Main UI sections / components:**
- **Login screen** (`#login-screen`, 393-404) — Google sign-in card (RTL Hebrew).
- **App header** (410-424) — logo, dynamic title, status pill (`#status-pill`), user chip (avatar/name), logout form.
- **Tab bar** (427-437) — Bot Builder / Leads / Schedule, `switchTab()` (632).
- **Builder panel** (443-445) — iframe to `/botbuilder`.
- **Leads panel** (448-491) — sub-tabs Dashboard / Active / All / Old (`switchLeadsSub`, 666); period filter (all/month/day, `setLeadsPeriod`, 705); flow-type `<select>`; dashboard stat cards (`renderDash`, 681); leads table (`renderLeadsTable`, 712); "test lead" button (`generateTestLead`, 764).
- **Schedule panel** (494-574) — booking-link banner with copy (`loadBookingLink`/`copyLink`, 789/796); availability settings accordion (duration buttons + per-day toggles & hours, `renderSettings`/`saveSettings`, 810/848); calendar (week/month, `loadSchedule`/`renderWeek`/`renderMonth`, 888/914/941); appointment modal with confirm/cancel (`openModal`/`updateApt`, 964/985).
- **Toast** (`#toast`, 1006).

**Data it loads on init** (index.html:606-611): status pill, booking link, booking settings, schedule (current week), leads dashboard, leads list.

### API calls — Dashboard

| Method | Path | Sends | Returns | Purpose | Code |
|--------|------|-------|---------|---------|------|
| GET | `/api/me` | — | `{authenticated, ...user}` or 401 | Auth gate; populate user chip | 592 |
| GET | `/api/status` | — | `{business_name, flows, ...}` (ok/!ok used) | Status pill (bot active / not connected) | 620 |
| GET | `/api/leads?period=` | `period` query | `{leads:[...]}` | Leads table data | 651 |
| GET | `/api/config` | — | `{flows:[{id,...}]}` | **Active flow IDs** for active/old classification | 652 |
| GET | `/api/dashboard?period=` | `period` query | `{total_leads, abandoned, avg_open_chats, leads_by_flow}` | Dashboard stat cards | 653 |
| POST | `/api/leads/test` | empty body | `{...}` or `{detail}` on error | Generate a test lead | 769 |
| GET | `/api/booking-link` | — | `{url, slug}` | Personal booking URL banner | 791 |
| GET | `/api/booking-settings` | — | `{working_days, working_hours, slot_duration, service_name?}` | Availability form | 805 |
| POST | `/api/booking-settings` | `{working_days, working_hours, slot_duration}` JSON | `{status:"ok"}` | Save availability | 859 |
| GET | `/api/bookings?from=&to=` | `from`,`to` dates | `[{id,date,time,client_name,client_phone,client_email,status,notes}]` | Calendar appointments | 906 |
| PATCH | `/api/bookings/{id}` | `{status}` JSON | `{status:"ok"}` | Confirm / cancel an appointment | 987 |

> **Contract mismatch (needs verification / fix during rebuild):** index.html calls `GET /api/bookings?from=...&to=...` (906), but the backend handler declares query params `date_from` / `date_to` (main.py:585). The current frontend likely relies on FastAPI ignoring unknown params and returning *all* bookings (empty `date_from`/`date_to`). The React app should send `date_from` / `date_to` to actually filter, OR keep `from`/`to` to preserve current (unfiltered) behaviour. **Do not change blindly** — confirm intended behaviour.

> **Note:** `GET /api/config` is called by the frontend (652) but does **not** appear in the `main.py` route grep. It may be an alias/older route, served elsewhere, or returning 404 and being swallowed by the `try/catch` in `loadLeads` (which would leave `_activeFlowIds` empty). **Needs verification.**

### Proposed React breakdown
- `App` / `AuthGate` (wraps everything; calls `/api/me`)
- `LoginScreen`
- `AppHeader` (`StatusPill`, `UserChip`, `LogoutButton`)
- `TabBar`
- `BotBuilderTab` (renders the Bot Builder page component directly instead of an iframe)
- `LeadsTab` → `LeadsSubTabs`, `LeadsDashboard` (`StatCard`, `FlowBreakdownList`), `LeadsToolbar` (`PeriodFilter`, `FlowFilterSelect`, `TestLeadButton`), `LeadsTable`
- `ScheduleTab` → `BookingLinkBanner`, `AvailabilitySettings` (`DurationPicker`, `DayRow`), `ScheduleCalendar` (`WeekGrid`, `MonthGrid`, `AppointmentChip`), `AppointmentModal`
- `Toast` (global context/provider)
- Hooks: `useMe`, `useLeads`, `useDashboard`, `useBookingSettings`, `useBookings`

---

# Page 2 — Bot Builder (`frontend/botbuilder.html`)

**Purpose:** Visual editor for the bot's conversational config — flows (info-collection steps, knowledge/RAG menus, human-handoff, booking-link), main menu, business settings, tone, escalation, and a knowledge base (RAG) manager. Includes an **AI assistant** ("מנהל הבוט") that edits the config via chat, and a **"Try" simulator** that previews the bot.

This file is **already React 18 + Babel-standalone (CDN)**, transpiled in-browser (`<script type="text/babel">`). The comment at botbuilder.html:28-29 says the JSX is "auto-updated by build" from `botybuilderFront.jsx`. So this page is the closest to the target architecture and is the highest-value conversion (move it from CDN Babel to Vite, swap inline styles for Tailwind).

**Public or behind login:** Behind login. Served only after server-side session check (main.py:668-673), plus an in-page guard (botbuilder.html:19-26) that redirects to `/` on `401` from `/api/me`.

**Main UI sections / components (already componentized in JSX):**
- `App` (740) — root; loads config, autosaves on change.
- Top bar with save status, "🤖 מנהל בוט" (AI), "▶️ Try" buttons (866-883).
- Bottom nav tabs: **מסלולים** (flows), **בסיס ידע** (knowledge), **הגדרות** (settings) (1073-1078).
- **Flows tab** (888-1001): flow chips with delete; flow-type toggle (steps / knowledge / human_handoff / booking_link); per-type editors:
  - `knowledge` editor (topic, opening message, exit keywords) (926-951)
  - `human_handoff` info panel (954-965)
  - `booking_link` panel (serviceName) (968-981)
  - standard step editor (add/edit/delete steps) (984-1000)
- **Knowledge tab** = `KnowledgeTab` (581) — RAG status counts, "when to use RAG" use-cases, file upload (drag/drop), URL scrape, indexed-sources list with delete.
- **Settings tab** (1005-1067): business name, system prompt, tone chips, `MainMenuEditor` (73), menu-return keywords, human-escalation settings (message, keywords, auto-close minutes).
- `Editable` (48) — inline edit-on-click text/textarea.
- `MainMenuEditor` (73) — greeting + ordered menu options + WhatsApp-style preview.
- `FloatingWindow` (136) — draggable window shell for AI & Try panels.
- `AIChatPanel` (163) — chat that builds a system prompt from current `data`, calls AI, extracts ```json blocks and applies them via `applyChanges` (793).
- `TryMeOverlay` (323) — simulates the menu + each flow type; calls validate/chat/rag/booking-link.

**Data it loads:** `GET /api/botbuilder/config` on mount (749) → `{businessName, systemPrompt, tone, mainMenu, flows[], humanEscalation*, autoCloseMinutes, menuKeywords, rag_use_cases}`. Autosaves the whole object on every edit via `POST /api/botbuilder/config` (763).

### API calls — Bot Builder

| Method | Path | Sends | Returns | Purpose | Code |
|--------|------|-------|---------|---------|------|
| GET | `/api/me` | — | user or 401 | In-page auth guard | 22 |
| GET | `/api/botbuilder/config` | — | full bot config object | Load editor state | 749 |
| POST | `/api/botbuilder/config` | full config JSON | `{status:"ok"}` | Autosave config | 763 |
| POST | `/api/ai/chat` | `{system, messages[], max_tokens}` | `{content:[{text}]}` | AI bot-manager chat + summary at flow end | 247, 479 |
| POST | `/api/ai/validate` | `{system, messages[], model?, max_tokens?}` | `{content:[{text}]}` (JSON inside) | Validate Try-mode step answers | 373 |
| POST | `/api/rag/chat` | `{system, messages[]}` | `{content:[{text}]}` | Knowledge-flow RAG answers in Try mode | 449 |
| GET | `/api/booking-link` | — | `{url, slug}` | Try-mode booking-link reply | 349 |
| GET | `/api/rag/sources` | — | `[{id,type,name,chunk_count}]` | Knowledge sources list | 592 |
| GET | `/api/rag/status` | — | `{source_count, total_chunks}` | RAG status counters | 593 |
| GET | `/api/botbuilder/config` | — | `{rag_use_cases, ...}` | Read RAG use-cases (KnowledgeTab) | 594 |
| POST | `/api/rag/use-cases` | `{rag_use_cases}` JSON | ok | Save RAG use-cases | 601 |
| POST | `/api/rag/upload` | `multipart/form-data` (`file`) | `{name, chunks}` or `{detail}` | Upload a knowledge document | 611 |
| POST | `/api/rag/add-url` | `{url}` JSON | `{chunks}` or `{detail}` | Scrape a URL into knowledge base | 624 |
| DELETE | `/api/rag/source/{id}` | — | ok | Delete a knowledge source | 635 |

> **Backend reality check (main.py):** `/api/ai/chat`, `/api/ai/validate`, `/api/rag/chat` all proxy **Gemini** (`_gemini_call`, model `gemini-3.1-flash-lite`) and return Anthropic-shaped `{"content":[{"type":"text","text":...}]}` (main.py:917-963). The frontend sends Anthropic-style params (`model:"claude-haiku-..."`, `system`, `messages`); the backend **ignores `model`** and uses Gemini. The response shape is honored, so the React port can keep the same request/response contract verbatim.

> `botybuilderFront.jsx` (root, 789 lines) is an **older/source copy**: it contains only `/api/ai/chat`, `/api/ai/validate`, `/api/botbuilder/config` (lines 227/381/430/566/582) and is missing the RAG + booking-link logic present in the served `botbuilder.html`. Treat `botbuilder.html` as the source of truth.

### Proposed React breakdown
- `BotBuilderPage` (state: `data`, `tab`, `flowId`, `saveStatus`, `aiOpen`, `tryOpen`)
- `BuilderTopBar` (`SaveStatus`, `AiButton`, `TryButton`)
- `BuilderBottomNav`
- `FlowsTab` → `FlowChips`, `FlowTypeToggle`, `KnowledgeFlowEditor`, `HumanHandoffPanel`, `BookingLinkPanel`, `StepEditor` (`StepCard`)
- `KnowledgeTab` → `RagStatusCards`, `UseCasesEditor`, `FileDropzone`, `UrlScraper`, `SourceList`
- `SettingsTab` → `BusinessNameField`, `SystemPromptField`, `ToneChips`, `MainMenuEditor`, `MenuKeywordsField`, `EscalationSettings`
- Shared: `Editable`, `FloatingWindow`, `AiChatPanel`, `TryMeOverlay`
- Hooks: `useBotConfig` (load + debounced autosave), `useAiChat`, `useRagSources`

---

# Page 3 — Public Booking (`frontend/book_client.html`)

**Purpose:** Public, slug-scoped page where a client books an appointment: pick a date on a calendar, pick a free time slot, fill a form (name/phone required; email/notes optional), submit, see a success card.

**Public or behind login:** **Public, no auth.** Served at `/book/{slug}` (main.py:620). The slug is parsed from `location.pathname` (book_client.html:106).

**Main UI sections / components:**
- Top bar with business/service name (`#biz-name`, `#service-label`).
- Booking card: month calendar (`renderCalendar`, 135) marking working days (`isWorkDay`, 130) as clickable.
- Slots grid (`loadSlots`/`pickSlot`, 167/193).
- Booking form (`showForm`, 200) with inline validation.
- Success card (`resetBooking`, 254).
- Error/loading states.

**Data it loads:** On `init()` (114) `GET /api/book/{slug}/settings` for service name + working days; on day click `GET /api/book/{slug}/slots?date=` for free times; on submit `POST /api/book/{slug}`.

### API calls — Public Booking

| Method | Path | Sends | Returns | Purpose | Code |
|--------|------|-------|---------|---------|------|
| GET | `/api/book/{slug}/settings` | slug in path | `{service_name, working_days, working_hours, slot_duration}` | Service label + which days are bookable | 116 |
| GET | `/api/book/{slug}/slots?date=` | slug, `date` | `{slots:[ "HH:MM", ... ]}` | Free time slots for a day | 171 |
| POST | `/api/book/{slug}` | `{date, time, name, phone, email, notes}` JSON | `{id}` on success; **409** if slot taken | Create the booking (double-book guard) | 226 |

> `409` handling is load-bearing (book_client.html:231): on conflict it alerts and reloads slots. The React port must preserve the 409 branch (backend returns it at main.py:653).

### Proposed React breakdown
- `PublicBookingPage` (reads `slug` from route; this can be its own Vite route or even a separate entry to keep the public bundle small)
- `BookingHeader`
- `MonthCalendar` (`CalendarDay`)
- `SlotGrid` (`SlotButton`)
- `BookingForm` (validated)
- `BookingSuccess`, `BookingError`, `LoadingState`
- Hooks: `useBookingConfig(slug)`, `useSlots(slug, date)`, `useCreateBooking(slug)`

---

# Page 4 — Chat Status Tester (`frontend/test_chat_status.html`)

**Purpose:** Internal QA/dev tool to exercise the bot/human/closed conversation state machine. Simulates inbound WhatsApp webhooks, inspects conversation status, lists conversations waiting for a human, and overrides status directly. Runs scripted scenarios (escalate, closed→reopen, human-silent).

**Public or behind login:** Served at `GET /test-chat-status` (main.py:676). **Auth state needs verification** — the handler is present but the page has no `/api/me` guard. The admin endpoints it hits (`/api/conversations*`) may or may not require a session; **needs verification** before deciding whether this becomes an authenticated admin tool or is dropped from the React app.

**Main UI sections / components:**
- Simulate-message card (`sendSim`, 129) → posts a fake webhook payload.
- Check-status card (`checkStatus`, 150).
- Pending-human list (`loadHuman`/`adminSet`, 185/208).
- Direct status override (`overrideStatus`, 223).
- Quick scenarios (`runScenario`, 240).
- Dark log panes.

### API calls — Chat Status Tester

| Method | Path | Sends | Returns | Purpose | Code |
|--------|------|-------|---------|---------|------|
| POST | `/webhook` | WhatsApp-shaped `{entry:[{changes:[{value:{messages:[{from,text:{body}}]}}]}]}` | `{status: "ok"\|"ignored"\|...}` | Simulate inbound customer message | 142, 245 |
| GET | `/api/conversations?status=` | `status` = `human`/`closed`/`bot` | `[{phone_masked, phone_enc, chat_status, last_msg_at}]` | List conversations by status | 154-158, 188, 253-255 |
| POST | `/api/conversations/{phone_enc}/status` | `{status}` JSON | `{status:"ok"}` | Override a conversation's chat status | 210, 228, 249 |

> Webhook payload shape is the production WhatsApp webhook contract (`/webhook`, main.py:325). The React port (if kept) must keep this exact nested shape. `phone_enc` is URL-encoded in the path.

### Proposed React breakdown
- `ChatStatusTesterPage` (admin-gated)
- `SimulateMessageCard`, `CheckStatusCard`, `PendingHumanList`, `StatusOverrideCard`, `ScenarioRunner`, `LogPane`
- Hooks: `useConversations(status)`, `useSetConversationStatus`, `useSimulateWebhook`
- *(Recommendation: this is a dev tool. Consider gating behind an admin flag or excluding from the production React build.)*

---

# Global API endpoint inventory (the contract React must honor)

Distinct endpoints actually called by the frontend, cross-checked against `main.py`. `{}` = path param.

| Method | Path | Used by | Purpose |
|--------|------|---------|---------|
| GET | `/api/me` | index, botbuilder | Auth check + current user |
| GET | `/auth/google` | index (link) | Start Google OAuth |
| POST | `/auth/logout` | index (form) | Sign out |
| GET | `/api/status` | index | Bot active/connected status |
| GET | `/api/dashboard?period=` | index | Leads dashboard stats |
| GET | `/api/leads?period=` | index | Leads list |
| POST | `/api/leads/test` | index | Create test lead |
| GET | `/api/config` | index | Active flow IDs (**not found in main.py grep — needs verification**) |
| GET | `/api/booking-link` | index, botbuilder | Personal booking URL |
| GET | `/api/booking-settings` | index | Read availability settings |
| POST | `/api/booking-settings` | index | Save availability settings |
| GET | `/api/bookings?from=&to=` | index | Owner appointment calendar (**param-name mismatch: backend expects `date_from`/`date_to`**) |
| PATCH | `/api/bookings/{id}` | index | Confirm/cancel appointment |
| GET | `/api/botbuilder/config` | botbuilder | Load bot config (+ rag_use_cases) |
| POST | `/api/botbuilder/config` | botbuilder | Save bot config |
| POST | `/api/ai/chat` | botbuilder | AI bot-manager chat (Gemini proxy) |
| POST | `/api/ai/validate` | botbuilder | Validate Try-mode answers (Gemini proxy) |
| POST | `/api/rag/chat` | botbuilder | Knowledge-flow RAG chat |
| GET | `/api/rag/sources` | botbuilder | List knowledge sources |
| GET | `/api/rag/status` | botbuilder | RAG counters |
| POST | `/api/rag/use-cases` | botbuilder | Save RAG use-cases |
| POST | `/api/rag/upload` | botbuilder | Upload knowledge file (multipart) |
| POST | `/api/rag/add-url` | botbuilder | Scrape URL into knowledge base |
| DELETE | `/api/rag/source/{id}` | botbuilder | Delete knowledge source |
| GET | `/api/book/{slug}/settings` | book_client | Public booking config |
| GET | `/api/book/{slug}/slots?date=` | book_client | Public free slots |
| POST | `/api/book/{slug}` | book_client | Public create booking (409 on conflict) |
| POST | `/webhook` | test_chat_status | Simulate inbound WhatsApp message |
| GET | `/api/conversations?status=` | test_chat_status | List conversations by status |
| POST | `/api/conversations/{phone_enc}/status` | test_chat_status | Override conversation status |

**Total distinct API endpoints called by the frontend: 30** (each Method+Path counted once; the two GET/POST pairs on `/api/booking-settings` and `/api/botbuilder/config` are counted separately by method).

Backend routes in `main.py` NOT currently called by these four pages (available, for awareness): `GET/POST /auth/google/callback`, `POST /admin/migrate-leads`, `POST /admin/rebuild-rag`, `GET /health`, `POST /api/rag/rebuild`, `GET /webhook` (WhatsApp verify challenge), plus the file-serving routes `GET /`, `/botbuilder`, `/book/{slug}`, `/test-chat-status`.

---

# Shared JS / CSS notes

- **No shared files.** Every page is fully self-contained: each HTML inlines its own `<style>` and `<script>`. There are no external `.css` or `.js` assets in `frontend/` (only the 4 HTML files). React + Tailwind should extract the repeated patterns below into shared modules.
- **Design tokens are duplicated** across pages via CSS variables (`:root{--bg,--surface,--border,--green:#25D366,--green-dark:#128C7E,--blue,--radius,--shadow,--font:'Heebo'...}`). Three palettes exist:
  - Light "Heebo" owner-app palette (index.html, book_client.html, bookslot.html).
  - WhatsApp greens for the builder (botbuilder.html, inline).
  - Dark "GitHub" palette in the qr_wa_scanner reference (`--bg:#0d1117`).
  → Consolidate into a single Tailwind theme (`tailwind.config` colors + CSS variables for the few dynamic ones).
- **RTL everywhere:** `<html lang="he" dir="rtl">`. Tailwind must be configured RTL-aware (logical properties / `dir="rtl"` on root). All copy is Hebrew.
- **Fonts:** `Heebo` (Google Fonts) for owner/booking pages; `sans-serif` for builder; `Inter`/`JetBrains Mono` in the reference. Standardize on Heebo for the app.
- **Icons:** book_client.html / bookslot.html use **Tabler Icons webfont** (`@tabler/icons-webfont@3.19.0` via CDN). Owner/builder pages use raw emoji and one inline Google SVG. For React, use `@tabler/icons-react` or inline SVG components.
- **Repeated logic to centralize:** Hebrew day/month name arrays (`HEB_DAYS`, `HEB_MONTHS`, `DAYS_SHORT`); `fmtDate`/`fmt` date formatting; week/month calendar grid builders (in index.html, book_client.html, bookslot.html — three near-duplicate implementations); slot computation (`toMin`/`toStr`/`getSlots` mirrors backend `_compute_slots`); toast; accordion toggle; appointment status → label/color maps. → shared `lib/dates.ts`, `lib/slots.ts`, `components/Calendar`, `components/Toast`.
- **Auth pattern:** both authed pages call `GET /api/me` and branch on `401`. Centralize as one `AuthProvider` + route guard.
- **AI response shape:** all three AI endpoints return `{content:[{type:"text",text}]}`; the JSON-extraction regex (```json fenced block) in `AIChatPanel.send` is shared logic worth a helper.

---

# Stray / non-wired files

### `botybuilderFront.jsx` (project root, 789 lines)
- An **older source copy** of the bot builder React app. The served `frontend/botbuilder.html` inlines a *newer, larger* version of the same JSX (its header comment says it is "auto-updated by build" from this file).
- API calls present: `/api/ai/chat` (227, 430), `/api/ai/validate` (381), `GET/POST /api/botbuilder/config` (566, 582). It is **missing** the RAG `KnowledgeTab`, booking-link Try flow, and all `/api/rag/*` calls that exist in the served page.
- **Action for the rebuild:** do **not** port this file. Use `frontend/botbuilder.html` as the source of truth and ignore the stray `.jsx`. (Reminder: it is in the READ-ONLY tree — do not modify it there; just don't carry it forward.)

### `bookslot.html` (project root, 1014 lines)
- A **standalone static design mockup** of a full booking SaaS (settings / schedule week-month-year views / client booking) with **hardcoded fake data** (`genApts()`, 30 fake clients, `TODAY_STR='2026-06-09'`, in-memory `appointments`/`bookedMap`).
- **Zero backend calls** — confirmed: no `fetch`, `/api/`, `/auth`, `/webhook`, or `/book/` references anywhere in the file. State is purely client-side; "save" just animates a button.
- Not served by any FastAPI route.
- **Value:** it is the **richest UI reference** — it has the polished week/month/**year** schedule views, load-heatmap coloring (`loadColor`), an appointment detail+edit modal, and stat cards that the live `index.html` schedule tab does NOT have. Mine it for the React **Schedule** components' look-and-feel, but wire those components to the real `/api/bookings` + `/api/booking-settings` endpoints.

---

# React + Tailwind rebuild recommendations (summary)

- **Stack:** Vite + React 18 (+ optional TypeScript) + Tailwind, mirroring `qr_wa_scanner/frontend` (same `@vitejs/plugin-react`, `vite.config.js`). Add a dev `server.proxy` to the FastAPI origin so `/api/*`, `/auth/*`, `/webhook`, `/book/*` keep working in dev. (The reference hardcodes `http://localhost:3000` for a *different* Node/Baileys gateway — a Vite proxy is cleaner and keeps cookies/session same-origin for FastAPI.)
- **Keep the API contract byte-for-byte.** Same methods, paths, query params, request bodies, and the `{content:[{text}]}` AI shape. The only two contract items to consciously decide on: the `/api/bookings` `from/to` vs `date_from/date_to` param names, and whether `/api/config` is real (verify).
- **Replace the `/botbuilder` iframe** with a real route/component once both pages are React.
- **Routing:** `/` (authed dashboard), `/book/:slug` (public — keep as a lightweight/separate entry so the public page doesn't pull in the authed bundle), and optionally an admin `/test-chat-status`.
- **Build output:** point FastAPI's file-serving routes (`/`, `/book/{slug}`, etc.) at the Vite `dist/` output, or add a catch-all that serves the SPA `index.html` while leaving `/api/*` untouched — so the backend stays unbroken.

> **qr_wa_scanner is a different service.** Its React app (`src/App.jsx`) talks to a Node WhatsApp gateway at `localhost:3000` (`/status`, `/send`, `/webhook`, `/logout`) — **none** of those are the FastAPI endpoints above. Use it only as a Vite/React scaffolding reference, not for API contracts.
