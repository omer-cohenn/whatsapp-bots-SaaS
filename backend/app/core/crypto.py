"""Application-layer encryption — the M2 "fail-loud" rebuild.

This replaces the old `last_bo/bot/crypto.py`. We KEEP the proven idea (Fernet
authenticated encryption of PII fields) and DELETE its one dangerous habit: the
old `decrypt()` did `except Exception: return value` — silently handing back the
ciphertext (or garbage) when the key was wrong. That masked key-rotation and
migration bugs (security issue M2). Here, **decrypt failure raises** — there is
no plaintext fallback, ever.

Two separate key domains (different blast radius):
  1. PII data key  → leads.phone / contact_name / answers,
                     whatsapp_connections.phone_number.
  2. Crown KEK     → whatsapp_credentials.auth_state, via ENVELOPE encryption
                     (a fresh per-row data key wrapped by the KEK). A stolen DB
                     dump is useless without the KEK.
Plus a keyed HMAC for deterministic phone lookups (customer_phone_hash).

Keys come from the settings (env in dev; a secret manager / KMS later — same
interface). Every encrypted value is stamped with a `key_version` so rotation is
possible and decryption selects the right key instead of guessing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

# Only one key version exists in dev. When we rotate, add the new key here and
# bump CURRENT_KEY_VERSION; old rows still decrypt under their stored version.
CURRENT_KEY_VERSION = 1


class DecryptionError(Exception):
    """Raised LOUD when decryption fails. Never swallowed, never falls back."""


# --- key access (the seam a real secret manager / KMS slots into later) ------

def _pii_fernet(key_version: int = CURRENT_KEY_VERSION) -> Fernet:
    if key_version != CURRENT_KEY_VERSION:
        raise DecryptionError(f"unknown PII key_version={key_version}")
    return Fernet(get_settings().pii_data_key.get_secret_value().encode())


def _kek_fernet(key_version: int = CURRENT_KEY_VERSION) -> Fernet:
    if key_version != CURRENT_KEY_VERSION:
        raise DecryptionError(f"unknown crown KEK key_version={key_version}")
    return Fernet(get_settings().wa_cred_kek.get_secret_value().encode())


def _hmac_key() -> bytes:
    return get_settings().phone_hmac_key.get_secret_value().encode()


# --- PII field encryption (strings) ------------------------------------------

def encrypt_pii(plaintext: str | None) -> str | None:
    """Encrypt a single PII string. None/empty pass through unchanged."""
    if not plaintext:
        return plaintext
    return _pii_fernet().encrypt(plaintext.encode()).decode()


def decrypt_pii(token: str | None, key_version: int = CURRENT_KEY_VERSION) -> str | None:
    """Decrypt a PII string. Raises DecryptionError on ANY failure (no fallback)."""
    if not token:
        return token
    try:
        return _pii_fernet(key_version).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, TypeError) as exc:
        # Loud: caller sees the failure; the plaintext is NEVER guessed/returned.
        raise DecryptionError("PII decryption failed") from exc


# --- answers blob (a dict, stored as {"_": "<ciphertext>"}) ------------------

def encrypt_answers(answers: dict[str, Any]) -> dict[str, str]:
    """Encrypt the answers dict as a single blob, matching the {"_": ct} shape."""
    payload = json.dumps(answers, ensure_ascii=False, separators=(",", ":"))
    return {"_": _pii_fernet().encrypt(payload.encode()).decode()}


def decrypt_answers(blob: dict[str, Any] | None,
                    key_version: int = CURRENT_KEY_VERSION) -> dict[str, Any]:
    """Decrypt the {"_": ct} answers blob back to a dict. Raises on failure."""
    if not blob:
        return {}
    if "_" not in blob:
        # A blob without our sentinel is NOT silently trusted as plaintext.
        raise DecryptionError("answers blob is not in the expected encrypted shape")
    try:
        raw = _pii_fernet(key_version).decrypt(str(blob["_"]).encode())
        return json.loads(raw.decode())
    except (InvalidToken, ValueError, TypeError) as exc:
        raise DecryptionError("answers decryption failed") from exc


# --- crown jewel: envelope encryption for the Baileys auth_state -------------

def encrypt_auth_state(plaintext: bytes) -> bytes:
    """Envelope-encrypt the Baileys auth state → ciphertext bytes for `bytea`.

    A fresh data key (DEK) encrypts the payload; the KEK wraps the DEK. We store
    both together as a small JSON envelope. The KEK never leaves the secret
    manager; the DB only ever holds wrapped material.
    """
    dek = Fernet.generate_key()
    ciphertext = Fernet(dek).encrypt(plaintext)
    wrapped_dek = _kek_fernet().encrypt(dek)
    envelope = {"dek": wrapped_dek.decode(), "ct": ciphertext.decode()}
    return json.dumps(envelope).encode()


def decrypt_auth_state(blob: bytes | None,
                       key_version: int = CURRENT_KEY_VERSION) -> bytes:
    """Reverse encrypt_auth_state. Raises DecryptionError on ANY failure."""
    if not blob:
        raise DecryptionError("auth_state is empty")
    try:
        envelope = json.loads(bytes(blob).decode())
        dek = _kek_fernet(key_version).decrypt(envelope["dek"].encode())
        return Fernet(dek).decrypt(envelope["ct"].encode())
    except (InvalidToken, ValueError, TypeError, KeyError) as exc:
        raise DecryptionError("auth_state decryption failed") from exc


# --- M16: envelope encryption with a SPLIT envelope (bytes → object storage) -
#
# `encrypt_auth_state` above stores the wrapped DEK and the ciphertext TOGETHER
# in one JSON envelope, because both halves live in the same `bytea` column.
# For customer files (M16) the two halves live in DIFFERENT places on purpose:
#   * the ciphertext goes to Cloudflare R2 (object storage),
#   * the wrapped DEK goes to `lead_files.wrapped_dek` (Postgres).
# A stolen bucket has no keys; a stolen DB dump has no bytes. So we expose the
# wrap/unwrap step on its own instead of a combined envelope. Same KEK, same
# key_version stamping, same fail-LOUD contract.

def wrap_new_dek() -> tuple[bytes, str]:
    """Mint a fresh data key → (raw_dek, wrapped_dek_for_storage).

    The RAW dek is used once, in-process, to encrypt one payload and is then
    dropped. Only the WRAPPED form is ever persisted. Stamp the row with
    CURRENT_KEY_VERSION so rotation can pick the right KEK later.
    """
    dek = Fernet.generate_key()
    return dek, _kek_fernet().encrypt(dek).decode()


def unwrap_dek(wrapped_dek: str, key_version: int = CURRENT_KEY_VERSION) -> bytes:
    """Unwrap a stored DEK with the crown KEK. Raises DecryptionError on failure."""
    if not wrapped_dek:
        raise DecryptionError("wrapped_dek is empty")
    try:
        return _kek_fernet(key_version).decrypt(wrapped_dek.encode())
    except (InvalidToken, ValueError, TypeError) as exc:
        raise DecryptionError("DEK unwrap failed") from exc


def encrypt_with_dek(dek: bytes, plaintext: bytes) -> bytes:
    """Encrypt payload bytes under an already-minted DEK. bytes → bytes."""
    return Fernet(dek).encrypt(plaintext)


def decrypt_with_dek(dek: bytes, ciphertext: bytes) -> bytes:
    """Decrypt payload bytes under an unwrapped DEK. Raises on ANY failure.

    NEVER falls back to returning the ciphertext (the M2 rule): a wrong key or a
    tampered object raises, so a corrupted file can never be served as if it
    were the real one.
    """
    try:
        return Fernet(dek).decrypt(ciphertext)
    except (InvalidToken, ValueError, TypeError) as exc:
        raise DecryptionError("file payload decryption failed") from exc


# --- deterministic keyed hash for lookups (no plaintext stored) --------------

def phone_hash(phone: str) -> str:
    """Keyed HMAC-SHA256 of a phone → stable per-business lookup key.

    Deterministic (same input → same output) so it can be a uniqueness/lookup
    key, unlike randomized ciphertext. The HMAC key is a real secret, so the
    digest can't be reversed or rainbow-tabled without it.
    """
    return hmac.new(_hmac_key(), phone.encode(), hashlib.sha256).hexdigest()
