from __future__ import annotations

from pathlib import Path
import subprocess
import uuid

import pytest

from shared.config import Settings, get_database_url
from shared.contracts import (
    APP_ROUTES,
    CLI_COMMAND_NAMES,
    WORKSPACE_AGENTS_CONTENT,
    WORKSPACE_SKILL_CONTENT,
)
from shared.workspace import bootstrap_workspace


class _FakeNestedTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, flush_exc: Exception | None = None):
        self.added = []
        self.flush_exc = flush_exc
        self.flush_calls = 0
        self.begin_nested_calls = 0

    def add(self, item):
        self.added.append(item)

    def flush(self):
        self.flush_calls += 1
        if self.flush_exc is not None:
            raise self.flush_exc

    def begin_nested(self):
        self.begin_nested_calls += 1
        return _FakeNestedTransaction()


def _make_settings(tmp_path: Path) -> Settings:
    workspace_dir = tmp_path / "workspace"
    return Settings(
        app_base_url="http://localhost:8000",
        app_secret_key="test-secret",
        database_url="postgresql+psycopg://triage:triage@localhost:5432/triage",
        uploads_dir=tmp_path / "uploads",
        triage_workspace_dir=workspace_dir,
        repo_mount_dir=workspace_dir / "app",
        manuals_mount_dir=workspace_dir / "manuals",
        codex_bin="codex",
        codex_api_key="test-key",
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


def _load_ticketing_dependencies():
    pytest.importorskip("sqlalchemy")
    from sqlalchemy.exc import IntegrityError
    from shared.models import AIRun, Ticket
    from shared.ticketing import create_pending_ai_run, record_status_change

    return IntegrityError, AIRun, Ticket, create_pending_ai_run, record_status_change


def _make_ticket(*, status: str = "new"):
    _, _, Ticket, _, _ = _load_ticketing_dependencies()
    return Ticket(
        id=uuid.uuid4(),
        reference_num=1,
        reference="T-000001",
        title="Ticket",
        created_by_user_id=uuid.uuid4(),
        status=status,
        urgent=False,
    )


def test_create_pending_ai_run_returns_run_on_success():
    _, AIRun, _, create_pending_ai_run, _ = _load_ticketing_dependencies()
    session = _FakeSession()

    run = create_pending_ai_run(
        session,
        ticket_id=uuid.uuid4(),
        triggered_by="manual_rerun",
    )

    assert isinstance(run, AIRun)
    assert run.status == "pending"
    assert run.triggered_by == "manual_rerun"
    assert session.added == [run]
    assert session.begin_nested_calls == 1
    assert session.flush_calls == 1


def test_create_pending_ai_run_returns_none_for_active_run_conflict():
    IntegrityError, _, _, create_pending_ai_run, _ = _load_ticketing_dependencies()
    conflict = IntegrityError(
        "INSERT INTO ai_runs ...",
        params={},
        orig=Exception("duplicate key value violates unique constraint \"uq_ai_runs_active_ticket\""),
    )
    session = _FakeSession(flush_exc=conflict)

    run = create_pending_ai_run(
        session,
        ticket_id=uuid.uuid4(),
        triggered_by="requester_reply",
    )

    assert run is None
    assert session.begin_nested_calls == 1
    assert session.flush_calls == 1


def test_create_pending_ai_run_reraises_unrelated_integrity_errors():
    IntegrityError, _, _, create_pending_ai_run, _ = _load_ticketing_dependencies()
    unrelated = IntegrityError(
        "INSERT INTO ai_runs ...",
        params={},
        orig=Exception("violates foreign key constraint"),
    )
    session = _FakeSession(flush_exc=unrelated)

    with pytest.raises(IntegrityError):
        create_pending_ai_run(
            session,
            ticket_id=uuid.uuid4(),
            triggered_by="requester_reply",
        )


def test_record_status_change_supports_initial_null_transition():
    _, _, _, _, record_status_change = _load_ticketing_dependencies()
    ticket = _make_ticket(status="new")
    session = _FakeSession()

    history = record_status_change(
        session,
        ticket=ticket,
        to_status="new",
        changed_by_type="system",
        from_status_override=None,
    )

    assert history.from_status is None
    assert history.to_status == "new"
    assert ticket.status == "new"
    assert session.added == [history]


def test_get_database_url_reads_only_database_url(monkeypatch):
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://triage:triage@localhost:5432/triage")

    assert get_database_url() == "postgresql+psycopg://triage:triage@localhost:5432/triage"


def test_alembic_env_uses_database_url_helper():
    env_source = Path("shared/migrations/env.py").read_text(encoding="utf-8")

    assert "from shared.config import get_database_url" in env_source
    assert "database_url = get_database_url()" in env_source
    assert "get_settings" not in env_source


def test_bootstrap_workspace_writes_exact_files_and_initializes_git_repo(tmp_path):
    settings = _make_settings(tmp_path)
    settings.repo_mount_dir.mkdir(parents=True)
    settings.manuals_mount_dir.mkdir(parents=True)

    bootstrap_workspace(settings)

    assert settings.workspace_agents_path.read_text(encoding="utf-8") == WORKSPACE_AGENTS_CONTENT
    assert settings.workspace_skill_path.read_text(encoding="utf-8") == WORKSPACE_SKILL_CONTENT
    assert (settings.triage_workspace_dir / ".git").is_dir()
    subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=settings.triage_workspace_dir,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_bootstrap_workspace_requires_repo_and_manual_mounts(tmp_path):
    settings = _make_settings(tmp_path)
    settings.repo_mount_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError):
        bootstrap_workspace(settings)


def test_contract_constants_expose_required_route_and_cli_contracts():
    assert "create-admin" in CLI_COMMAND_NAMES
    assert "create-user" in CLI_COMMAND_NAMES
    assert "/login" in APP_ROUTES
    assert "/ops/drafts/{draft_id}/approve-publish" in APP_ROUTES


def test_initial_migration_contains_required_sessions_table_and_active_run_index():
    migration_source = Path("shared/migrations/versions/20260323_0001_initial.py").read_text(encoding="utf-8")

    assert 'op.create_table(\n        "sessions"' in migration_source
    assert 'op.create_table(\n        "ai_runs"' in migration_source
    assert "CREATE UNIQUE INDEX uq_ai_runs_active_ticket ON ai_runs (ticket_id) WHERE status IN ('pending', 'running')" in migration_source
