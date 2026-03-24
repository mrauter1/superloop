# Claude CLI Provider Plan

## Objective
- Add Claude as a first-class CLI provider by invoking the local `claude` binary in headless print mode, never via Anthropic SDKs.
- Preserve existing Codex behavior and keep Claude’s default mode aligned with the user’s existing Claude Code environment.
- Keep Autoloop’s canonical loop-control contract, resume behavior, artifact layout, and pair orchestration authoritative across providers.

## Current Repository Seams
- `src/autoloop/main.py` currently owns config parsing/merging, dependency checks, provider command resolution, session persistence, phase execution, CLI parsing, and `full_auto_answers`; the provider work should stay localized there unless extraction becomes clearly necessary.
- Session persistence is run-scoped and file-based via `create_run_paths()`, `plan_session_file()`, `phase_session_file()`, `load_session_state()`, and `save_session_state()`. The stored schema is still Codex-specific because it only persists `thread_id`.
- All provider turns currently flow through `run_codex_phase()`, which builds a combined prompt, shells out to Codex, parses JSON, updates session state, appends raw logs, and fatal-exits on provider failure.
- Prompt behavior comes from `build_phase_prompt()` plus the pair templates under `src/autoloop/templates/`; Claude support must preserve these rules while changing how prompt material is delivered.
- Existing regression tests already cover config precedence, session/run creation, resume recovery, phase-local sessions, and pair execution in `tests/test_autoloop_observability.py` and `tests/test_phase_local_behavior.py`; the plan should extend those instead of creating parallel test scaffolding.

## Scope And Non-Goals
- In scope: provider-neutral runtime plumbing, Claude CLI execution, persisted provider/session compatibility, provider-aware `full_auto_answers`, config/schema updates, regression tests, and user-facing docs/install messaging.
- Out of scope for this slice: Anthropic SDK integration, default tool restriction flags, default strict mode, `stream-json` telemetry, and any provider package split beyond a small local abstraction inside `main.py`.

## Milestone 1: Provider-Neutral Runtime Refactor
- Replace the Codex-only execution seam with a small provider abstraction in `src/autoloop/main.py` that can serve both `execute_pair_cycles()` and `auto_answer_question()` without duplicating phase/session/logging code.
- Update config parsing from the current flat provider block to an explicit nested shape:

```yaml
provider:
  name: codex | claude
  codex:
    model: gpt-5.4
    model_effort: null
  claude:
    model: null
    effort: null
    permission_strategy: inherit
runtime:
  pairs: plan,implement,test
  max_iterations: 15
  phase_mode: single
  intent_mode: preserve
  full_auto_answers: false
  no_git: false
```

- Preserve backward compatibility by accepting legacy flat Codex config (`provider.model`, `provider.model_effort`) as a read-compatible alias for `provider.name: codex`; docs should point users to the new nested shape, but the loader should not break old config files.
- Generalize `SessionState` to store `provider`, `session_id`, provider diagnostics, and explicit override metadata while still loading legacy `thread_id` values into the neutral `session_id` field; for Codex-backed sessions, keep a `thread_id` mirror while writing the new schema so existing tests and older run state remain readable.
- Add an explicit provider-consistency check before any resumed turn: if the stored session provider does not match the currently selected provider, fail fast with a clear message rather than silently starting a mismatched conversation.
- Keep the refactor local: reuse the current `build_phase_prompt()`, raw-log appenders, and pair loop orchestration rather than creating a new provider subsystem or moving logic into new packages.

## Milestone 2: Claude CLI Adapter
- Implement a Claude adapter that shells out with argument lists only, captures stdout/stderr, and returns normalized turn results containing assistant text, session id, raw payload, and categorized failure details.
- Fresh Claude turn command:

```text
claude -p "<prompt>" --output-format json --append-system-prompt-file "<autoloop-prompt-file>"
```

- Resumed Claude turn command:

```text
claude -p "<prompt>" --output-format json --append-system-prompt-file "<autoloop-prompt-file>" --resume "<session_id>"
```

- Do not pass `--bare`, `--system-prompt`, `--system-prompt-file`, `--setting-sources`, `--strict-mcp-config`, `--tools`, `--disallowedTools`, `--disable-slash-commands`, or `--max-turns` in default Claude mode. Only optional explicit overrides may add `--model`, `--effort`, `--allowedTools`, or `--dangerously-skip-permissions`.
- Split prompt delivery for Claude so Autoloop preserves Claude Code defaults without losing repository/run context:
  - Keep the run preamble, request snapshot, artifact paths, and phase context as the `-p` prompt payload.
  - Materialize the pair template plus any Claude-specific orchestration guardrails into the appended system-prompt file.
  - Add explicit Claude-facing instructions that loop-control questions/completion must stay inside Autoloop’s canonical block instead of Claude-native ask-user/plan/worktree/task tools.
- Add provider-aware preflight:
  - Codex path keeps current CLI capability probing.
  - Claude path verifies `claude --version` and `claude auth status` before the first provider turn and fails with provider-specific setup errors when missing/not authenticated.
- Add Claude permission strategy mapping:
  - `inherit`: pass nothing.
  - `allow_core_tools`: pass `--allowedTools Read,Write,Edit,Glob,Grep,Bash`.
  - `bypass`: pass `--dangerously-skip-permissions`.
- Treat non-zero Claude exits and malformed JSON as provider failures, not loop-control parse failures; raw payload must still be written to existing raw logs for diagnosis.
- Make `full_auto_answers` provider-aware so the extra clarification-answer pass uses the currently selected provider instead of being hard-wired to Codex.

## Milestone 3: Validation, Compatibility, And Operator Surface
- Extend unit tests in `tests/test_autoloop_observability.py` for nested provider config parsing, legacy config normalization, provider selection, provider mismatch on resume, session schema migration, provider-aware dependency checks, and unchanged Codex command behavior.
- Add Claude adapter tests for fresh/resume command construction, omission of default-suppressing flags, JSON parsing of `result`/`session_id`, permission strategy mapping, malformed JSON handling, and provider-aware auto-answer execution.
- Extend phase/session tests in `tests/test_phase_local_behavior.py` where needed so phase-local sessions still isolate pending clarification notes correctly after the schema change.
- Update `README.md` and any install/setup messaging that currently implies Codex is the only provider; requirements should describe provider-specific prerequisites instead of treating `codex` as globally mandatory.
- Record a manual live-validation checklist for maintainers that covers:
  - fresh Claude session
  - resumed Claude session
  - default inherited-environment runs in repos with `CLAUDE.md`, output styles, hooks, skills, plugins, MCP, and subagents
  - optional `allow_core_tools` mode
  - optional `bypass` mode only in isolated environments
  - config drift between an initial Claude session and a resumed Claude session
- Defer strict mode and `stream-json` telemetry until after representative inherited-environment validation shows a concrete need.

## Interface Notes
- Public config contract becomes nested and explicit. Legacy flat Codex config remains load-compatible in this slice; new docs and examples should use the nested shape only.
- Session files remain at the current paths (`runs/<run_id>/sessions/plan.json` and phase-local files under `runs/<run_id>/sessions/phases/`) so artifact discovery and resume logic do not move.
- Resume compatibility is one-way and safe:
  - old run state without `provider` continues to load as Codex
  - old `thread_id` continues to hydrate the neutral session id
  - new runtime must not resume a session under a different provider
- CLI behavior should remain stable unless a new provider-selection flag is explicitly justified later; in this slice, existing model/effort flags must not regress Codex behavior.

## Regression Controls
- Preserve Codex command probing and invocation semantics exactly while routing them through the new provider-neutral seam.
- Keep the loop-control parser, retry-on-parse-error behavior, clarification logging, decisions ledger writes, and artifact directory structure unchanged across providers.
- Do not alter `runtime.max_iterations` semantics; Claude `--max-turns` remains unset so Autoloop continues to own outer-loop iteration limits.
- Ensure provider failures still surface before loop-control parsing so malformed provider payloads do not get misreported as agent contract violations.

## Risk Register
- `R1 Session migration regression`: changing `SessionState` can break resume or phase-local clarification carryover. Mitigation: one-way legacy loader support, Codex `thread_id` mirror, targeted session/resume tests.
- `R2 Codex behavior drift`: extracting a provider seam could accidentally change Codex flags, prompts, or resume handling. Mitigation: preserve current Codex resolver/parser code paths behind the new abstraction and add explicit no-behavior-change tests.
- `R3 Claude inherited-environment nondeterminism`: hooks, skills, output styles, plugins, or subagents may violate loop-control expectations. Mitigation: strengthen appended orchestration instructions and keep strict mode deferred/opt-in rather than default.
- `R4 Operator confusion about prerequisites`: docs and installer messaging currently imply Codex-only support. Mitigation: update requirements/setup messaging alongside the code change.
- `R5 Permission prompt dead-ends`: inherited Claude permissions may block unattended runs. Mitigation: document `inherit` as default, surface raw provider failures clearly, and support `allow_core_tools` / `bypass` as explicit user choices.

## Rollout And Rollback
- Rollout order:
  1. land provider-neutral runtime/state refactor with Codex kept green
  2. land Claude adapter behind `provider.name: claude`
  3. complete unit coverage and documented live validation before recommending Claude generally
  4. only then consider strict-mode/tool restriction work if validation shows default inherited mode is too noisy
- Rollback:
  - switch configs back to `provider.name: codex`
  - disable/remove the Claude resolver branch without reverting the broader task/phase/run artifact layout
  - keep legacy session loading intact so old Codex runs remain resumable

## Definition Of Done
- Autoloop can start a Claude-backed session with `claude -p`.
- Autoloop can resume the same Claude conversation using persisted `session_id`.
- Session files persist provider-neutral state and still load legacy Codex `thread_id` state safely.
- Default Claude mode preserves the user’s Claude Code environment instead of bypassing it.
- Optional explicit Claude model, effort, and permission overrides work when configured.
- Canonical loop-control output remains the only orchestration contract across plan/implement/test.
- Codex behavior, resume flow, and existing artifact paths remain unchanged for current users.
- No Anthropic or Claude SDK is introduced anywhere in the implementation.
