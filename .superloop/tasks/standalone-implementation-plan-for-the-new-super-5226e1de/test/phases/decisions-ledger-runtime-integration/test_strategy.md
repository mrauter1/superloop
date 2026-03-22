# Test Strategy

- Task ID: standalone-implementation-plan-for-the-new-super-5226e1de
- Pair: test
- Phase ID: decisions-ledger-runtime-integration
- Phase Directory Key: decisions-ledger-runtime-integration
- Phase Title: Integrate runtime-managed decisions ledger behavior
- Scope: phase-local producer artifact

## Behavior To Test Coverage Map
- Decisions header parsing and sequence allocation: covered in `tests/test_phase_local_behavior.py::test_decisions_header_parsing_and_sequence_allocation`.
- Clarification persistence to `decisions.txt` plus session-note preservation: covered in `tests/test_phase_local_behavior.py::test_append_clarification_persists_to_phase_session_only` and `tests/test_superloop_observability.py::test_append_clarification_logs_to_raw_phase_log_and_updates_session`.
- Producer question turn with empty producer block: covered in `tests/test_superloop_observability.py::test_execute_pair_cycles_removes_empty_producer_block_before_runtime_question_blocks`.
- Producer question turn with non-empty producer block: covered in `tests/test_superloop_observability.py::test_execute_pair_cycles_preserves_non_empty_producer_block_on_question_turn`.
- Verifier turn read-only behavior for producer headers: covered in `tests/test_superloop_observability.py::test_execute_pair_cycles_does_not_precreate_verifier_decision_header`.

## Preserved Invariants Checked
- Questions and answers share the same `qa_seq` and questioning-turn `turn_seq`.
- Empty producer headers are removed, but non-empty producer bodies remain in append-only order ahead of runtime question/answer blocks.
- Runtime clarification writes do not replace raw-log authority or phase-scoped session note updates.
- Verifier turns do not receive producer-owned `decisions.txt` headers.

## Edge Cases And Failure Paths
- Empty producer body on a clarification turn.
- Non-empty producer body on a clarification turn.
- Fresh decisions ledger with no prior headers.
- New `(run_id, pair, phase_id)` stream starting at `turn_seq=1`.

## Known Gaps
- No dedicated git-mode assertion was added for decisions-ledger commits in this phase because the existing git-tracking tests already cover tracked-path filtering and commit scope behavior.

## Validation
- `PYTHONPATH=/workspace/superloop pytest -q tests/test_phase_local_behavior.py`
- `PYTHONPATH=/workspace/superloop pytest -q tests/test_superloop_observability.py`
