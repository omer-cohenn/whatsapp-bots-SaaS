# Workflow: scan-existing-system

**Goal:** produce a complete, beginner-readable map of the original `last_bo` system — plus a bugs
file and a security-issues file — by running the specialist scanning agents in the right order.

**Target (read-only):** `C:\Users\עמר כהן\Desktop\last_bo`
**Output:** files under `C:\Users\עמר כהן\Desktop\bizz_up\docs\`

---

## The recipe

### Phase 1 — Scan in parallel (independent specialists)
These 4 run at the same time; none depends on another:

| Agent | Reads | Produces |
|-------|-------|----------|
| `business-logic-scanner` | `last_bo/bot/**` | `docs/system-map/backend-map.md` |
| `frontend-mapper` | `last_bo/frontend/**` | `docs/system-map/frontend-map.md` |
| `whatsapp-scanner` | the Node/Baileys gateway | `docs/system-map/whatsapp-gateway.md` |
| `infra-scanner` | run scripts, configs, deps | `docs/system-map/infrastructure.md` |

### Phase 2 — Security pass
`security-scanner` reads across the whole repo and writes `docs/security-issues.md`.
(Can run in Phase 1 too — it's independent — but is listed separately because it consumes flags the
other scanners raise.)

### Phase 3 — Collect the bugs
Gather every "⚠️ flag for bugs.md" raised by the Phase 1/2 agents into `docs/bugs.md`
(slow `setup.bat` startup, possibly-unused `rag_data/`, fragile gateway reconnection, etc.).

### Phase 4 — Assemble the big picture
`docs-assembler` reads all of the above and writes the "glue" documents:
- `docs/00_overview.md`
- `docs/system-map/architecture.md`
- `docs/system-map/data-flow.md`
- `docs/system-map/database-schema.md`

---

## Order summary

```
  ┌─ business-logic-scanner ─┐
  ├─ frontend-mapper ────────┤
  ├─ whatsapp-scanner ───────┤  (parallel)
  ├─ infra-scanner ──────────┤
  └─ security-scanner ───────┘
                │
                ▼
        collect bugs.md
                │
                ▼
        docs-assembler  (overview + architecture + data-flow + db-schema)
```

## Rules for the whole workflow
- `last_bo` is **READ-ONLY**. Agents write ONLY inside `Bizz_up/docs/`.
- If an agent is unsure of a fact, it must mark it "needs verification" — never invent details.
- This workflow only produces documentation. **No production code is written.**

> When we run this, the main agent will translate this recipe into an executable run (spawning the
> agents above in this order) and report a short summary back to Omer.
