# Implementation Notes

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: implement
- Phase ID: foundation-persistence
- Phase Directory Key: foundation-persistence
- Phase Title: Foundation and Persistence
- Scope: phase-local producer artifact

## Files changed

- `README.md`, `.env.example`, `requirements.txt`, `alembic.ini`
- `app/__init__.py`, `app/auth.py`, `app/main.py`, `app/render.py`, `app/routes_auth.py`, `app/routes_requester.py`, `app/routes_ops.py`, `app/uploads.py`, `app/templates/base.html`, `app/static/app.css`
- `shared/__init__.py`, `shared/contracts.py`, `shared/config.py`, `shared/db.py`, `shared/models.py`, `shared/security.py`, `shared/permissions.py`, `shared/sessions.py`, `shared/ticketing.py`, `shared/user_admin.py`, `shared/workspace.py`
- `shared/migrations/env.py`, `shared/migrations/script.py.mako`, `shared/migrations/versions/20260323_0001_initial.py`, `shared/migrations/README`
- `worker/__init__.py`, `worker/main.py`, `worker/queue.py`, `worker/ticket_loader.py`, `worker/triage.py`, `worker/codex_runner.py`
- `scripts/bootstrap_workspace.py`, `scripts/create_admin.py`, `scripts/create_user.py`, `scripts/set_password.py`, `scripts/deactivate_user.py`, `scripts/run_web.py`, `scripts/run_worker.py`
- `.superloop/tasks/i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7/decisions.txt`

## Symbols touched

- Config/contracts: `Settings`, `get_settings`, `APP_ROUTES`, `CLI_COMMAND_NAMES`, exact workspace file/template constants, prompt/schema constants
- Config/contracts: `get_database_url`
- Persistence: `Base`, `get_engine`, `get_session_factory`, `session_scope`, `db_session_dependency`, ORM models for all Stage 1 tables, initial Alembic revision `20260323_0001`
- Security/session: `hash_password`, `verify_password`, `hash_token`, `create_server_session`, `get_valid_session_by_token`, `validate_csrf_token`
- Shared ticket primitives: `reserve_ticket_reference`, `generate_provisional_title`, `record_status_change`, `upsert_ticket_view`, `create_pending_ai_run`, `request_requeue`, `supersede_pending_drafts`, `ensure_system_state_defaults`
- Workspace/bootstrap: `bootstrap_workspace`, `verify_workspace_mounts`, `ensure_uploads_dir`, `workspace_contract_snapshot`
- Worker foundations: `claim_oldest_pending_run`, `load_ticket_context`, `build_requester_visible_fingerprint`, `build_codex_command`, `update_worker_heartbeat`

## Checklist mapping

- AC-1: created the Stage 1 package skeleton, dependency manifest, env example, templates/static directories, and run/bootstrap/admin scripts
- AC-2: implemented the full initial schema and constraints, including PostgreSQL-backed `sessions` and the partial unique active `ai_runs` index
- AC-3: implemented workspace bootstrap that writes the exact PRD `AGENTS.md` and `SKILL.md`, initializes a git repo, creates an empty initial commit, and verifies repo/manual mounts
- AC-4: centralized route/CLI/env/filesystem/workspace prompt/schema contracts under `shared/contracts.py` and `shared/config.py`

## Assumptions

- The repository remains greenfield for this phase; no legacy code or data migration compatibility work was required.
- Runtime installation of dependencies is handled outside this turn; this environment did not have `alembic` available as a CLI binary for an offline SQL render check.

## Preserved invariants

- Primary auth state is server-side and database-backed; no signed-cookie session middleware is used.
- Shared helpers own status history, ticket `updated_at` touching, ticket-view upserts, and active-run/requeue primitives.
- Pending `ai_runs` creation now treats the partial unique index as the source of truth under concurrency and normalizes the active-run race inside the helper.
- The shared status-history helper can now represent the mandated initial `null -> new` transition without bypass logic in later phases.
- Workspace bootstrap writes the exact mandated file contents under the exact mandated paths.
- The worker heartbeat cadence is kept separate from poll cadence so the 60-second heartbeat contract can remain stable when the queue loop evolves later.

## Intended behavior changes

- The repo now contains a runnable Stage 1 scaffold with contract-sensitive persistence and bootstrap foundations rather than only PRD/planning artifacts.

## Known non-changes

- Requester UI flows, Dev/TI UI flows, and Codex publication/action logic are still deferred to later phases.
- No attempt was made to implement the full route surface yet beyond health/readiness and foundational auth/session helpers.
- No tests were added in this phase; validation stayed at compile/bootstrap/contract level.

## Expected side effects

- `python scripts/bootstrap_workspace.py` now creates upload/workspace directories, initializes the workspace git repo if absent, and writes the exact workspace control files.
- `python scripts/create_admin.py`, `create_user.py`, `set_password.py`, and `deactivate_user.py` now provide the required local-account management entry points.

## Validation performed

- `python -m compileall app shared worker scripts`
- Disposable bootstrap run with environment overrides to verify workspace initialization, empty initial commit creation, and exact `AGENTS.md` / `SKILL.md` output
- Direct import check for route/CLI/workspace contract constants
- `python -m compileall shared` after the reviewer-driven fixes
- Direct `DATABASE_URL` loader check for the Alembic DB-only settings path
- Attempted lightweight helper import validation, but the environment does not have installed runtime dependencies such as SQLAlchemy

## Deduplication / centralization decisions

- Contract-sensitive strings and path/route/CLI names were centralized in `shared/contracts.py` instead of scattering copies across scripts and future worker modules.
- Session creation/lookup and ticket mutation primitives were kept in shared modules so later requester, ops, and worker code paths can reuse them instead of hand-rolling state transitions.
