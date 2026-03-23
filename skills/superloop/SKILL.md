---
name: superloop
description: Use when running or operating the Superloop orchestration runtime, including starting new loops, resuming tasks, phase-scoped runs, troubleshooting stuck-looking runs, and interpreting run artifacts. Do not use for unrelated coding tasks.
---

# Superloop skill

Use this skill for tasks that involve executing Superloop itself (`superloop.py`), reading its run artifacts, or guiding users through Superloop workflows.

## Purpose

Superloop orchestrates multi-stage producer/verifier loops (plan, implement, test) with durable run state and explicit completion signals.

Use this skill to:
- start a new Superloop run
- resume or continue an existing task/run
- run a subset of pairs (`plan`, `implement`, `test`)
- analyze run outputs under `.superloop/tasks/...`
- diagnose blocked or incomplete verifier outcomes

## Canonical commands

From the Superloop repository root:

```bash
superloop --help
```

Typical new run:

```bash
superloop \
  --workspace /path/to/target/repo \
  --intent "<user goal>"
```

Target specific pairs:

```bash
superloop \
  --workspace /path/to/target/repo \
  --pairs plan,implement,test \
  --intent "<user goal>"
```

Resume task:

```bash
superloop \
  --workspace /path/to/target/repo \
  --task-id <task-id> \
  --intent "<updated goal or clarification>"
```

## Execution policy (critical)

- **Never kill a running Superloop process just because output appears idle.**
- Superloop may look quiet while waiting on long-running server-side model execution.
- Only terminate Superloop if the user explicitly asks, or if there is clear evidence of an unrecoverable local failure (for example: repeated immediate crashes with traceback, missing binary, or permission denial).
- If a run appears stalled, inspect logs/artifacts first and report status instead of interrupting execution.

## Stalled-looking run checklist

1. Confirm the process is still alive.
2. Check recent updates in run artifacts:
   - `.superloop/tasks/<task-id>/runs/<run-id>/run_log.md`
   - `.superloop/tasks/<task-id>/runs/<run-id>/raw_phase_log.md`
   - `.superloop/tasks/<task-id>/runs/<run-id>/events.jsonl`
3. Verify whether Superloop is waiting on a verifier decision or clarification.
4. Prefer `resume`/follow-up intent over force-killing.

## Guardrails

- Keep work scoped to the user-selected workspace (`--workspace`).
- Preserve git history unless user explicitly requests otherwise.
- Use `--no-git` only when git is unavailable or explicitly requested.
- Report exact commands executed and key artifact paths when summarizing outcomes.
