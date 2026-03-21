# test_strategy.md

## Coverage map
- Prompt-template phase-local artifact wording:
  `tests/test_superloop_observability.py::test_ensure_workspace_creates_task_scoped_paths_and_task_prompts`
  verifies fresh task bootstraps render implement/test producer and verifier prompts with `phases/<phase-dir-key>/...` paths and reject legacy pair-root mutable artifact paths.
- Active session-file contract in prompts:
  `tests/test_superloop_observability.py::test_build_phase_prompt_includes_active_phase_contract`
  verifies the phase prompt preamble includes the injected `sessions/phases/<phase-dir-key>.json` path.
- Phase key generation and validation:
  `tests/test_phase_local_behavior.py::test_phase_dir_key_behavior_and_validation`
  and `tests/test_phase_local_behavior.py::test_phase_id_over_96_utf8_bytes_rejected`
  cover safe-id passthrough, utf8-hex encoding, and the 96-byte limit.
- Lazy phase artifact creation without overwrite:
  `tests/test_phase_local_behavior.py::test_workspace_and_lazy_phase_artifacts`
  verifies pair roots only create `phases/` eagerly and active-phase files are created lazily and preserved on rerun.
- Session routing and same-phase sharing:
  `tests/test_phase_local_behavior.py::test_session_resolution_paths`
  verifies plan routes to `sessions/plan.json`, implement/test share the same phase session, and different phases use different files.
- Scoped clarification persistence:
  `tests/test_phase_local_behavior.py::test_append_clarification_persists_to_phase_session_only`
  verifies a clarification written for a phased pair lands in `sessions/phases/<phase-dir-key>.json` and leaves `plan.json` untouched.
- Fresh-vs-resumed bootstrap:
  `tests/test_phase_local_behavior.py::test_prompt_bootstrap_only_for_fresh_phase_thread`
  verifies fresh phased threads receive authoritative bootstrap sections while resumed threads skip reinjection.
- Verifier scope:
  `tests/test_phase_local_behavior.py::test_verifier_scope_phase_local_allows_active_phase_only`
  and `tests/test_superloop_observability.py::test_verifier_scope_violations_ignores_superloop_artifacts`
  verify allowed active-phase writes and rejection of other-phase paths.

## Flake risk
- These checks are deterministic file-path and content assertions with no network, sleep, or timing dependency.

## Notes
- No additional fixture layer was needed; the existing tmp-path based tests already isolate workspace, run, and session state cleanly.
