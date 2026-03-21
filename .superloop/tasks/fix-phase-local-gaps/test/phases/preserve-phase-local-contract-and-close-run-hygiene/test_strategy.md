# Test Strategy

- Task ID: fix-phase-local-gaps
- Pair: test
- Phase ID: preserve-phase-local-contract-and-close-run-hygiene
- Phase Directory Key: preserve-phase-local-contract-and-close-run-hygiene
- Phase Title: Preserve strict phase-local behavior and close remaining run-artifact hygiene
- Scope: phase-local producer artifact

## Behavior-To-Test Coverage Map

- AC-1 session-path strictness:
  - Covered by `tests/test_phase_local_behavior.py::test_session_resolution_paths`.
  - Confirms run-path helpers expose `plan_session_file` and omit `session_file`, and that phase-session resolution remains explicit.

- AC-2 explicit scoped session file and no legacy `session.json` surfacing:
  - Covered by `tests/test_phase_local_behavior.py::test_prompt_bootstrap_only_for_fresh_phase_thread`.
  - Covered by `tests/test_superloop_observability.py::test_build_phase_prompt_includes_active_phase_contract`.
  - Covered by `tests/test_superloop_observability.py::test_build_phase_prompt_requires_explicit_session_file`.

- AC-3 fresh bootstrap correctness and failure path:
  - Covered by `tests/test_phase_local_behavior.py::test_clarification_extraction_and_status_lines`.
  - Covered by `tests/test_phase_local_behavior.py::test_prompt_bootstrap_only_for_fresh_phase_thread`.
  - Covered by `tests/test_phase_local_behavior.py::test_fresh_phase_bootstrap_fails_when_size_cap_is_exceeded`.

- AC-4 snapshot-delta commit hygiene for volatile run outputs:
  - Covered by `tests/test_phase_local_behavior.py::test_filter_volatile_task_run_paths_keeps_non_run_phase_artifacts`.
  - Covered by `tests/test_superloop_observability.py::test_execute_pair_cycles_excludes_run_outputs_from_snapshot_delta_commits`.
  - Covered by `tests/test_superloop_observability.py::test_execute_pair_cycles_excludes_run_outputs_from_blocked_commit`.

- AC-5 focused regression sufficiency:
  - The helper-level test covers the filtering happy path and allowed-path retention.
  - The execute-pair-cycle tests cover end-to-end mixed deltas for both `pair complete` and `blocked` commit branches.

- AC-6 execution evidence:
  - Focused suite: `PYTHONPATH=/workspace/superloop pytest -q tests/test_phase_local_behavior.py tests/test_superloop_observability.py`
  - Full suite: `PYTHONPATH=/workspace/superloop pytest -q`

## Edge Cases And Failure Paths

- Oversize bootstrap is exercised with an explicit failure assertion rather than truncation behavior.
- Mixed snapshot deltas include both legitimate edits and `.superloop/tasks/<task>/runs/...` artifacts to prove filtering is selective rather than broad.
- Blocked verifier completion path is covered explicitly so the unioned `set(pair_tracked) | verifier_delta` commit flow cannot regress silently.

## Fixture / Determinism Notes

- No live `.superloop/tasks/*/runs/*` fixture data is used; tests synthesize state under `tmp_path`.
- Git/codex interactions in execute-pair-cycle coverage are monkeypatched to fixed values to avoid timing, network, and ordering flake.
- Path assertions use explicit repo-relative strings, keeping ordering dependence out of the checks.
