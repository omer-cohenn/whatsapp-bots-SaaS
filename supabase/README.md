# supabase/ — database (Postgres) 🗄️

**Owner agent:** Data · **Built in:** M2 (see [`../docs/spec/mvp-checklist.md`](../docs/spec/mvp-checklist.md))

Versioned SQL migrations for the **9 tables** — and, critically, **their RLS policies and the two
non-service DB roles live in the same migrations** (RLS is never an afterthought).

```
supabase/
├── migrations/   # NNNN_*.sql — tables + RLS (USING + WITH CHECK) + grants, in order
└── seed/         # tenant-aware demo data (is_test) — seeded via the real app roles
```

> The schema is specified in [`../docs/spec/data-model.md`](../docs/spec/data-model.md). The dashboard role
> gets **zero grant** on `whatsapp_credentials`; every tenant table carries `business_id` + RLS.

*Status: skeleton (folder reserved). Migrations authored in M2.*
