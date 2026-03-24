# Implementation Notes

- Task ID: understood-here-is-the-revised-standalone-plan-w-42da73b9
- Pair: implement
- Phase ID: validation-and-operator-surface
- Phase Directory Key: validation-and-operator-surface
- Phase Title: Validation And Operator Surface
- Scope: phase-local producer artifact

## Files changed
- `README.md`
- `docs/claude_rollout_checklist.md`
- `install_autoloop.sh`
- `src/autoloop/main.py`
- `tests/test_autoloop_observability.py`

## Symbols touched
- `build_arg_parser()`

## Checklist mapping
- Milestone 3 / automated coverage: extended parser help coverage so the visible CLI surface now asserts provider-aware wording.
- Milestone 3 / README and setup messaging: updated requirements, install notes, config examples, runtime-state notes, and installer messaging to describe Codex and Claude accurately.
- Milestone 3 / live validation checklist: recorded the inherited-environment Claude rollout checklist and config-drift resume checks in `docs/claude_rollout_checklist.md`.
- Deferred by plan: strict mode and `stream-json` remain documented as follow-up work, not default behavior.

## Assumptions
- Repository docs are an acceptable home for the maintainer rollout checklist because this phase explicitly includes operator-facing documentation.

## Preserved invariants
- No provider runtime behavior changed in this phase; the code path changes are limited to help text.
- Codex remains the default provider when configs do not select Claude.
- Claude strict mode and `stream-json` remain deferred, not enabled by documentation drift.

## Intended behavior changes
- Visible CLI/help/install messaging now reflects provider-neutral orchestration and provider-specific prerequisites.
- The repository now ships an explicit Claude rollout validation checklist for maintainers.
- The README checklist reference now uses a repository-relative path so the shipped docs stay valid outside this workspace checkout.

## Known non-changes
- No new CLI flags were introduced for provider selection in this phase.
- No installer logic now installs provider CLIs automatically.
- No live Claude execution was added to automated tests.

## Expected side effects
- `autoloop --help` now describes the multi-provider model and clarifies that `--model`/`--model-effort` are Codex-only overrides.
- The installer now reports both Codex and Claude prerequisite status instead of implying Codex is the only provider path.

## Validation performed
- `pytest -q tests/test_autoloop_observability.py -k 'build_arg_parser or claude or provider or resume_refuses_provider_mismatch'`
- `pytest -q tests/test_autoloop_observability.py tests/test_phase_local_behavior.py`
- `rg -n "workspace/superloop/docs|claude_rollout_checklist" README.md docs`

## Deduplication / centralization
- Kept rollout guidance in a single repository doc (`docs/claude_rollout_checklist.md`) and linked it from `README.md` instead of duplicating the full checklist in multiple operator-facing files.
