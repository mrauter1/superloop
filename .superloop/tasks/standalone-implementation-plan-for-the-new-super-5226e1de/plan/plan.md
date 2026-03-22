# Standalone Implementation Plan For The New Superloop Flow

## Objective
Refactor Superloop to use one shared task-scoped append-only `decisions.txt` ledger, load prompt text directly from `templates/`, remove obsolete run-log and summary artifacts, remove redundant phase artifacts, keep raw logs and `events.jsonl` authoritative for chronology and machine-readable lifecycle data, and preserve verifier read-only treatment for `decisions.txt`.

## Scope And Constraints
- Treat the immutable request snapshot as the implementation contract.
- Apply the six appendix prompt templates verbatim in `templates/`.
- Keep the three criteria templates as-is.
- Do not add backward-compatibility or migration work beyond tolerating legacy files if present.
- Keep `decisions.txt` plain-text append-only body content, one meaningful item per line, with runtime-owned deterministic header tags.
- Producers may append only under the latest runtime-created producer header for their turn; verifiers remain read-only for `decisions.txt`.

## Implementation Strategy
1. Replace the shared prompt templates first so runtime behavior and tests align with the locked prompt contract before touching orchestration.
2. Update artifact constants and workspace/run scaffolding so newly-created workspaces match the final filesystem layout and no code continues depending on copied prompt files or removed artifacts.
3. Refactor prompt construction to read shared templates in memory, render task-relative paths without writing task-local prompt files, and include the authoritative `decisions.txt` path plus template provenance in prompt/log output.
4. Split tracked Superloop artifacts from verifier-exempt runtime bookkeeping so `decisions.txt` is tracked for staging/commits but still visible to verifier scope enforcement.
5. Add direct `decisions.txt` parsing and append helpers, then integrate producer pre-header creation, empty producer-block cleanup, clarification question/answer block appends, and prompt/body semantics around `format_question(...)`.
6. Remove obsolete run-log and run-summary helpers/call sites, update completion/failure staging paths, and refresh tests to cover the new artifact layout, prompt sourcing, decisions flow, clarification flow, and verifier scope enforcement.

## Planned Phases
### Phase 1: Template And Artifact Contract Alignment
- Replace `templates/plan_producer.md`, `templates/plan_verifier.md`, `templates/implement_producer.md`, `templates/implement_verifier.md`, `templates/test_producer.md`, and `templates/test_verifier.md` with the appendix text verbatim.
- Update `IMPLEMENT_PHASE_LOCAL_ARTIFACTS`, `TEST_PHASE_LOCAL_ARTIFACTS`, `PAIR_ARTIFACTS`, and `_phase_artifact_template(...)` so `review_findings.md` and `test_gaps.md` disappear everywhere.
- Update `ensure_workspace(...)`, `create_run_paths(...)`, and `open_existing_run_paths(...)` to create `decisions.txt`, stop creating task/run `run_log.md`, stop creating run `summary.md`, and stop copying prompts into task pair directories.
- Preserve criteria scaffolding in task/phase artifact directories because criteria remains verifier-owned mutable state.

### Phase 2: Shared Prompt Loading And Artifact Ownership Split
- Refactor `build_phase_prompt(...)` and `run_codex_phase(...)` so prompt source text comes from `load_pair_templates()` and `render_task_prompt(...)` in memory rather than from task-local `prompt.md` files.
- Change prompt provenance logging in raw logs to record template filename/path instead of a workspace prompt file.
- Add the authoritative shared decisions path to every prompt preamble without inlining the whole file.
- Replace the current single `superloop_artifact_paths(...)` / `is_superloop_artifact_path(...)` concept with separate tracked-artifact and verifier-exempt-runtime-artifact helpers.
- Ensure `decisions.txt` is included in tracked staging/commit paths but excluded from verifier exemptions so verifier edits still surface as scope violations.

### Phase 3: Decisions Ledger Runtime Integration
- Add helpers for decisions file resolution, header parsing, sequence allocation, header/block append, and trailing empty producer-block removal.
- Use fixed `phase_id="task-global"` for plan turns and existing phase ids for implement/test turns.
- Pre-create producer headers only for planner, implementer, and test author turns before agent execution; do not create producer headers for verifier turns because verifiers are read-only for `decisions.txt`.
- Enforce the question-turn ordering contract exactly: pre-create the producer header, run the producer turn, remove the trailing producer block if it is empty, then append the runtime questions block, and later append the matching runtime answers block so question turns cannot leave stranded empty producer headers.
- Extend `append_clarification(...)` so runtime appends one questions block and one answers block per clarification turn in `decisions.txt`, linked by `qa_seq`, alongside existing raw-log writes and session updates.
- Update `format_question(...)` to preserve `control.question.text` as the main body and avoid appending a synthetic global best-supposition line.

### Phase 4: Orchestration Cleanup And Regression Coverage
- Delete `append_run_log(...)` and `write_run_summary(...)`, remove all call sites, and simplify `append_runtime_notice(...)` to write only task/run raw logs.
- Update main flow, pair execution, resume handling, blocked/failed/completed status paths, and failure-path commits so nothing references removed run artifacts.
- Refresh or replace tests in `tests/test_superloop_observability.py` and `tests/test_phase_local_behavior.py` to cover new scaffolding, template loading, prompt preambles, tracked-vs-exempt scope rules, clarification-to-decisions behavior, empty producer-block cleanup, and removal of obsolete files.
- Verify there is no remaining dependency on task/run `run_log.md`, task-local prompt files, `summary.md`, `review_findings.md`, or `test_gaps.md`.

## Interfaces And Files Touched
- Runtime/orchestration: `superloop.py`
- Prompt templates: `templates/plan_producer.md`, `templates/plan_verifier.md`, `templates/implement_producer.md`, `templates/implement_verifier.md`, `templates/test_producer.md`, `templates/test_verifier.md`
- Criteria templates: unchanged source of truth in `templates/plan_criteria.md`, `templates/implement_criteria.md`, `templates/test_criteria.md`
- Regression coverage: `tests/test_superloop_observability.py`, `tests/test_phase_local_behavior.py`

## Behavioral Invariants To Preserve
- Raw logs remain the authoritative chronological record for runtime and clarification events.
- `events.jsonl` remains the machine-readable lifecycle stream.
- Verifiers may still edit only their allowed artifact scope plus explicit runtime bookkeeping artifacts; `decisions.txt` must not be verifier-exempt.
- Planner turns remain task-global; implement/test turns remain phase-local.
- Older workspaces may exist, but new code should not depend on legacy artifacts being present.

## Compatibility, Migration, And Rollback
- Compatibility: this is intentionally forward-only for new layout behavior; no migration or preservation logic is required for older workspaces beyond avoiding crashes if legacy files remain on disk.
- Developer workflow change: prompts are no longer materialized into task directories, so any debug/provenance output must point to shared template files instead.
- Rollback path: revert the runtime/orchestration changes and restore artifact constants/tests in one commit if prompt loading or decisions integration destabilizes execution.

## Validation Plan
- Unit-test workspace scaffolding, run scaffolding, prompt construction, artifact ownership/scope logic, clarification persistence, and pair execution paths.
- Add direct tests for `decisions.txt` header parsing, sequence allocation, producer empty-block cleanup, clarification Q/A block append ordering, and verifier scope violations on `decisions.txt`.
- Run the focused pytest coverage for observability and phase-local behavior after refactor.

## Regression Risks
- Prompt refactor could silently break task-relative path rendering or prompt provenance logging.
- Artifact ownership split could accidentally whitelist verifier writes too broadly or stage the wrong files on failure/completion paths.
- Decisions ledger integration could leave empty producer headers behind, allocate inconsistent sequences, or mis-order question/answer blocks relative to producer turns.
- Decisions ledger integration could also regress if verifier turns accidentally receive runtime-created producer headers, because that would violate the read-only verifier contract and muddy block ownership semantics.
- Removing run logs and summaries could break resume/recovery notices and tests that still inspect removed files.

## Minimal Correction Principles During Implementation
- Keep helper additions narrow and local to orchestration concerns.
- Prefer direct parsing of `decisions.txt` over introducing extra manifests or caches.
- Avoid new generic abstractions unless they directly remove duplicated artifact/scope logic.
