# Test Author ↔ Test Auditor Feedback

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: test
- Phase ID: ops-workflow
- Phase Directory Key: ops-workflow
- Phase Title: Dev/TI Workflow Surface
- Scope: phase-local authoritative verifier artifact

- Added ops-workflow regression coverage in `tests/test_ops_workflow.py` for shared helper happy/edge/failure paths, list/board/detail read semantics, requester ops denial, and source-level assertions for required filters plus public/internal/AI panels.
- TST-001 | blocking | `tests/test_ops_workflow.py::test_request_manual_rerun_creates_pending_run_and_moves_ticket_to_ai_triage` monkeypatches `shared.ticketing.create_pending_ai_run` with `lambda **kwargs: expected_run`, but the production helper is called with a positional `db` argument. Once the FastAPI/SQLAlchemy/argon2 stack is present and this test stops skipping, it will fail before exercising the idle manual-rerun branch, leaving the exact `waiting_on_dev_ti -> ai_triage` behavior called out in the phase contract unprotected. Minimal fix: make the stub signature compatible with the real call shape, e.g. `lambda *args, **kwargs: expected_run`, and rerun the dependency-backed suite.
- TST-002 | blocking | AC-3 requires that requesters cannot access any `/ops` surface, but the suite only asserts denial for `GET /ops`. There is no equivalent protection for `GET /ops/board` or `GET /ops/tickets/{reference}`, so a future regression opening those surfaces to requesters would still pass the current tests. Minimal fix: add requester-denial coverage for the board and detail routes, or equivalent source-level assertions tied specifically to those route dependencies if the runtime stack is unavailable.
- Follow-up: fixed the idle manual-rerun stub signature, added requester-denial tests for `/ops/board` and `/ops/tickets/{reference}`, and reran the phase regression bundle.
- Re-audit result: no remaining blocking findings after the follow-up fixes; the current suite now protects the audited idle-rerun branch and requester denial across the full ops GET surface.
