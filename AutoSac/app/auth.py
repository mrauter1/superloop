from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.config import Settings, get_settings
from shared.contracts import SESSION_COOKIE_NAME
from shared.db import db_session_dependency
from shared.models import SessionRecord, User
from shared.permissions import is_ops_user, is_requester
from shared.sessions import create_server_session, get_valid_session_by_token, invalidate_session


def get_settings_dependency() -> Settings:
    return get_settings()


def get_optional_auth_session(
    request: Request,
    db: Session = Depends(db_session_dependency),
) -> SessionRecord | None:
    return get_valid_session_by_token(db, request.cookies.get(SESSION_COOKIE_NAME))


def get_current_user(
    auth_session: SessionRecord | None = Depends(get_optional_auth_session),
    db: Session = Depends(db_session_dependency),
) -> User:
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    user = db.execute(select(User).where(User.id == auth_session.user_id, User.is_active.is_(True))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid")
    return user


def get_required_auth_session(
    auth_session: SessionRecord | None = Depends(get_optional_auth_session),
) -> SessionRecord:
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return auth_session


def require_requester_user(current_user: User = Depends(get_current_user)) -> User:
    if not is_requester(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requester access required")
    return current_user


def require_ops_user(current_user: User = Depends(get_current_user)) -> User:
    if not is_ops_user(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Ops access required")
    return current_user


def validate_csrf_token(auth_session: SessionRecord, provided_token: str | None) -> None:
    if not provided_token or provided_token != auth_session.csrf_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def require_csrf(
    csrf_token: str | None,
    *,
    auth_session: SessionRecord,
) -> None:
    validate_csrf_token(auth_session, csrf_token)


def begin_user_session(
    *,
    request: Request,
    response: Response,
    db: Session,
    user: User,
    remember_me: bool,
    settings: Settings,
) -> SessionRecord:
    auth_session, raw_token = create_server_session(
        db,
        settings=settings,
        user=user,
        remember_me=remember_me,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    max_age = settings.session_remember_days * 24 * 60 * 60 if remember_me else None
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
        max_age=max_age,
        expires=max_age,
    )
    return auth_session


def end_user_session(*, request: Request, response: Response, db: Session) -> None:
    invalidate_session(db, request.cookies.get(SESSION_COOKIE_NAME))
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
