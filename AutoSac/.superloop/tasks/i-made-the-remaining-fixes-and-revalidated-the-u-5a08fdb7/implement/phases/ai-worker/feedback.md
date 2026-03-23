# Implement ↔ Code Reviewer Feedback

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: implement
- Phase ID: ai-worker
- Phase Directory Key: ai-worker
- Phase Title: AI Worker and Codex Orchestration
- Scope: phase-local authoritative verifier artifact

- IMP-001 `blocking` — `worker.main.main` / `worker.triage.process_ai_run`: `process_ai_run()` only converts Codex/validation failures into `_mark_failed()`. Any exception raised later during `_apply_success_result()` escapes to `worker/main.py:51-65`, where it is only logged as `run_crash`. In that scenario the claimed row remains `status='running'`, which blocks future reruns for the ticket and violates the one-active-run / deferred-requeue contract. Minimal fix: wrap the success-publication path in the same terminal-state protection as the exec path, or have the outer loop convert unexpected post-claim exceptions into `_mark_failed()` before continuing.

- IMP-002 `blocking` — `worker/main.py:31-66`: heartbeat updates only happen at the top of the single-threaded polling loop. A normal Codex execution can block for up to `CODEX_TIMEOUT_SECONDS=75`, and the worker then sleeps another poll interval, so `system_state.worker_heartbeat` can easily go stale for ~85 seconds. That violates the PRD’s “update every 60 seconds” requirement and can make a healthy worker look dead during long runs. Minimal fix: decouple heartbeat writes from blocking run execution (for example a timer/thread or periodic updates while waiting on the subprocess) instead of only updating before/after the main loop iteration.

Cycle 2 re-review:
- IMP-001 resolved: `worker.triage.process_ai_run` now routes unexpected post-claim exceptions, including success-publication failures, through `_mark_failed()` instead of leaving the run in `running`.
- IMP-002 resolved: `worker.main` now runs heartbeat writes on a dedicated background loop, so long Codex executions no longer starve the 60-second heartbeat contract.
- No remaining blocking findings in phase scope.
