# Implementation Notes

- Task ID: understood-here-is-the-revised-standalone-plan-w-42da73b9
- Pair: implement
- Phase ID: claude-cli-adapter
- Phase Directory Key: claude-cli-adapter
- Phase Title: Claude CLI Adapter
- Scope: phase-local producer artifact

## Files changed
- `src/autoloop/main.py`
- `tests/test_autoloop_observability.py`

## Symbols touched
- `SessionState`
- `ProviderRuntime`
- `ProviderTurnResult`
- `ProviderExecutionError`
- `provider_runtime_overrides()`
- `log_provider_failure_and_fatal()`
- `check_dependencies()`
- `resolve_provider_runtime()`
- `execute_provider_turn()`
- `build_phase_preamble()`
- `build_phase_prompt()`
- `build_claude_append_system_prompt()`
- `run_provider_phase()`
- `auto_answer_question()`
- `main()`

## Checklist mapping
- Milestone 2 / Claude CLI adapter: implemented `claude -p` fresh/resume execution, JSON parsing, permission flag mapping, and prompt-file assembly in `src/autoloop/main.py`.
- Milestone 2 / failure handling: malformed JSON and non-zero Claude exits now log `provider_failure` entries before fatal exit for both phase turns and `full_auto_answers` auto-answer turns.
- Milestone 2 / session metadata: successful Claude turns now persist explicit `model_override` and `effort_override` values when configured.
- Milestone 3 / unit coverage: added Claude preflight, prompt assembly, override mapping, metadata persistence, provider-failure, and auto-answer failure tests in `tests/test_autoloop_observability.py`.
- Deferred by plan: live local Claude validation, strict mode, and stream-json telemetry remain unchanged.

## Assumptions
- Claude JSON output is a single JSON object containing at least `result` and optionally `session_id`.
- Persisting `provider_metadata` as the Claude JSON payload minus `result`, plus explicit Claude `model_override` and `effort_override`, is sufficient for v1 diagnostics without storing duplicate assistant text in session state.

## Preserved invariants
- Codex command resolution and Codex execution semantics remain on the existing path.
- Legacy session payloads without `provider` still normalize to Codex.
- Default Claude mode omits `--bare`, system-prompt replacement flags, tool restriction flags, and `--max-turns`.
- Canonical Autoloop loop-control parsing remains the only completion/clarification contract.

## Intended behavior changes
- `provider.name: claude` is now executable via local Claude CLI preflight plus headless JSON turns.
- Claude phase prompts now split Autoloop context into `-p` preamble text and appended system instructions.
- Session files now persist `provider_metadata` and explicit Claude override metadata for successful turns.

## Known non-changes
- No Anthropic/Claude SDK usage was introduced.
- No default strict mode or tool restriction flags were added.
- No stream-json telemetry was added.
- No CLI surface was added beyond existing config-driven provider selection and overrides.

## Expected side effects
- Claude runs fail early if `claude --version` or `claude auth status` fails.
- Successful session files gain `provider_metadata`, `model_override`, and `effort_override` fields.
- Claude provider failures now leave raw stdout/stderr traces in both task and run raw logs, including `full_auto_answers` auto-answer failures.

## Validation performed
- `pytest -q tests/test_autoloop_observability.py -k 'claude or provider_runtime or check_dependencies or run_codex_phase_logs_shared_template_provenance or create_run_paths_initializes_persistent_session_file'`
- `pytest -q tests/test_autoloop_observability.py -k 'claude or auto_answer_question or provider_failure or model_and_effort_overrides or create_run_paths_creates_per_run_artifacts'`
- `pytest -q tests/test_autoloop_observability.py tests/test_phase_local_behavior.py`

## Deduplication / centralization
- Extracted `build_phase_preamble()` so Codex keeps the combined prompt path while Claude reuses the same preamble data with append-system prompt delivery.
- Kept provider branching localized inside `execute_provider_turn()` and `run_provider_phase()` rather than creating a new provider package.
- Centralized provider-failure raw-log/fatal handling so auto-answer and normal phase turns do not drift.
