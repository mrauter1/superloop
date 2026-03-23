# Test Strategy

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: test
- Phase ID: ai-worker
- Phase Directory Key: ai-worker
- Phase Title: AI Worker and Codex Orchestration
- Scope: phase-local producer artifact

## Behavior-to-test coverage map
- AC-1 worker/Codex contract:
  - `tests/test_ai_worker.py::test_prepare_codex_run_writes_prompt_and_schema`
  - `tests/test_ai_worker.py::test_build_codex_command_matches_required_contract`
  - `tests/test_ai_worker.py::test_process_ai_run_marks_failed_when_codex_errors`
- AC-2 successful non-superseded publication order:
  - `tests/test_ai_worker.py::test_apply_success_result_publishes_internal_note_before_public_action`
- AC-3 stale requester-visible input suppression:
  - `tests/test_ai_worker.py::test_apply_success_result_supersedes_stale_run_without_publication`
- AC-4 internal-note prompt-only influence:
  - `tests/test_ai_worker.py::test_requester_visible_fingerprint_excludes_internal_messages`
  - `tests/test_ai_worker.py::test_build_triage_prompt_includes_public_and_internal_context`

## Preserved invariants checked
- Unchanged input skip path remains non-publishing and non-transitioning:
  - `tests/test_ai_worker.py::test_prepare_run_skips_when_last_processed_hash_matches`
- Skip handling is also asserted against a non-`ai_triage` starting status so a skipped run cannot silently normalize a status transition:
  - `tests/test_ai_worker.py::test_prepare_run_skip_does_not_change_non_ai_triage_status`
- Invalid low-confidence auto-reply output is rejected before publication:
  - `tests/test_ai_worker.py::test_validate_triage_result_enforces_auto_reply_threshold`
- Unexpected publication errors are converted into `_mark_failed()` instead of leaving runs stranded:
  - `tests/test_ai_worker.py::test_process_ai_run_marks_failed_when_publication_step_raises`
- Heartbeat emission stays independent of the blocking worker loop:
  - `tests/test_ai_worker.py::test_heartbeat_loop_emits_while_stop_event_controls_exit`

## Edge cases
- Internal notes changing alone do not perturb requester-visible fingerprints.
- Skip logic still drains deferred requeue without a second status mutation.
- Prompt generation preserves separate public/internal sections.

## Failure paths
- Codex execution errors route to `_mark_failed()`.
- Unexpected success-publication exceptions route to `_mark_failed()`.
- `_mark_failed()` itself publishes the internal failure note, transitions the ticket to `waiting_on_dev_ti`, and drains deferred requeue:
  - `tests/test_ai_worker.py::test_mark_failed_publishes_internal_failure_note_and_routes_ticket`
- Low-confidence auto-reply payloads fail validation instead of publishing.

## Stabilization approach
- Worker tests stay deterministic by monkeypatching session scopes, Codex execution, and publication helpers instead of invoking a live database or Codex binary.
- The heartbeat test uses a local stop event and zero-second interval to avoid timing flakes.

## Known gaps
- No live integration test currently exercises the full worker loop against a real PostgreSQL database and real Codex artifacts; coverage remains unit-level and contract-focused.
- In this minimal environment the worker test module remains dependency-gated behind the existing lazy imports, so the new unit tests compile but may skip unless SQLAlchemy/argon2/pydantic are installed.
