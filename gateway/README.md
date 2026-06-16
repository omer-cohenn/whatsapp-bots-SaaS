# gateway/ — WhatsApp gateway (Node / Baileys) 💬

**Owner agent:** WhatsApp · **Built in:** M1 (spike) then M6 (see [`../docs/spec/mvp-checklist.md`](../docs/spec/mvp-checklist.md))

The standalone Node service that connects to WhatsApp via Baileys — **one session per business** — and
relays messages to/from the backend over a stable, authenticated channel.

## Planned layout (filled as we build)
```
gateway/
├── src/                 # service code (one clean entry, not the old single index.js)
├── package.json         # pinned deps (M0-3)
└── Dockerfile           # single-writer prod image (M8)
```

> Rules: **one writer per session**; session creds are **envelope-encrypted in the DB** (never plaintext on
> disk); the QR is **streamed, never stored**; header-only auth token; conservative **send rate-limits**
> (Baileys ban-risk). The gateway knows `accountId`, never `business_id`. See
> [`../docs/spec/roadmap-parts/whatsapp.md`](../docs/spec/roadmap-parts/whatsapp.md).

*Status: skeleton (folder reserved). No code yet.*
