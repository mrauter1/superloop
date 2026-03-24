#!/usr/bin/env python3
"""Backward-compatible shim for the moved Autoloop runtime module."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    package_root = str(Path(__file__).resolve().parent.parent)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)
    from autoloop.main import *  # noqa: F403
else:
    from .main import *  # noqa: F403


if __name__ == "__main__":
    sys.exit(main())
