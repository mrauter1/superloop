from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import json
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_required_auth_session, require_ops_user, validate_csrf_token
from app.render import render_markdown_to_html
from app.ui import build_template_context, ops_author_label, ops_status_label, templates
from shared.db import db_session_dependency
from shared.models import AIDraft, AIRun, Ticket, TicketAttachment, TicketMessage, TicketView, User
from shared.permissions import is_ops_user
from shared.ticketing import (
    add_ops_internal_note,
    add_ops_public_reply,
    assign_ticket_for_ops,
    publish_ai_draft_for_ops,
    reject_ai_draft_for_ops,
    request_manual_rerun,
    set_ticket_status_for_ops,
    upsert_ticket_view,
)

router = APIRouter()

_OPS_REPLY_STATUSES = ("waiting_on_user", "waiting_on_dev_ti", "resolved")
_OPS_FILTERABLE_STATUSES = ("new", "ai_triage", "waiting_on_user", "waiting_on_dev_ti", "resolved")
_OPS_FILTERABLE_CLASSES = ("support", "access_config", "data_ops", "bug", "feature", "unknown")


def _parse_bool(value: str | None) -> bool:
    return value in {"on", "true", "1", "yes"}


def _load_ops_ticket_or_404(db: Session, *, reference: str) -> Ticket:
    ticket = db.execute(select(Ticket).where(Ticket.reference == reference)).scalar_one_or_none()
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


def _load_ops_draft_or_404(db: Session, *, draft_id: str) -> AIDraft:
    try:
        draft_uuid = uuid.UUID(draft_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found") from exc
    draft = db.get(AIDraft, draft_uuid)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found")
    return draft


def _load_attachments_by_message(db: Session, *, ticket_id, visibility: str) -> dict[Any, list[TicketAttachment]]:
    attachments = list(
        db.execute(
            select(TicketAttachment)
            .where(TicketAttachment.ticket_id == ticket_id, TicketAttachment.visibility == visibility)
            .order_by(TicketAttachment.created_at.asc())
        ).scalars()
    )
    grouped: dict[Any, list[TicketAttachment]] = defaultdict(list)
    for attachment in attachments:
        grouped[attachment.message_id].append(attachment)
    return grouped


def _serialize_thread(db: Session, *, ticket_id, visibility: str) -> list[dict[str, object]]:
    attachments_by_message = _load_attachments_by_message(db, ticket_id=ticket_id, visibility=visibility)
    messages = list(
        db.execute(
            select(TicketMessage)
            .where(TicketMessage.ticket_id == ticket_id, TicketMessage.visibility == visibility)
            .order_by(TicketMessage.created_at.asc())
        ).scalars()
    )
    return [
        {
            "id": str(message.id),
            "created_at": message.created_at,
            "author_type": message.author_type,
            "author_label": ops_author_label(message.author_type),
            "source": message.source,
            "body_markdown": message.body_markdown,
            "body_html": render_markdown_to_html(message.body_markdown),
            "attachments": attachments_by_message.get(message.id, []),
        }
        for message in messages
    ]


def _load_ops_users(db: Session) -> list[User]:
    return list(
        db.execute(
            select(User)
            .where(User.is_active.is_(True), User.role.in_(("dev_ti", "admin")))
            .order_by(User.display_name.asc())
        ).scalars()
    )


def _load_latest_run(db: Session, *, ticket_id) -> AIRun | None:
    return db.execute(
        select(AIRun).where(AIRun.ticket_id == ticket_id).order_by(AIRun.created_at.desc())
    ).scalars().first()


def _load_pending_draft(db: Session, *, ticket_id) -> AIDraft | None:
    return db.execute(
        select(AIDraft)
        .where(AIDraft.ticket_id == ticket_id, AIDraft.status == "pending_approval")
        .order_by(AIDraft.created_at.desc())
    ).scalars().first()


def _load_latest_internal_ai_note(db: Session, *, ticket_id) -> TicketMessage | None:
    return db.execute(
        select(TicketMessage)
        .where(
            TicketMessage.ticket_id == ticket_id,
            TicketMessage.visibility == "internal",
            TicketMessage.source == "ai_internal_note",
        )
        .order_by(TicketMessage.created_at.desc())
    ).scalars().first()


def _load_run_output(run: AIRun | None) -> dict[str, object]:
    if run is None or not run.final_output_path:
        return {}
    output_path = Path(run.final_output_path)
    if not output_path.is_file():
        return {}
    try:
        return json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _read_filters(request: Request) -> dict[str, object]:
    query = request.query_params
    return {
        "status": query.get("status", "").strip(),
        "ticket_class": query.get("ticket_class", "").strip(),
        "assigned_to": query.get("assigned_to", "").strip(),
        "urgent": _parse_bool(query.get("urgent")),
        "unassigned_only": _parse_bool(query.get("unassigned_only")),
        "created_by_me": _parse_bool(query.get("created_by_me")),
        "needs_approval": _parse_bool(query.get("needs_approval")),
        "updated_since_viewed": _parse_bool(query.get("updated_since_viewed")),
    }


def _load_filtered_ticket_rows(db: Session, *, current_user: User, filters: dict[str, object]) -> list[dict[str, object]]:
    statement = select(Ticket).order_by(Ticket.updated_at.desc())
    status_filter = str(filters["status"])
    class_filter = str(filters["ticket_class"])
    assigned_to_filter = str(filters["assigned_to"])
    if status_filter:
        statement = statement.where(Ticket.status == status_filter)
    if class_filter:
        statement = statement.where(Ticket.ticket_class == class_filter)
    if filters["urgent"]:
        statement = statement.where(Ticket.urgent.is_(True))
    if filters["unassigned_only"]:
        statement = statement.where(Ticket.assigned_to_user_id.is_(None))
    if filters["created_by_me"]:
        statement = statement.where(Ticket.created_by_user_id == current_user.id)
    if assigned_to_filter:
        if assigned_to_filter == "unassigned":
            statement = statement.where(Ticket.assigned_to_user_id.is_(None))
        else:
            try:
                statement = statement.where(Ticket.assigned_to_user_id == uuid.UUID(assigned_to_filter))
            except ValueError:
                return []

    tickets = list(db.execute(statement).scalars())
    if not tickets:
        return []

    ticket_ids = [ticket.id for ticket in tickets]
    views = {
        view.ticket_id: view.last_viewed_at
        for view in db.execute(
            select(TicketView).where(TicketView.user_id == current_user.id, TicketView.ticket_id.in_(ticket_ids))
        ).scalars()
    }
    pending_drafts: dict[uuid.UUID, AIDraft] = {}
    for draft in db.execute(
        select(AIDraft)
        .where(AIDraft.ticket_id.in_(ticket_ids), AIDraft.status == "pending_approval")
        .order_by(AIDraft.created_at.desc())
    ).scalars():
        pending_drafts.setdefault(draft.ticket_id, draft)
    user_ids = {ticket.created_by_user_id for ticket in tickets}
    user_ids.update(ticket.assigned_to_user_id for ticket in tickets if ticket.assigned_to_user_id is not None)
    users = {
        user.id: user
        for user in db.execute(select(User).where(User.id.in_(user_ids))).scalars()
    }

    rows: list[dict[str, object]] = []
    for ticket in tickets:
        last_viewed_at = views.get(ticket.id)
        updated_for_user = last_viewed_at is None or ticket.updated_at > last_viewed_at
        pending_draft = pending_drafts.get(ticket.id)
        if filters["needs_approval"] and pending_draft is None:
            continue
        if filters["updated_since_viewed"] and not updated_for_user:
            continue
        rows.append(
            {
                "ticket": ticket,
                "creator": users.get(ticket.created_by_user_id),
                "assignee": users.get(ticket.assigned_to_user_id),
                "updated_for_user": updated_for_user,
                "pending_draft": pending_draft,
            }
        )
    return rows


def _group_ticket_rows(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    groups = {status: [] for status in _OPS_FILTERABLE_STATUSES}
    for row in rows:
        groups[row["ticket"].status].append(row)
    return groups


def _ops_filter_context(db: Session, *, current_user: User, filters: dict[str, object]) -> dict[str, object]:
    rows = _load_filtered_ticket_rows(db, current_user=current_user, filters=filters)
    return {
        "filters": filters,
        "ops_users": _load_ops_users(db),
        "status_options": _OPS_FILTERABLE_STATUSES,
        "class_options": _OPS_FILTERABLE_CLASSES,
        "rows": rows,
        "grouped_rows": _group_ticket_rows(rows),
    }


def _ticket_detail_context(db: Session, *, ticket: Ticket) -> dict[str, object]:
    public_thread = _serialize_thread(db, ticket_id=ticket.id, visibility="public")
    internal_thread = _serialize_thread(db, ticket_id=ticket.id, visibility="internal")
    pending_draft = _load_pending_draft(db, ticket_id=ticket.id)
    latest_run = _load_latest_run(db, ticket_id=ticket.id)
    latest_ai_note = _load_latest_internal_ai_note(db, ticket_id=ticket.id)
    run_output = _load_run_output(latest_run)
    creator = db.get(User, ticket.created_by_user_id)
    assignee = db.get(User, ticket.assigned_to_user_id) if ticket.assigned_to_user_id else None
    return {
        "ticket": ticket,
        "creator": creator,
        "assignee": assignee,
        "public_thread": public_thread,
        "internal_thread": internal_thread,
        "ops_users": _load_ops_users(db),
        "status_options": _OPS_FILTERABLE_STATUSES,
        "reply_status_options": _OPS_REPLY_STATUSES,
        "pending_draft": pending_draft,
        "pending_draft_html": render_markdown_to_html(pending_draft.body_markdown) if pending_draft else "",
        "latest_run": latest_run,
        "latest_ai_note": latest_ai_note,
        "latest_ai_note_html": render_markdown_to_html(latest_ai_note.body_markdown) if latest_ai_note else "",
        "ai_relevant_paths": run_output.get("relevant_paths", []) if isinstance(run_output, dict) else [],
        "ai_summary_short": run_output.get("summary_short", "") if isinstance(run_output, dict) else "",
        "ai_summary_internal": run_output.get("summary_internal", "") if isinstance(run_output, dict) else "",
    }


def _template_or_partial_response(
    request: Request,
    *,
    template_name: str,
    partial_name: str,
    context: dict[str, object],
):
    if request.headers.get("HX-Request", "").lower() == "true":
        return templates.TemplateResponse(request, partial_name, context)
    return templates.TemplateResponse(request, template_name, context)


@router.get("/ops", response_class=HTMLResponse)
def ops_ticket_list(
    request: Request,
    current_user: User = Depends(require_ops_user),
    auth_session=Depends(get_required_auth_session),
    db: Session = Depends(db_session_dependency),
):
    filters = _read_filters(request)
    db.commit()
    return templates.TemplateResponse(
        request,
        "ops_ticket_list.html",
        build_template_context(
            request=request,
            current_user=current_user,
            auth_session=auth_session,
            extra={
                **_ops_filter_context(db, current_user=current_user, filters=filters),
                "filters_action": "/ops",
            },
        ),
    )


@router.get("/ops/board", response_class=HTMLResponse)
def ops_board(
    request: Request,
    current_user: User = Depends(require_ops_user),
    auth_session=Depends(get_required_auth_session),
    db: Session = Depends(db_session_dependency),
):
    filters = _read_filters(request)
    db.commit()
    context = build_template_context(
        request=request,
        current_user=current_user,
        auth_session=auth_session,
        extra={
            **_ops_filter_context(db, current_user=current_user, filters=filters),
            "filters_action": "/ops/board",
            "ops_status_label": ops_status_label,
        },
    )
    return _template_or_partial_response(
        request,
        template_name="ops_board.html",
        partial_name="ops_board_columns.html",
        context=context,
    )


@router.get("/ops/tickets/{reference}", response_class=HTMLResponse)
def ops_ticket_detail(
    reference: str,
    request: Request,
    current_user: User = Depends(require_ops_user),
    auth_session=Depends(get_required_auth_session),
    db: Session = Depends(db_session_dependency),
):
    ticket = _load_ops_ticket_or_404(db, reference=reference)
    upsert_ticket_view(db, user_id=current_user.id, ticket_id=ticket.id)
    db.commit()
    return templates.TemplateResponse(
        request,
        "ops_ticket_detail.html",
        build_template_context(
            request=request,
            current_user=current_user,
            auth_session=auth_session,
            extra=_ticket_detail_context(db, ticket=ticket),
        ),
    )


@router.post("/ops/tickets/{reference}/assign")
def ops_assign_ticket(
    reference: str,
    current_user: User = Depends(require_ops_user),
    auth_session=Depends(get_required_auth_session),
    csrf_token: str = Form(...),
    assigned_to_user_id: str = Form(default=""),
    db: Session = Depends(db_session_dependency),
):
    validate_csrf_token(auth_session, csrf_token)
    ticket = _load_ops_ticket_or_404(db, reference=reference)
    assignee = None
    assignee_value = assigned_to_user_id.strip()
    if assignee_value:
        try:
            assignee_uuid = uuid.UUID(assignee_value)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid assignee") from exc
        assignee = db.get(User, assignee_uuid)
        if assignee is None or not assignee.is_active or not is_ops_user(assignee):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid assignee")
    assign_ticket_for_ops(db, ticket=ticket, actor=current_user, assignee=assignee)
    db.commit()
    return RedirectResponse(f"/ops/tickets/{ticket.reference}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ops/tickets/{reference}/set-status")
def ops_set_ticket_status(
    reference: str,
    current_user: User = Depends(require_ops_user),
    auth_session=Depends(get_required_auth_session),
    csrf_token: str = Form(...),
    next_status: str = Form(...),
    db: Session = Depends(db_session_dependency),
):
    validate_csrf_token(auth_session, csrf_token)
    ticket = _load_ops_ticket_or_404(db, reference=reference)
    try:
        set_ticket_status_for_ops(db, ticket=ticket, actor=current_user, next_status=next_status.strip())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/ops/tickets/{ticket.reference}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ops/tickets/{reference}/reply-public")
def ops_reply_public(
    reference: str,
    current_user: User = Depends(require_ops_user),
    auth_session=Depends(get_required_auth_session),
    csrf_token: str = Form(...),
    body: str = Form(...),
    next_status: str = Form(...),
    db: Session = Depends(db_session_dependency),
):
    validate_csrf_token(auth_session, csrf_token)
    ticket = _load_ops_ticket_or_404(db, reference=reference)
    if not body.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reply text is required")
    try:
        add_ops_public_reply(
            db,
            ticket=ticket,
            actor=current_user,
            body_markdown=body.strip(),
            next_status=next_status.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/ops/tickets/{ticket.reference}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ops/tickets/{reference}/note-internal")
def ops_note_internal(
    reference: str,
    current_user: User = Depends(require_ops_user),
    auth_session=Depends(get_required_auth_session),
    csrf_token: str = Form(...),
    body: str = Form(...),
    db: Session = Depends(db_session_dependency),
):
    validate_csrf_token(auth_session, csrf_token)
    ticket = _load_ops_ticket_or_404(db, reference=reference)
    if not body.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Internal note text is required")
    add_ops_internal_note(db, ticket=ticket, actor=current_user, body_markdown=body.strip())
    db.commit()
    return RedirectResponse(f"/ops/tickets/{ticket.reference}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ops/tickets/{reference}/rerun-ai")
def ops_rerun_ai(
    reference: str,
    current_user: User = Depends(require_ops_user),
    auth_session=Depends(get_required_auth_session),
    csrf_token: str = Form(...),
    db: Session = Depends(db_session_dependency),
):
    validate_csrf_token(auth_session, csrf_token)
    ticket = _load_ops_ticket_or_404(db, reference=reference)
    request_manual_rerun(db, ticket=ticket, actor=current_user)
    db.commit()
    return RedirectResponse(f"/ops/tickets/{ticket.reference}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ops/drafts/{draft_id}/approve-publish")
def ops_approve_publish_draft(
    draft_id: str,
    current_user: User = Depends(require_ops_user),
    auth_session=Depends(get_required_auth_session),
    csrf_token: str = Form(...),
    next_status: str = Form(...),
    db: Session = Depends(db_session_dependency),
):
    validate_csrf_token(auth_session, csrf_token)
    draft = _load_ops_draft_or_404(db, draft_id=draft_id)
    ticket = db.get(Ticket, draft.ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    try:
        publish_ai_draft_for_ops(
            db,
            ticket=ticket,
            draft=draft,
            actor=current_user,
            next_status=next_status.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/ops/tickets/{ticket.reference}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/ops/drafts/{draft_id}/reject")
def ops_reject_draft(
    draft_id: str,
    current_user: User = Depends(require_ops_user),
    auth_session=Depends(get_required_auth_session),
    csrf_token: str = Form(...),
    db: Session = Depends(db_session_dependency),
):
    validate_csrf_token(auth_session, csrf_token)
    draft = _load_ops_draft_or_404(db, draft_id=draft_id)
    ticket = db.get(Ticket, draft.ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    try:
        reject_ai_draft_for_ops(db, ticket=ticket, draft=draft, actor=current_user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    db.commit()
    return RedirectResponse(f"/ops/tickets/{ticket.reference}", status_code=status.HTTP_303_SEE_OTHER)
