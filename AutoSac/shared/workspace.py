from __future__ import annotations

from pathlib import Path
import subprocess

from shared.config import Settings
from shared.contracts import (
    WORKSPACE_AGENTS_CONTENT,
    WORKSPACE_AGENTS_RELATIVE_PATH,
    WORKSPACE_BOOTSTRAP_VERSION,
    WORKSPACE_SKILL_CONTENT,
    WORKSPACE_SKILL_RELATIVE_PATH,
)


def _write_exact_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def _ensure_git_repo(workspace_dir: Path) -> None:
    if not (workspace_dir / ".git").exists():
        subprocess.run(["git", "init"], cwd=workspace_dir, check=True)

    subprocess.run(["git", "config", "user.name", "Stage 1 Triage Bootstrap"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "config", "user.email", "stage1-triage@example.invalid"], cwd=workspace_dir, check=True)

    head_check = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=workspace_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if head_check.returncode != 0:
        subprocess.run(["git", "commit", "--allow-empty", "-m", "Initial workspace commit"], cwd=workspace_dir, check=True)


def verify_workspace_mounts(settings: Settings) -> None:
    for label, path in (("app", settings.repo_mount_dir), ("manuals", settings.manuals_mount_dir)):
        if not path.exists():
            raise FileNotFoundError(f"Required {label} mount does not exist: {path}")
        if not path.is_dir():
            raise NotADirectoryError(f"Required {label} mount is not a directory: {path}")
        path.stat()


def verify_workspace_contract_paths(settings: Settings) -> None:
    verify_workspace_mounts(settings)
    for label, path in (
        ("workspace", settings.triage_workspace_dir),
        ("runs", settings.runs_dir),
    ):
        if not path.exists():
            raise FileNotFoundError(f"Required {label} directory does not exist: {path}")
        if not path.is_dir():
            raise NotADirectoryError(f"Required {label} directory is not a directory: {path}")
        path.stat()

    for label, path in (
        ("AGENTS.md", settings.workspace_agents_path),
        ("stage1-triage skill", settings.workspace_skill_path),
    ):
        if not path.exists():
            raise FileNotFoundError(f"Required {label} file does not exist: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"Required {label} path is not a file: {path}")
        path.stat()


def bootstrap_workspace(settings: Settings) -> None:
    settings.triage_workspace_dir.mkdir(parents=True, exist_ok=True)
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    verify_workspace_mounts(settings)
    _write_exact_file(settings.triage_workspace_dir / WORKSPACE_AGENTS_RELATIVE_PATH, WORKSPACE_AGENTS_CONTENT)
    _write_exact_file(settings.triage_workspace_dir / WORKSPACE_SKILL_RELATIVE_PATH, WORKSPACE_SKILL_CONTENT)
    _ensure_git_repo(settings.triage_workspace_dir)


def ensure_uploads_dir(settings: Settings) -> None:
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)


def workspace_contract_snapshot(settings: Settings) -> dict[str, str]:
    return {
        "bootstrap_version": WORKSPACE_BOOTSTRAP_VERSION,
        "workspace_dir": str(settings.triage_workspace_dir),
        "repo_mount_dir": str(settings.repo_mount_dir),
        "manuals_mount_dir": str(settings.manuals_mount_dir),
        "agents_path": str(settings.triage_workspace_dir / WORKSPACE_AGENTS_RELATIVE_PATH),
        "skill_path": str(settings.triage_workspace_dir / WORKSPACE_SKILL_RELATIVE_PATH),
    }
