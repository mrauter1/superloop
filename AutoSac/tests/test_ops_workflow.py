from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone
import uuid

import pytest


def _load_symbols():
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("argon2")
    from shared.models import AIDraft, Ticket, TicketMessage, TicketStatusHistory, TicketView, User
    from shared.ticketing import (
        add_ops_internal_note,
        add_ops_public_reply,
        assign_ticket_for_ops,
        publish_ai_draft_for_ops,
        reject_ai_draft_for_ops,
        request_manual_rerun,
        set_ticket_status_for_ops,
    )

    return {
        "AIDraft": AIDraft,
        "Ticket": Ticket,
        "TicketMessage": TicketMessage,
        "TicketStatusHistory": TicketStatusHistory,
        "TicketView": TicketView,
        "User": User,
        "add_ops_internal_note": add_ops_internal_note,
        "add_ops_public_reply": add_ops_public_reply,
        "assign_ticket_for_ops": assign_ticket_for_ops,
        "publish_ai_draft_for_ops": publish_ai_draft_for_ops,
        "reject_ai_draft_for_ops": reject_ai_draft_for_ops,
        "request_manual_rerun": request_manual_rerun,
        "set_ticket_status_for_ops": set_ticket_status_for_ops,
    }


class _FakeSession:
    def __init__(self):
        self.added = []
        self.objects = {}
        self.commit_calls = 0

    def add(self, item):
        self.added.append(item)
        key = getattr(item, "user_id", None), getattr(item, "ticket_id", None)
        if key != (None, None):
            self.objects[key] = item

    def get(self, model, key):
        return self.objects.get((model, key)) or self.objects.get(key)

    def commit(self):
        self.commit_calls += 1


def _make_ops_user(symbols, *, role: str = "dev_ti"):
    return symbols["User"](
        id=uuid.uuid4(),
        email=f"{role}@example.com",
        display_name=role.upper(),
        password_hash="hash",
        role=role,
        is_active=True,
    )


def test_add_ops_public_reply_records_status_history_and_view():
    symbols = _load_symbols()
    fake_db = _FakeSession()
    actor = _make_ops_user(symbols)
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=5,
        reference="T-000005",
        title="Needs follow-up",
        created_by_user_id=uuid.uuid4(),
        status="waiting_on_dev_ti",
        urgent=False,
    )
    existing_view = symbols["TicketView"](user_id=actor.id, ticket_id=ticket.id)
    fake_db.objects[(actor.id, ticket.id)] = existing_view

    message = symbols["add_ops_public_reply"](
        fake_db,
        ticket=ticket,
        actor=actor,
        body_markdown="Please confirm the affected user account.",
        next_status="waiting_on_user",
    )

    history = [item for item in fake_db.added if isinstance(item, symbols["TicketStatusHistory"])]

    assert message.author_type == "dev_ti"
    assert message.visibility == "public"
    assert message.source == "human_public_reply"
    assert ticket.status == "waiting_on_user"
    assert history[0].from_status == "waiting_on_dev_ti"
    assert history[0].to_status == "waiting_on_user"
    assert fake_db.objects[(actor.id, ticket.id)].last_viewed_at >= existing_view.last_viewed_at


def test_add_ops_public_reply_rejects_invalid_next_status():
    symbols = _load_symbols()
    fake_db = _FakeSession()
    actor = _make_ops_user(symbols)
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=50,
        reference="T-000050",
        title="Invalid transition",
        created_by_user_id=uuid.uuid4(),
        status="waiting_on_dev_ti",
        urgent=False,
    )

    with pytest.raises(ValueError):
        symbols["add_ops_public_reply"](
            fake_db,
            ticket=ticket,
            actor=actor,
            body_markdown="This should fail.",
            next_status="new",
        )


def test_add_ops_internal_note_keeps_status_and_adds_internal_message():
    symbols = _load_symbols()
    fake_db = _FakeSession()
    actor = _make_ops_user(symbols)
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=6,
        reference="T-000006",
        title="Investigate mismatch",
        created_by_user_id=uuid.uuid4(),
        status="waiting_on_dev_ti",
        urgent=False,
    )

    message = symbols["add_ops_internal_note"](
        fake_db,
        ticket=ticket,
        actor=actor,
        body_markdown="Internal note for Dev/TI only.",
    )

    history = [item for item in fake_db.added if isinstance(item, symbols["TicketStatusHistory"])]

    assert message.author_type == "dev_ti"
    assert message.visibility == "internal"
    assert message.source == "human_internal_note"
    assert ticket.status == "waiting_on_dev_ti"
    assert history == []


def test_assign_ticket_for_ops_touches_ticket_and_view_only_when_assignment_changes():
    symbols = _load_symbols()
    fake_db = _FakeSession()
    actor = _make_ops_user(symbols)
    assignee = _make_ops_user(symbols, role="admin")
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=60,
        reference="T-000060",
        title="Assignment",
        created_by_user_id=uuid.uuid4(),
        status="waiting_on_dev_ti",
        urgent=False,
    )
    before_update = ticket.updated_at

    symbols["assign_ticket_for_ops"](fake_db, ticket=ticket, actor=actor, assignee=assignee)

    assert ticket.assigned_to_user_id == assignee.id
    assert ticket.updated_at != before_update
    assert fake_db.objects[(actor.id, ticket.id)].ticket_id == ticket.id


def test_set_ticket_status_for_ops_records_resolve_history_and_rejects_invalid_status():
    symbols = _load_symbols()
    fake_db = _FakeSession()
    actor = _make_ops_user(symbols)
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=61,
        reference="T-000061",
        title="Status",
        created_by_user_id=uuid.uuid4(),
        status="waiting_on_dev_ti",
        urgent=False,
    )

    symbols["set_ticket_status_for_ops"](fake_db, ticket=ticket, actor=actor, next_status="resolved")
    history = [item for item in fake_db.added if isinstance(item, symbols["TicketStatusHistory"])]

    assert ticket.status == "resolved"
    assert ticket.resolved_at is not None
    assert history[0].to_status == "resolved"

    with pytest.raises(ValueError):
        symbols["set_ticket_status_for_ops"](fake_db, ticket=ticket, actor=actor, next_status="not-a-status")


def test_request_manual_rerun_requeues_when_run_is_active(monkeypatch):
    symbols = _load_symbols()
    fake_db = _FakeSession()
    actor = _make_ops_user(symbols)
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=7,
        reference="T-000007",
        title="Rerun requested",
        created_by_user_id=uuid.uuid4(),
        status="waiting_on_dev_ti",
        urgent=False,
    )
    monkeypatch.setattr("shared.ticketing.has_active_ai_run", lambda db, ticket_id: True)

    run = symbols["request_manual_rerun"](fake_db, ticket=ticket, actor=actor)

    history = [item for item in fake_db.added if isinstance(item, symbols["TicketStatusHistory"])]

    assert run is None
    assert ticket.requeue_requested is True
    assert ticket.requeue_trigger == "manual_rerun"
    assert ticket.status == "waiting_on_dev_ti"
    assert history == []


def test_request_manual_rerun_creates_pending_run_and_moves_ticket_to_ai_triage(monkeypatch):
    symbols = _load_symbols()
    fake_db = _FakeSession()
    actor = _make_ops_user(symbols)
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=71,
        reference="T-000071",
        title="Fresh rerun",
        created_by_user_id=uuid.uuid4(),
        status="waiting_on_dev_ti",
        urgent=False,
    )
    expected_run = object()
    monkeypatch.setattr("shared.ticketing.has_active_ai_run", lambda db, ticket_id: False)
    monkeypatch.setattr("shared.ticketing.create_pending_ai_run", lambda *args, **kwargs: expected_run)

    run = symbols["request_manual_rerun"](fake_db, ticket=ticket, actor=actor)
    history = [item for item in fake_db.added if isinstance(item, symbols["TicketStatusHistory"])]

    assert run is expected_run
    assert ticket.status == "ai_triage"
    assert history[0].from_status == "waiting_on_dev_ti"
    assert history[0].to_status == "ai_triage"


def test_publish_ai_draft_for_ops_creates_ai_message_and_status_change():
    symbols = _load_symbols()
    fake_db = _FakeSession()
    actor = _make_ops_user(symbols)
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=8,
        reference="T-000008",
        title="Approval needed",
        created_by_user_id=uuid.uuid4(),
        status="waiting_on_dev_ti",
        urgent=False,
    )
    draft = symbols["AIDraft"](
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        ai_run_id=uuid.uuid4(),
        kind="public_reply",
        body_markdown="This is a safe draft reply.",
        body_text="This is a safe draft reply.",
        status="pending_approval",
    )

    message = symbols["publish_ai_draft_for_ops"](
        fake_db,
        ticket=ticket,
        draft=draft,
        actor=actor,
        next_status="waiting_on_user",
    )

    history = [item for item in fake_db.added if isinstance(item, symbols["TicketStatusHistory"])]

    assert message.author_type == "ai"
    assert message.source == "ai_draft_published"
    assert draft.status == "published"
    assert draft.reviewed_by_user_id == actor.id
    assert ticket.status == "waiting_on_user"
    assert history[0].to_status == "waiting_on_user"


def test_reject_ai_draft_for_ops_marks_review_metadata_without_status_change():
    symbols = _load_symbols()
    fake_db = _FakeSession()
    actor = _make_ops_user(symbols)
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=81,
        reference="T-000081",
        title="Reject draft",
        created_by_user_id=uuid.uuid4(),
        status="waiting_on_dev_ti",
        urgent=False,
    )
    draft = symbols["AIDraft"](
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        ai_run_id=uuid.uuid4(),
        kind="public_reply",
        body_markdown="Hold for review.",
        body_text="Hold for review.",
        status="pending_approval",
    )

    symbols["reject_ai_draft_for_ops"](fake_db, ticket=ticket, draft=draft, actor=actor)
    history = [item for item in fake_db.added if isinstance(item, symbols["TicketStatusHistory"])]

    assert draft.status == "rejected"
    assert draft.reviewed_by_user_id == actor.id
    assert draft.reviewed_at is not None
    assert ticket.status == "waiting_on_dev_ti"
    assert history == []


def test_publish_ai_draft_for_ops_rejects_non_pending_draft():
    symbols = _load_symbols()
    fake_db = _FakeSession()
    actor = _make_ops_user(symbols)
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=82,
        reference="T-000082",
        title="Already handled",
        created_by_user_id=uuid.uuid4(),
        status="waiting_on_dev_ti",
        urgent=False,
    )
    draft = symbols["AIDraft"](
        id=uuid.uuid4(),
        ticket_id=ticket.id,
        ai_run_id=uuid.uuid4(),
        kind="public_reply",
        body_markdown="Already published.",
        body_text="Already published.",
        status="published",
    )

    with pytest.raises(ValueError):
        symbols["publish_ai_draft_for_ops"](
            fake_db,
            ticket=ticket,
            draft=draft,
            actor=actor,
            next_status="waiting_on_user",
        )


def _load_web_stack():
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("argon2")
    from fastapi.testclient import TestClient

    from app import auth, routes_ops
    from app.main import create_app
    from shared.db import db_session_dependency

    return {
        "TestClient": TestClient,
        "auth": auth,
        "routes_ops": routes_ops,
        "create_app": create_app,
        "db_session_dependency": db_session_dependency,
    }


class _RouteDb:
    def __init__(self):
        self.commit_calls = 0

    def commit(self):
        self.commit_calls += 1


def test_requester_cannot_access_ops_routes():
    stack = _load_web_stack()
    app = stack["create_app"]()
    db = _RouteDb()
    requester = SimpleNamespace(id=uuid.uuid4(), display_name="Requester", role="requester", is_active=True)

    app.dependency_overrides[stack["db_session_dependency"]] = lambda: db
    app.dependency_overrides[stack["auth"].get_current_user] = lambda: requester
    app.dependency_overrides[stack["routes_ops"].get_required_auth_session] = lambda: SimpleNamespace(csrf_token="csrf")

    with stack["TestClient"](app) as client:
        response = client.get("/ops")

    assert response.status_code == 403


def test_requester_cannot_access_ops_board():
    stack = _load_web_stack()
    app = stack["create_app"]()
    db = _RouteDb()
    requester = SimpleNamespace(id=uuid.uuid4(), display_name="Requester", role="requester", is_active=True)

    app.dependency_overrides[stack["db_session_dependency"]] = lambda: db
    app.dependency_overrides[stack["auth"].get_current_user] = lambda: requester
    app.dependency_overrides[stack["routes_ops"].get_required_auth_session] = lambda: SimpleNamespace(csrf_token="csrf")

    with stack["TestClient"](app) as client:
        response = client.get("/ops/board")

    assert response.status_code == 403


def test_requester_cannot_access_ops_ticket_detail():
    stack = _load_web_stack()
    app = stack["create_app"]()
    db = _RouteDb()
    requester = SimpleNamespace(id=uuid.uuid4(), display_name="Requester", role="requester", is_active=True)

    app.dependency_overrides[stack["db_session_dependency"]] = lambda: db
    app.dependency_overrides[stack["auth"].get_current_user] = lambda: requester
    app.dependency_overrides[stack["routes_ops"].get_required_auth_session] = lambda: SimpleNamespace(csrf_token="csrf")

    with stack["TestClient"](app) as client:
        response = client.get("/ops/tickets/T-000999")

    assert response.status_code == 403


def test_ops_list_route_does_not_mark_ticket_as_read(monkeypatch):
    stack = _load_web_stack()
    app = stack["create_app"]()
    db = _RouteDb()
    ops_user = SimpleNamespace(id=uuid.uuid4(), display_name="Ops", role="dev_ti")
    auth_session = SimpleNamespace(csrf_token="csrf-token")
    observed = {"view_updates": 0}

    monkeypatch.setattr(
        stack["routes_ops"],
        "_ops_filter_context",
        lambda *args, **kwargs: {
            "rows": [],
            "grouped_rows": {key: [] for key in ("new", "ai_triage", "waiting_on_user", "waiting_on_dev_ti", "resolved")},
            "filters": {
                "status": "",
                "ticket_class": "",
                "assigned_to": "",
                "urgent": False,
                "unassigned_only": False,
                "created_by_me": False,
                "needs_approval": False,
                "updated_since_viewed": False,
            },
            "ops_users": [],
            "status_options": [],
            "class_options": [],
        },
    )
    monkeypatch.setattr(
        stack["routes_ops"],
        "upsert_ticket_view",
        lambda *args, **kwargs: observed.__setitem__("view_updates", observed["view_updates"] + 1),
    )

    app.dependency_overrides[stack["db_session_dependency"]] = lambda: db
    app.dependency_overrides[stack["routes_ops"].require_ops_user] = lambda: ops_user
    app.dependency_overrides[stack["routes_ops"].get_required_auth_session] = lambda: auth_session

    with stack["TestClient"](app) as client:
        response = client.get("/ops")

    assert response.status_code == 200
    assert observed["view_updates"] == 0
    assert db.commit_calls == 1


def test_ops_board_route_does_not_mark_ticket_as_read(monkeypatch):
    stack = _load_web_stack()
    app = stack["create_app"]()
    db = _RouteDb()
    ops_user = SimpleNamespace(id=uuid.uuid4(), display_name="Ops", role="dev_ti")
    auth_session = SimpleNamespace(csrf_token="csrf-token")
    observed = {"view_updates": 0}

    monkeypatch.setattr(
        stack["routes_ops"],
        "_ops_filter_context",
        lambda *args, **kwargs: {
            "rows": [],
            "grouped_rows": {key: [] for key in ("new", "ai_triage", "waiting_on_user", "waiting_on_dev_ti", "resolved")},
            "filters": {
                "status": "",
                "ticket_class": "",
                "assigned_to": "",
                "urgent": False,
                "unassigned_only": False,
                "created_by_me": False,
                "needs_approval": False,
                "updated_since_viewed": False,
            },
            "ops_users": [],
            "status_options": [],
            "class_options": [],
        },
    )
    monkeypatch.setattr(
        stack["routes_ops"],
        "upsert_ticket_view",
        lambda *args, **kwargs: observed.__setitem__("view_updates", observed["view_updates"] + 1),
    )

    app.dependency_overrides[stack["db_session_dependency"]] = lambda: db
    app.dependency_overrides[stack["routes_ops"].require_ops_user] = lambda: ops_user
    app.dependency_overrides[stack["routes_ops"].get_required_auth_session] = lambda: auth_session

    with stack["TestClient"](app) as client:
        response = client.get("/ops/board")

    assert response.status_code == 200
    assert observed["view_updates"] == 0
    assert db.commit_calls == 1


def test_ops_detail_route_marks_ticket_as_read(monkeypatch):
    stack = _load_web_stack()
    app = stack["create_app"]()
    db = _RouteDb()
    ops_user = SimpleNamespace(id=uuid.uuid4(), display_name="Ops", role="dev_ti")
    auth_session = SimpleNamespace(csrf_token="csrf-token")
    ticket = SimpleNamespace(
        reference="T-000010",
        id=uuid.uuid4(),
        title="Ops ticket",
        status="new",
        urgent=False,
        updated_at=datetime.now(timezone.utc),
    )
    observed = {"view_updates": 0}

    monkeypatch.setattr(stack["routes_ops"], "_load_ops_ticket_or_404", lambda *args, **kwargs: ticket)
    monkeypatch.setattr(stack["routes_ops"], "_ticket_detail_context", lambda *args, **kwargs: {"ticket": ticket, "public_thread": [], "internal_thread": [], "ops_users": [], "status_options": [], "reply_status_options": [], "pending_draft": None, "pending_draft_html": "", "latest_run": None, "latest_ai_note": None, "latest_ai_note_html": "", "ai_relevant_paths": [], "ai_summary_short": "", "ai_summary_internal": "", "creator": None, "assignee": None})
    monkeypatch.setattr(
        stack["routes_ops"],
        "upsert_ticket_view",
        lambda *args, **kwargs: observed.__setitem__("view_updates", observed["view_updates"] + 1),
    )

    app.dependency_overrides[stack["db_session_dependency"]] = lambda: db
    app.dependency_overrides[stack["routes_ops"].require_ops_user] = lambda: ops_user
    app.dependency_overrides[stack["routes_ops"].get_required_auth_session] = lambda: auth_session

    with stack["TestClient"](app) as client:
        response = client.get(f"/ops/tickets/{ticket.reference}")

    assert response.status_code == 200
    assert observed["view_updates"] == 1
    assert db.commit_calls == 1


def test_ops_routes_source_and_templates_keep_internal_and_public_lanes_separate():
    source = Path("app/routes_ops.py").read_text(encoding="utf-8")
    filters_template = Path("app/templates/ops_filters.html").read_text(encoding="utf-8")
    detail_template = Path("app/templates/ops_ticket_detail.html").read_text(encoding="utf-8")
    board_template = Path("app/templates/ops_board_columns.html").read_text(encoding="utf-8")
    list_template = Path("app/templates/ops_ticket_list.html").read_text(encoding="utf-8")

    assert '"/ops/tickets/{reference}/reply-public"' in source
    assert '"/ops/tickets/{reference}/note-internal"' in source
    assert '"/ops/tickets/{reference}/assign"' in source
    assert '"/ops/tickets/{reference}/set-status"' in source
    assert '"/ops/tickets/{reference}/rerun-ai"' in source
    assert "add_ops_public_reply" in source
    assert "add_ops_internal_note" in source
    assert "assign_ticket_for_ops" in source
    assert "set_ticket_status_for_ops" in source
    assert "Status" in filters_template
    assert "Class" in filters_template
    assert "Assigned to" in filters_template
    assert "Urgent only" in filters_template
    assert "Unassigned only" in filters_template
    assert "Created by me" in filters_template
    assert "Needs approval" in filters_template
    assert "Updated since my last view" in filters_template
    assert "Public thread" in detail_template
    assert "Internal thread" in detail_template
    assert "AI analysis" in detail_template
    assert "Relevant repo/docs paths" in detail_template
    assert "Pending AI draft" in detail_template
    assert "Ticket queue" in list_template
    assert "Pending draft approval" in board_template
