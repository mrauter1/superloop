# Implementation Notes

- Task ID: standalone-implementation-plan-for-the-new-super-5226e1de
- Pair: implement
- Phase ID: shared-prompt-loading-and-artifact-ownership-split
- Phase Directory Key: shared-prompt-loading-and-artifact-ownership-split
- Phase Title: Load prompts from shared templates and split artifact ownership rules
- Scope: phase-local producer artifact

## Files Changed
- `superloop.py`
- `tests/test_superloop_observability.py`
- `tests/test_phase_local_behavior.py`

## Symbols Touched
- `tracked_superloop_artifact_paths(...)`
- `verifier_exempt_runtime_artifact_paths(...)`
- `is_verifier_exempt_runtime_artifact_path(...)`
- `verifier_scope_violations(...)`
- `tracked_superloop_paths(...)`
- `resolve_artifact_bundle(...)`

## Checklist Mapping
- Plan Phase 2: kept prompt sourcing on shared template provenance and preserved the in-memory rendered-template path flow already present in `execute_pair_cycles(...)`.
- Plan Phase 2: split tracked artifacts from verifier-exempt runtime bookkeeping so `decisions.txt` is staged as tracked state but still flagged on verifier edits.
- Plan Phase 2: narrowed phase-local verifier allowlists to active artifact prefixes only; runtime bookkeeping is exempted by dedicated scope logic instead of broad phase prefixes.

## Assumptions
- Shared-template prompt loading and template provenance logging were already landed from the prior phase and only needed regression coverage, not another orchestration rewrite.

## Preserved Invariants
- `runs/` remains verifier-exempt runtime bookkeeping.
- Task `raw_phase_log.md` and `task.json` remain verifier-exempt runtime bookkeeping.
- Verifiers remain limited to their active artifact scope plus explicit runtime bookkeeping exemptions.
- Prompt preambles and raw-log template provenance continue to come from shared template sources, not task-local prompt copies.

## Intended Behavior Changes
- `decisions.txt` is now treated as tracked Superloop state for staging/commit selection.
- `decisions.txt` is no longer verifier-exempt, so verifier edits to it are reported as scope violations.

## Known Non-Changes
- No decisions-ledger header allocation, clarification block persistence, or producer empty-block cleanup was implemented in this phase.
- No prompt template text was changed in this phase.

## Expected Side Effects
- Failure/completion staging paths that rely on `tracked_superloop_paths(...)` now include `decisions.txt`.
- Phase-local verifier scope checks rely on dedicated runtime-artifact exemptions instead of implicit allowance via bundle prefixes.

## Validation Performed
- `PYTHONPATH=/workspace/superloop pytest -q /workspace/superloop/tests/test_superloop_observability.py -k "verifier_scope_violations or tracked_superloop_paths"`
- `PYTHONPATH=/workspace/superloop pytest -q /workspace/superloop/tests/test_superloop_observability.py -k "build_phase_prompt or execute_pair_cycles_excludes_run_outputs_from_snapshot_delta_commits or workspace_scaffold or prompt"`
- `PYTHONPATH=/workspace/superloop pytest -q /workspace/superloop/tests/test_phase_local_behavior.py -k "verifier_scope_phase_local_allows_active_phase_only or prompt_bootstrap_only_for_fresh_phase_thread or workspace_and_lazy_phase_artifacts"`
- `PYTHONPATH=/workspace/superloop pytest -q /workspace/superloop/tests/test_phase_local_behavior.py -k "prompt_bootstrap_only_for_fresh_phase_thread or fresh_phase_bootstrap_does_not_enforce_size_cap or workspace_and_lazy_phase_artifacts"`

## Deduplication / Centralization Decisions
- Centralized tracked-vs-exempt ownership into separate helper families so staging and verifier-scope enforcement no longer share one artifact list with conflicting semantics.
