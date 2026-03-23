# Test Strategy

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: test
- Phase ID: ops-workflow
- Phase Directory Key: ops-workflow
- Phase Title: Dev/TI Workflow Surface
- Scope: phase-local producer artifact

## Behavior-to-test coverage map
- Ops shared mutation helpers:
  - `add_ops_public_reply` happy path and invalid next-status failure.
  - `add_ops_internal_note` preserves status while creating an internal message.
  - `assign_ticket_for_ops` updates assignment and actor ticket view.
  - `set_ticket_status_for_ops` records status history for valid transitions and rejects invalid statuses.
  - `request_manual_rerun` covers both active-run requeue and idle-run transition to `ai_triage`, with a stub signature that matches the production call shape.
  - `publish_ai_draft_for_ops` covers publish happy path and non-pending rejection.
  - `reject_ai_draft_for_ops` covers review metadata updates without a status change.

## Preserved invariants checked
- Ops mutations continue to centralize `ticket_status_history`, `tickets.updated_at`, and `ticket_views`.
- List and board routes do not mark tickets read; detail routes do.
- Requesters remain blocked from `/ops`, `/ops/board`, and `/ops/tickets/{reference}`.
- Ops templates keep public/internal lanes distinct and retain the required draft/AI panels.

## Edge cases and failure paths
- Invalid public-reply next status raises `ValueError`.
- Invalid status helper input raises `ValueError`.
- Non-pending draft publish attempts raise `ValueError`.
- Manual rerun while another run is active only requeues and does not force a status transition.

## Stabilization approach
- Shared-helper tests use deterministic fake session objects instead of live DB state.
- FastAPI/SQLAlchemy/argon2-dependent tests are lazy-imported and skip cleanly when the runtime stack is unavailable so source-level contract tests still execute.
- Route/template coverage is reinforced with source assertions for required filters, controls, and public/internal separation markers.

## Validation executed
- `pytest -q tests/test_ops_workflow.py`
- `pytest -q tests/test_auth_requester.py tests/test_foundation_persistence.py tests/test_ops_workflow.py`
- `python -m compileall tests`

## Known gaps
- Runtime route rendering and request handling remain dependency-gated in this environment, so most ops route tests continue to skip when FastAPI/SQLAlchemy/argon2 are absent.
- Worker-populated AI artifact content is only asserted structurally at the template/source level in this phase; end-to-end artifact publication remains for the worker phase.
