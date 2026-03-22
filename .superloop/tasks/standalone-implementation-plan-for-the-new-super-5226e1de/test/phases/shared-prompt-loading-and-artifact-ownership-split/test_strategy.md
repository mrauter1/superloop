# Test Strategy

- Task ID: standalone-implementation-plan-for-the-new-super-5226e1de
- Pair: test
- Phase ID: shared-prompt-loading-and-artifact-ownership-split
- Phase Directory Key: shared-prompt-loading-and-artifact-ownership-split
- Phase Title: Load prompts from shared templates and split artifact ownership rules
- Scope: phase-local producer artifact

## Behavior Coverage Map
- Shared-template prompt sourcing: verify prompt construction and execution paths use rendered template text/provenance from `templates/` rather than task-local `prompt.md` copies.
- Prompt preamble decisions path: verify prompt payloads include `AUTHORITATIVE SHARED DECISIONS FILE`.
- Raw-log template provenance: verify `run_codex_phase(...)` writes shared template provenance into task/run raw logs.
- Artifact ownership split: verify tracked Superloop paths include `decisions.txt` while verifier scope enforcement still exempts runtime bookkeeping and still flags verifier edits to `decisions.txt`.

## Preserved Invariants Checked
- No prompt execution path depends on task-local `prompt.md` or `verifier_prompt.md`.
- Runtime bookkeeping paths remain exempt from verifier scope checks.
- `decisions.txt` remains visible to verifier scope enforcement.

## Edge Cases
- Verifier delta includes both exempt runtime bookkeeping paths and forbidden `decisions.txt` writes in the same change set.
- Phase-local verifier scope allows only the active phase artifact prefix while still tolerating runtime bookkeeping paths.

## Failure Paths
- Raw-log provenance test fails if session-turn logging falls back to a workspace `prompt.md` path or omits template provenance entirely.
- Verifier-scope tests fail if `decisions.txt` is accidentally added to the runtime-exempt path set.

## Known Gaps
- This phase does not cover later decisions-ledger runtime block append behavior, which is explicitly out of scope.

## Flake Risks / Stabilization
- Tests are deterministic and use monkeypatched subprocess execution plus temporary files only; no network, timing, or nondeterministic ordering is involved.
