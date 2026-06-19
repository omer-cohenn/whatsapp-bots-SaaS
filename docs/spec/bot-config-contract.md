# Bot Config Contract — `bot_settings` jsonb shapes (M4)

> **Status:** FINAL for M4 (the AI bot builder).
> **Scope:** the exact JSON shapes the **backend** writes and the **frontend** renders for the
> per-business bot configuration row in `bot_settings`. This is the single contract both sides agree on,
> so the bot engine, the builder UI, and the AI assistant never drift.
> **Source of truth for the table itself:** [`data-model.md`](./data-model.md) (table 6, `bot_settings`).
> **Grounding:** the original system's `client_config/system_prompt.json` + `menus_chat.json`
> (`last_bo`, read-only) — these are the M4-normalized versions of those files moved off disk into the DB.

---

## Why this document exists

`bot_settings` stores the bot's whole brain in a few `jsonb` columns. JSON is schemaless at the DB level,
so **the schema lives here, in writing.** Two rules follow from that:

1. **The backend is the gatekeeper.** The AI builder proposes config, but its output is **untrusted** (it's
   LLM text). The backend validates every shape below **before** writing to `bot_settings`, and rejects
   anything that doesn't match. The frontend may pre-validate for UX, but the server check is the real one.
2. **`business_id` is never in the JSON.** The tenant is the row's `business_id` column (set from the
   server session + enforced by RLS). A `business_id` appearing inside any jsonb payload is ignored —
   never trusted, never used to scope anything. (The old system kept `business_id` *inside* the config
   file, which is exactly the cross-tenant footgun the rebuild removes.)

The `bot_settings` columns this contract covers:

| Column | Type | Covered below |
|---|---|---|
| `bot_profile` | `jsonb` (object) | §1 |
| `lead_steps` | `jsonb` (object keyed by flow name) | §2 |
| `handoff_keywords` | `jsonb` (array of strings) | §3 |
| `is_published` | `boolean` | §4 |

> **Not in M4 — `knowledge` (RAG) is RESERVED.** RAG / file-grounded answering is **Phase 3**, not M4.
> See §6: the key name is reserved now so we don't repurpose it later, but the bot builder must **not**
> write it and the engine must **not** read it in M4.

---

## 1. `bot_profile` — the bot's identity + global behavior (object)

A single JSON **object**. Holds the bot's persona and the conversation-wide settings (greeting, escalation,
auto-close, the words that pop the menu). Replaces the old `system_prompt.json`.

```jsonc
{
  "name": "עוזר המספרה",                       // bot display name (shown in try-me + dashboard)
  "system_prompt": "אתה עוזר דיגיטלי...",       // the persona / instructions sent to Gemini
  "tone": "חברותי וקליל",                       // free-text tone hint ("warm and pleasant")
  "language": "he",                              // BCP-47-ish short code: "he" | "en" (default "he")
  "greeting": "שלום! איך אפשר לעזור?",          // first message the bot sends on a new chat
  "escalation_message": "נציג יחזור אליך בקרוב 🙏", // sent when a human handoff is triggered
  "auto_close_minutes": 60,                      // idle minutes before the live chat auto-closes
  "menu_keywords": ["תפריט", "menu", "0"]        // words that re-show the main menu (array of strings)
}
```

### Field rules

| Field | Type | Required | Rules / default |
|---|---|---|---|
| `name` | string | yes | 1–80 chars after trim. The bot's display name. |
| `system_prompt` | string | yes | non-empty after trim; soft cap ~4000 chars. The persona sent to the model. **Never** put secrets/keys here. |
| `tone` | string | no | free text, ≤ 120 chars. Default `""`. A hint, not a hard rule. |
| `language` | string | no | short code; M4 supports `"he"` (default) and `"en"`. Drives RTL + default copy. |
| `greeting` | string | no | ≤ 1000 chars. Default `""` (engine falls back to a generic hello). First outbound message. |
| `escalation_message` | string | no | ≤ 1000 chars. Default `""`. Sent once when handoff fires (see §3). |
| `auto_close_minutes` | integer | no | `5`–`1440`. Default `60`. Mirrors the Redis live-chat TTL (data-model "Live chat"). |
| `menu_keywords` | string[] | no | each item 1–40 chars; max 20 items; deduped, trimmed. Default `[]`. Typing one re-shows the menu. |

- **Unknown keys:** the backend **strips** keys not listed here before saving (forward-compatible, no
  surprise persistence of LLM-invented fields). `knowledge` is the one *reserved* exception (§6) — also not
  persisted in M4.
- **Empty profile is legal:** a brand-new business may have `bot_profile = {}`. The frontend renders empty
  fields; the engine uses the defaults above.

---

## 2. `lead_steps` — the questionnaires / flows (object keyed by flow name)

> ⚠️ **`lead_steps` is an OBJECT keyed by flow name — NOT an array.** This is the single most important
> shape in this contract and the most common place to get it wrong. One business can have several flows
> (e.g. a quote questionnaire *and* a complaint questionnaire *and* a "talk to a human" path), so the top
> level is a map: **`{ "<flow_name>": <flow object>, ... }`**. (The old `menus_chat.json` used a `flows`
> *array*; M4 keys it by name so `leads.lead_name` can point straight at the flow that produced a lead.)

```jsonc
{
  // key = the flow name. Also stored on each lead as leads.lead_name, and emitted as flow_events.flow_key.
  "quote": {
    "label": "קבלת הצעת מחיר",                  // human label shown in the menu / dashboard
    "flow_type": "lead",                          // "lead" | "human_handoff" | "booking"
    "steps": [
      {
        "key": "full_name",                       // machine key → becomes a key in leads.answers
        "question": "מה השם המלא שלך?",           // what the bot asks
        "type": "text",                           // "text" | "phone" | "email" | "choice"
        "required": true
      },
      {
        "key": "phone",
        "question": "מה מספר הטלפון שלך?",
        "type": "phone",
        "required": true,
        "error_message": "לא הצלחתי לזהות מספר טלפון, אפשר שוב?"
      },
      {
        "key": "service",
        "question": "איזה שירות מעניין אותך?",
        "type": "choice",
        "required": true,
        "options": ["תספורת", "צבע", "החלקה"]
      }
    ]
  },

  "talk_to_human": {
    "label": "דברו עם נציג",
    "flow_type": "human_handoff",                 // handoff flows carry NO steps (see rules)
    "steps": []
  },

  "book": {
    "label": "קביעת תור",
    "flow_type": "booking",                       // booking = Phase 2; shape reserved here only
    "service_name": "תספורת גברים",               // booking-only field
    "steps": [
      { "key": "full_name", "question": "מה שמך?", "type": "text", "required": true }
    ]
  }
}
```

### Top-level rules (the map)

| Concern | Rule |
|---|---|
| Container | a JSON **object** (`{}`), never an array. Default `{}` (no flows yet). |
| Flow name (the key) | `^[a-z0-9_]{1,40}$` (lowercase snake_case). Stable id — renaming = new key. Must be unique (objects guarantee that). Mirrored into `leads.lead_name` / `flow_events.flow_key`. |
| Max flows | ≤ 20 per business (sanity cap). |
| Empty | `{}` is valid — the bot just has no questionnaires. |

### Per-flow object

| Field | Type | Required | Rules |
|---|---|---|---|
| `label` | string | yes | 1–80 chars after trim. Human-readable menu/dashboard label. |
| `flow_type` | enum string | yes | one of **`"lead"`**, **`"human_handoff"`**, **`"booking"`**. Anything else is rejected. |
| `steps` | array | yes | array of step objects (§2.1). For `human_handoff` it MUST be empty (`[]`). For `lead` it MUST have ≥ 1 step. Max 30 steps. |
| `service_name` | string | no | **booking-only.** Ignored (stripped) for non-booking flows. ≤ 80 chars. |

- **`flow_type: "human_handoff"`** → `steps` must be `[]`. The bot doesn't collect anything; it flips the
  live chat to `human` and sends `bot_profile.escalation_message`. (See §3 for the *other* way handoff
  fires — keywords.)
- **`flow_type: "booking"`** → **reserved for Phase 2.** M4 validates the shape if present but the engine
  treats it as informational only (booking isn't wired in M4). Frontend may show it as "coming soon".
- **`flow_type: "lead"`** → the normal questionnaire path. Answers are saved (encrypted) to
  `leads.answers`, keyed by each step's `key`.

### 2.1 Step object (inside `steps`)

```jsonc
{
  "key": "email",                 // machine key (unique within the flow)
  "question": "מה כתובת המייל?",  // the prompt the bot sends
  "type": "email",                // "text" | "phone" | "email" | "choice"
  "required": true,               // must the user answer to advance?
  "validate": "email",            // OPTIONAL extra check hint (see rules)
  "options": ["א", "ב"],          // REQUIRED only when type = "choice"
  "error_message": "כתובת לא תקינה, נסו שוב"  // OPTIONAL retry message on validation fail
}
```

| Field | Type | Required | Rules |
|---|---|---|---|
| `key` | string | yes | `^[a-z0-9_]{1,40}$`. **Unique within its flow.** Becomes a key in `leads.answers`. |
| `question` | string | yes | 1–500 chars after trim. The text the bot sends. |
| `type` | enum string | yes | one of **`"text"`**, **`"phone"`**, **`"email"`**, **`"choice"`**. |
| `required` | boolean | yes | `true`/`false`. If `true`, the bot won't advance without a valid answer. |
| `validate` | string | no | extra validation hint, e.g. `"phone"` / `"email"` / a named rule. For `type:"phone"`/`"email"` validation is implied; `validate` is for overriding/extra rules. Unknown values are ignored by the engine (treated as no extra check). |
| `options` | string[] | conditional | **required & non-empty when `type:"choice"`** (2–12 items, each 1–80 chars, deduped). **Ignored/stripped for non-choice types.** |
| `error_message` | string | no | ≤ 200 chars. Shown when the user's answer fails validation; engine has a generic default if omitted. |

- **Choice steps:** `options` is the closed list of valid answers. The engine matches the user's reply
  against it (and may render them as numbered options). Without `options`, a `choice` step is **invalid**.
- **`type` vs `validate`:** `type` drives both the *input expectation* and built-in validation
  (`phone` → phone-shaped, `email` → email-shaped). `validate` is an optional extra/override. Keep them
  consistent; when in doubt the backend trusts `type`.
- **Where answers go:** each answered step writes `answers[step.key] = <value>` on the lead. The whole
  `answers` blob is **encrypted at rest** (it's customer PII) — that's the backend's job, not part of this
  shape. The keys (`step.key`) are not PII and stay readable in the structure.

---

## 3. `handoff_keywords` — words that trigger a human (column, array)

The `bot_settings.handoff_keywords` **column** (jsonb) is a **flat array of strings**. If a customer's
message contains one of these, the bot escalates to a human (flips the Redis live-chat status to `human`
and sends `bot_profile.escalation_message`), independent of which flow they're in.

```jsonc
["נציג", "אדם", "human", "agent"]
```

| Concern | Rule |
|---|---|
| Type | JSON array of strings. Default (DB) `["נציג","אדם","human","agent"]`. |
| Item rules | each 1–40 chars after trim; case-insensitive match; deduped. |
| Size | 0–30 items. `[]` is legal (keyword-handoff off; the `human_handoff` *flow* in §2 still works). |

> Two independent handoff triggers exist and both are valid: **(a)** a `flow_type:"human_handoff"` flow the
> user picks from the menu (§2), and **(b)** these free-text keywords matched anywhere (§3). Both end in the
> same place: status → `human`, send `escalation_message`, bot stops answering that chat.

---

## 4. `is_published` — try-me vs live (column, boolean)

The `bot_settings.is_published` **column** (boolean, default `false`).

- `false` → the bot is in **try-me / draft** mode. It runs only in the owner's test tool; leads created are
  flagged `leads.is_test = true` and excluded from real stats.
- `true` → the bot is **live**: it answers real inbound WhatsApp messages for that business.

This is a column, not part of any jsonb. The builder flips it via the publish action (validated server-side:
a business can only publish a config that passes §1–§3).

---

## 5. End-to-end example (one full `bot_settings` row)

What a saved row looks like, column by column (UUIDs/timestamps omitted):

```jsonc
// business_id: <uuid from the server session — NOT shown in any jsonb>

// bot_profile (§1)
{
  "name": "עוזר מספרת הסטייל",
  "system_prompt": "אתה עוזר דיגיטלי חברותי של מספרה. עזור לקבוע תורים ולהשאיר פרטים. אל תמציא מידע.",
  "tone": "חברותי וקליל",
  "language": "he",
  "greeting": "שלום וברוך הבא! 💇 איך אפשר לעזור?",
  "escalation_message": "תודה! נציג יחזור אליך בקרוב 🙏",
  "auto_close_minutes": 60,
  "menu_keywords": ["תפריט", "menu", "0"]
}

// lead_steps (§2) — OBJECT keyed by flow name
{
  "quote": {
    "label": "קבלת הצעת מחיר",
    "flow_type": "lead",
    "steps": [
      { "key": "full_name", "question": "מה השם המלא שלך?", "type": "text",  "required": true },
      { "key": "phone",     "question": "מה הטלפון שלך?",    "type": "phone", "required": true,
        "error_message": "מספר לא תקין, נסו שוב" }
    ]
  },
  "talk_to_human": {
    "label": "דברו עם נציג",
    "flow_type": "human_handoff",
    "steps": []
  }
}

// handoff_keywords (§3)
["נציג", "אדם", "human", "agent"]

// is_published (§4)
false
```

---

## 6. Reserved for later — `knowledge` (RAG) is NOT M4

RAG (file/website-grounded answering, **Phase 3**) will need its own config. To avoid repurposing a name
later, the key **`knowledge`** on `bot_profile` (or a future dedicated column) is **reserved now**:

- The bot builder must **not** emit `knowledge` in M4.
- The bot engine must **not** read `knowledge` in M4.
- Validators **strip** an incoming `knowledge` key in M4 (treated like any unknown key — not persisted),
  so nothing accidentally depends on it before Phase 3 designs the real shape.

When RAG lands, this section is replaced with the real `knowledge` contract (expected: source list, chunk
settings, "zero creativity / grounded-only" flags).

---

## 7. Validation checklist (the backend MUST enforce; the frontend SHOULD mirror)

Before any write to `bot_settings`:

- [ ] `bot_profile` is an object; `name` + `system_prompt` present & non-empty; `auto_close_minutes` in
      `5..1440`; `menu_keywords` an array of ≤20 trimmed strings; unknown keys stripped (incl. `knowledge`).
- [ ] `lead_steps` is an **object** (reject arrays); each key matches `^[a-z0-9_]{1,40}$`; ≤20 flows.
- [ ] each flow has a valid `flow_type` (`lead`|`human_handoff`|`booking`) and a string `label`.
- [ ] `human_handoff` flows have `steps: []`; `lead` flows have ≥1 step; ≤30 steps each.
- [ ] each step: `key` unique-in-flow & snake_case; `question` non-empty; `type` in the enum;
      `required` boolean; `choice` steps have a non-empty `options` array; non-choice `options` stripped.
- [ ] `handoff_keywords` is an array of ≤30 trimmed strings.
- [ ] `is_published` is a boolean (and only flips to `true` if all of the above pass).
- [ ] **no `business_id` is read from any payload** — the tenant comes from the server session + RLS only.
</content>
</invoke>
