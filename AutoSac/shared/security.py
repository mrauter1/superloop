from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from shared.config import Settings

_PASSWORD_HASHER = PasswordHasher()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str) -> str:
    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def calculate_session_expiry(settings: Settings, remember_me: bool, now: datetime | None = None) -> datetime:
    base = now or utc_now()
    if remember_me:
        return base + timedelta(days=settings.session_remember_days)
    return base + timedelta(hours=settings.session_default_hours)
