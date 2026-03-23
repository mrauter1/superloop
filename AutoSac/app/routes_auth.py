from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import (
    begin_user_session,
    end_user_session,
    get_optional_auth_session,
    get_settings_dependency,
    get_required_auth_session,
    validate_csrf_token,
)
from app.ui import build_template_context, post_login_redirect_path, templates
from shared.config import Settings
from shared.db import db_session_dependency
from shared.models import SessionRecord, User
from shared.security import verify_password
from shared.user_admin import get_user_by_email

router = APIRouter()


def get_current_user_optional(
    auth_session: SessionRecord | None = Depends(get_optional_auth_session),
    db: Session = Depends(db_session_dependency),
) -> User | None:
    if auth_session is None:
        return None
    user = db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        return None
    return user


@router.get("/login", response_class=HTMLResponse)
def login_page(
    request: Request,
    auth_session: SessionRecord | None = Depends(get_optional_auth_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    if current_user is not None:
        return RedirectResponse(post_login_redirect_path(current_user), status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "login.html",
        build_template_context(request=request, current_user=None, auth_session=auth_session),
    )


@router.post("/login")
def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    remember_me: str | None = Form(default=None),
    settings: Settings = Depends(get_settings_dependency),
    db: Session = Depends(db_session_dependency),
    auth_session: SessionRecord | None = Depends(get_optional_auth_session),
    current_user: User | None = Depends(get_current_user_optional),
):
    if current_user is not None:
        return RedirectResponse(post_login_redirect_path(current_user), status_code=status.HTTP_303_SEE_OTHER)

    user = get_user_by_email(db, email)
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        response = templates.TemplateResponse(
            request,
            "login.html",
            build_template_context(
                request=request,
                current_user=None,
                auth_session=auth_session,
                extra={"error": "Invalid email or password.", "email": email.strip()},
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return response

    response = RedirectResponse(post_login_redirect_path(user), status_code=status.HTTP_303_SEE_OTHER)
    begin_user_session(
        request=request,
        response=response,
        db=db,
        user=user,
        remember_me=remember_me == "on",
        settings=settings,
    )
    db.commit()
    return response


@router.post("/logout")
def logout_action(
    request: Request,
    csrf_token: str = Form(...),
    auth_session: SessionRecord = Depends(get_required_auth_session),
    db: Session = Depends(db_session_dependency),
):
    validate_csrf_token(auth_session, csrf_token)
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    end_user_session(request=request, response=response, db=db)
    db.commit()
    return response
