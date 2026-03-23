# Implementation Notes

- Task ID: render-best-supposition-in-questions-on-loop-con-1dfc6af2
- Pair: implement
- Phase ID: implicit-phase
- Phase Directory Key: implicit-phase
- Phase Title: Implicit single phase
- Scope: phase-local producer artifact

## Files changed
- `superloop.py`
- `tests/test_superloop_observability.py`
- `.superloop/tasks/render-best-supposition-in-questions-on-loop-con-1dfc6af2/decisions.txt`
- `.superloop/tasks/render-best-supposition-in-questions-on-loop-con-1dfc6af2/implement/phases/implicit-phase/implementation_notes.md`

## Symbols touched
- `format_question`
- `build_loop_control_retry_feedback`
- `set_pending_session_note`
- `retry_phase_after_parse_error`
- `parse_phase_control`
- `execute_pair_cycles`

## Checklist mapping
- `plan/plan.md` contains no implementation checklist items; implemented the request directly.

## Assumptions
- The retry-once requirement applies to malformed loop-control emitted by either producer or verifier phases.

## Preserved invariants
- Valid canonical and legacy loop-control parsing behavior remains unchanged.
- A second malformed loop-control response still fails the run immediately.
- Retry stays in the same cycle/attempt and reuses the same phase session file/thread.
- Question bodies that already include an inline `Best supposition:` line are preserved verbatim.

## Intended behavior changes
- Runtime questions preserve prompt-defined `question` text and only render a fallback `Best supposition: ...` line when canonical loop-control provides `best_supposition` but the body does not already include one.
- On the first loop-control parse failure, Superloop records parse feedback, injects that feedback into the next phase prompt via the session note, and retries the same phase once before failing.

## Known non-changes
- No prompt template files changed.
- `legacy/` code paths were left untouched.

## Expected side effects
- Raw phase logs can now include `entry=loop_control_retry`.
- Retried malformed phases emit one additional agent execution for the same cycle/attempt.

## Validation performed
- `PYTHONPATH=/workspace/superloop pytest -q /workspace/superloop/tests/test_superloop_observability.py /workspace/superloop/tests/test_phase_local_behavior.py /workspace/superloop/tests/test_loop_control.py`

## Deduplication or centralization decisions
- Reused the existing session `pending_clarification_note` mechanism for parse retry feedback instead of adding a separate retry prompt channel.
- Centralized the producer/verifier retry-on-parse-error flow in `retry_phase_after_parse_error` so logging, session-note injection, and retry execution stay aligned.
