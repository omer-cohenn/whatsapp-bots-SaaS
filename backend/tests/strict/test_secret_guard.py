"""CI secret/PII guard (runtime slice).

Cheap, always-on assertions that secrets stay out of stringified objects and
that decryption never degrades to plaintext. The static repo scan (grep for
hardcoded keys / DB URLs in source) is wired separately in `make test`; this is
the runtime half that travels with the app.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.crypto import DecryptionError, decrypt_pii


def test_settings_do_not_leak_secrets_when_stringified():
    s = get_settings()
    secret = s.pii_data_key.get_secret_value()
    # Pydantic SecretStr must mask in repr/str — printing settings can't leak it.
    assert secret not in repr(s)
    assert secret not in str(s)
    assert "**" in repr(s.pii_data_key)  # SecretStr masks as '**********'


def test_decrypt_never_returns_input_on_failure():
    # Garbage in must RAISE, never echo back (the old silent-fallback bug).
    try:
        decrypt_pii("not-a-real-token")
    except DecryptionError:
        return
    raise AssertionError("decrypt_pii returned instead of raising on bad input")
