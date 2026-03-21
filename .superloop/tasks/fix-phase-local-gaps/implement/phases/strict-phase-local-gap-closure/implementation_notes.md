# Implementation Notes

- Task ID: fix-phase-local-gaps
- Pair: implement
- Phase ID: strict-phase-local-gap-closure
- Phase Directory Key: strict-phase-local-gap-closure
- Phase Title: Close the remaining phase-local runtime contract gaps
- Scope: phase-local producer artifact
- Files changed:
  `/workspace/superloop/superloop.py`
  `/workspace/superloop/tests/test_phase_local_behavior.py`
  `/workspace/superloop/tests/test_superloop_observability.py`
  `/workspace/superloop/Readme.md`
  `/workspace/superloop/.gitignore`
- Checklist mapping:
  Milestone 1 complete: removed `run_paths["session_file"]`, made `build_phase_prompt(...)` require `session_file`, and added prompt regressions that reject legacy `session.json`.
  Milestone 2 complete: fresh bootstrap now receives explicit prior phase ids/keys from the ordered selection, reports prior statuses across earlier phases in the current run, and emits repo-relative `.superloop/tasks/<task-id>/...` prior artifact paths in the required section order.
  Milestone 3 complete: added `MAX_FRESH_PHASE_BOOTSTRAP_BYTES` enforcement with explicit `ValueError` failure and regression coverage.
  Milestone 4 complete: normal tracked-path staging excludes `.superloop/tasks/*/runs/`, tests no longer depend on live tracked run outputs, and `.gitignore` adds only secondary protection for newly generated run dirs.
- Assumptions:
  `task_dir` remains rooted at `<repo>/.superloop/tasks/<task-id>`, so repo-relative prior artifact paths can be derived from the repository root via the canonical task layout.
  The active phase loop should decide what counts as "prior"; helper code should only consume the explicit ordered ids/keys passed by the caller.
- Expected side effects:
  Any in-repo caller that omitted `session_file` from `build_phase_prompt(...)` will now fail immediately.
  Fresh phased prompts now fail fast instead of silently growing without bound when request, clarification, or prior-artifact context becomes too large.
  Baseline/pair-cycle/success staging no longer sweeps task `runs/` output into normal code-focused commits.
- Deduplication / centralization decisions:
  Kept `phase_prompt_context(...)` as the single formatter for active-phase contract text and reused it inside fresh bootstrap assembly rather than duplicating section rendering.
  Passed explicit prior-phase ids/keys through `execute_pair_cycles(...) -> run_codex_phase(...) -> build_phase_prompt(...)` instead of teaching lower-level helpers to infer "prior" from the active bundle.
