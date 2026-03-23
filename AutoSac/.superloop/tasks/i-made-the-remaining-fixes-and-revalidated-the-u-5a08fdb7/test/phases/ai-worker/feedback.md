# Test Author ↔ Test Auditor Feedback

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: test
- Phase ID: ai-worker
- Phase Directory Key: ai-worker
- Phase Title: AI Worker and Codex Orchestration
- Scope: phase-local authoritative verifier artifact

- Added `tests/test_ai_worker.py` coverage for prompt inclusion of internal/public message context, Codex-error failure routing into `_mark_failed()`, the publication-failure terminal-state fallback, and the decoupled heartbeat loop, while preserving the existing command/fingerprint/publication-order assertions.

- TST-001 `blocking` — `tests/test_ai_worker.py::test_prepare_run_skips_when_last_processed_hash_matches` only exercises the skip path when the ticket already starts in `status="ai_triage"` (`tests/test_ai_worker.py:232-297`). The PRD, however, requires skipped runs to make no status change at all. Because the current test fixture never starts from a different status, it would not catch a regression where `_prepare_run()` mutates a `waiting_on_user` or `waiting_on_dev_ti` ticket to `ai_triage` before discovering the run should be skipped (`worker/triage.py:150-180`). Minimal correction: add a skip-path test with a non-`ai_triage` starting status and assert that both the ticket status and status-history side effects remain unchanged when the run is marked `skipped`.

- TST-002 `blocking` — the new failure-path coverage stops at “`_mark_failed()` was called” (`tests/test_ai_worker.py:416-435`) and never verifies the required side effects inside `_mark_failed()` itself (`worker/triage.py:301-328`). A regression that drops the internal failure note, forgets to move the ticket to `waiting_on_dev_ti`, or skips deferred requeue processing would still pass. Minimal correction: add a focused unit test for `_mark_failed()` with a fake session/ticket/run that asserts the run terminal state, failure-note publication, status transition behavior, and deferred requeue invocation.

- Added follow-up coverage in `tests/test_ai_worker.py` for the non-`ai_triage` skip invariant and `_mark_failed()` side effects, and refreshed `test_strategy.md` to map those checks explicitly. In this environment the worker test module still skips behind the existing lazy dependency gates, so validation confirmed compilation plus the suite-level skip behavior (`pytest -q tests/test_ai_worker.py` and `pytest -q`).

Cycle 2 re-audit:
- TST-001 resolved: `tests/test_ai_worker.py::test_prepare_run_skip_does_not_change_non_ai_triage_status` now covers the skipped-run invariant from a non-`ai_triage` starting status and would catch an unintended status normalization.
- TST-002 resolved: `tests/test_ai_worker.py::test_mark_failed_publishes_internal_failure_note_and_routes_ticket` now asserts the required `_mark_failed()` side effects instead of only checking that the helper was invoked.
- No remaining blocking findings in phase scope.
