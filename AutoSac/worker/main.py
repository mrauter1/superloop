from __future__ import annotations

import threading
import time

from sqlalchemy.orm import Session

from shared.config import get_settings
from shared.db import session_scope
from shared.logging import log_worker_event
from shared.models import SystemState
from shared.security import utc_now
from worker.queue import claim_oldest_pending_run
from worker.triage import process_ai_run

HEARTBEAT_INTERVAL_SECONDS = 60.0


def update_worker_heartbeat(db: Session) -> None:
    heartbeat = db.get(SystemState, "worker_heartbeat")
    now = utc_now()
    payload = {"status": "alive", "timestamp": now.isoformat()}
    if heartbeat is None:
        heartbeat = SystemState(key="worker_heartbeat", value_json=payload, updated_at=now)
        db.add(heartbeat)
    else:
        heartbeat.value_json = payload
        heartbeat.updated_at = now


def emit_worker_heartbeat(settings) -> None:
    with session_scope(settings) as db:
        update_worker_heartbeat(db)
    log_worker_event("heartbeat")


def heartbeat_loop(settings, *, stop_event: threading.Event | None = None, interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS) -> None:
    while True:
        try:
            emit_worker_heartbeat(settings)
        except Exception as exc:
            log_worker_event("heartbeat_error", level="error", error=str(exc))
        if stop_event is None:
            time.sleep(interval_seconds)
            continue
        if stop_event.wait(interval_seconds):
            return


def start_heartbeat_thread(settings) -> threading.Thread:
    thread = threading.Thread(
        target=heartbeat_loop,
        kwargs={"settings": settings},
        name="worker-heartbeat",
        daemon=True,
    )
    thread.start()
    return thread


def main() -> None:
    settings = get_settings()
    log_worker_event("worker_started", poll_seconds=settings.worker_poll_seconds)
    start_heartbeat_thread(settings)
    while True:
        claimed_run_id = None
        with session_scope(settings) as db:
            run = claim_oldest_pending_run(db)
            if run is not None:
                claimed_run_id = run.id
        if claimed_run_id is not None:
            try:
                process_ai_run(settings, run_id=claimed_run_id)
            except Exception as exc:
                log_worker_event("run_crash", level="error", run_id=str(claimed_run_id), error=str(exc))
        time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
