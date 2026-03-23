# Test Author ↔ Test Auditor Feedback

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: test
- Phase ID: foundation-persistence
- Phase Directory Key: foundation-persistence
- Phase Title: Foundation and Persistence
- Scope: phase-local authoritative verifier artifact

- Added focused regression tests for queue-safe ai-run creation, initial status-history override support, DB-only Alembic config loading, workspace bootstrap exact-file behavior, missing-mount failure handling, and the contract constants surface.
- Tightened the ai-run helper tests to assert nested savepoint usage and added source-level regression checks for `shared/migrations/env.py` plus the initial migration’s required `sessions` table and active `ai_runs` partial unique index.
- `TST-001` `blocking` [tests/test_foundation_persistence.py:84] The ai-run helper tests never assert that `create_pending_ai_run()` actually uses `begin_nested()` / savepoint semantics. A regression back to `db.add(); db.flush()` would still satisfy the current fake-session assertions while silently reintroducing the poisoned-session failure mode the reviewer just had fixed. Minimal correction: instrument the fake session to record `begin_nested()` calls and assert that the helper enters a nested transaction on both the success and handled-conflict paths.
- `TST-002` `blocking` [tests/test_foundation_persistence.py:152] The new test only proves that `get_database_url()` reads `DATABASE_URL`; it does not verify that [shared/migrations/env.py](/workspace/superloop/AutoSac/shared/migrations/env.py) actually uses that DB-only path instead of reverting to `get_settings()`. The reviewer-driven Alembic fix could regress without any test failing. Minimal correction: add a focused regression test for the migration environment module itself, for example by asserting the file content/import path or by importing it with a stubbed Alembic context and environment.
- `TST-003` `blocking` [tests/test_foundation_persistence.py:1] [test_strategy.md](/workspace/superloop/AutoSac/.superloop/tasks/i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7/test/phases/foundation-persistence/test_strategy.md) The phase acceptance criteria include the full initial migration contract, including the `sessions` table and active `ai_runs` partial unique index, but the added suite has no regression check for the migration artifact at all. A future edit could drop or rename those schema guarantees while all current tests still pass. Minimal correction: add migration-level assertions against [shared/migrations/versions/20260323_0001_initial.py](/workspace/superloop/AutoSac/shared/migrations/versions/20260323_0001_initial.py) for the required tables/index names or inspect SQLAlchemy metadata/migration text directly.

- Audit cycle 2: `TST-001`, `TST-002`, and `TST-003` are resolved in the current diff. No new findings were identified in the touched scope.
