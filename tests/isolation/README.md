# tests/isolation/ — the multi-tenant isolation harness 🛡️🚦

**Owner agents:** Security + Infra · **Built in:** M2 · **Status: the project's #1 quality gate**

The automated suite that proves **one business can never see or touch another's data** — across the DB/RLS
layer, the API layer, and the Redis cache — plus the crown-jewel no-read guard and the "no secret/PII in
logs or responses" check. **It is a blocking CI check: nothing tenant-scoped merges while it's red.**

Must cover (per [`../../docs/spec/data-model.md`](../../docs/spec/data-model.md) + the security part):
- DB: tenant A can't read/write tenant B's rows; a forged `business_id` is denied; **a forgotten-`WHERE`
  canary** still returns zero of B's rows; the dashboard role gets *permission denied* on `whatsapp_credentials`.
- **Pooling/concurrency:** interleaved A/B requests on a shared pool never bleed `business_id`.
- API: unauthenticated → 401 (no anonymous fallback tenant); a client-supplied `business_id` is never trusted.
- Redis: A can't touch B's `chat:{business_id}:…` key.
- A **negative-control** test (a deliberately cross-tenant query that *must* fail) so a misconfigured harness can't give false confidence.

> ⚠️ The harness must connect as the **real non-service roles** — if it runs as a superuser it passes
> trivially and proves nothing. This was the old system's #1 failure; treat it accordingly.

*Status: skeleton (folder reserved). Built in M2.*
