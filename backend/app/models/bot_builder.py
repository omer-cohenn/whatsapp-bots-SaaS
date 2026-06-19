"""Pydantic v2 models for the bot config — the SERVER-SIDE validation gate.

These models are the single enforcement point for the jsonb shapes in
`docs/spec/bot-config-contract.md`. They matter for two reasons:

  1. The AI builder's output is **untrusted** (it's raw LLM text). Whatever the
     model proposes is parsed and re-validated against these bounds *before* it
     is ever written to `bot_settings`. Anything out of bounds is rejected.
  2. They are also the read/write shape for the plain GET/PUT settings API.

Design choices that follow the contract:

  * `lead_steps` is an **object keyed by flow name** (NOT an array). We model it
    as `dict[str, Flow]` and validate the keys with a snake_case pattern.
  * `business_id` NEVER appears here — the tenant comes from the server session
    + RLS. (A `business_id` in any payload is simply ignored.)
  * `extra="forbid"` on the leaf models is deliberate: unknown keys are an error
    while validating, but the *service* strips unknown keys first (so an LLM that
    invents a field — including the reserved `knowledge` key — is forgiven and
    normalized, not exploited). See `app/services/bot_builder_ai.py`.

Bounds are intentionally generous-but-finite: they exist to stop abuse / runaway
LLM output, not to nitpick a real owner's wording.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- Shared bound constants (kept here so the contract lives in one place) ----
# Flow name (the dict key) and step key: Hebrew/English letters, digits, space
# or underscore, 1..40 chars. The Hebrew block U+0590-U+05FF is allowed so owners
# can name fields in Hebrew — the key is just an internal identifier.
KEY_PATTERN = re.compile(r"^[a-z0-9_֐-׿ ]{1,40}$")

MAX_FLOWS = 20          # ≤ 20 flows per business (contract §2)
MAX_STEPS_PER_FLOW = 30  # ≤ 30 steps per flow (contract §2)
MAX_CHOICE_OPTIONS = 12  # choice options: 2..12 (contract §2.1)
MAX_MENU_KEYWORDS = 20   # bot_profile.menu_keywords ≤ 20 (contract §1)
MAX_HANDOFF_KEYWORDS = 30  # handoff_keywords ≤ 30 (contract §3)

StepType = Literal["text", "phone", "email", "choice"]
FlowType = Literal["lead", "human_handoff", "booking"]


class Step(BaseModel):
    """One question in a flow (contract §2.1).

    `options` is REQUIRED (2..12 items) when `type == "choice"`, and ignored for
    every other type. `key` must be snake_case and unique within its flow (the
    uniqueness check is done at the Flow level, where all keys are visible).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(..., min_length=1, max_length=40)
    question: str = Field(..., min_length=1, max_length=500)
    type: StepType
    required: bool
    # Optional extra-validation hint (e.g. "phone"/"email"); the engine treats
    # unknown values as "no extra check". Kept short.
    # NOTE: the field is named `validate` to match the frozen wire contract
    # (docs/spec/bot-config-contract.md §2.1). Pydantic emits a benign
    # UserWarning because `validate` shadows a deprecated BaseModel method we
    # never call (we always use the `model_validate` classmethod) — the data
    # field is unaffected. Renaming would break the JSON shape the frontend uses.
    validate: str | None = Field(default=None, max_length=40)  # noqa: A003
    # Required ONLY for choice steps; stripped for others (see model_validator).
    options: list[str] | None = Field(default=None)
    error_message: str | None = Field(default=None, max_length=200)

    @field_validator("key")
    @classmethod
    def _key_is_snake_case(cls, value: str) -> str:
        if not KEY_PATTERN.fullmatch(value):
            raise ValueError(
                "field key may contain letters (Hebrew/English), digits, "
                "space or underscore (max 40 chars)"
            )
        return value

    @model_validator(mode="after")
    def _enforce_options_rule(self) -> "Step":
        """choice → options required (2..12, trimmed, deduped); else → no options."""
        if self.type == "choice":
            opts = [o.strip() for o in (self.options or []) if o and o.strip()]
            # Dedupe but keep order (a closed answer list shouldn't repeat).
            seen: list[str] = []
            for o in opts:
                if o not in seen:
                    seen.append(o)
            if not (2 <= len(seen) <= MAX_CHOICE_OPTIONS):
                raise ValueError(
                    f"choice step '{self.key}' needs 2..{MAX_CHOICE_OPTIONS} options"
                )
            for o in seen:
                if len(o) > 80:
                    raise ValueError("each choice option must be ≤ 80 chars")
            self.options = seen
        else:
            # Non-choice types never carry options (strip silently).
            self.options = None
        return self


class Flow(BaseModel):
    """One questionnaire / path, keyed by name at the top level (contract §2).

    Rules enforced here:
      * `human_handoff` flows MUST have `steps == []` (the bot collects nothing).
      * `lead` flows MUST have ≥ 1 step.
      * step `key`s must be unique within the flow.
      * `service_name` is booking-only; it is stripped for non-booking flows.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    label: str = Field(..., min_length=1, max_length=80)
    flow_type: FlowType
    steps: list[Step] = Field(default_factory=list, max_length=MAX_STEPS_PER_FLOW)
    service_name: str | None = Field(default=None, max_length=80)
    # Customer-facing message for human_handoff (the handoff notice) and booking
    # (supports an optional {link} placeholder). Optional for lead flows.
    message: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _enforce_flow_rules(self) -> "Flow":
        if self.flow_type == "human_handoff":
            if self.steps:
                raise ValueError("human_handoff flows must have steps: []")
        elif self.flow_type == "lead":
            if len(self.steps) < 1:
                raise ValueError("lead flows must have at least 1 step")

        # service_name is booking-only — strip it for the other flow types.
        if self.flow_type != "booking":
            self.service_name = None

        # step keys unique within this flow.
        keys = [s.key for s in self.steps]
        if len(keys) != len(set(keys)):
            raise ValueError("step keys must be unique within a flow")
        return self


class BotProfile(BaseModel):
    """The bot's identity + global behavior (contract §1).

    `name` + `system_prompt` are the only required fields; everything else has a
    safe default so a brand-new business can save a minimal profile. Unknown
    keys (including the reserved `knowledge`) are rejected here, but the service
    strips them first so an LLM that adds extras is normalized, not failed.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=80)
    # Soft cap ~4000 chars (contract §1). NEVER put secrets here.
    system_prompt: str = Field(..., min_length=1, max_length=4000)
    tone: str = Field(default="", max_length=120)
    language: Literal["he", "en"] = "he"
    greeting: str = Field(default="", max_length=1000)
    escalation_message: str = Field(default="", max_length=1000)
    auto_close_minutes: int = Field(default=60, ge=5, le=1440)
    menu_keywords: list[str] = Field(default_factory=list)

    @field_validator("menu_keywords")
    @classmethod
    def _clean_menu_keywords(cls, value: list[str]) -> list[str]:
        return _clean_keyword_list(value, max_items=MAX_MENU_KEYWORDS, field="menu_keywords")


class BotSettings(BaseModel):
    """The full `bot_settings` row shape (minus the DB-managed columns).

    This is both the GET/PUT API body and the validated target the AI merge must
    satisfy before any write. `lead_steps` is the object-keyed map of flows.
    """

    model_config = ConfigDict(extra="forbid")

    lead_steps: dict[str, Flow] = Field(default_factory=dict)
    bot_profile: BotProfile
    handoff_keywords: list[str] = Field(
        default_factory=lambda: ["נציג", "אדם", "human", "agent"]
    )
    is_published: bool = False

    @field_validator("lead_steps")
    @classmethod
    def _validate_flow_keys(cls, value: dict[str, Flow]) -> dict[str, Flow]:
        if len(value) > MAX_FLOWS:
            raise ValueError(f"at most {MAX_FLOWS} flows are allowed")
        for key in value:
            if not KEY_PATTERN.fullmatch(key):
                raise ValueError(
                    f"flow name '{key}' may contain letters (Hebrew/English), "
                    "digits, space or underscore (max 40 chars)"
                )
        return value

    @field_validator("handoff_keywords")
    @classmethod
    def _clean_handoff_keywords(cls, value: list[str]) -> list[str]:
        return _clean_keyword_list(
            value, max_items=MAX_HANDOFF_KEYWORDS, field="handoff_keywords"
        )


# --- API request/response wrappers (the AI-chat endpoint) --------------------

# Hard cap on a single builder message (defense against oversized request bodies
# / prompt-stuffing). Generous for normal chat, finite against abuse.
MAX_CHAT_MESSAGE_CHARS = 8000
# Hard cap on the working-config prompt context sent with each AI turn. Stops an
# authenticated owner (or a stolen session) from posting a multi-megabyte /
# deeply-nested blob that would inflate the Gemini prompt (memory/CPU pressure +
# token-cost abuse). Generous for a real mid-build config, finite against abuse.
# (M4 security review — the one "med" finding.)
MAX_CHAT_CONFIG_BYTES = 65536


class BotAiChatRequest(BaseModel):
    """POST /api/bot/ai/chat body.

    `current_config` is the builder's working copy sent from the client. It is
    UNTRUSTED context for the prompt only — the merge result is re-validated and
    the tenant is NEVER read from it. It is permissive (a free dict) on purpose,
    because mid-build the config may be incomplete (no name/prompt yet) — but it
    is size/flow-count bounded so it can't be used to stuff the prompt.
    """

    model_config = ConfigDict(extra="ignore")

    message: str = Field(..., min_length=1, max_length=MAX_CHAT_MESSAGE_CHARS)
    current_config: dict = Field(default_factory=dict)

    @field_validator("current_config")
    @classmethod
    def _bound_current_config(cls, value: dict) -> dict:
        """Cap the working-config size + flow count (anti-DoS / token-cost abuse)."""
        try:
            size = len(json.dumps(value, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            raise ValueError("current_config must be JSON-serializable") from exc
        if size > MAX_CHAT_CONFIG_BYTES:
            raise ValueError(f"current_config too large (> {MAX_CHAT_CONFIG_BYTES} bytes)")
        flows = value.get("lead_steps")
        if isinstance(flows, dict) and len(flows) > MAX_FLOWS:
            raise ValueError(f"current_config has too many flows (> {MAX_FLOWS})")
        return value


class BotAiChatResponse(BaseModel):
    """POST /api/bot/ai/chat response: the assistant reply + parsed changes (if any)."""

    reply: str
    # Present only when the model proposed a (validated) config change.
    changes: dict | None = None


class BotAiMessage(BaseModel):
    """One stored build-chat message (for GET /api/bot/ai/history)."""

    role: str  # "user" | "assistant"
    content: str
    created_at: str


class BotAiHistoryResponse(BaseModel):
    """GET /api/bot/ai/history response: recent build-chat messages (oldest→newest)."""

    messages: list[BotAiMessage]


# --- small shared helper ------------------------------------------------------

def _clean_keyword_list(value: list[str], *, max_items: int, field: str) -> list[str]:
    """Trim, drop blanks, dedupe (case-insensitive), and bound a keyword list."""
    cleaned: list[str] = []
    seen_lower: set[str] = set()
    for raw in value:
        item = (raw or "").strip()
        if not item:
            continue
        if len(item) > 40:
            raise ValueError(f"each {field} item must be ≤ 40 chars")
        low = item.lower()
        if low in seen_lower:
            continue
        seen_lower.add(low)
        cleaned.append(item)
    if len(cleaned) > max_items:
        raise ValueError(f"{field} allows at most {max_items} items")
    return cleaned
