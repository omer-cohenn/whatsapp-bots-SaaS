# שומר הדמו — session של דמו רשאי לקרוא בלבד, כל כתיבה נחסמת
"""Read-only enforcement for public demo sessions.

The login screen offers "המשך בתור דמו", which mints a session with NO
credential behind it — anyone on the internet can press it. Those visitors are
meant to click around the real product freely, so the FRONTEND fakes their edits
in local state and the UI feels alive.

That faking is UX, not security. A visitor can open DevTools and call the API
directly with their own demo cookie, so the browser cannot be the boundary. This
middleware is the boundary: for a session flagged `is_demo`, every mutating
request to /api is refused before it reaches a route.

WHY A MIDDLEWARE AND NOT A DEPENDENCY: a dependency has to be remembered on
every new route, and the one someone forgets is the one that lets a stranger
delete the demo's leads. A middleware is deny-by-default — a route added next
year is covered without anyone thinking about it.

KNOWN GAP, stated rather than hidden: a few GET routes have write side effects —
opening a conversation resets its unread counter, and GET /api/booking/page
bootstraps the settings row and its slug on first read. Those still run for a
demo visitor, so demo data can drift slightly through reads alone. They are
harmless (a counter and a self-healing row) and blocking them would break the
demo, so they are deliberately allowed. The reset script is what restores a
pristine demo.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger
from app.services.auth import SESSION_COOKIE_NAME, load_session

log = get_logger("app.demo_guard")

# Anything that can change state. GET/HEAD/OPTIONS pass through.
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# POSTs that persist NOTHING, so blocking them only breaks the demo without
# protecting anything. Each entry needs that property verified in the route, not
# assumed — a path added here on a hunch is how the guard springs a leak.
#
#   /api/bot/tryme — "one PURE engine turn; no persistence (sandbox)" per
#   app/api/bot_builder.py. It runs bot_engine.advance(), a pure function, and
#   hands the next state back to the CLIENT to keep. Nothing is written, so a
#   demo visitor trying the bot is exactly as safe as one reading a page.
#
# Deliberately NOT here: the AI builder endpoints. They persist a conversation
# AND spend money on a Gemini call per request, so leaving them blocked protects
# the bill from anonymous visitors as much as it protects the data.
_READ_ONLY_POSTS = frozenset({"/api/bot/tryme"})

# Shown to the visitor. Deliberately friendly: in a demo this is expected
# behaviour, not an error the user did something wrong to cause.
_MESSAGE = "זהו חשבון דמו לצפייה בלבד — השינויים לא נשמרים."


class DemoReadOnlyMiddleware(BaseHTTPMiddleware):
    """Refuse writes from demo sessions."""

    async def dispatch(self, request: Request, call_next):
        if request.method not in _WRITE_METHODS:
            return await call_next(request)

        # Only /api is guarded. /auth/* must stay writable or a demo visitor
        # could never log out.
        if not request.url.path.startswith("/api"):
            return await call_next(request)

        if request.url.path.rstrip("/") in _READ_ONLY_POSTS:
            return await call_next(request)

        sid = request.cookies.get(SESSION_COOKIE_NAME)
        if not sid:
            return await call_next(request)

        redis = getattr(request.app.state, "redis", None)
        if redis is None:  # pragma: no cover — app always sets it
            return await call_next(request)

        session = await load_session(redis, sid)
        # `is_demo` comes from the Redis payload written at login, never from the
        # request — a client cannot promote or demote itself.
        if not session or not session.get("is_demo"):
            return await call_next(request)

        # 403, not 401: the session is valid, the ACTION is not. A 401 would make
        # the frontend think the login expired and bounce the visitor out.
        log.info(
            "demo write blocked",
            extra={"method": request.method, "path": request.url.path},
        )
        return JSONResponse(status_code=403, content={"detail": _MESSAGE})
