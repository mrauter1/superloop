#!/usr/bin/env python3
"""Repository-root launcher for Autoloop.

This wrapper keeps local development ergonomics (`python autoloopcli.py ...`)
while delegating all runtime behavior to the package entrypoint.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_package_import_path() -> None:
    repo_root = Path(__file__).resolve().parent
    src_path = str(repo_root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    current = sys.modules.get("autoloop")
    if current is not None and getattr(current, "__file__", None) == __file__:
        del sys.modules["autoloop"]


def main() -> int:
    _ensure_package_import_path()
    from autoloop.main import main as package_main

    return package_main()


if __name__ == "__main__":
    raise SystemExit(main())
