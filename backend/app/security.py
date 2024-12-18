"""Secret handling utilities.

API keys for optional LLM providers are encrypted at rest with Fernet
(AES-128-CBC) using a key derived from the JWT secret. The key itself must
come from the environment — if unavailable, provider keys are rejected and
users must configure credentials via environment variables instead.
Secrets are never logged, never returned by the API (only masked).
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet

log = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet | None:
    global _fernet
    if _fernet is not None:
        return _fernet
    from app.config import settings

    # Derive a stable Fernet key from the configured secret (never stored).
    digest = hashlib.sha256(settings.jwt_secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    _fernet = Fernet(key)
    return _fernet


def encrypt_secret(plain: str) -> str:
    if not plain:
        raise ValueError("Cannot encrypt an empty secret.")
    return _get_fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "****"
    return f"{value[:2]}…{value[-4:]}"  # first 2 + last 4 visible only


def redact_text(text: str) -> str:
    """Best-effort redaction of common secret patterns from log text."""
    import re

    patterns = [
        r"(?i)(sk-[A-Za-z0-9_\-]{8,})",
        r"(?i)(api[_-]?key['\"]?\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,})",
        r"(?i)(Bearer\s+[A-Za-z0-9_\-\.]{10,})",
    ]
    out = text
    for pat in patterns:
        out = re.sub(pat, "[REDACTED]", out)
    return out


# Never log full secrets; wrap logging calls that may contain payloads.
def safe_repr(obj: object, max_len: int = 500) -> str:
    text = repr(obj)[:max_len]
    return redact_text(text)
