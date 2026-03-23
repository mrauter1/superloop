# Test Strategy

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: test
- Phase ID: hardening-validation
- Phase Directory Key: hardening-validation
- Phase Title: Hardening, Observability, and Acceptance Validation
- Scope: phase-local producer artifact

## Behavior-to-test coverage map

- Markdown rendering and sanitization:
  covered by `tests/test_hardening_validation.py::test_render_markdown_to_html_sanitizes_untrusted_content`
  checks safe markdown rendering plus stripping raw script tags.
- Readiness contract paths:
  covered by `tests/test_hardening_validation.py::test_verify_workspace_contract_paths_requires_agents_and_skill_files`
  checks missing-file failure before success once required workspace files are present.
- Web health/readiness endpoints and logging:
  covered by `tests/test_hardening_validation.py::test_readyz_returns_ready_when_database_and_workspace_checks_pass`
  covered by `tests/test_hardening_validation.py::test_readyz_returns_503_and_logs_failure`
  covered by `tests/test_hardening_validation.py::test_healthz_request_is_structured_logged`
  checks happy-path readiness, readiness failure logging, and request-completion logging.
- Acceptance artifacts:
  covered by `tests/test_hardening_validation.py::test_env_example_and_readme_capture_acceptance_contract`
  checks `.env.example` variables and README validation instructions.
- Real script validation surface:
  covered by `tests/test_hardening_validation.py::test_bootstrap_web_and_worker_scripts_validate_end_to_end`
  covered by `tests/test_hardening_validation.py::test_script_checks_fail_before_workspace_bootstrap`
  checks bootstrap/web/worker subprocess happy path after bootstrap plus failure path before bootstrap.
- Session/auth/requester invariants:
  covered by `tests/test_auth_requester.py`
  checks session expiry, CSRF rejection, remember-me cookie behavior, requester read-tracking semantics, multipart-limit wiring, and attachment authorization.
- Ops permissions and view/status invariants:
  covered by `tests/test_ops_workflow.py`
  checks requester denial on ops routes, ops read-tracking semantics, reply/note/assignment/status behaviors, draft publish/reject paths, and manual rerun branches.
- Worker queueing, stale-run suppression, and publication order:
  covered by `tests/test_ai_worker.py`
  checks fingerprint rules, skip behavior, stale-run supersession, success-order publication, failure handling, Codex command contract, and heartbeat loop behavior.
- Persistence/bootstrap contracts:
  covered by `tests/test_foundation_persistence.py`
  checks ai_run uniqueness race normalization, status-history null transition, migration/source contracts, and exact bootstrap file generation.

## Preserved invariants checked

- Only detail GETs or ticket-mutating POSTs mark tickets as viewed.
- Requester and ops authorization remain separated.
- Skipped worker runs do not change status.
- Ready state requires database reachability and required workspace paths.
- Bootstrap continues to write exact AGENTS/skill contents.

## Edge cases and failure paths

- Missing workspace files before readiness succeeds.
- Readiness failure returns `503` and logs the error.
- Script `--check` modes fail before workspace bootstrap and succeed after bootstrap.
- Worker stale/superseded and skip branches remain deterministic.
- Attachment and CSRF rejection paths stay covered.

## Stabilization approach

- Use temp directories and temp local env vars for script subprocess tests.
- Use monkeypatch for DB/readiness/logging branches in web tests.
- Avoid timing-based assertions; worker heartbeat tests remain stop-event driven.
- Keep failure-path assertions focused on stable contract text, not incidental path ordering.

## Known gaps

- The hardening phase validates the provided local scripts and entrypoints, not production deployment automation.
- Script smoke checks validate readiness/startup contracts without running the long-lived web or worker loops indefinitely.
