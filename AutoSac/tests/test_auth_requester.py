from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from shared.config import Settings


def _load_ticketing_symbols():
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("argon2")
    from shared.models import AIRun, SessionRecord, Ticket, TicketAttachment, TicketMessage, TicketStatusHistory, TicketView, User
    from shared.ticketing import add_requester_reply, create_requester_ticket, resolve_ticket_for_requester

    return {
        "AIRun": AIRun,
        "SessionRecord": SessionRecord,
        "Ticket": Ticket,
        "TicketAttachment": TicketAttachment,
        "TicketMessage": TicketMessage,
        "TicketStatusHistory": TicketStatusHistory,
        "TicketView": TicketView,
        "User": User,
        "add_requester_reply": add_requester_reply,
        "create_requester_ticket": create_requester_ticket,
        "resolve_ticket_for_requester": resolve_ticket_for_requester,
    }


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


class _FakeSession:
    def __init__(self, *, next_reference_num: int = 1):
        self.added = []
        self.commits = 0
        self.existing = {}
        self.next_reference_num = next_reference_num

    def add(self, item):
        self.added.append(item)
        key = getattr(item, "user_id", None), getattr(item, "ticket_id", None)
        if key != (None, None):
            self.existing[key] = item

    def get(self, model, key):
        return self.existing.get(key)

    def execute(self, statement):
        return _FakeScalarResult(self.next_reference_num)


@dataclass
class _FakeImage:
    original_filename: str = "shot.png"
    mime_type: str = "image/png"
    sha256: str = "abc123"
    size_bytes: int = 128
    width: int = 40
    height: int = 20


def _make_settings(tmp_path: Path) -> Settings:
    workspace_dir = tmp_path / "workspace"
    return Settings(
        app_base_url="https://triage.example.test",
        app_secret_key="secret",
        database_url="postgresql+psycopg://triage:triage@localhost:5432/triage",
        uploads_dir=tmp_path / "uploads",
        triage_workspace_dir=workspace_dir,
        repo_mount_dir=workspace_dir / "app",
        manuals_mount_dir=workspace_dir / "manuals",
        codex_bin="codex",
        codex_api_key="key",
        codex_model="",
        codex_timeout_seconds=75,
        worker_poll_seconds=10,
        auto_support_reply_min_confidence=0.85,
        auto_confirm_intent_min_confidence=0.90,
        max_images_per_message=3,
        max_image_bytes=5 * 1024 * 1024,
        session_default_hours=12,
        session_remember_days=30,
    )


def _load_web_stack():
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    pytest.importorskip("argon2")
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app import routes_auth, routes_requester
    from shared.db import db_session_dependency

    return {
        "TestClient": TestClient,
        "create_app": create_app,
        "routes_auth": routes_auth,
        "routes_requester": routes_requester,
        "db_session_dependency": db_session_dependency,
    }


class _RouteDb:
    def __init__(self):
        self.commit_calls = 0
        self.rollback_calls = 0
        self.objects = {}

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def get(self, model, key):
        return self.objects.get((model, key))


def test_create_requester_ticket_creates_initial_records(monkeypatch, tmp_path):
    symbols = _load_ticketing_symbols()
    fake_db = _FakeSession(next_reference_num=17)
    requester = symbols["User"](
        id=uuid.uuid4(),
        email="requester@example.com",
        display_name="Requester",
        password_hash="hash",
        role="requester",
        is_active=True,
    )
    pending_run = symbols["AIRun"](
        ticket_id=uuid.uuid4(),
        status="pending",
        triggered_by="new_ticket",
        requested_by_user_id=requester.id,
    )
    monkeypatch.setattr("shared.ticketing.create_pending_ai_run", lambda *args, **kwargs: pending_run)

    ticket, message, attachments, run = symbols["create_requester_ticket"](
        fake_db,
        settings=_make_settings(tmp_path),
        requester=requester,
        title="",
        description_markdown="Email reports are missing after noon. Please check.",
        urgent=True,
        images=[_FakeImage()],
    )

    history = [item for item in fake_db.added if isinstance(item, symbols["TicketStatusHistory"])]
    views = [item for item in fake_db.added if isinstance(item, symbols["TicketView"])]

    assert ticket.reference == "T-000017"
    assert ticket.title == "Email reports are missing after noon."
    assert ticket.status == "new"
    assert ticket.urgent is True
    assert message.source == "ticket_create"
    assert message.visibility == "public"
    assert len(attachments) == 1
    assert str(ticket.id) in attachments[0].stored_path
    assert attachments[0].stored_path.endswith(".png")
    assert history[0].from_status is None
    assert history[0].to_status == "new"
    assert views[0].user_id == requester.id
    assert views[0].ticket_id == ticket.id
    assert run is pending_run


def test_add_requester_reply_reopens_and_requeues(monkeypatch, tmp_path):
    symbols = _load_ticketing_symbols()
    from shared.security import utc_now

    fake_db = _FakeSession()
    requester = symbols["User"](
        id=uuid.uuid4(),
        email="requester@example.com",
        display_name="Requester",
        password_hash="hash",
        role="requester",
        is_active=True,
    )
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=1,
        reference="T-000001",
        title="Closed ticket",
        created_by_user_id=requester.id,
        status="resolved",
        urgent=False,
        resolved_at=utc_now(),
    )
    existing_view = symbols["TicketView"](user_id=requester.id, ticket_id=ticket.id, last_viewed_at=utc_now())
    fake_db.existing[(requester.id, ticket.id)] = existing_view
    monkeypatch.setattr("shared.ticketing.create_pending_ai_run", lambda *args, **kwargs: None)

    message, attachments, run = symbols["add_requester_reply"](
        fake_db,
        settings=_make_settings(tmp_path),
        ticket=ticket,
        requester=requester,
        body_markdown="The issue came back after I retried it.",
        images=[],
    )

    history = [item for item in fake_db.added if isinstance(item, symbols["TicketStatusHistory"])]

    assert message.source == "requester_reply"
    assert attachments == []
    assert run is None
    assert ticket.status == "ai_triage"
    assert ticket.resolved_at is None
    assert ticket.requeue_requested is True
    assert ticket.requeue_trigger == "reopen"
    assert history[0].from_status == "resolved"
    assert history[0].to_status == "ai_triage"
    assert fake_db.existing[(requester.id, ticket.id)].last_viewed_at >= existing_view.last_viewed_at


def test_resolve_ticket_for_requester_updates_status_and_view():
    symbols = _load_ticketing_symbols()
    fake_db = _FakeSession()
    requester = symbols["User"](
        id=uuid.uuid4(),
        email="requester@example.com",
        display_name="Requester",
        password_hash="hash",
        role="requester",
        is_active=True,
    )
    ticket = symbols["Ticket"](
        id=uuid.uuid4(),
        reference_num=2,
        reference="T-000002",
        title="Need help",
        created_by_user_id=requester.id,
        status="waiting_on_user",
        urgent=False,
    )

    symbols["resolve_ticket_for_requester"](fake_db, ticket=ticket, requester=requester)

    history = [item for item in fake_db.added if isinstance(item, symbols["TicketStatusHistory"])]
    views = [item for item in fake_db.added if isinstance(item, symbols["TicketView"])]

    assert ticket.status == "resolved"
    assert ticket.resolved_at is not None
    assert history[0].to_status == "resolved"
    assert views[0].user_id == requester.id
    assert views[0].ticket_id == ticket.id


def test_validate_csrf_token_rejects_mismatch():
    pytest.importorskip("fastapi")
    pytest.importorskip("argon2")
    from fastapi import HTTPException
    from app.auth import validate_csrf_token
    from shared.security import utc_now

    symbols = _load_ticketing_symbols()
    auth_session = symbols["SessionRecord"](
        user_id=uuid.uuid4(),
        token_hash="token",
        csrf_token="expected-token",
        remember_me=False,
        expires_at=utc_now(),
    )

    with pytest.raises(HTTPException) as excinfo:
        validate_csrf_token(auth_session, "wrong-token")
    assert excinfo.value.status_code == 403


def test_session_expiry_and_requester_status_mapping(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("argon2")
    from app.ui import REQUESTER_AUTHOR_LABELS, REQUESTER_STATUS_LABELS
    from shared.security import calculate_session_expiry, utc_now

    settings = _make_settings(tmp_path)
    now = utc_now()

    remember_expiry = calculate_session_expiry(settings, True, now=now)
    default_expiry = calculate_session_expiry(settings, False, now=now)

    assert int((remember_expiry - now).total_seconds()) == 30 * 24 * 60 * 60
    assert int((default_expiry - now).total_seconds()) == 12 * 60 * 60
    assert REQUESTER_STATUS_LABELS["new"] == "Reviewing"
    assert REQUESTER_STATUS_LABELS["waiting_on_user"] == "Waiting for your reply"
    assert REQUESTER_AUTHOR_LABELS["dev_ti"] == "Team"


def test_requester_routes_source_uses_custom_auth_and_explicit_multipart_limits():
    source = Path("app/routes_requester.py").read_text(encoding="utf-8")
    upload_source = Path("app/uploads.py").read_text(encoding="utf-8")
    ui_source = Path("app/ui.py").read_text(encoding="utf-8")
    template_source = Path("app/templates/requester_ticket_detail.html").read_text(encoding="utf-8")

    assert '"/app/tickets/{reference}/reply"' in source
    assert "parse_multipart_form(request, settings)" in source
    assert "require_requester_user" in source
    assert "MULTIPART_PART_SIZE_SLACK_BYTES" in upload_source
    assert "max_part_size=settings.max_image_bytes + MULTIPART_PART_SIZE_SLACK_BYTES" in upload_source
    assert '"dev_ti": "Team"' in ui_source
    assert "requester_author_label(message.author_type)" in source
    assert "message.author_label" in template_source


def test_login_route_sets_remember_me_cookie(monkeypatch, tmp_path):
    stack = _load_web_stack()
    app = stack["create_app"]()
    db = _RouteDb()
    requester = SimpleNamespace(
        id=uuid.uuid4(),
        email="requester@example.com",
        display_name="Requester",
        password_hash="hash",
        role="requester",
        is_active=True,
    )
    settings = _make_settings(tmp_path)
    observed = {}

    def fake_begin_user_session(*, request, response, db, user, remember_me, settings):
        observed["remember_me"] = remember_me
        response.set_cookie(
            "triage_session",
            "opaque-token",
            max_age=settings.session_remember_days * 24 * 60 * 60 if remember_me else None,
            expires=settings.session_remember_days * 24 * 60 * 60 if remember_me else None,
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookies,
            path="/",
        )

    monkeypatch.setattr(stack["routes_auth"], "get_user_by_email", lambda db, email: requester)
    monkeypatch.setattr(stack["routes_auth"], "verify_password", lambda password, password_hash: True)
    monkeypatch.setattr(stack["routes_auth"], "begin_user_session", fake_begin_user_session)

    app.dependency_overrides[stack["db_session_dependency"]] = lambda: db
    app.dependency_overrides[stack["routes_auth"].get_current_user_optional] = lambda: None
    app.dependency_overrides[stack["routes_auth"].get_optional_auth_session] = lambda: None
    app.dependency_overrides[stack["routes_auth"].get_settings_dependency] = lambda: settings

    with stack["TestClient"](app) as client:
        response = client.post(
            "/login",
            data={"email": requester.email, "password": "secret", "remember_me": "on"},
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert response.headers["location"] == "/app"
    assert "Max-Age=2592000" in response.headers["set-cookie"]
    assert observed["remember_me"] is True
    assert db.commit_calls == 1


def test_logout_route_rejects_invalid_csrf_without_committing():
    stack = _load_web_stack()
    app = stack["create_app"]()
    db = _RouteDb()

    app.dependency_overrides[stack["db_session_dependency"]] = lambda: db
    app.dependency_overrides[stack["routes_auth"].get_required_auth_session] = lambda: SimpleNamespace(csrf_token="expected")

    with stack["TestClient"](app) as client:
        response = client.post("/logout", data={"csrf_token": "wrong"}, follow_redirects=False)

    assert response.status_code == 403
    assert db.commit_calls == 0


def test_requester_list_route_does_not_mark_ticket_as_read(monkeypatch):
    stack = _load_web_stack()
    app = stack["create_app"]()
    db = _RouteDb()
    requester = SimpleNamespace(id=uuid.uuid4(), display_name="Requester", role="requester")
    auth_session = SimpleNamespace(csrf_token="csrf-token")
    observed = {"view_updates": 0}

    monkeypatch.setattr(stack["routes_requester"], "_ticket_list_rows", lambda db, requester_id: [])
    monkeypatch.setattr(
        stack["routes_requester"],
        "upsert_ticket_view",
        lambda *args, **kwargs: observed.__setitem__("view_updates", observed["view_updates"] + 1),
    )

    app.dependency_overrides[stack["db_session_dependency"]] = lambda: db
    app.dependency_overrides[stack["routes_requester"].require_requester_user] = lambda: requester
    app.dependency_overrides[stack["routes_requester"].get_required_auth_session] = lambda: auth_session

    with stack["TestClient"](app) as client:
        response = client.get("/app")

    assert response.status_code == 200
    assert observed["view_updates"] == 0


def test_requester_detail_route_marks_ticket_as_read(monkeypatch):
    stack = _load_web_stack()
    app = stack["create_app"]()
    db = _RouteDb()
    requester = SimpleNamespace(id=uuid.uuid4(), display_name="Requester", role="requester")
    auth_session = SimpleNamespace(csrf_token="csrf-token")
    ticket = SimpleNamespace(reference="T-000001", id=uuid.uuid4(), title="Ticket", status="new", urgent=False)
    observed = {"view_updates": 0}

    monkeypatch.setattr(stack["routes_requester"], "_load_requester_ticket_or_404", lambda *args, **kwargs: ticket)
    monkeypatch.setattr(stack["routes_requester"], "_serialize_public_thread", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        stack["routes_requester"],
        "upsert_ticket_view",
        lambda *args, **kwargs: observed.__setitem__("view_updates", observed["view_updates"] + 1),
    )

    app.dependency_overrides[stack["db_session_dependency"]] = lambda: db
    app.dependency_overrides[stack["routes_requester"].require_requester_user] = lambda: requester
    app.dependency_overrides[stack["routes_requester"].get_required_auth_session] = lambda: auth_session

    with stack["TestClient"](app) as client:
        response = client.get(f"/app/tickets/{ticket.reference}")

    assert response.status_code == 200
    assert observed["view_updates"] == 1
    assert db.commit_calls == 1


def test_attachment_download_forbids_non_owner_requester():
    stack = _load_web_stack()
    app = stack["create_app"]()
    db = _RouteDb()
    requester = SimpleNamespace(id=uuid.uuid4(), display_name="Requester", role="requester")
    attachment_id = uuid.uuid4()
    attachment = SimpleNamespace(
        id=attachment_id,
        ticket_id=uuid.uuid4(),
        visibility="public",
        mime_type="image/png",
        stored_path="/tmp/test.png",
        original_filename="shot.png",
    )
    other_ticket = SimpleNamespace(id=attachment.ticket_id, created_by_user_id=uuid.uuid4())
    from shared.models import Ticket, TicketAttachment

    db.objects[(TicketAttachment, attachment_id)] = attachment
    db.objects[(Ticket, attachment.ticket_id)] = other_ticket

    app.dependency_overrides[stack["db_session_dependency"]] = lambda: db
    app.dependency_overrides[stack["routes_requester"].get_current_user] = lambda: requester

    with stack["TestClient"](app) as client:
        response = client.get(f"/attachments/{attachment_id}")

    assert response.status_code == 403
    assert db.commit_calls == 0
