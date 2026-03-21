# Implementation Notes

- Task ID: fix-phase-local-gaps
- Pair: implement
- Phase ID: preserve-phase-local-contract-and-close-run-hygiene
- Phase Directory Key: preserve-phase-local-contract-and-close-run-hygiene
- Phase Title: Preserve strict phase-local behavior and close remaining run-artifact hygiene
- Scope: phase-local producer artifact

## Files Changed

- `/workspace/superloop/superloop.py`
- `/workspace/superloop/tests/test_phase_local_behavior.py`
- `/workspace/superloop/tests/test_superloop_observability.py`
- `/workspace/superloop/.superloop/tasks/fix-phase-local-gaps/implement/phases/preserve-phase-local-contract-and-close-run-hygiene/implementation_notes.md`

## Checklist Mapping

- Milestone 1 preserved as-is: no session/bootstrap runtime changes were needed beyond keeping the existing strict contract intact.
- Milestone 2 implemented in `superloop.py` by adding `filter_volatile_task_run_paths(...)` and applying it to both snapshot-delta commit inputs (`producer_delta` and `verifier_delta`) before any code-focused commit flow uses them.
- Milestone 3 implemented in the focused tests:
  - `tests/test_phase_local_behavior.py` adds helper-level coverage that volatile `.superloop/tasks/<task>/runs/...` paths are removed while legitimate phase artifacts remain.
  - `tests/test_superloop_observability.py` adds an execution-path regression proving `execute_pair_cycles(...)` keeps legitimate mixed snapshot-delta edits while excluding run outputs from producer and pair-complete commit inputs.

## Assumptions

- The strict scoped-session contract, fresh bootstrap ordering, repo-relative prior artifact paths, and bootstrap size-cap behavior already present in the working tree are the baseline to preserve, not reopen.
- Runtime outputs under `.superloop/tasks/*/runs/*` are volatile orchestration artifacts and should be filtered only from code-focused snapshot-delta commits, not from final run bookkeeping handled through the existing tracked-path flows.

## Expected Side Effects

- Producer/verifier snapshot-based commits no longer stage per-run task outputs written under `.superloop/tasks/<task-id>/runs/...`.
- Legitimate code edits and phase-local artifacts outside `runs/` remain eligible for the same commit flows.
- No CLI or prompt-contract behavior changes were introduced.

## Deduplication / Centralization Decisions

- Centralized the filtering rule in one helper (`filter_volatile_task_run_paths(...)`) instead of repeating path-prefix checks at each commit call site.

## Verification

- `PYTHONPATH=/workspace/superloop pytest -q tests/test_phase_local_behavior.py tests/test_superloop_observability.py`
- `PYTHONPATH=/workspace/superloop pytest -q`

## Notes

- Left `/workspace/superloop/.gitignore` unchanged because it was already dirty and the runtime commit-path fix is the primary correctness mechanism.
- Did not touch existing generated `.superloop/tasks/*/runs/*` worktree artifacts; they remain out of scope for this code-focused fix.
