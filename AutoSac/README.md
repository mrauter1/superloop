# Stage 1 AI Triage MVP

Greenfield implementation of the Stage 1 internal AI triage system described in `Autosac_PRD.md`.

## Stack

- Python 3.12
- FastAPI + Jinja2 + HTMX
- PostgreSQL 16
- SQLAlchemy 2.x + Alembic
- Custom PostgreSQL-backed session auth
- Separate worker process for Codex orchestration

## Repository layout

```text
app/      FastAPI app surface and web-layer helpers
worker/   Queue, ticket loading, fingerprinting, and Codex execution helpers
shared/   Config, DB, models, migrations, security, permissions, workspace contracts
scripts/  Bootstrap, admin/user management, and local run entry points
```

## Local setup

1. Copy `.env.example` to `.env` and fill in required values.
2. Install dependencies from `requirements.txt`.
3. Run Alembic migrations.
4. Run `python scripts/bootstrap_workspace.py`.
5. Create an admin with `python scripts/create_admin.py`.
6. Start the web and worker processes with `python scripts/run_web.py` and `python scripts/run_worker.py`.

## Acceptance Validation

Run the same local checks used for the hardening phase:

1. Ensure `.env` contains the required Stage 1 variables from `.env.example`.
2. Run `python scripts/bootstrap_workspace.py` and confirm it prints the workspace contract paths.
3. Run `python scripts/run_web.py --check` to validate the web entrypoint, `/healthz`, and `/readyz` against the current local environment.
4. Verify `GET /readyz` returns `{"status":"ready"}` only when the database and required workspace paths are available.
5. Run `python scripts/run_worker.py --check` to validate the worker entrypoint against the current local environment, then start the long-running worker with `python scripts/run_worker.py`.
6. Run `pytest` to execute the regression suite for auth/session, uploads, requester/ops permissions, worker queueing, stale-run suppression, drafts, bootstrap exactness, rendering sanitization, and readiness behavior.

The repository now includes the Stage 1 scaffold, shared workflow logic, Codex worker integration, structured logging, readiness checks, and regression coverage for the main PRD invariants.
