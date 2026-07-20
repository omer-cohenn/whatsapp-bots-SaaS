"""The bot CONVERSATION ENGINE — a pure, deterministic function (M5 try-me).

This module is the brain that turns one inbound message + the current
conversation state into the bot's reply(ies) + the next state. It is the SAME
engine the real WhatsApp bot will use later, so it is kept strictly **pure**:

  * NO database, NO network, NO LLM, NO Redis, NO clock, NO module-level mutable
    state. Same inputs → same outputs, always.
  * It reads ONLY the two things it is handed: this tenant's `settings` (the
    validated `bot_settings` shape, see docs/spec/bot-config-contract.md) and the
    CURRENT conversation's `state`. It never touches another conversation, never
    reads a saved lead, never sees another tenant's data.

Security (owner requirement): because there is no LLM call and no data access of
any kind, there is no prompt-injection or exfiltration path. The engine only ever
echoes back the CURRENT conversation's own inputs (the answers the user just
typed). The `lead` it emits on completion is exactly what this same conversation
collected — nothing else.

The flow mirrors the original `last_bo/bot/flow_engine.py` (read-only reference),
re-shaped onto the M4 config contract (`lead_steps` is an OBJECT keyed by flow
name; step `type` in {text, phone, email, choice, file}; flow `flow_type` in
{lead, human_handoff, booking}).

M16 adds the `file` step type. The engine still does NO I/O: the gateway has
already downloaded + stored the attachment by the time we run, and hands us only
a REFERENCE (`{"file_id","mime_type","name"}`) as the optional `media` argument.
The engine's job is purely to decide whether that reference satisfies the current
step, and to place it into `collected` as the step's answer.
"""

from __future__ import annotations

import re
from typing import Any

# --- Defaults (used when the owner's profile leaves a field blank) ------------

# Words that re-show the main menu from anywhere (contract §1, bot_profile).
_DEFAULT_MENU_KEYWORDS = ["תפריט", "menu", "חזרה לתפריט הראשי", "0"]
# A friendly greeting if the owner hasn't written one yet.
_DEFAULT_GREETING = "שלום! 👋 איך אפשר לעזור?"
# Sent when a human takeover fires and no message is configured anywhere.
_DEFAULT_ESCALATION = "תודה! נציג יחזור אליך בקרוב 🙏"
# Shown every turn while the chat is paused after a human handoff.
_HANDED_OFF_NOTE = "השיחה הועברה לנציג אנושי. נחזור אליך בהקדם 🙏"
# Generic validation error if a step has no custom error_message.
_DEFAULT_VALIDATION_ERROR = "לא הצלחתי להבין את התשובה, אפשר לנסות שוב?"
# Warm completion message when a lead questionnaire finishes.
_DEFAULT_COMPLETION = "תודה רבה! קיבלנו את הפרטים שלך ונחזור אליך בקרוב 🙏"
# Gentle nudge when, at the menu, the message matched no flow.
_DEFAULT_NUDGE = "לא בטוח שהבנתי — אפשר לבחור אחת מהאפשרויות הבאות:"
# Placeholder booking link the PURE engine substitutes for {link}. The runtime
# (bot_runtime) swaps this exact string for the tenant's REAL public booking URL
# on a "booking" event (M11, fix B7) — kept PUBLIC so the runtime can match it.
DEMO_BOOKING_LINK = "https://example.com/book/demo"

# Owner requirement: every in-flow question reply ENDS with exactly this footer.
MENU_HINT = '↩️ בכל שלב אפשר לכתוב "תפריט" כדי לחזור לתפריט הראשי.'

# Simple email shape (good enough for a try-me check; mirrors the old engine).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# A phone is "real enough" if it has at least this many digits.
_MIN_PHONE_DIGITS = 9

# --- file steps (M16) --------------------------------------------------------
# The ONE translation point between a stored mime type and the owner-facing
# "kind" vocabulary used by a step's `accept` list (see
# app.models.bot_builder.FILE_ACCEPT_KINDS). A mime that is not in this map can
# never satisfy a file step — it should never reach us, because the backend's
# upload allow-list (file_storage.ALLOWED_MIME) is exactly these keys.
_MIME_KIND: dict[str, str] = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "doc",
    "application/vnd.ms-powerpoint": "ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "ppt",
}

# Hebrew labels for the kinds, used when we tell the customer what to send.
_KIND_LABEL: dict[str, str] = {
    "image": "תמונה",
    "pdf": "PDF",
    "doc": "מסמך Word",
    "ppt": "מצגת",
}

# Asked again when the customer answered a `file` step with plain text.
_FILE_EXPECTED_MSG = "אני צריך שתשלח קובץ 📎"
# Asked again when a file arrived but its kind is not on the step's accept list.
_FILE_WRONG_KIND_MSG = "סוג הקובץ הזה לא מתאים כאן. אפשר לשלוח: "
# Whole-message words that skip an OPTIONAL step (file steps only — a text step
# treats these as a legitimate answer).
_SKIP_WORDS = ("דלג", "דלגי", "אין", "אין לי", "לא", "skip", "-")

# Conversation phases.
PHASE_NEW = "new"            # brand-new conversation, not yet greeted (first turn).
PHASE_MENU = "menu"
PHASE_IN_FLOW = "in_flow"
PHASE_HANDED_OFF = "handed_off"


def initial_state() -> dict[str, Any]:
    """The state of a brand-new conversation (before the first message)."""
    return {
        "phase": PHASE_NEW,
        "active_flow": None,
        "step_index": 0,
        "collected": {},
    }


def advance(
    settings: dict, state: dict, message: str, media: dict | None = None
) -> dict[str, Any]:
    """Run one turn of the bot. PURE: no side effects, no I/O.

    Args:
        settings: this tenant's bot config (the `bot_settings` shape). Read-only.
        state:    the CURRENT conversation's state (see `initial_state`). Read-only.
        message:  the inbound text from the user (may be empty for the "open" turn).
        media:    OPTIONAL reference to a file the customer attached to THIS
                  message, already uploaded + stored by the gateway:
                  `{"file_id", "mime_type", "name"}`. None for every text-only
                  turn (try-me and /sim always pass None). It carries no bytes —
                  only the server-minted id and metadata — so the engine stays
                  pure and never touches storage.

    Returns a dict:
        {
          "replies": [str, ...],   # what the bot says this turn (1+ messages)
          "state":   dict,         # the NEXT conversation state (caller persists it)
          "event":   None | "lead_completed" | "handed_off" | "booking",
          "lead":    dict | None,  # the collected answers, ONLY on lead_completed
        }
    """
    # Work on a private copy so we never mutate the caller's state in place.
    state = _normalize_state(state)
    text = (message or "").strip()
    media = _normalize_media(media)

    flows = _ordered_flows(settings)
    profile = settings.get("bot_profile") or {}

    # (NEW) First contact: a brand-new conversation ALWAYS opens with the greeting
    # + menu — whatever the first message says. A customer's opening "היי" must get
    # a warm welcome, NEVER "לא בטוח שהבנתי" on message #1. Afterwards we sit at the
    # menu, where an unrecognized message DOES get the gentle nudge.
    if state["phase"] == PHASE_NEW:
        return _result(
            [_greeting_and_menu(profile, flows)],
            _menu_state(),
        )

    # (a) Empty/blank message → the "open" turn: greeting + menu, sit at menu.
    #     A message that carries MEDIA is never "empty" — an attachment with no
    #     caption is a real answer to a file step, not an open turn.
    if not text and media is None:
        return _result(
            [_greeting_and_menu(profile, flows)],
            _menu_state(),
        )

    # (b) Already handed off → bot is paused; say so and answer nothing else.
    if state["phase"] == PHASE_HANDED_OFF:
        return _result([_HANDED_OFF_NOTE], state)

    # An attachment that lands exactly on a `file` step IS the answer. Its caption
    # must not be re-read as a menu/handoff keyword, or a photo captioned "תפריט"
    # would silently throw away a file the customer already uploaded.
    answering_file_step = media is not None and _current_step_type(state, flows) == "file"

    if not answering_file_step:
        # (c) Return-to-menu keyword (checked before everything else below) → menu.
        if _matches_menu_keyword(text, profile):
            return _result(
                [_greeting_and_menu(profile, flows)],
                _menu_state(),
            )

        # (d) Human-escalation keyword anywhere → hand off and stop answering.
        if _matches_handoff_keyword(text, settings):
            return _result(
                [_handoff_message(settings, flows)],
                _handed_off_state(),
                event="handed_off",
            )

    # (e) Mid-flow → validate this answer against the current step.
    if state["phase"] == PHASE_IN_FLOW:
        return _advance_in_flow(state, text, flows, media)

    # (f) At the menu → pick a flow by number or by label/keyword.
    return _advance_menu(state, text, profile, flows)


# --- (e) in-flow handling -----------------------------------------------------

def _advance_in_flow(
    state: dict, text: str, flows: list[tuple[str, dict]], media: dict | None = None
) -> dict[str, Any]:
    """Validate the user's answer for the current step, then advance or re-ask."""
    flow = _find_flow(flows, state["active_flow"])
    steps = (flow or {}).get("steps") or []

    # If the active flow vanished (config changed mid-chat), fall back to menu.
    if flow is None or not steps or state["step_index"] >= len(steps):
        return _result([_greeting_and_menu({}, flows)], _menu_state())

    step = steps[state["step_index"]]
    ok, normalized, reason = _validate_answer(step, text, media)
    if not ok:
        # A file step explains ITSELF (send an attachment / wrong kind) — a generic
        # "לא הצלחתי להבין" would leave the customer with no idea what to do. The
        # owner's own error_message still wins when they wrote one.
        error = step.get("error_message") or reason or _DEFAULT_VALIDATION_ERROR
        return _result([_with_hint(error)], state)

    # Store the normalized value under the step's machine key, then advance.
    # NOTE `normalized` is a str for every step type EXCEPT `file`, where it is
    # the file-answer OBJECT {"file_id","mime_type","name"} (or None for a skipped
    # optional file step). `collected` is JSON-serialized and encrypted whole on
    # its way into leads.answers, so a nested dict rides along unchanged.
    collected = dict(state["collected"])
    collected[step["key"]] = normalized
    next_index = state["step_index"] + 1

    if next_index >= len(steps):
        # Past the last step → the questionnaire is complete.
        completion = _completion_message(flow)
        return _result(
            [completion],
            _menu_state(),
            event="lead_completed",
            lead=collected,
        )

    # More questions remain → ask the next one (with the menu hint footer).
    next_step = steps[next_index]
    new_state = {
        "phase": PHASE_IN_FLOW,
        "active_flow": state["active_flow"],
        "step_index": next_index,
        "collected": collected,
    }
    return _result([_with_hint(_question_text(next_step))], new_state)


# --- (f) menu handling --------------------------------------------------------

def _advance_menu(
    state: dict, text: str, profile: dict, flows: list[tuple[str, dict]]
) -> dict[str, Any]:
    """At the menu, pick a flow by 1-based number or by a label/keyword match."""
    match = _pick_flow(text, flows)
    if match is None:
        # No match → gentle nudge, then re-show the menu.
        nudge = f"{_DEFAULT_NUDGE}\n\n{_menu_list(flows)}".strip()
        return _result([nudge], _menu_state())

    flow_name, flow = match
    flow_type = flow.get("flow_type")

    if flow_type == "lead":
        steps = flow.get("steps") or []
        if not steps:
            # Defensive: a "lead" flow with no steps can't run — nudge instead.
            nudge = f"{_DEFAULT_NUDGE}\n\n{_menu_list(flows)}".strip()
            return _result([nudge], _menu_state())
        first_question = _question_text(steps[0])
        new_state = {
            "phase": PHASE_IN_FLOW,
            "active_flow": flow_name,
            "step_index": 0,
            "collected": {},
        }
        return _result([_with_hint(first_question)], new_state)

    if flow_type == "human_handoff":
        return _result(
            [_handoff_message_for_flow(flow, profile)],
            _handed_off_state(),
            event="handed_off",
        )

    if flow_type == "booking":
        # Booking engine is Phase 2 — here we only echo the configured message
        # with {link} replaced by a demo placeholder, and stay at the menu.
        msg = (flow.get("message") or "").strip()
        if not msg:
            msg = f"לקביעת תור: {{link}}"
        msg = msg.replace("{link}", DEMO_BOOKING_LINK)
        return _result([msg], _menu_state(), event="booking")

    # Unknown flow_type (shouldn't happen post-validation) → nudge.
    nudge = f"{_DEFAULT_NUDGE}\n\n{_menu_list(flows)}".strip()
    return _result([nudge], _menu_state())


# --- validation (per step type) ----------------------------------------------

def _validate_answer(
    step: dict, text: str, media: dict | None = None
) -> tuple[bool, Any, str | None]:
    """Validate + normalize one answer against a step.

    Returns `(ok, normalized, reason)`:
      * `normalized` is a **str** for text/phone/email/choice, and for a `file`
        step it is the file-answer OBJECT `{"file_id","mime_type","name"}` (or
        None when an optional file step was skipped).
      * `reason` is a step-specific customer-facing error used when `ok` is False
        and the owner configured no `error_message`; None ⇒ use the generic one.

    file → phone → email → choice → text. The `file` branch comes FIRST so a file
    step can never fall through to the text fallback (which would happily accept
    the customer typing "הנה הקובץ" as if it were an attachment).
    """
    step_type = step.get("type", "text")
    required = bool(step.get("required", True))
    value = text.strip()

    if step_type == "file":
        if media is not None:
            kind = _MIME_KIND.get((media.get("mime_type") or "").lower())
            accepted = _accepted_kinds(step)
            if kind is None or kind not in accepted:
                return False, None, _FILE_WRONG_KIND_MSG + _kinds_phrase(accepted)
            return True, dict(media), None
        # No attachment on this turn — the customer typed instead.
        if not required and (not value or _is_skip_word(value)):
            # Optional step: an explicit skip (or a bare empty turn) moves on with
            # no file recorded.
            return True, None, None
        return False, None, _FILE_EXPECTED_MSG

    if step_type == "phone":
        digits = re.sub(r"\D", "", value)
        if len(digits) < _MIN_PHONE_DIGITS:
            return False, "", None
        return True, digits, None

    if step_type == "email":
        if not _EMAIL_RE.match(value):
            return False, "", None
        return True, value, None

    if step_type == "choice":
        options = step.get("options") or []
        # Accept a 1-based number...
        if value.isdigit():
            idx = int(value) - 1
            if 0 <= idx < len(options):
                return True, options[idx], None
            return False, "", None
        # ...or an exact option string (normalize to the canonical option text).
        for opt in options:
            if value == opt:
                return True, opt, None
        return False, "", None

    # type == "text" (and any unknown type): non-empty if required.
    if required and not value:
        return False, "", None
    return True, value, None


# --- file-step helpers (M16) --------------------------------------------------

def _normalize_media(media: dict | None) -> dict | None:
    """Coerce the caller's media ref into the exact answer shape, or None.

    Defensive: the ref crosses a process boundary (gateway → webhook → runtime),
    so we accept only the three known keys and require a `file_id`. Anything the
    gateway invents is dropped here rather than stored in a lead. Never logs.
    """
    if not isinstance(media, dict):
        return None
    file_id = media.get("file_id")
    if not isinstance(file_id, str) or not file_id.strip():
        return None
    mime = media.get("mime_type")
    name = media.get("name")
    return {
        "file_id": file_id.strip(),
        "mime_type": (mime or "").strip().lower() if isinstance(mime, str) else "",
        "name": name.strip()[:200] if isinstance(name, str) else "",
    }


def _accepted_kinds(step: dict) -> list[str]:
    """The kinds a file step accepts. Empty/missing `accept` ⇒ every kind."""
    accept = step.get("accept")
    kinds = [k for k in (accept or []) if isinstance(k, str) and k in _KIND_LABEL]
    return kinds or list(_KIND_LABEL.keys())


def _kinds_phrase(kinds: list[str]) -> str:
    """A Hebrew list of kind labels, e.g. 'תמונה, PDF או מצגת'."""
    labels = [_KIND_LABEL[k] for k in kinds if k in _KIND_LABEL]
    if not labels:
        return "קובץ"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + " או " + labels[-1]


def _is_skip_word(text: str) -> bool:
    """True if the WHOLE message is a skip word (optional file steps only)."""
    low = text.strip().lower()
    return any(low == w.lower() for w in _SKIP_WORDS)


def _current_step_type(state: dict, flows: list[tuple[str, dict]]) -> str | None:
    """The `type` of the step the conversation is standing on, or None."""
    if state.get("phase") != PHASE_IN_FLOW:
        return None
    flow = _find_flow(flows, state.get("active_flow"))
    steps = (flow or {}).get("steps") or []
    idx = state.get("step_index") or 0
    if not isinstance(idx, int) or idx < 0 or idx >= len(steps):
        return None
    step = steps[idx]
    return step.get("type") if isinstance(step, dict) else None


# --- flow selection helpers ---------------------------------------------------

def _ordered_flows(settings: dict) -> list[tuple[str, dict]]:
    """The flows as an ORDERED list of (name, flow) pairs (menu/number order).

    `lead_steps` is an object keyed by flow name. Python dicts preserve insertion
    order, so this is the stable order the owner built — used for both the
    numbered menu and the 1-based number selection.
    """
    lead_steps = settings.get("lead_steps") or {}
    if not isinstance(lead_steps, dict):
        return []
    return [(name, flow) for name, flow in lead_steps.items() if isinstance(flow, dict)]


def _find_flow(flows: list[tuple[str, dict]], name: str | None) -> dict | None:
    """Look up a flow object by its name within the ordered list."""
    if not name:
        return None
    for flow_name, flow in flows:
        if flow_name == name:
            return flow
    return None


def _pick_flow(text: str, flows: list[tuple[str, dict]]) -> tuple[str, dict] | None:
    """Pick a flow from a menu message: 1-based number, else label/keyword match."""
    value = text.strip()

    # An EMPTY message can never pick a flow. (Guard, not decoration: since M16 a
    # media message with no caption reaches the menu with text="" — and `"" in
    # label` is always True, which would otherwise select the first flow.)
    if not value:
        return None

    # 1-based number over the ordered flows.
    if value.isdigit():
        idx = int(value) - 1
        if 0 <= idx < len(flows):
            return flows[idx]
        return None

    # Otherwise, match the message against each flow's label (substring, both ways
    # so "תספורת" matches a label "קביעת תספורת" and vice-versa) — case-insensitive.
    low = value.lower()
    for flow_name, flow in flows:
        label = (flow.get("label") or "").strip().lower()
        if label and (label in low or low in label):
            return (flow_name, flow)
    return None


# --- text builders ------------------------------------------------------------

def _greeting_and_menu(profile: dict, flows: list[tuple[str, dict]]) -> str:
    """The greeting followed by the numbered list of flow labels."""
    greeting = (profile.get("greeting") or "").strip() or _DEFAULT_GREETING
    menu = _menu_list(flows)
    if not menu:
        return greeting
    return f"{greeting}\n\n{menu}"


def _menu_list(flows: list[tuple[str, dict]]) -> str:
    """A 1-based numbered list of the flow labels (in order)."""
    lines: list[str] = []
    for i, (flow_name, flow) in enumerate(flows, start=1):
        label = (flow.get("label") or "").strip() or flow_name
        lines.append(f"{i}. {label}")
    return "\n".join(lines)


def _question_text(step: dict) -> str:
    """A step's question, with choice options listed as a numbered sub-list."""
    question = (step.get("question") or "").strip()
    if step.get("type") == "file":
        # A customer cannot guess that this question wants an ATTACHMENT (and
        # which kinds), so the prompt says so explicitly under the owner's text.
        hint = f"📎 אפשר לצרף: {_kinds_phrase(_accepted_kinds(step))}"
        if not bool(step.get("required", True)):
            hint += '\n(אם אין לך קובץ, אפשר לכתוב "דלג")'
        return f"{question}\n{hint}" if question else hint
    if step.get("type") == "choice":
        options = step.get("options") or []
        if options:
            opts = "\n".join(f"{i}. {o}" for i, o in enumerate(options, start=1))
            return f"{question}\n{opts}" if question else opts
    return question


def _with_hint(text: str) -> str:
    """Append the mandatory menu-hint footer to an in-flow reply."""
    text = (text or "").strip()
    return f"{text}\n\n{MENU_HINT}" if text else MENU_HINT


def _completion_message(flow: dict) -> str:
    """The warm completion message for a finished lead flow."""
    # A lead flow may carry its own closing line in `message`; otherwise default.
    msg = (flow.get("message") or "").strip()
    return msg or _DEFAULT_COMPLETION


def _handoff_message(settings: dict, flows: list[tuple[str, dict]]) -> str:
    """Message for a KEYWORD-triggered handoff (the human_handoff flow if any,
    else the profile escalation_message, else a sensible default)."""
    for _name, flow in flows:
        if flow.get("flow_type") == "human_handoff":
            msg = (flow.get("message") or "").strip()
            if msg:
                return msg
            break
    profile = settings.get("bot_profile") or {}
    return (profile.get("escalation_message") or "").strip() or _DEFAULT_ESCALATION


def _handoff_message_for_flow(flow: dict, profile: dict) -> str:
    """Message when the user PICKED a human_handoff flow from the menu."""
    msg = (flow.get("message") or "").strip()
    if msg:
        return msg
    return (profile.get("escalation_message") or "").strip() or _DEFAULT_ESCALATION


# --- state + result helpers ---------------------------------------------------

def _normalize_state(state: dict | None) -> dict[str, Any]:
    """Coerce an incoming (possibly malformed) state into a safe, known shape.

    Defensive only — the endpoint already maps null/empty to `initial_state()`.
    We copy `collected` so the caller's object is never mutated.
    """
    if not isinstance(state, dict):
        return initial_state()
    phase = state.get("phase")
    if phase not in (PHASE_NEW, PHASE_MENU, PHASE_IN_FLOW, PHASE_HANDED_OFF):
        phase = PHASE_MENU
    collected = state.get("collected")
    if not isinstance(collected, dict):
        collected = {}
    step_index = state.get("step_index")
    if not isinstance(step_index, int) or step_index < 0:
        step_index = 0
    active_flow = state.get("active_flow")
    if not isinstance(active_flow, str):
        active_flow = None
    return {
        "phase": phase,
        "active_flow": active_flow,
        "step_index": step_index,
        "collected": dict(collected),
    }


def _menu_state() -> dict[str, Any]:
    return {"phase": PHASE_MENU, "active_flow": None, "step_index": 0, "collected": {}}


def _handed_off_state() -> dict[str, Any]:
    return {
        "phase": PHASE_HANDED_OFF,
        "active_flow": None,
        "step_index": 0,
        "collected": {},
    }


def _result(
    replies: list[str],
    state: dict,
    *,
    event: str | None = None,
    lead: dict | None = None,
) -> dict[str, Any]:
    """Assemble the standard turn result."""
    return {"replies": replies, "state": state, "event": event, "lead": lead}


def _matches_menu_keyword(text: str, profile: dict) -> bool:
    """True if the WHOLE message is one of the menu (return) keywords.

    Exact (whole-message) match on purpose, not substring: a return keyword like
    "0" must not fire just because a phone number "052-..." happens to contain a
    zero. (The original engine also matched the menu shortcut by equality.)
    """
    keywords = profile.get("menu_keywords") or _DEFAULT_MENU_KEYWORDS
    low = text.strip().lower()
    for kw in keywords:
        k = (kw or "").strip().lower()
        if k and low == k:
            return True
    return False


def _matches_handoff_keyword(text: str, settings: dict) -> bool:
    """True if the message contains a handoff keyword (case-insensitive substring)."""
    keywords = settings.get("handoff_keywords") or []
    low = text.lower()
    for kw in keywords:
        k = (kw or "").strip().lower()
        if k and k in low:
            return True
    return False
