# Test Strategy

- Task ID: standalone-implementation-plan-for-the-new-super-5226e1de
- Pair: test
- Phase ID: orchestration-cleanup-and-regression-coverage
- Phase Directory Key: orchestration-cleanup-and-regression-coverage
- Phase Title: Remove obsolete run-log flow and finish regression coverage
- Scope: phase-local producer artifact

## Behaviors Covered
- Run scaffolding omits `run_log.md` and `summary.md` while preserving `request.md`, `raw_phase_log.md`, `events.jsonl`, and session files.
- Task scaffolding omits copied prompt files and preserves the shared `decisions.txt` contract.
- Prompt construction uses shared template provenance and includes the authoritative decisions path without task-local `prompt.md` references.
- Clarification flow persists raw-log entries, appends decisions questions/answers blocks, and keeps phase-session clarification state isolated from the plan session.
- Verifier scope enforcement continues to flag `decisions.txt` edits while exempting runtime bookkeeping only.
- Runtime notices append to task/run raw logs only.
- Failure-path staging uses tracked task/pair artifacts only, excluding `runs/`, `run_log.md`, and `summary.md`.
- Phase-local tracked artifact enumeration for the `test` pair keeps shared task artifacts and excludes volatile run outputs.

## Preserved Invariants Checked
- `decisions.txt` remains task-scoped, tracked, and not verifier-exempt.
- No prompt files are copied into task pair directories.
- Removed run-log and summary artifacts stay absent from new workspace and run scaffolding.

## Edge Cases
- Producer clarification turns that create empty or non-empty decisions blocks.
- Verifier scope checks against artifact-prefixed lookalikes and phase-local cross-phase edits.
- Failure after max iterations with git-style path staging.

## Failure Paths
- Run finalization paths do not rely on `summary.md`.
- Pair failure commits do not stage volatile run outputs or removed run-log artifacts.

## Known Gaps
- No backward-compatibility migration coverage for legacy workspaces, by design.
- No new observability channel coverage beyond raw logs and `events.jsonl`, by design.

## Flake Risk / Stabilization
- Tests are deterministic and filesystem-local.
- Max-iteration failure coverage stubs `time.sleep` to avoid timing-dependent delay.
