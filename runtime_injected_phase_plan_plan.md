# Plan: Runtime-injected phase_plan metadata and phases-only planner authoring

## Goal
Make `phase_plan.yaml` metadata deterministic and runtime-owned while keeping planner-authored content focused on `phases`.

## Scope
1. Runtime-generate a `phase_plan.yaml` scaffold with authoritative metadata:
   - `version` from `PHASE_PLAN_VERSION`
   - `task_id` from current task metadata
   - `request_snapshot_ref` from authoritative request snapshot pointer
2. Planner prompt changes:
   - Instruct planner to author/update `phases` only.
   - Explicitly forbid editing runtime-owned metadata keys.
3. Validation behavior changes:
   - Keep `in_scope` and `deliverables` required and non-empty.
   - Treat `out_of_scope`, `dependencies`, `acceptance_criteria`, `risks`, `rollback` as optional keys defaulting to empty lists when absent.
4. Verifier prompt changes:
   - Add a blocking check when runtime-owned metadata keys are altered incorrectly.
5. Add tests covering scaffolding, metadata immutability, and optional-list behavior.

## Deliverables
- Updated orchestration logic in `superloop.py` to create/preserve metadata scaffold.
- Updated planner/verifier prompt text in `superloop.py`.
- Updated validator behavior for optional list fields.
- Regression tests in `tests/test_phase_local_behavior.py` and/or related test files.
