from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Protocol

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from shared.config import Settings
from shared.models import (
    AIDraft,
    AIRun,
    SystemState,
    Ticket,
    TicketAttachment,
    TicketMessage,
    TicketStatusHistory,
    TicketView,
    TICKET_STATUSES,
    User,
)
from shared.security import utc_now

SYSTEM_STATE_KEYS = ("worker_heartbeat", "bootstrap_version")
_STATUS_SENTINEL = object()


class ImageUpload(Protocol):
    original_filename: str
    mime_type: str
    sha256: str
    size_bytes: int
    width: int
    height: int


def generate_ticket_reference(reference_num: int) -> str:
    return f"T-{reference_num:06d}"


def reserve_ticket_reference(db: Session) -> tuple[int, str]:
    reference_num = db.execute(text("SELECT nextval('ticket_reference_num_seq')")).scalar_one()
    return int(reference_num), generate_ticket_reference(int(reference_num))


def generate_provisional_title(description: str, max_length: int = 120) -> str:
    stripped = " ".join(description.strip().split())
    if not stripped:
        return "Untitled ticket"
    first_sentence = re.split(r"(?<=[.!?])\s+", stripped, maxsplit=1)[0]
    title = first_sentence or stripped
    return title[:max_length].rstrip()


def touch_ticket(ticket: Ticket, when=None) -> None:
    ticket.updated_at = when or utc_now()


def record_status_change(
    db: Session,
    *,
    ticket: Ticket,
    to_status: str,
    changed_by_type: str,
    changed_by_user_id: uuid.UUID | None = None,
    note: str | None = None,
    changed_at=None,
    from_status_override: str | None | object = _STATUS_SENTINEL,
) -> TicketStatusHistory:
    event_time = changed_at or utc_now()
    from_status = ticket.status if from_status_override is _STATUS_SENTINEL else from_status_override
    history = TicketStatusHistory(
        ticket_id=ticket.id,
        from_status=from_status,
        to_status=to_status,
        changed_by_user_id=changed_by_user_id,
        changed_by_type=changed_by_type,
        note=note,
        created_at=event_time,
    )
    db.add(history)
    ticket.status = to_status
    ticket.resolved_at = event_time if to_status == "resolved" else None
    ticket.updated_at = event_time
    return history


def upsert_ticket_view(db: Session, *, user_id: uuid.UUID, ticket_id: uuid.UUID, viewed_at=None) -> TicketView:
    view = db.get(TicketView, (user_id, ticket_id))
    event_time = viewed_at or utc_now()
    if view is None:
        view = TicketView(user_id=user_id, ticket_id=ticket_id, last_viewed_at=event_time)
        db.add(view)
    else:
        view.last_viewed_at = event_time
    return view


def has_active_ai_run(db: Session, ticket_id: uuid.UUID) -> bool:
    statement = select(func.count()).select_from(AIRun).where(
        AIRun.ticket_id == ticket_id,
        AIRun.status.in_(("pending", "running")),
    )
    return bool(db.execute(statement).scalar_one())


def create_pending_ai_run(
    db: Session,
    *,
    ticket_id: uuid.UUID,
    triggered_by: str,
    requested_by_user_id: uuid.UUID | None = None,
) -> AIRun | None:
    run = AIRun(
        ticket_id=ticket_id,
        status="pending",
        triggered_by=triggered_by,
        requested_by_user_id=requested_by_user_id,
    )
    try:
        with db.begin_nested():
            db.add(run)
            db.flush()
    except IntegrityError as exc:
        if "uq_ai_runs_active_ticket" not in str(exc.orig):
            raise
        return None
    return run


def request_requeue(ticket: Ticket, trigger: str) -> None:
    ticket.requeue_requested = True
    ticket.requeue_trigger = trigger
    touch_ticket(ticket)


def supersede_pending_drafts(db: Session, ticket_id: uuid.UUID, keep_draft_id: uuid.UUID | None = None) -> int:
    statement = (
        update(AIDraft)
        .where(AIDraft.ticket_id == ticket_id, AIDraft.status == "pending_approval")
        .values(status="superseded")
    )
    if keep_draft_id is not None:
        statement = statement.where(AIDraft.id != keep_draft_id)
    result = db.execute(statement)
    return int(result.rowcount or 0)


def ensure_system_state_defaults(db: Session, bootstrap_version: str) -> None:
    existing_keys = {
        row[0]
        for row in db.execute(select(SystemState.key).where(SystemState.key.in_(SYSTEM_STATE_KEYS))).all()
    }
    now = utc_now()
    if "worker_heartbeat" not in existing_keys:
        db.add(SystemState(key="worker_heartbeat", value_json={"status": "unknown"}, updated_at=now))
    if "bootstrap_version" not in existing_keys:
        db.add(SystemState(key="bootstrap_version", value_json={"version": bootstrap_version}, updated_at=now))


def normalize_message_text(markdown_text: str) -> str:
    return markdown_text.strip()


def apply_ai_classification(
    ticket: Ticket,
    *,
    ticket_class: str,
    confidence: float,
    impact_level: str,
    development_needed: bool,
    requester_language: str,
) -> None:
    ticket.ticket_class = ticket_class
    ticket.ai_confidence = confidence
    ticket.impact_level = impact_level
    ticket.development_needed = development_needed
    ticket.requester_language = requester_language


def _create_message(
    *,
    ticket_id: uuid.UUID,
    author_user_id: uuid.UUID | None,
    author_type: str,
    visibility: str,
    source: str,
    body_markdown: str,
    created_at,
    ai_run_id: uuid.UUID | None = None,
) -> TicketMessage:
    return TicketMessage(
        id=uuid.uuid4(),
        ticket_id=ticket_id,
        author_user_id=author_user_id,
        author_type=author_type,
        visibility=visibility,
        source=source,
        body_markdown=body_markdown,
        body_text=normalize_message_text(body_markdown),
        ai_run_id=ai_run_id,
        created_at=created_at,
    )


def _attachment_extension(mime_type: str) -> str:
    if mime_type == "image/png":
        return ".png"
    if mime_type == "image/jpeg":
        return ".jpg"
    raise ValueError(f"Unsupported attachment mime type: {mime_type}")


def enqueue_or_requeue_ai_run(
    db: Session,
    *,
    ticket: Ticket,
    trigger: str,
    requested_by_user_id: uuid.UUID | None = None,
) -> AIRun | None:
    run = create_pending_ai_run(
        db,
        ticket_id=ticket.id,
        triggered_by=trigger,
        requested_by_user_id=requested_by_user_id,
    )
    if run is None:
        request_requeue(ticket, trigger)
    return run


def _create_public_message(
    *,
    ticket_id: uuid.UUID,
    author_user_id: uuid.UUID,
    source: str,
    body_markdown: str,
    created_at,
) -> TicketMessage:
    return _create_message(
        ticket_id=ticket_id,
        author_user_id=author_user_id,
        author_type="requester",
        visibility="public",
        source=source,
        body_markdown=body_markdown,
        created_at=created_at,
    )


def _apply_ai_status(
    db: Session,
    *,
    ticket: Ticket,
    to_status: str,
    last_ai_action: str,
    changed_at,
) -> None:
    if ticket.status != to_status:
        record_status_change(
            db,
            ticket=ticket,
            to_status=to_status,
            changed_by_type="ai",
            changed_at=changed_at,
        )
    else:
        touch_ticket(ticket, changed_at)
    ticket.last_ai_action = last_ai_action


def _add_public_attachments(
    db: Session,
    *,
    ticket_id: uuid.UUID,
    message_id: uuid.UUID,
    images: list[ImageUpload],
    storage_path_builder: Callable[[uuid.UUID, str], str],
    created_at,
) -> list[TicketAttachment]:
    attachments: list[TicketAttachment] = []
    for image in images:
        attachment_id = uuid.uuid4()
        stored_path = storage_path_builder(attachment_id, _attachment_extension(image.mime_type))
        attachment = TicketAttachment(
            id=attachment_id,
            ticket_id=ticket_id,
            message_id=message_id,
            visibility="public",
            original_filename=image.original_filename,
            stored_path=stored_path,
            mime_type=image.mime_type,
            sha256=image.sha256,
            size_bytes=image.size_bytes,
            width=image.width,
            height=image.height,
            created_at=created_at,
        )
        db.add(attachment)
        attachments.append(attachment)
    return attachments


def create_requester_ticket(
    db: Session,
    *,
    settings: Settings,
    requester: User,
    title: str,
    description_markdown: str,
    urgent: bool,
    images: list[ImageUpload],
) -> tuple[Ticket, TicketMessage, list[TicketAttachment], AIRun | None]:
    created_at = utc_now()
    reference_num, reference = reserve_ticket_reference(db)
    resolved_title = title.strip() or generate_provisional_title(description_markdown)
    ticket = Ticket(
        id=uuid.uuid4(),
        reference_num=reference_num,
        reference=reference,
        title=resolved_title,
        created_by_user_id=requester.id,
        status="new",
        urgent=urgent,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(ticket)

    message = _create_public_message(
        ticket_id=ticket.id,
        author_user_id=requester.id,
        source="ticket_create",
        body_markdown=description_markdown,
        created_at=created_at,
    )
    db.add(message)
    attachments = _add_public_attachments(
        db,
        ticket_id=ticket.id,
        message_id=message.id,
        images=images,
        storage_path_builder=lambda attachment_id, extension: str(
            settings.uploads_dir / str(ticket.id) / f"{attachment_id}{extension}"
        ),
        created_at=created_at,
    )
    run = create_pending_ai_run(
        db,
        ticket_id=ticket.id,
        triggered_by="new_ticket",
        requested_by_user_id=requester.id,
    )
    record_status_change(
        db,
        ticket=ticket,
        to_status="new",
        changed_by_type="requester",
        changed_by_user_id=requester.id,
        changed_at=created_at,
        from_status_override=None,
    )
    upsert_ticket_view(db, user_id=requester.id, ticket_id=ticket.id, viewed_at=created_at)
    return ticket, message, attachments, run


def add_requester_reply(
    db: Session,
    *,
    settings: Settings,
    ticket: Ticket,
    requester: User,
    body_markdown: str,
    images: list[ImageUpload],
) -> tuple[TicketMessage, list[TicketAttachment], AIRun | None]:
    created_at = utc_now()
    message = _create_public_message(
        ticket_id=ticket.id,
        author_user_id=requester.id,
        source="requester_reply",
        body_markdown=body_markdown,
        created_at=created_at,
    )
    db.add(message)
    attachments = _add_public_attachments(
        db,
        ticket_id=ticket.id,
        message_id=message.id,
        images=images,
        storage_path_builder=lambda attachment_id, extension: str(
            settings.uploads_dir / str(ticket.id) / f"{attachment_id}{extension}"
        ),
        created_at=created_at,
    )

    trigger = "reopen" if ticket.status == "resolved" else "requester_reply"
    if ticket.status != "ai_triage":
        record_status_change(
            db,
            ticket=ticket,
            to_status="ai_triage",
            changed_by_type="requester",
            changed_by_user_id=requester.id,
            changed_at=created_at,
        )
    else:
        touch_ticket(ticket, created_at)
        ticket.resolved_at = None

    run = enqueue_or_requeue_ai_run(
        db,
        ticket=ticket,
        trigger=trigger,
        requested_by_user_id=requester.id,
    )
    upsert_ticket_view(db, user_id=requester.id, ticket_id=ticket.id, viewed_at=created_at)
    return message, attachments, run


def publish_ai_internal_note(
    db: Session,
    *,
    ticket: Ticket,
    ai_run_id: uuid.UUID,
    body_markdown: str,
    created_at=None,
) -> TicketMessage:
    note_time = created_at or utc_now()
    message = _create_message(
        ticket_id=ticket.id,
        author_user_id=None,
        author_type="ai",
        visibility="internal",
        source="ai_internal_note",
        body_markdown=body_markdown,
        created_at=note_time,
        ai_run_id=ai_run_id,
    )
    db.add(message)
    touch_ticket(ticket, note_time)
    return message


def publish_ai_failure_note(
    db: Session,
    *,
    ticket: Ticket,
    ai_run_id: uuid.UUID,
    body_markdown: str,
    created_at=None,
) -> TicketMessage:
    note_time = created_at or utc_now()
    message = _create_message(
        ticket_id=ticket.id,
        author_user_id=None,
        author_type="system",
        visibility="internal",
        source="system",
        body_markdown=body_markdown,
        created_at=note_time,
        ai_run_id=ai_run_id,
    )
    db.add(message)
    touch_ticket(ticket, note_time)
    return message


def publish_ai_public_reply(
    db: Session,
    *,
    ticket: Ticket,
    ai_run_id: uuid.UUID,
    body_markdown: str,
    next_status: str,
    last_ai_action: str,
    increment_clarification_rounds: bool = False,
    created_at=None,
) -> TicketMessage:
    published_at = created_at or utc_now()
    message = _create_message(
        ticket_id=ticket.id,
        author_user_id=None,
        author_type="ai",
        visibility="public",
        source="ai_auto_public",
        body_markdown=body_markdown,
        created_at=published_at,
        ai_run_id=ai_run_id,
    )
    db.add(message)
    if increment_clarification_rounds:
        ticket.clarification_rounds += 1
    _apply_ai_status(
        db,
        ticket=ticket,
        to_status=next_status,
        last_ai_action=last_ai_action,
        changed_at=published_at,
    )
    return message


def create_ai_draft(
    db: Session,
    *,
    ticket: Ticket,
    ai_run_id: uuid.UUID,
    body_markdown: str,
    created_at=None,
) -> AIDraft:
    draft_time = created_at or utc_now()
    draft = AIDraft(
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        ai_run_id=ai_run_id,
        kind="public_reply",
        body_markdown=body_markdown,
        body_text=normalize_message_text(body_markdown),
        status="pending_approval",
        created_at=draft_time,
    )
    db.add(draft)
    supersede_pending_drafts(db, ticket.id, keep_draft_id=draft.id)
    _apply_ai_status(
        db,
        ticket=ticket,
        to_status="waiting_on_dev_ti",
        last_ai_action="draft_public_reply",
        changed_at=draft_time,
    )
    return draft


def route_ticket_after_ai(
    db: Session,
    *,
    ticket: Ticket,
    next_status: str,
    last_ai_action: str,
    created_at=None,
) -> None:
    routed_at = created_at or utc_now()
    _apply_ai_status(
        db,
        ticket=ticket,
        to_status=next_status,
        last_ai_action=last_ai_action,
        changed_at=routed_at,
    )


def process_deferred_requeue(db: Session, *, ticket: Ticket) -> AIRun | None:
    if not ticket.requeue_requested or not ticket.requeue_trigger:
        return None
    db.flush()
    if has_active_ai_run(db, ticket.id):
        return None
    run = create_pending_ai_run(
        db,
        ticket_id=ticket.id,
        triggered_by=ticket.requeue_trigger,
    )
    if run is None:
        return None
    ticket.requeue_requested = False
    ticket.requeue_trigger = None
    touch_ticket(ticket)
    return run


def resolve_ticket_for_requester(db: Session, *, ticket: Ticket, requester: User) -> None:
    resolved_at = utc_now()
    if ticket.status != "resolved":
        record_status_change(
            db,
            ticket=ticket,
            to_status="resolved",
            changed_by_type="requester",
            changed_by_user_id=requester.id,
            changed_at=resolved_at,
        )
    upsert_ticket_view(db, user_id=requester.id, ticket_id=ticket.id, viewed_at=resolved_at)


def add_ops_public_reply(
    db: Session,
    *,
    ticket: Ticket,
    actor: User,
    body_markdown: str,
    next_status: str,
) -> TicketMessage:
    if next_status not in {"waiting_on_user", "waiting_on_dev_ti", "resolved"}:
        raise ValueError(f"Invalid ops reply next status: {next_status}")
    created_at = utc_now()
    message = _create_message(
        ticket_id=ticket.id,
        author_user_id=actor.id,
        author_type="dev_ti",
        visibility="public",
        source="human_public_reply",
        body_markdown=body_markdown,
        created_at=created_at,
    )
    db.add(message)
    if ticket.status != next_status:
        record_status_change(
            db,
            ticket=ticket,
            to_status=next_status,
            changed_by_type="dev_ti",
            changed_by_user_id=actor.id,
            changed_at=created_at,
        )
    else:
        touch_ticket(ticket, created_at)
    upsert_ticket_view(db, user_id=actor.id, ticket_id=ticket.id, viewed_at=created_at)
    return message


def add_ops_internal_note(
    db: Session,
    *,
    ticket: Ticket,
    actor: User,
    body_markdown: str,
) -> TicketMessage:
    created_at = utc_now()
    message = _create_message(
        ticket_id=ticket.id,
        author_user_id=actor.id,
        author_type="dev_ti",
        visibility="internal",
        source="human_internal_note",
        body_markdown=body_markdown,
        created_at=created_at,
    )
    db.add(message)
    touch_ticket(ticket, created_at)
    upsert_ticket_view(db, user_id=actor.id, ticket_id=ticket.id, viewed_at=created_at)
    return message


def assign_ticket_for_ops(
    db: Session,
    *,
    ticket: Ticket,
    actor: User,
    assignee: User | None,
) -> None:
    changed_at = utc_now()
    assignee_id = assignee.id if assignee is not None else None
    if ticket.assigned_to_user_id != assignee_id:
        ticket.assigned_to_user_id = assignee_id
        touch_ticket(ticket, changed_at)
    upsert_ticket_view(db, user_id=actor.id, ticket_id=ticket.id, viewed_at=changed_at)


def set_ticket_status_for_ops(
    db: Session,
    *,
    ticket: Ticket,
    actor: User,
    next_status: str,
    note: str | None = None,
) -> None:
    if next_status not in TICKET_STATUSES:
        raise ValueError(f"Invalid ticket status: {next_status}")
    changed_at = utc_now()
    if ticket.status != next_status:
        record_status_change(
            db,
            ticket=ticket,
            to_status=next_status,
            changed_by_type="dev_ti",
            changed_by_user_id=actor.id,
            note=note,
            changed_at=changed_at,
        )
    upsert_ticket_view(db, user_id=actor.id, ticket_id=ticket.id, viewed_at=changed_at)


def request_manual_rerun(
    db: Session,
    *,
    ticket: Ticket,
    actor: User,
) -> AIRun | None:
    requested_at = utc_now()
    if has_active_ai_run(db, ticket.id):
        request_requeue(ticket, "manual_rerun")
        upsert_ticket_view(db, user_id=actor.id, ticket_id=ticket.id, viewed_at=requested_at)
        return None
    run = create_pending_ai_run(
        db,
        ticket_id=ticket.id,
        triggered_by="manual_rerun",
        requested_by_user_id=actor.id,
    )
    if run is None:
        request_requeue(ticket, "manual_rerun")
        upsert_ticket_view(db, user_id=actor.id, ticket_id=ticket.id, viewed_at=requested_at)
        return None
    if ticket.status != "ai_triage":
        record_status_change(
            db,
            ticket=ticket,
            to_status="ai_triage",
            changed_by_type="dev_ti",
            changed_by_user_id=actor.id,
            changed_at=requested_at,
        )
    else:
        touch_ticket(ticket, requested_at)
    upsert_ticket_view(db, user_id=actor.id, ticket_id=ticket.id, viewed_at=requested_at)
    return run


def publish_ai_draft_for_ops(
    db: Session,
    *,
    ticket: Ticket,
    draft: AIDraft,
    actor: User,
    next_status: str,
) -> TicketMessage:
    if draft.status != "pending_approval":
        raise ValueError("Only pending drafts can be published.")
    if next_status not in {"waiting_on_user", "waiting_on_dev_ti", "resolved"}:
        raise ValueError(f"Invalid draft publish next status: {next_status}")
    published_at = utc_now()
    message = _create_message(
        ticket_id=ticket.id,
        author_user_id=None,
        author_type="ai",
        visibility="public",
        source="ai_draft_published",
        body_markdown=draft.body_markdown,
        created_at=published_at,
        ai_run_id=draft.ai_run_id,
    )
    db.add(message)
    draft.status = "published"
    draft.reviewed_by_user_id = actor.id
    draft.reviewed_at = published_at
    draft.published_message_id = message.id
    if ticket.status != next_status:
        record_status_change(
            db,
            ticket=ticket,
            to_status=next_status,
            changed_by_type="dev_ti",
            changed_by_user_id=actor.id,
            changed_at=published_at,
        )
    else:
        touch_ticket(ticket, published_at)
    upsert_ticket_view(db, user_id=actor.id, ticket_id=ticket.id, viewed_at=published_at)
    return message


def reject_ai_draft_for_ops(
    db: Session,
    *,
    ticket: Ticket,
    draft: AIDraft,
    actor: User,
) -> None:
    if draft.status != "pending_approval":
        raise ValueError("Only pending drafts can be rejected.")
    reviewed_at = utc_now()
    draft.status = "rejected"
    draft.reviewed_by_user_id = actor.id
    draft.reviewed_at = reviewed_at
    touch_ticket(ticket, reviewed_at)
    upsert_ticket_view(db, user_id=actor.id, ticket_id=ticket.id, viewed_at=reviewed_at)
