# Test Strategy

- Task ID: understood-here-is-the-revised-standalone-plan-w-42da73b9
- Pair: test
- Phase ID: claude-cli-adapter
- Phase Directory Key: claude-cli-adapter
- Phase Title: Claude CLI Adapter
- Scope: phase-local producer artifact

## Behavior-to-test coverage map

- Claude preflight:
  - `check_dependencies(provider_name="claude")` verifies `claude --version` and `claude auth status`.
- Fresh Claude phase turns:
  - command uses `claude -p ... --output-format json --append-system-prompt-file ...`
  - default mode omits `--bare`, system-prompt replacement flags, tool restriction flags, and `--max-turns`
  - phase preamble stays in `-p`, while pair instructions and guardrails live in the appended prompt file
- Resumed Claude turns and explicit overrides:
  - resumed command includes `--resume`
  - explicit `model`, `effort`, and permission strategy flags appear only when configured
  - successful turns persist `session_id`, `provider_metadata`, and explicit override metadata
- Failure paths:
  - malformed Claude JSON raises provider failure, not loop-control parse failure
  - phase turns append `provider_failure` diagnostics to task/run raw logs before fatal exit
  - `full_auto_answers` helper-level provider failures append the same diagnostics before fatal exit
- Loop-level preserved behavior:
  - `execute_pair_cycles()` passes Claude provider runtime, run/task raw logs, run id, and phase context into `auto_answer_question()` when `full_auto_answers` is enabled
  - auto-answered clarifications are recorded with `source="auto"`
- Preserved invariants checked:
  - legacy session loading remains compatible
  - Codex tests continue to pass in the shared suite

## Edge cases and failure cases

- Missing `session_id` in Claude JSON still leaves phase logs and session persistence deterministic.
- Explicit Claude overrides persist only when configured; default Claude runs keep override fields `null`.
- Auto-answer coverage avoids real subprocess/network behavior by mocking provider execution and loop-turn orchestration.

## Stabilization approach

- All Claude CLI interactions are mocked via `subprocess.CompletedProcess` or direct helper monkeypatches.
- Loop-level auto-answer coverage isolates the integration seam by monkeypatching `run_selected_phase()` and `append_clarification()` to stop immediately after the clarification write.

## Known gaps

- No live local Claude binary validation is performed in unit tests.
- Stream-json and strict-mode behavior remain intentionally uncovered because they are out of scope for this phase.
