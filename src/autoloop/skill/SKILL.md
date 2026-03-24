---
name: autoloop
description: Use when running or operating the Autoloop orchestration runtime, including starting new loops, resuming tasks, phase-scoped runs, troubleshooting stuck-looking runs, and interpreting run artifacts. Do not use for unrelated coding tasks.
---

# Autoloop skill

Use this skill for tasks that involve executing Autoloop itself (`autoloop` or `python -m autoloop`), reading its run artifacts, or guiding users through Autoloop workflows.

## Purpose

Autoloop orchestrates multi-stage producer/verifier loops (plan, implement, test) with durable run state and explicit completion signals.

Use this skill to:
- start a new Autoloop run
- resume or continue an existing task/run
- run a subset of pairs (`plan`, `implement`, `test`)
- analyze run outputs under `.autoloop/tasks/...`
- diagnose blocked or incomplete verifier outcomes

## Canonical commands

From the Autoloop repository root:

```bash
autoloop --help
```

Typical new run:

```bash
autoloop \
  --workspace /path/to/target/repo \
  --intent "<user goal>"
```

Resume task:

```bash
autoloop \
  --workspace /path/to/target/repo \
  --task-id <task-id> \
  --resume
```

## Execution policy

- Never kill a running Autoloop process just because output appears idle.
- Only terminate Autoloop if the user explicitly asks, or if there is clear evidence of an unrecoverable local failure.
- If a run appears stalled, inspect logs and artifacts first and report status instead of interrupting execution.

## Stalled-looking run checklist

1. Confirm the process is still alive.
2. Check recent updates in run artifacts:
   - `.autoloop/tasks/<task-id>/runs/<run-id>/raw_phase_log.md`
   - `.autoloop/tasks/<task-id>/runs/<run-id>/events.jsonl`
3. Verify whether Autoloop is waiting on a verifier decision or clarification.
4. Prefer `--resume` or follow-up intent over force-killing.

## Guardrails

- Keep work scoped to the user-selected workspace (`--workspace`).
- Preserve git history unless the user explicitly requests otherwise.
- Use `--no-git` only when git is unavailable or explicitly requested.
- Report exact commands executed and key artifact paths when summarizing outcomes.
