I made the remaining fixes and revalidated the underlying implementation assumptions before freezing this version: FastAPI supports server-rendered Jinja2 templates; Starlette’s SessionMiddleware is signed-cookie based and request.form() exposes configurable multipart limits; and Codex supports non-interactive read-only exec, CODEX_API_KEY, --output-schema, --output-last-message, and repo skills under .agents/skills.  ￼

# PRD — Stage 1 AI Triage MVP — Custom Python App, Repo-Aware, Implementation-Ready

Document status: Final  
Version: 1.2-custom-final  
Date: 2026-03-19  
Owner: Internal Engineering  
Audience: autonomous implementation agent, technical reviewer, system owner

This document is both a product requirements document and an implementation specification for Stage 1. It is intentionally prescriptive. An autonomous implementation agent must be able to build Stage 1 using only this document.

Normative terms:
- MUST = mandatory
- MUST NOT = prohibited
- SHOULD = recommended
- MAY = optional

---

## 1. Product decision

Stage 1 will use a **custom Python web application** as the only product surface.

There will be exactly **two UI surfaces**:

1. **Requester view** for internal users opening and replying to tickets
2. **Dev/TI view** for triage, review, approvals, assignment, and resolution

There will be:
- no Kanboard
- no Slack
- no SMTP/email notifications
- no separate requester portal plus board split
- no separate document indexing system

The system will use:
- server-rendered HTML
- FastAPI
- Jinja2 templates
- HTMX for partial updates
- PostgreSQL as the single system of record
- a separate Python worker process for Codex orchestration

The AI worker will use Codex CLI in **read-only** mode against a WSL workspace that contains:
- the mounted application repository
- the mounted manuals/docs directory
- repo-scoped `AGENTS.md`
- one repo skill under `.agents/skills/stage1-triage/`

Stage 1 is **repo-aware triage**, not patching.

---

## 2. Purpose

Build Stage 1 of an internal AI-assisted ticket triage system for a company-developed internal application.

Stage 1 exists to solve these problems:
- internal users need a low-friction place to open tickets
- many tickets are support/how-to/access/configuration issues and do not require development
- ambiguous tickets should trigger concise clarifying questions automatically
- clear support-like tickets should receive useful first-pass answers automatically when evidence exists in docs or the application repository
- likely bugs and feature requests should be routed to Dev/TI with a strong internal summary
- requesters and Dev/TI need different views of the same ticket
- public and internal discussion must be cleanly separated

---

## 3. Stage boundary

Stage 1 explicitly allows:
- read-only inspection of the mounted application repository
- read-only inspection of the mounted manuals/docs
- read-only inspection of ticket screenshots/images
- AI classification
- AI clarification questions
- safe automatic public replies
- internal AI notes
- public AI draft replies requiring human approval

Stage 1 explicitly forbids:
- modifying repository files
- generating or applying patches
- creating Git branches
- touching SQL Server
- reading schema dumps or DDL
- invoking Delphi MCP
- running Codex with write access
- using web search
- OCR pipelines
- non-image attachments
- outbound email or chat notifications

Stage 1 is an in-app workflow only.

---

## 4. Scope

### 4.1 In scope
- custom login with “remember me”
- local user accounts
- requester view
- Dev/TI view
- free-text ticket intake
- public and internal ticket messages
- image attachments only
- AI classification
- AI clarification loop
- AI safe auto-replies
- AI public draft replies for approval
- internal AI summaries
- board/list view for Dev/TI
- read-only repo/docs investigation by Codex
- DB-backed worker queue
- role-based access control
- audit history of status changes and AI runs
- unread/updated markers in the UI

### 4.2 Out of scope
- Kanboard
- Slack
- SMTP/email notifications
- LDAP/OAuth/SSO
- password reset by email
- web search
- application code modification
- patch generation
- DDL or live database analysis
- SQL Server access
- Delphi MCP
- file formats beyond PNG/JPEG uploads and text-readable docs/manuals
- OCR
- mobile app
- websocket infrastructure
- SPA frontend

---

## 5. Core principles

1. **One system of record**  
   PostgreSQL is the single system of record.

2. **Two views, one workflow**  
   Requesters see only public ticket content for their own tickets.  
   Dev/TI see all tickets plus internal notes, AI analysis, drafts, and controls.

3. **Thread-first requester experience**  
   Requesters do not need a board. They need:
   - create ticket
   - see my tickets
   - reply
   - see status
   - mark resolved

4. **Board/list-first Dev/TI experience**  
   Dev/TI need:
   - queue view
   - ticket detail
   - AI analysis
   - public draft approval
   - internal notes
   - assignment
   - status controls
   - rerun AI

5. **Read-only AI in Stage 1**  
   Codex may inspect repo/docs/images, but it must not modify anything.

6. **Safe automation only**  
   Automatic public replies are limited to:
   - clarifying questions
   - intent confirmation
   - high-confidence support/access replies

7. **Internal facts stay internal**  
   Internal notes may guide internal analysis and routing.  
   They MUST NOT be disclosed in automatic public replies unless that same information is already present in public ticket content.

8. **No external notifications in Stage 1**  
   Users rely on in-app unread/updated indicators.  
   The UI must clearly show tickets updated since the user last viewed them.

---

## 6. Technology stack

The implementation MUST use this stack unless a blocker is documented.

### Runtime
- Python 3.12
- PostgreSQL 16
- FastAPI
- Uvicorn
- Jinja2
- HTMX
- SQLAlchemy 2.x
- Alembic
- psycopg 3
- Pydantic 2
- Pillow
- markdown-it-py
- bleach
- argon2-cffi

### Process model
- one web process
- one worker process
- both in WSL
- PostgreSQL local to WSL or reachable from WSL

### Design intent
- server-rendered HTML keeps frontend complexity low
- HTMX gives partial-page updates without SPA complexity
- SQLAlchemy + Alembic provide maintainable relational persistence
- server-side session auth is simpler than OAuth/JWT for an internal browser app
- Codex CLI is the simplest AI integration path for Stage 1

---

## 7. Authentication and session model

### 7.1 Login model
Stage 1 uses **local application accounts**.

Users authenticate with:
- email
- password

Passwords MUST be stored as **Argon2id hashes**.

### 7.2 Remember me
The login form MUST include a `Remember me` checkbox.

Behavior:
- if unchecked:
  - create a normal session
  - session cookie has no long-lived persistence
  - server-side session expiry = 12 hours
- if checked:
  - create a persistent session
  - cookie max-age = 30 days
  - server-side session expiry = 30 days

### 7.3 Session design
Sessions MUST be **server-side**.

Cookie contents:
- one opaque random session token only

Database stores:
- SHA-256 hash of the raw session token
- never store the raw token

### 7.4 Forbidden session implementation
The implementation MUST NOT use framework signed-cookie session middleware as the primary auth/session mechanism.

Reason:
- Stage 1 requires server-side sessions
- the cookie must hold only an opaque token
- the session record must live in PostgreSQL

### 7.5 Cookie security
Session cookie MUST be:
- HttpOnly
- SameSite=Lax
- Secure when HTTPS is enabled
- path = `/`

### 7.6 CSRF
All POST forms MUST require a CSRF token tied to the server-side session.

### 7.7 No self-service password reset
Stage 1 does not implement password-reset email flows.

User administration is done by:
- initial bootstrap CLI for admin creation
- CLI commands for user creation and password reset

---

## 8. Roles and permissions

There are exactly three roles.

### 8.1 `requester`
Can:
- log in
- view only their own tickets
- create tickets
- add public replies to their own tickets
- view public messages on their own tickets
- download public attachments on their own tickets
- mark their own tickets resolved

Cannot:
- view internal notes
- view other users’ tickets
- approve drafts
- rerun AI
- change assignment
- change status except mark resolved on own tickets

### 8.2 `dev_ti`
Can:
- log in
- view all tickets
- view public and internal messages
- create internal notes
- create public replies
- approve or reject AI public drafts
- assign tickets
- change ticket status
- rerun AI
- mark tickets resolved

### 8.3 `admin`
Has all `dev_ti` permissions.

Stage 1 does not require a separate web admin panel.  
Admin tasks are handled by CLI commands.

---

## 9. UI surfaces

## 9.1 Requester view

Base path:
- `/app`

Pages:
- `/app`
- `/app/tickets`
- `/app/tickets/new`
- `/app/tickets/{reference}`

The requester UI MUST be thread-first.

### Requester home / ticket list
Show:
- ticket reference
- title
- current status
- urgency badge
- unread/updated badge
- last updated timestamp

A ticket is “updated” for a requester when:
- `tickets.updated_at > ticket_views.last_viewed_at`
for that requester and ticket.

### New ticket page
Form fields:
- optional short title
- required free-text description
- optional image attachments
- urgent checkbox

The requester MUST NOT choose:
- class
- priority beyond urgent toggle
- assignee
- internal team
- workflow state

### Title rule
The title is optional to preserve free-text intake.

If omitted:
- the system MUST generate a provisional title from the first sentence of the description, truncated to 120 characters
- after the first successful AI run, the ticket title MAY be normalized to:
  - `[Class] {summary_short}`

### Ticket detail page
Show:
- title
- public status
- public message thread only
- public attachments only
- reply form
- mark resolved button when ticket is not resolved

### Requester-visible statuses
Map internal statuses to:
- `Reviewing`
- `Waiting for your reply`
- `Waiting on team`
- `Resolved`

Mapping:
- `new` or `ai_triage` → `Reviewing`
- `waiting_on_user` → `Waiting for your reply`
- `waiting_on_dev_ti` → `Waiting on team`
- `resolved` → `Resolved`

## 9.2 Dev/TI view

Base path:
- `/ops`

Pages:
- `/ops`
- `/ops/board`
- `/ops/tickets/{reference}`

### Dev/TI board page
The board MUST group tickets by status:
- New
- AI Triage
- Waiting on User
- Waiting on Dev/TI
- Resolved

A drag-and-drop board is **not required** in Stage 1.

A grouped-column board rendered with HTMX is sufficient.

### Dev/TI filters
Board/list filters MUST include:
- status
- class
- assigned_to
- urgent
- unassigned only
- created_by me
- needs approval
- updated since my last view

### Dev/TI ticket detail page
Must show:
- ticket header
- public thread
- internal thread
- AI analysis panel
- relevant repo/docs paths
- public AI draft panel if present
- reply controls
- internal note composer
- assignment controls
- status controls
- rerun AI button

### View tracking semantics
`ticket_views.last_viewed_at` MUST be updated:
- on successful GET of `/app/tickets/{reference}`
- on successful GET of `/ops/tickets/{reference}`
- on successful POST that creates a message or changes status for that same user and ticket

`ticket_views.last_viewed_at` MUST NOT be updated:
- on list pages
- on board pages
- on filter changes without opening the ticket detail page

---

## 10. Workflow states

There are exactly five ticket states:
- `new`
- `ai_triage`
- `waiting_on_user`
- `waiting_on_dev_ti`
- `resolved`

### 10.1 Standard state transitions

#### Ticket creation
- requester creates ticket
- state = `new`
- enqueue AI run

#### AI starts processing
- worker sets state = `ai_triage`

#### AI clarification
- publish public AI clarification message
- state = `waiting_on_user`

#### AI safe public reply
- publish public AI reply
- state = `waiting_on_user`

#### AI safe public confirmation and route
- publish public AI confirmation message
- state = `waiting_on_dev_ti`

#### AI internal route only
- no public AI message
- state = `waiting_on_dev_ti`

#### AI public draft for approval
- create AI draft
- state = `waiting_on_dev_ti`

#### Requester reply
- create public requester message
- if state was `resolved`, reopen
- state = `ai_triage`
- enqueue AI run or mark requeue requested if an active run exists

#### Dev/TI public reply
- create public human message
- user chooses next state:
  - `waiting_on_user`
  - `waiting_on_dev_ti`
  - `resolved`

#### Dev/TI internal note
- create internal human message
- state unchanged

#### Dev/TI rerun AI
- if no active run exists:
  - state = `ai_triage`
  - enqueue AI run
- if an active run exists:
  - set `tickets.requeue_requested = true`
  - set `tickets.requeue_trigger = manual_rerun`

#### Resolve
- requester or dev_ti can set state = `resolved`

---

## 11. Cross-cutting invariants

These invariants are mandatory.

### 11.1 One active AI run per ticket
At most one `ai_runs` row per ticket may be in:
- `pending`
- `running`

This MUST be enforced by both:
- application logic
- database constraint

Database requirement:
- partial unique index on `ai_runs(ticket_id)` where `status in ('pending', 'running')`

### 11.2 Requeue-on-change
If new requester-visible input or a manual rerun request occurs while a run is already active:
- do not create a second active run
- set `tickets.requeue_requested = true`
- set `tickets.requeue_trigger` to the newest relevant trigger

Allowed `requeue_trigger` values:
- `requester_reply`
- `manual_rerun`
- `reopen`

### 11.3 Stale-run suppression
Before publishing any output from a completed AI run, the worker MUST:
1. reload the ticket and relevant data
2. recompute the **current publication fingerprint**
3. compare it to `ai_runs.input_hash`

If either is true:
- `tickets.requeue_requested = true`
- current publication fingerprint != `ai_runs.input_hash`

then the run is **superseded** and MUST:
- be marked `superseded`
- publish no public message
- publish no internal AI note
- make no status change from that run result
- create exactly one fresh pending run if none already exists
- clear `requeue_requested` only after that fresh run is safely enqueued

### 11.4 Status history
Every status change MUST insert a `ticket_status_history` row.

### 11.5 `updated_at`
Every mutation that materially affects the UI or worker logic MUST bump `tickets.updated_at`.

This includes:
- ticket creation
- requester reply
- public human reply
- internal human note
- AI public reply
- AI internal note
- AI draft creation
- AI draft approval
- AI draft rejection
- assignment change
- status change
- resolve
- reopen

### 11.6 Internal/public separation
Automatic public replies MUST be derived only from:
- public ticket content
- uploaded images
- repository/docs evidence
- general reasoning

They MUST NOT disclose:
- internal-only notes
- reviewer-only hypotheses
- internal escalation details
- anything present only in internal messages

Internal messages may be used to improve internal summaries and routing only.

### 11.7 Exactly one internal AI note per successful non-superseded run
For every successful AI run that is not skipped and not superseded:
- publish exactly one internal AI note
- that note is the canonical internal summary for the run

Action-specific logic MUST NOT publish a second internal AI note.

### 11.8 Publication and status decision order
For a successful non-superseded run, the worker MUST follow this order:
1. validate structured output
2. update ticket classification fields
3. publish exactly one internal AI note
4. apply the selected action path
5. update `last_processed_hash`
6. mark run `succeeded`

---

## 12. Data model

PostgreSQL is the only source of truth.

## 12.1 `users`
Columns:
- `id uuid primary key`
- `email text not null unique`
- `display_name text not null`
- `password_hash text not null`
- `role text not null`
  allowed:
  - `requester`
  - `dev_ti`
  - `admin`
- `is_active boolean not null default true`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`
- `last_login_at timestamptz null`

Rules:
- email stored lowercase
- role changes require admin CLI

## 12.2 `sessions`
Columns:
- `id uuid primary key`
- `user_id uuid not null references users(id)`
- `token_hash text not null unique`
- `csrf_token text not null`
- `remember_me boolean not null default false`
- `expires_at timestamptz not null`
- `last_seen_at timestamptz not null default now()`
- `created_at timestamptz not null default now()`
- `user_agent text null`
- `ip_address text null`

Rules:
- store only token hash
- expired sessions are invalid
- logout deletes the session row

## 12.3 `tickets`
Columns:
- `id uuid primary key`
- `reference_num bigserial not null unique`
- `reference text not null unique`
- `title text not null`
- `created_by_user_id uuid not null references users(id)`
- `assigned_to_user_id uuid null references users(id)`
- `status text not null`
  allowed:
  - `new`
  - `ai_triage`
  - `waiting_on_user`
  - `waiting_on_dev_ti`
  - `resolved`
- `urgent boolean not null default false`
- `ticket_class text null`
  allowed:
  - `support`
  - `access_config`
  - `data_ops`
  - `bug`
  - `feature`
  - `unknown`
- `ai_confidence numeric(4,3) null`
- `impact_level text null`
  allowed:
  - `low`
  - `medium`
  - `high`
  - `unknown`
- `development_needed boolean null`
- `clarification_rounds integer not null default 0`
- `requester_language text null`
- `last_processed_hash text null`
- `last_ai_action text null`
- `requeue_requested boolean not null default false`
- `requeue_trigger text null`
  allowed:
  - `requester_reply`
  - `manual_rerun`
  - `reopen`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`
- `resolved_at timestamptz null`

Rules:
- `reference = 'T-' + zero-padded six-digit reference_num` at minimum
- only one current status per ticket

Indexes:
- `(status, updated_at desc)`
- `(created_by_user_id, updated_at desc)`
- `(assigned_to_user_id, updated_at desc)`
- `(urgent, status, updated_at desc)`

## 12.4 `ticket_messages`
Columns:
- `id uuid primary key`
- `ticket_id uuid not null references tickets(id)`
- `author_user_id uuid null references users(id)`
- `author_type text not null`
  allowed:
  - `requester`
  - `dev_ti`
  - `ai`
  - `system`
- `visibility text not null`
  allowed:
  - `public`
  - `internal`
- `source text not null`
  allowed:
  - `ticket_create`
  - `requester_reply`
  - `human_public_reply`
  - `human_internal_note`
  - `ai_auto_public`
  - `ai_internal_note`
  - `ai_draft_published`
  - `system`
- `body_markdown text not null`
- `body_text text not null`
- `ai_run_id uuid null references ai_runs(id)`
- `created_at timestamptz not null default now()`

Indexes:
- `(ticket_id, created_at)`
- `(ticket_id, visibility, created_at)`

## 12.5 `ticket_attachments`
Columns:
- `id uuid primary key`
- `ticket_id uuid not null references tickets(id)`
- `message_id uuid not null references ticket_messages(id)`
- `visibility text not null`
  allowed:
  - `public`
  - `internal`
- `original_filename text not null`
- `stored_path text not null`
- `mime_type text not null`
- `sha256 text not null`
- `size_bytes integer not null`
- `width integer null`
- `height integer null`
- `created_at timestamptz not null default now()`

Rules:
- Stage 1 supports only `public` attachments
- internal attachments are not required in Stage 1

Indexes:
- `(ticket_id)`
- `(message_id)`
- `(sha256)`

## 12.6 `ticket_status_history`
Columns:
- `id uuid primary key`
- `ticket_id uuid not null references tickets(id)`
- `from_status text null`
- `to_status text not null`
- `changed_by_user_id uuid null references users(id)`
- `changed_by_type text not null`
  allowed:
  - `requester`
  - `dev_ti`
  - `ai`
  - `system`
- `note text null`
- `created_at timestamptz not null default now()`

Indexes:
- `(ticket_id, created_at)`

## 12.7 `ticket_views`
Columns:
- `user_id uuid not null references users(id)`
- `ticket_id uuid not null references tickets(id)`
- `last_viewed_at timestamptz not null default now()`
- primary key `(user_id, ticket_id)`

Purpose:
- support unread/updated indicators
- a ticket is updated for a user if `tickets.updated_at > ticket_views.last_viewed_at`

## 12.8 `ai_runs`
This table acts as both queue and execution log.

Columns:
- `id uuid primary key`
- `ticket_id uuid not null references tickets(id)`
- `status text not null`
  allowed:
  - `pending`
  - `running`
  - `succeeded`
  - `failed`
  - `skipped`
  - `superseded`
- `triggered_by text not null`
  allowed:
  - `new_ticket`
  - `requester_reply`
  - `manual_rerun`
  - `reopen`
- `requested_by_user_id uuid null references users(id)`
- `input_hash text null`
- `model_name text null`
- `prompt_path text null`
- `schema_path text null`
- `final_output_path text null`
- `stdout_jsonl_path text null`
- `stderr_path text null`
- `started_at timestamptz null`
- `ended_at timestamptz null`
- `error_text text null`
- `created_at timestamptz not null default now()`

Indexes:
- `(status, created_at)`
- `(ticket_id, created_at desc)`

Mandatory partial unique index:
- unique on `(ticket_id)` where `status in ('pending', 'running')`

## 12.9 `ai_drafts`
Columns:
- `id uuid primary key`
- `ticket_id uuid not null references tickets(id)`
- `ai_run_id uuid not null references ai_runs(id)`
- `kind text not null`
  allowed:
  - `public_reply`
- `body_markdown text not null`
- `body_text text not null`
- `status text not null`
  allowed:
  - `pending_approval`
  - `approved`
  - `rejected`
  - `superseded`
  - `published`
- `created_at timestamptz not null default now()`
- `reviewed_by_user_id uuid null references users(id)`
- `reviewed_at timestamptz null`
- `published_message_id uuid null references ticket_messages(id)`

Indexes:
- `(ticket_id, status, created_at desc)`
- `(ai_run_id)`

Rule:
- when a newer run produces a new pending draft for the same ticket, older `pending_approval` drafts for that ticket MUST be marked `superseded`

## 12.10 `system_state`
Columns:
- `key text primary key`
- `value_json jsonb not null`
- `updated_at timestamptz not null default now()`

Required keys:
- `worker_heartbeat`
- `bootstrap_version`

---

## 13. Ticket creation and message model

### 13.1 Initial ticket creation
Creating a ticket MUST create:
1. one row in `tickets`
2. one initial public `ticket_messages` row with `source = ticket_create`
3. zero to three public attachments linked to that initial message
4. one `ai_runs` row with `status = pending` and `triggered_by = new_ticket`
5. one `ticket_status_history` row from `null` to `new`
6. one `ticket_views` row for the creator with `last_viewed_at = now()`

### 13.2 Follow-up replies
Every requester reply MUST create:
- one public `ticket_messages` row with `source = requester_reply`
- optional public attachments
- either:
  - one `ai_runs` row with `status = pending`, if no active run exists
  - or `tickets.requeue_requested = true` and `requeue_trigger = requester_reply`, if an active run exists
- ticket status changed to `ai_triage`
- `tickets.updated_at` bumped
- requester `ticket_views.last_viewed_at` updated to now

### 13.3 Message visibility
Public messages are visible to:
- the requester who owns the ticket
- all `dev_ti`
- all `admin`

Internal messages are visible only to:
- `dev_ti`
- `admin`

### 13.4 Editing
Stage 1 does not support message editing or deletion.

Auditability is preferred over editability.

---

## 14. Attachments and multipart parsing

### 14.1 Supported types
Stage 1 supports only:
- `image/png`
- `image/jpeg`

### 14.2 Limits
Per message:
- maximum 3 images
- maximum 5 MiB per file

### 14.3 Parsing requirement
The implementation MUST parse multipart forms with limits that match the product rules.

When parsing forms, the implementation MUST set:
- `max_files = MAX_IMAGES_PER_MESSAGE`
- `max_part_size >= MAX_IMAGE_BYTES`

It MUST NOT rely on framework defaults.

### 14.4 Validation
Every uploaded image MUST:
- have allowed MIME type
- be opened successfully by Pillow
- have its SHA-256 computed
- be stored outside any public static directory

### 14.5 Storage
Attachments MUST be stored under:
- `/opt/triage/data/uploads/`

Path design:
- no user-supplied filename used as storage path
- use generated directories and file ids

### 14.6 Serving
Attachments MUST be served only through authenticated routes.

Authorization rules:
- requester can access only public attachments on their own tickets
- dev_ti/admin can access all attachments

---

## 15. Repo and docs workspace

The WSL workspace MUST be:

`/opt/triage/triage_workspace/`

Contents:
- `.git/`
- `AGENTS.md`
- `.agents/skills/stage1-triage/SKILL.md`
- `app/`    ← mounted application repository, read-only
- `manuals/` ← mounted docs/manuals directory, read-only
- `runs/`   ← per-run artifacts

### 15.1 Workspace repo
The workspace root MUST be a Git repository.

Bootstrap:
1. create directory if absent
2. run `git init` if absent
3. create one empty initial commit if needed
4. write `AGENTS.md`
5. write `.agents/skills/stage1-triage/SKILL.md`

### 15.2 Repo mount
The application repository MUST be mounted read-only at:
- `/opt/triage/triage_workspace/app`

### 15.3 Manuals mount
The manuals/docs directory MUST be mounted read-only at:
- `/opt/triage/triage_workspace/manuals`

### 15.4 Supported docs formats in Stage 1
Docs available to Codex in Stage 1 MUST be text-readable files:
- `.md`
- `.txt`
- `.html`

Binary doc conversion is out of scope for Stage 1.

---

## 16. Codex integration

### 16.1 Authentication
Stage 1 automation MUST use:
- `CODEX_API_KEY`

Do not rely on interactive login.

### 16.2 Execution mode
Every Codex run MUST use:
- `exec`
- `--ephemeral`
- `--sandbox read-only`
- `--ask-for-approval never`
- `--json`
- `--output-schema`
- `--output-last-message`
- `-c web_search="disabled"`

### 16.3 Working directory
Codex MUST run with:
- `cwd = /opt/triage/triage_workspace`

### 16.4 Inputs
The worker MUST provide Codex:
- ticket title
- public requester-visible messages
- internal Dev/TI notes in a separate clearly labeled section
- image attachments for the current ticket
- access to `manuals/`
- access to `app/`

### 16.5 Search policy for Codex
Codex MUST be instructed to:
1. search `manuals/` first for support/access/data_ops guidance
2. inspect `app/` when repository understanding is needed
3. remain read-only
4. never suggest edits or patches in Stage 1

### 16.6 Internal-note non-leak instruction
The prompt, `AGENTS.md`, and `SKILL.md` MUST all explicitly state:

- internal notes may inform internal summaries and routing
- internal-only details MUST NOT be copied or paraphrased into automatic public replies unless the same facts are already present in public ticket content

### 16.7 No web search
Web search MUST be disabled explicitly.

### 16.8 Final output
The file written by `--output-last-message` is the canonical result.  
The JSONL stream from `--json` is diagnostics only.

### 16.9 Timeout
Default timeout:
- 75 seconds per run

### 16.10 Skills location
Repo skills MUST live under:
- `.agents/skills/`

---

## 17. AI classification and safety policy

### 17.1 Allowed classes
Every ticket MUST be classified into exactly one of:
- `support`
- `access_config`
- `data_ops`
- `bug`
- `feature`
- `unknown`

### 17.2 `development_needed`
This is a triage estimate only:
- `true` = likely not solvable as support/config guidance
- `false` = likely solvable without development

### 17.3 `impact_level`
In Stage 1 this means business/user impact only:
- `low`
- `medium`
- `high`
- `unknown`

### 17.4 Clarification policy
Ask clarifying questions when:
- the request is ambiguous
- key facts are missing
- text and image conflict
- the request references the wrong screen/process
- confidence is too low

Rules:
- maximum 3 questions per round
- short questions only
- no repeated questions
- after 2 clarification rounds, route to Dev/TI

### 17.5 Automatic public replies allowed
Allowed only for:
- clarifying questions
- intent confirmation
- high-confidence support/access answers strongly supported by evidence from `manuals/` and/or `app/`

### 17.6 Automatic public replies forbidden
Forbidden for:
- bug root-cause claims
- feature commitments
- speculative answers
- anything that clearly requires engineering work
- anything low confidence
- anything derived solely from internal-only messages

### 17.7 Confidence thresholds
Defaults:
- `AUTO_SUPPORT_REPLY_MIN_CONFIDENCE = 0.85`
- `AUTO_CONFIRM_INTENT_MIN_CONFIDENCE = 0.90`

---

## 18. Exact fingerprint rules

The worker MUST compute two explicit fingerprints.

### 18.1 Automatic-trigger fingerprint
Used to decide whether new requester-facing input should queue or supersede a run.

It MUST include:
- current ticket title
- `urgent` flag
- current ticket status
- ordered public messages:
  - `body_text`
  - `author_type`
  - `source`
- ordered public attachment SHA-256 values
- attachment count

It MUST NOT include:
- internal messages
- assignment
- unread state
- AI run ids

### 18.2 Publication fingerprint
Used immediately before publishing outputs from a run.

It MUST include exactly the same fields as the automatic-trigger fingerprint.

### 18.3 Internal-message rule
Internal messages MAY be included in AI context, but they are **not** part of the automatic-trigger or publication fingerprints.

Consequence:
- adding an internal note does not automatically supersede an in-flight run
- if Dev/TI wants AI to consider a new internal note, they must click rerun

This is intentional.

---

## 19. Worker behavior

The worker is the only component that talks to Codex.

## 19.1 Queue polling
The worker MUST poll for pending `ai_runs` every 10 seconds.

Selection rule:
- oldest `pending` run first
- use row-level locking to avoid duplicate processing

Implementation requirement:
- use `FOR UPDATE SKIP LOCKED` or equivalent safe DB locking behavior

## 19.2 Before running Codex
For a picked run:
1. load ticket
2. load relevant public messages
3. load relevant internal messages
4. load image attachments
5. compute current automatic-trigger fingerprint
6. write `ai_runs.input_hash = current_fingerprint`

If:
- run is not `manual_rerun`
- and current fingerprint == `tickets.last_processed_hash`

then:
- mark run `skipped`
- do not create new messages
- do not change status
- if `requeue_requested = true`, create one new pending run after clearing it

## 19.3 During run
When processing begins:
- set run status = `running`
- set ticket status = `ai_triage`
- write run artifacts into:
  - `/opt/triage/triage_workspace/runs/{ticket_id}/{run_id}/`

## 19.4 After successful run
The worker MUST:
1. validate JSON against schema
2. reload the ticket and recompute the publication fingerprint
3. apply stale-run suppression rules
4. if not superseded:
   - update ticket classification fields
   - publish exactly one internal AI note
   - choose exactly one action path
   - update `last_processed_hash`
   - set run status = `succeeded`
5. process any deferred requeue request

### Action A — `ask_clarification`
- publish one public AI message
- increment `clarification_rounds`
- set ticket status = `waiting_on_user`
- set `last_ai_action = ask_clarification`

### Action B — `auto_public_reply`
- publish one public AI message
- set ticket status = `waiting_on_user`
- set `last_ai_action = auto_public_reply`

### Action C — `auto_confirm_and_route`
- publish one public AI message
- set ticket status = `waiting_on_dev_ti`
- set `last_ai_action = auto_confirm_and_route`

### Action D — `draft_public_reply`
- create one `ai_drafts` row
- set ticket status = `waiting_on_dev_ti`
- set `last_ai_action = draft_public_reply`

### Action E — `route_dev_ti`
- no public AI message
- set ticket status = `waiting_on_dev_ti`
- set `last_ai_action = route_dev_ti`

### Deferred requeue processing
After any non-active end state (`succeeded`, `failed`, `skipped`, `superseded`):
- if `tickets.requeue_requested = true`
- and no active run exists
then:
- create exactly one new `pending` run with `triggered_by = tickets.requeue_trigger`
- clear `requeue_requested`
- clear `requeue_trigger`

## 19.5 Run failure
If Codex:
- exits non-zero
- times out
- returns invalid JSON
- violates schema

then:
- publish one internal system/AI failure note
- set ticket status = `waiting_on_dev_ti`
- set run status = `failed`
- do not publish a public AI message
- process deferred requeue rules afterward

---

## 20. Dev/TI actions

### 20.1 Public reply
Dev/TI can send a public reply.

Result:
- create public `ticket_messages` row
- optional next status chosen by Dev/TI:
  - `waiting_on_user`
  - `waiting_on_dev_ti`
  - `resolved`
- update `ticket_views.last_viewed_at` for the actor

### 20.2 Internal note
Dev/TI can create an internal note.

Result:
- create internal `ticket_messages` row
- no status change by default
- update `ticket_views.last_viewed_at` for the actor

### 20.3 Approve AI draft
If an `ai_drafts` row is `pending_approval`, Dev/TI can:
- approve and publish as-is
- reject
- ignore and write a manual public reply instead

If approved:
- create public `ticket_messages` row with `source = ai_draft_published`
- mark draft = `published`
- Dev/TI chooses next status

If rejected:
- mark draft = `rejected`
- no public message created

### 20.4 Assignment
Dev/TI can assign or unassign `assigned_to_user_id`.

### 20.5 Manual rerun
Dev/TI can request a fresh AI run at any time.

If no active run exists:
- create new `ai_runs` row with `triggered_by = manual_rerun`
- set ticket status = `ai_triage`

If an active run exists:
- set `tickets.requeue_requested = true`
- set `tickets.requeue_trigger = manual_rerun`

---

## 21. Requester actions

### 21.1 Create ticket
Creates:
- `tickets` row
- initial public message
- optional attachments
- pending AI run
- ticket view row

### 21.2 Reply
Creates:
- public requester message
- optional attachments
- pending AI run if no active run exists, otherwise `requeue_requested = true` and `requeue_trigger = requester_reply`
- state becomes `ai_triage`
- requester view timestamp updated

### 21.3 Mark resolved
Requester can mark only their own ticket resolved.

Result:
- state = `resolved`
- `resolved_at` set
- status history row inserted
- requester view timestamp updated

### 21.4 Reopen by reply
If requester replies on a resolved ticket:
- create public requester message
- state = `ai_triage`
- clear `resolved_at`
- enqueue AI run or set `requeue_requested = true` and `requeue_trigger = reopen`

---

## 22. Routes

## 22.1 Auth routes
- `GET /login`
- `POST /login`
- `POST /logout`

## 22.2 Requester routes
- `GET /app`
- `GET /app/tickets`
- `GET /app/tickets/new`
- `POST /app/tickets`
- `GET /app/tickets/{reference}`
- `POST /app/tickets/{reference}/reply`
- `POST /app/tickets/{reference}/resolve`
- `GET /attachments/{attachment_id}`

## 22.3 Dev/TI routes
- `GET /ops`
- `GET /ops/board`
- `GET /ops/tickets/{reference}`
- `POST /ops/tickets/{reference}/assign`
- `POST /ops/tickets/{reference}/set-status`
- `POST /ops/tickets/{reference}/reply-public`
- `POST /ops/tickets/{reference}/note-internal`
- `POST /ops/tickets/{reference}/rerun-ai`
- `POST /ops/drafts/{draft_id}/approve-publish`
- `POST /ops/drafts/{draft_id}/reject`

## 22.4 Health routes
- `GET /healthz`
- `GET /readyz`

---

## 23. Authorization rules

### 23.1 Requester ticket access
A requester may access a ticket only if:
- `tickets.created_by_user_id == current_user.id`

### 23.2 Requester attachment access
A requester may download an attachment only if:
- attachment visibility is `public`
- ticket is owned by current user

### 23.3 Dev/TI access
`dev_ti` and `admin` may access:
- all tickets
- all messages
- all attachments
- all drafts
- all AI runs

### 23.4 Route enforcement
Every route MUST enforce role checks server-side.

---

## 24. Rendering and sanitization

### 24.1 Storage format
Messages MUST be stored as:
- markdown
- plain text

### 24.2 HTML rendering
Rendered HTML MUST be:
1. converted from markdown
2. sanitized with bleach

### 24.3 Forbidden rendering
Raw HTML from users or AI MUST NOT be rendered directly.

---

## 25. Health, logging, and observability

### 25.1 Logs
Web app and worker MUST emit structured JSON logs.

Each log event SHOULD include:
- timestamp
- service
- level
- ticket reference if applicable
- run id if applicable
- event name
- error text if applicable

### 25.2 Health endpoints
- `/healthz` = process alive
- `/readyz` = database reachable and required workspace paths exist

### 25.3 Worker heartbeat
Worker MUST update `system_state.worker_heartbeat` every 60 seconds.

### 25.4 Run artifacts
Each AI run MUST persist:
- prompt file
- schema file
- final output
- stdout jsonl
- stderr

---

## 26. Configuration

Required environment variables:
- `APP_BASE_URL`
- `APP_SECRET_KEY`
- `DATABASE_URL`
- `UPLOADS_DIR`
- `TRIAGE_WORKSPACE_DIR`
- `REPO_MOUNT_DIR`
- `MANUALS_MOUNT_DIR`
- `CODEX_BIN`
- `CODEX_API_KEY`
- `CODEX_MODEL`
- `CODEX_TIMEOUT_SECONDS`
- `WORKER_POLL_SECONDS`
- `AUTO_SUPPORT_REPLY_MIN_CONFIDENCE`
- `AUTO_CONFIRM_INTENT_MIN_CONFIDENCE`
- `MAX_IMAGES_PER_MESSAGE`
- `MAX_IMAGE_BYTES`
- `SESSION_DEFAULT_HOURS`
- `SESSION_REMEMBER_DAYS`

Recommended defaults:
- `UPLOADS_DIR=/opt/triage/data/uploads`
- `TRIAGE_WORKSPACE_DIR=/opt/triage/triage_workspace`
- `REPO_MOUNT_DIR=/opt/triage/triage_workspace/app`
- `MANUALS_MOUNT_DIR=/opt/triage/triage_workspace/manuals`
- `CODEX_TIMEOUT_SECONDS=75`
- `WORKER_POLL_SECONDS=10`
- `AUTO_SUPPORT_REPLY_MIN_CONFIDENCE=0.85`
- `AUTO_CONFIRM_INTENT_MIN_CONFIDENCE=0.90`
- `MAX_IMAGES_PER_MESSAGE=3`
- `MAX_IMAGE_BYTES=5242880`
- `SESSION_DEFAULT_HOURS=12`
- `SESSION_REMEMBER_DAYS=30`

---

## 27. Deployment topology

Stage 1 deployment components:
- PostgreSQL
- FastAPI web app
- Python worker
- WSL workspace mounts

Recommended filesystem layout:

`/opt/triage/`
- `app/`
- `worker/`
- `shared/`
- `scripts/`
- `data/`
  - `uploads/`
  - `logs/`
- `triage_workspace/`
  - `.git/`
  - `AGENTS.md`
  - `.agents/skills/stage1-triage/SKILL.md`
  - `app/`
  - `manuals/`
  - `runs/`

---

## 28. Bootstrap

Bootstrap sequence MUST be:
1. create database schema with Alembic
2. create initial admin user via CLI if absent
3. ensure upload directory exists
4. ensure workspace directory exists
5. initialize workspace Git repo if absent
6. create empty initial commit if needed
7. verify `app/` mount exists and is readable
8. verify `manuals/` mount exists and is readable
9. write `AGENTS.md`
10. write `.agents/skills/stage1-triage/SKILL.md`
11. start web app
12. start worker

Required management commands:
- `create-admin`
- `create-user`
- `set-password`
- `deactivate-user`

No web-based user administration is required in Stage 1.

---

## 29. Exact `AGENTS.md`

Write this exact content to:

`/opt/triage/triage_workspace/AGENTS.md`

```markdown
This repository is the Stage 1 custom triage workspace.

You are performing Stage 1 ticket triage only.

Hard rules:
1. Stage 1 is read-only.
2. Do not modify files under app/ or manuals/.
3. Do not inspect databases, DDL, schema dumps, or logs.
4. Do not use web search.
5. Use only the ticket title, public and internal ticket messages, attached images, files under manuals/, and files under app/.
6. Search manuals/ first for support, access, and operations guidance.
7. Inspect app/ when repository understanding is needed.
8. Distinguish among: support, access_config, data_ops, bug, feature, unknown.
9. Ask at most 3 clarifying questions.
10. Never promise a fix, implementation, release, or timeline.
11. Prefer concise requester-facing replies.
12. Auto-answer support/access questions only when the available evidence strongly supports the answer.
13. If information is ambiguous, missing, conflicting, or likely incorrect, ask clarifying questions instead of guessing.
14. Return only the final JSON object that matches the provided schema.
15. Treat screenshots as evidence but do not claim certainty beyond what is visible.
16. If evidence is weak or absent, do not invent procedural answers.
17. impact_level means business/user impact in Stage 1, not technical blast radius.
18. development_needed is a triage estimate only.
19. Never propose edits, patches, commits, branches, migrations, or database changes in Stage 1.
20. Internal messages may inform internal analysis and routing.
21. Do not disclose internal-only information in automatic public replies unless the same information is already present in public ticket content.
```

---

## 30. Exact `SKILL.md`

Write this exact content to:

`/opt/triage/triage_workspace/.agents/skills/stage1-triage/SKILL.md`

```markdown
---
name: stage1-triage
description: Classify a ticket, search manuals/ and app/ as needed, ask concise clarifying questions when needed, and draft either a safe public reply or an internal routing note. Never modify code, never inspect databases, and never propose patches.
---

Use this skill when:
- the task is a support ticket, internal request, bug report, or feature request written in natural language
- screenshots may help clarify the request
- the workspace contains app/ and manuals/
- the output must be structured JSON for automation

Do not use this skill when:
- code modification is required
- patch generation is required
- database or DDL analysis is required
- external web research is required

Workflow:
1. Read the ticket title and all relevant ticket messages carefully.
2. Search manuals/ first when support, access, or operations guidance may exist.
3. Inspect app/ when repository understanding is needed.
4. Use attached images when relevant.
5. Classify the ticket into exactly one class.
6. Determine if the ticket likely needs development.
7. Determine if clarification is needed.
8. If clarification is needed, ask only the minimum high-value questions, maximum 3.
9. If the available evidence strongly supports an answer and confidence is high, draft a concise public reply.
10. If the request is clearly understood but should go to Dev/TI, draft a concise public confirmation only if it is safe and useful.
11. Always produce a concise internal summary.
12. Internal-only notes may inform internal summaries and routing, but must not be disclosed in automatic public replies unless already public.
13. Return only the final JSON matching the provided schema.

Quality bar:
- do not repeat information already present
- do not ask questions that the image or files already answer
- do not claim certainty without evidence
- keep public text concise and practical
```

---

## 31. Exact JSON schema

Use this exact schema with `--output-schema`:

```json
{
  "type": "object",
  "additionalProperties": false,
  "properties": {
    "ticket_class": {
      "type": "string",
      "enum": ["support", "access_config", "data_ops", "bug", "feature", "unknown"]
    },
    "confidence": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0
    },
    "impact_level": {
      "type": "string",
      "enum": ["low", "medium", "high", "unknown"]
    },
    "requester_language": {
      "type": "string",
      "minLength": 2
    },
    "summary_short": {
      "type": "string",
      "minLength": 1,
      "maxLength": 120
    },
    "summary_internal": {
      "type": "string",
      "minLength": 1
    },
    "development_needed": {
      "type": "boolean"
    },
    "needs_clarification": {
      "type": "boolean"
    },
    "clarifying_questions": {
      "type": "array",
      "maxItems": 3,
      "items": {
        "type": "string",
        "minLength": 1
      }
    },
    "incorrect_or_conflicting_details": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1
      }
    },
    "evidence_found": {
      "type": "boolean"
    },
    "relevant_paths": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "path": { "type": "string" },
          "reason": { "type": "string" }
        },
        "required": ["path", "reason"]
      }
    },
    "recommended_next_action": {
      "type": "string",
      "enum": [
        "ask_clarification",
        "auto_public_reply",
        "auto_confirm_and_route",
        "draft_public_reply",
        "route_dev_ti"
      ]
    },
    "auto_public_reply_allowed": {
      "type": "boolean"
    },
    "public_reply_markdown": {
      "type": "string"
    },
    "internal_note_markdown": {
      "type": "string",
      "minLength": 1
    }
  },
  "required": [
    "ticket_class",
    "confidence",
    "impact_level",
    "requester_language",
    "summary_short",
    "summary_internal",
    "development_needed",
    "needs_clarification",
    "clarifying_questions",
    "incorrect_or_conflicting_details",
    "evidence_found",
    "relevant_paths",
    "recommended_next_action",
    "auto_public_reply_allowed",
    "public_reply_markdown",
    "internal_note_markdown"
  ]
}
```

Application-level validation rules:
- `ask_clarification` requires `needs_clarification = true`
- `ask_clarification` requires `public_reply_markdown` non-empty
- `auto_public_reply` requires `auto_public_reply_allowed = true`
- `auto_public_reply` requires `evidence_found = true`
- `auto_public_reply` requires `public_reply_markdown` non-empty
- `auto_confirm_and_route` requires `auto_public_reply_allowed = true`
- `auto_confirm_and_route` requires `public_reply_markdown` non-empty
- `draft_public_reply` requires `auto_public_reply_allowed = false`
- `draft_public_reply` requires `public_reply_markdown` non-empty
- `route_dev_ti` allows `public_reply_markdown` empty
- if `ticket_class = unknown`, `recommended_next_action` cannot be `auto_public_reply`

---

## 32. Prompt skeleton

Use this exact structure for each AI run:

```text
$stage1-triage

Task:
Analyze this internal ticket for Stage 1 triage only.

Constraints:
- Use only the ticket title, ticket messages, attached images, files under manuals/, and files under app/.
- Search manuals/ first when support, access, or operations guidance may exist.
- Inspect app/ when repository understanding is needed.
- Do not use databases, logs, DDL, schema dumps, or external web search.
- Return only valid JSON matching the provided schema.
- Ask at most 3 clarifying questions.
- Never promise a fix, implementation, or timeline.
- Internal messages may inform internal analysis and routing but MUST NOT be disclosed in automatic public replies unless the same information is already public on the ticket.

Ticket reference:
{REFERENCE}

Ticket title:
{TITLE}

Current status:
{STATUS}

Urgent:
{URGENT}

Public messages:
{PUBLIC_MESSAGES}

Internal messages:
{INTERNAL_MESSAGES}

Decision policy:
- Classify into exactly one of: support, access_config, data_ops, bug, feature, unknown.
- impact_level means business/user impact only.
- development_needed is only a triage estimate.
- Search manuals/ before answering support or access/config questions.
- Inspect app/ when repository understanding is needed.
- If the available evidence strongly supports an answer and confidence is high, you may draft a concise public reply.
- If the request is understood but should go to Dev/TI, you may draft a safe public confirmation and route it.
- If information is ambiguous, missing, conflicting, or likely incorrect, ask concise clarifying questions instead of guessing.
- If no safe public reply should be prepared, leave public_reply_markdown empty and set auto_public_reply_allowed to false.

Output:
Return only the JSON object.
```

---

## 33. Codex command template

Run Codex with a command equivalent to:

```bash
CODEX_API_KEY="${CODEX_API_KEY}" \
"${CODEX_BIN}" exec \
  --ephemeral \
  --sandbox read-only \
  --ask-for-approval never \
  --json \
  --output-schema "${RUN_DIR}/schema.json" \
  --output-last-message "${RUN_DIR}/final.json" \
  -c web_search="disabled" \
  ${MODEL_ARG} \
  ${IMAGE_ARGS} \
  "${PROMPT}"
```

Where:
- `MODEL_ARG` is empty or `--model "${CODEX_MODEL}"`
- `IMAGE_ARGS` repeats `--image /absolute/path/to/file`
- working directory is `/opt/triage/triage_workspace`
- `${RUN_DIR}/final.json` is the canonical parsed result

---

## 34. Acceptance criteria

### AC1 — Authentication
A user can log in with local credentials and optionally remain logged in via “remember me”.

### AC2 — Server-side sessions
The implementation uses PostgreSQL-backed sessions with an opaque cookie token and does not use framework signed-cookie session middleware for primary auth state.

### AC3 — Requester isolation
A requester can see only their own tickets and only public messages/attachments on those tickets.

### AC4 — New ticket
A requester can create a ticket with optional title, required free-text description, optional urgency flag, and optional PNG/JPEG images.

### AC5 — Clarification
A vague ticket causes the worker to:
- classify it
- publish at most 3 public clarifying questions
- set status to `waiting_on_user`

### AC6 — Safe public auto-reply
A clear support/access ticket with strong evidence causes the worker to:
- publish a public AI reply
- set status to `waiting_on_user`

### AC7 — Safe public confirm-and-route
A clearly understood ticket that still needs Dev/TI review can receive a short public confirmation and be moved to `waiting_on_dev_ti`.

### AC8 — Dev/TI route
A likely bug or feature request causes the worker to:
- publish exactly one internal AI note
- set status to `waiting_on_dev_ti`

### AC9 — Draft approval
When a safe public reply exists but should not be auto-sent, the worker creates an AI draft that Dev/TI can approve or reject.

### AC10 — Internal/public separation
Requesters never see internal notes or internal AI analysis.

### AC11 — Internal-note non-leak
Automatic public AI replies do not disclose facts present only in internal messages.

### AC12 — Repo-aware triage
Codex can inspect files under `app/` and `manuals/` in read-only mode and use them in its analysis.

### AC13 — No modifications
No Stage 1 path modifies the repository, creates patches, creates branches, or touches SQL Server.

### AC14 — Reopen by reply
A requester reply on a resolved ticket reopens it and enqueues or requeues a new AI run.

### AC15 — One active run per ticket
The system enforces at most one active (`pending` or `running`) AI run per ticket, with requeue behavior if new input arrives during processing.

### AC16 — Stale run suppression
If requester-facing input changes during a run, that stale run publishes no messages, causes no status transition, and is marked `superseded`.

### AC17 — Uploads work at stated limits
The app accepts up to 3 PNG/JPEG files of up to 5 MiB each on ticket creation and replies.

### AC18 — Unread markers work
Opening a ticket detail page marks it read for that user; list and board pages do not implicitly mark tickets read.

### AC19 — No external systems
There is no dependency on Kanboard, Slack, SMTP, or any external board or notification system.

---

## 35. File/module structure

The implementation MUST create a repository resembling:

`triage-stage1/`
- `README.md`
- `.env.example`
- `requirements.txt`
- `app/`
  - `main.py`
  - `auth.py`
  - `routes_auth.py`
  - `routes_requester.py`
  - `routes_ops.py`
  - `templates/`
  - `static/`
  - `render.py`
  - `uploads.py`
- `worker/`
  - `main.py`
  - `queue.py`
  - `triage.py`
  - `codex_runner.py`
  - `ticket_loader.py`
- `shared/`
  - `db.py`
  - `models.py`
  - `migrations/`
  - `config.py`
  - `security.py`
  - `permissions.py`
- `scripts/`
  - `create_admin.py`
  - `create_user.py`
  - `set_password.py`
  - `bootstrap_workspace.py`
  - `run_web.py`
  - `run_worker.py`

The exact filenames may vary slightly if the same logical separation is preserved.

---

## 36. Final implementation instruction

If a detail is not explicitly defined above, the implementation agent MUST choose the simpler option that preserves all of the following:
1. requesters have a simple thread-first experience
2. Dev/TI have a board/list and ticket-detail workflow
3. PostgreSQL remains the single source of truth
4. public and internal messages remain strictly separated
5. Codex remains read-only and repo-aware
6. Stage 1 does not drift into patch generation or infrastructure overengineering
