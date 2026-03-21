# PRD Plan: Phase-Local Mutable Artifacts and Per-Phase Codex Threads

## Objective
Finish the PRD by making Superloop's user-facing defaults and regression contracts match the runtime model that already exists in code: `plan` remains task-global, while `implement` and `test` resolve mutable artifacts and Codex session state from the active phase only. Keep the CLI unchanged, add no new summary or handoff artifact, and never auto-overwrite existing task prompt files.

## Verified Current State
- [`/workspace/superloop/superloop.py`](/workspace/superloop/superloop.py) already implements the core phase-local runtime primitives:
  `phase_dir_key(...)`, `phase_artifact_dir(...)`, `plan_session_file(...)`, `phase_session_file(...)`, `resolve_session_file(...)`, `resolve_artifact_bundle(...)`, `ensure_phase_artifacts(...)`, `build_fresh_phase_bootstrap(...)`, and `verifier_scope_violations(...)`.
- `ensure_workspace(...)` already preserves existing `prompt.md` and `verifier_prompt.md`, creates task-global `plan` artifacts, and creates `implement/phases/` and `test/phases/` directories without eagerly creating pair-root mutable artifacts for phased pairs.
- `create_run_paths(...)` and `open_existing_run_paths(...)` already initialize `sessions/plan.json` plus `sessions/phases/`, and the main execution loop already calls `resolve_session_file(...)` per pair/phase before invoking Codex.
- `append_clarification(...)` already stores `pending_clarification_note` in whichever session file the caller provides. In the phased execution path, that caller-provided file is already the active phase session file.
- Targeted tests currently pass with repo-root `PYTHONPATH`:
  [`/workspace/superloop/tests/test_phase_local_behavior.py`](/workspace/superloop/tests/test_phase_local_behavior.py) and [`/workspace/superloop/tests/test_superloop_observability.py`](/workspace/superloop/tests/test_superloop_observability.py) passed together (`67 passed`) after setting `PYTHONPATH=/workspace/superloop`.

## Remaining Gaps To Close
- Built-in implement/test prompt templates in [`/workspace/superloop/superloop.py`](/workspace/superloop/superloop.py) still instruct agents to read and write legacy pair-root files such as `.superloop/implement/implementation_notes.md` and `.superloop/test/test_strategy.md`, even though phased mutable artifacts now live under `implement/phases/<phase-dir-key>/` and `test/phases/<phase-dir-key>/`.
- [`/workspace/superloop/Readme.md`](/workspace/superloop/Readme.md) still documents pair-root mutable implement/test artifacts and a single run-level `session.json`, which conflicts with the current runtime layout.
- The planning artifacts were still underspecifying the clarification-note session contract. The PRD requires `pending_clarification_note` to live in the scope-specific session file, so that requirement must be explicit in both the narrative plan and `phase_plan.yaml`.

## Scope
In scope:
- Align default prompt templates, README documentation, and regression requirements with the existing phase-local artifact/session model.
- Keep the current helper architecture as the canonical path for artifact resolution, session routing, fresh-thread bootstrap, and verifier scope enforcement.
- Add or refine tests only where needed to lock the invariant and the remaining prompt/documentation/session-state expectations.

Out of scope:
- New CLI flags, config knobs, or concurrent phase execution.
- Prompt migration, prompt refresh, or any auto-overwrite of existing task-local `prompt.md` / `verifier_prompt.md`.
- New summary or handoff artifacts.
- Redesign of the already-centralized runtime helpers unless a concrete failing test exposes a contract gap.

## Central Invariant
For phased pairs, resolve mutable artifacts and Codex session state from the active phase, never from the pair root and never from a run-global session shared across phases.

## Implementation Plan
### Milestone 1: Make defaults match the runtime contract
- Update only the built-in prompt templates in [`/workspace/superloop/superloop.py`](/workspace/superloop/superloop.py) that seed future task workspaces.
- Replace legacy pair-root implement/test artifact references with phase-local or scope-neutral wording that matches the authoritative preamble fields already injected at runtime.
- Preserve the current no-overwrite behavior in `ensure_workspace(...)`; existing task prompt files remain user-owned and must not be rewritten.

### Milestone 2: Make session-state behavior explicit and stable
- Treat `resolve_session_file(...)` as the sole authority for pair/phase session routing:
  `plan` uses `sessions/plan.json`; phased `implement` and `test` use `sessions/phases/<phase-dir-key>.json`.
- Keep same-phase `implement` and `test` sharing the same phase session file.
- Keep phase changes mapping to different session files, which creates a fresh thread for the next phase unless that phase session file already exists.
- Make the clarification-note rule explicit in plan artifacts and tests:
  `pending_clarification_note` must be stored in the same scope-specific session file selected by `resolve_session_file(...)`.

### Milestone 3: Lock the contract in docs and tests
- Update [`/workspace/superloop/Readme.md`](/workspace/superloop/Readme.md) so the documented repository/session layout matches the current runtime layout.
- Extend focused tests around:
  prompt-template wording,
  phase key generation and validation,
  lazy phase artifact creation without overwrite,
  plan-vs-phase session routing,
  same-phase implement/test session sharing,
  clarification-note persistence in the scoped session file,
  fresh-vs-resumed phase bootstrap behavior,
  verifier rejection of edits to other phases.

## Interfaces And Contracts
### Filesystem contract
- Task-global plan artifacts:
  `.superloop/tasks/<task-id>/plan/{prompt.md,verifier_prompt.md,criteria.md,feedback.md,plan.md,phase_plan.yaml}`
- Pair-root phased directories:
  `.superloop/tasks/<task-id>/implement/{prompt.md,verifier_prompt.md,phases/}`
  `.superloop/tasks/<task-id>/test/{prompt.md,verifier_prompt.md,phases/}`
- Phase-local implement artifacts:
  `.superloop/tasks/<task-id>/implement/phases/<phase-dir-key>/{criteria.md,feedback.md,implementation_notes.md,review_findings.md}`
- Phase-local test artifacts:
  `.superloop/tasks/<task-id>/test/phases/<phase-dir-key>/{criteria.md,feedback.md,test_strategy.md,test_gaps.md}`
- `ensure_workspace(...)` may create pair-root prompts and `phases/` directories up front, but must not eagerly create pair-root mutable implement/test artifacts.
- `ensure_phase_artifacts(...)` is the only lazy creator for phase-local mutable artifacts and must never overwrite existing files.

### Session file contract
- Plan session file:
  `.superloop/tasks/<task-id>/runs/<run-id>/sessions/plan.json`
- Phase session file:
  `.superloop/tasks/<task-id>/runs/<run-id>/sessions/phases/<phase-dir-key>.json`
- `resolve_session_file(...)` must return `sessions/plan.json` for `plan`.
- `resolve_session_file(...)` must return `sessions/phases/<phase-dir-key>.json` for `implement` and `test` when an active phase is selected.
- `implement` and `test` for the same active phase must share the same phase session file.
- Moving to a different phase must resolve to a different session file.

### Session state contract
- `pending_clarification_note` is scoped exactly like the thread id:
  it must be persisted in `sessions/plan.json` for `plan`, and in `sessions/phases/<phase-dir-key>.json` for phased `implement` / `test`.
- Fresh and resumed behavior must both read clarification state from the same scope-specific session file that the current pair execution is using.
- Clearing `pending_clarification_note` after a successful Codex turn must update that same scope-specific session file, not a pair-root or run-global fallback.

### Phase identity contract
- `phase_id` must be non-empty, unique in the explicit phase plan, and at most 96 UTF-8 bytes.
- If `phase_id` matches `^[a-z0-9][a-z0-9._-]*$`, use it verbatim as the directory/session key.
- Otherwise derive `_pid-<utf8-hex>`.

### Fresh-thread bootstrap contract
On a fresh phased thread, bootstrap content must come only from authoritative artifacts already owned by the run/task and must include:
- `INITIAL REQUEST SNAPSHOT`
- `AUTHORITATIVE CLARIFICATIONS TO DATE`
- `PRIOR PHASE STATUS IN THIS RUN`
- `RELEVANT PRIOR PHASE ARTIFACT PATHS`
- `ACTIVE PHASE EXECUTION CONTRACT`
- `ACTIVE PHASE ARTIFACTS`

On a resumed phased thread, those fresh-thread bootstrap sections must not be re-injected.

### Verifier scope contract
- For phased pairs, verifier writes must be limited to the active phase artifact prefix plus orchestrator-owned run/task bookkeeping files already allowed by `resolve_artifact_bundle(...)`.
- Cross-phase edits, including other phase directories for the same pair, must be flagged as violations.

## Concrete File Targets
- [`/workspace/superloop/superloop.py`](/workspace/superloop/superloop.py)
  update built-in prompt template wording and only adjust helper code if a focused test reveals a missing contract edge.
- [`/workspace/superloop/tests/test_phase_local_behavior.py`](/workspace/superloop/tests/test_phase_local_behavior.py)
  keep unit-style assertions around phase keying, lazy creation, session routing, bootstrap, clarification-note scoping, and verifier scope.
- [`/workspace/superloop/tests/test_superloop_observability.py`](/workspace/superloop/tests/test_superloop_observability.py)
  keep integration-oriented assertions around workspace bootstrap, prompt generation, session recovery, and clarification persistence behavior.
- [`/workspace/superloop/Readme.md`](/workspace/superloop/Readme.md)
  update the documented artifact/session layout to the canonical phase-local model.

## Acceptance Checklist For Implementation
- `criteria_all_checked(...)` recognizes unchecked boxes at both column 0 and indented positions.
- `phase_dir_key(...)` preserves safe ids, hex-encodes unsafe ids, and rejects ids longer than 96 UTF-8 bytes.
- `ensure_workspace(...)` creates task-global plan artifacts, pair-root prompts, and `implement/test` `phases/` directories, but does not create pair-root mutable implement/test artifacts.
- `ensure_phase_artifacts(...)` lazily creates only missing active-phase artifacts and never overwrites existing files.
- `resolve_session_file(...)` returns `sessions/plan.json` for `plan` and `sessions/phases/<phase-dir-key>.json` for phased `implement` / `test`.
- Same-phase `implement` and `test` executions share one session file; moving to a different phase uses a different session file.
- `pending_clarification_note` persists in the same scope-specific session file selected for the current pair execution.
- Fresh phased threads bootstrap only from the request snapshot, explicit clarifications, prior phase status, relevant prior phase artifact paths, active phase contract, and active phase artifact paths.
- Resumed phased threads do not receive fresh bootstrap sections again.
- Verifier scope rejects edits to other phases while allowing the active phase artifact directory and orchestrator-owned run/task files.
- Built-in prompt templates and README no longer describe legacy pair-root mutable implement/test artifacts or a single run-level `session.json`.

## Risks And Controls
| Risk | Why it matters | Control |
| --- | --- | --- |
| Existing task-local prompts may keep legacy wording | Prompt migration is explicitly forbidden, so older tasks can retain outdated prose even after defaults are fixed | Keep runtime preamble authoritative and update only built-in templates for future bootstrap |
| Prompt/docs changes drift from the helper implementation | This PRD is mostly a consistency fix; drift recreates operator confusion and future regressions | Keep helper functions as the canonical contract and update README/prompts/tests in the same slice |
| Session routing or clarification-note scoping regresses on resume | Wrong session selection leaks thread memory across phases or loses clarification carry-forward | Keep routing centralized in `resolve_session_file(...)` and add explicit scoped-session acceptance/tests |
| Verifier scope becomes too permissive or too restrictive | Over-broad scope allows cross-phase contamination; over-tight scope blocks expected verifier updates | Preserve prefix-based enforcement and assert both allowed and rejected paths in focused tests |
| Unnecessary architectural churn broadens blast radius | The core behavior already exists and passes targeted tests, so redesign would add avoidable risk | Limit code changes to defaults, documentation, and only the smallest runtime/test deltas required by failing coverage |

## Execution Notes
- This remains one coherent delivery slice. The codebase does not need a redesign to satisfy the PRD; it needs contract completion and consistency hardening.
- No clarifying question is required. The request is specific, the authoritative raw log contains no later clarifications, and the relevant runtime behavior is already present and verifiable in the repository.
