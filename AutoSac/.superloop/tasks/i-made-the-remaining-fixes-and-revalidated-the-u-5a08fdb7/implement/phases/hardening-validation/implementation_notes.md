# Implementation Notes

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: implement
- Phase ID: hardening-validation
- Phase Directory Key: hardening-validation
- Phase Title: Hardening, Observability, and Acceptance Validation
- Scope: phase-local producer artifact

## Files changed
- `.env.example`
- `README.md`
- `app/main.py`
- `requirements.txt`
- `scripts/run_web.py`
- `scripts/run_worker.py`
- `shared/logging.py`
- `shared/workspace.py`
- `tests/test_ops_workflow.py`
- `tests/test_hardening_validation.py`
- `worker/triage.py`
- `.superloop/tasks/i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7/decisions.txt`

## Symbols touched
- `app.main.create_app`
- `scripts.run_web.smoke_check`
- `scripts.run_web.main`
- `scripts.run_worker.smoke_check`
- `scripts.run_worker.cli`
- `shared.logging.JsonLogFormatter`
- `shared.logging.log_event`
- `shared.logging.log_web_event`
- `shared.logging.log_worker_event`
- `shared.workspace.verify_workspace_contract_paths`
- `worker.main.emit_worker_heartbeat`
- `worker.main.main`
- `worker.triage._prepare_run`

## Checklist mapping
- Logging, health, and readiness support: completed via structured JSON logging helper, request middleware, and explicit `/readyz` failure handling plus workspace contract checks.
- Automated regression suite for core web and worker invariants: completed for hardening scope via rendering sanitization, readiness/logging behavior, workspace readiness contract, dependency-backed route/worker tests, and subprocess smoke validation of the real scripts.
- Acceptance validation checklist embedded in repo docs or scripts: completed in `README.md`, `.env.example`, and the new script `--check` modes exercised by tests.

## Assumptions
- Readiness should fail closed when the bootstrapped workspace files are missing, because Stage 1 worker execution depends on those exact paths being present.
- Operator-facing validation can be documented in-repo without adding a new orchestration script, since the phase scope excludes deployment automation.
- Adding deterministic `--check` modes to existing run scripts is an acceptable local-validation mechanism because it preserves the default long-running behavior while making the provided scripts testable in CI and local smoke runs.

## Preserved invariants
- `/healthz` remains a simple liveness endpoint.
- `/readyz` still requires database reachability and workspace availability before reporting ready.
- Worker heartbeat semantics and existing queue/publication logic were not changed.
- Existing requester/ops/session/worker mutation behavior remains untouched outside logging/readiness integration.
- `python scripts/run_web.py` and `python scripts/run_worker.py` still start the long-running services when `--check` is not provided.

## Intended behavior changes
- Web requests now emit structured JSON request logs.
- Worker startup/heartbeat/crash events now use the same structured JSON log shape as the web process.
- `/readyz` now returns `503 {"status":"not_ready","error":"..."}` on readiness failure instead of propagating an uncaught exception.
- Readiness now verifies `AGENTS.md`, the repo skill file, the workspace root, and `runs/` in addition to the app/manual mounts.
- `python scripts/run_web.py --check` now validates the actual web entrypoint plus `/healthz` and `/readyz` in a deterministic smoke mode.
- `python scripts/run_worker.py --check` now validates the worker entrypoint against database/workspace readiness in a deterministic smoke mode.
- Worker run preparation no longer changes ticket status on skip-only paths when `last_processed_hash` already matches.

## Known non-changes
- No new product workflow or route surface was introduced.
- No deployment automation, websocket support, or external notification behavior was added.
- No changes were made to the ticketing or worker decision logic beyond observability hooks.

## Expected side effects
- Local operators get explicit readiness failure reasons in both HTTP responses and JSON logs.
- Request logging adds one JSON log line per handled web request.
- Local validation and CI can now exercise the real bootstrap/web/worker scripts without needing to run long-lived processes manually.

## Validation performed
- `pytest tests/test_hardening_validation.py tests/test_foundation_persistence.py tests/test_auth_requester.py tests/test_ops_workflow.py tests/test_ai_worker.py`
  Result: `58 passed`

## Deduplication / centralization decisions
- Centralized structured log formatting and emission in `shared/logging.py` instead of duplicating JSON print logic in web and worker entrypoints.
- Kept workspace readiness validation in `shared.workspace` beside bootstrap/mount checks so bootstrap and readiness use the same filesystem contract source.
- Reused the existing run scripts as the acceptance-validation surface by adding optional smoke modes, instead of creating a parallel validation entrypoint with separate startup logic.
