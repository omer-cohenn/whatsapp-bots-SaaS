# מחברת הלידים — חיפוש חופשי: כלל ההתאמה המשותף לשרת ולדפדפן
"""The ONE keyword-match rule for a lead — shared by the server and the browser.

    ⚠️  THIS FUNCTION HAS A TWIN IN TYPESCRIPT.
        Frontend: `frontend/src/dashboard/leadSearch.ts` (`leadMatches`).
        The dashboard filters the leads list client-side with the TS twin; the
        Excel export (`GET /api/leads/export?q=...`) filters with THIS one. If
        the two ever drift, the file the owner downloads stops matching the rows
        they can see on screen — so ANY change here must be mirrored there, and
        vice versa.

The rule (verbatim, so both implementations can be read against it):

  1. Normalize the query: `strip()` then `lower()`.
  2. An empty / whitespace-only query matches EVERYTHING → return True.
  3. The lead matches when the normalized query appears as a case-insensitive
     SUBSTRING of any of these haystacks, each normalized the same way:
       * `contact_name`, `phone`, `lead_name`, `outcome_note`  (None → skipped)
       * every KEY of `answers`
       * every VALUE of `answers`, where a value is one of:
           - a string      → the string itself
           - a file answer → its `name` (skipped when missing/empty)
           - a list        → each element handled by the same two rules

Deliberately dependency-free and pure (a plain dict in, a bool out) so it is
trivially testable and cannot become a place where PII leaks: nothing here logs,
stores, or transmits anything.
"""

from __future__ import annotations

from typing import Any

# The plain-text fields (outside `answers`) that participate in the search.
# Mirrors the fields the lead cards actually render to the owner.
_TEXT_FIELDS = ("contact_name", "phone", "lead_name", "outcome_note")


def _norm(value: Any) -> str:
    """Normalize one haystack the same way the query is normalized.

    Non-strings collapse to "" rather than being coerced with `str()` — an
    accidental `str(dict)` would let the raw `{'file_id': ...}` repr become
    searchable, which is not the documented rule.
    """
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def _haystacks_for_value(value: Any) -> list[str]:
    """Every searchable string carried by ONE answer value.

    A string answer contributes itself; a file answer contributes its `name`;
    a list contributes the union of its elements handled the same way. Anything
    else contributes nothing.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        # A file answer: {"file_id", "mime_type", "name"}. Only the display name
        # is searchable — file_id / mime_type are plumbing, not content.
        name = value.get("name")
        return [name] if isinstance(name, str) and name else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_haystacks_for_value(item))
        return out
    return []


def lead_matches(lead: dict, query: str) -> bool:
    """Does this lead match the owner's free-text query? See the module docstring.

    `lead` is one row as returned by `leads.list_leads` (already decrypted).
    An empty or whitespace-only `query` (or None) matches every lead.
    """
    needle = (query or "").strip().lower()
    if not needle:
        return True

    for field in _TEXT_FIELDS:
        if needle in _norm(lead.get(field)):
            return True

    answers = lead.get("answers")
    if isinstance(answers, dict):
        for key, value in answers.items():
            if needle in _norm(key):
                return True
            for hay in _haystacks_for_value(value):
                if needle in _norm(hay):
                    return True

    return False
