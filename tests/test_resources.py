from __future__ import annotations

from pathlib import Path
from importlib.resources import files


def test_packaged_plan_template_present():
    template = files("autoloop").joinpath("templates/plan_producer.md")
    assert template.is_file()


def test_readme_links_claude_rollout_checklist_with_repo_relative_path():
    repo_root = Path(__file__).resolve().parents[1]
    readme_text = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "[docs/claude_rollout_checklist.md](docs/claude_rollout_checklist.md)" in readme_text
    assert "/workspace/superloop/docs/claude_rollout_checklist.md" not in readme_text
    assert (repo_root / "docs" / "claude_rollout_checklist.md").is_file()
