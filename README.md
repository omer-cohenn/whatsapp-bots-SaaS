# Bizz_up

A multi-tenant **WhatsApp Bot SaaS** platform. Business owners connect WhatsApp and build
conversational chat menus that collect leads, book appointments, answer questions from their own
content (RAG), and hand off to a human when needed.

> This is the **new, clean rebuild** of the original project (`../last_bo`).
> The original is **read-only** and is never modified.

## Project status

🟢 **Phase: BUILD (the MVP).** The full MVP (M0–M14) is built and runs locally.
**Read [`docs/STATUS.md`](docs/STATUS.md) first** — it's the single "where are we / how do I continue" file.

## Getting started

1. **Where we are** → [`docs/STATUS.md`](docs/STATUS.md).
2. **Run it** → double-click `run.bat` (Docker Desktop must be running); stop with `stop.bat`.
   Frontend `http://127.0.0.1:5173` · WhatsApp QR `http://127.0.0.1:3000/qr` · backend `:8000`.
3. **Real API keys** → [`ENV_SETUP.md`](ENV_SETUP.md) (what to fill to run with real Gemini + Google).
4. **Find your way around** → [`STRUCTURE.md`](STRUCTURE.md) (the master repo map, in Hebrew).

## Layout — five domains in one monorepo

| Folder | What it holds |
|---|---|
| `backend/` | 🧠 FastAPI server — the brain (api / services / models / core / db). |
| `gateway/` | 💬 Node + Baileys WhatsApp gateway (socket / webhook / routes). |
| `frontend/` | 🎨 React + Tailwind owner app + public pages (RTL Hebrew, accessible). |
| `infra/` | 🧱 docker-compose + env templates — how the stack runs. |
| `supabase/` | 🗄️ Postgres migrations (RLS lives here) + seed. |
| `docs/` | 📚 Living docs: STATUS, decisions, spec, system-map. |
| `tests/` | 🛡️ `test_*.bat` runners (test code lives in `backend/tests/`). |
| `CLAUDE.md` · `.claude/` | The master rulebook + the AI agents/workflows. |

Each domain folder has its own `README.md`; the full annotated map is in [`STRUCTURE.md`](STRUCTURE.md).

## Tech stack

- **Backend:** Python / FastAPI / LangGraph
- **Frontend:** React + Tailwind CSS
- **WhatsApp gateway:** Node.js / Express / Baileys
- **AI + RAG:** Google Gemini (`gemini-3.1-flash-lite`)
- **Database:** Supabase (PostgreSQL)
