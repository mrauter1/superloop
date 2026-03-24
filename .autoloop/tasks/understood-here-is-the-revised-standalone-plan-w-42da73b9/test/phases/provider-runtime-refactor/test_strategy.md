# Test Strategy

- Task ID: understood-here-is-the-revised-standalone-plan-w-42da73b9
- Pair: test
- Phase ID: provider-runtime-refactor
- Phase Directory Key: provider-runtime-refactor
- Phase Title: Provider-Neutral Runtime Refactor
- Scope: phase-local producer artifact

## Behavior Coverage Map
- Provider config compatibility:
  Nested `provider.name` / `provider.codex` / `provider.claude` parsing and legacy flat Codex precedence are covered in `tests/test_autoloop_observability.py`.
- Session migration:
  Legacy payloads with `thread_id` migrate to `provider=codex` plus `session_id`.
  Legacy payloads without `provider` still normalize to Codex even when `thread_id` is null.
  Missing session files still seed the requested `default_provider` for new session initialization.
- Resume safety:
  Explicit provider mismatch on resume fails fast in `main()`.

## Preserved Invariants Checked
- Codex remains the default provider for new run/session creation.
- Codex-backed session files keep a `thread_id` mirror for compatibility.
- Existing observability and phase-local workflows continue to pass end-to-end regression suites.

## Edge Cases
- Existing session file with no `provider` and no active thread/session id.
- Missing session file with a non-default requested provider.

## Failure Paths
- Resume with a stored provider that differs from the selected provider raises a fatal error.

## Stabilization Approach
- Tests are pure unit/integration-style filesystem fixtures under `tmp_path`; no network, subprocess provider calls, timing assertions, or nondeterministic ordering are involved.

## Known Gaps
- Claude subprocess execution, auth preflight, permission strategy flags, and provider-specific logging remain out of scope for this phase and are not encoded in tests here.
