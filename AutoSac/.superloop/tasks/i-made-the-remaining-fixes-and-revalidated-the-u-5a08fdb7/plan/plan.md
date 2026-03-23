# Stage 1 AI Triage MVP Plan

## Planning basis
- The repository is effectively greenfield: `Autosac_PRD.md` is the implementation contract and there is no existing application code to preserve beyond the planning artifacts.
- Current repo inspection confirms only `Autosac_PRD.md` and `superloop.yaml` exist outside `.superloop/`, so the implementation must create the full Stage 1 repository shape rather than integrate into an existing app.
- Scope remains exactly Stage 1: server-rendered FastAPI + Jinja2 + HTMX, PostgreSQL as the only system of record, one Python worker for Codex orchestration, and read-only repo/docs inspection only.
- The corrected assumptions in the frozen PRD are treated as binding implementation constraints:
  - FastAPI + Jinja2 templates are the supported web rendering path.
  - Starlette `SessionMiddleware` is signed-cookie based and therefore forbidden for primary auth state.
  - Multipart parsing must use explicit `request.form()` limits instead of framework defaults.
  - Codex runs must use non-interactive read-only `exec`, `CODEX_API_KEY`, `--output-schema`, `--output-last-message`, and repo skills under `.agents/skills/`.
- No scope drift into Kanboard, Slack, SMTP, OAuth/SSO, OCR, non-image attachments, patch generation, database inspection, or web search.

## Delivery strategy
Build the system in five ordered slices so persistence, session, and queue invariants are stable before UI and worker behavior branch.

### Phase 1: Foundation and persistence
- Create the Stage 1 repository/module layout from the PRD: `app/`, `worker/`, `shared/`, `scripts/`, templates/static, Alembic, requirements, env example, README.
- Implement configuration loading, DB engine/session wiring, SQLAlchemy models, and the initial Alembic migration for the full Stage 1 schema.
- Encode hard invariants at the shared/data layer:
  - PostgreSQL-backed server-side sessions with opaque cookie token only
  - `ai_runs` partial unique index for one active run per ticket
  - `ticket_status_history` writes on every status transition
  - `tickets.updated_at` bumps on every material mutation
  - title/reference generation, enum constraints, draft supersession support, and workspace path constants
- Add workspace/bootstrap and user-management scripts that create the workspace repo, exact `AGENTS.md`, exact `.agents/skills/stage1-triage/SKILL.md`, upload directories, and admin/user CLI commands.

### Phase 2: Authentication and requester workflow
- Implement local login/logout, Argon2id password verification, remember-me expiry handling, CSRF tied to the server-side session row, and role-aware auth guards.
- Build requester routes and templates for list/home, new ticket, ticket detail, reply, resolve, and authenticated attachment download.
- Implement ticket creation/reply/resolve flows with provisional title generation, attachment validation/storage, unread markers, reopen/requeue behavior, and requester-only authorization.
- Keep the requester UI thread-first and map internal statuses to requester-visible labels without exposing internal state or notes.

### Phase 3: Dev/TI workflow surface
- Implement `/ops`, `/ops/board`, and `/ops/tickets/{reference}` with grouped status columns, filters, ticket detail, and separate public/internal thread rendering.
- Reuse shared mutation services for public replies, internal notes, assignment changes, status changes, draft publish/reject, and manual rerun so status/history/view updates stay consistent.
- Surface AI analysis, relevant paths, pending drafts, and rerun controls only to `dev_ti` and `admin`.

### Phase 4: AI worker and Codex orchestration
- Implement DB-backed queue polling with `FOR UPDATE SKIP LOCKED` behavior, run pickup, artifact directory creation, and worker heartbeat updates.
- Implement automatic-trigger/publication fingerprinting, skip logic, stale-run suppression, deferred requeue processing, classification updates, and failure handling.
- Build the Codex runner exactly to the PRD contract:
  - `exec --ephemeral --sandbox read-only --ask-for-approval never --json`
  - `--output-schema` and `--output-last-message`
  - `-c web_search="disabled"`
  - `cwd=/opt/triage/triage_workspace`
  - image args passed explicitly
  - `final.json` treated as canonical output
- Enforce public/internal separation in worker publication paths and ensure successful non-superseded runs publish exactly one internal AI note before any action-specific publication or draft mutation.

### Phase 5: Hardening and acceptance validation
- Add markdown rendering + bleach sanitization, structured JSON logging, `/healthz`, `/readyz`, and readiness checks for DB plus workspace mounts.
- Add regression coverage for session/CSRF behavior, requester isolation, multipart limits, ticket view tracking, queue locking, skip/supersede/requeue flows, and draft workflows.
- Validate acceptance criteria end-to-end with local run scripts for bootstrap, web, worker, and admin/user CLI operations.

## Phase handoff gates
- Phase 1 may close only when the initial migration, workspace bootstrap, exact AGENTS/skill file generation, and user-management CLIs are runnable end to end.
- Phase 2 may close only when requester flows operate entirely on the custom session layer, attachment parsing enforces explicit limits at parse time, and requester detail/list read semantics match the PRD.
- Phase 3 may close only when every ops mutation path reuses shared ticket mutation services and requester-visible/public versus internal separation is preserved in both route protection and template rendering.
- Phase 4 may close only when the worker is the sole Codex caller, stale-run suppression is validated against changed requester-visible input, and non-superseded runs follow the exact publication order.
- Phase 5 may close only when automated coverage exercises the main invariants and a documented acceptance run proves the local bootstrap, web, and worker processes work together.

## Critical invariants
- One active AI run per ticket must be enforced in both application logic and the partial unique DB index.
- Shared helpers must own status-history writes, `updated_at` bumps, `resolved_at` transitions, requester/ops view tracking, and enqueue/requeue changes; route handlers and worker code must not hand-roll this logic.
- Automatic-trigger and publication fingerprints must use the exact same requester-visible field set; internal notes are AI context only and never part of supersede detection.
- Successful non-superseded runs must follow the exact order: validate output, update classification, publish one internal AI note, apply one action path, update `last_processed_hash`, mark run succeeded.
- Requester list/board pages must never mark tickets as read; only ticket detail GETs and successful ticket-mutating POSTs for that user may update `ticket_views`.
- Attachments must stay outside static assets and be served only through authenticated routes with requester ownership checks.

## Shared interfaces

### External/public contracts to preserve
- HTTP routes must match the PRD exactly for auth, requester, ops, attachment, and health surfaces; later implementation should not rename or collapse them.
- CLI commands must exist with the exact management names `create-admin`, `create-user`, `set-password`, and `deactivate-user`.
- Persisted schema names and semantics in `users`, `sessions`, `tickets`, `ticket_messages`, `ticket_attachments`, `ticket_status_history`, `ticket_views`, `ai_runs`, `ai_drafts`, and `system_state` are part of the Stage 1 contract and should be implemented in the initial migration, not introduced gradually.
- Environment variables listed in the PRD are the configuration contract; `.env.example`, startup validation, and readiness checks should expose missing/invalid values early instead of falling back silently.
- Filesystem contracts are exact: uploads under `/opt/triage/data/uploads/`, workspace under `/opt/triage/triage_workspace/`, repo/manual mounts at `/opt/triage/triage_workspace/app` and `/opt/triage/triage_workspace/manuals`, and run artifacts under `runs/{ticket_id}/{run_id}/`.

### Shared domain services
- Provide a small shared mutation layer used by both web routes and the worker for:
  - create ticket with initial message, attachments, status history, initial view row, and pending run
  - add requester reply with reopen/requeue behavior
  - add Dev/TI public reply
  - add Dev/TI internal note
  - set status / resolve / reopen
  - assign or unassign tickets
  - enqueue or defer AI reruns
  - approve/publish or reject drafts
  - upsert `ticket_views.last_viewed_at`
- Keep these services transaction-scoped so state change, history row, `updated_at`, and queue side effects commit together.

### Security/session layer
- `shared/security.py` should own password hashing/verification, raw-token generation, token hashing, CSRF token generation, and session expiry calculations.
- `app/auth.py` should resolve the current session/user from the `sessions` table only; no signed-cookie session store may hold primary auth state.
- CSRF checks should be wired as reusable POST guards for requester and ops forms.

### Upload/rendering layer
- `app/uploads.py` should own multipart parsing with explicit `max_files` and `max_part_size`, MIME/type validation, Pillow open/verify, SHA-256 calculation, and generated storage paths under `UPLOADS_DIR`.
- `app/render.py` should own markdown-to-HTML conversion plus bleach sanitization for all stored human and AI message content.

### Worker/domain boundary
- `worker/ticket_loader.py` should load the exact public/internal message and attachment context used for prompt generation and fingerprinting.
- `worker/triage.py` should own fingerprint computation, stale-run checks, success/failure publication order, and deferred requeue draining.
- `worker/codex_runner.py` should own prompt/schema/artifact writing and Codex process execution; it must not mutate tickets directly.

### Phase-owned module boundaries
- Phase 1 should establish `shared/` ownership for config, DB, models, migrations, security, and permissions so later phases extend stable primitives instead of duplicating glue code.
- Phase 2 should add `app/` auth and requester route modules but keep ticket-state mutation logic out of controllers.
- Phase 3 should extend `app/` with ops routes and templates while continuing to call the same shared ticket mutation services introduced earlier.
- Phase 4 should add `worker/` queue, loader, triage, and Codex runner modules without backsliding into route-owned AI logic.
- Phase 5 should add tests and operational scripts around those modules rather than introducing alternate execution paths.

## Compatibility and migration notes
- This is greenfield, so there is no prior app compatibility obligation; the initial migration becomes the persisted contract and should include the full Stage 1 schema and constraints from the start.
- Session/auth design is intentionally incompatible with Starlette signed-cookie sessions; do not add a hybrid or fallback cookie-session path.
- Because there is no pre-existing application code to preserve, the main compatibility risks are self-inflicted contract drift in route names, CLI command names, schema semantics, environment variables, and workspace file contents.
- The workspace artifacts are compatibility-sensitive:
  - exact `AGENTS.md` content
  - exact `.agents/skills/stage1-triage/SKILL.md` content
  - exact prompt skeleton and output schema
  - exact `.agents/skills/` location
- Because the worker is the only Codex caller, any future CLI or automation wrapper must preserve the PRD flags and canonical use of `final.json` from `--output-last-message`.

## Regression prevention and validation

### Primary regression surfaces
- Session handling drifting into signed-cookie auth.
- Multipart parsing silently using framework defaults instead of product limits.
- Public/internal data leakage in queries, templates, or worker publication.
- Divergent status/history/view logic across requester routes, ops routes, and worker actions.
- Queue races that create duplicate active runs or publish stale outputs.
- Bootstrap drift from the exact workspace file content and path contract in the PRD.

### Validation approach
- Unit tests:
  - session token hashing and expiry calculation
  - CSRF checks
  - title/reference generation
  - fingerprint computation
  - markdown sanitization
  - draft supersession and requeue helpers
- Route/integration tests:
  - requester isolation and attachment authorization
  - multipart upload limits and MIME/Pillow rejection
  - requester detail read tracking vs list/board non-tracking
  - ops-only access to internal notes, AI analysis, and draft actions
  - status history and `updated_at` behavior on all material mutations
- Worker/integration tests:
  - queue claim locking
  - skip when fingerprint matches `last_processed_hash`
  - supersede when requester-visible input changes
  - deferred requeue after running/failed/skipped/superseded runs
  - exact-one-internal-note rule
  - failure fallback to `waiting_on_dev_ti`

## Risk register
- Concurrency drift: route handlers and worker may diverge on run/status logic.
  Mitigation: central shared transaction services plus tests that exercise both requester and ops paths against the same helpers.
- Auth regression: accidental use of framework cookie sessions would violate the contract.
  Mitigation: isolate session lookup and cookie writing to a custom auth module backed only by `sessions`.
- Upload/parser mismatch: validation-only checks can still leave parser defaults too permissive.
  Mitigation: require explicit multipart parser limits at every request entry point that accepts images.
- Public/internal leakage: mixed queries or templates can expose internal notes or internal AI summaries.
  Mitigation: separate loaders/render blocks for public vs internal content and explicit attachment authorization paths.
- Stale publication: an old run could publish after new requester-visible input arrives.
  Mitigation: publication fingerprint check immediately before any internal note, public message, draft, or status mutation.
- Workspace drift: bootstrap content or skill location may stop matching the PRD.
  Mitigation: generate workspace files from checked-in exact string constants and test the file contents and paths directly.

## Rollout and rollback
- Rollout order:
  - apply migration
  - create initial admin
  - ensure uploads/workspace directories
  - bootstrap workspace repo and exact files
  - verify mounts and readiness
  - start web
  - start worker
  - run acceptance checks
- Rollback before real data exists:
  - stop services
  - revert code
  - drop the greenfield database and generated workspace/uploads
- Rollback after data exists:
  - preserve PostgreSQL data and uploaded files
  - prefer forward fixes over destructive rollback
  - if the worker is the issue, stop only the worker and keep the web app available for manual triage
