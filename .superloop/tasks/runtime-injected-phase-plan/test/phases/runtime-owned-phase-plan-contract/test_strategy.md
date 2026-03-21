# Test Strategy

- Task ID: runtime-injected-phase-plan
- Pair: test
- Phase ID: runtime-owned-phase-plan-contract
- Phase Directory Key: runtime-owned-phase-plan-contract
- Phase Title: Runtime-owned phase plan metadata and validation contract
- Scope: phase-local producer artifact

## Behavior-to-test coverage map

- `AC-1` Runtime seeds explicit `phase_plan.yaml` metadata only after the current run request snapshot exists.
  - `tests/test_superloop_observability.py::test_ensure_phase_plan_scaffold_writes_runtime_metadata_after_request_snapshot_exists`
  - `tests/test_superloop_observability.py::test_main_plan_run_seeds_phase_plan_scaffold_after_request_snapshot_exists`
- `AC-2` Planner prompt instructs agents to author `phases` only and forbids editing runtime-owned metadata keys.
  - `tests/test_superloop_observability.py::test_ensure_workspace_creates_task_scoped_paths_and_task_prompts`
- `AC-3` Verifier prompt treats incorrect runtime-owned metadata as a blocking issue.
  - `tests/test_superloop_observability.py::test_ensure_workspace_creates_task_scoped_paths_and_task_prompts`
- `AC-4` `validate_phase_plan()` accepts omitted optional list fields as empty values while still rejecting missing or empty `in_scope` and `deliverables`.
  - `tests/test_superloop_observability.py::test_validate_phase_plan_defaults_optional_lists_when_omitted`
  - `tests/test_superloop_observability.py::test_validate_phase_plan_still_rejects_missing_required_lists`
  - `tests/test_superloop_observability.py::test_validate_phase_plan_still_requires_non_empty_required_lists`
- `AC-5` Regression tests cover scaffold content/timing and metadata preservation behavior.
  - `tests/test_superloop_observability.py::test_ensure_phase_plan_scaffold_restores_runtime_metadata_and_preserves_phases`
  - `tests/test_superloop_observability.py::test_ensure_phase_plan_scaffold_writes_runtime_metadata_after_request_snapshot_exists`
  - `tests/test_superloop_observability.py::test_main_plan_run_seeds_phase_plan_scaffold_after_request_snapshot_exists`

## Determinism / flake control

- Coverage uses `tmp_path`, in-process monkeypatching, and local file assertions only.
- No network calls, sleeps, or nondeterministic ordering assumptions are introduced.
- Main-flow scaffold assertions stub agent-execution hooks so the tests stay focused on orchestrator state transitions and persisted artifacts.

## Verification

- `PYTHONPATH=/workspace/superloop pytest -q /workspace/superloop/tests/test_superloop_observability.py -q`
