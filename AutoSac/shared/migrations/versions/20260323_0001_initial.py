"""Initial Stage 1 schema.

Revision ID: 20260323_0001
Revises:
Create Date: 2026-03-23 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260323_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE ticket_reference_num_seq START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("role IN ('requester', 'dev_ti', 'admin')", name=op.f("ck_users_users_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )

    op.create_table(
        "system_state",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_state")),
    )

    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        sa.Column("remember_me", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)

    op.create_table(
        "tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reference_num", sa.BigInteger(), server_default=sa.text("nextval('ticket_reference_num_seq')"), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("urgent", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("ticket_class", sa.Text(), nullable=True),
        sa.Column("ai_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("impact_level", sa.Text(), nullable=True),
        sa.Column("development_needed", sa.Boolean(), nullable=True),
        sa.Column("clarification_rounds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("requester_language", sa.Text(), nullable=True),
        sa.Column("last_processed_hash", sa.Text(), nullable=True),
        sa.Column("last_ai_action", sa.Text(), nullable=True),
        sa.Column("requeue_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("requeue_trigger", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("impact_level IS NULL OR impact_level IN ('low', 'medium', 'high', 'unknown')", name=op.f("ck_tickets_tickets_impact_level")),
        sa.CheckConstraint("requeue_trigger IS NULL OR requeue_trigger IN ('requester_reply', 'manual_rerun', 'reopen')", name=op.f("ck_tickets_tickets_requeue_trigger")),
        sa.CheckConstraint("status IN ('new', 'ai_triage', 'waiting_on_user', 'waiting_on_dev_ti', 'resolved')", name=op.f("ck_tickets_tickets_status")),
        sa.CheckConstraint("ticket_class IS NULL OR ticket_class IN ('support', 'access_config', 'data_ops', 'bug', 'feature', 'unknown')", name=op.f("ck_tickets_tickets_ticket_class")),
        sa.ForeignKeyConstraint(["assigned_to_user_id"], ["users.id"], name=op.f("fk_tickets_assigned_to_user_id_users")),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name=op.f("fk_tickets_created_by_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
        sa.UniqueConstraint("reference", name=op.f("uq_tickets_reference")),
        sa.UniqueConstraint("reference_num", name=op.f("uq_tickets_reference_num")),
    )
    op.execute("CREATE INDEX ix_tickets_status_updated_at ON tickets (status, updated_at DESC)")
    op.execute("CREATE INDEX ix_tickets_created_by_user_id_updated_at ON tickets (created_by_user_id, updated_at DESC)")
    op.execute("CREATE INDEX ix_tickets_assigned_to_user_id_updated_at ON tickets (assigned_to_user_id, updated_at DESC)")
    op.execute("CREATE INDEX ix_tickets_urgent_status_updated_at ON tickets (urgent, status, updated_at DESC)")

    op.create_table(
        "ai_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("triggered_by", sa.Text(), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_hash", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("prompt_path", sa.Text(), nullable=True),
        sa.Column("schema_path", sa.Text(), nullable=True),
        sa.Column("final_output_path", sa.Text(), nullable=True),
        sa.Column("stdout_jsonl_path", sa.Text(), nullable=True),
        sa.Column("stderr_path", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'skipped', 'superseded')", name=op.f("ck_ai_runs_ai_runs_status")),
        sa.CheckConstraint("triggered_by IN ('new_ticket', 'requester_reply', 'manual_rerun', 'reopen')", name=op.f("ck_ai_runs_ai_runs_triggered_by")),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], name=op.f("fk_ai_runs_requested_by_user_id_users")),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ai_runs_ticket_id_tickets")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_runs")),
    )
    op.create_index("ix_ai_runs_status_created_at", "ai_runs", ["status", "created_at"], unique=False)
    op.execute("CREATE INDEX ix_ai_runs_ticket_id_created_at_desc ON ai_runs (ticket_id, created_at DESC)")
    op.execute("CREATE UNIQUE INDEX uq_ai_runs_active_ticket ON ai_runs (ticket_id) WHERE status IN ('pending', 'running')")

    op.create_table(
        "ticket_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("author_type", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("ai_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("author_type IN ('requester', 'dev_ti', 'ai', 'system')", name=op.f("ck_ticket_messages_ticket_messages_author_type")),
        sa.CheckConstraint("source IN ('ticket_create', 'requester_reply', 'human_public_reply', 'human_internal_note', 'ai_auto_public', 'ai_internal_note', 'ai_draft_published', 'system')", name=op.f("ck_ticket_messages_ticket_messages_source")),
        sa.CheckConstraint("visibility IN ('public', 'internal')", name=op.f("ck_ticket_messages_ticket_messages_visibility")),
        sa.ForeignKeyConstraint(["ai_run_id"], ["ai_runs.id"], name=op.f("fk_ticket_messages_ai_run_id_ai_runs")),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], name=op.f("fk_ticket_messages_author_user_id_users")),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_messages_ticket_id_tickets")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_messages")),
    )
    op.create_index("ix_ticket_messages_ticket_id_created_at", "ticket_messages", ["ticket_id", "created_at"], unique=False)
    op.create_index("ix_ticket_messages_ticket_id_visibility_created_at", "ticket_messages", ["ticket_id", "visibility", "created_at"], unique=False)

    op.create_table(
        "ticket_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("visibility IN ('public', 'internal')", name=op.f("ck_ticket_attachments_ticket_attachments_visibility")),
        sa.ForeignKeyConstraint(["message_id"], ["ticket_messages.id"], name=op.f("fk_ticket_attachments_message_id_ticket_messages")),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_attachments_ticket_id_tickets")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_attachments")),
    )
    op.create_index("ix_ticket_attachments_ticket_id", "ticket_attachments", ["ticket_id"], unique=False)
    op.create_index("ix_ticket_attachments_message_id", "ticket_attachments", ["message_id"], unique=False)
    op.create_index("ix_ticket_attachments_sha256", "ticket_attachments", ["sha256"], unique=False)

    op.create_table(
        "ticket_status_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_status", sa.Text(), nullable=True),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("changed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changed_by_type", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("changed_by_type IN ('requester', 'dev_ti', 'ai', 'system')", name=op.f("ck_ticket_status_history_ticket_status_history_changed_by_type")),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["users.id"], name=op.f("fk_ticket_status_history_changed_by_user_id_users")),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_status_history_ticket_id_tickets")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_status_history")),
    )
    op.create_index("ix_ticket_status_history_ticket_id_created_at", "ticket_status_history", ["ticket_id", "created_at"], unique=False)

    op.create_table(
        "ticket_views",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_views_ticket_id_tickets")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ticket_views_user_id_users")),
        sa.PrimaryKeyConstraint("user_id", "ticket_id", name=op.f("pk_ticket_views")),
    )

    op.create_table(
        "ai_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticket_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ai_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("kind IN ('public_reply')", name=op.f("ck_ai_drafts_ai_drafts_kind")),
        sa.CheckConstraint("status IN ('pending_approval', 'approved', 'rejected', 'superseded', 'published')", name=op.f("ck_ai_drafts_ai_drafts_status")),
        sa.ForeignKeyConstraint(["ai_run_id"], ["ai_runs.id"], name=op.f("fk_ai_drafts_ai_run_id_ai_runs")),
        sa.ForeignKeyConstraint(["published_message_id"], ["ticket_messages.id"], name=op.f("fk_ai_drafts_published_message_id_ticket_messages")),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], name=op.f("fk_ai_drafts_reviewed_by_user_id_users")),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], name=op.f("fk_ai_drafts_ticket_id_tickets")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_drafts")),
    )
    op.execute("CREATE INDEX ix_ai_drafts_ticket_id_status_created_at_desc ON ai_drafts (ticket_id, status, created_at DESC)")
    op.create_index("ix_ai_drafts_ai_run_id", "ai_drafts", ["ai_run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ai_drafts_ai_run_id", table_name="ai_drafts")
    op.execute("DROP INDEX ix_ai_drafts_ticket_id_status_created_at_desc")
    op.drop_table("ai_drafts")

    op.drop_table("ticket_views")

    op.drop_index("ix_ticket_status_history_ticket_id_created_at", table_name="ticket_status_history")
    op.drop_table("ticket_status_history")

    op.drop_index("ix_ticket_attachments_sha256", table_name="ticket_attachments")
    op.drop_index("ix_ticket_attachments_message_id", table_name="ticket_attachments")
    op.drop_index("ix_ticket_attachments_ticket_id", table_name="ticket_attachments")
    op.drop_table("ticket_attachments")

    op.drop_index("ix_ticket_messages_ticket_id_visibility_created_at", table_name="ticket_messages")
    op.drop_index("ix_ticket_messages_ticket_id_created_at", table_name="ticket_messages")
    op.drop_table("ticket_messages")

    op.execute("DROP INDEX uq_ai_runs_active_ticket")
    op.execute("DROP INDEX ix_ai_runs_ticket_id_created_at_desc")
    op.drop_index("ix_ai_runs_status_created_at", table_name="ai_runs")
    op.drop_table("ai_runs")

    op.execute("DROP INDEX ix_tickets_urgent_status_updated_at")
    op.execute("DROP INDEX ix_tickets_assigned_to_user_id_updated_at")
    op.execute("DROP INDEX ix_tickets_created_by_user_id_updated_at")
    op.execute("DROP INDEX ix_tickets_status_updated_at")
    op.drop_table("tickets")

    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.drop_table("sessions")

    op.drop_table("system_state")
    op.drop_table("users")

    op.execute("DROP SEQUENCE ticket_reference_num_seq")
