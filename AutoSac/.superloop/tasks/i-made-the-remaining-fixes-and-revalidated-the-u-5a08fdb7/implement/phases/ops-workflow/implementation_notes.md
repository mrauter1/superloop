# Implementation Notes

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: implement
- Phase ID: ops-workflow
- Phase Directory Key: ops-workflow
- Phase Title: Dev/TI Workflow Surface
- Scope: phase-local producer artifact

## Files changed
- `shared/ticketing.py`
- `app/routes_ops.py`
- `app/ui.py`
- `app/templates/base.html`
- `app/templates/ops_filters.html`
- `app/templates/ops_ticket_rows.html`
- `app/templates/ops_ticket_list.html`
- `app/templates/ops_board_columns.html`
- `app/templates/ops_board.html`
- `app/templates/ops_ticket_detail.html`
- `app/static/app.css`
- `tests/test_ops_workflow.py`

## Symbols touched
- `shared.ticketing.add_ops_public_reply`
- `shared.ticketing.add_ops_internal_note`
- `shared.ticketing.assign_ticket_for_ops`
- `shared.ticketing.set_ticket_status_for_ops`
- `shared.ticketing.request_manual_rerun`
- `shared.ticketing.publish_ai_draft_for_ops`
- `shared.ticketing.reject_ai_draft_for_ops`
- `app.routes_ops.*`
- `app.ui.ops_status_label`
- `app.ui.ops_author_label`

## Checklist mapping
- Phase 3 list/board surface: implemented `/ops` list view and `/ops/board` grouped board with required filters.
- Shared ops workflow services: assignment, status changes, public replies, internal notes, draft publish/reject, and manual rerun now route through `shared.ticketing`.
- Role-gated AI analysis and drafts: ops detail shows AI state, latest AI note, pending draft controls, and relevant paths loaded from canonical `final.json` when present.

## Assumptions
- `/ops` serves as the queue/list page and `/ops/board` serves as the grouped status board.
- AI relevant repo/docs paths are surfaced from `ai_runs.final_output_path` by reading the canonical saved JSON payload when it exists; no extra persistence layer was introduced in this phase.

## Preserved invariants
- Ops POST handlers reuse shared mutation helpers so `ticket_status_history`, `tickets.updated_at`, `ticket_views.last_viewed_at`, and rerun/requeue behavior stay centralized.
- Requester-visible and internal message lanes remain separate in both route queries and templates.
- Requesters remain blocked from `/ops` through the existing role guard path.

## Intended behavior changes
- Ops users now have queue, board, and ticket-detail pages plus human workflow controls.
- Pending AI drafts can now be approved/published or rejected from the ops detail page.

## Known non-changes
- Worker-side Codex execution and publication logic remain deferred to the worker phase.
- Ops public replies do not support attachments in Stage 1.

## Expected side effects
- Ops login redirect now lands on `/ops`, and the shared header switches navigation links based on role.
- Board/detail templates expect the existing Stage 1 schema fields and optional run artifact paths; absent AI data degrades to empty panels instead of failing.

## Validation performed
- `pytest -q tests/test_auth_requester.py tests/test_foundation_persistence.py tests/test_ops_workflow.py`
- `python -m compileall app shared tests`

## Deduplication / centralization decisions
- Shared ticket mutation helpers now cover both requester and ops flows to prevent route-owned status/history/view drift.
- Ops AI-analysis rendering reuses stored run artifacts instead of inventing a second persistence model for `relevant_paths` during this phase.
