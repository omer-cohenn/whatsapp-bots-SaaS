# 0001 — WhatsApp connection: use the Baileys QR gateway (not Meta Cloud API)

- **Date:** 2026-06-16
- **Status:** accepted

## Context
The codebase has **two unconnected** WhatsApp integrations:
- Meta's official **Cloud API** (live today in `last_bo` via the `pywa` library).
- A Node.js **Baileys QR-scanner gateway** (`qr_wa_scanner`) — standalone, not wired into the backend.

We had to pick one canonical path before rebuilding.

## Decision
The **Baileys QR-scanner gateway is the canonical WhatsApp path.** Businesses onboard by scanning a
QR code (WhatsApp → Linked Devices).

## Why
Omer's choice. Onboarding is simpler — no Meta Business verification or per-business number
provisioning, and no per-message Meta fees.

## Tradeoffs / risks to manage
- ⚠️ **Baileys is unofficial** (it automates WhatsApp Web) — against WhatsApp's ToS, with a real
  **account-ban risk**. Mitigate with sane sending rate limits and one number per business.
- 🔒 Session credentials are currently stored **unencrypted on disk** (security M1) → must be
  encrypted at rest in the rebuild.
- 🔌 The **receive/inbound path is not yet verified end-to-end**: the gateway *does* emit incoming
  messages to a webhook (Omer has seen that API), and **sending** is confirmed working — but the
  inbound path has never been tested all the way through to the backend, and the gateway→backend
  wiring + webhook-URL persistence are incomplete (bugs B1, B3). **One real end-to-end receive test**
  is an early priority.

## Consequences
- The rebuild's WhatsApp message in/out layer targets the **Baileys gateway payload format**, not the
  Meta envelope.
- The Meta Cloud API path (`pywa`, the Meta-style `/webhook` parsing) can be dropped — or kept only as
  an optional fallback (to decide during the spec).
- The gateway must support **multiple concurrent sessions** (one per business) — see
  [`0002-multi-tenant-required.md`](0002-multi-tenant-required.md).
