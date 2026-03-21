PRD: Phase-Local Mutable Artifacts and Per-Phase Codex Threads for Superloop

1. Summary

Superloop already treats implement and test as phase-scoped at runtime, but it still stores their mutable artifacts and Codex conversation state too broadly. That causes cross-phase contamination in criteria, feedback, notes, and thread memory.

This change makes Superloop internally consistent by introducing two rules:
1. plan remains task-global.
2. Every non-global mutable artifact and every Codex session for implement and test is resolved from the active phase.

2. Goals
- Keep plan task-global.
- Make all non-global mutable artifacts for implement and test phase-local.
- Use a separate Codex thread for each execution phase.
- Share the same phase thread across implement and test within that phase.
- Start a fresh thread automatically when moving to the next phase.
- Bootstrap fresh phase threads from existing authoritative artifacts only.
- Add no extra Codex summarization call.
- Add no new summary or handoff artifact.
- Preserve user-edited prompt files by never auto-overwriting prompts.
- Keep the CLI surface unchanged.

3. Non-Goals
- No new CLI flags.
- No external dependencies.
- No prompt migration or forced prompt refresh behavior.
- No concurrent phase execution.

4. Core design decisions
- plan stays task-global.
- implement/test mutable artifacts are phase-local.
- one plan thread per run.
- one separate thread per execution phase.
- implement/test share the same phase thread.
- moving phase means different session file.
- never overwrite existing prompt.md or verifier_prompt.md.

5. Filesystem layout
Task-global:
.superloop/tasks/<task-id>/plan/{prompt.md,verifier_prompt.md,criteria.md,feedback.md,plan.md,phase_plan.yaml}

Pair root:
.superloop/tasks/<task-id>/implement/{prompt.md,verifier_prompt.md,phases/}
.superloop/tasks/<task-id>/test/{prompt.md,verifier_prompt.md,phases/}

Phase-local implement:
.superloop/tasks/<task-id>/implement/phases/<phase-dir-key>/{criteria.md,feedback.md,implementation_notes.md,review_findings.md}

Phase-local test:
.superloop/tasks/<task-id>/test/phases/<phase-dir-key>/{criteria.md,feedback.md,test_strategy.md,test_gaps.md}

6. Session layout
.superloop/tasks/<task-id>/runs/<run-id>/sessions/plan.json
.superloop/tasks/<task-id>/runs/<run-id>/sessions/phases/<phase-dir-key>.json

7. Phase ID and key
- phase_id must be non-empty, unique in plan, <=96 UTF-8 bytes.
- if phase_id matches ^[a-z0-9][a-z0-9._-]*$ use verbatim.
- else use _pid-<utf8-hex>.

8. Runtime requirements
- ensure_workspace creates pair-root prompts when missing and implement/test phases dirs.
- no eager creation of phase-local mutable artifacts.
- lazy creation on active phase execution; never overwrite existing files.
- plan uses sessions/plan.json.
- phased pairs use sessions/phases/<phase-dir-key>.json.
- pending clarification note stored in scope-specific session file.

9. Fresh phase thread bootstrap sections
- INITIAL REQUEST SNAPSHOT
- AUTHORITATIVE CLARIFICATIONS TO DATE
- PRIOR PHASE STATUS IN THIS RUN
- RELEVANT PRIOR PHASE ARTIFACT PATHS
- ACTIVE PHASE EXECUTION CONTRACT
- ACTIVE PHASE ARTIFACTS

10. Testing requirements (minimum)
- criteria regex handles column-0 and indented unchecked boxes.
- phase key generation and length validation.
- workspace bootstrap creates plan global artifacts and pair phases dirs but not pair-root mutable implement/test files.
- lazy phase artifact creation and no overwrite.
- session resolution: plan session path + per-phase sharing between implement/test.
- bootstrap extraction and fresh vs resumed prompt behavior.
- verifier scope flags other-phase edits.

11. Central invariant
For phased pairs, resolve mutable artifacts and Codex session state from the active phase, never from pair root or run-global session.
