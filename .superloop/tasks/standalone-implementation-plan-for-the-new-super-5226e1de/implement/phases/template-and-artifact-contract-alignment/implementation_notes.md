# Implementation Notes

- Task ID: standalone-implementation-plan-for-the-new-super-5226e1de
- Pair: implement
- Phase ID: template-and-artifact-contract-alignment
- Phase Directory Key: template-and-artifact-contract-alignment
- Phase Title: Align templates and scaffolded artifact layout
- Scope: phase-local producer artifact
- Files changed: `superloop.py`, `templates/plan_producer.md`, `templates/plan_verifier.md`, `templates/implement_producer.md`, `templates/implement_verifier.md`, `templates/test_producer.md`, `templates/test_verifier.md`, `tests/test_superloop_observability.py`, `tests/test_phase_local_behavior.py`
- Symbols touched: `IMPLEMENT_PHASE_LOCAL_ARTIFACTS`, `TEST_PHASE_LOCAL_ARTIFACTS`, `PAIR_ARTIFACTS`, `load_pair_templates()`, `rendered_pair_template()`, `_phase_artifact_template()`, `resolve_artifact_bundle()`, `ensure_workspace()`, `create_run_paths()`, `open_existing_run_paths()`, `append_runtime_notice()`, `build_phase_prompt()`, `run_codex_phase()`, `format_question()`, `execute_pair_cycles()`, `main()`
- Checklist mapping: prompt templates replaced verbatim; task/run scaffolding trimmed to the final artifact set for this phase; prompt sourcing moved to shared templates rendered in memory; redundant phase artifacts removed from scaffolding and tests
- Assumptions: documentation files and `legacy/superloop.py` remain out of scope for this phase-local implementation slice
- Preserved invariants: `raw_phase_log.md` remains the chronological runtime log; `events.jsonl` remains the run lifecycle stream; criteria templates remain unchanged
- Intended behavior changes: new task workspaces create `decisions.txt`; task/run `run_log.md` and run `summary.md` are no longer created or written; prompt files are no longer copied into task pair directories; implement/test phase scaffolding no longer creates `review_findings.md` or `test_gaps.md`
- Known non-changes: decisions header parsing, turn sequencing, clarification mirroring into `decisions.txt`, and verifier-scope artifact splitting are intentionally deferred to later phases
- Expected side effects: session-turn raw logs now record shared template provenance instead of task-local prompt paths
- Validation performed: updated unit tests for artifact layout, in-memory prompt rendering, prompt preamble decisions-file exposure, and removal of run summary/log expectations
- Deduplication or centralization decisions: prompt sourcing now flows through `load_pair_templates()` plus a single in-memory `rendered_pair_template()` helper rather than task-local copied prompt files
