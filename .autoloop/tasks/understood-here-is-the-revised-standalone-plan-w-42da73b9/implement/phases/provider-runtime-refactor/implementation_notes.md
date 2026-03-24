# Implementation Notes

- Task ID: understood-here-is-the-revised-standalone-plan-w-42da73b9
- Pair: implement
- Phase ID: provider-runtime-refactor
- Phase Directory Key: provider-runtime-refactor
- Phase Title: Provider-Neutral Runtime Refactor
- Scope: phase-local producer artifact

## Files Changed
- `src/autoloop/main.py`
- `tests/test_autoloop_observability.py`

## Symbols Touched
- `CodexProviderConfig`, `ClaudeProviderConfig`, `ProviderConfig`
- `ProviderConfigOverride`, `ProviderRuntime`, `ProviderTurnResult`
- `SessionState`, `parse_autoloop_config`, `resolve_runtime_config`
- `load_session_state`, `save_session_state`
- `check_dependencies`, `resolve_provider_runtime`, `execute_provider_turn`
- `run_provider_phase`, `run_selected_phase`, `execute_pair_cycles`, `auto_answer_question`

## Checklist Mapping
- Milestone 1 / provider-neutral runtime seam: completed in `execute_provider_turn`, `run_provider_phase`, and `ProviderRuntime`.
- Milestone 1 / nested provider config with legacy Codex compatibility: completed in `parse_autoloop_config` and provider merge helpers.
- Milestone 1 / session migration and provider mismatch guard: completed in `SessionState`, session load/save helpers, and resume checks in `main`.
- Milestone 3 / regression coverage for config precedence and session migration: completed in `tests/test_autoloop_observability.py`.

## Assumptions
- CLI `--model` and `--model-effort` remain Codex-oriented in this phase; `provider.name=claude` is config-loadable but not executable yet.

## Preserved Invariants
- Codex remains the default provider.
- Legacy flat Codex config still resolves with existing precedence.
- Legacy session files with only `thread_id` still resume as Codex sessions.
- Existing `thread_id` field is still written for Codex sessions to preserve old readers and tests.

## Intended Behavior Changes
- Resumed runs now fail fast when stored session provider and selected provider differ.
- Session files now persist `provider` and `session_id` alongside the Codex `thread_id` mirror.
- Existing legacy session payloads without a `provider` field now always normalize to Codex, even when `thread_id` is absent.

## Known Non-Changes
- No Claude subprocess execution, auth preflight, or strict-mode flags were added.
- No provider package split or artifact-path changes were introduced.
- Provider-facing log/process labels remain Codex-specific in this slice; that reviewer note is deferred because Claude execution is still out of scope here.

## Expected Side Effects
- Config files can now declare `provider.name`, `provider.codex`, and `provider.claude`.
- New runs created under this refactor write provider-neutral session metadata immediately.

## Validation Performed
- `python -m py_compile src/autoloop/main.py tests/test_autoloop_observability.py tests/test_phase_local_behavior.py`
- `pytest -q tests/test_autoloop_observability.py tests/test_phase_local_behavior.py`

## Deduplication / Centralization
- Provider subprocess dispatch was centralized in `execute_provider_turn`.
- Phase execution now routes through `ProviderRuntime`, while keeping the legacy `run_codex_phase` wrapper for compatibility.
