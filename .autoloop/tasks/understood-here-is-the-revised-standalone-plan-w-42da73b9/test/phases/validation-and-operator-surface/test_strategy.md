# Test Strategy

- Task ID: understood-here-is-the-revised-standalone-plan-w-42da73b9
- Pair: test
- Phase ID: validation-and-operator-surface
- Phase Directory Key: validation-and-operator-surface
- Phase Title: Validation And Operator Surface
- Scope: phase-local producer artifact

## Behaviors covered
- Provider runtime/config/session behavior remains covered in `tests/test_autoloop_observability.py`, including nested provider selection, legacy session migration, provider mismatch on resume, Claude command construction/parsing, provider-aware `full_auto_answers`, and unchanged Codex execution paths.
- Operator-facing CLI help remains covered in `tests/test_autoloop_observability.py::test_build_arg_parser_exposes_explicit_git_flag_pair`.
- Repository docs regression coverage now includes the Claude rollout checklist reference in `tests/test_resources.py::test_readme_links_claude_rollout_checklist_with_repo_relative_path`.

## Preserved invariants checked
- README links to the shipped checklist via a repository-relative path, not a machine-local workspace path.
- The checklist document exists at `docs/claude_rollout_checklist.md`.
- Existing provider/runtime regression coverage still passes after the operator-surface edits.

## Edge cases and failure paths
- Negative assertion prevents reintroducing the hard-coded `/workspace/superloop/docs/...` path that broke portability outside this checkout.
- Focused observability rerun keeps the docs fix from drifting into provider/help regressions.

## Known gaps
- No automated validation executes a real local Claude CLI; live inherited-environment validation remains manual by plan.
- Installer messaging is still validated indirectly through source review rather than a shell-level installer test.
