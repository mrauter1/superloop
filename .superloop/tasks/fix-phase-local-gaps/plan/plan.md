# Plan: Fix Remaining Phase-Local Contract Gaps

## Objective
Finish the remaining phase-local contract cleanup in Superloop without changing the CLI. The current working tree already contains most of the requested session/bootstrap contract changes, so the implementation focus for this run is to preserve those behaviors, close the remaining repository-hygiene gap end to end, and verify the result with the requested focused and full test passes.

## Scope Considered
In scope:
- [`/workspace/superloop/superloop.py`](/workspace/superloop/superloop.py) session-routing helpers, fresh-phase bootstrap plumbing, and git staging/commit paths that can still surface volatile run artifacts.
- [`/workspace/superloop/tests/test_phase_local_behavior.py`](/workspace/superloop/tests/test_phase_local_behavior.py) helper-level regressions for strict session routing, bootstrap contents/order, prior-phase context, and size-cap behavior.
- [`/workspace/superloop/tests/test_superloop_observability.py`](/workspace/superloop/tests/test_superloop_observability.py) higher-level observability and hygiene regressions for run-path keys, prompt preambles, and tracked/staged path selection.
- [`/workspace/superloop/Readme.md`](/workspace/superloop/Readme.md) only if implementation reveals wording drift from the now-strict scoped-session contract.
- [`/workspace/superloop/.gitignore`](/workspace/superloop/.gitignore) only as secondary cleanliness protection for newly generated run outputs after runtime staging behavior is correct.

Out of scope:
- New CLI flags, config knobs, or alternate runtime modes.
- Reworking the phased prompt structure beyond what is required to preserve the current six-section bootstrap contract.
- Broad cleanup of unrelated historical `.superloop/tasks/*/runs/*` artifacts already present in the repository.
- Depending on live run outputs for tests instead of `tmp_path` or deterministic fixtures.

## Current Code Status
- `create_run_paths(...)` and `open_existing_run_paths(...)` already expose `plan_session_file` and `sessions_dir` without returning the legacy `session_file` alias.
- `build_phase_prompt(...)` already requires an explicit `session_file: Path`, and prompt preambles now surface the scoped authoritative session file instead of falling back to `cwd/session.json`.
- Fresh-phase bootstrap assembly already receives explicit `prior_phase_ids` and `prior_phase_keys`, preserves the six required sections and order, emits repo-relative prior artifact paths under `.superloop/tasks/<task-id>/...`, and enforces `MAX_FRESH_PHASE_BOOTSTRAP_BYTES`.
- The focused tests already cover the strict session contract, no-`session.json` prompt regressions, bootstrap section ordering, and oversize-bootstrap failure behavior.
- `tracked_superloop_paths(...)` already excludes `runs/`, and the README already states that phased execution uses scoped session files with no legacy run-level `session.json` fallback.
- The remaining material gap is repository hygiene in diff-based commit flows: `producer_delta`, `verifier_delta`, and pair-complete/blocked commits are still built from raw snapshot diffs around `run_codex_phase(...)`, which writes session/log artifacts under `.superloop/tasks/*/runs/*`. Those deltas can still sweep volatile run files into normal code-focused commits even though tracked path helpers now exclude `runs/`.
- `.gitignore` still does not ignore generated task run outputs, so local status noise remains possible for newly created untracked run directories. This is secondary to the runtime staging fix, not a substitute for it.
- The current worktree already shows unrelated generated task-run directories for prior runs plus a user-modified `.gitignore`; the implementation pair must treat those as existing dirty state, avoid absorbing them into scope, and only move to deterministic fixtures if a new regression truly requires sample data.

## Key Decisions
- Keep this as one implementation phase. The remaining work is tightly coupled: session/bootstrap behavior is already present and should be preserved while the final hygiene fix and its regressions are added.
- Treat the strict session/bootstrap behavior in the working tree as the baseline contract. The implementation pair should not reopen those interfaces unless focused/full tests reveal a concrete regression.
- Close repository hygiene at every code-focused commit boundary, not just `tracked_superloop_paths(...)`. Any path set derived from `changed_paths_from_snapshot(...)` must also exclude `.superloop/tasks/*/runs/*`.
- Keep `.gitignore` optional and secondary. It can reduce local noise for future untracked run directories, but correctness must come from commit-path filtering because tracked files and explicit staging bypass ignore rules.
- Continue to avoid committed runtime outputs as tests. If a stable sample is required, use the smallest deterministic fixture under `tests/fixtures/`; otherwise keep using `tmp_path`.

## Implementation Phase
### Phase 1: Preserve Strict Session Contracts And Finish Runtime Hygiene

#### Milestone 1: Preserve the already-landed strict session/bootstrap contract
- Keep the existing `plan_session_file`/phase-session routing contract intact.
- Keep `build_phase_prompt(...)` explicit about `session_file` and prevent any reintroduction of `session.json` fallback semantics.
- Keep fresh bootstrap assembly explicit about ordered prior-phase context and preserve the required section list and order:
  `INITIAL REQUEST SNAPSHOT`
  `AUTHORITATIVE CLARIFICATIONS TO DATE`
  `PRIOR PHASE STATUS IN THIS RUN`
  `RELEVANT PRIOR PHASE ARTIFACT PATHS`
  `ACTIVE PHASE EXECUTION CONTRACT`
  `ACTIVE PHASE ARTIFACTS`
- Only touch these areas if the hygiene changes or regression tests expose real drift.

#### Milestone 2: Close the remaining run-artifact hygiene gap in commit flows
- Audit every code-focused commit call site, not only `tracked_superloop_paths(...)`.
- Introduce a small helper or equivalent filtering rule that removes `.superloop/tasks/<task-id>/runs/...` paths from arbitrary changed-path sets derived from `changed_paths_from_snapshot(...)`.
- Apply that filtering to producer-edit commits, verifier-feedback commits, pair-complete commits, and blocked-path commits so volatile run artifacts do not enter normal source diffs through snapshot deltas.
- Preserve legitimate task artifacts and active phase artifacts while filtering only volatile run-output paths.
- Leave the existing baseline/success/finalize tracked-path behavior intact unless the implementation finds a concrete inconsistency.

#### Milestone 3: Add hygiene regressions and optional secondary cleanliness
- Add or update tests so the runtime explicitly proves that code-focused commit path selection cannot include `.superloop/tasks/*/runs/*`, even when raw snapshot diffs contain both run artifacts and real phase/code edits.
- Keep the existing strict session/bootstrap regressions passing after the hygiene changes.
- Add a narrow `.gitignore` rule for generated task run outputs only if it improves local cleanliness without obscuring intended deterministic fixtures.

## Interfaces And Contracts
### Run path helper contract
- `create_run_paths(...)` and `open_existing_run_paths(...)` expose `run_dir`, `run_log`, `raw_phase_log`, `events_file`, `summary_file`, `request_file`, `sessions_dir`, and `plan_session_file`.
- They must not expose the legacy alias key `session_file`.

### Prompt construction contract
- `build_phase_prompt(...)` requires `session_file: Path`.
- Prompt preambles must show the scoped authoritative session file supplied by the caller.
- No prompt path or bootstrap section may surface a fallback `session.json`.

### Fresh bootstrap contract
- Caller-provided ordered prior-phase context remains explicit via `prior_phase_ids` and `prior_phase_keys`, or an equivalent equally explicit caller-computed form.
- The bootstrap must preserve the six required sections in the required order.
- Prior status lines must come from earlier phases in the current run.
- Prior artifact paths must be repo-relative under `.superloop/tasks/<task-id>/...`.
- Bootstrap size is capped by one named UTF-8 byte limit, with a clear fail-fast error and no truncation.

### Repository hygiene contract
- `.superloop/tasks/*/runs/*` outputs are volatile orchestration artifacts and must not be included in normal code-focused commits.
- Excluding `runs/` from `tracked_superloop_paths(...)` is necessary but not sufficient; any snapshot-delta commit path must also filter those paths out.
- Ignore rules are optional secondary protection only.
- Tests must not depend on live run outputs under `.superloop/tasks/*/runs/*`.

## Concrete File Targets
- [`/workspace/superloop/superloop.py`](/workspace/superloop/superloop.py)
  preserve the strict session/bootstrap contract and implement any missing diff-path filtering for volatile run outputs.
- [`/workspace/superloop/tests/test_phase_local_behavior.py`](/workspace/superloop/tests/test_phase_local_behavior.py)
  preserve current helper-level regressions and add any narrowly missing coverage exposed by the hygiene fix.
- [`/workspace/superloop/tests/test_superloop_observability.py`](/workspace/superloop/tests/test_superloop_observability.py)
  add the end-to-end hygiene regression around code-focused commit path selection and keep existing observability assertions intact.
- [`/workspace/superloop/Readme.md`](/workspace/superloop/Readme.md)
  only if the implementation changes expose wording drift.
- [`/workspace/superloop/.gitignore`](/workspace/superloop/.gitignore)
  only if secondary local-noise suppression is still desirable after the runtime fix.
- [`/workspace/superloop/tests/fixtures`](/workspace/superloop/tests/fixtures)
  only if a deterministic sample is strictly required for a new regression.

## Test Plan
- Required focused suite:
  `PYTHONPATH=/workspace/superloop pytest -q tests/test_phase_local_behavior.py tests/test_superloop_observability.py`
- Full suite if feasible:
  `PYTHONPATH=/workspace/superloop pytest -q`
- Required assertions after implementation:
  `run_paths` still omit `session_file`;
  `build_phase_prompt(...)` still requires an explicit scoped session file and never surfaces `session.json`;
  fresh bootstrap still contains the six required sections in order with repo-relative prior artifact paths;
  oversize fresh bootstrap still fails explicitly without truncation;
  `tracked_superloop_paths(...)` still excludes `runs/`;
  code-focused commit path filtering also excludes `.superloop/tasks/*/runs/*` when snapshot deltas contain both volatile run outputs and legitimate edits.

## Risks And Controls
| Risk | Why it matters | Control |
| --- | --- | --- |
| Hygiene changes filter too narrowly | Volatile run artifacts still leak into producer/verifier/pair commits | Add one shared filtering helper or equivalent single rule and lock it with explicit regression coverage |
| Hygiene changes filter too broadly | Legitimate phase artifacts or real code edits could be dropped from commits | Limit filtering to `.superloop/tasks/<task-id>/runs/...` and test mixed path sets containing both allowed edits and run artifacts |
| Session/bootstrap behavior regresses while fixing hygiene | The current working tree already satisfies most of the request and should not be destabilized | Preserve existing helper signatures/behavior and rerun the focused strict-session/bootstrap tests after each hygiene change |
| `.gitignore` is used as the primary fix | Explicit staging and already tracked files would still bypass it | Keep ignore rules optional and secondary; make runtime commit filtering the acceptance gate |
| Dirty generated run directories in the worktree create review noise | The implementation pair could accidentally absorb volatile artifacts into scope | Do not stage or edit existing generated run outputs unless moving a minimal deterministic sample into `tests/fixtures/` is explicitly required |

## Execution Notes
- No clarifying question is required. The request is specific, the raw log for this run has no later clarification entries, and the remaining implementation gap is concrete.
- The implementation pair should treat the current strict session/bootstrap code and tests as the expected contract, close the remaining runtime hygiene gap, run the requested tests, and finish with the run event stream ending in `run_finished` with status `success`.
- Use the authoritative request and session files for this run under `.superloop/tasks/fix-phase-local-gaps/runs/run-20260321T180746Z-6bd1961f/`; do not rely on artifacts from the earlier planning run except as historical reference.
