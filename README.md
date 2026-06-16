# Bizz_up

A multi-tenant **WhatsApp Bot SaaS** platform. Business owners connect WhatsApp and build
conversational chat menus that collect leads, book appointments, answer questions from their own
content (RAG), and hand off to a human when needed.

> This is the **new, clean rebuild** of the original project (`../last_bo`).
> The original is **read-only** and is never modified.

## Project status

🟡 **Phase 1 — Mapping & Understanding.**
We are scanning the original system and documenting it before rebuilding anything.

## Layout

| Folder | What it holds |
|---|---|
| `CLAUDE.md` | The master rulebook all AI agents follow. |
| `.claude/` | The "AI control room": scanning agents, workflows, settings. |
| `docs/` | Living documentation — the map of the system, bugs, and security issues. |
| `backend/` `frontend/` `whatsapp-gateway/` | Empty placeholders for the future rebuild. |

## Tech stack (target)

- **Backend:** Python / FastAPI / LangGraph
- **Frontend:** React + Tailwind CSS
- **WhatsApp gateway:** Node.js / Express / Baileys
- **AI + RAG:** Google Gemini
- **Database:** Supabase (PostgreSQL)
