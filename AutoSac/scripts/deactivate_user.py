from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.db import session_scope
from shared.user_admin import deactivate_user


def main() -> None:
    parser = argparse.ArgumentParser(description="Deactivate a local user.")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    with session_scope() as db:
        deactivate_user(db, email=args.email)
    print(f"Deactivated user {args.email.lower()}")


if __name__ == "__main__":
    main()
