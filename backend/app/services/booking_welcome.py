"""AI welcome-message generator for the public booking page (M11.1).

A tiny, focused Gemini proxy: given a business name + its active service names
(and an optional tone), produce a SHORT warm Hebrew greeting (2-3 sentences) the
owner can show atop the public booking page. It deliberately mirrors
`bot_builder_ai`'s client/model/validate-at-use plumbing but uses a DEDICATED
prompt (NOT the bot-builder system prompt) and returns plain text — no JSON,
no config merge.

Hard guarantees (same as bot_builder_ai):
  1. **Validate-at-use.** No `GEMINI_API_KEY` → `WelcomeNotConfiguredError`
     (router → 503). The app boots fine without a key.
  2. **No secrets/PII logged.** We never log the key, the prompt, or the output;
     only generic failures.
  3. **Grounded.** The prompt is told to use ONLY the given name + services and
     to invent NO facts (no prices, hours, promises).

Test seam: `get_gemini_client()` is a module-level factory tests monkeypatch to
run with no key + no network (identical pattern to bot_builder_ai).
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings

# Single source of truth for the model name (CLAUDE.md / decision 0003). Reuse the
# bot-builder constant so there is exactly one place to change it.
from app.services.bot_builder_ai import GEMINI_MODEL

# A welcome line is short, so keep the budget tight + a little warmth (slightly
# higher temperature than config edits, but still grounded).
_TEMPERATURE = 0.6
_MAX_OUTPUT_TOKENS = 256

# Cap how many service names we put in the prompt (keeps it short + bounded).
_MAX_SERVICES_IN_PROMPT = 12


class WelcomeNotConfiguredError(Exception):
    """Raised when GEMINI_API_KEY is unset. The router maps this to HTTP 503."""


class WelcomeGenerateError(Exception):
    """Generic generator failure (model call failed). Mapped to a 502 by the router."""


# --- client factory (THE test injection seam) --------------------------------

def get_gemini_client() -> Any:
    """Return a google-genai Client bound to the configured key (validate-at-use).

    Raises `WelcomeNotConfiguredError` if no key is set, so the app boots without
    Gemini and only this endpoint degrades (503). TESTS replace this whole
    function with one returning a fake client (no key, no network).
    """
    api_key = get_settings().gemini_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        raise WelcomeNotConfiguredError("GEMINI_API_KEY is not configured")

    # Imported lazily so the package is only needed when AI is actually used.
    from google import genai

    return genai.Client(api_key=api_key.get_secret_value())


# --- prompt (dedicated; NOT the bot-builder prompt) --------------------------

def build_welcome_prompt(
    business_name: str, service_names: list[str], tone: str | None
) -> str:
    """Build the DEDICATED Hebrew instruction for the welcome generator.

    Grounded: it may use ONLY the provided business name + service names, must
    invent no facts (prices/hours/promises), and must return 2-3 warm sentences
    of PLAIN text (no markdown, no quotes, no JSON).
    """
    name = (business_name or "").strip() or "העסק"
    services = [s.strip() for s in service_names if s and s.strip()][:_MAX_SERVICES_IN_PROMPT]
    services_line = ", ".join(services) if services else "(לא צוינו שירותים)"
    tone_clean = (tone or "").strip()
    tone_line = f"טון רצוי: {tone_clean}." if tone_clean else "טון רצוי: חם ומזמין."

    return f"""אתה כותב/ת שיווקי/ת בעברית. כתוב/כתבי הודעת פתיחה קצרה וחמה לעמוד קביעת התורים הציבורי של העסק.

שם העסק: {name}
השירותים שמוצעים: {services_line}
{tone_line}

כללים:
- 2 עד 3 משפטים בלבד, קצרים וברורים.
- עברית טבעית וחמה, פונה ישירות ללקוח (לשון יחיד).
- הזמן/הזמיני את הלקוח לקבוע תור.
- השתמש/י אך ורק בשם העסק ובשירותים שניתנו. אל תמציא/י עובדות (מחירים, שעות, הבטחות, פרטי קשר).
- החזר/י טקסט רגיל בלבד — בלי כותרות, בלי מרכאות, בלי סימוני Markdown, בלי אימוג'ים מוגזמים."""


# --- orchestration -----------------------------------------------------------

async def generate_welcome(
    business_name: str, service_names: list[str], tone: str | None
) -> str:
    """Ask Gemini for a short welcome message and return the plain text.

    Raises `WelcomeNotConfiguredError` (→503) with no key, or
    `WelcomeGenerateError` (→502) if the model call fails / returns nothing.
    Never logs the key, prompt, or output.
    """
    client = get_gemini_client()  # raises WelcomeNotConfiguredError if unset
    prompt = build_welcome_prompt(business_name, service_names, tone)

    # Lazy import so the SDK types are only needed when AI is actually used.
    from google.genai import types

    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=types.GenerateContentConfig(
                temperature=_TEMPERATURE,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
            ),
        )
    except WelcomeNotConfiguredError:
        raise
    except Exception as exc:  # noqa: BLE001 — never leak provider internals/PII
        raise WelcomeGenerateError("the AI model call failed") from exc

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise WelcomeGenerateError("the AI model returned no text")
    return text
