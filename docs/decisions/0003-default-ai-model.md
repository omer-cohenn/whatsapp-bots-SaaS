# 0003 — Default AI model: `gemini-3.1-flash-lite`

- **Date:** 2026-06-16
- **Status:** accepted

## Context
The code used `gemini-3.1-flash-lite` while the README said `gemini-1.5-flash-8b` (bug B17). We needed
a single source of truth.

## Decision
The default AI / RAG model is **`gemini-3.1-flash-lite`**. It is recorded as the default in
`CLAUDE.md` (section 5).

## Why
Omer's choice.

## Consequences
- The README and any other mismatched references should be aligned to `gemini-3.1-flash-lite`.
- Bug **B17** (model-name mismatch) is resolved by this decision.
