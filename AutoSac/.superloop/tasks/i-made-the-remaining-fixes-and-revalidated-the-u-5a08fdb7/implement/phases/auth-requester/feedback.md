# Implement ↔ Code Reviewer Feedback

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: implement
- Phase ID: auth-requester
- Phase Directory Key: auth-requester
- Phase Title: Authentication and Requester Workflow
- Scope: phase-local authoritative verifier artifact

- IMP-001 resolved on re-review in cycle 2: [app/uploads.py](/workspace/superloop/AutoSac/app/uploads.py#L34) now gives `max_part_size` explicit slack above `MAX_IMAGE_BYTES` while [app/uploads.py](/workspace/superloop/AutoSac/app/uploads.py#L54) still enforces the true file-byte cap, so edge-size valid uploads are no longer rejected by multipart overhead.
- IMP-002 resolved on re-review in cycle 2: [app/routes_requester.py](/workspace/superloop/AutoSac/app/routes_requester.py#L71) now serializes an explicit `author_label`, and [app/templates/requester_ticket_detail.html](/workspace/superloop/AutoSac/app/templates/requester_ticket_detail.html#L21) renders that label instead of treating every non-AI message as requester-authored.
- IMP-003 `non-blocking` [app/routes_requester.py](/workspace/superloop/AutoSac/app/routes_requester.py#L262): the detail GET commits `ticket_views.last_viewed_at` before the thread is serialized and before the response is fully rendered. If a later query/template error occurs, the ticket is marked read even though the GET did not complete successfully, which is slightly out of line with the PRD’s “successful GET” wording. Minimal fix: finish loading/rendering the detail payload first, then persist the view update once the response can be returned successfully.
