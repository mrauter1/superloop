from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.config import get_settings
from shared.db import ping_database
from shared.workspace import verify_workspace_contract_paths
from worker.main import main


def smoke_check() -> None:
    settings = get_settings()
    ping_database(settings)
    verify_workspace_contract_paths(settings)
    print(
        json.dumps(
            {
                "script": "run_worker.py",
                "status": "ok",
                "worker_poll_seconds": settings.worker_poll_seconds,
            }
        )
    )


def cli() -> None:
    parser = argparse.ArgumentParser(description="Run the Stage 1 worker.")
    parser.add_argument("--check", action="store_true", help="Run a deterministic smoke check and exit.")
    args = parser.parse_args()
    if args.check:
        smoke_check()
        return
    main()


if __name__ == "__main__":
    cli()
