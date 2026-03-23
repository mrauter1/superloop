# Implement ↔ Code Reviewer Feedback

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: implement
- Phase ID: foundation-persistence
- Phase Directory Key: foundation-persistence
- Phase Title: Foundation and Persistence
- Scope: phase-local authoritative verifier artifact

- `IMP-001` `blocking` [shared/ticketing.py:83] `create_pending_ai_run()` is not queue-safe even though this phase is supposed to establish queue-safe run creation. It does a separate `has_active_ai_run()` read and then inserts, so two concurrent requester replies/manual reruns can both observe “no active run”; one of them will then trip the partial unique index and abort the whole transaction instead of cleanly returning `None` or converting to requeue behavior. Minimal fix: make this helper own the race by using a single transaction-safe insert path, or catch/normalize the `IntegrityError` raised by the partial unique index inside the helper.
- `IMP-002` `blocking` [shared/ticketing.py:37] `record_status_change()` cannot produce the required initial `ticket_status_history` row of `from_status = null` to `to_status = new`. The helper always copies `ticket.status` into `from_status`, which means later phases must either violate the PRD on initial ticket creation or bypass the shared status-history primitive that the decisions ledger says should own this logic. Minimal fix: extend the helper with an explicit initial/override mode so initial creation and later transitions both stay on the shared path.
- `IMP-003` `non-blocking` [shared/migrations/env.py:12] [shared/config.py:103] Alembic startup is coupled to the full application settings loader, which means schema bootstrap now requires unrelated runtime secrets like `CODEX_API_KEY` and the full workspace/app configuration just to read `DATABASE_URL`. That is operationally brittle for the PRD bootstrap step that starts with “create database schema with Alembic.” Minimal fix: let the Alembic environment read `DATABASE_URL` directly, or add a DB-only settings loader used only by migrations.

- Review cycle 2: `IMP-001`, `IMP-002`, and `IMP-003` are resolved in the current diff. No new findings were identified in the touched scope.
