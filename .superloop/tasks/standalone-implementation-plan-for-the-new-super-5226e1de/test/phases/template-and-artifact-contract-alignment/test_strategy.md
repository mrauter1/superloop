# Test Strategy

- Task ID: standalone-implementation-plan-for-the-new-super-5226e1de
- Pair: test
- Phase ID: template-and-artifact-contract-alignment
- Phase Directory Key: template-and-artifact-contract-alignment
- Phase Title: Align templates and scaffolded artifact layout
- Scope: phase-local producer artifact

## Behavior Coverage Map
- Workspace scaffolding: `tests/test_superloop_observability.py` verifies task-root `decisions.txt` creation, absence of task `run_log.md`, and absence of copied pair prompt files.
- Run scaffolding: `tests/test_superloop_observability.py` verifies new run directories create `request.md`, `raw_phase_log.md`, `events.jsonl`, and sessions only, with no `run_log.md` or `summary.md`.
- Phase artifact scaffolding: `tests/test_phase_local_behavior.py` verifies implement/test phase artifact bundles no longer include `review_findings.md` or `test_gaps.md`.
- Prompt sourcing: `tests/test_superloop_observability.py` and `tests/test_phase_local_behavior.py` verify prompt construction uses rendered shared template text in memory and includes the authoritative `decisions.txt` path in the preamble.
- Runtime logging preservation: `tests/test_superloop_observability.py` verifies resume/recovery notices remain in raw logs after removal of run-log/summary files.

## Preserved Invariants Checked
- Criteria templates remain untouched by this phase.
- `raw_phase_log.md` remains the authoritative chronological log.
- `events.jsonl` remains the machine-readable run lifecycle stream.

## Edge Cases
- Missing prompt template still fails fast in workspace setup.
- Resume paths without a stored session thread id still log recovery in raw logs.
- Legacy request snapshot reconstruction still works without relying on removed run-log artifacts.

## Failure Paths
- Fatal runs still emit terminal `run_finished` events without recreating `summary.md`.
- Verifier and producer delta filtering still excludes volatile run-scoped files after summary removal.

## Known Gaps
- No additional gap beyond the explicitly deferred later-phase work on `decisions.txt` sequencing and verifier-scope artifact splitting.
