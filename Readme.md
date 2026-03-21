# Superloop

**Protocol-driven agent loops for shipping real code with less babysitting.**

Superloop is a stateful orchestration runtime for repository work. It turns a coding agent into a repeatable delivery loop with explicit planning, implementation, testing, verification, resumability, and git-backed checkpoints.

It was inspired by Ralph-loops and evolves that model into a stricter, more operational system: machine-readable control signals, phase-aware execution, durable run state, verifier-gated completion, and first-class recovery after interruption.

## Why Superloop exists

Most agent workflows look good in demos and degrade in real projects.

The usual failure modes are predictable:

- the plan is vague or drifts from the request
- code gets written without a hard review gate
- tests are partial or bolted on late
- the agent gets interrupted and loses state
- clarification gets handled ad hoc and disappears into chat history
- it is hard to know what actually happened in a run

Superloop is built to solve those operational problems.

It does not try to be a giant prompt pack, a virtual org chart, or a documentation ceremony. It focuses on one thing:

**getting from intent to reviewed implementation with minimal human intervention and a much lower chance of silent failure.**

## What makes Superloop different

### 1. It is a runtime, not just a prompt system

Most alternatives define a methodology.  
Superloop enforces one.

It persists task state, run state, raw outputs, verifier decisions, clarifications, phase status, and resumable session data on disk.

### 2. Verification is a hard gate

A producer does not decide it is done.  
A verifier does.

Each pair loops until the verifier emits a canonical control decision:

- `COMPLETE`
- `INCOMPLETE`
- `BLOCKED`

That makes progress explicit and auditable instead of inferred from prose.

### 3. Planning becomes executable scope

The planning loop produces both human-readable planning artifacts and a machine-readable `phase_plan.yaml`.

That phase plan is then used to scope implementation and testing by phase, so later execution stays aligned with approved intent.

### 4. It is built for long-running real work

Superloop supports:

- resumable runs
- persistent Codex thread state
- git-backed checkpoints
- phase-by-phase progress tracking
- run event logs
- clarification injection back into the authoritative record

You can stop a run, resume it later, and still know exactly where you are.

### 5. Testing is a first-class loop

Testing is not an afterthought.

Superloop includes a dedicated test-author and test-auditor pair, so changed behavior gets an explicit coverage map and an independent audit for regression protection.

## Who Superloop is for

Superloop is for teams and solo engineers who:

- want the speed of coding agents without constant manual steering
- need something more reliable than one-shot prompting
- work in real repositories where interruption, drift, and partial progress matter
- want stronger delivery confidence without adding heavy process
- care more about shipped outcomes than workflow aesthetics

It is especially well suited to:

- medium to large existing codebases
- multi-file feature work
- risky changes that need explicit review gates
- tasks that benefit from phased execution
- teams adopting agentic development but unwilling to trust unchecked autonomy

## Mental model

Superloop runs three optional producer/verifier pairs:

1. **Plan** — Planner ↔ Plan Verifier
2. **Implement** — Implementer ↔ Code Reviewer
3. **Test** — Test Author ↔ Test Auditor

Each pair loops until one of three outcomes occurs:

- **COMPLETE**: the verifier accepts the current state
- **INCOMPLETE**: the producer must revise and try again
- **BLOCKED**: safe progress is not possible without intervention

This gives you a simple contract:

**plan → implement → test**  
with an audit gate between each stage and within each loop.

## Core workflow

### Plan

The planner turns the request into:

- `plan.md`
- `phase_plan.yaml`
- planning feedback

The verifier checks for:

- correctness
- completeness
- regression risk
- feasibility
- DRY/KISS quality

### Implement

The implementer executes the approved plan, updates implementation notes, and maps edits back to plan checklist items.

The reviewer checks for:

- correctness
- safety
- architecture conformance
- performance risk
- maintainability

### Test

The test author adds or refines tests and writes a behavior-to-coverage map.

The test auditor checks for:

- coverage quality
- edge cases
- flaky-risk control
- regression shielding
- assertion quality

## Why teams adopt it

### Higher trust without more meetings

Superloop reduces the need to watch every agent step because completion is verifier-gated and state is persisted.

### Better wall-clock outcomes

In real projects, elapsed time is often lost to rework, ambiguity, and restart friction.  
Superloop reduces those costs by keeping the loop structured and recoverable.

### Less silent drift

Clarifications are written into the authoritative run log and carried forward into future turns.  
Intent changes do not vanish into chat memory.

### Easier debugging of the workflow itself

When a run goes wrong, you can inspect:

- raw phase output
- event logs
- phase history
- criteria state
- verifier findings
- checkpointed artifacts

That makes the system much easier to improve than a black-box prompt flow.

## Positioning against common alternatives

Superloop is deliberately narrow.  
That is a strength.

It is **not** trying to be:

- a giant skills marketplace
- a simulated product org
- a heavyweight specification bureaucracy
- a single-shot “just let the model cook” harness

Instead, it sits in the most useful middle ground:

- more reliable than loose prompt workflows
- lighter than full process frameworks
- more operational than artifact-only methodologies
- more controllable than high-autonomy systems with weak review boundaries

In practical terms:

- if you want a workflow that can survive interruption, use Superloop
- if you want review to actually gate progress, use Superloop
- if you want planning to drive scoped implementation and test execution, use Superloop
- if you want less babysitting with higher confidence, use Superloop

## Inspired by Ralph-loops, evolved for production use

Ralph-loops proved the value of looping producer/reviewer agents.  
Superloop extends that idea into a more durable execution model.

Key evolutions include:

- canonical machine-readable loop control
- first-class phase planning and phase scoping
- persistent task and run workspaces
- resumable thread-aware execution
- explicit event recording and run summaries
- git-aware checkpoints and change detection
- dedicated test authoring and test auditing loops

In other words:

**Ralph-loops showed the pattern. Superloop operationalizes it.**

## Repository layout

```text
.superloop/
  tasks/
    <task-id>/
      task.json
      run_log.md
      raw_phase_log.md
      plan/
        prompt.md
        verifier_prompt.md
        plan.md
        phase_plan.yaml
        criteria.md
        feedback.md
      implement/
        prompt.md
        verifier_prompt.md
        phases/
          <phase-dir-key>/
            implementation_notes.md
            review_findings.md
            criteria.md
            feedback.md
      test/
        prompt.md
        verifier_prompt.md
        phases/
          <phase-dir-key>/
            test_strategy.md
            test_gaps.md
            criteria.md
            feedback.md
      runs/
        <run-id>/
          request.md
          run_log.md
          raw_phase_log.md
          events.jsonl
          summary.md
          sessions/
            plan.json
            phases/
              <phase-dir-key>.json

For phased `implement` and `test`, the pair root keeps only prompts plus `phases/`. Mutable artifacts are created lazily under the active phase directory, and Codex session state is scoped to `sessions/phases/<phase-dir-key>.json`. There is no legacy run-level `session.json` fallback: plan uses `sessions/plan.json`, and phased prompt construction must receive the scoped session path explicitly.

## Configuration

Superloop resolves provider settings from four layers, in this order:

1. built-in defaults
2. optional global config in the Superloop repo root
3. optional local config in the target `--workspace` repo root
4. explicit CLI flags

Precedence is deterministic:

`builtins < global config < local config < CLI`

Supported config filenames at each layer:

- `superloop.yaml`
- `superloop.config`

If both files exist in the same directory, Superloop fails fast instead of guessing which one to use.

Both filenames use the same YAML schema:

```yaml
provider:
  model: gpt-5.4
  model_effort: medium
runtime:
  pairs: plan,implement,test
  max_iterations: 15
  phase_mode: single
  intent_mode: preserve
  full_auto_answers: false
  no_git: false
```

Supported keys in this release:

- `provider.model`
- `provider.model_effort`
- `runtime.pairs`
- `runtime.max_iterations`
- `runtime.phase_mode` (`single` or `up-to`)
- `runtime.intent_mode` (`replace`, `append`, or `preserve`)
- `runtime.full_auto_answers`
- `runtime.no_git`

Example local override:

```yaml
provider:
  model: gpt-5.4-mini
runtime:
  max_iterations: 8
  no_git: true
```

Example CLI override:

```bash
python superloop.py --workspace /path/to/repo --model gpt-5.4 --model-effort high
```

PyYAML is only required when Superloop needs to parse a config file or an explicit `phase_plan.yaml`.
