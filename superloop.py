#!/usr/bin/env python3
"""Superloop: strategy-to-execution multi-pair Codex orchestration.

Implements optional producer/verifier loops using the shared Doc-Loop loop-control
contract, with canonical <loop-control> JSON output and legacy tag compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

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

PLAN_GLOBAL_ARTIFACTS = ("criteria.md", "feedback.md", "plan.md", "phase_plan.yaml")
IMPLEMENT_PHASE_LOCAL_ARTIFACTS = ("criteria.md", "feedback.md", "implementation_notes.md")
TEST_PHASE_LOCAL_ARTIFACTS = ("criteria.md", "feedback.md", "test_strategy.md")
PAIR_ARTIFACTS = {
    "plan": ["plan.md"],
    "implement": ["implementation_notes.md"],
    "test": ["test_strategy.md"],
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
MAX_PHASE_ID_UTF8_BYTES = 96
PHASE_DIR_SAFE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
DEFAULT_CODEX_MODEL = "gpt-5.4"
DEFAULT_PAIRS = "plan,implement,test"
DEFAULT_MAX_ITERATIONS = 15
DEFAULT_PHASE_MODE = PHASE_MODE_SINGLE
DEFAULT_INTENT_MODE = "preserve"
DEFAULT_FULL_AUTO_ANSWERS = False
DEFAULT_NO_GIT = False
SUPERLOOP_CONFIG_FILENAMES = ("superloop.yaml", "superloop.config")
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
PAIR_TEMPLATE_FILES = {
    "plan": {"producer": "plan_producer.md", "verifier": "plan_verifier.md", "criteria": "plan_criteria.md"},
    "implement": {
        "producer": "implement_producer.md",
        "verifier": "implement_verifier.md",
        "criteria": "implement_criteria.md",
    },
    "test": {"producer": "test_producer.md", "verifier": "test_verifier.md", "criteria": "test_criteria.md"},
}
DECISIONS_HEADER_PREFIX = "<superloop-decisions-header "
DECISIONS_HEADER_SUFFIX = " />"
DECISIONS_VERSION = "1"
PLAN_DECISIONS_PHASE_ID = "task-global"
DECISIONS_ROLE_BY_PAIR = {
    "plan": "planner",
    "implement": "implementer",
    "test": "test_author",
}


@lru_cache(maxsize=1)
def load_pair_templates() -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    producer_templates: Dict[str, str] = {}
    verifier_templates: Dict[str, str] = {}
    criteria_templates: Dict[str, str] = {}
    for pair, role_files in PAIR_TEMPLATE_FILES.items():
        producer_path = TEMPLATES_DIR / role_files["producer"]
        verifier_path = TEMPLATES_DIR / role_files["verifier"]
        criteria_path = TEMPLATES_DIR / role_files["criteria"]
        if not producer_path.exists():
            fatal(f"[!] FATAL: Missing producer prompt template: {producer_path}")
        if not verifier_path.exists():
            fatal(f"[!] FATAL: Missing verifier prompt template: {verifier_path}")
        if not criteria_path.exists():
            fatal(f"[!] FATAL: Missing criteria template: {criteria_path}")
        producer_templates[pair] = producer_path.read_text(encoding="utf-8")
        verifier_templates[pair] = verifier_path.read_text(encoding="utf-8")
        criteria_templates[pair] = criteria_path.read_text(encoding="utf-8")
    return producer_templates, verifier_templates, criteria_templates


def pair_template_path(pair: str, role: str) -> Path:
    return TEMPLATES_DIR / PAIR_TEMPLATE_FILES[pair][role]


def rendered_pair_template(pair: str, role: str, task_root_rel: str) -> Tuple[str, str]:
    producer_templates, verifier_templates, _criteria_templates = load_pair_templates()
    template_text = producer_templates[pair] if role == "producer" else verifier_templates[pair]
    return str(pair_template_path(pair, role)), render_task_prompt(template_text, task_root_rel)



@dataclass(frozen=True)
class PairConfig:
    name: str
    enabled: bool
    max_iterations: int


@dataclass(frozen=True)
class CodexCommandConfig:
    start_command: List[str]
    resume_command: List[str]


@dataclass(frozen=True)
class ProviderConfig:
    model: str
    model_effort: Optional[str] = None


@dataclass(frozen=True)
class ProviderConfigOverride:
    model: Optional[str] = None
    model_effort: Optional[str] = None


@dataclass(frozen=True)
class RuntimeConfig:
    pairs: str
    max_iterations: int
    phase_mode: str
    intent_mode: str
    full_auto_answers: bool
    no_git: bool


@dataclass(frozen=True)
class RuntimeConfigOverride:
    pairs: Optional[str] = None
    max_iterations: Optional[int] = None
    phase_mode: Optional[str] = None
    intent_mode: Optional[str] = None
    full_auto_answers: Optional[bool] = None
    no_git: Optional[bool] = None


@dataclass(frozen=True)
class SuperloopConfigOverride:
    provider: ProviderConfigOverride = ProviderConfigOverride()
    runtime: RuntimeConfigOverride = RuntimeConfigOverride()


@dataclass(frozen=True)
class ResolvedSuperloopConfig:
    provider: ProviderConfig
    runtime: RuntimeConfig


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


@dataclass(frozen=True)
class ArtifactBundle:
    pair: str
    scope: str
    artifact_dir: Path
    criteria_file: Path
    feedback_file: Path
    artifact_files: Dict[str, Path]
    allowed_verifier_prefixes: Tuple[str, ...]
    phase_id: Optional[str] = None
    phase_dir_key: Optional[str] = None
    phase_title: Optional[str] = None


@dataclass(frozen=True)
class DecisionsBlock:
    attrs: Dict[str, str]
    start_offset: int
    header_end_offset: int
    end_offset: int
    body: str


class PhasePlanError(ValueError):
    """Raised when phase-plan state is invalid or ambiguous."""


class ConfigError(ValueError):
    """Raised when Superloop configuration is invalid or cannot be loaded."""


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


def decisions_file(task_dir: Path) -> Path:
    return task_dir / "decisions.txt"


def decisions_phase_id(pair: str, artifact_bundle: ArtifactBundle) -> str:
    if pair == "plan":
        return PLAN_DECISIONS_PHASE_ID
    if artifact_bundle.phase_id:
        return artifact_bundle.phase_id
    return IMPLICIT_PHASE_ID


def decisions_owner(pair: str) -> str:
    return DECISIONS_ROLE_BY_PAIR[pair]


def parse_decisions_headers(text: str) -> List[DecisionsBlock]:
    lines = text.splitlines(keepends=True)
    headers: List[Tuple[int, int, int, Dict[str, str]]] = []
    offset = 0
    for line in lines:
        stripped = line.rstrip("\r\n")
        if stripped.startswith(DECISIONS_HEADER_PREFIX) and stripped.endswith("/>"):
            attrs = {
                match.group(1): html.unescape(match.group(2))
                for match in re.finditer(r'([a-z_]+)="([^"]*)"', stripped)
            }
            headers.append((offset, offset + len(line), len(headers), attrs))
        offset += len(line)

    blocks: List[DecisionsBlock] = []
    for idx, (start_offset, header_end_offset, _header_idx, attrs) in enumerate(headers):
        end_offset = headers[idx + 1][0] if idx + 1 < len(headers) else len(text)
        blocks.append(
            DecisionsBlock(
                attrs=attrs,
                start_offset=start_offset,
                header_end_offset=header_end_offset,
                end_offset=end_offset,
                body=text[header_end_offset:end_offset],
            )
        )
    return blocks


def _decisions_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _next_decisions_sequence(
    decisions_path: Path,
    attr_name: str,
    *,
    matcher: Optional[Callable[[DecisionsBlock], bool]] = None,
) -> int:
    blocks = parse_decisions_headers(_decisions_text(decisions_path))
    values: List[int] = []
    for block in blocks:
        if matcher is not None and not matcher(block):
            continue
        raw_value = block.attrs.get(attr_name)
        if raw_value is None:
            continue
        try:
            values.append(int(raw_value))
        except ValueError:
            continue
    return (max(values) + 1) if values else 1


def next_decisions_block_seq(decisions_path: Path) -> int:
    return _next_decisions_sequence(decisions_path, "block_seq")


def next_decisions_qa_seq(decisions_path: Path) -> int:
    return _next_decisions_sequence(decisions_path, "qa_seq")


def next_decisions_turn_seq(decisions_path: Path, *, run_id: str, pair: str, phase_id: str) -> int:
    return _next_decisions_sequence(
        decisions_path,
        "turn_seq",
        matcher=lambda block: (
            block.attrs.get("run_id") == run_id
            and block.attrs.get("pair") == pair
            and block.attrs.get("phase_id") == phase_id
        ),
    )


def _format_decisions_header(attrs: Dict[str, object]) -> str:
    ordered_keys = (
        "version",
        "block_seq",
        "owner",
        "phase_id",
        "pair",
        "turn_seq",
        "run_id",
        "ts",
        "entry",
        "qa_seq",
        "source",
    )
    serialized: List[str] = []
    for key in ordered_keys:
        value = attrs.get(key)
        if value is None:
            continue
        serialized.append(f'{key}="{html.escape(str(value), quote=True)}"')
    return f"{DECISIONS_HEADER_PREFIX}{' '.join(serialized)}{DECISIONS_HEADER_SUFFIX}"


def _append_decisions_text(decisions_path: Path, chunk: str) -> None:
    decisions_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _decisions_text(decisions_path)
    prefix = ""
    if existing and not existing.endswith("\n"):
        prefix = "\n"
    with decisions_path.open("a", encoding="utf-8") as handle:
        handle.write(prefix + chunk)


def append_decisions_header(
    decisions_path: Path,
    *,
    owner: str,
    pair: str,
    phase_id: str,
    turn_seq: int,
    run_id: str,
    ts: Optional[str] = None,
    entry: Optional[str] = None,
    qa_seq: Optional[int] = None,
    source: Optional[str] = None,
) -> int:
    block_seq = next_decisions_block_seq(decisions_path)
    if ts is None:
        ts = datetime.now(timezone.utc).isoformat()
    header = _format_decisions_header(
        {
            "version": DECISIONS_VERSION,
            "block_seq": block_seq,
            "owner": owner,
            "phase_id": phase_id,
            "pair": pair,
            "turn_seq": turn_seq,
            "run_id": run_id,
            "ts": ts,
            "entry": entry,
            "qa_seq": qa_seq,
            "source": source,
        }
    )
    _append_decisions_text(decisions_path, f"{header}\n")
    return block_seq


def append_decisions_runtime_block(
    decisions_path: Path,
    *,
    pair: str,
    phase_id: str,
    run_id: str,
    entry: str,
    body: str,
    turn_seq: Optional[int] = None,
    qa_seq: Optional[int] = None,
    source: Optional[str] = None,
    ts: Optional[str] = None,
) -> Tuple[int, int]:
    if turn_seq is None:
        turn_seq = next_decisions_turn_seq(decisions_path, run_id=run_id, pair=pair, phase_id=phase_id)
    if qa_seq is None:
        qa_seq = next_decisions_qa_seq(decisions_path)
    append_decisions_header(
        decisions_path,
        owner="runtime",
        pair=pair,
        phase_id=phase_id,
        turn_seq=turn_seq,
        run_id=run_id,
        ts=ts,
        entry=entry,
        qa_seq=qa_seq,
        source=source,
    )
    normalized_body = body if body.endswith("\n") else f"{body}\n"
    _append_decisions_text(decisions_path, normalized_body)
    return turn_seq, qa_seq


def remove_trailing_empty_decisions_block(
    decisions_path: Path,
    *,
    owner: str,
    pair: str,
    phase_id: str,
    turn_seq: int,
    run_id: str,
) -> bool:
    text = _decisions_text(decisions_path)
    blocks = parse_decisions_headers(text)
    if not blocks:
        return False
    trailing = blocks[-1]
    if trailing.attrs.get("owner") != owner:
        return False
    if trailing.attrs.get("pair") != pair:
        return False
    if trailing.attrs.get("phase_id") != phase_id:
        return False
    if trailing.attrs.get("run_id") != run_id:
        return False
    if trailing.attrs.get("turn_seq") != str(turn_seq):
        return False
    if trailing.body.strip():
        return False
    truncate_offset = len(text[: trailing.start_offset].encode("utf-8"))
    with decisions_path.open("r+b") as handle:
        handle.truncate(truncate_offset)
    return True


def phase_plan_file(task_dir: Path) -> Path:
    return task_dir / "plan" / "phase_plan.yaml"


def authoritative_phase_plan_metadata(task_id: str, request_file: Path) -> Dict[str, object]:
    return {
        "version": PHASE_PLAN_VERSION,
        "task_id": task_id,
        "request_snapshot_ref": str(request_file),
    }


def ensure_phase_plan_scaffold(task_dir: Path, task_id: str, request_file: Path) -> Path:
    if yaml is None:
        raise PhasePlanError(
            "phase_plan.yaml cannot be scaffolded without PyYAML installed. Install dependencies from requirements.txt."
        )

    plan_path = phase_plan_file(task_dir)
    phases: object = []
    if plan_path.exists():
        try:
            existing_payload = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            existing_payload = None
        if isinstance(existing_payload, dict) and "phases" in existing_payload:
            phases = existing_payload.get("phases")

    scaffold = authoritative_phase_plan_metadata(task_id, request_file)
    scaffold["phases"] = [] if phases is None else phases
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    dump_fn = getattr(yaml, "safe_dump", None)
    if callable(dump_fn):
        serialized = dump_fn(scaffold, sort_keys=False, allow_unicode=True)
    else:
        serialized = json.dumps(scaffold, indent=2) + "\n"
    plan_path.write_text(
        serialized,
        encoding="utf-8",
    )
    return plan_path


def validate_phase_id(phase_id: str) -> str:
    normalized = phase_id.strip()
    if not normalized:
        raise PhasePlanError("phase_id must be a non-empty string.")
    if len(normalized.encode("utf-8")) > MAX_PHASE_ID_UTF8_BYTES:
        raise PhasePlanError(
            f"phase_id {normalized!r} exceeds {MAX_PHASE_ID_UTF8_BYTES} UTF-8 bytes."
        )
    return normalized


def phase_dir_key(phase_id: str) -> str:
    normalized = validate_phase_id(phase_id)
    if PHASE_DIR_SAFE_RE.fullmatch(normalized):
        return normalized
    return f"_pid-{normalized.encode('utf-8').hex()}"


def phase_artifact_dir(task_dir: Path, pair: str, phase_id: str) -> Path:
    return task_dir / pair / "phases" / phase_dir_key(phase_id)


def plan_session_file(run_dir: Path) -> Path:
    return run_dir / "sessions" / "plan.json"


def phase_session_file(run_dir: Path, phase_id: str) -> Path:
    return run_dir / "sessions" / "phases" / f"{phase_dir_key(phase_id)}.json"


def resolve_session_file(pair: str, active_phase_selection: Optional[ResolvedPhaseSelection], run_dir: Path) -> Path:
    if pair == "plan":
        return plan_session_file(run_dir)
    if pair in PHASED_PAIRS and active_phase_selection and active_phase_selection.phase_ids:
        return phase_session_file(run_dir, active_phase_selection.phase_ids[0])
    return plan_session_file(run_dir)


def parse_status_paths(status_text: str) -> Set[str]:
    """Parses git porcelain status into a set of changed repo-relative paths."""
    changed: Set[str] = set()
    for line in status_text.splitlines():
        if len(line) < 4:
            continue
        changed.add(normalize_repo_path(line[3:]))
    return changed


def superloop_repo_root() -> Path:
    return Path(__file__).resolve().parent


def discover_config_file(directory: Path) -> Optional[Path]:
    matches: List[Path] = []
    for filename in SUPERLOOP_CONFIG_FILENAMES:
        candidate = directory / filename
        if not candidate.exists():
            continue
        if not candidate.is_file():
            raise ConfigError(f"Configuration path exists but is not a file: {candidate}")
        matches.append(candidate)
    if len(matches) > 1:
        raise ConfigError(
            f"Found multiple configuration files in {directory}: "
            f"{', '.join(path.name for path in matches)}. Keep only one."
        )
    return matches[0] if matches else None


def load_superloop_config(path: Path) -> object:
    if yaml is None:
        raise ConfigError(
            f"{path} cannot be loaded without PyYAML installed. Install dependencies from requirements.txt."
        )
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} could not be parsed as YAML: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"{path} could not be read: {exc}") from exc


def _optional_config_string(raw_value: object, label: str, source: Path) -> Optional[str]:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ConfigError(f"{source}: {label} must be a non-empty string when provided.")
    return raw_value.strip()


def _optional_config_int(raw_value: object, label: str, source: Path) -> Optional[int]:
    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise ConfigError(f"{source}: {label} must be an integer when provided.")
    return raw_value


def _optional_config_bool(raw_value: object, label: str, source: Path) -> Optional[bool]:
    if raw_value is None:
        return None
    if not isinstance(raw_value, bool):
        raise ConfigError(f"{source}: {label} must be a boolean when provided.")
    return raw_value


def _format_unknown_keys(keys: Iterable[object]) -> str:
    return ", ".join(sorted(str(key) for key in keys))


def parse_superloop_config(payload: object, source: Path) -> SuperloopConfigOverride:
    if not isinstance(payload, dict):
        raise ConfigError(f"{source}: configuration must be a YAML mapping.")

    unknown_top_level = sorted(key for key in payload if key not in {"provider", "runtime"})
    if unknown_top_level:
        raise ConfigError(f"{source}: unsupported top-level keys: {_format_unknown_keys(unknown_top_level)}")

    provider_payload = payload.get("provider")
    if provider_payload is not None and not isinstance(provider_payload, dict):
        raise ConfigError(f"{source}: provider must be a mapping.")
    provider_payload = provider_payload or {}
    unknown_provider_keys = sorted(key for key in provider_payload if key not in {"model", "model_effort"})
    if unknown_provider_keys:
        raise ConfigError(f"{source}: unsupported provider keys: {_format_unknown_keys(unknown_provider_keys)}")
    provider = ProviderConfigOverride(
        model=_optional_config_string(provider_payload.get("model"), "provider.model", source),
        model_effort=_optional_config_string(provider_payload.get("model_effort"), "provider.model_effort", source),
    )

    runtime_payload = payload.get("runtime")
    if runtime_payload is not None and not isinstance(runtime_payload, dict):
        raise ConfigError(f"{source}: runtime must be a mapping.")
    runtime_payload = runtime_payload or {}
    unknown_runtime_keys = sorted(
        key
        for key in runtime_payload
        if key not in {"pairs", "max_iterations", "phase_mode", "intent_mode", "full_auto_answers", "no_git"}
    )
    if unknown_runtime_keys:
        raise ConfigError(f"{source}: unsupported runtime keys: {_format_unknown_keys(unknown_runtime_keys)}")
    phase_mode = _optional_config_string(runtime_payload.get("phase_mode"), "runtime.phase_mode", source)
    if phase_mode is not None and phase_mode not in {PHASE_MODE_SINGLE, PHASE_MODE_UP_TO}:
        raise ConfigError(f"{source}: runtime.phase_mode must be one of: {PHASE_MODE_SINGLE}, {PHASE_MODE_UP_TO}.")
    intent_mode = _optional_config_string(runtime_payload.get("intent_mode"), "runtime.intent_mode", source)
    if intent_mode is not None and intent_mode not in {"replace", "append", "preserve"}:
        raise ConfigError(f"{source}: runtime.intent_mode must be one of: replace, append, preserve.")
    runtime = RuntimeConfigOverride(
        pairs=_optional_config_string(runtime_payload.get("pairs"), "runtime.pairs", source),
        max_iterations=_optional_config_int(runtime_payload.get("max_iterations"), "runtime.max_iterations", source),
        phase_mode=phase_mode,
        intent_mode=intent_mode,
        full_auto_answers=_optional_config_bool(runtime_payload.get("full_auto_answers"), "runtime.full_auto_answers", source),
        no_git=_optional_config_bool(runtime_payload.get("no_git"), "runtime.no_git", source),
    )

    return SuperloopConfigOverride(
        provider=provider,
        runtime=runtime,
    )


def _merge_provider_config(
    *layers: ProviderConfigOverride,
    cli_model: Optional[str],
    cli_model_effort: Optional[str],
) -> ProviderConfig:
    model = DEFAULT_CODEX_MODEL
    model_effort: Optional[str] = None

    for layer in layers:
        if layer.model is not None:
            model = layer.model
        if layer.model_effort is not None:
            model_effort = layer.model_effort

    if cli_model is not None:
        model = cli_model
    if cli_model_effort is not None:
        model_effort = cli_model_effort

    return ProviderConfig(model=model, model_effort=model_effort)


def _merge_runtime_config(*layers: RuntimeConfigOverride, args: argparse.Namespace) -> RuntimeConfig:
    pairs = DEFAULT_PAIRS
    max_iterations = DEFAULT_MAX_ITERATIONS
    phase_mode = DEFAULT_PHASE_MODE
    intent_mode = DEFAULT_INTENT_MODE
    full_auto_answers = DEFAULT_FULL_AUTO_ANSWERS
    no_git = DEFAULT_NO_GIT

    for layer in layers:
        if layer.pairs is not None:
            pairs = layer.pairs
        if layer.max_iterations is not None:
            max_iterations = layer.max_iterations
        if layer.phase_mode is not None:
            phase_mode = layer.phase_mode
        if layer.intent_mode is not None:
            intent_mode = layer.intent_mode
        if layer.full_auto_answers is not None:
            full_auto_answers = layer.full_auto_answers
        if layer.no_git is not None:
            no_git = layer.no_git

    if getattr(args, "pairs", None) is not None:
        pairs = args.pairs
    if getattr(args, "max_iterations", None) is not None:
        max_iterations = args.max_iterations
    if getattr(args, "phase_mode", None) is not None:
        phase_mode = args.phase_mode
    if getattr(args, "intent_mode", None) is not None:
        intent_mode = args.intent_mode
    if getattr(args, "full_auto_answers", None) is not None:
        full_auto_answers = args.full_auto_answers
    if getattr(args, "no_git", None) is not None:
        no_git = args.no_git

    if max_iterations < 1:
        raise ConfigError("runtime.max_iterations must be >= 1.")

    return RuntimeConfig(
        pairs=pairs,
        max_iterations=max_iterations,
        phase_mode=phase_mode,
        intent_mode=intent_mode,
        full_auto_answers=full_auto_answers,
        no_git=no_git,
    )


def resolve_runtime_config(root: Path, args: argparse.Namespace) -> ResolvedSuperloopConfig:
    program_root = superloop_repo_root()
    global_config_path = discover_config_file(program_root)
    local_config_path = discover_config_file(root) if root != program_root else None

    global_override = (
        parse_superloop_config(load_superloop_config(global_config_path), global_config_path)
        if global_config_path is not None
        else SuperloopConfigOverride()
    )
    local_override = (
        parse_superloop_config(load_superloop_config(local_config_path), local_config_path)
        if local_config_path is not None
        else SuperloopConfigOverride()
    )

    return ResolvedSuperloopConfig(
        provider=_merge_provider_config(
            global_override.provider,
            local_override.provider,
            cli_model=args.model,
            cli_model_effort=args.model_effort,
        ),
        runtime=_merge_runtime_config(
            global_override.runtime,
            local_override.runtime,
            args=args,
        ),
    )



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


def allowed_verifier_paths(bundle: ArtifactBundle, task_root: str) -> List[str]:
    """Returns repo-relative paths a verifier is allowed to edit for a pair."""
    del task_root
    return list(bundle.allowed_verifier_prefixes)


def tracked_superloop_artifact_paths(task_root: str) -> List[str]:
    """Returns repo-relative task-scoped artifacts that Superloop tracks and may stage."""
    return [
        f"{task_root}/task.json",
        f"{task_root}/raw_phase_log.md",
        f"{task_root}/decisions.txt",
    ]


def verifier_exempt_runtime_artifact_paths(task_root: str) -> List[str]:
    """Returns repo-relative runtime bookkeeping paths exempt from verifier scope checks."""
    return [
        f"{task_root}/task.json",
        f"{task_root}/raw_phase_log.md",
        f"{task_root}/runs/",
    ]


def is_verifier_exempt_runtime_artifact_path(path: str, task_root: str) -> bool:
    """Returns whether a path is verifier-exempt runtime bookkeeping."""
    for artifact in verifier_exempt_runtime_artifact_paths(task_root):
        if artifact.endswith("/"):
            if path.startswith(artifact):
                return True
            continue
        if path == artifact:
            return True
    return False


def verifier_scope_violations(bundle: ArtifactBundle | str, verifier_delta: Set[str], task_root: str) -> List[str]:
    """Returns verifier writes that are outside allowed scope and not runtime bookkeeping."""
    if isinstance(bundle, str):
        legacy_prefix = f"{task_root}/{bundle}/"
        allowed = (legacy_prefix,)
    else:
        allowed = tuple(allowed_verifier_paths(bundle, task_root))
    return sorted(
        path
        for path in verifier_delta
        if not path.startswith(allowed) and not is_verifier_exempt_runtime_artifact_path(path, task_root)
    )


def tracked_superloop_paths(task_root: str, pair: Optional[str] = None) -> List[str]:
    """Returns paths that Superloop may stage/commit."""
    shared_paths = tracked_superloop_artifact_paths(task_root)
    if pair is None:
        pair_paths = [f"{task_root}/{name}/" for name in PAIR_ORDER]
    else:
        pair_paths = [f"{task_root}/{pair}/"]
    return [*shared_paths, *pair_paths]


def filter_volatile_task_run_paths(paths: Iterable[str], task_root: str) -> Set[str]:
    """Drops volatile per-run task outputs from arbitrary path sets."""
    run_prefix = f"{task_root}/runs/"
    return {path for path in paths if path and not path.startswith(run_prefix)}


def _phase_criteria_payload(
    raw_value: object,
    label: str,
    *,
    allow_missing: bool = False,
) -> Tuple[PhasePlanCriterion, ...]:
    if raw_value is None:
        if allow_missing:
            return ()
        raise PhasePlanError(f"{label} must be a non-empty list.")
    if not isinstance(raw_value, list):
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


def _phase_string_list(
    raw_value: object,
    label: str,
    *,
    allow_empty: bool = True,
    allow_missing: bool = False,
) -> Tuple[str, ...]:
    if raw_value is None:
        if allow_missing:
            return ()
        raise PhasePlanError(f"{label} must be a list.")
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
        normalized_phase_id = validate_phase_id(phase_id)
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
                out_of_scope=_phase_string_list(
                    raw_phase.get("out_of_scope"),
                    f"{label}.out_of_scope",
                    allow_missing=True,
                ),
                dependencies=_phase_string_list(
                    raw_phase.get("dependencies"),
                    f"{label}.dependencies",
                    allow_missing=True,
                ),
                acceptance_criteria=_phase_criteria_payload(
                    raw_phase.get("acceptance_criteria"),
                    f"{label}.acceptance_criteria",
                    allow_missing=True,
                ),
                deliverables=_phase_string_list(raw_phase.get("deliverables"), f"{label}.deliverables", allow_empty=False),
                risks=_phase_string_list(raw_phase.get("risks"), f"{label}.risks", allow_missing=True),
                rollback=_phase_string_list(raw_phase.get("rollback"), f"{label}.rollback", allow_missing=True),
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
    task_raw_phase_log: Path,
    run_raw_phase_log: Path,
    run_id: str,
    message: str,
    *,
    entry: str,
):
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


def try_commit_tracked_changes(root: Path, message: str, tracked_paths: Optional[Sequence[str]] = None) -> bool:
    """Best-effort commit helper that never exits the process on git errors."""
    tracked = sorted({p for p in (tracked_paths or []) if p})
    if not tracked:
        return False

    add_res = run_git(["add", "--", *tracked], cwd=root, allow_fail=True)
    if add_res.returncode != 0:
        warn(f"Unable to stage final run artifacts for commit: {add_res.stderr.strip()}")
        return False

    status_res = run_git(["status", "--porcelain", "--", *tracked], cwd=root, allow_fail=True)
    if status_res.returncode != 0:
        warn(f"Unable to inspect final run artifact changes: {status_res.stderr.strip()}")
        return False
    if not parse_status_paths(status_res.stdout):
        return False

    commit_res = run_git(["commit", "-m", message], cwd=root, allow_fail=True)
    if commit_res.returncode != 0:
        warn(f"Unable to commit final run artifacts: {commit_res.stderr.strip()}")
        return False
    return True


def check_dependencies(require_git: bool = True):
    missing = []
    if require_git and not shutil.which("git"):
        missing.append("git")
    if not shutil.which("codex"):
        missing.append("codex (install via 'npm i -g @openai/codex')")
    if missing:
        fatal(f"[!] FATAL: Missing required dependencies: {', '.join(missing)}")


def resolve_codex_exec_command(provider: ProviderConfig | str) -> CodexCommandConfig:
    if isinstance(provider, str):
        provider = ProviderConfig(model=provider)
    model = provider.model
    model_effort = provider.model_effort

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
    supports_model_effort = "--model-effort" in help_text
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
    supports_resume_model_effort = "--model-effort" in resume_text

    if not supports_json or not supports_resume_json:
        fatal("[!] FATAL CODEX ERROR: This Superloop version requires `codex exec` and `codex exec resume` support for --json.")

    provider_args = ["--model", model]
    if model_effort is not None:
        if not supports_model_effort or not supports_resume_model_effort:
            fatal(
                "[!] FATAL CODEX ERROR: Configured model_effort requires `codex exec` and "
                "`codex exec resume` support for --model-effort."
            )
        provider_args.extend(["--model-effort", model_effort])

    if supports_bypass:
        return CodexCommandConfig(
            start_command=[
                "codex",
                "exec",
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
                *provider_args,
                "-",
            ],
            resume_command=[
                "codex",
                "exec",
                "resume",
                "--json",
                "--dangerously-bypass-approvals-and-sandbox",
                *provider_args,
            ],
        )

    if supports_full_auto:
        return CodexCommandConfig(
            start_command=[
                "codex",
                "exec",
                "--json",
                "--full-auto",
                *provider_args,
                "-",
            ],
            resume_command=[
                "codex",
                "exec",
                "resume",
                "--json",
                "--full-auto",
                *provider_args,
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


def _phase_metadata_block(task_id: str, pair: str, phase_id: str, phase_title: str, scope: str) -> str:
    return (
        f"- Task ID: {task_id}\n"
        f"- Pair: {pair}\n"
        f"- Phase ID: {phase_id}\n"
        f"- Phase Directory Key: {phase_dir_key(phase_id)}\n"
        f"- Phase Title: {phase_title}\n"
        f"- Scope: {scope}\n"
    )


def _phase_artifact_template(task_id: str, pair: str, phase_id: str, phase_title: str, filename: str) -> str:
    _producer_templates, _verifier_templates, criteria_templates = load_pair_templates()
    title_map = {
        "criteria.md": "Criteria",
        "feedback.md": f"{PAIR_LABELS[pair]} Feedback",
        "implementation_notes.md": "Implementation Notes",
        "test_strategy.md": "Test Strategy",
    }
    scope = (
        "phase-local authoritative verifier artifact"
        if filename in {"criteria.md", "feedback.md"}
        else "phase-local producer artifact"
    )
    header = f"# {title_map.get(filename, filename)}\n\n"
    meta = _phase_metadata_block(task_id, pair, phase_id, phase_title, scope)
    body = ""
    if filename == "criteria.md":
        body = criteria_templates[pair].split("\n", 1)[1]
    return f"{header}{meta}\n{body}".rstrip() + "\n"


def resolve_artifact_bundle(
    *,
    root: Path,
    task_dir: Path,
    task_id: str,
    task_root_rel: str,
    pair: str,
    active_phase_selection: Optional[ResolvedPhaseSelection],
) -> ArtifactBundle:
    if pair == "plan":
        artifact_dir = task_dir / "plan"
        mapping = {name: artifact_dir / name for name in PLAN_GLOBAL_ARTIFACTS}
        return ArtifactBundle(
            pair=pair,
            scope="task-global",
            artifact_dir=artifact_dir,
            criteria_file=mapping["criteria.md"],
            feedback_file=mapping["feedback.md"],
            artifact_files=mapping,
            allowed_verifier_prefixes=(f"{task_root_rel}/plan/",),
        )
    if active_phase_selection is None or not active_phase_selection.phase_ids:
        raise PhasePlanError(f"Pair {pair!r} requires an active phase selection.")
    phase = active_phase_selection.phases[0]
    phase_id = validate_phase_id(phase.phase_id)
    key = phase_dir_key(phase_id)
    artifact_dir = task_dir / pair / "phases" / key
    names = IMPLEMENT_PHASE_LOCAL_ARTIFACTS if pair == "implement" else TEST_PHASE_LOCAL_ARTIFACTS
    mapping = {name: artifact_dir / name for name in names}
    return ArtifactBundle(
        pair=pair,
        scope="phase-local",
        artifact_dir=artifact_dir,
        criteria_file=mapping["criteria.md"],
        feedback_file=mapping["feedback.md"],
        artifact_files=mapping,
        allowed_verifier_prefixes=(f"{task_root_rel}/{pair}/phases/{key}/",),
        phase_id=phase_id,
        phase_dir_key=key,
        phase_title=phase.title,
    )


def ensure_phase_artifacts(bundle: ArtifactBundle, task_id: str) -> ArtifactBundle:
    if bundle.scope != "phase-local":
        return bundle
    assert bundle.phase_id is not None and bundle.phase_title is not None
    bundle.artifact_dir.mkdir(parents=True, exist_ok=True)
    for name, path in bundle.artifact_files.items():
        if path.exists():
            continue
        path.write_text(
            _phase_artifact_template(task_id, bundle.pair, bundle.phase_id, bundle.phase_title, name),
            encoding="utf-8",
        )
    return bundle


def ensure_workspace(
    root: Path,
    task_id: str,
    product_intent: Optional[str],
    intent_mode: str,
) -> Dict[str, Path]:
    _producer_prompts, _verifier_prompts, criteria_templates = load_pair_templates()

    super_dir = root / ".superloop"
    super_dir.mkdir(parents=True, exist_ok=True)

    tasks_dir = super_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)

    task_dir = tasks_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    task_root_rel = repo_relative_path(root, task_dir)

    raw_phase_log = task_dir / "raw_phase_log.md"
    if not raw_phase_log.exists():
        raw_phase_log.write_text("# Superloop Raw Phase Log\n", encoding="utf-8")

    shared_decisions_file = decisions_file(task_dir)
    if not shared_decisions_file.exists():
        shared_decisions_file.write_text("", encoding="utf-8")

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

        if pair == "plan":
            criteria_file = pair_dir / "criteria.md"
            if not criteria_file.exists():
                criteria_file.write_text(criteria_templates[pair], encoding="utf-8")

            feedback_file = pair_dir / "feedback.md"
            if not feedback_file.exists():
                feedback_file.write_text(f"# {PAIR_LABELS[pair]} Feedback\n", encoding="utf-8")

            for artifact_name in PAIR_ARTIFACTS[pair]:
                artifact = pair_dir / artifact_name
                if not artifact.exists():
                    artifact.write_text(f"# {artifact_name}\n", encoding="utf-8")
        else:
            (pair_dir / "phases").mkdir(parents=True, exist_ok=True)

    return {
        "super_dir": super_dir,
        "tasks_dir": tasks_dir,
        "task_dir": task_dir,
        "task_meta_file": task_meta_file,
        "task_root_rel": Path(task_root_rel),
        "task_id": task_id,
        "runs_dir": runs_dir,
        "raw_phase_log": raw_phase_log,
        "decisions_file": shared_decisions_file,
        "legacy_context_file": legacy_context_file,
        **{f"pair_{k}": v for k, v in pair_dirs.items()},
    }


def create_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{timestamp}-{uuid4().hex[:8]}"


def create_run_paths(runs_dir: Path, run_id: str, request_text: Optional[str], session_mode: str = "persistent") -> Dict[str, Path]:
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    raw_phase_log = run_dir / "raw_phase_log.md"
    raw_phase_log.write_text(f"# Superloop Raw Phase Log ({run_id})\n", encoding="utf-8")

    events_file = run_dir / "events.jsonl"
    events_file.write_text("", encoding="utf-8")

    request_file = run_dir / "request.md"
    sessions_dir = run_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    phases_sessions_dir = sessions_dir / "phases"
    phases_sessions_dir.mkdir(parents=True, exist_ok=True)
    plan_state_file = plan_session_file(run_dir)
    write_request_snapshot(request_file, request_text)
    save_session_state(plan_state_file, load_session_state(plan_state_file, session_mode))

    return {
        "run_dir": run_dir,
        "raw_phase_log": raw_phase_log,
        "events_file": events_file,
        "request_file": request_file,
        "sessions_dir": sessions_dir,
        "plan_session_file": plan_state_file,
    }


def open_existing_run_paths(
    runs_dir: Path,
    run_id: str,
) -> Dict[str, Path]:
    run_dir = runs_dir / run_id
    if not run_dir.exists() or not run_dir.is_dir():
        fatal(f"[!] FATAL: run_id not found under task runs/: {run_id}")

    raw_phase_log = run_dir / "raw_phase_log.md"
    events_file = run_dir / "events.jsonl"
    request_file = run_dir / "request.md"
    sessions_dir = run_dir / "sessions"
    phases_sessions_dir = sessions_dir / "phases"
    plan_state_file = plan_session_file(run_dir)

    if not raw_phase_log.exists():
        raw_phase_log.write_text(f"# Superloop Raw Phase Log ({run_id})\n", encoding="utf-8")
    if not events_file.exists():
        events_file.write_text("", encoding="utf-8")
    sessions_dir.mkdir(parents=True, exist_ok=True)
    phases_sessions_dir.mkdir(parents=True, exist_ok=True)

    return {
        "run_dir": run_dir,
        "raw_phase_log": raw_phase_log,
        "events_file": events_file,
        "request_file": request_file,
        "sessions_dir": sessions_dir,
        "plan_session_file": plan_state_file,
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


def extract_clarifications(run_raw_phase_log: Path) -> List[Tuple[str, str]]:
    if not run_raw_phase_log.exists():
        return []
    text = run_raw_phase_log.read_text(encoding="utf-8")
    blocks = text.split("\n\n---\n")
    clarifications: List[Tuple[str, str]] = []
    for block in blocks:
        if "entry=clarification" not in block:
            continue
        if "Question:\n" not in block or "\n\nAnswer:\n" not in block:
            continue
        body = block.split("---\n", 1)[-1]
        question, answer = body.split("\n\nAnswer:\n", 1)
        question = question.replace("Question:\n", "", 1).strip()
        clarifications.append((question, answer.strip()))
    return clarifications


def prior_phase_status_lines(events_file: Path, selected_phase_ids: Sequence[str]) -> List[str]:
    if not events_file.exists():
        return []
    allowed = set(selected_phase_ids)
    lines: List[str] = []
    for raw in events_file.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        phase_id = event.get("phase_id")
        if not isinstance(phase_id, str) or phase_id not in allowed:
            continue
        if event.get("event_type") in {"phase_started", "phase_completed", "phase_blocked", "phase_deferred"}:
            lines.append(f"{phase_id}: {event.get('event_type')}")
    return lines


def relevant_prior_artifact_paths(task_dir: Path, pair: str, prior_phase_keys: Sequence[str]) -> List[str]:
    if not prior_phase_keys:
        return []
    pair_dir = task_dir / pair / "phases"
    if not pair_dir.exists():
        return []
    repo_root = task_dir.parents[2]
    paths: List[str] = []
    for phase_key in prior_phase_keys:
        entry = pair_dir / phase_key
        if not entry.is_dir():
            continue
        for child in sorted(entry.glob("*.md")):
            paths.append(str(child.relative_to(repo_root)))
    return paths


def build_fresh_phase_bootstrap(
    *,
    request_file: Path,
    run_raw_phase_log: Path,
    events_file: Path,
    task_dir: Path,
    bundle: ArtifactBundle,
    active_phase_selection: ResolvedPhaseSelection,
    prior_phase_ids: Sequence[str],
    prior_phase_keys: Sequence[str],
) -> str:
    assert bundle.phase_dir_key is not None
    request_text = request_file.read_text(encoding="utf-8").strip()
    clarifications = extract_clarifications(run_raw_phase_log)
    clar_lines = [f"Q: {q}\nA: {a}" for q, a in clarifications] or ["(none)"]
    status_lines = prior_phase_status_lines(events_file, prior_phase_ids) or ["(none)"]
    prior_paths = relevant_prior_artifact_paths(task_dir, bundle.pair, prior_phase_keys) or ["(none)"]
    artifact_lines = [f"- {name}: {path}" for name, path in bundle.artifact_files.items()] or ["(none)"]
    bootstrap = (
        "\nINITIAL REQUEST SNAPSHOT:\n"
        f"{request_text or DEFAULT_REQUEST_TEXT}\n"
        "\nAUTHORITATIVE CLARIFICATIONS TO DATE:\n"
        + "\n".join(clar_lines)
        + "\n\nPRIOR PHASE STATUS IN THIS RUN:\n"
        + "\n".join(status_lines)
        + "\n\nRELEVANT PRIOR PHASE ARTIFACT PATHS:\n"
        + "\n".join(prior_paths)
        + "\n\n"
        + phase_prompt_context(active_phase_selection)
        + "\n\nACTIVE PHASE ARTIFACTS:\n"
        + "\n".join(artifact_lines)
    )
    return bootstrap


def build_phase_prompt(
    *,
    cwd: Path,
    template_provenance: str,
    rendered_template_text: str,
    request_file: Path,
    run_raw_phase_log: Path,
    decisions_file: Path,
    pair_name: str,
    phase_name: str,
    cycle_num: int,
    attempt_num: int,
    run_id: str,
    session_state: SessionState,
    include_request_snapshot: bool,
    artifact_bundle: Optional[ArtifactBundle] = None,
    session_file: Path,
    is_fresh_phase_thread: bool = False,
    events_file: Optional[Path] = None,
    task_dir: Optional[Path] = None,
    active_phase_selection: Optional[ResolvedPhaseSelection] = None,
    prior_phase_ids: Sequence[str] = (),
    prior_phase_keys: Sequence[str] = (),
) -> str:
    base_instructions = rendered_template_text
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
        f"AUTHORITATIVE SHARED DECISIONS FILE: {decisions_file}",
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
    if artifact_bundle is None:
        artifact_bundle = ArtifactBundle(
            pair=pair_name,
            scope="task-global",
            artifact_dir=cwd,
            criteria_file=cwd / "criteria.md",
            feedback_file=cwd / "feedback.md",
            artifact_files={},
            allowed_verifier_prefixes=(),
        )

    preamble.extend(
        [
            f"THREAD SCOPE: {'phase-local' if pair_name in PHASED_PAIRS else 'task-global'}",
            f"ARTIFACT SCOPE: {artifact_bundle.scope}",
            f"AUTHORITATIVE ACTIVE ARTIFACT DIRECTORY: {artifact_bundle.artifact_dir}",
            f"AUTHORITATIVE ACTIVE CRITERIA FILE: {artifact_bundle.criteria_file}",
            f"AUTHORITATIVE ACTIVE FEEDBACK FILE: {artifact_bundle.feedback_file}",
            f"AUTHORITATIVE ACTIVE SESSION FILE: {session_file}",
            "AUTHORITATIVE OTHER ACTIVE ARTIFACT FILES:",
            *[f"- {path}" for name, path in artifact_bundle.artifact_files.items() if name not in {"criteria.md", "feedback.md"}],
        ]
    )
    if pair_name in PHASED_PAIRS and active_phase_selection is not None and not is_fresh_phase_thread:
        preamble.extend(
            [
                "",
                phase_prompt_context(active_phase_selection),
            ]
        )
    if (
        is_fresh_phase_thread
        and pair_name in PHASED_PAIRS
        and events_file is not None
        and task_dir is not None
        and active_phase_selection is not None
    ):
        preamble.extend(
            [
                "",
                build_fresh_phase_bootstrap(
                    request_file=request_file,
                    run_raw_phase_log=run_raw_phase_log,
                    events_file=events_file,
                    task_dir=task_dir,
                    bundle=artifact_bundle,
                    active_phase_selection=active_phase_selection,
                    prior_phase_ids=prior_phase_ids,
                    prior_phase_keys=prior_phase_keys,
                ),
            ]
        )
    return "\n".join(preamble) + "\n\nFollow the prompt rules exactly.\n\n" + base_instructions


def run_codex_phase(
    codex_command: CodexCommandConfig,
    cwd: Path,
    template_provenance: str,
    rendered_template_text: str,
    phase_name: str,
    pair_name: str,
    cycle_num: int,
    attempt_num: int,
    run_id: str,
    request_file: Path,
    session_file: Path,
    artifact_bundle: ArtifactBundle,
    run_raw_phase_log: Path,
    raw_phase_log: Path,
    events_file: Path,
    task_dir: Path,
    decisions_file: Path,
    active_phase_selection: Optional[ResolvedPhaseSelection] = None,
    prior_phase_ids: Sequence[str] = (),
    prior_phase_keys: Sequence[str] = (),
) -> str:
    session_state = load_session_state(session_file, "persistent")
    session_state.mode = "persistent"
    include_request_snapshot = session_state.thread_id is None
    prompt_payload = build_phase_prompt(
        cwd=cwd,
        template_provenance=template_provenance,
        rendered_template_text=rendered_template_text,
        request_file=request_file,
        run_raw_phase_log=run_raw_phase_log,
        decisions_file=decisions_file,
        pair_name=pair_name,
        phase_name=phase_name,
        cycle_num=cycle_num,
        attempt_num=attempt_num,
        run_id=run_id,
        session_state=session_state,
        include_request_snapshot=include_request_snapshot,
        artifact_bundle=artifact_bundle,
        session_file=session_file,
        is_fresh_phase_thread=include_request_snapshot and pair_name in PHASED_PAIRS,
        events_file=events_file,
        task_dir=task_dir,
        active_phase_selection=active_phase_selection,
        prior_phase_ids=prior_phase_ids,
        prior_phase_keys=prior_phase_keys,
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
        f"mode={command_mode}\ntemplate={template_provenance}",
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
        f"mode={command_mode}\ntemplate={template_provenance}",
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
    if control.question.best_supposition and not re.search(
        r"(?mi)^\s*Best supposition\s*:",
        control.question.text,
    ):
        return (
            f"{control.question.text}\n"
            f"Best supposition: {control.question.best_supposition}"
        )
    return control.question.text


def build_loop_control_retry_feedback(pair_name: str, phase_name: str, error: str) -> str:
    return (
        "Loop-control parse feedback:\n"
        f"The previous {pair_name} {phase_name} response could not be parsed: {error}\n"
        "Retry this phase once now. Preserve the intended response, but fix the loop-control output so it follows the required contract exactly."
    )


def set_pending_session_note(session_file: Path, note: str) -> None:
    session_state = load_session_state(session_file, "persistent")
    session_state.pending_clarification_note = note
    save_session_state(session_file, session_state)


def retry_phase_after_parse_error(
    *,
    phase_name: str,
    pair: str,
    cycle_num: int,
    attempt_num: int,
    feedback_note: str,
    session_file: Path,
    run_id: str,
    run_paths: Dict[str, Path],
    paths: Dict[str, Path],
    recorder: EventRecorder,
    active_phase_selection: Optional[ResolvedPhaseSelection],
    codex_command: CodexCommandConfig,
    root: Path,
    template_provenance: str,
    template_text: str,
    artifact_bundle: ArtifactBundle,
    prior_phase_ids: Sequence[str],
    prior_phase_keys: Sequence[str],
) -> str:
    warn(
        f"{pair} {phase_name} emitted malformed or conflicting loop-control output; retrying once with parse feedback."
    )
    append_runtime_raw_log(
        paths["raw_phase_log"],
        run_id,
        "loop_control_retry",
        feedback_note,
        pair=pair,
        phase=phase_name,
        cycle=cycle_num,
        attempt=attempt_num,
    )
    append_runtime_raw_log(
        run_paths["raw_phase_log"],
        run_id,
        "loop_control_retry",
        feedback_note,
        pair=pair,
        phase=phase_name,
        cycle=cycle_num,
        attempt=attempt_num,
    )
    set_pending_session_note(session_file, feedback_note)
    retry_stdout = run_codex_phase(
        codex_command,
        root,
        template_provenance,
        template_text,
        phase_name,
        pair,
        cycle_num,
        attempt_num,
        run_id,
        run_paths["request_file"],
        session_file,
        artifact_bundle,
        run_paths["raw_phase_log"],
        paths["raw_phase_log"],
        run_paths["events_file"],
        paths["task_dir"],
        paths["decisions_file"],
        active_phase_selection=active_phase_selection if pair in PHASED_PAIRS else None,
        prior_phase_ids=prior_phase_ids,
        prior_phase_keys=prior_phase_keys,
    )
    recorder.emit(
        "phase_finished",
        pair=pair,
        phase=phase_name,
        cycle=cycle_num,
        attempt=attempt_num,
        empty_output=(not retry_stdout.strip()),
        phase_id=active_phase_selection.phase_ids[0] if active_phase_selection else None,
    )
    if not retry_stdout.strip():
        recorder.emit(
            "phase_output_empty",
            pair=pair,
            phase=phase_name,
            cycle=cycle_num,
            attempt=attempt_num,
        )
        warn(f"{pair} {phase_name} returned empty stdout (cycle {cycle_num}, attempt {attempt_num}) on retry.")
    return retry_stdout


def parse_phase_control(
    stdout: str,
    phase_name: str,
    pair_name: str,
    *,
    retry_once: Optional[Callable[[str], str]] = None,
) -> LoopControl:
    try:
        return parse_loop_control(stdout)
    except LoopControlParseError as exc:
        if retry_once is not None:
            retry_stdout = retry_once(build_loop_control_retry_feedback(pair_name, phase_name, str(exc)))
            try:
                return parse_loop_control(retry_stdout)
            except LoopControlParseError as retry_exc:
                fatal(
                    f"[!] {pair_name} {phase_name} emitted malformed or conflicting loop-control output after one retry: {retry_exc}"
                )
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
    decisions_path: Path,
    session_file: Path,
    pair: str,
    phase_id: str,
    phase: str,
    cycle: int,
    attempt: int,
    question: str,
    answer: str,
    run_id: str,
    source: str,
    turn_seq: Optional[int] = None,
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
    turn_seq, qa_seq = append_decisions_runtime_block(
        decisions_path,
        pair=pair,
        phase_id=phase_id,
        run_id=run_id,
        entry="questions",
        body=question,
        turn_seq=turn_seq,
    )
    append_decisions_runtime_block(
        decisions_path,
        pair=pair,
        phase_id=phase_id,
        run_id=run_id,
        entry="answers",
        body=answer,
        turn_seq=turn_seq,
        qa_seq=qa_seq,
        source=source,
    )
    session_state = load_session_state(session_file, "persistent")
    session_state.pending_clarification_note = note
    save_session_state(session_file, session_state)
    return note
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
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
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
    artifact_bundle: ArtifactBundle,
    session_file: Path,
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
    prior_phase_ids: Sequence[str] = (),
    prior_phase_keys: Sequence[str] = (),
) -> Tuple[str, int]:
    print(f"\n===== Pair: {PAIR_LABELS[pair]} =====")
    producer_template_provenance, producer_template_text = rendered_pair_template(pair, "producer", task_root_rel)
    verifier_template_provenance, verifier_template_text = rendered_pair_template(pair, "verifier", task_root_rel)
    recorder.emit(
        "pair_started",
        pair=pair,
        phase_id=active_phase_selection.phase_ids[0] if active_phase_selection else None,
    )

    cycle = 0
    attempt_counts: Dict[int, int] = {}
    active_phase_id = artifact_bundle.phase_id if artifact_bundle.scope == "phase-local" else None
    ledger_phase_id = decisions_phase_id(pair, artifact_bundle)
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

        producer_turn_seq = next_decisions_turn_seq(
            paths["decisions_file"],
            run_id=run_id,
            pair=pair,
            phase_id=ledger_phase_id,
        )
        append_decisions_header(
            paths["decisions_file"],
            owner=decisions_owner(pair),
            pair=pair,
            phase_id=ledger_phase_id,
            turn_seq=producer_turn_seq,
            run_id=run_id,
        )
        producer_baseline = phase_snapshot_ref(root) if use_git else None

        try:
            producer_stdout = run_codex_phase(
                codex_command,
                root,
                producer_template_provenance,
                producer_template_text,
                "producer",
                pair,
                cycle_num,
                attempt_num,
                run_id,
                run_paths["request_file"],
                session_file,
                artifact_bundle,
                run_paths["raw_phase_log"],
                paths["raw_phase_log"],
                run_paths["events_file"],
                paths["task_dir"],
                paths["decisions_file"],
                active_phase_selection=active_phase_selection if pair in PHASED_PAIRS else None,
                prior_phase_ids=prior_phase_ids,
                prior_phase_keys=prior_phase_keys,
            )
        except BaseException:
            remove_trailing_empty_decisions_block(
                paths["decisions_file"],
                owner=decisions_owner(pair),
                pair=pair,
                phase_id=ledger_phase_id,
                turn_seq=producer_turn_seq,
                run_id=run_id,
            )
            raise
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

        def retry_producer_parse_once(feedback_note: str) -> str:
            return retry_phase_after_parse_error(
                phase_name="producer",
                pair=pair,
                cycle_num=cycle_num,
                attempt_num=attempt_num,
                feedback_note=feedback_note,
                session_file=session_file,
                run_id=run_id,
                run_paths=run_paths,
                paths=paths,
                recorder=recorder,
                active_phase_selection=active_phase_selection,
                codex_command=codex_command,
                root=root,
                template_provenance=producer_template_provenance,
                template_text=producer_template_text,
                artifact_bundle=artifact_bundle,
                prior_phase_ids=prior_phase_ids,
                prior_phase_keys=prior_phase_keys,
            )

        producer_control = parse_phase_control(
            producer_stdout,
            "producer",
            pair,
            retry_once=retry_producer_parse_once,
        )
        producer_decision = decide_producer_control(producer_control)
        producer_delta = (
            filter_volatile_task_run_paths(changed_paths_from_snapshot(root, producer_baseline), task_root_rel)
            if use_git
            else set()
        )
        remove_trailing_empty_decisions_block(
            paths["decisions_file"],
            owner=decisions_owner(pair),
            pair=pair,
            phase_id=ledger_phase_id,
            turn_seq=producer_turn_seq,
            run_id=run_id,
        )

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
                paths["decisions_file"],
                session_file,
                pair,
                ledger_phase_id,
                "producer",
                cycle_num,
                attempt_num,
                producer_question,
                answer,
                run_id,
                answer_source,
                turn_seq=producer_turn_seq,
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
            verifier_template_provenance,
            verifier_template_text,
            "verifier",
            pair,
            cycle_num,
            attempt_num,
            run_id,
            run_paths["request_file"],
            session_file,
            artifact_bundle,
            run_paths["raw_phase_log"],
            paths["raw_phase_log"],
            run_paths["events_file"],
            paths["task_dir"],
            paths["decisions_file"],
            active_phase_selection=active_phase_selection if pair in PHASED_PAIRS else None,
            prior_phase_ids=prior_phase_ids,
            prior_phase_keys=prior_phase_keys,
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

        def retry_verifier_parse_once(feedback_note: str) -> str:
            return retry_phase_after_parse_error(
                phase_name="verifier",
                pair=pair,
                cycle_num=cycle_num,
                attempt_num=attempt_num,
                feedback_note=feedback_note,
                session_file=session_file,
                run_id=run_id,
                run_paths=run_paths,
                paths=paths,
                recorder=recorder,
                active_phase_selection=active_phase_selection,
                codex_command=codex_command,
                root=root,
                template_provenance=verifier_template_provenance,
                template_text=verifier_template_text,
                artifact_bundle=artifact_bundle,
                prior_phase_ids=prior_phase_ids,
                prior_phase_keys=prior_phase_keys,
            )

        verifier_control = parse_phase_control(
            verifier_stdout,
            "verifier",
            pair,
            retry_once=retry_verifier_parse_once,
        )
        verifier_decision = decide_verifier_control(
            verifier_control,
            criteria_checked=criteria_all_checked(artifact_bundle.criteria_file),
        )
        verifier_delta = (
            filter_volatile_task_run_paths(changed_paths_from_snapshot(root, verifier_baseline), task_root_rel)
            if use_git
            else set()
        )

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
                paths["decisions_file"],
                session_file,
                pair,
                ledger_phase_id,
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

        violations = verifier_scope_violations(artifact_bundle, verifier_delta, task_root_rel) if use_git else []
        if use_git and violations:
            preview = ", ".join(violations[:8])
            if len(violations) > 8:
                preview += ", ..."
            warn(
                f"{pair} verifier edited files outside recommended scope ({artifact_bundle.artifact_dir}): {preview}. Continuing in lax guard mode."
            )

        if verifier_control.promise is None:
            recorder.emit("missing_promise_default", pair=pair, cycle=cycle_num, attempt=attempt_num)
            with artifact_bundle.feedback_file.open("a", encoding="utf-8") as f:
                f.write(
                    f"\n\n## System Warning (cycle {cycle_num})\n"
                    f"{verifier_decision.warning}\n"
                )
            verifier_delta.add(repo_relative_path(root, artifact_bundle.feedback_file))

        if verifier_control.promise == PROMISE_COMPLETE and verifier_decision.warning:
            warn(f"{pair} {verifier_decision.warning}")
            verifier_delta.add(repo_relative_path(root, artifact_bundle.feedback_file))

        if verifier_decision.action == "complete":
            print(f"[SUCCESS] Pair `{pair}` completed.")
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

    recorder.emit("pair_failed", pair=pair)
    if use_git:
        commit_paths(root, f"superloop: failed ({pair} max iterations)", pair_tracked)
    print(f"[FAILED] Pair `{pair}` reached max iterations without COMPLETE.", file=sys.stderr)
    return "failed", 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Superloop: optional strategy-to-execution Codex loop orchestration")
    parser.add_argument("--pairs", type=str, default=None, help="Comma list from: plan,implement,test")
    parser.add_argument("--phase-id", type=str, help="Explicit phase id for implement/test execution when phase_plan.yaml exists")
    parser.add_argument(
        "--phase-mode",
        choices=[PHASE_MODE_SINGLE, PHASE_MODE_UP_TO],
        default=None,
        help="Phase targeting mode for implement/test execution",
    )
    parser.add_argument("--max-iterations", type=int, default=None, help="Maximum verifier cycles per enabled pair")
    parser.add_argument("--model", type=str, default=None, help="Codex model override")
    parser.add_argument("--model-effort", type=str, default=None, help="Codex model effort override")
    parser.add_argument("--workspace", type=str, default=".", help="Repository/workspace root")
    parser.add_argument("--intent", type=str, help="Optional initial product intent text")
    parser.add_argument("--task-id", type=str, help="Task workspace id/slug under .superloop/tasks")
    parser.add_argument(
        "--intent-mode",
        choices=["replace", "append", "preserve"],
        default=None,
        help="How --intent updates an existing task context",
    )
    parser.add_argument("--resume", action="store_true", help="Resume from an existing task/run state")
    parser.add_argument("--run-id", type=str, help="Run ID under .superloop/tasks/<task-id>/runs")
    parser.add_argument("--list-tasks", action="store_true", help="List existing .superloop task IDs and exit")
    parser.add_argument(
        "--full-auto-answers",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Auto-answer agent questions using an extra Codex pass",
    )
    parser.add_argument(
        "--no-git",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Do not initialize git or create git commits/checkpoints",
    )
    args = parser.parse_args()

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

    tasks_dir = root / ".superloop" / "tasks"

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
    try:
        runtime_config = resolve_runtime_config(root, args)
    except ConfigError as exc:
        fatal(f"[!] FATAL CONFIG ERROR: {exc}")
    args.pairs = runtime_config.runtime.pairs
    args.max_iterations = runtime_config.runtime.max_iterations
    args.phase_mode = runtime_config.runtime.phase_mode
    args.intent_mode = runtime_config.runtime.intent_mode
    args.full_auto_answers = runtime_config.runtime.full_auto_answers
    args.no_git = runtime_config.runtime.no_git
    use_git = not args.no_git
    if use_git and not shutil.which("git"):
        warn("git is not installed; forcing --no-git mode.")
        use_git = False
    check_dependencies(require_git=use_git)
    if args.run_id and not args.resume:
        fatal("[!] FATAL: --run-id requires --resume.")
    codex_command = resolve_codex_exec_command(runtime_config.provider)
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
                paths["raw_phase_log"],
                run_paths["raw_phase_log"],
                run_id,
                request_notice,
                entry="request_recovery",
            )
        resume_checkpoint = load_resume_checkpoint(run_paths["events_file"], enabled_pairs)
        recorder = EventRecorder(run_id=run_id, events_file=run_paths["events_file"], sequence=resume_checkpoint.last_sequence)
        if run_paths["plan_session_file"].exists():
            session_state = load_session_state(run_paths["plan_session_file"], "persistent")
            session_state.mode = "persistent"
        else:
            session_state = SessionState(
                mode="persistent",
                thread_id=None,
                pending_clarification_note=None,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            save_session_state(run_paths["plan_session_file"], session_state)
        if not session_state.thread_id:
            session_notice = "No stored Codex thread id is available; resuming with a new conversation for the next phase."
            warn(session_notice)
            append_runtime_notice(
                paths["raw_phase_log"],
                run_paths["raw_phase_log"],
                run_id,
                session_notice,
                entry="session_recovery",
            )
            save_session_state(run_paths["plan_session_file"], session_state)
    else:
        run_id = create_run_id()
        run_paths = create_run_paths(paths["runs_dir"], run_id, resolved_request_text, session_mode="persistent")
        recorder = EventRecorder(run_id=run_id, events_file=run_paths["events_file"])
        session_state = load_session_state(run_paths["plan_session_file"], "persistent")
    run_status = "running"

    if use_git and not args.resume:
        commit_tracked_changes(root, "superloop: baseline", task_scoped_paths)

    print("\n[+] Starting Superloop")
    print(f"[*] Workspace root: {root}")
    print(f"[*] Task ID: {task_id}")
    print(f"[*] Task root: {task_root_rel}")
    print(f"[*] Enabled pairs: {', '.join(enabled_pairs)}")
    print(f"[*] Run ID: {run_id}")
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
            ensure_phase_plan_scaffold(paths["task_dir"], task_id, run_paths["request_file"])
            plan_bundle = resolve_artifact_bundle(
                root=root,
                task_dir=paths["task_dir"],
                task_id=task_id,
                task_root_rel=task_root_rel,
                pair="plan",
                active_phase_selection=None,
            )
            plan_result, plan_exit = execute_pair_cycles(
                pair_cfg=plan_cfg,
                pair="plan",
                artifact_bundle=plan_bundle,
                session_file=run_paths["plan_session_file"],
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
                        artifact_bundle=ensure_phase_artifacts(
                            resolve_artifact_bundle(
                                root=root,
                                task_dir=paths["task_dir"],
                                task_id=task_id,
                                task_root_rel=task_root_rel,
                                pair=pair,
                                active_phase_selection=current_phase_selection,
                            ),
                            task_id,
                        ),
                        session_file=resolve_session_file(pair, current_phase_selection, run_paths["run_dir"]),
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
                        prior_phase_ids=active_phase_selection.phase_ids[:phase_index],
                        prior_phase_keys=tuple(
                            phase_dir_key(phase_id) for phase_id in active_phase_selection.phase_ids[:phase_index]
                        ),
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
            if use_git:
                try_commit_tracked_changes(
                    root,
                    f"superloop: finalize run artifacts ({run_status})",
                    task_scoped_paths,
                )


if __name__ == "__main__":
    sys.exit(main())
