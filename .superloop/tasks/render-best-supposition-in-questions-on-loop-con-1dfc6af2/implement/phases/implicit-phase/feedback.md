# Implement ↔ Code Reviewer Feedback

- Task ID: render-best-supposition-in-questions-on-loop-con-1dfc6af2
- Pair: implement
- Phase ID: implicit-phase
- Phase Directory Key: implicit-phase
- Phase Title: Implicit single phase
- Scope: phase-local authoritative verifier artifact

- IMP-001 `blocking` [superloop.py::format_question] The new formatter always appends a synthetic `Best supposition:` line whenever `best_supposition` is present. That contradicts the settled repo design in `Refactor.md` to preserve the prompt-defined question body, and it regresses existing canonical question payloads that already embed `Best supposition:` inside `question` (for example the existing observability fixtures around `question":"Need confirmation?\nBest supposition: proceed safely."`). In that common case the user will now see the supposition twice and the duplicated body will also be written into clarification logs/decisions. Minimal fix: keep `control.question.text` as the default rendered body and only fall back to synthesizing a supposition line when the question text itself does not already carry one.
- IMP-002 `non-blocking` [superloop.py::execute_pair_cycles] `retry_producer_parse_once` and `retry_verifier_parse_once` duplicate the same retry/log/session-note/rerun flow in two large inline blocks. The behavior is currently aligned, but future edits to retry logging, event emission, or session-note handling now need to be made in both places. Minimal fix: extract one shared helper in `superloop.py` that accepts the phase-specific template inputs and performs the common retry path for both producer and verifier.

Review pass cycle=2 attempt=1:
- No remaining findings in scope.
- IMP-001 resolved by preserving prompt-defined question text and only synthesizing a fallback `Best supposition:` line when the body does not already include one.
- IMP-002 resolved by centralizing the retry-on-parse-error flow in `retry_phase_after_parse_error(...)`.

Review pass cycle=1 attempt=1:
- No blocking findings in scope.
- Verified `format_question(...)` preserves an existing inline `Best supposition:` line and only synthesizes the fallback line when the question body lacks one.
- Verified malformed producer/verifier loop-control retries are centralized in `retry_phase_after_parse_error(...)`.
- Validation: `PYTHONPATH=/workspace/superloop pytest -q /workspace/superloop/tests/test_superloop_observability.py /workspace/superloop/tests/test_phase_local_behavior.py /workspace/superloop/tests/test_loop_control.py` (`116 passed`).
