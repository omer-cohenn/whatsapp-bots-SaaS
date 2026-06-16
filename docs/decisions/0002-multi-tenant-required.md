# 0002 — The platform must be truly multi-tenant

- **Date:** 2026-06-16
- **Status:** accepted

## Context
Today the inbound WhatsApp path collapses **all** traffic to a single business (`client_001`, read
from one global config file), several tables/queries lack proper `business_id` isolation (security
C2/C3/C4), and per-business config lives in JSON files on disk.

## Decision
Bizz_up is a **multi-tenant SaaS**. Every business is fully isolated: its own WhatsApp connection (QR
session), its own configuration, and its own data — all keyed by a real `business_id`.

## Why
Omer's choice; multi-tenancy is the core of the product (many businesses on one platform).

## Consequences
- **Inbound routing** must map each incoming message to the correct business (by which gateway
  session / phone number received it) — fixes the single-tenant webhook (bug B18).
- **Every tenant-scoped query MUST filter by `business_id`** — fixes C2 (no auth → shared tenant),
  C3 (admin UPDATE with no WHERE), C4 (booking IDOR), and the `conversations` phone-only keys.
- **Per-business config** (`system_prompt.json`, `menus_chat.json`) moves from disk into **Supabase**.
- The Baileys gateway must manage **one session per business**, not the shared `default` slot it uses
  today. See [`0001-whatsapp-baileys-canonical.md`](0001-whatsapp-baileys-canonical.md).
