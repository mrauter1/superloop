# Test Strategy

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: test
- Phase ID: foundation-persistence
- Phase Directory Key: foundation-persistence
- Phase Title: Foundation and Persistence
- Scope: phase-local producer artifact

## Behavior-to-test coverage map

- Queue-safe run creation:
  `create_pending_ai_run()` happy path, partial-unique-index conflict normalization, unrelated `IntegrityError` re-raise, and explicit nested-savepoint usage.
- Status-history primitive:
  `record_status_change()` supports the required initial `null -> new` transition via explicit override without bypassing the shared helper.
- Bootstrap/config contracts:
  `get_database_url()` only depends on `DATABASE_URL`; `shared/migrations/env.py` uses the DB-only helper; `bootstrap_workspace()` writes the exact `AGENTS.md` and `SKILL.md` content, creates the workspace git repo, and fails when required mounts are missing.
- Migration artifact contract:
  the initial migration source contains the required `sessions` table and the active `ai_runs` partial unique index.
- Stable contract surfaces:
  `CLI_COMMAND_NAMES` and `APP_ROUTES` expose the required command and route contracts.

## Preserved invariants checked

- The ai-run helper treats the DB partial unique index race as a benign `None` result rather than an unhandled transaction failure.
- The ai-run helper enters a nested savepoint path before flushing the insert.
- The initial status-history row can be represented on the shared helper path.
- Workspace bootstrap keeps the exact PRD-controlled file contents and initializes an empty commit.
- The Alembic environment module remains wired to the DB-only loader and the migration source keeps the required Stage 1 schema markers.

## Edge cases and failure paths

- Duplicate active-run conflict on flush.
- Unrelated `IntegrityError` during ai-run creation.
- Missing manuals mount during workspace bootstrap.
- Missing unrelated env vars while `DATABASE_URL` is still available.

## Flake risks and stabilization

- Git bootstrap is isolated to a temporary workspace directory and validated with `git rev-parse --verify HEAD`.
- No network, time, or ordering-sensitive assertions are used.
- Tests that exercise SQLAlchemy-backed helpers skip cleanly when the runtime dependency is not installed, while source/bootstrap contract checks still execute.

## Known gaps

- No live PostgreSQL migration execution coverage in this phase; ai-run conflict handling and migration assertions stay deterministic by testing helper/source contracts rather than a real database.
- No runtime CLI invocation coverage because the current environment may not have the full Python dependency set installed.
