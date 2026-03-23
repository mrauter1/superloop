from __future__ import annotations

from collections.abc import Mapping

from fastapi.templating import Jinja2Templates

from shared.models import SessionRecord, User
from shared.permissions import is_ops_user

templates = Jinja2Templates(directory="app/templates")

REQUESTER_STATUS_LABELS = {
    "new": "Reviewing",
    "ai_triage": "Reviewing",
    "waiting_on_user": "Waiting for your reply",
    "waiting_on_dev_ti": "Waiting on team",
    "resolved": "Resolved",
}

REQUESTER_AUTHOR_LABELS = {
    "requester": "You",
    "dev_ti": "Team",
    "ai": "AI",
    "system": "System",
}

OPS_STATUS_LABELS = {
    "new": "New",
    "ai_triage": "AI Triage",
    "waiting_on_user": "Waiting on User",
    "waiting_on_dev_ti": "Waiting on Dev/TI",
    "resolved": "Resolved",
}

OPS_AUTHOR_LABELS = {
    "requester": "Requester",
    "dev_ti": "Dev/TI",
    "ai": "AI",
    "system": "System",
}


def requester_status_label(status: str) -> str:
    return REQUESTER_STATUS_LABELS.get(status, status)


def requester_author_label(author_type: str) -> str:
    return REQUESTER_AUTHOR_LABELS.get(author_type, author_type.replace("_", " ").title())


def ops_status_label(status: str) -> str:
    return OPS_STATUS_LABELS.get(status, status.replace("_", " ").title())


def ops_author_label(author_type: str) -> str:
    return OPS_AUTHOR_LABELS.get(author_type, author_type.replace("_", " ").title())


def post_login_redirect_path(user: User) -> str:
    if is_ops_user(user):
        return "/ops"
    return "/app"


def build_template_context(
    *,
    request,
    current_user: User | None = None,
    auth_session: SessionRecord | None = None,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    context: dict[str, object] = {
        "request": request,
        "current_user": current_user,
        "csrf_token": auth_session.csrf_token if auth_session is not None else "",
        "requester_status_label": requester_status_label,
        "requester_author_label": requester_author_label,
        "ops_status_label": ops_status_label,
        "ops_author_label": ops_author_label,
        "is_ops_user": is_ops_user(current_user) if current_user is not None else False,
    }
    if extra:
        context.update(extra)
    return context
