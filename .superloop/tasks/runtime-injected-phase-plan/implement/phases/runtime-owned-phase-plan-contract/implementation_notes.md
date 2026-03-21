# Implementation Notes

- Task ID: runtime-injected-phase-plan
- Pair: implement
- Phase ID: runtime-owned-phase-plan-contract
- Phase Directory Key: runtime-owned-phase-plan-contract
- Phase Title: Runtime-owned phase plan metadata and validation contract
- Scope: phase-local producer artifact

## Files Changed

- `superloop.py`
  - Runtime-owned `phase_plan.yaml` metadata scaffold helper present in the working tree.
  - Planner/verifier prompt contract updated so metadata keys are runtime-owned and verifier treats drift as blocking.
  - Phase plan validation updated so optional list fields default to empty tuples when omitted.
- `tests/test_superloop_observability.py`
  - Regression coverage exercises scaffold creation, metadata restoration while preserving `phases`, optional-list defaults, required-list enforcement, and plan prompt/verifier contract rendering.
- `.superloop/tasks/runtime-injected-phase-plan/implement/phases/runtime-owned-phase-plan-contract/implementation_notes.md`
  - Recorded checklist mapping, assumptions, expected side effects, and verification for this phase.

## Checklist Mapping

- [x] Add an authoritative phase-plan metadata/scaffold helper in `superloop.py`.
  - Covered by `authoritative_phase_plan_metadata()` and `ensure_phase_plan_scaffold()`.
- [x] Create or normalize `phase_plan.yaml` only after the current run's `request.md` exists.
  - Covered by the main-run call site gated behind `should_run_plan_pair`, with regression coverage asserting scaffolding after `create_run_paths()`.
- [x] Keep existing implicit-plan behavior for runs that do not execute the plan pair.
  - Preserved by only calling scaffold creation in the enabled plan-pair path; existing implicit-flow tests remain relevant.
- [x] Update the planner prompt so only `phases` are planner-authored.
  - Reflected in the plan prompt contract and prompt-render assertions.
- [x] Update the verifier prompt so incorrect runtime-owned metadata is blocking.
  - Reflected in the plan verifier prompt contract and prompt-render assertions.
- [x] Make optional list fields default to empty values during validation.
  - Covered by `validate_phase_plan()` regression coverage for omitted optional fields.
- [x] Preserve strict non-empty enforcement for `in_scope` and `deliverables`.
  - Covered by negative validation tests for missing and empty required lists.
- [x] Add regression tests for scaffold creation, metadata immutability/preservation, and optional-list behavior.
  - Added in `tests/test_superloop_observability.py`.

## Assumptions

- JSON-formatted text remains acceptable for `phase_plan.yaml` because runtime loading already relies on `yaml.safe_load()`, and the existing tests use JSON payloads for the same file.
- Restoring runtime-owned metadata before the plan pair starts is sufficient; verifier visibility into bad planner edits still comes from reviewing the planner-authored file contents after the producer runs.

## Expected Side Effects

- Plan-enabled runs now materialize `.superloop/tasks/<task-id>/plan/phase_plan.yaml` earlier, once the authoritative run-scoped `request.md` exists.
- Existing custom task-local prompt files remain untouched because prompt rendering is still create-only when missing.
- Explicit plans that already exist will have runtime-owned metadata normalized while preserving the planner-authored `phases` payload.

## Deduplication / Centralization Decisions

- Reused the shared `authoritative_phase_plan_metadata()` helper instead of repeating top-level metadata construction at each scaffold/write site.

## Verification

- `PYTHONPATH=/workspace/superloop pytest -q /workspace/superloop/tests/test_superloop_observability.py -q`
