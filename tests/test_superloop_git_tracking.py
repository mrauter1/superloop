from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from superloop import changed_paths_from_snapshot, commit_paths, phase_snapshot_ref


def init_temp_git_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="superloop-test-"))
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.name", "Superloop Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "superloop-test@example.com"], cwd=root, check=True)
    return root


def commit_initial_file(root: Path, name: str = "tracked.txt", content: str = "init\n") -> Path:
    path = root / name
    path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return path


def test_dirty_file_edited_again_is_in_snapshot_delta():
    root = init_temp_git_repo()
    tracked = commit_initial_file(root)

    # Already dirty before snapshot
    tracked.write_text("init\nbefore\n", encoding="utf-8")
    snap = phase_snapshot_ref(root)

    # Edited again during phase
    tracked.write_text("init\nbefore\nafter\n", encoding="utf-8")
    delta = changed_paths_from_snapshot(root, snap)

    assert "tracked.txt" in delta


def test_new_untracked_file_after_baseline_is_in_delta():
    root = init_temp_git_repo()
    commit_initial_file(root)

    snap = phase_snapshot_ref(root)
    (root / "new_file.txt").write_text("new\n", encoding="utf-8")

    delta = changed_paths_from_snapshot(root, snap)
    assert "new_file.txt" in delta


def test_preexisting_untracked_file_is_not_reported_as_new_delta():
    root = init_temp_git_repo()
    commit_initial_file(root)

    # Exists before baseline snapshot
    (root / "already_untracked.txt").write_text("existing\n", encoding="utf-8")
    snap = phase_snapshot_ref(root)

    # Phase makes no new changes
    delta = changed_paths_from_snapshot(root, snap)
    assert "already_untracked.txt" not in delta


def test_commit_paths_commits_only_requested_paths():
    root = init_temp_git_repo()
    commit_initial_file(root)

    a = root / "a.txt"
    b = root / "b.txt"
    a.write_text("A\n", encoding="utf-8")
    b.write_text("B\n", encoding="utf-8")

    committed = commit_paths(root, "commit-a-only", ["a.txt"])
    assert committed is True

    show = subprocess.run(
        ["git", "show", "--name-only", "--pretty="],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.splitlines()
    committed_files = {line.strip() for line in show if line.strip()}

    assert "a.txt" in committed_files
    assert "b.txt" not in committed_files
