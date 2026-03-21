# Runtime-injected phase_plan metadata and phases-only planner authoring

## Objective
Make `phase_plan.yaml` runtime-owned at the metadata layer while keeping planner-authored content limited to `phases`, then lock the contract down with validator and regression-test updates.

## Scope and current-state findings
- `PAIR_PRODUCER_PROMPT["plan"]` currently tells the planner to author the full top-level `phase_plan.yaml`, including `version`, `task_id`, and `request_snapshot_ref`.
- `PAIR_VERIFIER_PROMPT["plan"]` currently reviews plan quality, but it does not explicitly block incorrect edits to runtime-owned metadata.
- `validate_phase_plan()` currently requires every list-valued phase field to be present, and `_phase_criteria_payload()` rejects omitted `acceptance_criteria` entirely.
- `ensure_workspace()` cannot author the correct `request_snapshot_ref` because the authoritative run-scoped `request.md` is created later by `create_run_paths()`.
- Prompt files are only rendered when absent. Existing task-local prompt overrides must remain untouched.

## Implementation plan

### Milestone 1: Runtime-owned `phase_plan.yaml` scaffold
- Add a small helper in `superloop.py` that computes the authoritative metadata payload from:
  - `PHASE_PLAN_VERSION`
  - the resolved `task_id`
  - the current run's `request_file`
- Add a scaffold writer/normalizer that targets `phase_plan_file(task_dir)` and keeps top-level metadata deterministic while preserving the current `phases` payload when possible.
- Invoke scaffold creation after `create_run_paths()` and before the plan producer/verifier cycle starts, because that is the earliest point where the current run's immutable request snapshot path is known.
- Keep scaffold creation scoped to plan-enabled runs so implement/test-only runs without an explicit plan continue to use the existing implicit fallback path.
- Preserve verifier visibility into bad planner edits by seeding authoritative metadata before the plan cycle starts, not immediately before verifier review of the same producer output.

Implementation notes:
- Reuse the existing `phase_plan_file()` path helper.
- Keep serialization deterministic and dependency-light. A JSON-compatible YAML payload is acceptable here because the repo already loads `.yaml` content with `yaml.safe_load()` and tests use JSON text for the same file.
- If a prior explicit plan exists when plan runs again, restore metadata keys to authoritative runtime values without discarding planner-authored `phases`.

### Milestone 2: Planner/verifier contract update
- Update `PAIR_PRODUCER_PROMPT["plan"]` so the planner is instructed to author or update `phases` only.
- Remove any suggestion that the planner should set `version`, `task_id`, or `request_snapshot_ref`.
- Add explicit language that those three keys are runtime-owned and must not be edited by the planner.
- Update `PAIR_VERIFIER_PROMPT["plan"]` so incorrect runtime-owned metadata is a blocking finding, alongside the existing intent-fidelity and phase-quality checks.
- Keep the prompt change template-only. Do not start rewriting existing task-local `prompt.md` or `verifier_prompt.md` files, because `ensure_workspace()` intentionally preserves custom prompt content once present.

### Milestone 3: Validator defaults and regression coverage
- Update `validate_phase_plan()` parsing so these keys default to empty lists when absent:
  - `out_of_scope`
  - `dependencies`
  - `acceptance_criteria`
  - `risks`
  - `rollback`
- Keep `in_scope` and `deliverables` required and non-empty.
- Keep dependency-order validation unchanged once defaults have been applied.
- Adjust helper parsing rather than duplicating field-specific logic inside the main validator loop.

Test coverage:
- Add a regression test for scaffold creation that proves the generated explicit plan includes authoritative `version`, `task_id`, `request_snapshot_ref`, and an editable `phases` container.
- Add a regression test that proves runtime-owned metadata is restored/preserved by the scaffold logic without dropping existing `phases`.
- Add a regression test that omitted optional list fields are accepted and materialize as empty tuples/lists in the validated `PhasePlan`.
- Keep or extend existing negative tests to show `in_scope` and `deliverables` still fail when missing or empty.
- Add prompt-text assertions only where they are stable and high-signal, using fresh task workspaces so preserved custom prompts are not affected.

## Interface and file-level changes
- `superloop.py`
  - Add a helper for authoritative phase-plan metadata construction.
  - Add a helper that writes or normalizes the explicit `phase_plan.yaml` scaffold.
  - Call the scaffold helper from the main run orchestration after run paths exist and before the plan pair executes.
  - Update `PAIR_PRODUCER_PROMPT["plan"]` and `PAIR_VERIFIER_PROMPT["plan"]`.
  - Relax `validate_phase_plan()` handling for optional list fields.
- `tests/test_superloop_observability.py`
  - Cover scaffold generation timing/content.
  - Cover metadata normalization/preservation behavior.
  - Cover fresh prompt rendering expectations if prompt text assertions are added.
- `tests/test_phase_local_behavior.py`
  - Only extend if phase-local helper coverage is the most direct place to validate any new orchestration helper behavior. Otherwise keep the test delta in `test_superloop_observability.py`.

## Implementation checklist
- [ ] Add an authoritative phase-plan metadata/scaffold helper in `superloop.py`.
- [ ] Create or normalize `phase_plan.yaml` only after the current run's `request.md` exists.
- [ ] Keep existing implicit-plan behavior for runs that do not execute the plan pair.
- [ ] Update the planner prompt so only `phases` are planner-authored.
- [ ] Update the verifier prompt so incorrect runtime-owned metadata is blocking.
- [ ] Make optional list fields default to empty values during validation.
- [ ] Preserve strict non-empty enforcement for `in_scope` and `deliverables`.
- [ ] Add regression tests for scaffold creation, metadata immutability/preservation, and optional-list behavior.

## Risks, mitigations, rollback

### Risks
- Seeding an explicit `phase_plan.yaml` too early would force implement/test-only runs onto an incomplete explicit plan and break the current implicit fallback path.
- Rewriting metadata at the wrong point in the plan cycle could hide planner mistakes from the verifier.
- Prompt changes in `superloop.py` will not update already-materialized task-local prompt files, which is intentional but easy to overlook during testing.

### Mitigations
- Scope scaffold creation to plan-enabled runs after `create_run_paths()`.
- Normalize metadata at runtime boundaries, not right before the verifier needs to inspect planner output for drift.
- Use fresh temp workspaces in tests when asserting prompt text rendered from updated constants.

### Rollback
- If scaffold creation leaks into non-plan flows, revert to the current “no explicit phase plan until the planner creates one” behavior.
- If optional-list defaults create downstream incompatibilities, revert the parser relaxation while keeping the prompt/verifier metadata contract changes isolated.
