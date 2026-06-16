# infra/ — local dev platform 🧱

**Owner agent:** Infra · **Built in:** M0 (see [`../docs/spec/mvp-checklist.md`](../docs/spec/mvp-checklist.md))

Everything that makes the project **runnable, repeatable, and safe to develop on**: the docker-compose
stack, the env/secrets template, and (in CI) the isolation harness wiring. Cloud provisioning (AWS) is
separate — that's the DevOps agent's `M8`.

## The monorepo (canonical tree)
```
Bizz_up/
├── backend/      🧠 FastAPI app                (Backend)
├── gateway/      💬 Node / Baileys gateway      (WhatsApp)
├── frontend/     🎨 React + Tailwind            (Frontend)
├── infra/        🧱 docker-compose, .env.example (Infra)   ← you are here
├── supabase/     🗄️ migrations/ (RLS lives here) (Data)
├── tests/        🛡️ isolation/ harness          (Security/Infra)
├── docs/         📚 the planning set (spec, decisions, roadmap)
├── Makefile      one-command verbs
└── .gitignore
```

## What lives here
- `docker-compose.yml` — the local stack: backend + gateway + frontend + redis + supabase, **health-gated** (M0-2).
- `.env.example` — the **names** of every required secret (no values). The app fails to boot if any is missing (M0-4).

*Status: skeleton — `docker-compose.yml` and `.env.example` are stubs to be filled in M0-2 / M0-4.*
