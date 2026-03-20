from __future__ import annotations

import json
from pathlib import Path

import superloop

from superloop import (
    CodexCommandConfig,
    EventRecorder,
    append_clarification,
    append_raw_phase_log,
    append_run_log,
    build_phase_prompt,
    create_run_paths,
    derive_intent_task_id,
    ensure_workspace,
    latest_run_id,
    latest_task_id,
    load_resume_checkpoint,
    load_phase_plan,
    open_existing_run_paths,
    latest_run_status,
    phase_plan_file,
    resolve_task_id,
    resolve_phase_selection,
    restore_phase_selection,
    SessionState,
    task_request_text,
    task_id_for_run,
    write_run_summary,
)


def fake_codex_command() -> CodexCommandConfig:
    return CodexCommandConfig(
        start_command=["codex", "exec", "--json", "-"],
        resume_command=["codex", "exec", "resume", "--json"],
    )


def install_fake_yaml(monkeypatch):
    class FakeYaml:
        YAMLError = ValueError

        @staticmethod
        def safe_load(text: str):
            return json.loads(text)

    monkeypatch.setattr(superloop, "yaml", FakeYaml)


def write_phase_plan(path: Path, task_id: str, *, phases: list[dict[str, object]] | None = None):
    payload = {
        "version": 1,
        "task_id": task_id,
        "request_snapshot_ref": "request.md",
        "phases": phases
        or [
            {
                "phase_id": "phase-1",
                "title": "Phase 1",
                "objective": "Build phase one",
                "in_scope": ["Implement phase one"],
                "out_of_scope": [],
                "dependencies": [],
                "acceptance_criteria": [{"id": "AC-1", "text": "Phase one is complete"}],
                "deliverables": ["code"],
                "risks": [],
                "rollback": [],
                "status": "planned",
            }
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_create_run_paths_creates_per_run_artifacts(tmp_path: Path):
    run_paths = create_run_paths(tmp_path, "run-test-123", "Implement feature X")

    assert run_paths["run_dir"].is_dir()
    assert run_paths["run_log"].exists()
    assert run_paths["raw_phase_log"].exists()
    assert run_paths["events_file"].exists()
    assert run_paths["summary_file"].parent == run_paths["run_dir"]
    assert run_paths["request_file"].read_text(encoding="utf-8").strip() == "Implement feature X"
    session_payload = json.loads(run_paths["session_file"].read_text(encoding="utf-8"))
    assert session_payload["mode"] == "persistent"
    assert session_payload["thread_id"] is None


def test_open_existing_run_paths_reuses_existing_artifacts(tmp_path: Path):
    create_run_paths(tmp_path, "run-test-123", "Implement feature X")
    opened = open_existing_run_paths(tmp_path, "run-test-123")
    assert opened["run_dir"].name == "run-test-123"
    assert opened["events_file"].exists()
    assert opened["request_file"].read_text(encoding="utf-8").strip() == "Implement feature X"


def test_raw_phase_log_includes_run_cycle_attempt(tmp_path: Path):
    raw_log = tmp_path / "raw_phase_log.md"
    raw_log.write_text("# Raw\n", encoding="utf-8")

    append_raw_phase_log(
        raw_log,
        pair="implement",
        phase="producer",
        cycle=2,
        attempt=3,
        process_name="codex-agent",
        stdout="hello",
        run_id="run-xyz",
    )

    text = raw_log.read_text(encoding="utf-8")
    assert "run_id=run-xyz" in text
    assert "pair=implement" in text
    assert "cycle=2" in text
    assert "attempt=3" in text


def test_event_recorder_and_summary_counts(tmp_path: Path):
    run_paths = create_run_paths(tmp_path, "run-abc", "Implement feature X")
    recorder = EventRecorder(run_id="run-abc", events_file=run_paths["events_file"])

    recorder.emit("pair_started", pair="plan")
    recorder.emit("phase_output_empty", pair="plan", phase="producer", cycle=1, attempt=1)
    recorder.emit("missing_promise_default", pair="plan", cycle=1, attempt=1)
    recorder.emit("phase_scope_resolved", phase_mode="single", phase_ids=["phase-1"])
    recorder.emit("phase_started", pair="implement", phase_id="phase-1")
    recorder.emit("phase_completed", pair="implement", phase_id="phase-1")
    recorder.emit("pair_completed", pair="plan", cycle=1, attempt=1)
    recorder.emit("run_finished", status="success")

    events = [json.loads(line) for line in run_paths["events_file"].read_text(encoding="utf-8").splitlines() if line]
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5, 6, 7, 8]

    write_run_summary(run_paths["summary_file"], "run-abc", run_paths["events_file"])
    summary = run_paths["summary_file"].read_text(encoding="utf-8")
    assert "phase_output_empty: 1" in summary
    assert "missing_promise_default: 1" in summary
    assert "pair_completed events: 1" in summary
    assert "phase_scope_resolved events: 1" in summary
    assert "phase_completed events: 1" in summary


def test_write_run_summary_allows_phase_lifecycle_events_after_pair_completed(tmp_path: Path):
    run_paths = create_run_paths(tmp_path, "run-lifecycle", "Implement feature X")
    recorder = EventRecorder(run_id="run-lifecycle", events_file=run_paths["events_file"])
    recorder.emit("pair_completed", pair="implement", cycle=1, attempt=1, phase_id="phase-1")
    recorder.emit("phase_deferred", pair="implement", phase_id="phase-1")
    recorder.emit("pair_completed", pair="test", cycle=1, attempt=1, phase_id="phase-1")
    recorder.emit("phase_completed", pair="test", phase_id="phase-1")
    recorder.emit("run_finished", status="success")

    write_run_summary(run_paths["summary_file"], "run-lifecycle", run_paths["events_file"])
    summary = run_paths["summary_file"].read_text(encoding="utf-8")
    assert "## Invariant violations" not in summary


def test_load_resume_checkpoint_skips_completed_pairs_and_continues_cycle(tmp_path: Path):
    run_paths = create_run_paths(tmp_path, "run-abc", "Implement feature X")
    recorder = EventRecorder(run_id="run-abc", events_file=run_paths["events_file"])
    recorder.emit("phase_scope_resolved", phase_mode="single", phase_ids=["phase-1"])
    recorder.emit("pair_completed", pair="plan", cycle=1, attempt=1)
    recorder.emit("phase_finished", pair="implement", phase="producer", cycle=2, attempt=3)

    checkpoint = load_resume_checkpoint(run_paths["events_file"], ["plan", "implement", "test"])
    assert checkpoint.pair_start_index == 1
    assert checkpoint.cycle_by_pair["implement"] == 1
    assert checkpoint.attempts_by_pair_cycle[("implement", 2)] == 3
    assert checkpoint.phase_mode == "single"
    assert checkpoint.phase_ids == ("phase-1",)


def test_validate_phase_plan_rejects_duplicate_phase_ids_after_normalization():
    import pytest

    with pytest.raises(superloop.PhasePlanError):
        superloop.validate_phase_plan(
            {
                "version": 1,
                "task_id": "dup-phase-task",
                "request_snapshot_ref": "request.md",
                "phases": [
                    {
                        "phase_id": "phase-1",
                        "title": "Phase 1",
                        "objective": "First",
                        "in_scope": ["first"],
                        "out_of_scope": [],
                        "dependencies": [],
                        "acceptance_criteria": [{"id": "AC-1", "text": "first done"}],
                        "deliverables": ["code"],
                        "risks": [],
                        "rollback": [],
                        "status": "planned",
                    },
                    {
                        "phase_id": " phase-1 ",
                        "title": "Phase 1 duplicate",
                        "objective": "Duplicate",
                        "in_scope": ["dup"],
                        "out_of_scope": [],
                        "dependencies": [],
                        "acceptance_criteria": [{"id": "AC-2", "text": "dup done"}],
                        "deliverables": ["docs"],
                        "risks": [],
                        "rollback": [],
                        "status": "planned",
                    },
                ],
            },
            "dup-phase-task",
        )


def test_append_run_log_scopes_entries(tmp_path: Path):
    run_log = tmp_path / "run_log.md"
    run_log.write_text("# Run\n", encoding="utf-8")

    append_run_log(run_log, "Started pair `plan`", run_id="run-1", pair="plan", cycle=1, attempt=2)

    text = run_log.read_text(encoding="utf-8")
    assert "run_id=run-1" in text
    assert "pair=plan" in text
    assert "cycle=1" in text
    assert "attempt=2" in text


def test_main_fatal_error_still_writes_terminal_event_and_summary(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(
        superloop,
        "run_codex_phase",
        lambda *args, **kwargs: "<loop-control>{not-json}</loop-control>",
    )

    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "plan",
            "--task-id",
            "fatal-test",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 1

    task_root = tmp_path / ".superloop" / "tasks" / "fatal-test"
    runs_root = task_root / "runs"
    run_dirs = [p for p in runs_root.iterdir() if p.is_dir()]
    assert len(run_dirs) == 1

    events = [
        json.loads(line)
        for line in (run_dirs[0] / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert events[-1]["event_type"] == "run_finished"
    assert events[-1]["status"] == "fatal_error"

    summary_text = (run_dirs[0] / "summary.md").read_text(encoding="utf-8")
    assert "Superloop Run Summary" in summary_text


def test_resolve_task_id_uses_task_id_or_intent():
    assert resolve_task_id("Custom Task", None) == "custom-task"
    assert resolve_task_id(None, "Implement refined reflow v1.2") == derive_intent_task_id("Implement refined reflow v1.2")


def test_latest_task_and_run_helpers(tmp_path: Path):
    task_a = tmp_path / "tasks" / "a"
    task_b = tmp_path / "tasks" / "b"
    task_a.mkdir(parents=True)
    task_b.mkdir(parents=True)
    assert latest_task_id(tmp_path / "tasks") in {"a", "b"}

    runs = tmp_path / "runs"
    (runs / "run-1").mkdir(parents=True)
    (runs / "run-2").mkdir(parents=True)
    assert latest_run_id(runs) in {"run-1", "run-2"}




def test_latest_task_id_prefers_created_at_over_mtime(tmp_path: Path):
    tasks_dir = tmp_path / "tasks"
    task_old = tasks_dir / "task-old"
    task_new = tasks_dir / "task-new"
    task_old.mkdir(parents=True)
    task_new.mkdir(parents=True)

    (task_old / "task.json").write_text('{"created_at":"2026-01-01T00:00:00Z"}\n', encoding="utf-8")
    (task_new / "task.json").write_text('{"created_at":"2026-01-02T00:00:00Z"}\n', encoding="utf-8")

    # Make filesystem mtime misleading on purpose.
    import os
    os.utime(task_old, (2000000000, 2000000000))
    os.utime(task_new, (1000000000, 1000000000))

    assert latest_task_id(tasks_dir) == "task-new"


def test_latest_run_id_prefers_run_timestamp_over_mtime(tmp_path: Path):
    run_new = tmp_path / "run-20260316T110008Z-aaaaaaaa"
    run_old = tmp_path / "run-20260316T103559Z-bbbbbbbb"
    run_new.mkdir(parents=True)
    run_old.mkdir(parents=True)

    import os
    os.utime(run_new, (1000000000, 1000000000))
    os.utime(run_old, (2000000000, 2000000000))

    assert latest_run_id(tmp_path) == "run-20260316T110008Z-aaaaaaaa"


def test_latest_run_status_reads_last_run_finished(tmp_path: Path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        '{"event_type":"run_finished","status":"failed"}\n'
        '{"event_type":"run_started"}\n'
        '{"event_type":"run_finished","status":"success"}\n',
        encoding="utf-8",
    )
    assert latest_run_status(events) == "success"

def test_main_resume_refuses_terminal_run(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())

    paths = ensure_workspace(
        root=tmp_path,
        task_id="resume-task",
        product_intent=None,
        intent_mode="preserve",
    )
    run_paths = create_run_paths(paths["runs_dir"], "run-20260316T120000Z-abcdef12", "Resume request")
    recorder = EventRecorder(run_id="run-20260316T120000Z-abcdef12", events_file=run_paths["events_file"])
    recorder.emit("run_finished", status="success")

    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "plan",
            "--task-id",
            "resume-task",
            "--resume",
            "--run-id",
            "run-20260316T120000Z-abcdef12",
            "--no-git",
        ],
    )

    import pytest
    with pytest.raises(SystemExit):
        superloop.main()

def test_task_id_for_run_finds_task_containing_run(tmp_path: Path):
    tasks_dir = tmp_path / "tasks"
    (tasks_dir / "task-x" / "runs" / "run-1").mkdir(parents=True)
    (tasks_dir / "task-y" / "runs" / "run-2").mkdir(parents=True)
    assert task_id_for_run(tasks_dir, "run-2") == "task-y"


def test_resolve_task_id_preserves_long_explicit_task_ids():
    intent_a = "Implement refined reflow v1.2 with strict verification and artifact scoping alpha"
    intent_b = "Implement refined reflow v1.2 with strict verification and artifact scoping beta"
    assert resolve_task_id(intent_a, None) == superloop.slugify_task(intent_a)
    assert resolve_task_id(intent_b, None) == superloop.slugify_task(intent_b)
    assert resolve_task_id(intent_a, None) != resolve_task_id(intent_b, None)


def test_derive_intent_task_id_truncates_long_slug_but_keeps_hash_uniqueness():
    intent_a = "x " * 300
    intent_b = "x " * 299 + "y"

    task_id_a = derive_intent_task_id(intent_a)
    task_id_b = derive_intent_task_id(intent_b)

    assert len(task_id_a.split("-")[-1]) == 8
    assert len(task_id_a) <= 57
    assert task_id_a != task_id_b


def test_derive_intent_task_id_strips_trailing_hyphen_from_truncated_slug():
    intent = ("abc-" * 20) + "tail"

    task_id = derive_intent_task_id(intent)
    slug, digest = task_id.rsplit("-", 1)

    assert not slug.endswith("-")
    assert len(digest) == 8


def test_ensure_workspace_accepts_long_intent_derived_task_ids(tmp_path: Path):
    intent = "x " * 300

    task_id = derive_intent_task_id(intent)
    paths = ensure_workspace(
        root=tmp_path,
        task_id=task_id,
        product_intent=intent,
        intent_mode="preserve",
    )

    assert paths["task_dir"].name == task_id
    assert paths["task_dir"].is_dir()
    assert (paths["task_dir"] / "task.json").exists()


def test_resume_accepts_long_explicit_task_id(tmp_path: Path, monkeypatch):
    task_id = "implement-refined-reflow-v1-2-sad-md-as-function-d391842d"
    paths = ensure_workspace(
        root=tmp_path,
        task_id=task_id,
        product_intent="Long explicit resume request",
        intent_mode="preserve",
    )
    create_run_paths(paths["runs_dir"], "run-20260316T120000Z-abcdef12", "Long explicit resume request")
    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(superloop, "run_codex_phase", lambda *args, **kwargs: "<loop-control></loop-control>")
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)

    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "plan",
            "--task-id",
            task_id,
            "--resume",
            "--run-id",
            "run-20260316T120000Z-abcdef12",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0


def test_ensure_workspace_creates_task_scoped_paths_and_task_prompts(tmp_path: Path):
    paths = ensure_workspace(
        root=tmp_path,
        task_id="my-task",
        product_intent="Implement feature X",
        intent_mode="replace",
    )

    task_dir = tmp_path / ".superloop" / "tasks" / "my-task"
    assert paths["task_dir"] == task_dir
    assert (task_dir / "task.json").exists()
    assert (task_dir / "plan" / "prompt.md").exists()
    assert not phase_plan_file(task_dir).exists()
    assert not (task_dir / "context.md").exists()
    assert task_request_text(paths["task_meta_file"], paths["legacy_context_file"]) == "Implement feature X"

    plan_prompt = (task_dir / "plan" / "prompt.md").read_text(encoding="utf-8")
    assert ".superloop/tasks/my-task/plan/plan.md" in plan_prompt
    assert ".superloop/tasks/my-task/plan/phase_plan.yaml" in plan_prompt
    assert ".superloop/plan/plan.md" not in plan_prompt
    assert ".superloop/context.md" not in plan_prompt


def test_load_phase_plan_and_resolve_selection(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    task_dir = tmp_path / ".superloop" / "tasks" / "demo-task"
    (task_dir / "plan").mkdir(parents=True)
    write_phase_plan(
        phase_plan_file(task_dir),
        "demo-task",
        phases=[
            {
                "phase_id": "phase-1",
                "title": "Phase 1",
                "objective": "Do first",
                "in_scope": ["first"],
                "out_of_scope": [],
                "dependencies": [],
                "acceptance_criteria": [{"id": "AC-1", "text": "first done"}],
                "deliverables": ["code"],
                "risks": [],
                "rollback": [],
                "status": "planned",
            },
            {
                "phase_id": "phase-2",
                "title": "Phase 2",
                "objective": "Do second",
                "in_scope": ["second"],
                "out_of_scope": [],
                "dependencies": ["phase-1"],
                "acceptance_criteria": [{"id": "AC-2", "text": "second done"}],
                "deliverables": ["tests"],
                "risks": [],
                "rollback": [],
                "status": "planned",
            },
        ],
    )

    plan = load_phase_plan(phase_plan_file(task_dir), "demo-task")
    assert plan is not None

    default_selection = resolve_phase_selection(plan, None, "single", ["implement", "test"])
    assert default_selection.phase_mode == "single"
    assert default_selection.phase_ids == ("phase-1", "phase-2")

    selection = resolve_phase_selection(plan, "phase-2", "up-to", ["implement", "test"])
    assert selection.phase_mode == "up-to"
    assert selection.phase_ids == ("phase-1", "phase-2")

    restored = restore_phase_selection(plan, ("phase-1", "phase-2"), "up-to")
    assert restored.phase_ids == ("phase-1", "phase-2")


def test_build_phase_prompt_includes_active_phase_contract(tmp_path: Path):
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("Prompt body\n", encoding="utf-8")
    request_file = tmp_path / "request.md"
    request_file.write_text("Implement feature X\n", encoding="utf-8")
    selection = superloop.ResolvedPhaseSelection(
        phase_mode="single",
        phase_ids=("phase-1",),
        phases=(
            superloop.PhasePlanPhase(
                phase_id="phase-1",
                title="Phase 1",
                objective="Deliver phase 1",
                in_scope=("code path A",),
                out_of_scope=("future work",),
                dependencies=("phase-0",),
                acceptance_criteria=(superloop.PhasePlanCriterion(id="AC-1", text="done"),),
                deliverables=("code",),
                risks=(),
                rollback=(),
                status="planned",
            ),
        ),
        explicit=True,
    )

    prompt = build_phase_prompt(
        cwd=tmp_path,
        prompt_file=prompt_file,
        request_file=request_file,
        run_raw_phase_log=tmp_path / "raw_phase_log.md",
        pair_name="implement",
        phase_name="producer",
        cycle_num=1,
        attempt_num=1,
        run_id="run-1",
        session_state=SessionState(
            mode="persistent",
            thread_id=None,
            pending_clarification_note=None,
            created_at="2026-03-18T00:00:00Z",
        ),
        include_request_snapshot=True,
        active_phase_selection=selection,
    )

    assert "ACTIVE PHASE EXECUTION CONTRACT:" in prompt
    assert "phase_ids: phase-1" in prompt
    assert "Phase phase-1: Phase 1" in prompt


def test_ensure_workspace_preserve_mode_keeps_existing_request(tmp_path: Path):
    ensure_workspace(
        root=tmp_path,
        task_id="same-task",
        product_intent="Intent A",
        intent_mode="replace",
    )
    ensure_workspace(
        root=tmp_path,
        task_id="same-task",
        product_intent="Intent B",
        intent_mode="preserve",
    )

    task_meta = json.loads((tmp_path / ".superloop" / "tasks" / "same-task" / "task.json").read_text(encoding="utf-8"))
    assert task_meta["request_text"] == "Intent A"


def test_ensure_workspace_does_not_rewrite_existing_task_prompts(tmp_path: Path):
    paths = ensure_workspace(
        root=tmp_path,
        task_id="same-task",
        product_intent="Intent A",
        intent_mode="replace",
    )
    prompt_file = paths["task_dir"] / "plan" / "prompt.md"
    verifier_prompt_file = paths["task_dir"] / "plan" / "verifier_prompt.md"
    prompt_file.write_text("custom prompt\n", encoding="utf-8")
    verifier_prompt_file.write_text("custom verifier prompt\n", encoding="utf-8")

    ensure_workspace(
        root=tmp_path,
        task_id="same-task",
        product_intent="Intent B",
        intent_mode="preserve",
    )

    assert prompt_file.read_text(encoding="utf-8") == "custom prompt\n"
    assert verifier_prompt_file.read_text(encoding="utf-8") == "custom verifier prompt\n"


def test_append_clarification_logs_to_raw_phase_log_and_updates_session(tmp_path: Path):
    run_paths = create_run_paths(tmp_path, "run-clarify", "Initial request")
    task_raw_log = tmp_path / "task_raw_phase_log.md"
    task_raw_log.write_text("# Task Raw\n", encoding="utf-8")

    append_clarification(
        run_paths["raw_phase_log"],
        task_raw_log,
        run_paths["session_file"],
        pair="plan",
        phase="producer",
        cycle=1,
        attempt=2,
        question="Question text\nBest supposition: safest path",
        answer="Approved answer",
        run_id="run-clarify",
        source="human",
    )

    run_text = run_paths["raw_phase_log"].read_text(encoding="utf-8")
    assert "entry=clarification" in run_text
    assert "source=human" in run_text
    assert "Approved answer" in run_text
    session_payload = json.loads(run_paths["session_file"].read_text(encoding="utf-8"))
    assert "Approved answer" in session_payload["pending_clarification_note"]


def test_main_resume_without_session_file_starts_new_conversation_and_logs_notice(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(
        root=tmp_path,
        task_id="legacy-run",
        product_intent="Legacy request",
        intent_mode="replace",
    )
    run_paths = create_run_paths(paths["runs_dir"], "run-20260316T120000Z-abcdef12", "Legacy request")
    run_paths["session_file"].unlink()
    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(superloop, "run_codex_phase", lambda *args, **kwargs: "<loop-control></loop-control>")
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "plan",
            "--task-id",
            "legacy-run",
            "--resume",
            "--run-id",
            "run-20260316T120000Z-abcdef12",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0
    session_payload = json.loads(run_paths["session_file"].read_text(encoding="utf-8"))
    assert session_payload["mode"] == "persistent"
    run_log_text = run_paths["run_log"].read_text(encoding="utf-8")
    raw_log_text = run_paths["raw_phase_log"].read_text(encoding="utf-8")
    assert "new conversation for the next phase" in run_log_text
    assert "entry=session_recovery" in raw_log_text


def test_main_resume_with_missing_thread_id_starts_new_conversation_and_logs_notice(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(
        root=tmp_path,
        task_id="legacy-run",
        product_intent="Legacy request",
        intent_mode="replace",
    )
    run_paths = create_run_paths(paths["runs_dir"], "run-20260316T120000Z-abcdef12", "Legacy request")
    run_paths["session_file"].write_text(
        json.dumps(
            {
                "mode": "persistent",
                "thread_id": None,
                "pending_clarification_note": None,
                "created_at": "2026-03-16T12:00:00Z",
                "last_used_at": "2026-03-16T12:05:00Z",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(superloop, "run_codex_phase", lambda *args, **kwargs: "<loop-control></loop-control>")
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "plan",
            "--task-id",
            "legacy-run",
            "--resume",
            "--run-id",
            "run-20260316T120000Z-abcdef12",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0
    run_log_text = run_paths["run_log"].read_text(encoding="utf-8")
    raw_log_text = run_paths["raw_phase_log"].read_text(encoding="utf-8")
    assert "new conversation for the next phase" in run_log_text
    assert "entry=session_recovery" in raw_log_text


def test_main_resume_reconstructs_missing_request_from_legacy_context_not_current_task_request(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(
        root=tmp_path,
        task_id="legacy-run",
        product_intent=None,
        intent_mode="preserve",
    )
    paths["legacy_context_file"].write_text(
        "# Product Context\nLegacy request from original run\n\n### Clarification\nLater clarification",
        encoding="utf-8",
    )
    task_meta = json.loads(paths["task_meta_file"].read_text(encoding="utf-8"))
    task_meta["request_text"] = "Newer mutable task request"
    paths["task_meta_file"].write_text(json.dumps(task_meta, indent=2) + "\n", encoding="utf-8")

    run_paths = create_run_paths(paths["runs_dir"], "run-20260316T120000Z-abcdef12", "Original request")
    run_paths["request_file"].unlink()
    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(superloop, "run_codex_phase", lambda *args, **kwargs: "<loop-control></loop-control>")
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "plan",
            "--task-id",
            "legacy-run",
            "--resume",
            "--run-id",
            "run-20260316T120000Z-abcdef12",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0
    request_text = run_paths["request_file"].read_text(encoding="utf-8")
    run_log_text = run_paths["run_log"].read_text(encoding="utf-8")
    raw_log_text = run_paths["raw_phase_log"].read_text(encoding="utf-8")
    assert "Legacy request from original run" in request_text
    assert "Newer mutable task request" not in request_text
    assert "entry=request_recovery" in raw_log_text
    assert "reconstructed from the legacy task context" in run_log_text


def test_main_without_phase_id_with_explicit_phase_plan_executes_all_phases_in_order(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    paths = ensure_workspace(
        root=tmp_path,
        task_id="phase-task",
        product_intent="Explicit plan request",
        intent_mode="replace",
    )
    write_phase_plan(
        phase_plan_file(paths["task_dir"]),
        "phase-task",
        phases=[
            {
                "phase_id": "phase-1",
                "title": "Phase 1",
                "objective": "First",
                "in_scope": ["first"],
                "out_of_scope": [],
                "dependencies": [],
                "acceptance_criteria": [{"id": "AC-1", "text": "first done"}],
                "deliverables": ["code"],
                "risks": [],
                "rollback": [],
                "status": "planned",
            },
            {
                "phase_id": "phase-2",
                "title": "Phase 2",
                "objective": "Second",
                "in_scope": ["second"],
                "out_of_scope": [],
                "dependencies": ["phase-1"],
                "acceptance_criteria": [{"id": "AC-2", "text": "second done"}],
                "deliverables": ["docs"],
                "risks": [],
                "rollback": [],
                "status": "planned",
            },
        ],
    )
    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(
        superloop,
        "run_codex_phase",
        lambda *args, **kwargs: calls.append((args[4], kwargs["active_phase_selection"].phase_ids[0])) or "<loop-control></loop-control>",
    )
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)

    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "implement",
            "--task-id",
            "phase-task",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0
    assert calls == [
        ("implement", "phase-1"),
        ("implement", "phase-1"),
        ("implement", "phase-2"),
        ("implement", "phase-2"),
    ]

    task_meta = json.loads(paths["task_meta_file"].read_text(encoding="utf-8"))
    assert task_meta["active_phase_selection"]["phase_ids"] == ["phase-1", "phase-2"]
    assert task_meta["phase_status"]["phase-1"] == "completed"
    assert task_meta["phase_status"]["phase-2"] == "completed"
    assert "phase_pair_status" not in task_meta


def test_main_fails_fast_when_yaml_missing_for_plan_plus_phased_pairs(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(
        root=tmp_path,
        task_id="yaml-fast-fail",
        product_intent="Need phased execution",
        intent_mode="replace",
    )

    monkeypatch.setattr(superloop, "yaml", None)
    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())

    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "plan,implement,test",
            "--task-id",
            "yaml-fast-fail",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    import pytest
    with pytest.raises(SystemExit):
        superloop.main()

    assert phase_plan_file(paths["task_dir"]).exists() is False


def test_main_allows_implicit_legacy_phase_when_yaml_missing_and_no_explicit_plan(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(
        root=tmp_path,
        task_id="yaml-implicit-ok",
        product_intent="Legacy implicit flow",
        intent_mode="replace",
    )
    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )

    monkeypatch.setattr(superloop, "yaml", None)
    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(superloop, "run_codex_phase", lambda *args, **kwargs: "<loop-control></loop-control>")
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "implement",
            "--task-id",
            "yaml-implicit-ok",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0
    assert phase_plan_file(paths["task_dir"]).exists() is False


def test_main_implement_with_explicit_phase_id_emits_phase_events_and_updates_meta(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    paths = ensure_workspace(
        root=tmp_path,
        task_id="phase-task",
        product_intent="Explicit plan request",
        intent_mode="replace",
    )
    write_phase_plan(phase_plan_file(paths["task_dir"]), "phase-task")
    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(superloop, "run_codex_phase", lambda *args, **kwargs: "<loop-control></loop-control>")
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "implement",
            "--task-id",
            "phase-task",
            "--phase-id",
            "phase-1",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0

    events_file = next((paths["runs_dir"]).iterdir()) / "events.jsonl"
    event_types = [json.loads(line)["event_type"] for line in events_file.read_text(encoding="utf-8").splitlines() if line]
    assert "phase_scope_resolved" in event_types
    assert "phase_started" in event_types
    assert "phase_completed" in event_types

    task_meta = json.loads(paths["task_meta_file"].read_text(encoding="utf-8"))
    assert task_meta["phase_status"]["phase-1"] == "completed"
    assert task_meta["active_phase_selection"]["phase_ids"] == ["phase-1"]
    assert "phase_pair_status" not in task_meta


def test_main_up_to_executes_phases_sequentially_and_completes_each_phase(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    paths = ensure_workspace(
        root=tmp_path,
        task_id="phase-prefix-task",
        product_intent="Explicit prefix request",
        intent_mode="replace",
    )
    write_phase_plan(
        phase_plan_file(paths["task_dir"]),
        "phase-prefix-task",
        phases=[
            {
                "phase_id": "phase-1",
                "title": "Phase 1",
                "objective": "First",
                "in_scope": ["first"],
                "out_of_scope": [],
                "dependencies": [],
                "acceptance_criteria": [{"id": "AC-1", "text": "first done"}],
                "deliverables": ["code"],
                "risks": [],
                "rollback": [],
                "status": "planned",
            },
            {
                "phase_id": "phase-2",
                "title": "Phase 2",
                "objective": "Second",
                "in_scope": ["second"],
                "out_of_scope": [],
                "dependencies": ["phase-1"],
                "acceptance_criteria": [{"id": "AC-2", "text": "second done"}],
                "deliverables": ["tests"],
                "risks": [],
                "rollback": [],
                "status": "planned",
            },
        ],
    )
    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(superloop, "run_codex_phase", lambda *args, **kwargs: "<loop-control></loop-control>")
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "implement,test",
            "--task-id",
            "phase-prefix-task",
            "--phase-id",
            "phase-2",
            "--phase-mode",
            "up-to",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0

    events_file = next((paths["runs_dir"]).iterdir()) / "events.jsonl"
    events = [json.loads(line) for line in events_file.read_text(encoding="utf-8").splitlines() if line]
    completed_phase_ids = [event["phase_id"] for event in events if event["event_type"] == "phase_completed"]
    assert completed_phase_ids == ["phase-1", "phase-2"]

    task_meta = json.loads(paths["task_meta_file"].read_text(encoding="utf-8"))
    assert task_meta["phase_status"]["phase-1"] == "completed"
    assert task_meta["phase_status"]["phase-2"] == "completed"
    assert "phase_pair_status" not in task_meta


def test_load_resume_checkpoint_tracks_phase_scoped_completion_and_cycles(tmp_path: Path):
    run_paths = create_run_paths(tmp_path, "run-phase-aware", "Implement feature X")
    recorder = EventRecorder(run_id="run-phase-aware", events_file=run_paths["events_file"])

    recorder.emit("phase_scope_resolved", phase_mode="single", phase_ids=["phase-1", "phase-2"], current_phase_index=1)
    recorder.emit("pair_completed", pair="implement", cycle=1, attempt=1, phase_id="phase-1")
    recorder.emit("phase_started", pair="implement", phase_id="phase-2")
    recorder.emit("phase_finished", pair="implement", phase="producer", cycle=2, attempt=3, phase_id="phase-2")
    recorder.emit("phase_deferred", pair="implement", phase_id="phase-2")

    checkpoint = load_resume_checkpoint(run_paths["events_file"], ["implement", "test"])
    assert checkpoint.phase_ids == ("phase-1", "phase-2")
    assert checkpoint.current_phase_index == 1
    assert checkpoint.completed_pairs_by_phase == {"phase-1": ("implement",)}
    assert checkpoint.cycle_by_phase_pair[("phase-2", "implement")] == 1
    assert checkpoint.attempts_by_phase_pair_cycle[("phase-2", "implement", 2)] == 3
    assert checkpoint.scope_event_seen is True
    assert checkpoint.emitted_phase_started_ids == ("phase-2",)
    assert checkpoint.emitted_phase_deferred_keys == (("phase-2", "implement"),)


def test_main_resume_without_phase_id_resumes_first_incomplete_phase_and_dedupes_events(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    paths = ensure_workspace(
        root=tmp_path,
        task_id="resume-phase-task",
        product_intent="Explicit resume request",
        intent_mode="replace",
    )
    write_phase_plan(
        phase_plan_file(paths["task_dir"]),
        "resume-phase-task",
        phases=[
            {
                "phase_id": "phase-1",
                "title": "Phase 1",
                "objective": "First",
                "in_scope": ["first"],
                "out_of_scope": [],
                "dependencies": [],
                "acceptance_criteria": [{"id": "AC-1", "text": "first done"}],
                "deliverables": ["code"],
                "risks": [],
                "rollback": [],
                "status": "planned",
            },
            {
                "phase_id": "phase-2",
                "title": "Phase 2",
                "objective": "Second",
                "in_scope": ["second"],
                "out_of_scope": [],
                "dependencies": ["phase-1"],
                "acceptance_criteria": [{"id": "AC-2", "text": "second done"}],
                "deliverables": ["tests"],
                "risks": [],
                "rollback": [],
                "status": "planned",
            },
            {
                "phase_id": "phase-3",
                "title": "Phase 3",
                "objective": "Third",
                "in_scope": ["third"],
                "out_of_scope": [],
                "dependencies": ["phase-2"],
                "acceptance_criteria": [{"id": "AC-3", "text": "third done"}],
                "deliverables": ["docs"],
                "risks": [],
                "rollback": [],
                "status": "planned",
            },
        ],
    )
    run_paths = create_run_paths(paths["runs_dir"], "run-20260319T010101Z-aaaaaaaa", "Explicit resume request")
    recorder = EventRecorder(run_id="run-20260319T010101Z-aaaaaaaa", events_file=run_paths["events_file"])
    recorder.emit("run_started", workspace=str(tmp_path), pairs=["implement", "test"])
    recorder.emit(
        "phase_scope_resolved",
        phase_mode="single",
        phase_ids=["phase-1", "phase-2", "phase-3"],
        current_phase_index=1,
    )
    recorder.emit("phase_started", pair="implement", phase_id="phase-1")
    recorder.emit("pair_completed", pair="implement", cycle=1, attempt=1, phase_id="phase-1")
    recorder.emit("phase_deferred", pair="implement", phase_id="phase-1")
    recorder.emit("pair_completed", pair="test", cycle=1, attempt=1, phase_id="phase-1")
    recorder.emit("phase_completed", pair="test", phase_id="phase-1")
    recorder.emit("phase_started", pair="implement", phase_id="phase-2")
    recorder.emit("pair_completed", pair="implement", cycle=1, attempt=1, phase_id="phase-2")
    recorder.emit("phase_deferred", pair="implement", phase_id="phase-2")

    task_meta = json.loads(paths["task_meta_file"].read_text(encoding="utf-8"))
    task_meta["active_phase_selection"] = {
        "run_id": "run-20260319T010101Z-aaaaaaaa",
        "mode": "single",
        "phase_ids": ["phase-1", "phase-2", "phase-3"],
        "explicit": True,
        "current_phase_index": 1,
        "current_phase_id": "phase-2",
    }
    task_meta["phase_status"] = {
        "phase-1": "completed",
        "phase-2": "in_progress",
        "phase-3": "planned",
    }
    paths["task_meta_file"].write_text(json.dumps(task_meta, indent=2) + "\n", encoding="utf-8")

    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )
    calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(
        superloop,
        "run_codex_phase",
        lambda *args, **kwargs: calls.append((args[4], args[3], kwargs["active_phase_selection"].phase_ids[0])) or "<loop-control></loop-control>",
    )
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "implement,test",
            "--task-id",
            "resume-phase-task",
            "--resume",
            "--run-id",
            "run-20260319T010101Z-aaaaaaaa",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0
    assert [(pair, phase_id) for pair, _phase_name, phase_id in calls] == [
        ("test", "phase-2"),
        ("test", "phase-2"),
        ("implement", "phase-3"),
        ("implement", "phase-3"),
        ("test", "phase-3"),
        ("test", "phase-3"),
    ]

    events = [
        json.loads(line)
        for line in run_paths["events_file"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    phase_scope_events = [event for event in events if event["event_type"] == "phase_scope_resolved"]
    phase2_started_events = [
        event for event in events if event["event_type"] == "phase_started" and event.get("phase_id") == "phase-2"
    ]
    phase2_deferred_events = [
        event for event in events if event["event_type"] == "phase_deferred" and event.get("phase_id") == "phase-2"
    ]
    phase2_completed_events = [
        event for event in events if event["event_type"] == "phase_completed" and event.get("phase_id") == "phase-2"
    ]
    phase3_completed_events = [
        event for event in events if event["event_type"] == "phase_completed" and event.get("phase_id") == "phase-3"
    ]
    assert len(phase_scope_events) == 1
    assert len(phase2_started_events) == 1
    assert len(phase2_deferred_events) == 1
    assert len(phase2_completed_events) == 1
    assert len(phase3_completed_events) == 1

    updated_task_meta = json.loads(paths["task_meta_file"].read_text(encoding="utf-8"))
    assert updated_task_meta["phase_status"]["phase-2"] == "completed"
    assert updated_task_meta["phase_status"]["phase-3"] == "completed"
    assert "phase_pair_status" not in updated_task_meta


def test_main_resume_skips_plan_pair_when_plan_already_completed(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    paths = ensure_workspace(
        root=tmp_path,
        task_id="resume-plan-skip-task",
        product_intent="Resume plan skip request",
        intent_mode="replace",
    )
    write_phase_plan(phase_plan_file(paths["task_dir"]), "resume-plan-skip-task")

    run_paths = create_run_paths(paths["runs_dir"], "run-20260319T020202Z-bbbbbbbb", "Resume request")
    recorder = EventRecorder(run_id="run-20260319T020202Z-bbbbbbbb", events_file=run_paths["events_file"])
    recorder.emit("run_started", workspace=str(tmp_path), pairs=["plan", "implement"])
    recorder.emit("pair_completed", pair="plan", cycle=1, attempt=1)
    recorder.emit("phase_scope_resolved", phase_mode="single", phase_ids=["phase-1"], current_phase_index=0)
    recorder.emit("phase_started", pair="implement", phase_id="phase-1")

    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )
    calls: list[str] = []

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(
        superloop,
        "run_codex_phase",
        lambda *args, **kwargs: calls.append(args[4]) or "<loop-control></loop-control>",
    )
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "plan,implement",
            "--task-id",
            "resume-plan-skip-task",
            "--resume",
            "--run-id",
            "run-20260319T020202Z-bbbbbbbb",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0
    assert calls == ["implement", "implement"]


def test_main_non_resume_does_not_skip_prior_run_phase_pair_completion(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    paths = ensure_workspace(
        root=tmp_path,
        task_id="non-resume-phase-task",
        product_intent="Prior run should not skip new run",
        intent_mode="replace",
    )
    write_phase_plan(phase_plan_file(paths["task_dir"]), "non-resume-phase-task")

    prior_run = create_run_paths(paths["runs_dir"], "run-20260319T020303Z-cccccccc", "Prior run")
    prior_recorder = EventRecorder(run_id="run-20260319T020303Z-cccccccc", events_file=prior_run["events_file"])
    prior_recorder.emit("pair_completed", pair="implement", cycle=1, attempt=1, phase_id="phase-1")
    prior_recorder.emit("run_finished", status="success")

    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(
        superloop,
        "run_codex_phase",
        lambda *args, **kwargs: calls.append((args[4], kwargs["active_phase_selection"].phase_ids[0])) or "<loop-control></loop-control>",
    )
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "implement",
            "--task-id",
            "non-resume-phase-task",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0
    assert calls == [("implement", "phase-1"), ("implement", "phase-1")]

def test_main_test_only_requires_prior_implement_completion(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    paths = ensure_workspace(
        root=tmp_path,
        task_id="test-only-phase-task",
        product_intent="Explicit test-only request",
        intent_mode="replace",
    )
    write_phase_plan(phase_plan_file(paths["task_dir"]), "test-only-phase-task")
    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(superloop, "run_codex_phase", lambda *args, **kwargs: "<loop-control></loop-control>")
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "test",
            "--task-id",
            "test-only-phase-task",
            "--phase-id",
            "phase-1",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 1

    task_meta = json.loads(paths["task_meta_file"].read_text(encoding="utf-8"))
    assert task_meta["phase_status"]["phase-1"] != "completed"
    assert "phase_pair_status" not in task_meta


def test_main_implement_without_phase_plan_uses_implicit_phase(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(
        root=tmp_path,
        task_id="legacy-phase-task",
        product_intent="Legacy request",
        intent_mode="replace",
    )
    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(superloop, "run_codex_phase", lambda *args, **kwargs: "<loop-control></loop-control>")
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(tmp_path),
            "--pairs",
            "implement",
            "--task-id",
            "legacy-phase-task",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0

    task_meta = json.loads(paths["task_meta_file"].read_text(encoding="utf-8"))
    assert task_meta["phase_status"]["implicit-phase"] == "completed"
