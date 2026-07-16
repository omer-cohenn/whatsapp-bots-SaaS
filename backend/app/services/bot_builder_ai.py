"""AI bot-builder service — a thin, grounded Gemini proxy.

This ports the IDEA of the original `last_bo` AI-assist (build a stateful system
prompt from the current config on every turn, ask the model to return config
changes as a fenced ```json block, then smart-merge), reimplemented cleanly for
our stack and our object-keyed `lead_steps` shape.

Three hard guarantees:
  1. **Validate-at-use.** If `GEMINI_API_KEY` is unset we raise
     `GeminiNotConfiguredError` (the router maps it to HTTP 503). The app still
     boots without a key.
  2. **The LLM is untrusted.** Its proposed changes are merged into the current
     config and the RESULT is re-validated against the Pydantic `BotSettings`
     bounds (`app/models/bot_builder.py`). Out-of-bounds → rejected, nothing is
     written.
  3. **No business facts invented + no secrets/PII logged.** The system prompt
     tells the model to never invent facts; this module logs only sizes/booleans.

Injection seam for tests: `get_gemini_client()` is a module-level factory.
Tests monkeypatch it (e.g. `monkeypatch.setattr(mod, "get_gemini_client", lambda: FakeClient())`)
to run the whole flow with NO real key and NO network.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.core.config import get_settings
from app.models.bot_builder import BotSettings, Flow

# The single source of truth for the model name (CLAUDE.md / decision 0003).
GEMINI_MODEL = "gemini-3.1-flash-lite"

# Generation knobs: low temperature so config edits are deterministic/grounded,
# and a bounded output. The ceiling is generous because a one-shot "build me a
# whole bot" returns a large JSON (many flows × many steps, in Hebrew) — too low
# a cap truncates mid-JSON and the change can't be parsed.
_TEMPERATURE = 0.2
_MAX_OUTPUT_TOKENS = 8192

# Matches a fenced ```json ... ``` block (preferred), or a bare ``` ... ```.
_JSON_FENCE_RE = re.compile(r"```json\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_ANY_FENCE_RE = re.compile(r"```\s*(.*?)```", re.DOTALL)


class GeminiNotConfiguredError(Exception):
    """Raised when GEMINI_API_KEY is unset. The router maps this to HTTP 503."""


class BotBuilderError(Exception):
    """Generic AI-builder failure (model call failed). Mapped to a 502 by the router."""


# --- client factory (THE test injection seam) --------------------------------

def get_gemini_client() -> Any:
    """Return a google-genai Client bound to the configured key.

    Validate-at-use: raises `GeminiNotConfiguredError` if no key is set, so the
    app can boot without Gemini and only the AI endpoints degrade (503).

    TESTS substitute this whole function with one that returns a fake client, so
    the rest of the module can be exercised with no key and no network.
    """
    api_key = get_settings().gemini_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        raise GeminiNotConfiguredError("GEMINI_API_KEY is not configured")

    # Imported lazily so the package is only needed when AI is actually used.
    from google import genai

    return genai.Client(api_key=api_key.get_secret_value())


# --- system prompt (rebuilt from the live config on every turn) --------------

def build_system_prompt(current_config: dict[str, Any]) -> str:
    """Build a DYNAMIC, grounded Hebrew/RTL instruction for the builder model.

    The prompt states the CURRENT config (so the model edits, not invents),
    tells it to ask ONE question at a time, and to emit changes as STRICT JSON in
    a fenced ```json block matching our shapes (the 3 flow types + bot_profile).
    """
    profile = current_config.get("bot_profile") or {}
    flows = current_config.get("lead_steps") or {}
    handoff = current_config.get("handoff_keywords") or []
    is_published = bool(current_config.get("is_published"))

    # A short, readable summary of each existing flow (name + type + step count).
    if flows:
        flow_lines = []
        for name, flow in flows.items():
            ftype = (flow or {}).get("flow_type", "?")
            label = (flow or {}).get("label", "")
            steps = (flow or {}).get("steps", []) or []
            flow_lines.append(f'  • "{name}" [{ftype}] — {label} ({len(steps)} שלבים)')
        flows_summary = "\n".join(flow_lines)
    else:
        flows_summary = "  (אין מסלולים עדיין)"

    state = "\n".join(
        [
            f'שם הבוט: {profile.get("name") or "(לא הוגדר)"}',
            f'הוראות (system_prompt): {profile.get("system_prompt") or "(לא הוגדר)"}',
            f'טון: {profile.get("tone") or "(ברירת מחדל)"}',
            f'שפה: {profile.get("language") or "he"}',
            f'הודעת פתיחה: {profile.get("greeting") or "(לא הוגדרה)"}',
            f'הודעת מעבר לנציג: {profile.get("escalation_message") or "(לא הוגדרה)"}',
            f'סגירה אוטומטית (דקות): {profile.get("auto_close_minutes") or 60}',
            f'מילות תפריט: {", ".join(profile.get("menu_keywords") or []) or "(אין)"}',
            f"מסלולים ({len(flows)}):\n{flows_summary}",
            f'מילות מעבר לנציג: {", ".join(handoff) or "(אין)"}',
            f'מצב פרסום: {"פורסם (חי)" if is_published else "טיוטה (try-me)"}',
        ]
    )

    return f"""אתה "בונה הבוט" — עוזר חכם שעוזר לבעל עסק לבנות ולנהל בוט וואטסאפ, בשיחה טבעית בעברית.

המצב הנוכחי של הבוט (מעודכן בכל הודעה):
{state}

כללי התנהגות:
1. ברירת מחדל — שיחה מדורגת: שאל שאלה אחת בכל פעם, אשר בקצרה מה הבנת, ואז המשך.
2. בנייה מהירה (חשוב מאוד): אם המשתמש מתאר עסק שלם או מבקש "תבנה לי בוט ל…" עם רשימת שירותים/מסלולים — אל תשאל שאלה־שאלה. בנה את כל המערכת בבת אחת באמצעות "replaceAll": פרופיל מלא, מסלול לכל שירות שביקש, מעבר לנציג, וקביעת פגישה אם התבקש.
3. בבנייה מהירה, לכל מסלול איסוף ליד תכנן 3 עד 7 שדות הגיוניים (כלל 5±2): תמיד שם מלא וטלפון, ועוד שדות ספציפיים לשירות (לדוגמה לביטוח רכב: סוג רכב ושנת ייצור; לנסיעות לחו"ל: יעד, תאריכים ומספר נוסעים).
4. מותר ורצוי לעצב את השאלות שהבוט ישאל את הלקוחות — זו בניית המבנה. אבל אסור להמציא עובדות על העסק עצמו (מחירים, שעות, כתובות); אם חסר מידע כזה — שאל את בעל העסק.
5. כתוב תמיד עברית, חברותי, ברור וקצר.
6. כשיש שינוי — כלול אותו כ-JSON תקין בתוך גוש ```json ... ``` אחד בלבד. המשתמש לא רואה את ה-JSON, לכן אל תתאר אותו במילים ואל תדביק אותו פעמיים — רק אשר בקצרה ובשפה פשוטה מה עשית.

חשוב מאוד לגבי "greeting" (הודעת הפתיחה): זו הקדמה קצרה וחמה בעברית בלבד — משפט או שניים שמברכים את הלקוח ומסבירים מי הבוט. אסור לה לכלול את רשימת המסלולים/האפשרויות ואסור לה לכלול מספרים (1, 2, 3...) — המערכת מציגה את התפריט הממוספר באופן אוטומטי מיד אחרי הודעת הפתיחה, אז אם תוסיף אפשרויות בעצמך הן יופיעו פעמיים. דוגמה טובה: "שלום וברוכים הבאים לסוכנות הביטוח של דנה! אני כאן לעזור לך, איך אפשר לסייע?".

פורמט ה-JSON לשינויים (כל השדות אופציונליים — שלח רק את מה שמשתנה):
- פרופיל הבוט:
  {{"bot_profile": {{"name": "...", "system_prompt": "...", "tone": "...", "language": "he",
  "greeting": "הקדמה קצרה בלבד — ללא רשימת אפשרויות וללא מספרים", "escalation_message": "...", "auto_close_minutes": 60, "menu_keywords": ["תפריט"]}}}}
- מסלולים (מפתח = שם המסלול בעברית, קצר וייחודי — זה השם שבעל העסק רואה בדשבורד):
  • איסוף מידע (lead): {{"lead_steps": {{"הצעת מחיר": {{"label": "הצעת מחיר", "flow_type": "lead",
    "steps": [{{"key": "שם מלא", "question": "מה השם המלא?", "type": "text", "required": true}}]}}}}}}
  • סוגי שדה אפשריים ל-type: "text" | "phone" | "email" | "choice".
    לשדה מסוג "choice" חובה להוסיף "options": ["א", "ב"] (2 עד 12 פריטים).
  • מעבר לנציג (human_handoff): {{"lead_steps": {{"מעבר לנציג": {{"label": "דברו עם נציג",
    "flow_type": "human_handoff", "steps": []}}}}}}  ← למסלול כזה steps חייב להיות ריק.
  • קביעת תור (booking, שמור לשלב הבא): {{"lead_steps": {{"קביעת תור": {{"label": "קביעת תור",
    "flow_type": "booking", "service_name": "תספורת", "steps": []}}}}}}
- מחיקת מסלולים לפי שם: {{"deleteFlows": ["הצעת מחיר", "קביעת תור"]}}
- מילות מעבר לנציג: {{"handoff_keywords": ["נציג", "אדם"]}}
- בנייה מהירה / מחדש מאפס (לבניית בוט שלם בבת אחת) — "replaceAll": true עם bot_profile מלא (חובה name + system_prompt) וכל המסלולים ב-lead_steps. דוגמה מקוצרת:
  {{"replaceAll": true,
    "bot_profile": {{"name": "סוכנות הביטוח של דנה", "system_prompt": "...", "greeting": "שלום! הגעתם לסוכנות הביטוח של דנה, אני כאן לעזור — איך אפשר לסייע?", "escalation_message": "...", "menu_keywords": ["תפריט"]}},
    "lead_steps": {{
      "ביטוח חיים": {{"label": "ביטוח חיים", "flow_type": "lead", "steps": [
        {{"key": "שם מלא", "question": "מה השם המלא?", "type": "text", "required": true}},
        {{"key": "טלפון", "question": "מה מספר הטלפון?", "type": "phone", "required": true}},
        {{"key": "גיל", "question": "מה הגיל?", "type": "text", "required": true}}
      ]}},
      "מעבר לנציג": {{"label": "מעבר לנציג", "flow_type": "human_handoff", "steps": []}},
      "קביעת פגישה": {{"label": "קביעת פגישה", "flow_type": "booking", "service_name": "פגישת ייעוץ", "steps": []}}
    }}}}

כללים ל-JSON:
- שמות מסלולים (המפתחות ב-lead_steps) ומפתחות שדות ("key") — תמיד בעברית פשוטה וקצרה,
  כי הם מוצגים לבעל העסק בדשבורד (למשל "הצעת מחיר", "שם מלא"). מותר: אותיות עברית/אנגלית
  קטנות, ספרות, רווח וקו תחתון, עד 40 תווים. אל תשתמש באנגלית אלא אם בעל העסק ביקש.
- אל תכלול לעולם business_id או מפתחות סודיים.
- אל תכלול מפתח "knowledge" — הוא שמור לשלב מאוחר יותר ולא נתמך כעת.
- אם אין שינוי בהודעה הזו — אל תכלול גוש JSON כלל."""


# --- extract + merge (the untrusted-output handling) -------------------------

def extract_changes(reply_text: str) -> dict[str, Any] | None:
    """Pull the fenced ```json changes block from the model reply, if present.

    Returns the parsed dict, or None when there is no (valid) JSON block — a
    plain conversational turn with no config change. Never raises on bad JSON;
    a malformed block is treated as "no changes" (the LLM output is untrusted).
    """
    if not reply_text:
        return None
    match = _JSON_FENCE_RE.search(reply_text) or _ANY_FENCE_RE.search(reply_text)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    # Only an object of changes is meaningful; ignore arrays/scalars.
    return parsed if isinstance(parsed, dict) else None


def clean_reply_text(reply_text: str) -> str:
    """Strip the fenced JSON change block from a reply, for DISPLAY to the owner.

    The model embeds its config change as a ```json ... ``` block. The owner
    should never see raw JSON — only plain language. We remove every fenced block
    and tidy the leftover blank lines.
    """
    if not reply_text:
        return ""
    text = _JSON_FENCE_RE.sub("", reply_text)
    text = _ANY_FENCE_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def summarize_changes(changes: dict[str, Any], merged: dict[str, Any]) -> str:
    """A short, plain-Hebrew, JSON-free description of what an applied change did.

    `changes` is the model's raw delta (what it asked to change); `merged` is the
    validated result (what is actually now in the config). We describe from the
    delta but verify flow names against `merged`, so we never claim a flow that
    was salvaged away. Returns "" when there's nothing meaningful to announce.
    """
    if not isinstance(changes, dict):
        return ""

    parts: list[str] = []
    merged_flows = merged.get("lead_steps") or {}
    full_reset = bool(changes.get("deleteAll") or changes.get("replaceAll"))

    if full_reset:
        labels = [
            (flow or {}).get("label") or name for name, flow in merged_flows.items()
        ]
        if labels:
            parts.append(
                f"בניתי את הבוט מחדש עם {len(labels)} מסלולים: {', '.join(labels)}"
            )
        else:
            parts.append("בניתי את הבוט מחדש")
    else:
        if isinstance(changes.get("bot_profile"), dict) and changes["bot_profile"]:
            parts.append("עדכנתי את הגדרות הבוט")
        incoming = changes.get("lead_steps")
        if isinstance(incoming, dict):
            for raw_name in incoming:
                name = _slugify_key(str(raw_name))
                if name in merged_flows:
                    label = (merged_flows[name] or {}).get("label") or name
                    parts.append(f"הוספתי/עדכנתי את המסלול '{label}'")
        deleted = changes.get("deleteFlows")
        if isinstance(deleted, list) and deleted:
            parts.append(
                "מחקתי מסלול אחד"
                if len(deleted) == 1
                else f"מחקתי {len(deleted)} מסלולים"
            )
        if isinstance(changes.get("handoff_keywords"), list):
            parts.append("עדכנתי את מילות המעבר לנציג")

    if not parts:
        return ""
    return "✅ " + "; ".join(parts) + "."


def merge_changes(
    current: dict[str, Any], changes: dict[str, Any]
) -> tuple[BotSettings, dict[str, Any]]:
    """Smart-merge `changes` (untrusted) into `current`, then VALIDATE the result.

    Adapted to our object-keyed `lead_steps`:
      * `deleteAll` / `replaceAll` → reset flows (and apply any profile/keywords
        also present in the same change object). A full rebuild.
      * `lead_steps` (without reset) → per-flow upsert: each named flow REPLACES
        the existing flow of that name, or is ADDED if new.
      * `deleteFlows` → remove the named flows.
      * `bot_profile` → shallow field merge over the current profile.
      * `handoff_keywords` / `is_published` → direct overwrite.

    Returns `(validated_settings, merged_dict)`. Raises `ValidationError` if the
    merged result violates the Pydantic bounds — the caller must NOT persist then.
    """
    if not isinstance(changes, dict):
        raise ValueError("changes must be a JSON object")

    # Work on copies so we never mutate the caller's current config.
    merged: dict[str, Any] = {
        "bot_profile": dict(current.get("bot_profile") or {}),
        "lead_steps": dict(current.get("lead_steps") or {}),
        "handoff_keywords": list(current.get("handoff_keywords") or []),
        "is_published": bool(current.get("is_published")),
    }

    full_reset = bool(changes.get("deleteAll") or changes.get("replaceAll"))

    # --- bot_profile: shallow field merge (drop unknown/reserved keys) --------
    if isinstance(changes.get("bot_profile"), dict):
        incoming_profile = _strip_unknown(
            changes["bot_profile"], _ALLOWED_PROFILE_KEYS
        )
        merged["bot_profile"] = {**merged["bot_profile"], **incoming_profile}

    # --- lead_steps: full reset OR per-flow upsert ---------------------------
    incoming_flows = changes.get("lead_steps")
    if full_reset:
        # On a reset, flows become exactly what was sent (or empty if none).
        merged["lead_steps"] = _normalize_flows(incoming_flows or {})
    elif isinstance(incoming_flows, dict):
        normalized = _normalize_flows(incoming_flows)
        # Upsert by flow name: replace existing, add new.
        merged["lead_steps"].update(normalized)

    # --- deleteFlows: remove named flows -------------------------------------
    to_delete = changes.get("deleteFlows")
    if isinstance(to_delete, list):
        for name in to_delete:
            merged["lead_steps"].pop(name, None)

    # --- handoff_keywords / is_published: direct overwrite -------------------
    if isinstance(changes.get("handoff_keywords"), list):
        merged["handoff_keywords"] = changes["handoff_keywords"]
    if isinstance(changes.get("is_published"), bool):
        merged["is_published"] = changes["is_published"]

    # On a full rebuild ("build me a whole bot"), fill the required profile fields
    # if the model omitted them, so a big one-shot build never fails validation
    # over a missing name/prompt. This is generic boilerplate behavior text — NOT
    # invented business facts (no prices/hours/addresses).
    if full_reset:
        prof = merged["bot_profile"]
        if not (prof.get("name") or "").strip():
            prof["name"] = "העסק שלי"
        if not (prof.get("system_prompt") or "").strip():
            prof["system_prompt"] = (
                f"את/ה העוזר/ת הווירטואלי/ת של {prof['name']}. ענה/י בעברית "
                "באדיבות ובמקצועיות. אל תמציא/י מידע — כשחסר מידע או כשהלקוח "
                "מבקש, הצע/י מעבר לנציג אנושי."
            )

    # THE GATE: validate the merged result against the Pydantic bounds. If the
    # LLM proposed something out of bounds, this raises and the caller rejects.
    # EXCEPTION — on a full rebuild we SALVAGE: drop only the invalid flow(s) so a
    # single bad field can't lose an entire one-shot build, then re-validate.
    # Incremental edits stay strictly all-or-nothing (no partial surprise apply).
    try:
        validated = BotSettings.model_validate(merged)
    except ValidationError:
        if not full_reset:
            raise
        merged["lead_steps"] = _salvage_flows(merged.get("lead_steps") or {})
        validated = BotSettings.model_validate(merged)
    return validated, validated.model_dump(mode="json")


# --- orchestration -----------------------------------------------------------

async def generate_reply(message: str, current_config: dict[str, Any]) -> str:
    """Send one builder turn to Gemini and return the raw reply text.

    Stateless per call (the system prompt carries the current config), matching
    the original design. Raises `GeminiNotConfiguredError` (→503) with no key, or
    `BotBuilderError` (→502) if the model call fails. Never logs the message.
    """
    client = get_gemini_client()  # raises GeminiNotConfiguredError if unset
    system_prompt = build_system_prompt(current_config)

    # Lazy import so the SDK types are only needed when AI is actually used.
    from google.genai import types

    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Content(role="user", parts=[types.Part.from_text(text=message)])
            ],
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=_TEMPERATURE,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
            ),
        )
    except GeminiNotConfiguredError:
        raise
    except Exception as exc:  # noqa: BLE001 — never leak provider internals/PII
        raise BotBuilderError("the AI model call failed") from exc

    return getattr(response, "text", None) or ""


# --- small helpers -----------------------------------------------------------

# Keys the model is allowed to set on bot_profile (everything else is stripped,
# including the reserved "knowledge"). Mirrors BotProfile's fields.
_ALLOWED_PROFILE_KEYS = {
    "name",
    "system_prompt",
    "tone",
    "language",
    "greeting",
    "escalation_message",
    "auto_close_minutes",
    "menu_keywords",
}

# Keys allowed on each flow object (unknown keys stripped before validation).
_ALLOWED_FLOW_KEYS = {"label", "flow_type", "steps", "service_name"}
_ALLOWED_STEP_KEYS = {
    "key",
    "question",
    "type",
    "required",
    "validate",
    "options",
    "error_message",
}


def _strip_unknown(obj: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    """Keep only allowed keys from a dict (forgive LLM-invented fields)."""
    return {k: v for k, v in obj.items() if k in allowed}


# Allowed key characters mirror KEY_PATTERN in models: a-z, 0-9, _, Hebrew, space.
_KEY_BAD_RE = re.compile(r"[^a-z0-9_֐-׿ ]+")


def _slugify_key(name: str) -> str:
    """Coerce an LLM-proposed flow/step key into the allowed key pattern.

    The key is just an internal identifier. The model sometimes returns camelCase
    or hyphens (e.g. "lifeInsurance", "pet-insurance"); rather than lose a whole
    one-shot build to one bad key, we normalize it (lowercase, junk → underscore)
    so it passes the same pattern the server enforces.
    """
    s = (name or "").strip().lower()
    s = _KEY_BAD_RE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("_ ")
    return s[:40] or "flow"


def _normalize_steps(steps: list[Any]) -> list[dict[str, Any]]:
    """Strip unknown keys + slugify step keys, keeping them unique within the flow."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        clean = _strip_unknown(step, _ALLOWED_STEP_KEYS)
        key = clean.get("key")
        if isinstance(key, str) and key.strip():
            slug = _slugify_key(key)
            if slug in seen:  # keep step keys unique within the flow
                i = 2
                while f"{slug}_{i}" in seen:
                    i += 1
                slug = f"{slug}_{i}"
            clean["key"] = slug
            seen.add(slug)
        out.append(clean)
    return out


def _normalize_flows(flows: Any) -> dict[str, Any]:
    """Strip unknown keys + slugify keys so Pydantic (extra='forbid') accepts them.

    We forgive extra keys the LLM may add and fix invalid keys (normalize, don't
    fail) — the real bounds are still enforced by `BotSettings.model_validate`.
    """
    if not isinstance(flows, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for raw_name, flow in flows.items():
        if not isinstance(flow, dict):
            continue
        name = _slugify_key(str(raw_name))
        if name in cleaned:  # de-dupe collided flow names
            i = 2
            while f"{name}_{i}" in cleaned:
                i += 1
            name = f"{name}_{i}"
        flow_clean = _strip_unknown(flow, _ALLOWED_FLOW_KEYS)
        steps = flow_clean.get("steps")
        if isinstance(steps, list):
            flow_clean["steps"] = _normalize_steps(steps)
        cleaned[name] = flow_clean
    return cleaned


def _salvage_flows(flows: dict[str, Any]) -> dict[str, Any]:
    """Keep only the flows that individually pass validation; drop the invalid ones.

    Used ONLY on a full rebuild so one malformed flow can't sink a whole one-shot
    build. Each surviving flow is guaranteed to satisfy the Flow model.
    """
    good: dict[str, Any] = {}
    for name, flow in flows.items():
        try:
            Flow.model_validate(flow)
        except ValidationError:
            continue
        good[name] = flow
    return good
