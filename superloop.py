#!/usr/bin/env python3
"""Superloop: strategy-to-execution multi-pair Codex orchestration.

Implements optional producer/verifier loops using the shared Doc-Loop loop-control
contract, with canonical <loop-control> JSON output and legacy tag compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    import yaml
except ImportError:  # pragma: no cover - exercised in environments without optional deps installed
    yaml = None

from loop_control import (
    LoopControl,
    LoopControlParseError,
    PROMISE_BLOCKED,
    PROMISE_COMPLETE,
    PROMISE_INCOMPLETE,
    criteria_all_checked,
    parse_loop_control,
)

PAIR_ORDER = ["plan", "implement", "test"]

PAIR_LABELS = {
    "plan": "Plan ↔ Plan Verifier",
    "implement": "Implement ↔ Code Reviewer",
    "test": "Test Author ↔ Test Auditor",
}

PAIR_ARTIFACTS = {
    "plan": ["plan.md"],
    "implement": ["implementation_notes.md", "review_findings.md"],
    "test": ["test_strategy.md", "test_gaps.md"],
}

PHASED_PAIRS = frozenset({"implement", "test"})
PHASE_MODE_SINGLE = "single"
PHASE_MODE_UP_TO = "up-to"
PHASE_PLAN_VERSION = 1
PHASE_STATUS_PLANNED = "planned"
PHASE_STATUS_IN_PROGRESS = "in_progress"
PHASE_STATUS_COMPLETED = "completed"
PHASE_STATUS_BLOCKED = "blocked"
PHASE_STATUS_DEFERRED = "deferred"
RUNTIME_PHASE_STATUSES = {
    PHASE_STATUS_PLANNED,
    PHASE_STATUS_IN_PROGRESS,
    PHASE_STATUS_COMPLETED,
    PHASE_STATUS_BLOCKED,
    PHASE_STATUS_DEFERRED,
}
IMPLICIT_PHASE_ID = "implicit-phase"

PAIR_CRITERIA_TEMPLATES = {
    "plan": """# Plan Verification Criteria
Check these boxes (`- [x]`) only when true.

- [ ] **Correctness**: The plan does not contradict repository constraints, known requirements, or prior clarifications.
- [ ] **Completeness**: Scope, milestones, interfaces, dependencies, rollout, and operational constraints are concrete and implementation-ready.
- [ ] **Regression Risk**: Risks, blast radius, and rollback/mitigation strategy are explicit and actionable.
- [ ] **DRY / KISS**: The plan avoids redundant sections and unnecessary complexity.
- [ ] **Feasibility**: Timeline and sequencing are realistic and blockers are surfaced.
""",
    "implement": """# Code Review Criteria
Check these boxes (`- [x]`) only when true.

- [ ] **Correctness**: Changes satisfy the accepted plan/requirements and preserve expected behavior.
- [ ] **Safety**: No obvious security or data-integrity regressions were introduced.
- [ ] **Architecture Conformance**: Changes match repo conventions and avoid needless complexity.
- [ ] **Performance**: No avoidable major regressions or pathological hot paths were introduced.
- [ ] **Maintainability**: Diffs are understandable, cohesive, and adequately documented where needed.
""",
    "test": """# Test Audit Criteria
Check these boxes (`- [x]`) only when true.

- [ ] **Coverage Quality**: New/changed behavior is covered at appropriate levels (unit/integration/e2e as applicable).
- [ ] **Edge Cases**: Failure and boundary cases for changed behavior are covered.
- [ ] **Flaky Risk Control**: Tests avoid nondeterministic timing/network assumptions without stabilization.
- [ ] **Regression Shield**: Critical regressions from changed modules/contracts are guarded.
- [ ] **Signal Quality**: Assertions validate outcomes, not only execution paths.
""",
}

PAIR_PRODUCER_PROMPT = {
    "plan": """# Superloop Planner Instructions
You are the planning agent for this repository.

## Goal
Turn the user intent into an implementation-ready plan with milestones, interfaces, and risk controls.

## Authoritative context
- The run preamble identifies the immutable request snapshot and the authoritative chronological raw log for this run.
- Use the original request plus any later clarification entries as the source of truth for intent.
- Explore the repository as needed for dependency and regression analysis, but do not expand task scope unless explicitly justified.

## Required outputs
Update `.superloop/plan/plan.md` as the single source of truth for the plan, including milestones, interface definitions, and risk register details in that one file.

Create or update `.superloop/plan/phase_plan.yaml` as the canonical machine-readable ordered phase decomposition. If the task is genuinely small and coherently shippable as one slice, produce exactly one explicit phase rather than inventing artificial decomposition.

Also append a concise entry to `.superloop/plan/feedback.md` with what changed and why.

## Rules
1. Analyze codebase areas and behaviors relevant to the current user request first. Broaden analysis scope when justified: cross-cutting patterns must be checked, dependencies are unclear, behavior may be reused elsewhere, or the repository/files are small enough that full analysis is cheaper and safer.
2. Check and verify your own plan for consistency, feasibility, DRY/KISS quality, and regression risk before writing files.
3. Keep the plan concrete and implementation-ready.
4. Apply KISS and DRY; avoid speculative complexity.
5. Do not edit `.superloop/plan/criteria.md` (verifier-owned).
6. `phase_plan.yaml` must define coherent ordered phases with explicit dependency ordering, in-scope/out-of-scope boundaries, acceptance criteria, and future-phase deferments. Do not use heuristics or scoring rules for granularity.
7. Accept a single explicit phase when scope is small and coherent; do not force multi-phase decomposition for its own sake.
8. If the user request is ambiguous, logically flawed, introduces breaking changes, may cause regressions, or may create hidden unintended behavior, warn the user via a clarifying question.
9. Every clarifying question must include your best suggestion/supposition so the user can confirm or correct quickly.
10. When asking a clarifying question, do not edit files and output exactly one canonical loop-control block as the last non-empty logical block:
<loop-control>
{"schema":"docloop.loop_control/v1","kind":"question","question":"Question text.","best_supposition":"..."}
</loop-control>
Legacy `<question>...</question>` remains supported for compatibility, but the canonical loop-control block is the default contract.
11. Before the final loop-control block, print a concise plain-text summary with these exact headings: `Scope considered`, `What I analyzed`, `What I changed`, `Key findings / decisions`, `Open issues / next step`.
12. Do not output any `<promise>...</promise>` tag.
""",
    "implement": """# Superloop Implementer Instructions
You are the implementation agent for this repository.

## Goal
Implement the approved plan and reviewer feedback with high-quality multi-file code changes.

## Working set
- Request snapshot and run raw log identified in the run preamble
- The active phase execution contract injected in the run preamble for implement/test phase-scoped runs
- Repository areas required by the current task and justified blast radius
- `.superloop/implement/feedback.md`
- `.superloop/plan/plan.md`
- `.superloop/implement/implementation_notes.md`

## Rules
1. Treat the original request plus later clarification entries as authoritative for intent. Pair artifacts may refine execution details, but they may not override explicit user intent.
2. Analyze request-relevant code paths and behavior before editing. Broaden analysis scope when justified: shared patterns may exist, dependencies are unclear, regressions could propagate across modules, or the repository/files are small enough that full analysis is simpler and safer.
3. Repo-wide exploration is allowed for dependency and regression analysis, but unrelated dirty files are not part of this task unless explicitly justified.
4. Apply minimal, high-signal changes; keep KISS/DRY.
5. Resolve reviewer findings explicitly and avoid introducing unrelated refactors.
6. When you see duplicated logic that clearly adds technical debt, centralize it into a shared abstraction/module unless that would introduce unjustified complexity.
7. Before finalizing edits, check likely regression surfaces for touched behavior (interfaces, persisted data, compatibility, tests).
8. Treat the active phase contract as authoritative scoped work for implement/test runs. Any intentional out-of-phase change must be explicitly justified in `.superloop/implement/implementation_notes.md`.
9. Map your edits to the implementation checklist in `.superloop/plan/plan.md` when present, and note any checklist item you intentionally defer.
10. Update `.superloop/implement/implementation_notes.md` with: files changed, checklist mapping, assumptions, expected side effects, and any deduplication/centralization decisions.
11. Before the final loop-control block, print a concise plain-text summary with these exact headings: `Scope considered`, `What I analyzed`, `What I changed`, `Key findings / decisions`, `Open issues / next step`.
12. Do not edit `.superloop/implement/criteria.md` (reviewer-owned).
13. If ambiguity or intent gaps remain, or if a required change may introduce breaking behavior/regressions, ask a clarifying question with your best suggestion/supposition and do not edit files:
<loop-control>
{"schema":"docloop.loop_control/v1","kind":"question","question":"Question text.","best_supposition":"..."}
</loop-control>
Legacy `<question>...</question>` remains supported for compatibility, but the canonical loop-control block is the default contract.
14. Do not output any `<promise>...</promise>` tag.
""",
    "test": """# Superloop Test Author Instructions
You are the test authoring agent for this repository.

## Goal
Create or refine tests and fixtures to validate changed behavior and prevent regressions.

## Required outputs
- Update relevant test files in the repository.
- Respect the active phase execution contract injected in the run preamble for test-phase runs.
- Update `.superloop/test/test_strategy.md` with an explicit behavior-to-test coverage map.
- Append a concise entry to `.superloop/test/feedback.md` summarizing test additions.

## Rules
1. Treat the original request plus later clarification entries as authoritative for intent. Pair artifacts may refine execution details, but they may not override explicit user intent.
2. Focus on changed/request-relevant behavior first; avoid unrelated test churn. Broaden analysis when justified to find shared test patterns, dependency impacts, or when repository/files are small enough that full inspection is more reliable.
3. Repo-wide exploration is allowed for dependency and regression analysis, but unrelated dirty files are not part of this task unless explicitly justified.
4. Favor deterministic tests with stable setup/teardown.
5. For each changed behavior, include happy path, edge case, and failure-path coverage where relevant.
6. Call out flake risks (timing, network, nondeterministic ordering) and stabilization approach.
7. Before the final loop-control block, print a concise plain-text summary with these exact headings: `Scope considered`, `What I analyzed`, `What I changed`, `Key findings / decisions`, `Open issues / next step`.
8. Do not edit `.superloop/test/criteria.md` (auditor-owned).
9. If blocked by missing intent, ask a clarifying question with your best suggestion/supposition and do not edit files:
<loop-control>
{"schema":"docloop.loop_control/v1","kind":"question","question":"Question text.","best_supposition":"..."}
</loop-control>
Legacy `<question>...</question>` remains supported for compatibility, but the canonical loop-control block is the default contract.
10. Do not output any `<promise>...</promise>` tag.
""",
}

PAIR_VERIFIER_PROMPT = {
    "plan": """# Superloop Plan Verifier Instructions
You are the plan verifier.

## Goal
Audit planning artifacts for correctness, completeness, regression risk, and KISS/DRY quality.

## Required actions
1. Update `.superloop/plan/criteria.md` checkboxes accurately.
2. Append prioritized findings to `.superloop/plan/feedback.md` with stable IDs (for example `PLAN-001`).
3. Label each finding as `blocking` or `non-blocking`.
4. End stdout with exactly one canonical loop-control block as the last non-empty logical block:
<loop-control>
{"schema":"docloop.loop_control/v1","kind":"promise","promise":"COMPLETE"}
</loop-control>
or the same shape with `INCOMPLETE` / `BLOCKED`.

## Rules
- You may not edit repository source code.
- Treat the run raw log as the authoritative chronological ledger for clarifications and scope decisions. Later clarification entries override earlier assumptions for execution details.
- Focus on request-relevant and changed-scope plan sections first; justify any out-of-scope finding. Broaden analysis when cross-cutting patterns/dependencies or small-repo economics make wider review safer.
- A finding may be `blocking` only if it materially risks correctness, compatibility, hidden behavior changes, or implementation failure.
- For each `blocking` finding include evidence: affected section(s), concrete failure/conflict scenario, and minimal correction direction.
- Validate `phase_plan.yaml` quality by review judgment: coherent boundaries, dependency ordering, acceptance criteria, and future-phase deferments.
- Accept a single explicit phase when the task is genuinely small and coherent; do not require multiple phases for their own sake.
- Do not require or invent runtime heuristics for phase granularity.
- Do not return `INCOMPLETE` if you have no blocking findings.
- Ask a canonical `<loop-control>` question block only when missing product intent makes safe verification impossible, and include best suggestion/supposition.
- If COMPLETE, every checkbox in criteria must be checked.
- Before the final loop-control block, print a concise plain-text summary with these exact headings: `Scope considered`, `What I analyzed`, `What I reviewed`, `Key findings / decisions`, `Open issues / next step`.
Legacy `<question>...</question>` and final-line `<promise>...</promise>` remain supported for compatibility, but canonical loop-control output is the default contract.
""",
    "implement": """# Superloop Code Reviewer Instructions
You are the code reviewer.

## Goal
Audit implementation diffs for correctness, architecture conformance, security, performance, and maintainability.

## Required actions
1. Update `.superloop/implement/criteria.md` checkboxes accurately.
2. Append prioritized review findings to `.superloop/implement/feedback.md` with stable IDs (for example `IMP-001`).
3. Label each finding as `blocking` or `non-blocking`.
4. End stdout with exactly one canonical loop-control block as the last non-empty logical block:
<loop-control>
{"schema":"docloop.loop_control/v1","kind":"promise","promise":"COMPLETE"}
</loop-control>
or the same shape with `INCOMPLETE` / `BLOCKED`.

## Rules
- Do not modify non-`.superloop/` code files.
- Treat the original request plus later clarification entries as authoritative for intent.
- Treat the run raw log as the authoritative chronological ledger for clarifications and scope decisions. Later clarification entries override earlier assumptions for execution details.
- Review changed/request-relevant scope first; justify any out-of-scope finding. Broaden analysis when shared patterns, uncertain dependencies, or small-repo economics justify wider inspection.
- Repo-wide exploration is allowed for dependency and regression analysis, but unrelated dirty files are not part of this task unless explicitly justified.
- A finding may be `blocking` only if it materially risks correctness, security, reliability, compatibility, required behavior coverage, or introduces avoidable duplicated logic that increases technical debt.
- Flag duplicated logic that should be centralized for DRY/KISS as a finding; treat it as `blocking` when duplication is substantial and likely to increase maintenance or inconsistency risk.
- Each `blocking` finding must include: file/symbol reference, concrete failure or regression (or maintainability debt) scenario, and minimal fix direction including centralization target when applicable.
- Do not return `INCOMPLETE` if you have no blocking findings.
- Ask a canonical `<loop-control>` question block only for missing product intent, and include best suggestion/supposition.
- If COMPLETE, criteria must have no unchecked boxes.
- Before the final loop-control block, print a concise plain-text summary with these exact headings: `Scope considered`, `What I analyzed`, `What I reviewed`, `Key findings / decisions`, `Open issues / next step`.
Legacy `<question>...</question>` and final-line `<promise>...</promise>` remain supported for compatibility, but canonical loop-control output is the default contract.
""",
    "test": """# Superloop Test Auditor Instructions
You are the test auditor.

## Goal
Audit tests for coverage quality, edge-case depth, and flaky-risk control.

## Required actions
1. Update `.superloop/test/criteria.md` checkboxes accurately.
2. Append prioritized audit findings to `.superloop/test/feedback.md` with stable IDs (for example `TST-001`).
3. Label each finding as `blocking` or `non-blocking`.
4. End stdout with exactly one canonical loop-control block as the last non-empty logical block:
<loop-control>
{"schema":"docloop.loop_control/v1","kind":"promise","promise":"COMPLETE"}
</loop-control>
or the same shape with `INCOMPLETE` / `BLOCKED`.

## Rules
- Do not edit repository code except `.superloop/test/*` audit artifacts.
- Treat the original request plus later clarification entries as authoritative for intent.
- Treat the run raw log as the authoritative chronological ledger for clarifications and scope decisions. Later clarification entries override earlier assumptions for execution details.
- Focus on changed/request-relevant behavior first; justify any out-of-scope finding. Broaden analysis when shared patterns, uncertain dependencies, or small-repo economics justify wider inspection.
- Repo-wide exploration is allowed for dependency and regression analysis, but unrelated dirty files are not part of this task unless explicitly justified.
- A finding may be `blocking` only if it materially risks regression detection, correctness coverage, or test reliability.
- Each `blocking` finding must include evidence: affected behavior/tests, concrete missed-regression scenario, and minimal correction direction.
- Low-confidence concerns should be non-blocking suggestions.
- Do not return `INCOMPLETE` if you have no blocking findings.
- Ask a canonical `<loop-control>` question block only for missing product intent, and include best suggestion/supposition.
- If COMPLETE, criteria must have no unchecked boxes.
- Before the final loop-control block, print a concise plain-text summary with these exact headings: `Scope considered`, `What I analyzed`, `What I reviewed`, `Key findings / decisions`, `Open issues / next step`.
Legacy `<question>...</question>` and final-line `<promise>...</promise>` remain supported for compatibility, but canonical loop-control output is the default contract.
""",
}


@dataclass(frozen=True)
class PairConfig:
    name: str
    enabled: bool
    max_iterations: int


@dataclass(frozen=True)
class CodexCommandConfig:
    start_command: List[str]
    resume_command: List[str]


@dataclass
class SessionState:
    mode: str
    thread_id: Optional[str]
    pending_clarification_note: Optional[str]
    created_at: str
    last_used_at: Optional[str] = None


@dataclass
class EventRecorder:
    run_id: str
    events_file: Path
    sequence: int = 0

    def emit(self, event_type: str, **fields):
        self.sequence += 1
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "seq": self.sequence,
            "event_type": event_type,
            **fields,
        }
        with self.events_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class ResumeCheckpoint:
    pair_start_index: int
    cycle_by_pair: Dict[str, int]
    attempts_by_pair_cycle: Dict[Tuple[str, int], int]
    cycle_by_phase_pair: Dict[Tuple[str, str], int]
    attempts_by_phase_pair_cycle: Dict[Tuple[str, str, int], int]
    completed_pairs_by_phase: Dict[str, Tuple[str, ...]]
    emitted_phase_started_ids: Tuple[str, ...]
    emitted_phase_completed_ids: Tuple[str, ...]
    emitted_phase_deferred_keys: Tuple[Tuple[str, str], ...]
    scope_event_seen: bool
    last_sequence: int
    phase_mode: Optional[str] = None
    phase_ids: Tuple[str, ...] = ()
    current_phase_index: int = 0


@dataclass(frozen=True)
class PhaseSnapshot:
    """Git reference and untracked-file baseline for one phase."""

    ref: str
    untracked_paths: frozenset[str]


@dataclass(frozen=True)
class PhasePlanCriterion:
    id: str
    text: str


@dataclass(frozen=True)
class PhasePlanPhase:
    phase_id: str
    title: str
    objective: str
    in_scope: Tuple[str, ...]
    out_of_scope: Tuple[str, ...]
    dependencies: Tuple[str, ...]
    acceptance_criteria: Tuple[PhasePlanCriterion, ...]
    deliverables: Tuple[str, ...]
    risks: Tuple[str, ...]
    rollback: Tuple[str, ...]
    status: str


@dataclass(frozen=True)
class PhasePlan:
    version: int
    task_id: str
    request_snapshot_ref: str
    phases: Tuple[PhasePlanPhase, ...]
    explicit: bool = True

    def phase_by_id(self, phase_id: str) -> Optional[PhasePlanPhase]:
        for phase in self.phases:
            if phase.phase_id == phase_id:
                return phase
        return None


@dataclass(frozen=True)
class ResolvedPhaseSelection:
    phase_mode: str
    phase_ids: Tuple[str, ...]
    phases: Tuple[PhasePlanPhase, ...]
    explicit: bool

    @property
    def is_implicit(self) -> bool:
        return not self.explicit


class PhasePlanError(ValueError):
    """Raised when phase-plan state is invalid or ambiguous."""


def fatal(message: str, exit_code: int = 1):
    print(message, file=sys.stderr)
    sys.exit(exit_code)


def warn(message: str):
    print(f"[!] WARNING: {message}", file=sys.stderr)


def run_git(args: List[str], cwd: Path, allow_fail: bool = False) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if res.returncode != 0 and not allow_fail:
        fatal(f"[!] FATAL GIT ERROR: {' '.join(args)}\n{res.stderr.strip()}")
    return res


def normalize_repo_path(path_text: str) -> str:
    """Normalizes a repo-relative path from git porcelain output."""
    cleaned = path_text.strip()
    if " -> " in cleaned:
        cleaned = cleaned.split(" -> ", 1)[1]
    return cleaned


def phase_plan_file(task_dir: Path) -> Path:
    return task_dir / "plan" / "phase_plan.yaml"


def parse_status_paths(status_text: str) -> Set[str]:
    """Parses git porcelain status into a set of changed repo-relative paths."""
    changed: Set[str] = set()
    for line in status_text.splitlines():
        if len(line) < 4:
            continue
        changed.add(normalize_repo_path(line[3:]))
    return changed



def list_untracked_paths(cwd: Path, tracked_paths: Optional[Sequence[str]] = None) -> Set[str]:
    """Returns untracked files in the working tree."""
    args = ["ls-files", "--others", "--exclude-standard"]
    if tracked_paths:
        args.extend(["--", *tracked_paths])
    out = run_git(args, cwd=cwd).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def phase_snapshot_ref(cwd: Path, tracked_paths: Optional[Sequence[str]] = None) -> PhaseSnapshot:
    """Returns a git snapshot reference plus untracked-file baseline."""
    untracked = frozenset(list_untracked_paths(cwd, tracked_paths=tracked_paths))

    snap = run_git(["stash", "create", "superloop-phase-snapshot"], cwd=cwd, allow_fail=True).stdout.strip()
    if snap:
        return PhaseSnapshot(ref=snap, untracked_paths=untracked)

    head = run_git(["rev-parse", "HEAD"], cwd=cwd, allow_fail=True).stdout.strip()
    if head:
        return PhaseSnapshot(ref=head, untracked_paths=untracked)

    fatal("[!] FATAL GIT ERROR: Unable to create a phase snapshot reference.")


def changed_paths_from_snapshot(cwd: Path, snapshot: PhaseSnapshot, tracked_paths: Optional[Sequence[str]] = None) -> Set[str]:
    """Returns files changed since a snapshot, including newly-created untracked files."""
    args = ["diff", "--name-only", snapshot.ref, "--"]
    if tracked_paths:
        args.extend(tracked_paths)
    tracked_delta = {line.strip() for line in run_git(args, cwd=cwd).stdout.splitlines() if line.strip()}

    current_untracked = list_untracked_paths(cwd, tracked_paths=tracked_paths)
    new_untracked = current_untracked - set(snapshot.untracked_paths)
    return tracked_delta | new_untracked
def changed_paths(cwd: Path, tracked_paths: Optional[Sequence[str]] = None) -> Set[str]:
    """Returns changed paths from git porcelain status, optionally restricted to tracked paths."""
    args = ["status", "--porcelain"]
    if tracked_paths:
        args.extend(["--", *tracked_paths])
    return parse_status_paths(run_git(args, cwd=cwd).stdout)


def allowed_verifier_paths(pair: str, task_root: str) -> List[str]:
    """Returns repo-relative paths a verifier is allowed to edit for a pair."""
    return [f"{task_root}/{pair}/"]


def verifier_scope_violations(pair: str, verifier_delta: Set[str], task_root: str) -> List[str]:
    """Returns verifier writes that are outside its allowed scope."""
    allowed = tuple(allowed_verifier_paths(pair, task_root))
    return sorted(path for path in verifier_delta if not path.startswith(allowed))


def tracked_superloop_paths(task_root: str, pair: Optional[str] = None) -> List[str]:
    """Returns paths that Superloop may stage/commit."""
    shared_paths = [
        f"{task_root}/task.json",
        f"{task_root}/run_log.md",
        f"{task_root}/raw_phase_log.md",
        f"{task_root}/runs/",
    ]
    if pair is None:
        pair_paths = [f"{task_root}/{name}/" for name in PAIR_ORDER]
    else:
        pair_paths = [f"{task_root}/{pair}/"]
    return [*shared_paths, *pair_paths]


def _phase_criteria_payload(raw_value: object, label: str) -> Tuple[PhasePlanCriterion, ...]:
    if not isinstance(raw_value, list) or not raw_value:
        raise PhasePlanError(f"{label} must be a non-empty list.")
    items: List[PhasePlanCriterion] = []
    for idx, raw_item in enumerate(raw_value, start=1):
        if not isinstance(raw_item, dict):
            raise PhasePlanError(f"{label}[{idx}] must be a mapping.")
        criterion_id = raw_item.get("id")
        text = raw_item.get("text")
        if not isinstance(criterion_id, str) or not criterion_id.strip():
            raise PhasePlanError(f"{label}[{idx}].id must be a non-empty string.")
        if not isinstance(text, str) or not text.strip():
            raise PhasePlanError(f"{label}[{idx}].text must be a non-empty string.")
        items.append(PhasePlanCriterion(id=criterion_id.strip(), text=text.strip()))
    return tuple(items)


def _phase_string_list(raw_value: object, label: str, *, allow_empty: bool = True) -> Tuple[str, ...]:
    if not isinstance(raw_value, list):
        raise PhasePlanError(f"{label} must be a list.")
    items: List[str] = []
    for idx, raw_item in enumerate(raw_value, start=1):
        if not isinstance(raw_item, str) or not raw_item.strip():
            raise PhasePlanError(f"{label}[{idx}] must be a non-empty string.")
        items.append(raw_item.strip())
    if not allow_empty and not items:
        raise PhasePlanError(f"{label} must be a non-empty list.")
    return tuple(items)


def validate_phase_plan(payload: object, task_id: str) -> PhasePlan:
    if not isinstance(payload, dict):
        raise PhasePlanError("phase_plan.yaml must contain a YAML mapping.")

    version = payload.get("version")
    if version != PHASE_PLAN_VERSION:
        raise PhasePlanError(f"phase_plan.yaml version must be {PHASE_PLAN_VERSION}.")

    payload_task_id = payload.get("task_id")
    if payload_task_id != task_id:
        raise PhasePlanError(f"phase_plan.yaml task_id must match task id {task_id!r}.")

    request_snapshot_ref = payload.get("request_snapshot_ref")
    if not isinstance(request_snapshot_ref, str) or not request_snapshot_ref.strip():
        raise PhasePlanError("phase_plan.yaml request_snapshot_ref must be a non-empty string.")

    raw_phases = payload.get("phases")
    if not isinstance(raw_phases, list) or not raw_phases:
        raise PhasePlanError("phase_plan.yaml phases must be a non-empty list.")

    phase_ids: List[str] = []
    built_phases: List[PhasePlanPhase] = []
    for idx, raw_phase in enumerate(raw_phases, start=1):
        if not isinstance(raw_phase, dict):
            raise PhasePlanError(f"phases[{idx}] must be a mapping.")
        label = f"phases[{idx}]"
        phase_id = raw_phase.get("phase_id")
        title = raw_phase.get("title")
        objective = raw_phase.get("objective")
        status = raw_phase.get("status")
        if not isinstance(phase_id, str) or not phase_id.strip():
            raise PhasePlanError(f"{label}.phase_id must be a non-empty string.")
        normalized_phase_id = phase_id.strip()
        if normalized_phase_id in phase_ids:
            raise PhasePlanError(f"phase_plan.yaml contains duplicate phase_id {normalized_phase_id!r}.")
        if not isinstance(title, str) or not title.strip():
            raise PhasePlanError(f"{label}.title must be a non-empty string.")
        if not isinstance(objective, str) or not objective.strip():
            raise PhasePlanError(f"{label}.objective must be a non-empty string.")
        if not isinstance(status, str) or status not in RUNTIME_PHASE_STATUSES:
            raise PhasePlanError(
                f"{label}.status must be one of: {', '.join(sorted(RUNTIME_PHASE_STATUSES))}."
            )
        phase_ids.append(normalized_phase_id)
        built_phases.append(
            PhasePlanPhase(
                phase_id=normalized_phase_id,
                title=title.strip(),
                objective=objective.strip(),
                in_scope=_phase_string_list(raw_phase.get("in_scope"), f"{label}.in_scope", allow_empty=False),
                out_of_scope=_phase_string_list(raw_phase.get("out_of_scope"), f"{label}.out_of_scope"),
                dependencies=_phase_string_list(raw_phase.get("dependencies"), f"{label}.dependencies"),
                acceptance_criteria=_phase_criteria_payload(
                    raw_phase.get("acceptance_criteria"),
                    f"{label}.acceptance_criteria",
                ),
                deliverables=_phase_string_list(raw_phase.get("deliverables"), f"{label}.deliverables", allow_empty=False),
                risks=_phase_string_list(raw_phase.get("risks"), f"{label}.risks"),
                rollback=_phase_string_list(raw_phase.get("rollback"), f"{label}.rollback"),
                status=status,
            )
        )

    all_phase_ids = set(phase_ids)
    seen_phase_ids: Set[str] = set()
    for phase in built_phases:
        for dependency in phase.dependencies:
            if dependency in all_phase_ids and dependency not in seen_phase_ids:
                raise PhasePlanError(
                    f"phase {phase.phase_id!r} depends on phase {dependency!r}, "
                    "which is not earlier in phase order."
                )
        seen_phase_ids.add(phase.phase_id)

    return PhasePlan(
        version=PHASE_PLAN_VERSION,
        task_id=task_id,
        request_snapshot_ref=request_snapshot_ref.strip(),
        phases=tuple(built_phases),
        explicit=True,
    )


def load_phase_plan(path: Path, task_id: str) -> Optional[PhasePlan]:
    if not path.exists():
        return None
    if yaml is None:
        raise PhasePlanError(
            "phase_plan.yaml cannot be loaded without PyYAML installed. Install dependencies from requirements.txt."
        )
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PhasePlanError(f"{path} could not be parsed as YAML: {exc}") from exc
    except OSError as exc:
        raise PhasePlanError(f"{path} could not be read: {exc}") from exc
    return validate_phase_plan(payload, task_id)


def build_implicit_phase_plan(task_id: str, request_file: Path) -> PhasePlan:
    request_text = request_file.read_text(encoding="utf-8").strip() if request_file.exists() else ""
    summary = request_text if request_text else DEFAULT_REQUEST_TEXT
    phase = PhasePlanPhase(
        phase_id=IMPLICIT_PHASE_ID,
        title="Implicit single phase",
        objective="Complete the requested work described in the immutable request snapshot.",
        in_scope=(summary,),
        out_of_scope=(),
        dependencies=(),
        acceptance_criteria=(PhasePlanCriterion(id="AC-1", text="Implement the requested work coherently."),),
        deliverables=("code", "tests", "docs"),
        risks=(),
        rollback=(),
        status=PHASE_STATUS_PLANNED,
    )
    return PhasePlan(
        version=PHASE_PLAN_VERSION,
        task_id=task_id,
        request_snapshot_ref=str(request_file),
        phases=(phase,),
        explicit=False,
    )


def restore_phase_selection(plan: PhasePlan, phase_ids: Sequence[str], phase_mode: Optional[str]) -> ResolvedPhaseSelection:
    if not phase_ids:
        raise PhasePlanError("Stored phase selection is empty.")
    restored_phases: List[PhasePlanPhase] = []
    expected_order = [phase.phase_id for phase in plan.phases if phase.phase_id in set(phase_ids)]
    if expected_order != list(phase_ids):
        raise PhasePlanError("Stored phase selection no longer matches phase plan order.")
    for phase_id in phase_ids:
        phase = plan.phase_by_id(phase_id)
        if phase is None:
            raise PhasePlanError(
                f"Stored phase selection references unknown phase_id {phase_id!r}. "
                "Regenerate or reconcile phase_plan.yaml."
            )
        restored_phases.append(phase)
    return ResolvedPhaseSelection(
        phase_mode=phase_mode or (PHASE_MODE_SINGLE if len(restored_phases) == 1 else PHASE_MODE_UP_TO),
        phase_ids=tuple(phase_ids),
        phases=tuple(restored_phases),
        explicit=plan.explicit,
    )


def resolve_phase_selection(
    plan: PhasePlan,
    phase_id: Optional[str],
    phase_mode: str,
    enabled_pairs: Sequence[str],
) -> ResolvedPhaseSelection:
    if not any(pair in PHASED_PAIRS for pair in enabled_pairs):
        raise PhasePlanError("Phase selection is only valid when implement or test is enabled.")
    normalized_phase_id = phase_id.strip() if isinstance(phase_id, str) and phase_id.strip() else None
    if normalized_phase_id is None and phase_mode == PHASE_MODE_UP_TO:
        raise PhasePlanError("--phase-mode up-to requires --phase-id.")

    if not plan.explicit:
        if normalized_phase_id is not None:
            raise PhasePlanError("--phase-id requires an explicit phase_plan.yaml.")
        return ResolvedPhaseSelection(
            phase_mode=PHASE_MODE_SINGLE,
            phase_ids=(IMPLICIT_PHASE_ID,),
            phases=plan.phases,
            explicit=False,
        )

    if normalized_phase_id is None:
        return ResolvedPhaseSelection(
            phase_mode=phase_mode,
            phase_ids=tuple(phase.phase_id for phase in plan.phases),
            phases=plan.phases,
            explicit=True,
        )

    selected_phase = plan.phase_by_id(normalized_phase_id)
    if selected_phase is None:
        raise PhasePlanError(f"Unknown --phase-id {normalized_phase_id!r} for current phase_plan.yaml.")

    ordered_phases = list(plan.phases)
    phase_index = ordered_phases.index(selected_phase)
    selected_phases = ordered_phases[: phase_index + 1] if phase_mode == PHASE_MODE_UP_TO else [selected_phase]
    return ResolvedPhaseSelection(
        phase_mode=phase_mode,
        phase_ids=tuple(phase.phase_id for phase in selected_phases),
        phases=tuple(selected_phases),
        explicit=True,
    )


def phase_prompt_context(selection: ResolvedPhaseSelection) -> str:
    lines = [
        "ACTIVE PHASE EXECUTION CONTRACT:",
        f"- phase_mode: {selection.phase_mode}",
        f"- phase_ids: {', '.join(selection.phase_ids)}",
        f"- phase_plan_source: {'explicit phase_plan.yaml' if selection.explicit else 'implicit legacy fallback (no phase_plan.yaml)'}",
    ]
    for phase in selection.phases:
        lines.extend(
            [
                "",
                f"Phase {phase.phase_id}: {phase.title}",
                f"Objective: {phase.objective}",
                "In scope:",
                *[f"- {item}" for item in phase.in_scope],
            ]
        )
        if phase.out_of_scope:
            lines.extend(["Out of scope:", *[f"- {item}" for item in phase.out_of_scope]])
        if phase.acceptance_criteria:
            lines.extend(
                [
                    "Acceptance criteria:",
                    *[f"- {criterion.id}: {criterion.text}" for criterion in phase.acceptance_criteria],
                ]
            )
        if phase.dependencies:
            lines.extend(["Dependencies / deferments:", *[f"- {item}" for item in phase.dependencies]])
        if phase.deliverables:
            lines.extend(["Deliverables:", *[f"- {item}" for item in phase.deliverables]])
    return "\n".join(lines)


def active_phase_selection_from_meta(task_meta_file: Path) -> Tuple[Optional[str], Tuple[str, ...], int]:
    payload = _load_task_meta(task_meta_file, task_meta_file.parent.name)
    raw_selection = payload.get("active_phase_selection")
    if not isinstance(raw_selection, dict):
        return None, (), 0
    phase_mode = raw_selection.get("mode")
    phase_ids = raw_selection.get("phase_ids")
    current_phase_index = raw_selection.get("current_phase_index")
    if not isinstance(phase_mode, str):
        phase_mode = None
    if not isinstance(phase_ids, list):
        return phase_mode, (), 0
    if not isinstance(current_phase_index, int) or current_phase_index < 0:
        current_phase_index = 0
    return phase_mode, tuple(item for item in phase_ids if isinstance(item, str) and item.strip()), current_phase_index


def persist_phase_selection(
    task_meta_file: Path,
    selection: ResolvedPhaseSelection,
    run_id: str,
    plan_path: Path,
    *,
    current_phase_index: int = 0,
):
    payload = _load_task_meta(task_meta_file, task_meta_file.parent.name)
    payload["phase_plan_path"] = str(plan_path)
    payload["phase_plan_version"] = PHASE_PLAN_VERSION
    payload["active_phase_selection"] = {
        "run_id": run_id,
        "mode": selection.phase_mode,
        "phase_ids": list(selection.phase_ids),
        "explicit": selection.explicit,
        "current_phase_index": current_phase_index,
    }
    raw_phase_status = payload.get("phase_status")
    phase_status = raw_phase_status if isinstance(raw_phase_status, dict) else {}
    for phase_id in selection.phase_ids:
        current = phase_status.get(phase_id)
        if current not in RUNTIME_PHASE_STATUSES:
            phase_status[phase_id] = PHASE_STATUS_PLANNED
    payload["phase_status"] = phase_status
    _write_task_meta(task_meta_file, payload)


def active_phase_index_from_meta(task_meta_file: Path) -> int:
    payload = _load_task_meta(task_meta_file, task_meta_file.parent.name)
    raw_selection = payload.get("active_phase_selection")
    if not isinstance(raw_selection, dict):
        return 0
    current_phase_index = raw_selection.get("current_phase_index")
    if not isinstance(current_phase_index, int) or current_phase_index < 0:
        return 0
    return current_phase_index


def resolve_resume_start_phase_index(
    selection: ResolvedPhaseSelection,
    phased_enabled: Sequence[str],
    completed_pairs_by_phase: Dict[str, Tuple[str, ...]],
) -> int:
    if not selection.phase_ids:
        return 0
    for idx, phase_id in enumerate(selection.phase_ids):
        completed_for_phase = set(completed_pairs_by_phase.get(phase_id, ()))
        if any(pair not in completed_for_phase for pair in phased_enabled):
            return idx
    return len(selection.phase_ids)


def resume_scope_matches(checkpoint: ResumeCheckpoint, selection: ResolvedPhaseSelection) -> bool:
    if not checkpoint.scope_event_seen:
        return False
    if checkpoint.phase_ids != selection.phase_ids:
        return False
    if checkpoint.phase_mode is None:
        return selection.phase_mode == PHASE_MODE_SINGLE
    return checkpoint.phase_mode == selection.phase_mode


def update_active_phase_index(task_meta_file: Path, phase_index: int, current_phase_id: Optional[str]):
    payload = _load_task_meta(task_meta_file, task_meta_file.parent.name)
    raw_selection = payload.get("active_phase_selection")
    selection = raw_selection if isinstance(raw_selection, dict) else {}
    selection["current_phase_index"] = max(0, phase_index)
    selection["current_phase_id"] = current_phase_id
    payload["active_phase_selection"] = selection
    _write_task_meta(task_meta_file, payload)


def phase_pair_completed(completed_phase_pairs: Dict[str, Set[str]], phase_id: str, pair: str) -> bool:
    return pair in completed_phase_pairs.get(phase_id, set())


def mark_phase_pair_completed(completed_phase_pairs: Dict[str, Set[str]], phase_id: str, pair: str):
    completed_phase_pairs.setdefault(phase_id, set()).add(pair)


def mark_phase_status(
    task_meta_file: Path,
    phase_ids: Sequence[str],
    status: str,
    *,
    run_id: str,
    pair: Optional[str] = None,
):
    if status not in RUNTIME_PHASE_STATUSES:
        raise PhasePlanError(f"Unsupported phase status {status!r}.")
    payload = _load_task_meta(task_meta_file, task_meta_file.parent.name)
    raw_phase_status = payload.get("phase_status")
    phase_status = raw_phase_status if isinstance(raw_phase_status, dict) else {}
    raw_history = payload.get("phase_history")
    history = list(raw_history) if isinstance(raw_history, list) else []
    timestamp = datetime.now(timezone.utc).isoformat()
    for phase_id in phase_ids:
        if phase_status.get(phase_id) == status:
            continue
        phase_status[phase_id] = status
        entry: Dict[str, object] = {
            "phase_id": phase_id,
            "run_id": run_id,
            "status": status,
            "ts": timestamp,
        }
        if pair is not None:
            entry["pair"] = pair
        history.append(entry)
    payload["phase_status"] = phase_status
    payload["phase_history"] = history
    _write_task_meta(task_meta_file, payload)


DEFAULT_REQUEST_TEXT = "No explicit initial request was provided for this run. Use repository artifacts and explicit clarifications only."


def _normalize_request_text(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    normalized = text.strip()
    return normalized or None


def _extract_request_from_legacy_context(context_file: Path) -> Optional[str]:
    if not context_file.exists():
        return None
    text = context_file.read_text(encoding="utf-8").strip()
    if not text:
        return None
    text = re.split(r"\n### Clarification\b", text, maxsplit=1)[0].strip()
    if text.startswith("# Product Context"):
        text = text[len("# Product Context"):].strip()
    return text or None


def _load_task_meta(task_meta_file: Path, task_id: str) -> Dict[str, Any]:
    if task_meta_file.exists():
        try:
            payload = json.loads(task_meta_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "task_id": task_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_task_meta(task_meta_file: Path, payload: Dict[str, Any]):
    task_meta_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def task_request_text(task_meta_file: Path, legacy_context_file: Optional[Path] = None) -> Optional[str]:
    payload = _load_task_meta(task_meta_file, task_meta_file.parent.name)
    request_text = _normalize_request_text(payload.get("request_text") if isinstance(payload.get("request_text"), str) else None)
    if request_text:
        return request_text
    if legacy_context_file is not None:
        return _extract_request_from_legacy_context(legacy_context_file)
    return None


def write_request_snapshot(request_file: Path, request_text: Optional[str]):
    if request_file.exists():
        return
    body = _normalize_request_text(request_text) or DEFAULT_REQUEST_TEXT
    request_file.write_text(body.rstrip() + "\n", encoding="utf-8")


def reconstruct_legacy_request_snapshot(request_file: Path, legacy_context_file: Path) -> str:
    stamp = datetime.now(timezone.utc).isoformat()
    legacy_request = _extract_request_from_legacy_context(legacy_context_file)
    if legacy_request:
        request_file.write_text(
            (
                f"[Legacy request snapshot reconstructed on {stamp} from {legacy_context_file}. "
                "The original run-scoped request.md was missing, so this may not exactly match the original run-start request.]\n\n"
                f"{legacy_request.rstrip()}\n"
            ),
            encoding="utf-8",
        )
        return "Legacy run request snapshot was reconstructed from the legacy task context because request.md was missing."
    request_file.write_text(
        (
            f"[Original run-start request unavailable. This legacy run predates immutable request snapshots. "
            f"Reconstructed placeholder written on {stamp}.]\n"
        ),
        encoding="utf-8",
    )
    return "Legacy run request snapshot was unavailable; resuming with a placeholder request snapshot."


def append_runtime_notice(
    task_run_log: Path,
    run_run_log: Path,
    task_raw_phase_log: Path,
    run_raw_phase_log: Path,
    run_id: str,
    message: str,
    *,
    entry: str,
):
    append_run_log(task_run_log, message, run_id=run_id)
    append_run_log(run_run_log, message, run_id=run_id)
    append_runtime_raw_log(task_raw_phase_log, run_id, entry, message)
    append_runtime_raw_log(run_raw_phase_log, run_id, entry, message)


def load_session_state(session_file: Path, default_mode: str) -> SessionState:
    if session_file.exists():
        try:
            payload = json.loads(session_file.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return SessionState(
                    mode=str(payload.get("mode") or default_mode),
                    thread_id=payload.get("thread_id") if isinstance(payload.get("thread_id"), str) else None,
                    pending_clarification_note=payload.get("pending_clarification_note")
                    if isinstance(payload.get("pending_clarification_note"), str)
                    else None,
                    created_at=str(payload.get("created_at") or datetime.now(timezone.utc).isoformat()),
                    last_used_at=payload.get("last_used_at") if isinstance(payload.get("last_used_at"), str) else None,
                )
        except (json.JSONDecodeError, OSError):
            pass
    return SessionState(
        mode=default_mode,
        thread_id=None,
        pending_clarification_note=None,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def save_session_state(session_file: Path, state: SessionState):
    payload = {
        "mode": state.mode,
        "thread_id": state.thread_id,
        "pending_clarification_note": state.pending_clarification_note,
        "created_at": state.created_at,
        "last_used_at": state.last_used_at,
    }
    session_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def has_git_repo(root: Path) -> bool:
    probe = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return probe.returncode == 0


def ensure_git_commit_ready(root: Path):
    author = run_git(["var", "GIT_AUTHOR_IDENT"], cwd=root, allow_fail=True)
    committer = run_git(["var", "GIT_COMMITTER_IDENT"], cwd=root, allow_fail=True)
    if author.returncode != 0 or committer.returncode != 0:
        details = (
            author.stderr.strip()
            or committer.stderr.strip()
            or "Configure user.name and user.email for this repository."
        )
        fatal(f"[!] FATAL GIT ERROR: Unable to determine a valid git author identity.\n{details}")


def repo_relative_path(root: Path, absolute_or_relative: Path) -> str:
    """Returns a git-usable repo-relative path string."""
    try:
        return str(absolute_or_relative.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(absolute_or_relative)


def commit_paths(root: Path, message: str, paths: Iterable[str]) -> bool:
    """Stages and commits only the provided repo-relative paths when changed."""
    unique_paths = sorted({p for p in paths if p})
    if not unique_paths:
        return False

    run_git(["add", "--", *unique_paths], cwd=root)
    if not changed_paths(root, tracked_paths=unique_paths):
        return False

    run_git(["commit", "-m", message], cwd=root)
    return True


def commit_tracked_changes(root: Path, message: str, tracked_paths: Optional[Sequence[str]] = None) -> bool:
    tracked = list(tracked_paths) if tracked_paths else []
    if not tracked:
        return False
    return commit_paths(root, message, tracked)


def check_dependencies(require_git: bool = True):
    missing = []
    if require_git and not shutil.which("git"):
        missing.append("git")
    if not shutil.which("codex"):
        missing.append("codex (install via 'npm i -g @openai/codex')")
    if missing:
        fatal(f"[!] FATAL: Missing required dependencies: {', '.join(missing)}")


def resolve_codex_exec_command(model: str) -> CodexCommandConfig:
    help_result = subprocess.run(
        ["codex", "exec", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if help_result.returncode != 0:
        details = help_result.stderr.strip() or help_result.stdout.strip() or "Unable to inspect `codex exec --help`."
        fatal(f"[!] FATAL CODEX ERROR: {details}")

    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    supports_bypass = "--dangerously-bypass-approvals-and-sandbox" in help_text
    supports_full_auto = "--full-auto" in help_text
    supports_json = "--json" in help_text
    resume_help = subprocess.run(
        ["codex", "exec", "resume", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if resume_help.returncode != 0:
        details = resume_help.stderr.strip() or resume_help.stdout.strip() or "Unable to inspect `codex exec resume --help`."
        fatal(f"[!] FATAL CODEX ERROR: {details}")
    resume_text = f"{resume_help.stdout}\n{resume_help.stderr}"
    supports_resume_json = "--json" in resume_text

    if not supports_json or not supports_resume_json:
        fatal("[!] FATAL CODEX ERROR: This Superloop version requires `codex exec` and `codex exec resume` support for --json.")

    if supports_bypass:
        return CodexCommandConfig(
            start_command=[
                "codex",
                "exec",
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
                "--model",
                model,
                "-",
            ],
            resume_command=[
                "codex",
                "exec",
                "resume",
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
                "--model",
                model,
            ],
        )

    if supports_full_auto:
        return CodexCommandConfig(
            start_command=[
                "codex",
                "exec",
                "--json",
                "--full-auto",
                "--model",
                model,
                "-",
            ],
            resume_command=[
                "codex",
                "exec",
                "resume",
                "--json",
                "--full-auto",
                "--model",
                model,
            ],
        )

    fatal(
        "[!] FATAL CODEX ERROR: This Superloop version requires `codex exec` support for "
        "either --dangerously-bypass-approvals-and-sandbox or --full-auto."
    )

def parse_pairs(pairs_arg: str, max_iterations: int) -> List[PairConfig]:
    requested = [p.strip().lower() for p in pairs_arg.split(",") if p.strip()]
    if not requested:
        fatal("[!] FATAL: --pairs must include at least one pair.")

    duplicates = sorted({name for name in requested if requested.count(name) > 1})
    if duplicates:
        fatal(
            f"[!] FATAL: Duplicate pair(s) in --pairs: {', '.join(duplicates)}. "
            f"Use each pair at most once from: {', '.join(PAIR_ORDER)}"
        )

    invalid = [p for p in requested if p not in PAIR_ORDER]
    if invalid:
        fatal(f"[!] FATAL: Unsupported pair(s): {', '.join(invalid)}. Valid values: {', '.join(PAIR_ORDER)}")

    requested_set = set(requested)
    return [
        PairConfig(name=pair, enabled=(pair in requested_set), max_iterations=max_iterations)
        for pair in PAIR_ORDER
    ]


def slugify_task(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug or "task"


def derive_intent_task_id(intent: str) -> str:
    slug = _truncate_slug(slugify_task(intent), 48)
    digest = hashlib.sha1(intent.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def _truncate_slug(slug: str, max_length: int) -> str:
    if len(slug) <= max_length:
        return slug or "task"
    truncated = slug[:max_length].rstrip("-")
    return truncated or "task"


def render_task_prompt(template: str, task_root_rel: str) -> str:
    return template.replace(".superloop/", f"{task_root_rel}/")


def ensure_workspace(
    root: Path,
    task_id: str,
    product_intent: Optional[str],
    intent_mode: str,
) -> Dict[str, Path]:
    super_dir = root / ".superloop"
    super_dir.mkdir(parents=True, exist_ok=True)

    tasks_dir = super_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    task_dir = tasks_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    task_root_rel = repo_relative_path(root, task_dir)

    run_log = task_dir / "run_log.md"
    if not run_log.exists():
        run_log.write_text("# Superloop Run Log\n", encoding="utf-8")

    raw_phase_log = task_dir / "raw_phase_log.md"
    if not raw_phase_log.exists():
        raw_phase_log.write_text("# Superloop Raw Phase Log\n", encoding="utf-8")

    runs_dir = task_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    task_meta_file = task_dir / "task.json"
    legacy_context_file = task_dir / "context.md"
    task_meta = _load_task_meta(task_meta_file, task_id)
    existing_request = _normalize_request_text(task_meta.get("request_text") if isinstance(task_meta.get("request_text"), str) else None)
    if existing_request is None:
        existing_request = _extract_request_from_legacy_context(legacy_context_file)

    normalized_intent = _normalize_request_text(product_intent)
    if normalized_intent is not None:
        if intent_mode == "replace" or existing_request is None:
            existing_request = normalized_intent
        elif intent_mode == "append":
            stamp = datetime.now(timezone.utc).isoformat()
            existing_request = f"{existing_request}\n\n## Run Intent ({stamp})\n{normalized_intent}"
        elif intent_mode == "preserve" and existing_request is None:
            existing_request = normalized_intent
    task_meta["request_text"] = existing_request
    if normalized_intent is not None or "request_updated_at" not in task_meta:
        task_meta["request_updated_at"] = datetime.now(timezone.utc).isoformat()
    task_meta.setdefault("phase_plan_path", str(Path(task_root_rel) / "plan" / "phase_plan.yaml"))
    _write_task_meta(task_meta_file, task_meta)

    pair_dirs: Dict[str, Path] = {}
    for pair in PAIR_ORDER:
        pair_dir = task_dir / pair
        pair_dir.mkdir(parents=True, exist_ok=True)
        pair_dirs[pair] = pair_dir

        prompt_file = pair_dir / "prompt.md"
        if not prompt_file.exists():
            prompt_file.write_text(render_task_prompt(PAIR_PRODUCER_PROMPT[pair], task_root_rel), encoding="utf-8")

        verifier_prompt_file = pair_dir / "verifier_prompt.md"
        if not verifier_prompt_file.exists():
            verifier_prompt_file.write_text(render_task_prompt(PAIR_VERIFIER_PROMPT[pair], task_root_rel), encoding="utf-8")

        criteria_file = pair_dir / "criteria.md"
        if not criteria_file.exists():
            criteria_file.write_text(PAIR_CRITERIA_TEMPLATES[pair], encoding="utf-8")

        feedback_file = pair_dir / "feedback.md"
        if not feedback_file.exists():
            feedback_file.write_text(f"# {PAIR_LABELS[pair]} Feedback\n", encoding="utf-8")

        for artifact_name in PAIR_ARTIFACTS[pair]:
            artifact = pair_dir / artifact_name
            if not artifact.exists():
                artifact.write_text(f"# {artifact_name}\n", encoding="utf-8")

    return {
        "super_dir": super_dir,
        "tasks_dir": tasks_dir,
        "task_dir": task_dir,
        "task_meta_file": task_meta_file,
        "task_root_rel": Path(task_root_rel),
        "task_id": task_id,
        "runs_dir": runs_dir,
        "run_log": run_log,
        "raw_phase_log": raw_phase_log,
        "legacy_context_file": legacy_context_file,
        **{f"pair_{k}": v for k, v in pair_dirs.items()},
    }


def create_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}-{uuid4().hex[:8]}"


def create_run_paths(runs_dir: Path, run_id: str, request_text: Optional[str], session_mode: str = "persistent") -> Dict[str, Path]:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    run_log = run_dir / "run_log.md"
    run_log.write_text(f"# Superloop Run Log ({run_id})\n", encoding="utf-8")

    raw_phase_log = run_dir / "raw_phase_log.md"
    raw_phase_log.write_text(f"# Superloop Raw Phase Log ({run_id})\n", encoding="utf-8")

    events_file = run_dir / "events.jsonl"
    events_file.write_text("", encoding="utf-8")

    summary_file = run_dir / "summary.md"
    request_file = run_dir / "request.md"
    session_file = run_dir / "session.json"
    write_request_snapshot(request_file, request_text)
    save_session_state(session_file, load_session_state(session_file, session_mode))

    return {
        "run_dir": run_dir,
        "run_log": run_log,
        "raw_phase_log": raw_phase_log,
        "events_file": events_file,
        "summary_file": summary_file,
        "request_file": request_file,
        "session_file": session_file,
    }


def open_existing_run_paths(
    runs_dir: Path,
    run_id: str,
) -> Dict[str, Path]:
    run_dir = runs_dir / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        fatal(f"[!] FATAL: run_id not found under task runs/: {run_id}")

    run_log = run_dir / "run_log.md"
    raw_phase_log = run_dir / "raw_phase_log.md"
    events_file = run_dir / "events.jsonl"
    summary_file = run_dir / "summary.md"
    request_file = run_dir / "request.md"
    session_file = run_dir / "session.json"

    if not run_log.exists():
        run_log.write_text(f"# Superloop Run Log ({run_id})\n", encoding="utf-8")
    if not raw_phase_log.exists():
        raw_phase_log.write_text(f"# Superloop Raw Phase Log ({run_id})\n", encoding="utf-8")
    if not events_file.exists():
        events_file.write_text("", encoding="utf-8")

    return {
        "run_dir": run_dir,
        "run_log": run_log,
        "raw_phase_log": raw_phase_log,
        "events_file": events_file,
        "summary_file": summary_file,
        "request_file": request_file,
        "session_file": session_file,
    }


def append_raw_log_entry(raw_phase_log: Path, body: str, **fields: Optional[object]):
    header = " | ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
    with raw_phase_log.open("a", encoding="utf-8") as f:
        f.write("\n\n---\n")
        f.write(f"{header}\n")
        f.write("---\n")
        f.write(body if body else "[empty stdout]\n")
        if not body.endswith("\n"):
            f.write("\n")


def append_raw_phase_log(
    raw_phase_log: Path,
    pair: str,
    phase: str,
    cycle: int,
    attempt: int,
    process_name: str,
    stdout: str,
    run_id: str,
    thread_id: Optional[str] = None,
):
    append_raw_log_entry(
        raw_phase_log,
        stdout if stdout else "[empty stdout]\n",
        run_id=run_id,
        entry="phase_output",
        pair=pair,
        phase=phase,
        process=process_name,
        cycle=cycle,
        attempt=attempt,
        thread_id=thread_id,
    )


def append_runtime_raw_log(
    raw_phase_log: Path,
    run_id: str,
    entry: str,
    body: str,
    *,
    pair: Optional[str] = None,
    phase: Optional[str] = None,
    cycle: Optional[int] = None,
    attempt: Optional[int] = None,
    thread_id: Optional[str] = None,
    source: Optional[str] = None,
):
    append_raw_log_entry(
        raw_phase_log,
        body,
        run_id=run_id,
        entry=entry,
        pair=pair,
        phase=phase,
        cycle=cycle,
        attempt=attempt,
        thread_id=thread_id,
        source=source,
    )


def parse_codex_exec_json(raw_output: str) -> Tuple[str, Optional[str]]:
    messages: List[str] = []
    thread_id: Optional[str] = None
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            thread_id = event["thread_id"]
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            messages.append(item["text"])
    return "\n\n".join(part.strip() for part in messages if part and part.strip()), thread_id


def build_phase_prompt(
    *,
    cwd: Path,
    prompt_file: Path,
    request_file: Path,
    run_raw_phase_log: Path,
    pair_name: str,
    phase_name: str,
    cycle_num: int,
    attempt_num: int,
    run_id: str,
    session_state: SessionState,
    include_request_snapshot: bool,
    active_phase_selection: Optional[ResolvedPhaseSelection] = None,
) -> str:
    base_instructions = prompt_file.read_text(encoding="utf-8")
    request_text = request_file.read_text(encoding="utf-8").strip()
    preamble = [
        f"REPOSITORY ROOT: {cwd}",
        f"RUN ID: {run_id}",
        f"LOOP PAIR: {pair_name}",
        f"PHASE ROLE: {phase_name}",
        f"CYCLE: {cycle_num}",
        f"ATTEMPT: {attempt_num}",
        f"IMMUTABLE REQUEST FILE: {request_file}",
        f"AUTHORITATIVE RAW LOG: {run_raw_phase_log}",
        "AUTHORITY ORDER FOR THIS TURN:",
        "1. Explicit clarification entries already appended to the authoritative raw log.",
        "2. The immutable initial request snapshot.",
        "3. Pair artifacts produced by earlier phases.",
        "4. Earlier conversation memory.",
        "Only explicit clarification entries may change user intent.",
        "Use repo-wide exploration only for dependency and regression analysis; do not absorb unrelated dirty files into scope unless explicitly justified.",
    ]
    if session_state.thread_id:
        preamble.append(f"RESUMED THREAD ID: {session_state.thread_id}")
    else:
        preamble.append("THREAD STATUS: new thread starts on this turn.")
    if session_state.pending_clarification_note:
        preamble.extend(
            [
                "",
                "MOST RECENT CLARIFICATION TO APPLY IMMEDIATELY:",
                session_state.pending_clarification_note,
            ]
        )
    if include_request_snapshot:
        preamble.extend(
            [
                "",
                "INITIAL REQUEST SNAPSHOT:",
                request_text if request_text else DEFAULT_REQUEST_TEXT,
            ]
        )
    if pair_name in PHASED_PAIRS and active_phase_selection is not None:
        preamble.extend(
            [
                "",
                phase_prompt_context(active_phase_selection),
            ]
        )
    return "\n".join(preamble) + "\n\nFollow the prompt rules exactly.\n\n" + base_instructions


def run_codex_phase(
    codex_command: CodexCommandConfig,
    cwd: Path,
    prompt_file: Path,
    phase_name: str,
    pair_name: str,
    cycle_num: int,
    attempt_num: int,
    run_id: str,
    request_file: Path,
    session_file: Path,
    run_raw_phase_log: Path,
    raw_phase_log: Path,
    active_phase_selection: Optional[ResolvedPhaseSelection] = None,
) -> str:
    session_state = load_session_state(session_file, "persistent")
    session_state.mode = "persistent"
    include_request_snapshot = session_state.thread_id is None
    prompt_payload = build_phase_prompt(
        cwd=cwd,
        prompt_file=prompt_file,
        request_file=request_file,
        run_raw_phase_log=run_raw_phase_log,
        pair_name=pair_name,
        phase_name=phase_name,
        cycle_num=cycle_num,
        attempt_num=attempt_num,
        run_id=run_id,
        session_state=session_state,
        include_request_snapshot=include_request_snapshot,
        active_phase_selection=active_phase_selection,
    )

    if session_state.thread_id:
        command = [*codex_command.resume_command, session_state.thread_id, "-"]
        command_mode = "resume"
    else:
        command = list(codex_command.start_command)
        command_mode = "start"

    print(f"[*] Spawning {pair_name}:{phase_name} agent...")
    process = subprocess.run(
        command,
        cwd=cwd,
        input=prompt_payload,
        text=True,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        encoding="utf-8",
    )

    raw_exec_output = process.stdout or ""
    stdout, thread_id = parse_codex_exec_json(raw_exec_output)
    session_state.thread_id = thread_id or session_state.thread_id
    session_state.last_used_at = datetime.now(timezone.utc).isoformat()
    if process.returncode == 0:
        session_state.pending_clarification_note = None
    save_session_state(session_file, session_state)

    append_runtime_raw_log(
        raw_phase_log,
        run_id,
        "session_turn",
        f"mode={command_mode}\nprompt_file={prompt_file}",
        pair=pair_name,
        phase=phase_name,
        cycle=cycle_num,
        attempt=attempt_num,
        thread_id=session_state.thread_id,
    )
    append_runtime_raw_log(
        run_raw_phase_log,
        run_id,
        "session_turn",
        f"mode={command_mode}\nprompt_file={prompt_file}",
        pair=pair_name,
        phase=phase_name,
        cycle=cycle_num,
        attempt=attempt_num,
        thread_id=session_state.thread_id,
    )

    append_raw_phase_log(
        raw_phase_log,
        pair_name,
        phase_name,
        cycle_num,
        attempt_num,
        "codex-agent",
        stdout,
        run_id=run_id,
        thread_id=session_state.thread_id,
    )
    append_raw_phase_log(
        run_raw_phase_log,
        pair_name,
        phase_name,
        cycle_num,
        attempt_num,
        "codex-agent",
        stdout,
        run_id=run_id,
        thread_id=session_state.thread_id,
    )

    if process.returncode == 0 and command_mode == "start" and not thread_id:
        warning_message = (
            f"Codex CLI did not return a thread id during {pair_name}:{phase_name}; "
            "future phases will start a new conversation unless one becomes available."
        )
        warn(warning_message)
        append_runtime_raw_log(
            raw_phase_log,
            run_id,
            "session_warning",
            warning_message,
            pair=pair_name,
            phase=phase_name,
            cycle=cycle_num,
            attempt=attempt_num,
        )
        append_runtime_raw_log(
            run_raw_phase_log,
            run_id,
            "session_warning",
            warning_message,
            pair=pair_name,
            phase=phase_name,
            cycle=cycle_num,
            attempt=attempt_num,
        )

    if process.returncode != 0:
        diagnostic = stdout.strip() or raw_exec_output.strip()
        if diagnostic:
            print(diagnostic.rstrip(), file=sys.stderr)
        fatal(f"\n[!] Codex CLI failed during {pair_name}:{phase_name} with exit code {process.returncode}.")
    return stdout

@dataclass(frozen=True)
class PhaseControlDecision:
    action: str
    warning: Optional[str] = None


def format_question(control: LoopControl) -> Optional[str]:
    if not control.question:
        return None
    if control.question.best_supposition:
        return (
            f"{control.question.text}\n"
            f"Best supposition: {control.question.best_supposition}"
        )
    return control.question.text


def parse_phase_control(stdout: str, phase_name: str, pair_name: str) -> LoopControl:
    try:
        return parse_loop_control(stdout)
    except LoopControlParseError as exc:
        fatal(
            f"[!] {pair_name} {phase_name} emitted malformed or conflicting loop-control output: {exc}"
        )


def decide_producer_control(control: LoopControl) -> PhaseControlDecision:
    if control.question:
        return PhaseControlDecision(action="question")
    if control.promise:
        return PhaseControlDecision(action="ignore_promise")
    return PhaseControlDecision(action="continue")


def decide_verifier_control(control: LoopControl, criteria_checked: bool) -> PhaseControlDecision:
    if control.question:
        return PhaseControlDecision(action="question")
    if not control.promise:
        return PhaseControlDecision(
            action="incomplete",
            warning="No promise tag found, defaulted to <promise>INCOMPLETE</promise>.",
        )
    if control.promise == PROMISE_COMPLETE and not criteria_checked:
        return PhaseControlDecision(
            action="incomplete",
            warning="verifier emitted COMPLETE with unchecked criteria; downgrading to INCOMPLETE in lax guard mode.",
        )
    if control.promise == PROMISE_COMPLETE:
        return PhaseControlDecision(action="complete")
    if control.promise == PROMISE_BLOCKED:
        return PhaseControlDecision(action="blocked")
    return PhaseControlDecision(action="incomplete")


def ask_human(question_text: str) -> str:
    print(f"\n[AGENT QUESTION]\n{question_text}\n")
    while True:
        try:
            answer = input("Your answer (type 'skip' to provide no answer): ").strip()
        except EOFError:
            print("\n[!] EOF detected. Exiting.")
            sys.exit(130)

        if answer.lower() == "skip":
            return "[User skipped providing an answer]"
        if answer:
            return answer
        print("Please provide an answer, or type 'skip'.")


def auto_answer_question(codex_command: CodexCommandConfig, root: Path, request_file: Path, raw_phase_log: Path, question: str) -> str:
    request_text = request_file.read_text(encoding="utf-8").strip()
    prompt = (
        "You are assisting a superloop orchestrator.\n"
        "Answer the question using repository context and existing requirements.\n"
        "If uncertain, provide the safest explicit assumption.\n"
        f"The immutable request snapshot is at {request_file}.\n"
        f"The authoritative chronological raw log is at {raw_phase_log}.\n"
        "Return plain text only.\n\n"
        f"Question:\n{question}\n\n"
        f"Request snapshot:\n{request_text if request_text else DEFAULT_REQUEST_TEXT}\n"
    )
    process = subprocess.run(
        codex_command.start_command,
        cwd=root,
        input=prompt,
        text=True,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        encoding="utf-8",
    )
    if process.returncode != 0:
        fatal(f"[!] Auto-answer pass failed with exit code {process.returncode}.")
    answer, _thread_id = parse_codex_exec_json(process.stdout or "")
    answer = answer.strip()
    if not answer:
        return "[Auto-answer failed to produce content]"
    return answer


def append_clarification(
    run_raw_phase_log: Path,
    task_raw_phase_log: Path,
    session_file: Path,
    pair: str,
    phase: str,
    cycle: int,
    attempt: int,
    question: str,
    answer: str,
    run_id: str,
    source: str,
) -> str:
    note = f"Question:\n{question}\n\nAnswer:\n{answer}"
    body = f"{note}\n"
    append_runtime_raw_log(
        task_raw_phase_log,
        run_id,
        "clarification",
        body,
        pair=pair,
        phase=phase,
        cycle=cycle,
        attempt=attempt,
        source=source,
    )
    append_runtime_raw_log(
        run_raw_phase_log,
        run_id,
        "clarification",
        body,
        pair=pair,
        phase=phase,
        cycle=cycle,
        attempt=attempt,
        source=source,
    )
    session_state = load_session_state(session_file, "persistent")
    session_state.pending_clarification_note = note
    save_session_state(session_file, session_state)
    return note


def append_run_log(
    run_log: Path,
    message: str,
    run_id: str,
    pair: Optional[str] = None,
    cycle: Optional[int] = None,
    attempt: Optional[int] = None,
):
    scope_bits = [f"run_id={run_id}"]
    if pair is not None:
        scope_bits.append(f"pair={pair}")
    if cycle is not None:
        scope_bits.append(f"cycle={cycle}")
    if attempt is not None:
        scope_bits.append(f"attempt={attempt}")
    scope = " | ".join(scope_bits)
    with run_log.open("a", encoding="utf-8") as f:
        f.write(f"\n- {message} ({scope})\n")


def write_run_summary(summary_file: Path, run_id: str, events_file: Path):
    if not events_file.exists():
        summary_file.write_text(f"# Superloop Run Summary ({run_id})\n\nNo events recorded.\n", encoding="utf-8")
        return

    counters = {
        "phase_output_empty": 0,
        "missing_promise_default": 0,
        "question": 0,
        "blocked": 0,
        "pair_completed": 0,
        "pair_failed": 0,
        "phase_scope_resolved": 0,
        "phase_started": 0,
        "phase_completed": 0,
        "phase_blocked": 0,
        "phase_deferred": 0,
    }

    invariant_violations: List[str] = []
    completed_pair_scopes: Set[Tuple[str, Optional[str]]] = set()

    with events_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            event_type = event.get("event_type")
            if event_type in counters:
                counters[event_type] += 1

            pair = event.get("pair")
            phase_id = event.get("phase_id") if isinstance(event.get("phase_id"), str) else None
            completion_scope = (pair, phase_id) if pair else None
            allowed_after_pair_completion = {
                "pair_completed",
                "run_finished",
                "phase_deferred",
                "phase_completed",
                "phase_blocked",
            }
            if (
                completion_scope
                and completion_scope in completed_pair_scopes
                and event_type not in allowed_after_pair_completion
            ):
                invariant_violations.append(
                    f"Pair {pair} received event {event_type} after pair_completed for phase "
                    f"{phase_id or '[global]'} (seq={event.get('seq')})."
                )

            if event_type == "pair_completed" and pair:
                completed_pair_scopes.add((pair, phase_id))

    summary = (
        f"# Superloop Run Summary ({run_id})\n\n"
        f"- phase_output_empty: {counters['phase_output_empty']}\n"
        f"- missing_promise_default: {counters['missing_promise_default']}\n"
        f"- question events: {counters['question']}\n"
        f"- blocked events: {counters['blocked']}\n"
        f"- pair_completed events: {counters['pair_completed']}\n"
        f"- pair_failed events: {counters['pair_failed']}\n"
        f"- phase_scope_resolved events: {counters['phase_scope_resolved']}\n"
        f"- phase_started events: {counters['phase_started']}\n"
        f"- phase_completed events: {counters['phase_completed']}\n"
        f"- phase_blocked events: {counters['phase_blocked']}\n"
        f"- phase_deferred events: {counters['phase_deferred']}\n"
    )
    if invariant_violations:
        summary += "\n## Invariant violations\n"
        for violation in invariant_violations:
            summary += f"- {violation}\n"
    summary_file.write_text(summary, encoding="utf-8")


def list_tasks(tasks_dir: Path) -> List[str]:
    if not tasks_dir.exists():
        return []
    return sorted([entry.name for entry in tasks_dir.iterdir() if entry.is_dir()])


def _parse_iso8601_utc(text: str) -> Optional[datetime]:
    try:
        if text.endswith("Z"):
            return datetime.fromisoformat(text[:-1] + "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def latest_task_id(tasks_dir: Path) -> Optional[str]:
    if not tasks_dir.exists():
        return None
    tasks = [entry for entry in tasks_dir.iterdir() if entry.is_dir()]
    if not tasks:
        return None

    best: Optional[Tuple[datetime, str]] = None
    for task in tasks:
        created_at: Optional[datetime] = None
        task_meta = task / "task.json"
        if task_meta.exists():
            try:
                payload = json.loads(task_meta.read_text(encoding="utf-8"))
                raw_created = payload.get("created_at")
                if isinstance(raw_created, str):
                    created_at = _parse_iso8601_utc(raw_created)
            except (json.JSONDecodeError, OSError):
                created_at = None
        if created_at is None:
            created_at = datetime.min.replace(tzinfo=timezone.utc)

        candidate = (created_at, task.name)
        if best is None or candidate > best:
            best = candidate

    return best[1] if best else None


def _run_id_timestamp(run_id: str) -> Optional[datetime]:
    match = re.fullmatch(r"run-(\d{8}T\d{6}Z)-[0-9a-f]{8}", run_id)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def latest_run_id(runs_dir: Path) -> Optional[str]:
    if not runs_dir.exists():
        return None
    runs = [entry for entry in runs_dir.iterdir() if entry.is_dir()]
    if not runs:
        return None

    def run_sort_key(run_path: Path) -> Tuple[datetime, str]:
        parsed = _run_id_timestamp(run_path.name)
        if parsed is not None:
            return (parsed, run_path.name)

        events_file = run_path / "events.jsonl"
        if events_file.exists():
            try:
                with events_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        event = json.loads(line)
                        ts = event.get("ts")
                        if isinstance(ts, str):
                            parsed_ts = _parse_iso8601_utc(ts)
                            if parsed_ts is not None:
                                return (parsed_ts, run_path.name)
            except (OSError, json.JSONDecodeError):
                pass

        return (datetime.min.replace(tzinfo=timezone.utc), run_path.name)

    return max(runs, key=run_sort_key).name


def latest_run_status(events_file: Path) -> Optional[str]:
    if not events_file.exists():
        return None
    last_status: Optional[str] = None
    with events_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            if event.get("event_type") == "run_finished":
                status = event.get("status")
                if isinstance(status, str):
                    last_status = status
    return last_status


def task_id_for_run(tasks_dir: Path, run_id: str) -> Optional[str]:
    if not tasks_dir.exists():
        return None
    for task_dir in tasks_dir.iterdir():
        if not task_dir.is_dir():
            continue
        if (task_dir / "runs" / run_id).is_dir():
            return task_dir.name
    return None


def load_resume_checkpoint(events_file: Path, enabled_pairs: Sequence[str]) -> ResumeCheckpoint:
    attempts: Dict[Tuple[str, int], int] = {}
    max_cycle_by_pair: Dict[str, int] = {}
    completed_pairs: Set[str] = set()
    phase_attempts: Dict[Tuple[str, str, int], int] = {}
    max_cycle_by_phase_pair: Dict[Tuple[str, str], int] = {}
    completed_pairs_by_phase: Dict[str, Set[str]] = {}
    emitted_phase_started_ids: Set[str] = set()
    emitted_phase_completed_ids: Set[str] = set()
    emitted_phase_deferred_keys: Set[Tuple[str, str]] = set()
    scope_event_seen = False
    last_seq = 0
    phase_mode: Optional[str] = None
    phase_ids: Tuple[str, ...] = ()
    current_phase_index = 0

    if events_file.exists():
        with events_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                event = json.loads(line)
                event_type = event.get("event_type")
                pair = event.get("pair")
                cycle = event.get("cycle")
                attempt = event.get("attempt")
                seq = event.get("seq")
                phase_id = event.get("phase_id") if isinstance(event.get("phase_id"), str) else None

                if isinstance(seq, int):
                    last_seq = max(last_seq, seq)
                if pair in enabled_pairs and isinstance(cycle, int):
                    if phase_id is None:
                        max_cycle_by_pair[pair] = max(max_cycle_by_pair.get(pair, 0), cycle)
                        if isinstance(attempt, int):
                            key = (pair, cycle)
                            attempts[key] = max(attempts.get(key, 0), attempt)
                    else:
                        phase_pair_key = (phase_id, pair)
                        max_cycle_by_phase_pair[phase_pair_key] = max(
                            max_cycle_by_phase_pair.get(phase_pair_key, 0), cycle
                        )
                        if isinstance(attempt, int):
                            attempt_key = (phase_id, pair, cycle)
                            phase_attempts[attempt_key] = max(phase_attempts.get(attempt_key, 0), attempt)
                if event_type == "pair_completed" and pair in enabled_pairs:
                    if phase_id is None:
                        completed_pairs.add(pair)
                    else:
                        completed_pairs_by_phase.setdefault(phase_id, set()).add(pair)
                if event_type == "phase_scope_resolved":
                    scope_event_seen = True
                    raw_mode = event.get("phase_mode")
                    raw_phase_ids = event.get("phase_ids")
                    raw_current_phase_index = event.get("current_phase_index")
                    if isinstance(raw_mode, str):
                        phase_mode = raw_mode
                    if isinstance(raw_phase_ids, list):
                        phase_ids = tuple(
                            item for item in raw_phase_ids if isinstance(item, str) and item.strip()
                        )
                    if isinstance(raw_current_phase_index, int) and raw_current_phase_index >= 0:
                        current_phase_index = raw_current_phase_index
                if event_type == "phase_started" and phase_id is not None:
                    emitted_phase_started_ids.add(phase_id)
                if event_type == "phase_completed" and phase_id is not None:
                    emitted_phase_completed_ids.add(phase_id)
                if event_type == "phase_deferred" and phase_id is not None and isinstance(pair, str):
                    emitted_phase_deferred_keys.add((phase_id, pair))

    pair_start_index = len(enabled_pairs)
    for idx, pair in enumerate(enabled_pairs):
        if pair not in completed_pairs:
            pair_start_index = idx
            break

    cycle_by_pair: Dict[str, int] = {}
    if pair_start_index < len(enabled_pairs):
        active_pair = enabled_pairs[pair_start_index]
        cycle_by_pair[active_pair] = max(0, max_cycle_by_pair.get(active_pair, 0) - 1)

    cycle_by_phase_pair = {
        phase_pair: max(0, cycle - 1) for phase_pair, cycle in max_cycle_by_phase_pair.items()
    }

    return ResumeCheckpoint(
        pair_start_index=pair_start_index,
        cycle_by_pair=cycle_by_pair,
        attempts_by_pair_cycle=attempts,
        cycle_by_phase_pair=cycle_by_phase_pair,
        attempts_by_phase_pair_cycle=phase_attempts,
        completed_pairs_by_phase={
            phase_id: tuple(sorted(pairs)) for phase_id, pairs in completed_pairs_by_phase.items()
        },
        emitted_phase_started_ids=tuple(sorted(emitted_phase_started_ids)),
        emitted_phase_completed_ids=tuple(sorted(emitted_phase_completed_ids)),
        emitted_phase_deferred_keys=tuple(sorted(emitted_phase_deferred_keys)),
        scope_event_seen=scope_event_seen,
        last_sequence=last_seq,
        phase_mode=phase_mode,
        phase_ids=phase_ids,
        current_phase_index=current_phase_index,
    )


def resolve_task_id(task_id: Optional[str], intent: Optional[str]) -> str:
    if task_id:
        return slugify_task(task_id)
    if intent:
        return derive_intent_task_id(intent)
    fatal("[!] FATAL: Provide --task-id or --intent so Superloop can select a task workspace.")


def load_phase_plan_or_fatal(task_dir: Path, task_id: str) -> Optional[PhasePlan]:
    plan_path = phase_plan_file(task_dir)
    try:
        return load_phase_plan(plan_path, task_id)
    except PhasePlanError as exc:
        fatal(f"[!] FATAL: Invalid explicit phase_plan.yaml at {plan_path}: {exc}")


def enforce_phase_parser_preconditions(
    *,
    task_dir: Path,
    enabled_pairs: Sequence[str],
):
    if yaml is not None:
        return
    phased_enabled = any(pair in PHASED_PAIRS for pair in enabled_pairs)
    if not phased_enabled:
        return

    explicit_plan_exists = phase_plan_file(task_dir).exists()
    plan_enabled = "plan" in enabled_pairs

    if explicit_plan_exists or plan_enabled:
        fatal(
            "[!] FATAL: PyYAML is required for explicit phase-plan workflows. "
            "Install dependencies from requirements.txt before running phased plan/implement/test flows."
        )


def resolve_active_phase_selection(
    *,
    task_dir: Path,
    task_id: str,
    request_file: Path,
    task_meta_file: Path,
    phase_id: Optional[str],
    phase_mode: str,
    enabled_pairs: Sequence[str],
    resume_checkpoint: Optional[ResumeCheckpoint],
    is_resume: bool,
) -> ResolvedPhaseSelection:
    explicit_plan = load_phase_plan_or_fatal(task_dir, task_id)
    if resume_checkpoint is not None and resume_checkpoint.phase_ids:
        stored_plan = explicit_plan if explicit_plan is not None else build_implicit_phase_plan(task_id, request_file)
        try:
            return restore_phase_selection(stored_plan, resume_checkpoint.phase_ids, resume_checkpoint.phase_mode)
        except PhasePlanError as exc:
            fatal(f"[!] FATAL: Unable to restore phase selection for resumed run: {exc}")

    if is_resume:
        stored_mode, stored_phase_ids, _stored_phase_index = active_phase_selection_from_meta(task_meta_file)
        if stored_phase_ids:
            stored_plan = explicit_plan if explicit_plan is not None else build_implicit_phase_plan(task_id, request_file)
            try:
                return restore_phase_selection(stored_plan, stored_phase_ids, stored_mode)
            except PhasePlanError as exc:
                fatal(f"[!] FATAL: Unable to restore phase selection from task metadata: {exc}")

    plan = explicit_plan if explicit_plan is not None else build_implicit_phase_plan(task_id, request_file)
    try:
        return resolve_phase_selection(plan, phase_id, phase_mode, enabled_pairs)
    except PhasePlanError as exc:
        fatal(f"[!] FATAL: {exc}")


def execute_pair_cycles(
    *,
    pair_cfg: PairConfig,
    pair: str,
    prompt_file: Path,
    verifier_prompt_file: Path,
    criteria_file: Path,
    feedback_file: Path,
    root: Path,
    codex_command: CodexCommandConfig,
    run_id: str,
    run_paths: Dict[str, Path],
    paths: Dict[str, Path],
    recorder: EventRecorder,
    task_root_rel: str,
    use_git: bool,
    active_phase_selection: Optional[ResolvedPhaseSelection],
    enabled_pairs: Sequence[str],
    args: argparse.Namespace,
    resume_checkpoint: Optional[ResumeCheckpoint],
    use_resume_state: bool,
) -> Tuple[str, int]:
    print(f"\n===== Pair: {PAIR_LABELS[pair]} =====")
    append_run_log(paths["run_log"], f"Started pair `{pair}`", run_id=run_id, pair=pair)
    append_run_log(run_paths["run_log"], f"Started pair `{pair}`", run_id=run_id, pair=pair)
    recorder.emit(
        "pair_started",
        pair=pair,
        phase_id=active_phase_selection.phase_ids[0] if active_phase_selection else None,
    )

    cycle = 0
    attempt_counts: Dict[int, int] = {}
    active_phase_id = active_phase_selection.phase_ids[0] if active_phase_selection else None
    if use_resume_state and resume_checkpoint is not None:
        if active_phase_id is None:
            cycle = resume_checkpoint.cycle_by_pair.get(pair, 0)
            for (attempt_pair, attempt_cycle), attempt_value in resume_checkpoint.attempts_by_pair_cycle.items():
                if attempt_pair == pair:
                    attempt_counts[attempt_cycle] = attempt_value
        else:
            cycle = resume_checkpoint.cycle_by_phase_pair.get((active_phase_id, pair), 0)
            for (attempt_phase_id, attempt_pair, attempt_cycle), attempt_value in (
                resume_checkpoint.attempts_by_phase_pair_cycle.items()
            ):
                if attempt_phase_id == active_phase_id and attempt_pair == pair:
                    attempt_counts[attempt_cycle] = attempt_value

    while cycle < pair_cfg.max_iterations:
        cycle_num = cycle + 1
        attempt_counts[cycle_num] = attempt_counts.get(cycle_num, 0) + 1
        attempt_num = attempt_counts[cycle_num]
        print(f"\n--- {pair} cycle {cycle_num}/{pair_cfg.max_iterations} ---")
        recorder.emit(
            "cycle_started",
            pair=pair,
            cycle=cycle_num,
            attempt=attempt_num,
            phase_id=active_phase_selection.phase_ids[0] if active_phase_selection else None,
        )
        pair_tracked = tracked_superloop_paths(task_root_rel, pair)
        if use_git:
            commit_tracked_changes(root, f"superloop: pre-cycle snapshot ({pair} #{cycle_num})", pair_tracked)

        producer_baseline = phase_snapshot_ref(root) if use_git else None

        producer_stdout = run_codex_phase(
            codex_command,
            root,
            prompt_file,
            "producer",
            pair,
            cycle_num,
            attempt_num,
            run_id,
            run_paths["request_file"],
            run_paths["session_file"],
            run_paths["raw_phase_log"],
            paths["raw_phase_log"],
            active_phase_selection=active_phase_selection if pair in PHASED_PAIRS else None,
        )
        recorder.emit(
            "phase_finished",
            pair=pair,
            phase="producer",
            cycle=cycle_num,
            attempt=attempt_num,
            empty_output=(not producer_stdout.strip()),
            phase_id=active_phase_selection.phase_ids[0] if active_phase_selection else None,
        )
        if not producer_stdout.strip():
            recorder.emit("phase_output_empty", pair=pair, phase="producer", cycle=cycle_num, attempt=attempt_num)
            warn(f"{pair} producer returned empty stdout (cycle {cycle_num}, attempt {attempt_num}).")
        producer_control = parse_phase_control(producer_stdout, "producer", pair)
        producer_decision = decide_producer_control(producer_control)
        producer_delta = changed_paths_from_snapshot(root, producer_baseline) if use_git else set()

        if producer_decision.action == "question":
            recorder.emit("question", pair=pair, phase="producer", cycle=cycle_num, attempt=attempt_num)
            producer_question = format_question(producer_control)
            if args.full_auto_answers:
                answer = auto_answer_question(codex_command, root, run_paths["request_file"], run_paths["raw_phase_log"], producer_question)
                print(f"[+] Auto-answered producer question: {answer}")
                answer_source = "auto"
            else:
                answer = ask_human(producer_question)
                answer_source = "human"
            append_clarification(
                run_paths["raw_phase_log"],
                paths["raw_phase_log"],
                run_paths["session_file"],
                pair,
                "producer",
                cycle_num,
                attempt_num,
                producer_question,
                answer,
                run_id,
                answer_source,
            )
            if use_git:
                commit_tracked_changes(root, f"superloop: answered producer question ({pair} #{cycle_num})", pair_tracked)
            continue

        if producer_decision.action == "ignore_promise":
            warn(
                f"{pair} producer emitted <promise>{producer_control.promise}</promise>; ignoring because verifier controls completion."
            )

        if use_git and producer_delta:
            commit_paths(root, f"superloop: producer edits ({pair} #{cycle_num})", producer_delta)
        else:
            if use_git:
                print("[-] Producer made no changes.")
            else:
                print("[-] Change detection skipped in --no-git mode.")

        verifier_baseline = phase_snapshot_ref(root) if use_git else None

        verifier_stdout = run_codex_phase(
            codex_command,
            root,
            verifier_prompt_file,
            "verifier",
            pair,
            cycle_num,
            attempt_num,
            run_id,
            run_paths["request_file"],
            run_paths["session_file"],
            run_paths["raw_phase_log"],
            paths["raw_phase_log"],
            active_phase_selection=active_phase_selection if pair in PHASED_PAIRS else None,
        )
        recorder.emit(
            "phase_finished",
            pair=pair,
            phase="verifier",
            cycle=cycle_num,
            attempt=attempt_num,
            empty_output=(not verifier_stdout.strip()),
            phase_id=active_phase_selection.phase_ids[0] if active_phase_selection else None,
        )
        if not verifier_stdout.strip():
            recorder.emit("phase_output_empty", pair=pair, phase="verifier", cycle=cycle_num, attempt=attempt_num)
            warn(f"{pair} verifier returned empty stdout (cycle {cycle_num}, attempt {attempt_num}).")
        verifier_control = parse_phase_control(verifier_stdout, "verifier", pair)
        verifier_decision = decide_verifier_control(
            verifier_control,
            criteria_checked=criteria_all_checked(criteria_file),
        )
        verifier_delta = changed_paths_from_snapshot(root, verifier_baseline) if use_git else set()

        if verifier_decision.action == "question":
            recorder.emit("question", pair=pair, phase="verifier", cycle=cycle_num, attempt=attempt_num)
            verifier_question = format_question(verifier_control)
            if args.full_auto_answers:
                answer = auto_answer_question(codex_command, root, run_paths["request_file"], run_paths["raw_phase_log"], verifier_question)
                print(f"[+] Auto-answered verifier question: {answer}")
                answer_source = "auto"
            else:
                answer = ask_human(verifier_question)
                answer_source = "human"
            append_clarification(
                run_paths["raw_phase_log"],
                paths["raw_phase_log"],
                run_paths["session_file"],
                pair,
                "verifier",
                cycle_num,
                attempt_num,
                verifier_question,
                answer,
                run_id,
                answer_source,
            )
            if use_git:
                commit_tracked_changes(root, f"superloop: answered verifier question ({pair} #{cycle_num})", pair_tracked)
            continue

        violations = verifier_scope_violations(pair, verifier_delta, task_root_rel) if use_git else []
        if use_git and violations:
            preview = ", ".join(violations[:8])
            if len(violations) > 8:
                preview += ", ..."
            warn(
                f"{pair} verifier edited files outside recommended scope ({task_root_rel}/{pair}/): {preview}. Continuing in lax guard mode."
            )

        if verifier_control.promise is None:
            recorder.emit("missing_promise_default", pair=pair, cycle=cycle_num, attempt=attempt_num)
            with feedback_file.open("a", encoding="utf-8") as f:
                f.write(
                    f"\n\n## System Warning (cycle {cycle_num})\n"
                    f"{verifier_decision.warning}\n"
                )
            verifier_delta.add(repo_relative_path(root, feedback_file))

        if verifier_control.promise == PROMISE_COMPLETE and verifier_decision.warning:
            warn(f"{pair} {verifier_decision.warning}")
            verifier_delta.add(repo_relative_path(root, feedback_file))

        if verifier_decision.action == "complete":
            print(f"[SUCCESS] Pair `{pair}` completed.")
            append_run_log(paths["run_log"], f"Completed pair `{pair}` in {cycle_num} cycles", run_id=run_id, pair=pair, cycle=cycle_num, attempt=attempt_num)
            append_run_log(run_paths["run_log"], f"Completed pair `{pair}` in {cycle_num} cycles", run_id=run_id, pair=pair, cycle=cycle_num, attempt=attempt_num)
            recorder.emit(
                "pair_completed",
                pair=pair,
                cycle=cycle_num,
                attempt=attempt_num,
                phase_id=active_phase_selection.phase_ids[0] if active_phase_selection else None,
            )
            if use_git:
                commit_paths(root, f"superloop: pair complete ({pair})", set(pair_tracked) | verifier_delta)
            return "complete", 0

        if verifier_decision.action == "blocked":
            append_run_log(paths["run_log"], f"Blocked in pair `{pair}` cycle {cycle_num}", run_id=run_id, pair=pair, cycle=cycle_num, attempt=attempt_num)
            append_run_log(run_paths["run_log"], f"Blocked in pair `{pair}` cycle {cycle_num}", run_id=run_id, pair=pair, cycle=cycle_num, attempt=attempt_num)
            recorder.emit("blocked", pair=pair, cycle=cycle_num, attempt=attempt_num)
            if use_git:
                commit_paths(root, f"superloop: blocked ({pair} #{cycle_num})", set(pair_tracked) | verifier_delta)
            print(f"[BLOCKED] Pair `{pair}` emitted BLOCKED.", file=sys.stderr)
            return "blocked", 2

        if use_git:
            commit_paths(root, f"superloop: verifier feedback ({pair} #{cycle_num})", verifier_delta)
        else:
            print("[-] Change detection skipped in --no-git mode.")
        cycle += 1
        time.sleep(2)

    append_run_log(paths["run_log"], f"Failed pair `{pair}` after max cycles", run_id=run_id, pair=pair)
    append_run_log(run_paths["run_log"], f"Failed pair `{pair}` after max cycles", run_id=run_id, pair=pair)
    recorder.emit("pair_failed", pair=pair)
    if use_git:
        commit_paths(root, f"superloop: failed ({pair} max iterations)", [repo_relative_path(root, paths["run_log"])])
    print(f"[FAILED] Pair `{pair}` reached max iterations without COMPLETE.", file=sys.stderr)
    return "failed", 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Superloop: optional strategy-to-execution Codex loop orchestration")
    parser.add_argument("--pairs", type=str, default="plan,implement,test", help="Comma list from: plan,implement,test")
    parser.add_argument("--phase-id", type=str, help="Explicit phase id for implement/test execution when phase_plan.yaml exists")
    parser.add_argument(
        "--phase-mode",
        choices=[PHASE_MODE_SINGLE, PHASE_MODE_UP_TO],
        default=PHASE_MODE_SINGLE,
        help="Phase targeting mode for implement/test execution",
    )
    parser.add_argument("--max-iterations", type=int, default=15, help="Maximum verifier cycles per enabled pair")
    parser.add_argument("--model", type=str, default="gpt-5.4", help="Codex model")
    parser.add_argument("--workspace", type=str, default=".", help="Repository/workspace root")
    parser.add_argument("--intent", type=str, help="Optional initial product intent text")
    parser.add_argument("--task-id", type=str, help="Task workspace id/slug under .superloop/tasks")
    parser.add_argument(
        "--intent-mode",
        choices=["replace", "append", "preserve"],
        default="preserve",
        help="How --intent updates an existing task context",
    )
    parser.add_argument("--resume", action="store_true", help="Resume from an existing task/run state")
    parser.add_argument("--run-id", type=str, help="Run ID under .superloop/tasks/<task-id>/runs")
    parser.add_argument("--list-tasks", action="store_true", help="List existing .superloop task IDs and exit")
    parser.add_argument("--full-auto-answers", action="store_true", help="Auto-answer agent questions using an extra Codex pass")
    parser.add_argument("--no-git", action="store_true", help="Do not initialize git or create git commits/checkpoints")
    args = parser.parse_args()

    if args.max_iterations < 1:
        fatal("[!] FATAL: --max-iterations must be >= 1")

    root = Path(args.workspace).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        fatal(f"[!] FATAL: --workspace must be an existing directory: {root}")

    if args.list_tasks:
        tasks = list_tasks(root / ".superloop" / "tasks")
        if tasks:
            for task in tasks:
                print(task)
        else:
            print("(no tasks found)")
        return 0

    use_git = not args.no_git
    tasks_dir = root / ".superloop" / "tasks"
    if args.run_id and not args.resume:
        fatal("[!] FATAL: --run-id requires --resume.")

    if args.resume:
        if args.task_id:
            task_id = slugify_task(args.task_id)
        elif args.run_id:
            found_task = task_id_for_run(tasks_dir, args.run_id)
            if not found_task:
                fatal(f"[!] FATAL: Unable to resolve task for run_id: {args.run_id}")
            task_id = found_task
        else:
            resolved_latest_task = latest_task_id(tasks_dir)
            if resolved_latest_task is None:
                fatal("[!] FATAL: No existing tasks available to resume.")
            task_id = resolved_latest_task
    else:
        task_id = resolve_task_id(args.task_id, args.intent)
    run_id: Optional[str] = None
    run_paths: Optional[Dict[str, Path]] = None
    recorder: Optional[EventRecorder] = None
    run_status = "setup"
    exit_code = 1
    if use_git and not shutil.which("git"):
        warn("git is not installed; forcing --no-git mode.")
        use_git = False
    check_dependencies(require_git=use_git)
    codex_command = resolve_codex_exec_command(args.model)
    pair_configs = parse_pairs(args.pairs, args.max_iterations)
    enabled_pairs = [p.name for p in pair_configs if p.enabled]

    if use_git:
        repo_exists = has_git_repo(root)
        if not repo_exists:
            print("[*] Initializing local Git repository...")
            run_git(["init"], cwd=root)
            run_git(["config", "user.name", "Superloop Agent"], cwd=root)
            run_git(["config", "user.email", "superloop@localhost"], cwd=root)

        ensure_git_commit_ready(root)
    paths = ensure_workspace(root, task_id, args.intent, args.intent_mode)
    enforce_phase_parser_preconditions(task_dir=paths["task_dir"], enabled_pairs=enabled_pairs)
    task_root_rel = str(paths["task_root_rel"])
    task_scoped_paths = tracked_superloop_paths(task_root_rel)
    resolved_request_text = task_request_text(paths["task_meta_file"], paths["legacy_context_file"])
    resume_checkpoint: Optional[ResumeCheckpoint] = None
    session_state: Optional[SessionState] = None
    if args.resume:
        run_id = args.run_id or latest_run_id(paths["runs_dir"])
        if not run_id:
            fatal(f"[!] FATAL: No runs found to resume for task: {task_id}")
        run_paths = open_existing_run_paths(paths["runs_dir"], run_id)
        terminal_status = latest_run_status(run_paths["events_file"])
        if terminal_status in {"success", "blocked", "failed", "fatal_error", "interrupted"}:
            fatal(f"[!] FATAL: Refusing to resume terminal run {run_id} (status={terminal_status}).")
        if not run_paths["request_file"].exists():
            request_notice = reconstruct_legacy_request_snapshot(
                run_paths["request_file"],
                paths["legacy_context_file"],
            )
            warn(request_notice)
            append_runtime_notice(
                paths["run_log"],
                run_paths["run_log"],
                paths["raw_phase_log"],
                run_paths["raw_phase_log"],
                run_id,
                request_notice,
                entry="request_recovery",
            )
        resume_checkpoint = load_resume_checkpoint(run_paths["events_file"], enabled_pairs)
        recorder = EventRecorder(run_id=run_id, events_file=run_paths["events_file"], sequence=resume_checkpoint.last_sequence)
        if run_paths["session_file"].exists():
            session_state = load_session_state(run_paths["session_file"], "persistent")
            session_state.mode = "persistent"
        else:
            session_state = SessionState(
                mode="persistent",
                thread_id=None,
                pending_clarification_note=None,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            save_session_state(run_paths["session_file"], session_state)
        if not session_state.thread_id:
            session_notice = "No stored Codex thread id is available; resuming with a new conversation for the next phase."
            warn(session_notice)
            append_runtime_notice(
                paths["run_log"],
                run_paths["run_log"],
                paths["raw_phase_log"],
                run_paths["raw_phase_log"],
                run_id,
                session_notice,
                entry="session_recovery",
            )
            save_session_state(run_paths["session_file"], session_state)
    else:
        run_id = create_run_id()
        run_paths = create_run_paths(paths["runs_dir"], run_id, resolved_request_text, session_mode="persistent")
        recorder = EventRecorder(run_id=run_id, events_file=run_paths["events_file"])
        session_state = load_session_state(run_paths["session_file"], "persistent")
    run_status = "running"

    if use_git and not args.resume:
        commit_tracked_changes(root, "superloop: baseline", task_scoped_paths)

    print("\n[+] Starting Superloop")
    print(f"[*] Workspace root: {root}")
    print(f"[*] Task ID: {task_id}")
    print(f"[*] Task root: {task_root_rel}")
    print(f"[*] Enabled pairs: {', '.join(enabled_pairs)}")
    print(f"[*] Run ID: {run_id}")
    append_run_log(paths["run_log"], "Run resumed" if args.resume else "Run started", run_id=run_id)
    append_run_log(run_paths["run_log"], "Run resumed" if args.resume else "Run started", run_id=run_id)
    recorder.emit(
        "run_resumed" if args.resume else "run_started",
        workspace=str(root),
        pairs=enabled_pairs,
        max_iterations=args.max_iterations,
        use_git=use_git,
        task_id=task_id,
        task_root=task_root_rel,
    )
    append_runtime_raw_log(
        paths["raw_phase_log"],
        run_id,
        "run_state",
        (
            f"workspace={root}\n"
            f"pairs={','.join(enabled_pairs)}\n"
            f"request_file={run_paths['request_file']}\n"
            f"session_mode={session_state.mode if session_state else 'persistent'}"
        ),
        thread_id=session_state.thread_id if session_state else None,
    )
    append_runtime_raw_log(
        run_paths["raw_phase_log"],
        run_id,
        "run_state",
        (
            f"workspace={root}\n"
            f"pairs={','.join(enabled_pairs)}\n"
            f"request_file={run_paths['request_file']}\n"
            f"session_mode={session_state.mode if session_state else 'persistent'}"
        ),
        thread_id=session_state.thread_id if session_state else None,
    )

    try:
        active_phase_selection: Optional[ResolvedPhaseSelection] = None
        phase_scope_emitted = False
        completed_phase_pairs: Dict[str, Set[str]] = (
            {phase_id: set(pairs) for phase_id, pairs in resume_checkpoint.completed_pairs_by_phase.items()}
            if resume_checkpoint is not None
            else {}
        )
        phase_started_ids: Set[str] = set(
            resume_checkpoint.emitted_phase_started_ids if resume_checkpoint is not None else ()
        )
        phase_completed_ids: Set[str] = set(
            resume_checkpoint.emitted_phase_completed_ids if resume_checkpoint is not None else ()
        )
        phase_deferred_keys: Set[Tuple[str, str]] = set(
            resume_checkpoint.emitted_phase_deferred_keys if resume_checkpoint is not None else ()
        )
        pair_by_name = {cfg.name: cfg for cfg in pair_configs}

        plan_cfg = pair_by_name.get("plan")
        should_run_plan_pair = plan_cfg is not None and plan_cfg.enabled
        if should_run_plan_pair and args.resume and resume_checkpoint is not None:
            try:
                plan_pair_index = enabled_pairs.index("plan")
            except ValueError:
                plan_pair_index = -1
            should_run_plan_pair = plan_pair_index >= 0 and plan_pair_index >= resume_checkpoint.pair_start_index
        if should_run_plan_pair:
            plan_result, plan_exit = execute_pair_cycles(
                pair_cfg=plan_cfg,
                pair="plan",
                prompt_file=paths["pair_plan"] / "prompt.md",
                verifier_prompt_file=paths["pair_plan"] / "verifier_prompt.md",
                criteria_file=paths["pair_plan"] / "criteria.md",
                feedback_file=paths["pair_plan"] / "feedback.md",
                root=root,
                codex_command=codex_command,
                run_id=run_id,
                run_paths=run_paths,
                paths=paths,
                recorder=recorder,
                task_root_rel=task_root_rel,
                use_git=use_git,
                active_phase_selection=None,
                enabled_pairs=enabled_pairs,
                args=args,
                resume_checkpoint=resume_checkpoint,
                use_resume_state=bool(args.resume and (resume_checkpoint is not None)),
            )
            if plan_result == "blocked":
                run_status = "blocked"
                exit_code = plan_exit
                return exit_code
            if plan_result == "failed":
                run_status = "failed"
                exit_code = plan_exit
                return exit_code

        phased_enabled = [pair for pair in ("implement", "test") if pair_by_name.get(pair) and pair_by_name[pair].enabled]
        if phased_enabled:
            active_phase_selection = resolve_active_phase_selection(
                task_dir=paths["task_dir"],
                task_id=task_id,
                request_file=run_paths["request_file"],
                task_meta_file=paths["task_meta_file"],
                phase_id=args.phase_id,
                phase_mode=args.phase_mode,
                enabled_pairs=enabled_pairs,
                resume_checkpoint=resume_checkpoint,
                is_resume=args.resume,
            )
            if args.resume:
                starting_phase_index = resolve_resume_start_phase_index(
                    active_phase_selection,
                    phased_enabled,
                    resume_checkpoint.completed_pairs_by_phase if resume_checkpoint is not None else {},
                )
            else:
                starting_phase_index = 0
            if starting_phase_index < 0:
                starting_phase_index = 0
            if starting_phase_index > len(active_phase_selection.phase_ids):
                starting_phase_index = len(active_phase_selection.phase_ids)
            persist_phase_selection(
                paths["task_meta_file"],
                active_phase_selection,
                run_id,
                phase_plan_file(paths["task_dir"]),
                current_phase_index=starting_phase_index,
            )
            if args.resume and resume_checkpoint is not None:
                phase_scope_emitted = resume_scope_matches(resume_checkpoint, active_phase_selection)
            if not phase_scope_emitted:
                recorder.emit(
                    "phase_scope_resolved",
                    phase_mode=active_phase_selection.phase_mode,
                    phase_ids=list(active_phase_selection.phase_ids),
                    explicit=active_phase_selection.explicit,
                    current_phase_index=starting_phase_index,
                )
                selection_body = (
                    f"phase_mode={active_phase_selection.phase_mode}\n"
                    f"phase_ids={','.join(active_phase_selection.phase_ids)}\n"
                    f"explicit={active_phase_selection.explicit}\n"
                    f"current_phase_index={starting_phase_index}"
                )
                append_runtime_raw_log(paths["raw_phase_log"], run_id, "phase_scope_resolved", selection_body)
                append_runtime_raw_log(run_paths["raw_phase_log"], run_id, "phase_scope_resolved", selection_body)
                phase_scope_emitted = True

            for phase_index in range(starting_phase_index, len(active_phase_selection.phase_ids)):
                current_phase = active_phase_selection.phases[phase_index]
                current_phase_selection = ResolvedPhaseSelection(
                    phase_mode=active_phase_selection.phase_mode if active_phase_selection.phase_mode == PHASE_MODE_UP_TO else PHASE_MODE_SINGLE,
                    phase_ids=(current_phase.phase_id,),
                    phases=(current_phase,),
                    explicit=active_phase_selection.explicit,
                )
                update_active_phase_index(paths["task_meta_file"], phase_index, current_phase.phase_id)
                if current_phase.phase_id not in phase_started_ids:
                    mark_phase_status(
                        paths["task_meta_file"],
                        [current_phase.phase_id],
                        PHASE_STATUS_IN_PROGRESS,
                        run_id=run_id,
                    )
                    recorder.emit(
                        "phase_started",
                        phase_id=current_phase.phase_id,
                        phase_mode=active_phase_selection.phase_mode,
                    )
                    phase_started_ids.add(current_phase.phase_id)

                for pair in phased_enabled:
                    pair_cfg = pair_by_name[pair]
                    assert pair_cfg is not None
                    if args.resume and phase_pair_completed(completed_phase_pairs, current_phase.phase_id, pair):
                        continue
                    if pair == "test" and not phase_pair_completed(completed_phase_pairs, current_phase.phase_id, "implement"):
                        fatal(
                            f"[!] FATAL: Cannot run test completion for phase {current_phase.phase_id!r} "
                            "before implement completion has been recorded for that phase."
                        )

                    result, result_exit = execute_pair_cycles(
                        pair_cfg=pair_cfg,
                        pair=pair,
                        prompt_file=paths[f"pair_{pair}"] / "prompt.md",
                        verifier_prompt_file=paths[f"pair_{pair}"] / "verifier_prompt.md",
                        criteria_file=paths[f"pair_{pair}"] / "criteria.md",
                        feedback_file=paths[f"pair_{pair}"] / "feedback.md",
                        root=root,
                        codex_command=codex_command,
                        run_id=run_id,
                        run_paths=run_paths,
                        paths=paths,
                        recorder=recorder,
                        task_root_rel=task_root_rel,
                        use_git=use_git,
                        active_phase_selection=current_phase_selection,
                        enabled_pairs=enabled_pairs,
                        args=args,
                        resume_checkpoint=resume_checkpoint,
                        use_resume_state=bool(args.resume and phase_index == starting_phase_index),
                    )
                    resume_checkpoint = None
                    if result == "blocked":
                        mark_phase_status(
                            paths["task_meta_file"],
                            [current_phase.phase_id],
                            PHASE_STATUS_BLOCKED,
                            run_id=run_id,
                            pair=pair,
                        )
                        recorder.emit(
                            "phase_blocked",
                            pair=pair,
                            phase_id=current_phase.phase_id,
                            phase_mode=active_phase_selection.phase_mode,
                        )
                        run_status = "blocked"
                        exit_code = result_exit
                        return exit_code
                    if result == "failed":
                        run_status = "failed"
                        exit_code = result_exit
                        return exit_code

                    mark_phase_pair_completed(completed_phase_pairs, current_phase.phase_id, pair)
                    if pair == "implement" and "test" in phased_enabled:
                        deferred_key = (current_phase.phase_id, pair)
                        if deferred_key not in phase_deferred_keys:
                            recorder.emit(
                                "phase_deferred",
                                pair=pair,
                                phase_mode=active_phase_selection.phase_mode,
                                phase_id=current_phase.phase_id,
                                reason="awaiting enabled test pair completion",
                            )
                            phase_deferred_keys.add(deferred_key)
                        continue
                    if pair == "test" or ("test" not in phased_enabled and pair == "implement"):
                        mark_phase_status(
                            paths["task_meta_file"],
                            [current_phase.phase_id],
                            PHASE_STATUS_COMPLETED,
                            run_id=run_id,
                            pair=pair,
                        )
                        if current_phase.phase_id not in phase_completed_ids:
                            recorder.emit(
                                "phase_completed",
                                pair=pair,
                                phase_id=current_phase.phase_id,
                                phase_mode=active_phase_selection.phase_mode,
                            )
                            phase_completed_ids.add(current_phase.phase_id)

                update_active_phase_index(
                    paths["task_meta_file"],
                    phase_index + 1,
                    active_phase_selection.phase_ids[phase_index + 1] if phase_index + 1 < len(active_phase_selection.phase_ids) else None,
                )

        append_run_log(paths["run_log"], "All enabled pairs completed", run_id=run_id)
        append_run_log(run_paths["run_log"], "All enabled pairs completed", run_id=run_id)
        if use_git:
            commit_tracked_changes(root, "superloop: successful completion", task_scoped_paths)
        print("\n[SUCCESS] All enabled pairs completed.")
        run_status = "success"
        exit_code = 0
        return exit_code

    except KeyboardInterrupt:
        print("\n[!] Interrupted by user. Shutting down gracefully...")
        run_status = "interrupted"
        exit_code = 130
        return exit_code
    except SystemExit as exc:
        if isinstance(exc.code, int):
            exit_code = exc.code
        else:
            exit_code = 1
        if run_status == "running":
            run_status = "fatal_error"
        return exit_code
    finally:
        if recorder is not None and run_paths is not None and run_id is not None and run_status != "setup":
            recorder.emit("run_finished", status=run_status, exit_code=exit_code)
            write_run_summary(run_paths["summary_file"], run_id, run_paths["events_file"])


if __name__ == "__main__":
    sys.exit(main())
