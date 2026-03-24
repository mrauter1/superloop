from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_python_m_autoloop_help_exits_zero():
    repo_root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH")
    src_path = str(repo_root / "src")
    env["PYTHONPATH"] = src_path if not existing_pythonpath else f"{src_path}:{existing_pythonpath}"

    result = subprocess.run(
        [sys.executable, "-m", "autoloop", "--help"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Autoloop" in result.stdout
