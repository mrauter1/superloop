from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def runtime_env(repo_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    src_path = str(repo_root / "src")
    env["PYTHONPATH"] = src_path if not existing_pythonpath else f"{src_path}:{existing_pythonpath}"
    return env


def test_python_m_autoloop_help_exits_zero():
    repo_root = Path(__file__).resolve().parents[1]
    package_cwd = repo_root / "src"

    result = subprocess.run(
        [sys.executable, "-m", "autoloop", "--help"],
        cwd=package_cwd,
        env=runtime_env(repo_root),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Autoloop" in result.stdout


def test_direct_main_py_help_exits_zero():
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(repo_root / "src" / "autoloop" / "main.py"), "--help"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Autoloop" in result.stdout


def test_runtime_entrypoint_metadata_points_to_main_module():
    repo_root = Path(__file__).resolve().parents[1]
    pyproject_text = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    install_script_text = (repo_root / "install_autoloop.sh").read_text(encoding="utf-8")

    assert 'autoloop = "autoloop.main:main"' in pyproject_text
    assert 'autoloop = "autoloop.autoloop:main"' not in pyproject_text
    assert "src/autoloop/main.py" in install_script_text


def test_root_wrapper_help_exits_zero():
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(repo_root / "autoloopcli.py"), "--help"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Autoloop" in result.stdout
