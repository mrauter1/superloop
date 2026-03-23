# Implementation Notes

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: implement
- Phase ID: auth-requester
- Phase Directory Key: auth-requester
- Phase Title: Authentication and Requester Workflow
- Scope: phase-local producer artifact

## Files changed
- `app/auth.py`
- `app/main.py`
- `app/routes_auth.py`
- `app/routes_requester.py`
- `app/static/app.css`
- `app/templates/base.html`
- `app/templates/login.html`
- `app/templates/requester_ticket_detail.html`
- `app/templates/requester_ticket_list.html`
- `app/templates/requester_ticket_new.html`
- `app/ui.py`
- `app/uploads.py`
- `shared/ticketing.py`
- `tests/conftest.py`
- `tests/test_auth_requester.py`

## Symbols touched
- `app.auth`: `get_required_auth_session`, `require_requester_user`, `require_csrf`
- `app.routes_auth`: `get_current_user_optional`, `login_page`, `login_action`, `logout_action`
- `app.routes_requester`: requester list/new/detail/create/reply/resolve/download handlers plus local query/form helpers
- `app.ui`: `templates`, `REQUESTER_STATUS_LABELS`, `REQUESTER_AUTHOR_LABELS`, `requester_status_label`, `requester_author_label`, `post_login_redirect_path`, `build_template_context`
- `app.uploads`: `MULTIPART_PART_SIZE_SLACK_BYTES`, `get_form_images`, `validate_image_upload`
- `shared.ticketing`: `normalize_message_text`, `enqueue_or_requeue_ai_run`, `create_requester_ticket`, `add_requester_reply`, `resolve_ticket_for_requester`

## Checklist mapping
- Phase 2 auth: implemented custom login/logout, server-side session lookup, remember-me cookie handling, requester guard, and CSRF validation for authenticated requester POSTs.
- Phase 2 requester routes: implemented `/app`, `/app/tickets`, `/app/tickets/new`, `/app/tickets/{reference}`, reply, resolve, and authenticated attachment download.
- Phase 2 workflow services: centralized requester create/reply/resolve plus view tracking and enqueue/requeue behavior in `shared.ticketing`.
- Phase 2 uploads/rendering: requester forms use explicit multipart parser limits, image validation/storage, and sanitized markdown rendering in the thread view.

## Assumptions
- Login POST is left without a server-session CSRF requirement because the PRD requires CSRF tied to an authenticated server-side session row and the schema has no anonymous session concept.
- Attachment download is implemented for both requester and future ops users by switching that route to authenticated-user access instead of requester-only access.

## Preserved invariants
- No signed-cookie session middleware is used for primary auth state; the cookie still holds only the raw opaque session token.
- Requesters only query their own tickets and only render public messages/attachments.
- Ticket detail GETs and successful requester mutations update `ticket_views`; requester list/new pages do not.
- Requester reply reopen/requeue behavior still uses the shared one-active-run normalization path.
- Multipart parsing uses explicit `request.form(max_files=..., max_part_size=...)` through `app.uploads.parse_multipart_form`.

## Intended behavior changes
- The app now renders real requester/auth HTML pages instead of router stubs.
- Successful login redirects requesters to `/app` and ops users to `/ops`.
- Requester ticket create/reply flows now persist validated image attachments under the configured uploads directory and expose them only through the authenticated download route.
- Requester thread rendering now labels public messages by explicit author type so future Dev/TI public replies appear as team messages instead of requester messages.

## Known non-changes
- Ops board/detail controls and draft review actions remain out of scope for this phase.
- Worker-side Codex execution, stale-run publication handling, and AI drafting remain deferred.
- No message editing/deletion or password-reset flow was added.

## Expected side effects
- Authenticated requester GETs now commit the DB session to persist `last_seen_at` and detail-page read tracking.
- Invalid requester form submissions return the same page with a 400 status and a rendered error banner.
- Multipart parser rejection should no longer occur for otherwise-valid 5 MiB uploads that only exceeded the part limit because of multipart header overhead.

## Validation performed
- `python -m compileall app shared tests`
- `pytest -q`

## Deduplication / centralization decisions
- Ticket creation, requester replies, resolve handling, view updates, and ai-run enqueue/requeue decisions were kept in `shared.ticketing` instead of duplicating mutation logic in route handlers.
- Template context and requester-visible status mapping were centralized in `app.ui` so auth/requester pages share the same cookie/CSRF/user wiring.
