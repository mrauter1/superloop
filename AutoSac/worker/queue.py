from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared.models import AIRun
from shared.security import utc_now


def claim_oldest_pending_run(db: Session) -> AIRun | None:
    statement = (
        select(AIRun)
        .where(AIRun.status == "pending")
        .order_by(AIRun.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    run = db.execute(statement).scalar_one_or_none()
    if run is None:
        return None
    run.status = "running"
    run.started_at = utc_now()
    return run
