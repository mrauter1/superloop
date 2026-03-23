# Test Strategy

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: test
- Phase ID: auth-requester
- Phase Directory Key: auth-requester
- Phase Title: Authentication and Requester Workflow
- Scope: phase-local producer artifact

## Behavior-to-test coverage map
- AC-1 auth/session guardrails:
  - `test_validate_csrf_token_rejects_mismatch`
  - `test_session_expiry_and_requester_status_mapping`
  - `test_login_route_sets_remember_me_cookie`
  - `test_logout_route_rejects_invalid_csrf_without_committing`
- AC-2 requester create/reply/resolve flows:
  - `test_create_requester_ticket_creates_initial_records`
  - `test_add_requester_reply_reopens_and_requeues`
  - `test_resolve_ticket_for_requester_updates_status_and_view`
  - source assertions that multipart parsing still flows through `parse_multipart_form`
  - `test_attachment_download_forbids_non_owner_requester`
- AC-3 view tracking / read semantics:
  - shared helper coverage in create/reply/resolve tests verifies `ticket_views` creation/update on successful mutations
  - `test_requester_list_route_does_not_mark_ticket_as_read`
  - `test_requester_detail_route_marks_ticket_as_read`
- AC-4 requester rendering / public-thread fidelity:
  - `test_session_expiry_and_requester_status_mapping` verifies explicit requester status and author-label mappings
  - source assertions verify the route serializes `requester_author_label(message.author_type)` and the template renders `message.author_label`

## Preserved invariants checked
- Initial ticket creation still records `null -> new` status history and creates the requester view row.
- Requester reply on a resolved ticket still reopens to `ai_triage` and requeues instead of creating a duplicate active run in the fake-session path.
- Multipart parsing still uses explicit limits rather than framework defaults, and the part-size limit now includes explicit slack above `MAX_IMAGE_BYTES`.

## Edge cases
- Provisional title generation from the first sentence when title input is omitted.
- Reopen path when requester replies to a resolved ticket with an active run conflict.
- Author labeling for future public `dev_ti` replies.
- 5 MiB-at-the-limit upload acceptance protected by the multipart part-size slack assertion.

## Failure paths
- CSRF mismatch raises a 403.
- Active `ai_runs` uniqueness conflict normalizes to requeue behavior through the existing shared helper tests.
- Logout with a bad CSRF token does not commit.
- Non-owner requester attachment access returns 403 without serving a file.

## Stabilization / flake control
- Shared helper tests use deterministic fake sessions instead of live DB state.
- Route-level tests use FastAPI dependency overrides and a tiny fake DB/session object instead of a live database, filesystem, or worker process.
- FastAPI/argon2/SQLAlchemy-dependent imports remain gated with `pytest.importorskip` so source-level and harness-based tests still run deterministically in minimal environments.

## Known gaps
- Attachment happy-path file serving is still not exercised because the current tests intentionally avoid creating real files on disk.
