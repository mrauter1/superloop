from __future__ import annotations

from pathlib import Path

import pytest

from loop_control import (
    LoopControlParseError,
    LoopQuestion,
    PROMISE_BLOCKED,
    PROMISE_COMPLETE,
    PROMISE_INCOMPLETE,
    parse_loop_control,
)
from superloop import decide_producer_control, decide_verifier_control as decide_superloop_verifier_control

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "loop_control"


def fixture_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("fixture_name", "expected_question", "expected_promise"),
    [
        ("canonical_promise_complete.txt", None, PROMISE_COMPLETE),
        ("canonical_promise_incomplete.txt", None, PROMISE_INCOMPLETE),
        ("canonical_question.txt", LoopQuestion(text="What retention period should exports use?"), None),
        (
            "canonical_question_best_supposition.txt",
            LoopQuestion(
                text="Should the importer reject duplicate IDs?",
                best_supposition="Reject duplicates and surface a validation error.",
            ),
            None,
        ),
        ("canonical_leading_prose.txt", None, PROMISE_BLOCKED),
    ],
)
def test_parse_loop_control_canonical_fixtures(fixture_name: str, expected_question: LoopQuestion | None, expected_promise: str | None):
    control = parse_loop_control(fixture_text(fixture_name))

    assert control.source == "canonical"
    assert control.question == expected_question
    assert control.promise == expected_promise
    assert control.raw_payload is not None


@pytest.mark.parametrize(
    "fixture_name",
    [
        "canonical_multiple_blocks.txt",
        "canonical_malformed_json.txt",
        "canonical_unknown_schema.txt",
        "canonical_invalid_kind.txt",
        "canonical_invalid_promise.txt",
        "canonical_mixed_with_legacy.txt",
        "canonical_trailing_prose.txt",
    ],
)
def test_parse_loop_control_rejects_invalid_canonical_fixtures(fixture_name: str):
    with pytest.raises(LoopControlParseError):
        parse_loop_control(fixture_text(fixture_name))


@pytest.mark.parametrize(
    ("fixture_name", "expected_question", "expected_promise"),
    [
        ("legacy_question_only.txt", LoopQuestion(text="What auth mode should the service use?"), None),
        (
            "legacy_multiline_question.txt",
            LoopQuestion(text="Question: Which event source is canonical?\nBest current guess: the Kafka topic."),
            None,
        ),
        ("legacy_promise_only.txt", None, PROMISE_COMPLETE),
        ("legacy_promise_in_prose.txt", None, None),
        (
            "legacy_question_and_promise.txt",
            LoopQuestion(text="Should the CLI support dry-run output?"),
            PROMISE_INCOMPLETE,
        ),
    ],
)
def test_parse_loop_control_legacy_fixtures(fixture_name: str, expected_question: LoopQuestion | None, expected_promise: str | None):
    control = parse_loop_control(fixture_text(fixture_name))

    expected_source = "legacy" if expected_question or expected_promise else "none"
    assert control.source == expected_source
    assert control.question == expected_question
    assert control.promise == expected_promise
    assert control.raw_payload is None


def test_parse_loop_control_no_signal_fixture():
    control = parse_loop_control(fixture_text("no_control.txt"))

    assert control.source == "none"
    assert control.question is None
    assert control.promise is None
    assert control.raw_payload is None


def test_superloop_producer_promise_without_question_is_ignored():
    control = parse_loop_control(fixture_text("legacy_promise_only.txt"))

    decision = decide_producer_control(control)

    assert decision.action == "ignore_promise"


def test_superloop_producer_question_still_wins_over_final_line_legacy_promise():
    control = parse_loop_control(fixture_text("legacy_question_and_promise.txt"))

    decision = decide_producer_control(control)

    assert decision.action == "question"


def test_superloop_missing_verifier_promise_defaults_to_incomplete_with_warning():
    control = parse_loop_control(fixture_text("no_control.txt"))

    decision = decide_superloop_verifier_control(control, criteria_checked=True)

    assert decision.action == "incomplete"
    assert decision.warning == "No promise tag found, defaulted to <promise>INCOMPLETE</promise>."


def test_superloop_complete_with_unchecked_criteria_is_downgraded():
    control = parse_loop_control(fixture_text("canonical_promise_complete.txt"))

    decision = decide_superloop_verifier_control(control, criteria_checked=False)

    assert decision.action == "incomplete"
    assert decision.warning == "verifier emitted COMPLETE with unchecked criteria; downgrading to INCOMPLETE in lax guard mode."


def test_parse_loop_control_invalid_promise_error_includes_rejected_value():
    with pytest.raises(LoopControlParseError, match="not 'DONE'"):
        parse_loop_control(fixture_text("canonical_invalid_promise.txt"))
