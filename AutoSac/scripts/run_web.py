from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def smoke_check() -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        health_response = client.get("/healthz")
        ready_response = client.get("/readyz")

    if health_response.status_code != 200 or health_response.json() != {"status": "ok"}:
        raise SystemExit("Web smoke check failed: /healthz did not return the expected payload")
    if ready_response.status_code != 200 or ready_response.json() != {"status": "ready"}:
        raise SystemExit("Web smoke check failed: /readyz did not return the expected payload")

    print(
        json.dumps(
            {
                "script": "run_web.py",
                "status": "ok",
                "healthz_status": health_response.status_code,
                "readyz_status": ready_response.status_code,
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Stage 1 web app.")
    parser.add_argument("--check", action="store_true", help="Run a deterministic smoke check and exit.")
    args = parser.parse_args()
    if args.check:
        smoke_check()
        return
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
