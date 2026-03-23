from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest
import superloop

from loop_control import LoopQuestion
from superloop import (
    CodexCommandConfig,
    ConfigError,
    EventRecorder,
    ProviderConfig,
    RuntimeConfig,
    append_clarification,
    append_raw_phase_log,
    build_phase_prompt,
    create_run_paths,
    discover_config_file,
    derive_intent_task_id,
    ensure_phase_plan_scaffold,
    ensure_workspace,
    execute_pair_cycles,
    latest_run_id,
    latest_task_id,
    load_resume_checkpoint,
    load_phase_plan,
    open_existing_run_paths,
    latest_run_status,
    phase_plan_file,
    resolve_runtime_config,
    resolve_task_id,
    resolve_phase_selection,
    resolve_codex_exec_command,
    restore_phase_selection,
    PairConfig,
    SessionState,
    task_request_text,
    task_id_for_run,
    verifier_scope_violations,
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


def write_superloop_config(path: Path, payload: dict[str, object]):
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_discover_config_file_rejects_same_directory_ambiguity(tmp_path: Path):
    import pytest

    (tmp_path / "superloop.yaml").write_text("{}", encoding="utf-8")
    (tmp_path / "superloop.config").write_text("{}", encoding="utf-8")

    with pytest.raises(ConfigError, match="multiple configuration files"):
        discover_config_file(tmp_path)


def test_resolve_runtime_config_uses_builtins_when_no_config_and_yaml_missing(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(superloop, "yaml", None)
    monkeypatch.setattr(superloop, "superloop_repo_root", lambda: tmp_path / "global")

    resolved = resolve_runtime_config(
        tmp_path / "workspace",
        argparse.Namespace(model=None, model_effort=None),
    )

    assert resolved.provider == ProviderConfig(model="gpt-5.4", model_effort=None)
    assert resolved.runtime == RuntimeConfig(
        pairs="plan,implement,test",
        max_iterations=15,
        phase_mode="single",
        intent_mode="preserve",
        full_auto_answers=False,
        no_git=False,
    )


def test_resolve_runtime_config_applies_global_local_and_cli_precedence(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    global_root = tmp_path / "global"
    workspace_root = tmp_path / "workspace"
    global_root.mkdir()
    workspace_root.mkdir()
    monkeypatch.setattr(superloop, "superloop_repo_root", lambda: global_root)

    write_superloop_config(
        global_root / "superloop.yaml",
        {
            "provider": {"model": "gpt-global", "model_effort": "medium"},
            "runtime": {"max_iterations": 9, "phase_mode": "up-to", "no_git": True},
        },
    )
    write_superloop_config(
        workspace_root / "superloop.config",
        {"provider": {"model": "gpt-local"}, "runtime": {"max_iterations": 3, "no_git": False}},
    )

    resolved = resolve_runtime_config(
        workspace_root,
        argparse.Namespace(model=None, model_effort=None),
    )
    assert resolved.provider == ProviderConfig(model="gpt-local", model_effort="medium")
    assert resolved.runtime.max_iterations == 3
    assert resolved.runtime.phase_mode == "up-to"
    assert resolved.runtime.no_git is False

    cli_resolved = resolve_runtime_config(
        workspace_root,
        argparse.Namespace(model="gpt-cli", model_effort="high", max_iterations=4, no_git=True),
    )
    assert cli_resolved.provider == ProviderConfig(model="gpt-cli", model_effort="high")
    assert cli_resolved.runtime.max_iterations == 4
    assert cli_resolved.runtime.no_git is True


def test_resolve_runtime_config_rejects_invalid_runtime_values(tmp_path: Path, monkeypatch):
    import pytest

    install_fake_yaml(monkeypatch)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setattr(superloop, "superloop_repo_root", lambda: tmp_path / "global")
    write_superloop_config(
        workspace_root / "superloop.yaml",
        {"runtime": {"max_iterations": 0}},
    )

    with pytest.raises(ConfigError, match="max_iterations"):
        resolve_runtime_config(workspace_root, argparse.Namespace(model=None, model_effort=None))


def test_resolve_runtime_config_requires_yaml_when_config_present(tmp_path: Path, monkeypatch):
    import pytest

    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setattr(superloop, "yaml", None)
    monkeypatch.setattr(superloop, "superloop_repo_root", lambda: tmp_path / "global")
    (workspace_root / "superloop.yaml").write_text("{}", encoding="utf-8")

    with pytest.raises(ConfigError, match="PyYAML"):
        resolve_runtime_config(workspace_root, argparse.Namespace(model=None, model_effort=None))


def test_resolve_runtime_config_rejects_unknown_provider_keys(tmp_path: Path, monkeypatch):
    import pytest

    install_fake_yaml(monkeypatch)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setattr(superloop, "superloop_repo_root", lambda: tmp_path / "global")
    write_superloop_config(
        workspace_root / "superloop.yaml",
        {"provider": {"temperature": "1"}},
    )

    with pytest.raises(ConfigError, match="unsupported provider keys"):
        resolve_runtime_config(workspace_root, argparse.Namespace(model=None, model_effort=None))


def test_resolve_runtime_config_rejects_unknown_top_level_keys(tmp_path: Path, monkeypatch):
    import pytest

    install_fake_yaml(monkeypatch)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setattr(superloop, "superloop_repo_root", lambda: tmp_path / "global")
    write_superloop_config(
        workspace_root / "superloop.yaml",
        {"unexpected": {"model": "gpt-test"}},
    )

    with pytest.raises(ConfigError, match="unsupported top-level keys"):
        resolve_runtime_config(workspace_root, argparse.Namespace(model=None, model_effort=None))


def test_resolve_runtime_config_rejects_non_string_top_level_key(tmp_path: Path, monkeypatch):
    import pytest

    install_fake_yaml(monkeypatch)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setattr(superloop, "superloop_repo_root", lambda: tmp_path / "global")
    write_superloop_config(
        workspace_root / "superloop.yaml",
        {"provider": {"model": "gpt-test"}, 1: "x"},
    )

    with pytest.raises(ConfigError, match="unsupported top-level keys: 1"):
        resolve_runtime_config(workspace_root, argparse.Namespace(model=None, model_effort=None))


def test_resolve_runtime_config_rejects_non_string_runtime_key(tmp_path: Path, monkeypatch):
    import pytest

    install_fake_yaml(monkeypatch)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setattr(superloop, "superloop_repo_root", lambda: tmp_path / "global")
    write_superloop_config(
        workspace_root / "superloop.yaml",
        {"runtime": {1: "x"}},
    )

    with pytest.raises(ConfigError, match="unsupported runtime keys: 1"):
        resolve_runtime_config(workspace_root, argparse.Namespace(model=None, model_effort=None))


def test_resolve_runtime_config_rejects_malformed_yaml(tmp_path: Path, monkeypatch):
    import pytest

    install_fake_yaml(monkeypatch)
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    monkeypatch.setattr(superloop, "superloop_repo_root", lambda: tmp_path / "global")
    (workspace_root / "superloop.yaml").write_text("{not-json", encoding="utf-8")

    with pytest.raises(ConfigError, match="could not be parsed as YAML"):
        resolve_runtime_config(workspace_root, argparse.Namespace(model=None, model_effort=None))


def test_resolve_codex_exec_command_includes_model_effort_when_supported(monkeypatch):
    help_calls: list[list[str]] = []

    def fake_run(cmd, capture_output, text, encoding):
        help_calls.append(cmd)
        if cmd == ["codex", "exec", "--help"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="--json --full-auto --model-effort",
                stderr="",
            )
        if cmd == ["codex", "exec", "resume", "--help"]:
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout="--json --model-effort",
                stderr="",
            )
        raise AssertionError(cmd)

    monkeypatch.setattr(superloop.subprocess, "run", fake_run)

    command = resolve_codex_exec_command(ProviderConfig(model="gpt-test", model_effort="high"))

    assert help_calls == [
        ["codex", "exec", "--help"],
        ["codex", "exec", "resume", "--help"],
    ]
    assert "--model-effort" in command.start_command
    assert "--model-effort" in command.resume_command
    assert command.start_command[-1] == "-"


def test_resolve_codex_exec_command_omits_model_effort_when_unset(monkeypatch):
    def fake_run(cmd, capture_output, text, encoding):
        if cmd == ["codex", "exec", "--help"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="--json --full-auto", stderr="")
        if cmd == ["codex", "exec", "resume", "--help"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="--json", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(superloop.subprocess, "run", fake_run)

    command = resolve_codex_exec_command(ProviderConfig(model="gpt-test"))

    assert "--model-effort" not in command.start_command
    assert "--model-effort" not in command.resume_command


def test_resolve_codex_exec_command_rejects_unsupported_model_effort(monkeypatch):
    import pytest

    def fake_run(cmd, capture_output, text, encoding):
        if cmd == ["codex", "exec", "--help"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="--json --full-auto", stderr="")
        if cmd == ["codex", "exec", "resume", "--help"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="--json", stderr="")
        raise AssertionError(cmd)

    monkeypatch.setattr(superloop.subprocess, "run", fake_run)

    with pytest.raises(SystemExit):
        resolve_codex_exec_command(ProviderConfig(model="gpt-test", model_effort="high"))


def test_main_resolves_provider_config_before_codex_command(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    workspace_root = tmp_path / "workspace"
    global_root = tmp_path / "global"
    workspace_root.mkdir()
    global_root.mkdir()
    monkeypatch.setattr(superloop, "superloop_repo_root", lambda: global_root)
    write_superloop_config(
        global_root / "superloop.yaml",
        {"provider": {"model": "gpt-global", "model_effort": "medium"}},
    )
    write_superloop_config(
        workspace_root / "superloop.config",
        {"provider": {"model": "gpt-local"}},
    )

    captured: list[ProviderConfig] = []
    control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(
        superloop,
        "resolve_codex_exec_command",
        lambda provider: captured.append(provider) or fake_codex_command(),
    )
    monkeypatch.setattr(superloop, "run_codex_phase", lambda *args, **kwargs: "<loop-control></loop-control>")
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: control)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop.sys,
        "argv",
        [
            "superloop.py",
            "--workspace",
            str(workspace_root),
            "--pairs",
            "plan",
            "--task-id",
            "config-task",
            "--max-iterations",
            "1",
            "--model-effort",
            "high",
            "--no-git",
        ],
    )

    exit_code = superloop.main()

    assert exit_code == 0
    assert captured == [ProviderConfig(model="gpt-local", model_effort="high")]


def test_create_run_paths_creates_per_run_artifacts(tmp_path: Path):
    run_paths = create_run_paths(tmp_path, "run-test-123", "Implement feature X")

    assert "session_file" not in run_paths
    assert run_paths["run_dir"].is_dir()
    assert run_paths["raw_phase_log"].exists()
    assert run_paths["events_file"].exists()
    assert not (run_paths["run_dir"] / "run_log.md").exists()
    assert not (run_paths["run_dir"] / "summary.md").exists()
    assert run_paths["request_file"].read_text(encoding="utf-8").strip() == "Implement feature X"
    session_payload = json.loads(run_paths["plan_session_file"].read_text(encoding="utf-8"))
    assert session_payload["mode"] == "persistent"
    assert session_payload["thread_id"] is None


def test_append_runtime_notice_writes_only_task_and_run_raw_logs(tmp_path: Path):
    task_raw_phase_log = tmp_path / "task_raw_phase_log.md"
    run_raw_phase_log = tmp_path / "run_raw_phase_log.md"
    task_raw_phase_log.write_text("# task raw\n", encoding="utf-8")
    run_raw_phase_log.write_text("# run raw\n", encoding="utf-8")

    superloop.append_runtime_notice(
        task_raw_phase_log,
        run_raw_phase_log,
        "run-123",
        "Recovered missing request snapshot",
        entry="request_recovery",
    )

    task_text = task_raw_phase_log.read_text(encoding="utf-8")
    run_text = run_raw_phase_log.read_text(encoding="utf-8")

    assert "Recovered missing request snapshot" in task_text
    assert "Recovered missing request snapshot" in run_text
    assert "request_recovery" in task_text
    assert "request_recovery" in run_text
    assert not (tmp_path / "run_log.md").exists()


def test_ensure_phase_plan_scaffold_writes_runtime_metadata_after_request_snapshot_exists(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    paths = ensure_workspace(
        root=tmp_path,
        task_id="phase-plan-task",
        product_intent="Implement feature X",
        intent_mode="replace",
    )
    assert not phase_plan_file(paths["task_dir"]).exists()

    run_paths = create_run_paths(paths["runs_dir"], "run-test-123", "Implement feature X")
    plan_path = ensure_phase_plan_scaffold(paths["task_dir"], "phase-plan-task", run_paths["request_file"])

    assert plan_path == phase_plan_file(paths["task_dir"])
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    assert payload == {
        "version": superloop.PHASE_PLAN_VERSION,
        "task_id": "phase-plan-task",
        "request_snapshot_ref": str(run_paths["request_file"]),
        "phases": [],
    }


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


def test_event_recorder_writes_sequenced_events(tmp_path: Path):
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


def test_validate_phase_plan_defaults_optional_lists_when_omitted():
    plan = superloop.validate_phase_plan(
        {
            "version": 1,
            "task_id": "optional-phase-task",
            "request_snapshot_ref": "request.md",
            "phases": [
                {
                    "phase_id": "phase-1",
                    "title": "Phase 1",
                    "objective": "First",
                    "in_scope": ["first"],
                    "deliverables": ["code"],
                    "status": "planned",
                }
            ],
        },
        "optional-phase-task",
    )

    phase = plan.phases[0]
    assert phase.out_of_scope == ()
    assert phase.dependencies == ()
    assert phase.acceptance_criteria == ()
    assert phase.risks == ()
    assert phase.rollback == ()


def test_validate_phase_plan_still_rejects_missing_required_lists():
    import pytest

    with pytest.raises(superloop.PhasePlanError, match=r"phases\[1\]\.in_scope must be a list\."):
        superloop.validate_phase_plan(
            {
                "version": 1,
                "task_id": "required-phase-task",
                "request_snapshot_ref": "request.md",
                "phases": [
                    {
                        "phase_id": "phase-1",
                        "title": "Phase 1",
                        "objective": "First",
                        "deliverables": ["code"],
                        "status": "planned",
                    }
                ],
            },
            "required-phase-task",
        )

    with pytest.raises(superloop.PhasePlanError, match=r"phases\[1\]\.deliverables must be a list\."):
        superloop.validate_phase_plan(
            {
                "version": 1,
                "task_id": "required-phase-task",
                "request_snapshot_ref": "request.md",
                "phases": [
                    {
                        "phase_id": "phase-1",
                        "title": "Phase 1",
                        "objective": "First",
                        "in_scope": ["first"],
                        "status": "planned",
                    }
                ],
            },
            "required-phase-task",
        )


def test_validate_phase_plan_still_requires_non_empty_required_lists():
    import pytest

    with pytest.raises(superloop.PhasePlanError, match=r"phases\[1\]\.deliverables must be a non-empty list\."):
        superloop.validate_phase_plan(
            {
                "version": 1,
                "task_id": "required-phase-task",
                "request_snapshot_ref": "request.md",
                "phases": [
                    {
                        "phase_id": "phase-1",
                        "title": "Phase 1",
                        "objective": "First",
                        "in_scope": ["first"],
                        "deliverables": [],
                        "status": "planned",
                    }
                ],
            },
            "required-phase-task",
        )

    with pytest.raises(superloop.PhasePlanError, match=r"phases\[1\]\.in_scope must be a non-empty list\."):
        superloop.validate_phase_plan(
            {
                "version": 1,
                "task_id": "required-phase-task",
                "request_snapshot_ref": "request.md",
                "phases": [
                    {
                        "phase_id": "phase-1",
                        "title": "Phase 1",
                        "objective": "First",
                        "in_scope": [],
                        "deliverables": ["code"],
                        "status": "planned",
                    }
                ],
            },
            "required-phase-task",
        )


def test_main_fatal_error_still_writes_terminal_event_without_summary(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
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
    assert not (run_dirs[0] / "summary.md").exists()


def test_try_commit_tracked_changes_warns_and_returns_false_on_commit_failure(tmp_path: Path, monkeypatch):
    warnings: list[str] = []

    def fake_run_git(args, cwd, allow_fail=False):
        assert cwd == tmp_path
        assert allow_fail is True
        if args[:2] == ["add", "--"]:
            return subprocess.CompletedProcess(["git", *args], 0, "", "")
        if args[:2] == ["status", "--porcelain"]:
            return subprocess.CompletedProcess(["git", *args], 0, " M .superloop/tasks/t/runs/run/events.jsonl\n", "")
        if args[:2] == ["commit", "-m"]:
            return subprocess.CompletedProcess(["git", *args], 1, "", "hook rejected commit")
        raise AssertionError(f"Unexpected git args: {args}")

    monkeypatch.setattr(superloop, "run_git", fake_run_git)
    monkeypatch.setattr(superloop, "warn", lambda msg: warnings.append(msg))

    committed = superloop.try_commit_tracked_changes(
        tmp_path,
        "superloop: finalize run artifacts (fatal_error)",
        [".superloop/tasks/t/runs/"],
    )

    assert committed is False
    assert any("Unable to commit final run artifacts" in msg for msg in warnings)


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


def test_latest_run_status_skips_malformed_event_lines(tmp_path: Path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        '{"event_type":"run_finished","status":"failed"}\n'
        '{"event_type":"run_finished","status":"success"}\n'
        '{"event_type":"run_finished","status":"incomplete"\n',
        encoding="utf-8",
    )
    assert latest_run_status(events) == "success"


def test_verifier_scope_violations_only_ignores_runtime_bookkeeping_artifacts():
    task_root = ".superloop/tasks/task-1"
    delta = {
        ".superloop/tasks/task-1/runs/run-1/events.jsonl",
        ".superloop/tasks/task-1/raw_phase_log.md",
        ".superloop/tasks/task-1/decisions.txt",
        ".superloop/tasks/task-1/implement/notes.md",
        ".superloop/tasks/task-1/test/output.md",
    }
    assert verifier_scope_violations("implement", delta, task_root) == [
        ".superloop/tasks/task-1/decisions.txt",
        ".superloop/tasks/task-1/test/output.md",
    ]


def test_verifier_scope_violations_does_not_ignore_artifact_prefixed_files():
    task_root = ".superloop/tasks/task-1"
    delta = {
        ".superloop/tasks/task-1/task.json.bak",
        ".superloop/tasks/task-1/runs-backup/log.jsonl",
    }
    assert verifier_scope_violations("implement", delta, task_root) == sorted(delta)

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
    install_fake_yaml(monkeypatch)
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


def test_ensure_workspace_creates_task_scoped_paths_without_task_local_prompts(tmp_path: Path):
    paths = ensure_workspace(
        root=tmp_path,
        task_id="my-task",
        product_intent="Implement feature X",
        intent_mode="replace",
    )

    task_dir = tmp_path / ".superloop" / "tasks" / "my-task"
    assert paths["task_dir"] == task_dir
    assert (task_dir / "task.json").exists()
    assert (task_dir / "decisions.txt").exists()
    assert not (task_dir / "run_log.md").exists()
    assert not (task_dir / "plan" / "prompt.md").exists()
    assert not (task_dir / "plan" / "verifier_prompt.md").exists()
    assert not (task_dir / "implement" / "prompt.md").exists()
    assert not (task_dir / "implement" / "verifier_prompt.md").exists()
    assert not (task_dir / "test" / "prompt.md").exists()
    assert not (task_dir / "test" / "verifier_prompt.md").exists()
    assert not phase_plan_file(task_dir).exists()
    assert not (task_dir / "context.md").exists()
    assert task_request_text(paths["task_meta_file"], paths["legacy_context_file"]) == "Implement feature X"




def test_ensure_workspace_fails_fast_when_prompt_template_missing(tmp_path: Path, monkeypatch):
    import pytest

    templates = tmp_path / "templates"
    templates.mkdir()
    for pair, role_files in superloop.PAIR_TEMPLATE_FILES.items():
        for role in ("producer", "verifier"):
            filename = role_files[role]
            (templates / filename).write_text(f"# {pair} {role}\n", encoding="utf-8")
        (templates / role_files["criteria"]).write_text(f"# {pair} criteria\n", encoding="utf-8")

    (templates / "plan_producer.md").unlink()
    monkeypatch.setattr(superloop, "TEMPLATES_DIR", templates)
    superloop.load_pair_templates.cache_clear()

    with pytest.raises(SystemExit):
        ensure_workspace(
            root=tmp_path,
            task_id="my-task",
            product_intent="Implement feature X",
            intent_mode="replace",
        )
    superloop.load_pair_templates.cache_clear()


def test_ensure_phase_plan_scaffold_restores_runtime_metadata_and_preserves_phases(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    task_dir = tmp_path / ".superloop" / "tasks" / "phase-plan-task"
    (task_dir / "plan").mkdir(parents=True)
    original_phases = [
        {
            "phase_id": "phase-1",
            "title": "Phase 1",
            "objective": "Build phase one",
            "in_scope": ["Implement phase one"],
            "deliverables": ["code"],
            "status": "planned",
        }
    ]
    phase_plan_file(task_dir).write_text(
        json.dumps(
            {
                "version": 999,
                "task_id": "wrong-task",
                "request_snapshot_ref": "wrong-request.md",
                "phases": original_phases,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    request_file = tmp_path / "request.md"
    request_file.write_text("Implement feature X\n", encoding="utf-8")

    plan_path = ensure_phase_plan_scaffold(task_dir, "phase-plan-task", request_file)

    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    assert payload["version"] == superloop.PHASE_PLAN_VERSION
    assert payload["task_id"] == "phase-plan-task"
    assert payload["request_snapshot_ref"] == str(request_file)
    assert payload["phases"] == original_phases


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
    request_file = tmp_path / "request.md"
    request_file.write_text("Implement feature X\n", encoding="utf-8")
    decisions_file = tmp_path / "decisions.txt"
    decisions_file.write_text("", encoding="utf-8")
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
        template_provenance="templates/implement_producer.md",
        rendered_template_text="Prompt body\n",
        request_file=request_file,
        run_raw_phase_log=tmp_path / "raw_phase_log.md",
        decisions_file=decisions_file,
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
        session_file=tmp_path / "runs" / "run-1" / "sessions" / "phases" / "phase-1.json",
    )

    assert "ACTIVE PHASE EXECUTION CONTRACT:" in prompt
    assert "phase_ids: phase-1" in prompt
    assert "Phase phase-1: Phase 1" in prompt
    assert f"AUTHORITATIVE SHARED DECISIONS FILE: {decisions_file}" in prompt
    assert "AUTHORITATIVE ACTIVE SESSION FILE: " in prompt
    assert "sessions/phases/phase-1.json" in prompt
    assert "session.json" not in prompt


def test_build_phase_prompt_requires_explicit_session_file(tmp_path: Path):
    import pytest

    request_file = tmp_path / "request.md"
    request_file.write_text("Implement feature X\n", encoding="utf-8")
    decisions_file = tmp_path / "decisions.txt"
    decisions_file.write_text("", encoding="utf-8")

    with pytest.raises(TypeError):
        build_phase_prompt(
            cwd=tmp_path,
            template_provenance="templates/plan_producer.md",
            rendered_template_text="Prompt body\n",
            request_file=request_file,
            run_raw_phase_log=tmp_path / "raw_phase_log.md",
            decisions_file=decisions_file,
            pair_name="plan",
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
        )


def test_run_codex_phase_logs_shared_template_provenance(tmp_path: Path, monkeypatch):
    request_file = tmp_path / "request.md"
    request_file.write_text("Implement feature X\n", encoding="utf-8")
    task_raw_phase_log = tmp_path / "task_raw_phase_log.md"
    task_raw_phase_log.write_text("# task raw\n", encoding="utf-8")
    run_raw_phase_log = tmp_path / "run_raw_phase_log.md"
    run_raw_phase_log.write_text("# run raw\n", encoding="utf-8")
    decisions_file = tmp_path / "decisions.txt"
    decisions_file.write_text("", encoding="utf-8")
    events_file = tmp_path / "events.jsonl"
    events_file.write_text("", encoding="utf-8")
    session_file = tmp_path / "session.json"
    superloop.save_session_state(
        session_file,
        SessionState(
            mode="persistent",
            thread_id=None,
            pending_clarification_note=None,
            created_at="2026-03-18T00:00:00Z",
        ),
    )
    artifact_bundle = superloop.ArtifactBundle(
        pair="plan",
        scope="task-global",
        artifact_dir=tmp_path,
        criteria_file=tmp_path / "criteria.md",
        feedback_file=tmp_path / "feedback.md",
        artifact_files={},
        allowed_verifier_prefixes=(),
    )

    raw_exec_output = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "agent output"}}),
        ]
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout=raw_exec_output)

    monkeypatch.setattr(superloop.subprocess, "run", fake_run)

    template_provenance = str(superloop.pair_template_path("plan", "producer"))
    stdout = superloop.run_codex_phase(
        fake_codex_command(),
        tmp_path,
        template_provenance,
        "Prompt body\n",
        "producer",
        "plan",
        1,
        1,
        "run-1",
        request_file,
        session_file,
        artifact_bundle,
        run_raw_phase_log,
        task_raw_phase_log,
        events_file,
        tmp_path,
        decisions_file,
    )

    assert stdout == "agent output"
    assert f"template={template_provenance}" in task_raw_phase_log.read_text(encoding="utf-8")
    assert f"template={template_provenance}" in run_raw_phase_log.read_text(encoding="utf-8")
    assert "prompt.md" not in task_raw_phase_log.read_text(encoding="utf-8")
    assert "prompt.md" not in run_raw_phase_log.read_text(encoding="utf-8")


def test_tracked_superloop_paths_excludes_runs_directory():
    tracked = superloop.tracked_superloop_paths(".superloop/tasks/task-1", "implement")
    assert ".superloop/tasks/task-1/runs/" not in tracked
    assert ".superloop/tasks/task-1/decisions.txt" in tracked
    assert ".superloop/tasks/task-1/implement/" in tracked


def test_execute_pair_cycles_excludes_run_outputs_from_snapshot_delta_commits(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(tmp_path, "task-1", "Implement feature X", "replace")
    run_paths = create_run_paths(paths["runs_dir"], "run-1", "Implement feature X")
    recorder = EventRecorder(run_id="run-1", events_file=run_paths["events_file"])

    phase_dir = paths["task_dir"] / "implement" / "phases" / "phase-1"
    phase_dir.mkdir(parents=True, exist_ok=True)
    criteria_file = phase_dir / "criteria.md"
    feedback_file = phase_dir / "feedback.md"
    criteria_file.write_text("- [x] done\n", encoding="utf-8")
    feedback_file.write_text("# feedback\n", encoding="utf-8")

    selection = superloop.ResolvedPhaseSelection(
        phase_mode="single",
        phase_ids=("phase-1",),
        phases=(
            superloop.PhasePlanPhase(
                phase_id="phase-1",
                title="Phase 1",
                objective="Deliver phase 1",
                in_scope=("code path A",),
                out_of_scope=(),
                dependencies=(),
                acceptance_criteria=(superloop.PhasePlanCriterion(id="AC-1", text="done"),),
                deliverables=("code",),
                risks=(),
                rollback=(),
                status="planned",
            ),
        ),
        explicit=True,
    )
    bundle = superloop.ArtifactBundle(
        pair="implement",
        scope="phase-local",
        artifact_dir=phase_dir,
        criteria_file=criteria_file,
        feedback_file=feedback_file,
        artifact_files={"criteria.md": criteria_file, "feedback.md": feedback_file},
        allowed_verifier_prefixes=(f"{paths['task_root_rel']}/implement/phases/phase-1/",),
        phase_id="phase-1",
        phase_dir_key="phase-1",
        phase_title="Phase 1",
    )

    producer_control = superloop.LoopControl(question=None, promise=None, source="canonical", raw_payload=None)
    verifier_control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_COMPLETE,
        source="canonical",
        raw_payload=None,
    )
    parse_results = [producer_control, verifier_control]
    delta_by_snapshot = {
        "producer": {
            ".superloop/tasks/task-1/runs/run-1/events.jsonl",
            "src/feature.py",
        },
        "verifier": {
            ".superloop/tasks/task-1/implement/phases/phase-1/feedback.md",
        },
    }
    committed_paths: list[tuple[str, set[str]]] = []

    monkeypatch.setattr(superloop, "commit_tracked_changes", lambda *args, **kwargs: False)
    monkeypatch.setattr(superloop, "phase_snapshot_ref", lambda *_args, **_kwargs: "producer" if not committed_paths else "verifier")
    monkeypatch.setattr(
        superloop,
        "run_codex_phase",
        lambda *args, **kwargs: "<loop-control></loop-control>",
    )
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: parse_results.pop(0))
    monkeypatch.setattr(
        superloop,
        "changed_paths_from_snapshot",
        lambda _root, snapshot, tracked_paths=None: set(delta_by_snapshot[snapshot]),
    )
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop,
        "commit_paths",
        lambda _root, message, paths: committed_paths.append((message, set(paths))) or True,
    )

    status, code = execute_pair_cycles(
        pair_cfg=PairConfig(name="implement", enabled=True, max_iterations=1),
        pair="implement",
        artifact_bundle=bundle,
        session_file=run_paths["plan_session_file"],
        root=tmp_path,
        codex_command=fake_codex_command(),
        run_id="run-1",
        run_paths=run_paths,
        paths=paths,
        recorder=recorder,
        task_root_rel=str(paths["task_root_rel"]),
        use_git=True,
        active_phase_selection=selection,
        enabled_pairs=["implement"],
        args=argparse.Namespace(full_auto_answers=False),
        resume_checkpoint=None,
        use_resume_state=False,
    )

    assert (status, code) == ("complete", 0)
    assert [message for message, _paths in committed_paths] == [
        "superloop: producer edits (implement #1)",
        "superloop: pair complete (implement)",
    ]
    assert all(
        not any(path.startswith(".superloop/tasks/task-1/runs/") for path in paths)
        for _message, paths in committed_paths
    )
    assert "src/feature.py" in committed_paths[0][1]
    assert ".superloop/tasks/task-1/implement/phases/phase-1/feedback.md" in committed_paths[1][1]


def test_execute_pair_cycles_excludes_run_outputs_from_blocked_commit(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(tmp_path, "task-1", "Implement feature X", "replace")
    run_paths = create_run_paths(paths["runs_dir"], "run-1", "Implement feature X")
    recorder = EventRecorder(run_id="run-1", events_file=run_paths["events_file"])

    phase_dir = paths["task_dir"] / "implement" / "phases" / "phase-1"
    phase_dir.mkdir(parents=True, exist_ok=True)
    criteria_file = phase_dir / "criteria.md"
    feedback_file = phase_dir / "feedback.md"
    criteria_file.write_text("- [x] done\n", encoding="utf-8")
    feedback_file.write_text("# feedback\n", encoding="utf-8")

    selection = superloop.ResolvedPhaseSelection(
        phase_mode="single",
        phase_ids=("phase-1",),
        phases=(
            superloop.PhasePlanPhase(
                phase_id="phase-1",
                title="Phase 1",
                objective="Deliver phase 1",
                in_scope=("code path A",),
                out_of_scope=(),
                dependencies=(),
                acceptance_criteria=(superloop.PhasePlanCriterion(id="AC-1", text="done"),),
                deliverables=("code",),
                risks=(),
                rollback=(),
                status="planned",
            ),
        ),
        explicit=True,
    )
    bundle = superloop.ArtifactBundle(
        pair="implement",
        scope="phase-local",
        artifact_dir=phase_dir,
        criteria_file=criteria_file,
        feedback_file=feedback_file,
        artifact_files={"criteria.md": criteria_file, "feedback.md": feedback_file},
        allowed_verifier_prefixes=(f"{paths['task_root_rel']}/implement/phases/phase-1/",),
        phase_id="phase-1",
        phase_dir_key="phase-1",
        phase_title="Phase 1",
    )

    producer_control = superloop.LoopControl(question=None, promise=None, source="canonical", raw_payload=None)
    verifier_control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_BLOCKED,
        source="canonical",
        raw_payload=None,
    )
    parse_results = [producer_control, verifier_control]
    delta_by_snapshot = {
        "producer": {
            ".superloop/tasks/task-1/runs/run-1/events.jsonl",
            "src/feature.py",
        },
        "verifier": {
            ".superloop/tasks/task-1/implement/phases/phase-1/feedback.md",
        },
    }
    committed_paths: list[tuple[str, set[str]]] = []

    monkeypatch.setattr(superloop, "commit_tracked_changes", lambda *args, **kwargs: False)
    monkeypatch.setattr(superloop, "phase_snapshot_ref", lambda *_args, **_kwargs: "producer" if not committed_paths else "verifier")
    monkeypatch.setattr(
        superloop,
        "run_codex_phase",
        lambda *args, **kwargs: "<loop-control></loop-control>",
    )
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: parse_results.pop(0))
    monkeypatch.setattr(
        superloop,
        "changed_paths_from_snapshot",
        lambda _root, snapshot, tracked_paths=None: set(delta_by_snapshot[snapshot]),
    )
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        superloop,
        "commit_paths",
        lambda _root, message, paths: committed_paths.append((message, set(paths))) or True,
    )

    status, code = execute_pair_cycles(
        pair_cfg=PairConfig(name="implement", enabled=True, max_iterations=1),
        pair="implement",
        artifact_bundle=bundle,
        session_file=run_paths["plan_session_file"],
        root=tmp_path,
        codex_command=fake_codex_command(),
        run_id="run-1",
        run_paths=run_paths,
        paths=paths,
        recorder=recorder,
        task_root_rel=str(paths["task_root_rel"]),
        use_git=True,
        active_phase_selection=selection,
        enabled_pairs=["implement"],
        args=argparse.Namespace(full_auto_answers=False),
        resume_checkpoint=None,
        use_resume_state=False,
    )

    assert (status, code) == ("blocked", 2)
    assert [message for message, _paths in committed_paths] == [
        "superloop: producer edits (implement #1)",
        "superloop: blocked (implement #1)",
    ]
    assert all(
        not any(path.startswith(".superloop/tasks/task-1/runs/") for path in paths)
        for _message, paths in committed_paths
    )
    assert "src/feature.py" in committed_paths[0][1]
    assert ".superloop/tasks/task-1/implement/phases/phase-1/feedback.md" in committed_paths[1][1]


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


def test_execute_pair_cycles_failure_commit_uses_tracked_pair_paths_only(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(tmp_path, "task-1", "Implement feature X", "replace")
    run_paths = create_run_paths(paths["runs_dir"], "run-1", "Implement feature X")
    recorder = EventRecorder(run_id="run-1", events_file=run_paths["events_file"])

    phase_dir = paths["task_dir"] / "implement" / "phases" / "phase-1"
    phase_dir.mkdir(parents=True, exist_ok=True)
    criteria_file = phase_dir / "criteria.md"
    feedback_file = phase_dir / "feedback.md"
    criteria_file.write_text("- [x] done\n", encoding="utf-8")
    feedback_file.write_text("# feedback\n", encoding="utf-8")

    selection = superloop.ResolvedPhaseSelection(
        phase_mode="single",
        phase_ids=("phase-1",),
        phases=(
            superloop.PhasePlanPhase(
                phase_id="phase-1",
                title="Phase 1",
                objective="Deliver phase 1",
                in_scope=("code path A",),
                out_of_scope=(),
                dependencies=(),
                acceptance_criteria=(superloop.PhasePlanCriterion(id="AC-1", text="done"),),
                deliverables=("code",),
                risks=(),
                rollback=(),
                status="planned",
            ),
        ),
        explicit=True,
    )
    bundle = superloop.ArtifactBundle(
        pair="implement",
        scope="phase-local",
        artifact_dir=phase_dir,
        criteria_file=criteria_file,
        feedback_file=feedback_file,
        artifact_files={"criteria.md": criteria_file, "feedback.md": feedback_file},
        allowed_verifier_prefixes=(f"{paths['task_root_rel']}/implement/phases/phase-1/",),
        phase_id="phase-1",
        phase_dir_key="phase-1",
        phase_title="Phase 1",
    )

    producer_control = superloop.LoopControl(question=None, promise=None, source="canonical", raw_payload=None)
    verifier_control = superloop.LoopControl(
        question=None,
        promise=superloop.PROMISE_INCOMPLETE,
        source="canonical",
        raw_payload=None,
    )
    parse_results = [producer_control, verifier_control]
    delta_by_snapshot = {
        "producer": {
            ".superloop/tasks/task-1/runs/run-1/events.jsonl",
            "src/feature.py",
        },
        "verifier": {
            ".superloop/tasks/task-1/implement/phases/phase-1/feedback.md",
        },
    }
    committed_paths: list[tuple[str, set[str]]] = []

    monkeypatch.setattr(superloop, "commit_tracked_changes", lambda *args, **kwargs: False)
    monkeypatch.setattr(superloop, "phase_snapshot_ref", lambda *_args, **_kwargs: "producer" if not committed_paths else "verifier")
    monkeypatch.setattr(superloop, "run_codex_phase", lambda *args, **kwargs: "<loop-control></loop-control>")
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: parse_results.pop(0))
    monkeypatch.setattr(
        superloop,
        "changed_paths_from_snapshot",
        lambda _root, snapshot, tracked_paths=None: set(delta_by_snapshot[snapshot]),
    )
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        superloop,
        "commit_paths",
        lambda _root, message, paths: committed_paths.append((message, set(paths))) or True,
    )
    monkeypatch.setattr(superloop.time, "sleep", lambda _seconds: None)

    status, code = execute_pair_cycles(
        pair_cfg=PairConfig(name="implement", enabled=True, max_iterations=1),
        pair="implement",
        artifact_bundle=bundle,
        session_file=run_paths["plan_session_file"],
        root=tmp_path,
        codex_command=fake_codex_command(),
        run_id="run-1",
        run_paths=run_paths,
        paths=paths,
        recorder=recorder,
        task_root_rel=str(paths["task_root_rel"]),
        use_git=True,
        active_phase_selection=selection,
        enabled_pairs=["implement"],
        args=argparse.Namespace(full_auto_answers=False),
        resume_checkpoint=None,
        use_resume_state=False,
    )

    assert (status, code) == ("failed", 1)
    assert [message for message, _paths in committed_paths] == [
        "superloop: producer edits (implement #1)",
        "superloop: verifier feedback (implement #1)",
        "superloop: failed (implement max iterations)",
    ]
    assert committed_paths[-1][1] == set(superloop.tracked_superloop_paths(".superloop/tasks/task-1", "implement"))
    assert all(
        not any(
            path.endswith("run_log.md") or path.endswith("summary.md") or path.startswith(".superloop/tasks/task-1/runs/")
            for path in paths
        )
        for _message, paths in committed_paths
    )


def test_ensure_workspace_does_not_create_task_local_prompts_on_repeat_calls(tmp_path: Path):
    paths = ensure_workspace(
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

    assert not (paths["task_dir"] / "plan" / "prompt.md").exists()
    assert not (paths["task_dir"] / "plan" / "verifier_prompt.md").exists()

def test_append_clarification_logs_to_raw_phase_log_and_updates_session(tmp_path: Path):
    run_paths = create_run_paths(tmp_path, "run-clarify", "Initial request")
    task_raw_log = tmp_path / "task_raw_phase_log.md"
    task_raw_log.write_text("# Task Raw\n", encoding="utf-8")
    decisions = tmp_path / "decisions.txt"
    decisions.write_text("", encoding="utf-8")

    append_clarification(
        run_paths["raw_phase_log"],
        task_raw_log,
        decisions,
        run_paths["plan_session_file"],
        pair="plan",
        phase_id="task-global",
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
    session_payload = json.loads(run_paths["plan_session_file"].read_text(encoding="utf-8"))
    assert "Approved answer" in session_payload["pending_clarification_note"]
    decisions_text = decisions.read_text(encoding="utf-8")
    assert 'entry="questions"' in decisions_text
    assert 'entry="answers"' in decisions_text
    assert 'source="human"' in decisions_text


def test_format_question_preserves_inline_best_supposition_text():
    control = superloop.LoopControl(
        question=LoopQuestion(
            text="Need confirmation?\nBest supposition: proceed safely",
            best_supposition="proceed safely",
        ),
        promise=None,
        source="canonical",
        raw_payload=None,
    )

    assert superloop.format_question(control) == "Need confirmation?\nBest supposition: proceed safely"


def test_format_question_renders_best_supposition_fallback_when_missing_from_text():
    control = superloop.LoopControl(
        question=LoopQuestion(
            text="Need confirmation?",
            best_supposition="proceed safely",
        ),
        promise=None,
        source="canonical",
        raw_payload=None,
    )

    assert superloop.format_question(control) == "Need confirmation?\nBest supposition: proceed safely"


def test_execute_pair_cycles_removes_empty_producer_block_before_runtime_question_blocks(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(tmp_path, "task-1", "Implement feature X", "replace")
    run_paths = create_run_paths(paths["runs_dir"], "run-1", "Implement feature X")
    recorder = EventRecorder(run_id="run-1", events_file=run_paths["events_file"])

    phase_dir = paths["task_dir"] / "implement" / "phases" / "phase-1"
    phase_dir.mkdir(parents=True, exist_ok=True)
    criteria_file = phase_dir / "criteria.md"
    feedback_file = phase_dir / "feedback.md"
    criteria_file.write_text("- [x] done\n", encoding="utf-8")
    feedback_file.write_text("# feedback\n", encoding="utf-8")

    selection = superloop.ResolvedPhaseSelection(
        phase_mode="single",
        phase_ids=("phase-1",),
        phases=(
            superloop.PhasePlanPhase(
                phase_id="phase-1",
                title="Phase 1",
                objective="Deliver phase 1",
                in_scope=("code path A",),
                out_of_scope=(),
                dependencies=(),
                acceptance_criteria=(superloop.PhasePlanCriterion(id="AC-1", text="done"),),
                deliverables=("code",),
                risks=(),
                rollback=(),
                status="planned",
            ),
        ),
        explicit=True,
    )
    bundle = superloop.ArtifactBundle(
        pair="implement",
        scope="phase-local",
        artifact_dir=phase_dir,
        criteria_file=criteria_file,
        feedback_file=feedback_file,
        artifact_files={"criteria.md": criteria_file, "feedback.md": feedback_file},
        allowed_verifier_prefixes=(f"{paths['task_root_rel']}/implement/phases/phase-1/",),
        phase_id="phase-1",
        phase_dir_key="phase-1",
        phase_title="Phase 1",
    )

    observed_headers: list[str] = []
    question_stdout = (
        '<loop-control>\n'
        '{"schema":"docloop.loop_control/v1","kind":"question","question":"Need confirmation?\\nBest supposition: proceed safely.","best_supposition":"proceed safely"}\n'
        '</loop-control>'
    )

    def fake_run_codex_phase(*args, **kwargs):
        phase_name = args[4]
        current = paths["decisions_file"].read_text(encoding="utf-8")
        if phase_name == "producer":
            observed_headers.append(current)
            assert 'owner="implementer"' in current
            return question_stdout
        raise AssertionError("Verifier should not run after a producer clarification question.")

    class StopAfterClarification(RuntimeError):
        pass

    original_append_clarification = superloop.append_clarification

    def stop_after_clarification(*args, **kwargs):
        original_append_clarification(*args, **kwargs)
        raise StopAfterClarification

    monkeypatch.setattr(superloop, "commit_tracked_changes", lambda *args, **kwargs: False)
    monkeypatch.setattr(superloop, "run_codex_phase", fake_run_codex_phase)
    monkeypatch.setattr(superloop, "ask_human", lambda question_text: "Approved answer")
    monkeypatch.setattr(superloop, "append_clarification", stop_after_clarification)

    with pytest.raises(StopAfterClarification):
        execute_pair_cycles(
            pair_cfg=PairConfig(name="implement", enabled=True, max_iterations=1),
            pair="implement",
            artifact_bundle=bundle,
            session_file=run_paths["plan_session_file"],
            root=tmp_path,
            codex_command=fake_codex_command(),
            run_id="run-1",
            run_paths=run_paths,
            paths=paths,
            recorder=recorder,
            task_root_rel=str(paths["task_root_rel"]),
            use_git=False,
            active_phase_selection=selection,
            enabled_pairs=["implement"],
            args=argparse.Namespace(full_auto_answers=False),
            resume_checkpoint=None,
            use_resume_state=False,
        )

    decisions_text = paths["decisions_file"].read_text(encoding="utf-8")
    assert 'owner="implementer"' not in decisions_text
    assert 'entry="questions"' in decisions_text
    assert 'entry="answers"' in decisions_text
    assert 'qa_seq="1"' in decisions_text
    assert 'turn_seq="1"' in decisions_text
    assert "Need confirmation?" in decisions_text
    assert "Approved answer" in decisions_text


def test_execute_pair_cycles_preserves_non_empty_producer_block_on_question_turn(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(tmp_path, "task-1", "Implement feature X", "replace")
    run_paths = create_run_paths(paths["runs_dir"], "run-1", "Implement feature X")
    recorder = EventRecorder(run_id="run-1", events_file=run_paths["events_file"])

    phase_dir = paths["task_dir"] / "implement" / "phases" / "phase-1"
    phase_dir.mkdir(parents=True, exist_ok=True)
    criteria_file = phase_dir / "criteria.md"
    feedback_file = phase_dir / "feedback.md"
    criteria_file.write_text("- [x] done\n", encoding="utf-8")
    feedback_file.write_text("# feedback\n", encoding="utf-8")

    selection = superloop.ResolvedPhaseSelection(
        phase_mode="single",
        phase_ids=("phase-1",),
        phases=(
            superloop.PhasePlanPhase(
                phase_id="phase-1",
                title="Phase 1",
                objective="Deliver phase 1",
                in_scope=("code path A",),
                out_of_scope=(),
                dependencies=(),
                acceptance_criteria=(superloop.PhasePlanCriterion(id="AC-1", text="done"),),
                deliverables=("code",),
                risks=(),
                rollback=(),
                status="planned",
            ),
        ),
        explicit=True,
    )
    bundle = superloop.ArtifactBundle(
        pair="implement",
        scope="phase-local",
        artifact_dir=phase_dir,
        criteria_file=criteria_file,
        feedback_file=feedback_file,
        artifact_files={"criteria.md": criteria_file, "feedback.md": feedback_file},
        allowed_verifier_prefixes=(f"{paths['task_root_rel']}/implement/phases/phase-1/",),
        phase_id="phase-1",
        phase_dir_key="phase-1",
        phase_title="Phase 1",
    )

    question_stdout = (
        '<loop-control>\n'
        '{"schema":"docloop.loop_control/v1","kind":"question","question":"Need confirmation?\\nBest supposition: proceed safely.","best_supposition":"proceed safely"}\n'
        '</loop-control>'
    )

    def fake_run_codex_phase(*args, **kwargs):
        phase_name = args[4]
        if phase_name != "producer":
            raise AssertionError("Verifier should not run after a producer clarification question.")
        with paths["decisions_file"].open("a", encoding="utf-8") as handle:
            handle.write("Keep runtime-created producer header when body is non-empty\n")
        return question_stdout

    class StopAfterClarification(RuntimeError):
        pass

    original_append_clarification = superloop.append_clarification

    def stop_after_clarification(*args, **kwargs):
        original_append_clarification(*args, **kwargs)
        raise StopAfterClarification

    monkeypatch.setattr(superloop, "commit_tracked_changes", lambda *args, **kwargs: False)
    monkeypatch.setattr(superloop, "run_codex_phase", fake_run_codex_phase)
    monkeypatch.setattr(superloop, "ask_human", lambda question_text: "Approved answer")
    monkeypatch.setattr(superloop, "append_clarification", stop_after_clarification)

    with pytest.raises(StopAfterClarification):
        execute_pair_cycles(
            pair_cfg=PairConfig(name="implement", enabled=True, max_iterations=1),
            pair="implement",
            artifact_bundle=bundle,
            session_file=run_paths["plan_session_file"],
            root=tmp_path,
            codex_command=fake_codex_command(),
            run_id="run-1",
            run_paths=run_paths,
            paths=paths,
            recorder=recorder,
            task_root_rel=str(paths["task_root_rel"]),
            use_git=False,
            active_phase_selection=selection,
            enabled_pairs=["implement"],
            args=argparse.Namespace(full_auto_answers=False),
            resume_checkpoint=None,
            use_resume_state=False,
        )

    blocks = superloop.parse_decisions_headers(paths["decisions_file"].read_text(encoding="utf-8"))
    assert [block.attrs.get("owner") for block in blocks] == ["implementer", "runtime", "runtime"]
    assert [block.attrs.get("entry") for block in blocks] == [None, "questions", "answers"]
    assert blocks[0].body == "Keep runtime-created producer header when body is non-empty\n"
    assert blocks[0].attrs["turn_seq"] == blocks[1].attrs["turn_seq"] == blocks[2].attrs["turn_seq"] == "1"
    assert blocks[1].attrs["qa_seq"] == blocks[2].attrs["qa_seq"] == "1"


def test_execute_pair_cycles_retries_malformed_producer_loop_control_once(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(tmp_path, "task-1", "Implement feature X", "replace")
    run_paths = create_run_paths(paths["runs_dir"], "run-1", "Implement feature X")
    recorder = EventRecorder(run_id="run-1", events_file=run_paths["events_file"])

    phase_dir = paths["task_dir"] / "implement" / "phases" / "phase-1"
    phase_dir.mkdir(parents=True, exist_ok=True)
    criteria_file = phase_dir / "criteria.md"
    feedback_file = phase_dir / "feedback.md"
    criteria_file.write_text("- [x] done\n", encoding="utf-8")
    feedback_file.write_text("# feedback\n", encoding="utf-8")

    selection = superloop.ResolvedPhaseSelection(
        phase_mode="single",
        phase_ids=("phase-1",),
        phases=(
            superloop.PhasePlanPhase(
                phase_id="phase-1",
                title="Phase 1",
                objective="Deliver phase 1",
                in_scope=("code path A",),
                out_of_scope=(),
                dependencies=(),
                acceptance_criteria=(superloop.PhasePlanCriterion(id="AC-1", text="done"),),
                deliverables=("code",),
                risks=(),
                rollback=(),
                status="planned",
            ),
        ),
        explicit=True,
    )
    bundle = superloop.ArtifactBundle(
        pair="implement",
        scope="phase-local",
        artifact_dir=phase_dir,
        criteria_file=criteria_file,
        feedback_file=feedback_file,
        artifact_files={"criteria.md": criteria_file, "feedback.md": feedback_file},
        allowed_verifier_prefixes=(f"{paths['task_root_rel']}/implement/phases/phase-1/",),
        phase_id="phase-1",
        phase_dir_key="phase-1",
        phase_title="Phase 1",
    )

    question_stdout = (
        '<loop-control>\n'
        '{"schema":"docloop.loop_control/v1","kind":"question","question":"Need confirmation?","best_supposition":"proceed safely"}\n'
        '</loop-control>'
    )
    producer_calls = 0
    asked_questions: list[str] = []

    def fake_run_codex_phase(*args, **kwargs):
        nonlocal producer_calls
        phase_name = args[4]
        assert phase_name == "producer"
        producer_calls += 1
        session_payload = json.loads(Path(args[10]).read_text(encoding="utf-8"))
        if producer_calls == 1:
            assert session_payload["pending_clarification_note"] is None
            return "<loop-control>{not-json}</loop-control>"
        assert "Loop-control parse feedback" in session_payload["pending_clarification_note"]
        assert "Invalid canonical loop-control JSON" in session_payload["pending_clarification_note"]
        session_payload["pending_clarification_note"] = None
        Path(args[10]).write_text(json.dumps(session_payload, indent=2) + "\n", encoding="utf-8")
        return question_stdout

    class StopAfterClarification(RuntimeError):
        pass

    original_append_clarification = superloop.append_clarification

    def stop_after_clarification(*args, **kwargs):
        original_append_clarification(*args, **kwargs)
        raise StopAfterClarification

    def fake_ask_human(question_text: str) -> str:
        asked_questions.append(question_text)
        return "Approved answer"

    monkeypatch.setattr(superloop, "commit_tracked_changes", lambda *args, **kwargs: False)
    monkeypatch.setattr(superloop, "run_codex_phase", fake_run_codex_phase)
    monkeypatch.setattr(superloop, "ask_human", fake_ask_human)
    monkeypatch.setattr(superloop, "append_clarification", stop_after_clarification)

    with pytest.raises(StopAfterClarification):
        execute_pair_cycles(
            pair_cfg=PairConfig(name="implement", enabled=True, max_iterations=1),
            pair="implement",
            artifact_bundle=bundle,
            session_file=run_paths["plan_session_file"],
            root=tmp_path,
            codex_command=fake_codex_command(),
            run_id="run-1",
            run_paths=run_paths,
            paths=paths,
            recorder=recorder,
            task_root_rel=str(paths["task_root_rel"]),
            use_git=False,
            active_phase_selection=selection,
            enabled_pairs=["implement"],
            args=argparse.Namespace(full_auto_answers=False),
            resume_checkpoint=None,
            use_resume_state=False,
        )

    assert producer_calls == 2
    assert asked_questions == ["Need confirmation?\nBest supposition: proceed safely"]
    run_raw_text = run_paths["raw_phase_log"].read_text(encoding="utf-8")
    assert "entry=loop_control_retry" in run_raw_text
    assert "Invalid canonical loop-control JSON" in run_raw_text


def test_execute_pair_cycles_retries_malformed_verifier_loop_control_once(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(tmp_path, "task-1", "Implement feature X", "replace")
    run_paths = create_run_paths(paths["runs_dir"], "run-1", "Implement feature X")
    recorder = EventRecorder(run_id="run-1", events_file=run_paths["events_file"])

    phase_dir = paths["task_dir"] / "implement" / "phases" / "phase-1"
    phase_dir.mkdir(parents=True, exist_ok=True)
    criteria_file = phase_dir / "criteria.md"
    feedback_file = phase_dir / "feedback.md"
    criteria_file.write_text("- [x] done\n", encoding="utf-8")
    feedback_file.write_text("# feedback\n", encoding="utf-8")

    selection = superloop.ResolvedPhaseSelection(
        phase_mode="single",
        phase_ids=("phase-1",),
        phases=(
            superloop.PhasePlanPhase(
                phase_id="phase-1",
                title="Phase 1",
                objective="Deliver phase 1",
                in_scope=("code path A",),
                out_of_scope=(),
                dependencies=(),
                acceptance_criteria=(superloop.PhasePlanCriterion(id="AC-1", text="done"),),
                deliverables=("code",),
                risks=(),
                rollback=(),
                status="planned",
            ),
        ),
        explicit=True,
    )
    bundle = superloop.ArtifactBundle(
        pair="implement",
        scope="phase-local",
        artifact_dir=phase_dir,
        criteria_file=criteria_file,
        feedback_file=feedback_file,
        artifact_files={"criteria.md": criteria_file, "feedback.md": feedback_file},
        allowed_verifier_prefixes=(f"{paths['task_root_rel']}/implement/phases/phase-1/",),
        phase_id="phase-1",
        phase_dir_key="phase-1",
        phase_title="Phase 1",
    )

    calls: list[str] = []

    def fake_run_codex_phase(*args, **kwargs):
        phase_name = args[4]
        session_payload = json.loads(Path(args[10]).read_text(encoding="utf-8"))
        calls.append(phase_name)
        if phase_name == "producer":
            assert session_payload["pending_clarification_note"] is None
            return "producer output"
        assert phase_name == "verifier"
        if calls.count("verifier") == 1:
            assert session_payload["pending_clarification_note"] is None
            return "<loop-control>{not-json}</loop-control>"
        assert "Loop-control parse feedback" in session_payload["pending_clarification_note"]
        assert "Invalid canonical loop-control JSON" in session_payload["pending_clarification_note"]
        session_payload["pending_clarification_note"] = None
        Path(args[10]).write_text(json.dumps(session_payload, indent=2) + "\n", encoding="utf-8")
        return '<loop-control>{"schema":"docloop.loop_control/v1","kind":"promise","promise":"COMPLETE"}</loop-control>'

    monkeypatch.setattr(superloop, "commit_tracked_changes", lambda *args, **kwargs: False)
    monkeypatch.setattr(superloop, "run_codex_phase", fake_run_codex_phase)
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)

    status, code = execute_pair_cycles(
        pair_cfg=PairConfig(name="implement", enabled=True, max_iterations=1),
        pair="implement",
        artifact_bundle=bundle,
        session_file=run_paths["plan_session_file"],
        root=tmp_path,
        codex_command=fake_codex_command(),
        run_id="run-1",
        run_paths=run_paths,
        paths=paths,
        recorder=recorder,
        task_root_rel=str(paths["task_root_rel"]),
        use_git=False,
        active_phase_selection=selection,
        enabled_pairs=["implement"],
        args=argparse.Namespace(full_auto_answers=False),
        resume_checkpoint=None,
        use_resume_state=False,
    )

    assert (status, code) == ("complete", 0)
    assert calls == ["producer", "verifier", "verifier"]
    run_raw_text = run_paths["raw_phase_log"].read_text(encoding="utf-8")
    assert "entry=loop_control_retry" in run_raw_text
    assert "phase=verifier" in run_raw_text


def test_parse_phase_control_retries_once_before_failing():
    feedback_notes: list[str] = []

    with pytest.raises(SystemExit, match="1"):
        superloop.parse_phase_control(
            "<loop-control>{not-json}</loop-control>",
            "producer",
            "implement",
            retry_once=lambda feedback_note: feedback_notes.append(feedback_note)
            or "<loop-control>{still-not-json}</loop-control>",
        )

    assert len(feedback_notes) == 1
    assert "Loop-control parse feedback" in feedback_notes[0]
    assert "Invalid canonical loop-control JSON" in feedback_notes[0]


def test_execute_pair_cycles_does_not_precreate_verifier_decision_header(tmp_path: Path, monkeypatch):
    paths = ensure_workspace(tmp_path, "task-1", "Implement feature X", "replace")
    run_paths = create_run_paths(paths["runs_dir"], "run-1", "Implement feature X")
    recorder = EventRecorder(run_id="run-1", events_file=run_paths["events_file"])

    phase_dir = paths["task_dir"] / "implement" / "phases" / "phase-1"
    phase_dir.mkdir(parents=True, exist_ok=True)
    criteria_file = phase_dir / "criteria.md"
    feedback_file = phase_dir / "feedback.md"
    criteria_file.write_text("- [x] done\n", encoding="utf-8")
    feedback_file.write_text("# feedback\n", encoding="utf-8")

    selection = superloop.ResolvedPhaseSelection(
        phase_mode="single",
        phase_ids=("phase-1",),
        phases=(
            superloop.PhasePlanPhase(
                phase_id="phase-1",
                title="Phase 1",
                objective="Deliver phase 1",
                in_scope=("code path A",),
                out_of_scope=(),
                dependencies=(),
                acceptance_criteria=(superloop.PhasePlanCriterion(id="AC-1", text="done"),),
                deliverables=("code",),
                risks=(),
                rollback=(),
                status="planned",
            ),
        ),
        explicit=True,
    )
    bundle = superloop.ArtifactBundle(
        pair="implement",
        scope="phase-local",
        artifact_dir=phase_dir,
        criteria_file=criteria_file,
        feedback_file=feedback_file,
        artifact_files={"criteria.md": criteria_file, "feedback.md": feedback_file},
        allowed_verifier_prefixes=(f"{paths['task_root_rel']}/implement/phases/phase-1/",),
        phase_id="phase-1",
        phase_dir_key="phase-1",
        phase_title="Phase 1",
    )

    parse_results = [
        superloop.LoopControl(question=None, promise=None, source="canonical", raw_payload=None),
        superloop.LoopControl(
            question=None,
            promise=superloop.PROMISE_COMPLETE,
            source="canonical",
            raw_payload=None,
        ),
    ]

    def fake_run_codex_phase(*args, **kwargs):
        phase_name = args[4]
        decisions_text = paths["decisions_file"].read_text(encoding="utf-8")
        if phase_name == "producer":
            assert 'owner="implementer"' in decisions_text
            return "<loop-control></loop-control>"
        if phase_name == "verifier":
            assert decisions_text == ""
            return "<loop-control></loop-control>"
        raise AssertionError(f"Unexpected phase {phase_name}")

    monkeypatch.setattr(superloop, "commit_tracked_changes", lambda *args, **kwargs: False)
    monkeypatch.setattr(superloop, "run_codex_phase", fake_run_codex_phase)
    monkeypatch.setattr(superloop, "parse_phase_control", lambda *args, **kwargs: parse_results.pop(0))
    monkeypatch.setattr(superloop, "criteria_all_checked", lambda *_args, **_kwargs: True)

    status, code = execute_pair_cycles(
        pair_cfg=PairConfig(name="implement", enabled=True, max_iterations=1),
        pair="implement",
        artifact_bundle=bundle,
        session_file=run_paths["plan_session_file"],
        root=tmp_path,
        codex_command=fake_codex_command(),
        run_id="run-1",
        run_paths=run_paths,
        paths=paths,
        recorder=recorder,
        task_root_rel=str(paths["task_root_rel"]),
        use_git=False,
        active_phase_selection=selection,
        enabled_pairs=["implement"],
        args=argparse.Namespace(full_auto_answers=False),
        resume_checkpoint=None,
        use_resume_state=False,
    )

    assert (status, code) == ("complete", 0)
    assert paths["decisions_file"].read_text(encoding="utf-8") == ""


def test_main_resume_without_session_file_starts_new_conversation_and_logs_notice(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    paths = ensure_workspace(
        root=tmp_path,
        task_id="legacy-run",
        product_intent="Legacy request",
        intent_mode="replace",
    )
    run_paths = create_run_paths(paths["runs_dir"], "run-20260316T120000Z-abcdef12", "Legacy request")
    run_paths["plan_session_file"].unlink()
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
    session_payload = json.loads(run_paths["plan_session_file"].read_text(encoding="utf-8"))
    assert session_payload["mode"] == "persistent"
    raw_log_text = run_paths["raw_phase_log"].read_text(encoding="utf-8")
    assert "new conversation for the next phase" in raw_log_text
    assert "entry=session_recovery" in raw_log_text


def test_main_resume_with_missing_thread_id_starts_new_conversation_and_logs_notice(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    paths = ensure_workspace(
        root=tmp_path,
        task_id="legacy-run",
        product_intent="Legacy request",
        intent_mode="replace",
    )
    run_paths = create_run_paths(paths["runs_dir"], "run-20260316T120000Z-abcdef12", "Legacy request")
    run_paths["plan_session_file"].write_text(
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
    raw_log_text = run_paths["raw_phase_log"].read_text(encoding="utf-8")
    assert "new conversation for the next phase" in raw_log_text
    assert "entry=session_recovery" in raw_log_text


def test_main_resume_reconstructs_missing_request_from_legacy_context_not_current_task_request(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
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
    raw_log_text = run_paths["raw_phase_log"].read_text(encoding="utf-8")
    assert "Legacy request from original run" in request_text
    assert "Newer mutable task request" not in request_text
    assert "entry=request_recovery" in raw_log_text
    assert "reconstructed from the legacy task context" in raw_log_text


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
        lambda *args, **kwargs: calls.append((args[5], kwargs["active_phase_selection"].phase_ids[0])) or "<loop-control></loop-control>",
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


def test_main_plan_run_seeds_phase_plan_scaffold_after_request_snapshot_exists(tmp_path: Path, monkeypatch):
    install_fake_yaml(monkeypatch)
    seen: dict[str, object] = {}

    def fake_execute_pair_cycles(*, run_paths, paths, **kwargs):
        phase_plan_path = phase_plan_file(paths["task_dir"])
        seen["phase_plan_exists"] = phase_plan_path.exists()
        seen["request_exists"] = run_paths["request_file"].exists()
        seen["payload"] = json.loads(phase_plan_path.read_text(encoding="utf-8"))
        seen["request_file"] = str(run_paths["request_file"])
        return ("complete", 0)

    monkeypatch.setattr(superloop, "check_dependencies", lambda require_git=True: None)
    monkeypatch.setattr(superloop, "resolve_codex_exec_command", lambda model: fake_codex_command())
    monkeypatch.setattr(superloop, "execute_pair_cycles", fake_execute_pair_cycles)
    monkeypatch.setattr(superloop, "commit_tracked_changes", lambda *args, **kwargs: False)
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
            "plan-scaffold-task",
            "--max-iterations",
            "1",
            "--no-git",
        ],
    )

    exit_code = superloop.main()
    assert exit_code == 0
    assert seen["phase_plan_exists"] is True
    assert seen["request_exists"] is True
    assert seen["payload"] == {
        "version": superloop.PHASE_PLAN_VERSION,
        "task_id": "plan-scaffold-task",
        "request_snapshot_ref": seen["request_file"],
        "phases": [],
    }


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
        lambda *args, **kwargs: calls.append((args[5], args[4], kwargs["active_phase_selection"].phase_ids[0])) or "<loop-control></loop-control>",
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
        lambda *args, **kwargs: calls.append(args[5]) or "<loop-control></loop-control>",
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
        lambda *args, **kwargs: calls.append((args[5], kwargs["active_phase_selection"].phase_ids[0])) or "<loop-control></loop-control>",
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
