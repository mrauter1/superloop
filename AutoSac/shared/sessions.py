from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from shared.config import Settings
from shared.models import SessionRecord, User
from shared.security import calculate_session_expiry, generate_csrf_token, generate_opaque_token, hash_token, utc_now


def create_server_session(
    db: Session,
    *,
    settings: Settings,
    user: User,
    remember_me: bool,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[SessionRecord, str]:
    raw_token = generate_opaque_token()
    now = utc_now()
    session_record = SessionRecord(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        csrf_token=generate_csrf_token(),
        remember_me=remember_me,
        expires_at=calculate_session_expiry(settings, remember_me, now=now),
        last_seen_at=now,
        created_at=now,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(session_record)
    user.last_login_at = now
    user.updated_at = now
    return session_record, raw_token


def get_valid_session_by_token(db: Session, raw_token: str | None) -> SessionRecord | None:
    if not raw_token:
        return None
    token_hash = hash_token(raw_token)
    now = utc_now()
    statement = select(SessionRecord).where(SessionRecord.token_hash == token_hash, SessionRecord.expires_at > now)
    record = db.execute(statement).scalar_one_or_none()
    if record is not None:
        record.last_seen_at = now
    return record


def invalidate_session(db: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    db.execute(delete(SessionRecord).where(SessionRecord.token_hash == hash_token(raw_token)))
