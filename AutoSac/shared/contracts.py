from __future__ import annotations

from pathlib import Path

SESSION_COOKIE_NAME = "triage_session"
CSRF_FORM_FIELD = "csrf_token"
WORKSPACE_BOOTSTRAP_VERSION = "stage1-v1"

APP_ROUTES = (
    "/login",
    "/logout",
    "/app",
    "/app/tickets",
    "/app/tickets/new",
    "/app/tickets/{reference}",
    "/app/tickets/{reference}/reply",
    "/app/tickets/{reference}/resolve",
    "/attachments/{attachment_id}",
    "/ops",
    "/ops/board",
    "/ops/tickets/{reference}",
    "/ops/tickets/{reference}/assign",
    "/ops/tickets/{reference}/set-status",
    "/ops/tickets/{reference}/reply-public",
    "/ops/tickets/{reference}/note-internal",
    "/ops/tickets/{reference}/rerun-ai",
    "/ops/drafts/{draft_id}/approve-publish",
    "/ops/drafts/{draft_id}/reject",
    "/healthz",
    "/readyz",
)

CLI_COMMAND_NAMES = (
    "create-admin",
    "create-user",
    "set-password",
    "deactivate-user",
)

DEFAULT_UPLOADS_DIR = Path("/opt/triage/data/uploads")
DEFAULT_TRIAGE_WORKSPACE_DIR = Path("/opt/triage/triage_workspace")
DEFAULT_REPO_MOUNT_DIR = DEFAULT_TRIAGE_WORKSPACE_DIR / "app"
DEFAULT_MANUALS_MOUNT_DIR = DEFAULT_TRIAGE_WORKSPACE_DIR / "manuals"
DEFAULT_RUNS_DIR = DEFAULT_TRIAGE_WORKSPACE_DIR / "runs"

WORKSPACE_AGENTS_RELATIVE_PATH = Path("AGENTS.md")
WORKSPACE_SKILL_RELATIVE_PATH = Path(".agents/skills/stage1-triage/SKILL.md")

WORKSPACE_AGENTS_CONTENT = """This repository is the Stage 1 custom triage workspace.

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
"""

WORKSPACE_SKILL_CONTENT = """---
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
"""

TRIAGE_OUTPUT_SCHEMA = """{
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
"""

TRIAGE_PROMPT_TEMPLATE = """$stage1-triage

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
"""
