from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CONTROL_SCHEMA_ID = "docloop.loop_control/v1"

PROMISE_COMPLETE = "COMPLETE"
PROMISE_INCOMPLETE = "INCOMPLETE"
PROMISE_BLOCKED = "BLOCKED"
PROMISE_VALUES = {PROMISE_COMPLETE, PROMISE_INCOMPLETE, PROMISE_BLOCKED}

CANONICAL_BLOCK_RE = re.compile(
    r"<loop-control>\s*(.*?)\s*</loop-control>",
    re.DOTALL | re.IGNORECASE,
)
LEGACY_QUESTION_RE = re.compile(r"<question>(.*?)</question>", re.DOTALL | re.IGNORECASE)
PROMISE_LINE_RE = re.compile(
    r"^\s*<promise>(COMPLETE|INCOMPLETE|BLOCKED)</promise>\s*$",
    re.IGNORECASE,
)
UNCHECKED_BOX_RE = re.compile(r"^- \[ \]", re.MULTILINE)


class LoopControlParseError(ValueError):
    """Raised when loop-control output is malformed or conflicting."""


@dataclass(frozen=True)
class LoopQuestion:
    text: str
    best_supposition: str | None = None


@dataclass(frozen=True)
class LoopControl:
    question: LoopQuestion | None
    promise: str | None
    source: Literal["canonical", "legacy", "none"]
    raw_payload: str | None


def last_non_empty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def parse_loop_control(stdout: str) -> LoopControl:
    canonical_matches = list(CANONICAL_BLOCK_RE.finditer(stdout))
    if len(canonical_matches) > 1:
        raise LoopControlParseError("Multiple <loop-control> blocks found.")

    if canonical_matches:
        return _parse_canonical_control(stdout, canonical_matches[0])

    return _parse_legacy_control(stdout)


def criteria_all_checked(criteria_file: Path) -> bool:
    criteria_text = criteria_file.read_text(encoding="utf-8")
    return UNCHECKED_BOX_RE.search(criteria_text) is None


def _parse_canonical_control(stdout: str, canonical_match: re.Match[str]) -> LoopControl:
    prefix = stdout[: canonical_match.start()]
    suffix = stdout[canonical_match.end() :]

    if suffix.strip():
        raise LoopControlParseError(
            "Canonical <loop-control> output must be the last non-empty block in stdout."
        )

    if LEGACY_QUESTION_RE.search(prefix):
        raise LoopControlParseError(
            "Canonical <loop-control> output cannot be combined with legacy <question> tags."
        )
    legacy_promise_match = PROMISE_LINE_RE.fullmatch(last_non_empty_line(prefix))
    if legacy_promise_match:
        raise LoopControlParseError(
            "Canonical <loop-control> output cannot be combined with legacy final-line <promise> tags."
        )

    raw_payload = canonical_match.group(1).strip()
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise LoopControlParseError(f"Invalid canonical loop-control JSON: {exc.msg}.") from exc

    if not isinstance(payload, dict):
        raise LoopControlParseError("Canonical loop-control payload must decode to a JSON object.")
    if payload.get("schema") != CONTROL_SCHEMA_ID:
        raise LoopControlParseError(
            f"Canonical loop-control schema must be {CONTROL_SCHEMA_ID!r}."
        )

    kind = payload.get("kind")
    if kind == "question":
        return _parse_canonical_question(payload, raw_payload)
    if kind == "promise":
        return _parse_canonical_promise(payload, raw_payload)
    raise LoopControlParseError("Canonical loop-control kind must be 'question' or 'promise'.")


def _parse_canonical_question(payload: dict[str, object], raw_payload: str) -> LoopControl:
    if "promise" in payload:
        raise LoopControlParseError("Canonical question payload must not include a promise field.")

    question = _require_non_empty_string(payload.get("question"), "Canonical question payload requires 'question'.")
    best_supposition = payload.get("best_supposition")
    if best_supposition is not None:
        best_supposition = _require_non_empty_string(
            best_supposition,
            "Canonical question payload best_supposition must be a non-empty string when provided.",
        )

    return LoopControl(
        question=LoopQuestion(text=question, best_supposition=best_supposition),
        promise=None,
        source="canonical",
        raw_payload=raw_payload,
    )


def _parse_canonical_promise(payload: dict[str, object], raw_payload: str) -> LoopControl:
    if "question" in payload or "best_supposition" in payload:
        raise LoopControlParseError(
            "Canonical promise payload must not include question or best_supposition fields."
        )

    promise = _require_non_empty_string(payload.get("promise"), "Canonical promise payload requires 'promise'.")
    promise = promise.upper()
    if promise not in PROMISE_VALUES:
        raise LoopControlParseError(
            f"Canonical promise must be one of {PROMISE_COMPLETE}, {PROMISE_INCOMPLETE}, or {PROMISE_BLOCKED}."
        )

    return LoopControl(
        question=None,
        promise=promise,
        source="canonical",
        raw_payload=raw_payload,
    )


def _parse_legacy_control(stdout: str) -> LoopControl:
    question_match = LEGACY_QUESTION_RE.search(stdout)
    promise_match = PROMISE_LINE_RE.fullmatch(last_non_empty_line(stdout))

    question = None
    if question_match:
        question_text = question_match.group(1).strip()
        question = LoopQuestion(text=question_text)

    promise = promise_match.group(1).upper() if promise_match else None
    if question or promise:
        return LoopControl(question=question, promise=promise, source="legacy", raw_payload=None)

    return LoopControl(question=None, promise=None, source="none", raw_payload=None)


def _require_non_empty_string(value: object, message: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LoopControlParseError(message)
    return value.strip()
