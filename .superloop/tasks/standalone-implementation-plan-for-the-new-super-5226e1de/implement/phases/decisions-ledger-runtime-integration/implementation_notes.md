# Implementation Notes

- Task ID: standalone-implementation-plan-for-the-new-super-5226e1de
- Pair: implement
- Phase ID: decisions-ledger-runtime-integration
- Phase Directory Key: decisions-ledger-runtime-integration
- Phase Title: Integrate runtime-managed decisions ledger behavior
- Scope: phase-local producer artifact

## Files Changed
- `superloop.py`
- `tests/test_phase_local_behavior.py`
- `tests/test_superloop_observability.py`

## Symbols Touched
- `decisions_file(...)`
- `decisions_phase_id(...)`
- `decisions_owner(...)`
- `parse_decisions_headers(...)`
- `next_decisions_block_seq(...)`
- `next_decisions_qa_seq(...)`
- `next_decisions_turn_seq(...)`
- `append_decisions_header(...)`
- `append_decisions_runtime_block(...)`
- `remove_trailing_empty_decisions_block(...)`
- `append_clarification(...)`
- `execute_pair_cycles(...)`
- `ensure_workspace(...)`

## Checklist Mapping
- Plan Phase 3: added direct decisions header parsing, sequence allocation, runtime header append, runtime question/answer block append, and trailing empty producer-block cleanup in `superloop.py`.
- Plan Phase 3: integrated producer pre-header creation only for producer turns, with no verifier pre-header path.
- Plan Phase 4 regression coverage relevant to this slice: added tests for parsing/sequencing, clarification-to-decisions persistence, producer-question ordering, and verifier no-header behavior.

## Assumptions
- Runtime question and answer blocks should share the questioning turn's `turn_seq` so they remain linked to the originating turn in the same `(run_id, pair, phase_id)` stream.
- Question and answer bodies should be appended verbatim to `decisions.txt` without `Question:` / `Answer:` wrappers; those wrappers remain raw-log only.

## Preserved Invariants
- Raw logs remain the authoritative chronological clarification ledger.
- `events.jsonl` remains unchanged as the lifecycle stream.
- Verifier turns do not receive producer-owned `decisions.txt` headers.
- Empty producer decision blocks are removed without rewriting older non-empty history.

## Intended Behavior Changes
- Producer turns now get a runtime-created decisions header before execution.
- Producer turns that leave no decision body lines now have that trailing empty block removed.
- Clarification handling now appends paired runtime `questions` and `answers` blocks into `decisions.txt` in addition to existing raw-log and session updates.

## Known Non-Changes
- No verifier write path to `decisions.txt` was added.
- No compaction, migration, manifest, or backward-compatibility layer was introduced for decisions history.
- `format_question(...)` was left unchanged because current behavior already returns `control.question.text` directly without adding a synthetic trailing best-supposition line.

## Expected Side Effects
- `decisions.txt` becomes part of normal producer/question turn filesystem churn because runtime now writes headers and clarification blocks there.
- Producer git snapshots now start after runtime pre-header creation so producer delta detection reflects producer body edits and post-turn empty-header cleanup correctly.

## Validation Performed
- `PYTHONPATH=/workspace/superloop pytest -q tests/test_phase_local_behavior.py tests/test_superloop_observability.py`
- `PYTHONPATH=/workspace/superloop pytest -q tests/test_superloop_git_tracking.py tests/test_loop_control.py`

## Deduplication / Centralization Decisions
- Centralized decisions-ledger parsing, sequence allocation, header formatting, and append/remove behavior in dedicated helpers inside `superloop.py` instead of scattering ad hoc file edits across producer and clarification paths.
