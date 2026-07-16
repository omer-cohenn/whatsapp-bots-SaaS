"""Frontend secret guard — no server secret may reach the browser bundle.

The browser is UNTRUSTED: it must only ever hold a same-origin session cookie,
never a service secret. This guard greps the frontend SOURCE (and the built
bundle, if one exists) for the fingerprints of every server-side secret and
FAILS if any appears. The frontend is already clean today — this locks that in
so a future regression (e.g. someone importing a key into a component, or a
build inlining an env var) trips the CI gate instead of shipping.

Runs on the host / full-checkout CI. When the frontend tree isn't present (e.g.
inside the minimal backend container), it skips with a clear message rather than
false-failing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Fingerprints that must NEVER appear in anything shipped to the browser:
#   - the server env-var NAMES (their presence means a secret was wired in)
#   - Google's OAuth client-secret prefix (GOCSPX-) and API-key prefix (AIza)
#   - a Postgres DSN, and the session signing secret's name
_SECRET_PATTERNS = [
    "GATEWAY_API_TOKEN",
    "WA_CRED_KEK",
    "PII_DATA_KEY",
    "PHONE_HMAC_KEY",
    "GOCSPX-",
    "AIza",
    "postgresql://",
    "SESSION_SECRET",
]

# Only scan text-ish files; skip images/fonts/maps binaries.
_TEXT_SUFFIXES = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".html",
    ".css", ".scss", ".md", ".txt", ".env", ".map",
}


def _find_frontend_dir() -> Path | None:
    """Walk up from this file to the repo root and return frontend/ if present."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "frontend"
        if (candidate / "package.json").is_file():
            return candidate
    return None


def _scan_targets(frontend: Path) -> list[Path]:
    """Files to scan: everything under src/, plus dist/ if a build exists."""
    roots = [frontend / "src"]
    dist = frontend / "dist"
    if dist.is_dir():
        roots.append(dist)
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES:
                files.append(path)
    return files


def test_no_server_secrets_in_frontend():
    frontend = _find_frontend_dir()
    if frontend is None:
        pytest.skip("frontend/ not available in this environment")

    files = _scan_targets(frontend)
    assert files, "frontend scan found no files — check the repo layout"

    pattern = re.compile("|".join(re.escape(p) for p in _SECRET_PATTERNS))
    offenders: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                # Report the location + which fingerprint — but NOT the whole line
                # (which could itself contain the secret we're guarding against).
                hit = pattern.search(line).group(0)
                offenders.append(f"{path}:{lineno} matched {hit!r}")

    assert not offenders, (
        "server secret fingerprint(s) found in the frontend bundle:\n  "
        + "\n  ".join(offenders)
    )
