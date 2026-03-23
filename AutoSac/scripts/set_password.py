from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.db import session_scope
from shared.user_admin import set_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Set a local user's password.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    with session_scope() as db:
        set_password(db, email=args.email, password=args.password)
    print(f"Updated password for {args.email.lower()}")


if __name__ == "__main__":
    main()
