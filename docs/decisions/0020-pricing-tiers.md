# 0020 — Pricing model: 3 tiers + usage caps + future add-on modules

> Status: **approved, building** · Date: 2026-06-25 · Owner: Omer
> All customer-facing prices **include 18% VAT**. Currency ₪ (NIS), Israeli market.

## The story (plain language)
A business owner lands on the site and sees three plans. **Free** lets them try the system with up to
5 phone numbers — enough to build confidence. **Professional (₪149)** is for small businesses that
collect leads. **Business (₪299)** adds the appointment calendar for businesses that book meetings.
Launch prices are shown struck-through against the regular price ("limited-time launch"). Pay yearly
and get two months free.

## Pricing principle (locked)
**Base subscription (3 tiers) + fair-use caps + future add-on modules for AI-heavy features.**
The base is priced by *value*; the AI-heavy/variable-cost features (RAG, broadcast) are sold
separately and metered, so one heavy customer can't erode margin.

## The three tiers (prices include VAT)
| | 🆓 חינמי | 💼 מקצועי | 🏢 עסקי |
|---|---|---|---|
| Monthly | ₪0 | ~~₪200~~ **₪149** (launch) | ~~₪349~~ **₪299** (launch) |
| Annual (2 months free) | — | **₪1,490** (₪124/mo eff.) | **₪2,990** (₪249/mo eff.) |
| Target customer | trial / "see it work" | small biz collecting leads | biz with a calendar (clinic, salon, studio) |
| Lead-collection flows | 1 | 5 | 9 |
| Leads / month | 30 | 600 | 2,000 |
| Human handoff (answered phone numbers) | up to 5 numbers | unlimited | unlimited + priority |
| Appointment booking | ❌ | ❌ | ✅ |
| AI bot-builder actions / month | 10 | 50 | 100 |
| WhatsApp numbers | 1 | 1 | 1 |
| Bizz_up branding in messages | shown | removed | removed |
| Dashboard & analytics | basic | full | full + export |

> ⚠️ **Landing page note:** human handoff is **NOT advertised** on the landing pricing cards
> (Omer's decision). The "up to 5 phone numbers" free cap is shown as a limit, not as a handoff feature.

## Future add-on modules (sold separately, on top of Pro/Business; prices include VAT)
| Module | Price | Included |
|---|---|---|
| 🧠 Smart answering (RAG) from site/docs | +₪199/mo | 500 AI answers; overage ₪0.4 each |
| 🔔 Appointment reminders | +₪49/mo | unlimited |
| 📣 Broadcast / outbound messaging | +₪99/mo | 1,000 messages; overage ₪0.08 each |

## Cost model & unit economics
Costs that matter (per the back-office `ai_call` meter and AWS):
- **VAT 18%** — pass-through. Net revenue = displayed price ÷ 1.18; the 18% is remitted to the state.
- **Sales commission 15%** — **one-time, on the first sale only** (current policy), computed on the
  **first contract value** (so a yearly deal pays the agent 15% of ₪1,490 / ₪2,990). One-time CAC.
- **Cloud (AWS)** — ~₪6 / ₪12 / ₪20 per active tenant (free/pro/business).
- **AI** — Gemini `gemini-3.1-flash-lite`, ~₪0.02 per `ai_call`. Negligible for scripted lead flows;
  heavy only for RAG → which is a metered add-on.
- **WhatsApp (Baileys)** — no per-message fee (offset by ban risk).
- **Card processing** — ~2.5% + fee.

| | מקצועי (₪149 incl VAT) | עסקי (₪299 incl VAT) |
|---|---|---|
| Net revenue (after VAT) | ~₪126 | ~₪253 |
| Monthly cost to serve | ~₪18 | ~₪36 |
| **Monthly gross profit** | **~₪108 (86%)** | **~₪217 (86%)** |
| Sales commission (one-time, first sale) | ~₪227 | ~₪456 |
| CAC payback | ~2 months | ~2 months |

~86% recurring gross margin, and even better at regular prices (₪200/₪349). Annual billing brings the
cash up front to cover the one-time commission.

## Launch-price presentation
- מקצועי: ~~₪200~~ **₪149** · "מחיר השקה לזמן מוגבל"
- עסקי: ~~₪349~~ **₪299** · "מחיר השקה לזמן מוגבל"
- Annual commitment locks the launch price for the full year (retention hook).

## DB / catalog mapping (migration 0022)
Existing `plans` catalog (0015): `free`/`basic`/`pro` @ ₪0/49/149. New model:
- `free` → name **חינמי**, price 0.
- `pro` → name **מקצועי**, price 149.
- `business` → **new**, name **עסקי**, price 299, sort_order 3.
- `basic` → **retired** (reassign any subscription on `basic` to `free`, then remove).
- Feature caps stored in `plans.limits` jsonb: `lead_flows`, `leads_per_month`, `ai_actions_per_month`,
  `handoff_numbers` (null = unlimited), `booking` (bool), `whatsapp_numbers`, plus display extras
  `regular_price`, `annual_price`. `plans.price` = the charged launch price.

## Open / deferred
- Cap **enforcement** in the engine (block at the limit, nudge to upgrade) is NOT in this change —
  catalog + landing display only. Tracked for a later milestone.
- The landing FEATURES section still has a "מעבר לנציג אנושי" card (separate from pricing) — left as-is
  unless Omer wants it removed too.

## Security & isolation
- `plans` is a GLOBAL catalog (no tenant key, no RLS) — reference data only; `app_role` keeps SELECT.
- `subscriptions` stays admin-SD-only (no direct grant). No secrets, no PII in any of this.
