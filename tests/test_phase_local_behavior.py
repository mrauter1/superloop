from __future__ import annotations

import json
from pathlib import Path

import pytest

from loop_control import criteria_all_checked
from superloop import (
    ArtifactBundle,
    PHASE_MODE_SINGLE,
    PhasePlan,
    PhasePlanCriterion,
    PhasePlanPhase,
    ResolvedPhaseSelection,
    append_clarification,
    build_phase_prompt,
    create_run_paths,
    ensure_phase_artifacts,
    ensure_workspace,
    extract_clarifications,
    filter_volatile_task_run_paths,
    phase_dir_key,
    phase_session_file,
    plan_session_file,
    prior_phase_status_lines,
    resolve_artifact_bundle,
    resolve_session_file,
    verifier_scope_violations,
)


def _selection(phase_id: str = "phase-1") -> ResolvedPhaseSelection:
    phase = PhasePlanPhase(
        phase_id=phase_id,
        title="Phase 1",
        objective="obj",
        in_scope=("x",),
        out_of_scope=(),
        dependencies=(),
        acceptance_criteria=(PhasePlanCriterion(id="AC-1", text="done"),),
        deliverables=("code",),
        risks=(),
        rollback=(),
        status="planned",
    )
    return ResolvedPhaseSelection(phase_mode=PHASE_MODE_SINGLE, phase_ids=(phase_id,), phases=(phase,), explicit=True)


def test_criteria_all_checked_indented_and_unindented(tmp_path: Path):
    f = tmp_path / "criteria.md"
    f.write_text("- [ ] a\n", encoding="utf-8")
    assert criteria_all_checked(f) is False
    f.write_text("  - [ ] indented\n", encoding="utf-8")
    assert criteria_all_checked(f) is False
    f.write_text("- [x] done\n  - [x] done\n", encoding="utf-8")
    assert criteria_all_checked(f) is True


def test_phase_dir_key_behavior_and_validation():
    assert phase_dir_key("phase-1") == "phase-1"
    assert phase_dir_key("Phase One") == "_pid-5068617365204f6e65"
    assert phase_dir_key("ß") == "_pid-c39f"
    assert phase_dir_key("Phase One") == phase_dir_key("Phase One")
    assert phase_dir_key("A") != phase_dir_key("B")


def test_phase_id_over_96_utf8_bytes_rejected():
    import pytest

    with pytest.raises(Exception):
        phase_dir_key("é" * 49)


def test_workspace_and_lazy_phase_artifacts(tmp_path: Path):
    paths = ensure_workspace(tmp_path, "task-1", "intent", "replace")
    assert (paths["pair_implement"] / "phases").is_dir()
    assert (paths["pair_test"] / "phases").is_dir()
    assert not (paths["pair_implement"] / "criteria.md").exists()
    selection = _selection()
    bundle = resolve_artifact_bundle(
        root=tmp_path,
        task_dir=paths["task_dir"],
        task_id="task-1",
        task_root_rel=str(paths["task_root_rel"]),
        pair="implement",
        active_phase_selection=selection,
    )
    ensure_phase_artifacts(bundle, "task-1")
    assert bundle.criteria_file.exists()
    before = bundle.criteria_file.read_text(encoding="utf-8")
    bundle.criteria_file.write_text("changed\n", encoding="utf-8")
    ensure_phase_artifacts(bundle, "task-1")
    assert bundle.criteria_file.read_text(encoding="utf-8") == "changed\n"
    assert before


def test_session_resolution_paths(tmp_path: Path):
    run = create_run_paths(tmp_path, "run-1", "req")
    assert "session_file" not in run
    sel_a = _selection("phase-a")
    sel_b = _selection("phase-b")
    assert plan_session_file(run["run_dir"]) == run["plan_session_file"]
    a_implement = resolve_session_file("implement", sel_a, run["run_dir"])
    a_test = resolve_session_file("test", sel_a, run["run_dir"])
    b_implement = resolve_session_file("implement", sel_b, run["run_dir"])
    assert a_implement == a_test
    assert a_implement != b_implement
    assert a_implement == phase_session_file(run["run_dir"], "phase-a")


def test_append_clarification_persists_to_phase_session_only(tmp_path: Path):
    run = create_run_paths(tmp_path, "run-clarify", "req")
    task_raw_log = tmp_path / "task_raw_phase_log.md"
    task_raw_log.write_text("# Task Raw\n", encoding="utf-8")

    phase_file = phase_session_file(run["run_dir"], "phase-a")
    append_clarification(
        run["raw_phase_log"],
        task_raw_log,
        phase_file,
        pair="implement",
        phase="producer",
        cycle=1,
        attempt=1,
        question="Question text",
        answer="Approved answer",
        run_id="run-clarify",
        source="human",
    )

    phase_payload = json.loads(phase_file.read_text(encoding="utf-8"))
    plan_payload = json.loads(run["plan_session_file"].read_text(encoding="utf-8"))
    assert "Approved answer" in phase_payload["pending_clarification_note"]
    assert plan_payload["pending_clarification_note"] is None


def test_clarification_extraction_and_status_lines(tmp_path: Path):
    raw = tmp_path / "raw_phase_log.md"
    raw.write_text(
        """# Raw\n\n---\nrun_id=r | entry=clarification\n---\nQuestion:\nQ1\n\nAnswer:\nA1\n\n---\nrun_id=r | entry=clarification\n---\nQuestion:\nQ2\n\nAnswer:\nA2\n""",
        encoding="utf-8",
    )
    assert extract_clarifications(raw) == [("Q1", "A1"), ("Q2", "A2")]

    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps({"event_type": "phase_started", "phase_id": "phase-a"}) + "\n"
        + json.dumps({"event_type": "phase_completed", "phase_id": "phase-a"}) + "\n"
        + json.dumps({"event_type": "phase_started", "phase_id": "phase-b"}) + "\n",
        encoding="utf-8",
    )
    lines = prior_phase_status_lines(events, ("phase-a", "phase-b"))
    assert lines == ["phase-a: phase_started", "phase-a: phase_completed", "phase-b: phase_started"]


def test_prompt_bootstrap_only_for_fresh_phase_thread(tmp_path: Path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Prompt\n", encoding="utf-8")
    request_file = tmp_path / "request.md"
    request_file.write_text("Request\n", encoding="utf-8")
    run_raw = tmp_path / "raw.md"
    run_raw.write_text("# raw\n", encoding="utf-8")
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    bundle = ArtifactBundle(
        pair="implement",
        scope="phase-local",
        artifact_dir=tmp_path / ".superloop" / "tasks" / "task" / "implement" / "phases" / "phase-b",
        criteria_file=tmp_path / "criteria.md",
        feedback_file=tmp_path / "feedback.md",
        artifact_files={
            "criteria.md": tmp_path / "criteria.md",
            "feedback.md": tmp_path / "feedback.md",
            "implementation_notes.md": tmp_path / "implementation_notes.md",
        },
        allowed_verifier_prefixes=(".superloop/tasks/t/implement/phases/phase-a/",),
        phase_id="phase-b",
        phase_dir_key="phase-b",
        phase_title="Phase B",
    )
    task_dir = tmp_path / ".superloop" / "tasks" / "task"
    prior_phase_dir = task_dir / "implement" / "phases" / "phase-a"
    prior_phase_dir.mkdir(parents=True, exist_ok=True)
    (prior_phase_dir / "implementation_notes.md").write_text("Prior notes\n", encoding="utf-8")
    sel = _selection("phase-b")
    events.write_text(
        json.dumps({"event_type": "phase_started", "phase_id": "phase-a"}) + "\n"
        + json.dumps({"event_type": "phase_completed", "phase_id": "phase-a"}) + "\n"
        + json.dumps({"event_type": "phase_started", "phase_id": "phase-b"}) + "\n",
        encoding="utf-8",
    )
    fresh = build_phase_prompt(
        cwd=tmp_path,
        prompt_file=prompt_file,
        request_file=request_file,
        run_raw_phase_log=run_raw,
        pair_name="implement",
        phase_name="producer",
        cycle_num=1,
        attempt_num=1,
        run_id="run",
        session_state=type("S", (), {"thread_id": None, "pending_clarification_note": None})(),
        include_request_snapshot=True,
        artifact_bundle=bundle,
        session_file=tmp_path / "sess.json",
        is_fresh_phase_thread=True,
        events_file=events,
        task_dir=task_dir,
        active_phase_selection=sel,
        prior_phase_ids=("phase-a",),
        prior_phase_keys=("phase-a",),
    )
    resumed = build_phase_prompt(
        cwd=tmp_path,
        prompt_file=prompt_file,
        request_file=request_file,
        run_raw_phase_log=run_raw,
        pair_name="implement",
        phase_name="producer",
        cycle_num=1,
        attempt_num=1,
        run_id="run",
        session_state=type("S", (), {"thread_id": "t", "pending_clarification_note": None})(),
        include_request_snapshot=False,
        artifact_bundle=bundle,
        session_file=tmp_path / "sess.json",
        is_fresh_phase_thread=False,
        events_file=events,
        task_dir=task_dir,
        active_phase_selection=sel,
    )
    expected_sections = [
        "INITIAL REQUEST SNAPSHOT:",
        "AUTHORITATIVE CLARIFICATIONS TO DATE:",
        "PRIOR PHASE STATUS IN THIS RUN:",
        "RELEVANT PRIOR PHASE ARTIFACT PATHS:",
        "ACTIVE PHASE EXECUTION CONTRACT:",
        "ACTIVE PHASE ARTIFACTS:",
    ]
    positions = [fresh.index(section) for section in expected_sections]
    assert positions == sorted(positions)
    assert "phase-a: phase_started" in fresh
    assert "phase-a: phase_completed" in fresh
    assert ".superloop/tasks/task/implement/phases/phase-a/implementation_notes.md" in fresh
    assert "session.json" not in fresh
    assert fresh.count("ACTIVE PHASE EXECUTION CONTRACT:") == 1
    assert "AUTHORITATIVE CLARIFICATIONS TO DATE:" not in resumed
    assert "ACTIVE PHASE EXECUTION CONTRACT:" in resumed
    assert "session.json" not in resumed


def test_fresh_phase_bootstrap_does_not_enforce_size_cap(tmp_path: Path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Prompt\n", encoding="utf-8")
    request_file = tmp_path / "request.md"
    request_file.write_text("Request\n", encoding="utf-8")
    run_raw = tmp_path / "raw.md"
    run_raw.write_text("# raw\n", encoding="utf-8")
    events = tmp_path / "events.jsonl"
    events.write_text("", encoding="utf-8")
    task_dir = tmp_path / ".superloop" / "tasks" / "task"
    bundle = ArtifactBundle(
        pair="implement",
        scope="phase-local",
        artifact_dir=task_dir / "implement" / "phases" / "phase-b",
        criteria_file=tmp_path / "criteria.md",
        feedback_file=tmp_path / "feedback.md",
        artifact_files={"implementation_notes.md": tmp_path / "implementation_notes.md"},
        allowed_verifier_prefixes=(".superloop/tasks/task/implement/phases/phase-b/",),
        phase_id="phase-b",
        phase_dir_key="phase-b",
        phase_title="Phase B",
    )
    fresh = build_phase_prompt(
        cwd=tmp_path,
        prompt_file=prompt_file,
        request_file=request_file,
        run_raw_phase_log=run_raw,
        pair_name="implement",
        phase_name="producer",
        cycle_num=1,
        attempt_num=1,
        run_id="run",
        session_state=type("S", (), {"thread_id": None, "pending_clarification_note": None})(),
        include_request_snapshot=True,
        artifact_bundle=bundle,
        session_file=tmp_path / "sess.json",
        is_fresh_phase_thread=True,
        events_file=events,
        task_dir=task_dir,
        active_phase_selection=_selection("phase-b"),
        prior_phase_ids=("phase-a",),
        prior_phase_keys=("phase-a",),
    )
    assert "INITIAL REQUEST SNAPSHOT:" in fresh


def test_verifier_scope_phase_local_allows_active_phase_only():
    bundle = ArtifactBundle(
        pair="implement",
        scope="phase-local",
        artifact_dir=Path(".superloop/tasks/task/implement/phases/a"),
        criteria_file=Path("x"),
        feedback_file=Path("y"),
        artifact_files={},
        allowed_verifier_prefixes=(
            ".superloop/tasks/task/implement/phases/a/",
            ".superloop/tasks/task/runs/",
        ),
        phase_id="a",
        phase_dir_key="a",
        phase_title="A",
    )
    delta = {
        ".superloop/tasks/task/implement/phases/a/criteria.md",
        ".superloop/tasks/task/implement/phases/b/criteria.md",
    }
    violations = verifier_scope_violations(bundle, delta, ".superloop/tasks/task")
    assert violations == [".superloop/tasks/task/implement/phases/b/criteria.md"]


def test_filter_volatile_task_run_paths_keeps_non_run_phase_artifacts():
    paths = {
        ".superloop/tasks/task/runs/run-1/events.jsonl",
        ".superloop/tasks/task/runs/run-1/summary.md",
        ".superloop/tasks/task/implement/phases/phase-a/implementation_notes.md",
        ".superloop/tasks/task/test/phases/phase-a/test_strategy.md",
    }

    filtered = filter_volatile_task_run_paths(paths, ".superloop/tasks/task")

    assert filtered == {
        ".superloop/tasks/task/implement/phases/phase-a/implementation_notes.md",
        ".superloop/tasks/task/test/phases/phase-a/test_strategy.md",
    }
