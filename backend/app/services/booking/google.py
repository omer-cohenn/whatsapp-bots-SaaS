# לוגיקת התורים — תפר הסנכרון ל‑Google Calendar (no-op עד שנרשם hook)
"""Google-calendar sync seam for bookings (M11).

A decoupled module-level hook so the booking core has ZERO Google import. The
Google agent registers a real implementation via `register_google_hook`; until
then every call is a no-op. A hook failure is swallowed + logged generically so
Google can NEVER break a booking (decision 0011: degrade gracefully). Moved
VERBATIM from the old single-file `booking.py` — no logic change.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from app.core.logging import get_logger

log = get_logger("app.services.booking")

# The action that just happened to a booking, passed to the hook so a single
# implementation can branch (create vs update vs delete the calendar event).
GoogleHookAction = str  # "created" | "rescheduled" | "cancelled"

# Signature the Google agent implements + registers. It receives the tenant id
# (already verified) and the booking id, NOT a connection — Google sync runs
# AFTER the booking transaction commits, opening its own tenant_connection as
# needed. It must never raise (failures degrade gracefully); we also guard it.
GoogleHook = Callable[[str, str, GoogleHookAction], Awaitable[None]]

_google_hook: GoogleHook | None = None


def register_google_hook(hook: GoogleHook | None) -> None:
    """Register (or clear) the Google-calendar sync hook. Called by the Google agent.

    Passing None disables it (the default state). Keeping this a module-level
    registration keeps the booking core free of any Google import/dependency.
    """
    global _google_hook
    _google_hook = hook


async def run_google_hook(business_id: str, booking_id: str, action: GoogleHookAction) -> None:
    """Fire the Google hook for a committed booking mutation — best-effort.

    Called AFTER the booking row is committed. If no hook is registered this is a
    no-op. Any error is swallowed + logged generically so Google can NEVER break
    a booking (decision 0011). Never logs PII/tokens.
    """
    hook = _google_hook
    if hook is None:
        return
    try:
        await hook(business_id, booking_id, action)
    except Exception:  # noqa: BLE001 — degrade gracefully; no str(e)/PII
        log.warning("google booking hook failed", extra={"action": action})
