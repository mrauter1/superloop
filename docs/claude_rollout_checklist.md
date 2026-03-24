# Claude Rollout Checklist

Use this checklist before recommending `provider.name: claude` as a default team workflow.

## Preflight

- Confirm `claude --version` succeeds on the operator machine.
- Confirm `claude auth status` succeeds with the intended local account.
- Confirm the repo can still run `autoloop --no-git` and normal git-backed runs without changing provider config.

## Fresh and resumed sessions

- Start a fresh Claude-backed run with `provider.name: claude`.
- Verify the saved session file records `provider: claude`, `session_id`, and Claude `provider_metadata`.
- Resume the same run and verify Autoloop uses `--resume <session_id>` rather than starting a new session.
- Confirm resume fails fast if the saved session provider is `claude` and the operator switches config back to `codex`, or vice versa.

## Inherited-environment validation

Run representative `plan`, `implement`, and `test` loops in repositories that exercise Claude Code configuration features Autoloop intentionally inherits.

- Repo with `CLAUDE.md`.
- Repo with custom Claude output styles.
- Repo with Claude hooks enabled.
- Repo with Claude skills present.
- Repo with Claude plugins present.
- Repo with Claude MCP servers configured.
- Repo with Claude subagents enabled.

For each run:

- Verify Claude keeps clarifications and completion decisions inside Autoloop’s canonical loop-control block.
- Verify Autoloop does not need `--bare`, tool restriction flags, or system-prompt replacement flags in the default path.
- Verify task and run raw logs capture enough provider output to diagnose failures.

## Permission strategies

- Validate default `permission_strategy: inherit` in a normal local environment.
- Validate `permission_strategy: allow_core_tools` and confirm `Read,Write,Edit,Glob,Grep,Bash` run without the prompts you expect.
- Validate `permission_strategy: bypass` only inside an isolated environment such as a container or VM.

## Config-drift resume checks

- Start a Claude-backed run, then change `CLAUDE.md` before resuming and observe whether the resumed session keeps expected loop-control behavior.
- Start a Claude-backed run, then change Claude output style before resuming and compare the resumed session with a brand-new session started after the change.
- Start a Claude-backed run, then change hooks, skills, plugins, or MCP configuration before resuming and verify Autoloop still gets canonical loop-control output.

## Deferred follow-up work

Do not treat these as v1 rollout blockers unless the validation above exposes a concrete need.

- Strict mode or default tool restrictions.
- `stream-json` telemetry and partial-message capture.
