PRD Follow-up: Fix remaining phase-local contract gaps in Superloop

Objectives
1) Remove runtime fallback/alias semantics that imply legacy run-level session.json.
2) Correct fresh-phase bootstrap extraction so prior phase status and prior artifact paths are accurate and repo-relative.
3) Add explicit bootstrap size cap/error behavior.
4) Remove volatile generated .superloop task-run artifacts from source diffs or treat as deterministic fixtures only.

Scope
- Update superloop.py runtime helpers and prompt context plumbing.
- Update tests/test_phase_local_behavior.py and tests/test_superloop_observability.py to lock behavior.
- Update Readme.md if needed for strict scoped-session behavior language.
- Keep CLI surface unchanged.

Required changes
A. Session strictness
- Remove returned run_paths alias key `session_file`; keep `plan_session_file` and `sessions_dir` only.
- Require explicit `session_file` in build_phase_prompt() and remove cwd/session.json fallback.
- Add regression assertion that no prompt preamble can surface legacy session.json.

B. Fresh bootstrap correctness
- prior_phase_status_lines(...) should derive statuses for prior phases in current run (not only active phase id).
- relevant_prior_artifact_paths(...) should produce repo-relative paths rooted at .superloop/tasks/<task-id>/...
- Ensure bootstrap sections remain:
  INITIAL REQUEST SNAPSHOT
  AUTHORITATIVE CLARIFICATIONS TO DATE
  PRIOR PHASE STATUS IN THIS RUN
  RELEVANT PRIOR PHASE ARTIFACT PATHS
  ACTIVE PHASE EXECUTION CONTRACT
  ACTIVE PHASE ARTIFACTS

C. Bootstrap size cap
- Add conservative max bootstrap size constant.
- If exceeded, fail with clear actionable error. No silent truncation.

D. Repository hygiene
- Stop committing volatile task runtime outputs under .superloop/tasks/*/runs/* in code-focused changes.
- If any artifacts are needed for tests, move minimal deterministic samples to tests/fixtures.

Testing requirements
- Run focused tests:
  PYTHONPATH=/workspace/superloop pytest -q tests/test_phase_local_behavior.py tests/test_superloop_observability.py
- Run full tests if feasible:
  PYTHONPATH=/workspace/superloop pytest -q

Completion criteria
- Plan, implement, and test pairs all COMPLETE for this task run.
- Event log ends with run_finished status=success.
