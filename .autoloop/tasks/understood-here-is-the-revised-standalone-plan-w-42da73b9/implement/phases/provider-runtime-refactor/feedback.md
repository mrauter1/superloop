# Implement ↔ Code Reviewer Feedback

- Task ID: understood-here-is-the-revised-standalone-plan-w-42da73b9
- Pair: implement
- Phase ID: provider-runtime-refactor
- Phase Directory Key: provider-runtime-refactor
- Phase Title: Provider-Neutral Runtime Refactor
- Scope: phase-local authoritative verifier artifact

## Findings

- IMP-001 `blocking` — `src/autoloop/main.py:load_session_state`
  Legacy session migration does not always infer `provider="codex"` when the saved payload predates the new provider field. For an existing legacy session file that has no `provider` key and no `thread_id`/`session_id` yet, `load_session_state(..., default_provider=runtime_config.provider.name)` currently adopts the selected provider instead of normalizing the persisted run state to Codex. That contradicts the accepted migration rule in the request and decisions ledger, and it will let old Codex runs silently appear provider-compatible once Claude execution is added. Minimal fix: treat any existing session payload without an explicit `provider` as `codex`, regardless of whether a thread/session id is present; reserve `default_provider` only for missing session files / new session initialization. Add a regression test covering a legacy payload with `thread_id: null`.

- IMP-002 `non-blocking` — `src/autoloop/main.py:run_provider_phase`
  The new provider seam still hard-codes Codex-specific log/process labels and warning text (`"codex-agent"`, `"Codex CLI did not return a thread id"`). That does not break this phase because Claude execution is still out of scope, but it leaves follow-on Claude work touching multiple Codex-named branches inside the supposedly provider-neutral path. Minimal fix: centralize provider display/process naming alongside `ProviderRuntime` before the Claude adapter lands.

## Re-review Outcome

- IMP-001 resolved in cycle 2: `load_session_state` now treats any existing payload without an explicit `provider` field as legacy Codex state, and regression coverage now includes the `thread_id: null` legacy case.
- No blocking findings remain for this phase slice.
- IMP-002 remains non-blocking follow-up work for the later Claude adapter phase.
