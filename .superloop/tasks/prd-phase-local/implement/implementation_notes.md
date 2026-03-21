# implementation_notes.md

## Files changed
- `superloop.py`
- `tests/test_superloop_observability.py`
- `Readme.md`

## Checklist mapping
- Prompt-template wording for phased implement/test artifacts and active session scope: completed in `superloop.py`.
- README filesystem/session layout alignment: completed in `Readme.md`.
- Focused regression coverage for seeded prompt wording and active session path injection: completed in `tests/test_superloop_observability.py`.
- Existing runtime helpers for phase keying, lazy artifact creation, session routing, clarification persistence, bootstrap freshness, and verifier scope: left unchanged because the current focused tests and code paths already matched the approved plan.

## Assumptions
- The PRD scope for this phase is contract alignment, not redesign; existing runtime helpers remain the source of truth unless a regression test proves otherwise.
- Existing task-local prompt files remain user-owned and are intentionally not migrated; only built-in templates for future workspace bootstraps changed.

## Expected side effects
- Newly bootstrapped phased tasks will instruct implement/test producers and verifiers to use active-phase artifact paths instead of legacy pair-root mutable files.
- README examples now match the current runtime layout, including `sessions/plan.json` and per-phase session files.
- Focused tests will fail if future prompt-template edits reintroduce pair-root phased artifact references or omit the active phase session path from the preamble.

## Deduplication / centralization decisions
- No helper refactor was introduced. The runtime already centralizes artifact/session routing in `resolve_artifact_bundle(...)` and `resolve_session_file(...)`, so this change stays at the prompt/docs/test boundary.
