from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Sequence,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db import Base
from shared.security import utc_now

USER_ROLES = ("requester", "dev_ti", "admin")
TICKET_STATUSES = ("new", "ai_triage", "waiting_on_user", "waiting_on_dev_ti", "resolved")
TICKET_CLASSES = ("support", "access_config", "data_ops", "bug", "feature", "unknown")
IMPACT_LEVELS = ("low", "medium", "high", "unknown")
AUTHOR_TYPES = ("requester", "dev_ti", "ai", "system")
VISIBILITIES = ("public", "internal")
MESSAGE_SOURCES = (
    "ticket_create",
    "requester_reply",
    "human_public_reply",
    "human_internal_note",
    "ai_auto_public",
    "ai_internal_note",
    "ai_draft_published",
    "system",
)
AI_RUN_STATUSES = ("pending", "running", "succeeded", "failed", "skipped", "superseded")
AI_RUN_TRIGGERS = ("new_ticket", "requester_reply", "manual_rerun", "reopen")
REQUEUE_TRIGGERS = ("requester_reply", "manual_rerun", "reopen")
AI_DRAFT_KINDS = ("public_reply",)
AI_DRAFT_STATUSES = ("pending_approval", "approved", "rejected", "superseded", "published")

TICKET_REFERENCE_NUM_SEQUENCE = Sequence("ticket_reference_num_seq")


def _enum_sql(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"({quoted})"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(f"role IN {_enum_sql(USER_ROLES)}", name="users_role"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=text("now()"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    csrf_token: Mapped[str] = mapped_column(Text, nullable=False)
    remember_me: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()"))
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(Text, nullable=True)


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(f"status IN {_enum_sql(TICKET_STATUSES)}", name="tickets_status"),
        CheckConstraint(f"ticket_class IS NULL OR ticket_class IN {_enum_sql(TICKET_CLASSES)}", name="tickets_ticket_class"),
        CheckConstraint(f"impact_level IS NULL OR impact_level IN {_enum_sql(IMPACT_LEVELS)}", name="tickets_impact_level"),
        CheckConstraint(f"requeue_trigger IS NULL OR requeue_trigger IN {_enum_sql(REQUEUE_TRIGGERS)}", name="tickets_requeue_trigger"),
        Index("ix_tickets_status_updated_at", "status", text("updated_at DESC")),
        Index("ix_tickets_created_by_user_id_updated_at", "created_by_user_id", text("updated_at DESC")),
        Index("ix_tickets_assigned_to_user_id_updated_at", "assigned_to_user_id", text("updated_at DESC")),
        Index("ix_tickets_urgent_status_updated_at", "urgent", "status", text("updated_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reference_num: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        unique=True,
        server_default=text("nextval('ticket_reference_num_seq')"),
    )
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    urgent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    ticket_class: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    impact_level: Mapped[str | None] = mapped_column(Text, nullable=True)
    development_needed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    clarification_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    requester_language: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_processed_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_ai_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    requeue_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    requeue_trigger: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=text("now()"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TicketMessage(Base):
    __tablename__ = "ticket_messages"
    __table_args__ = (
        CheckConstraint(f"author_type IN {_enum_sql(AUTHOR_TYPES)}", name="ticket_messages_author_type"),
        CheckConstraint(f"visibility IN {_enum_sql(VISIBILITIES)}", name="ticket_messages_visibility"),
        CheckConstraint(f"source IN {_enum_sql(MESSAGE_SOURCES)}", name="ticket_messages_source"),
        Index("ix_ticket_messages_ticket_id_created_at", "ticket_id", "created_at"),
        Index("ix_ticket_messages_ticket_id_visibility_created_at", "ticket_id", "visibility", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    author_type: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()"))


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"
    __table_args__ = (
        CheckConstraint(f"visibility IN {_enum_sql(VISIBILITIES)}", name="ticket_attachments_visibility"),
        Index("ix_ticket_attachments_ticket_id", "ticket_id"),
        Index("ix_ticket_attachments_message_id", "message_id"),
        Index("ix_ticket_attachments_sha256", "sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ticket_messages.id"), nullable=False)
    visibility: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()"))


class TicketStatusHistory(Base):
    __tablename__ = "ticket_status_history"
    __table_args__ = (
        CheckConstraint(f"changed_by_type IN {_enum_sql(AUTHOR_TYPES)}", name="ticket_status_history_changed_by_type"),
        Index("ix_ticket_status_history_ticket_id_created_at", "ticket_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    to_status: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    changed_by_type: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()"))


class TicketView(Base):
    __tablename__ = "ticket_views"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id"), primary_key=True)
    last_viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()"))


class AIRun(Base):
    __tablename__ = "ai_runs"
    __table_args__ = (
        CheckConstraint(f"status IN {_enum_sql(AI_RUN_STATUSES)}", name="ai_runs_status"),
        CheckConstraint(f"triggered_by IN {_enum_sql(AI_RUN_TRIGGERS)}", name="ai_runs_triggered_by"),
        Index("ix_ai_runs_status_created_at", "status", "created_at"),
        Index("ix_ai_runs_ticket_id_created_at_desc", "ticket_id", text("created_at DESC")),
        Index(
            "uq_ai_runs_active_ticket",
            "ticket_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_by: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    stdout_jsonl_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()"))


class AIDraft(Base):
    __tablename__ = "ai_drafts"
    __table_args__ = (
        CheckConstraint(f"kind IN {_enum_sql(AI_DRAFT_KINDS)}", name="ai_drafts_kind"),
        CheckConstraint(f"status IN {_enum_sql(AI_DRAFT_STATUSES)}", name="ai_drafts_status"),
        Index("ix_ai_drafts_ticket_id_status_created_at_desc", "ticket_id", "status", text("created_at DESC")),
        Index("ix_ai_drafts_ai_run_id", "ai_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id"), nullable=False)
    ai_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ai_runs.id"), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=text("now()"))
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ticket_messages.id"), nullable=True)


class SystemState(Base):
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now, server_default=text("now()"))
