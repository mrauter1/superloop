from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.config import get_settings
from shared.workspace import bootstrap_workspace, ensure_uploads_dir, workspace_contract_snapshot


def main() -> None:
    settings = get_settings()
    ensure_uploads_dir(settings)
    bootstrap_workspace(settings)
    print(json.dumps(workspace_contract_snapshot(settings), indent=2))


if __name__ == "__main__":
    main()
