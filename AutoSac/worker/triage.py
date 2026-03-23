from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import hashlib
import json
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.config import Settings
from shared.db import session_scope
from shared.models import AIRun, Ticket
from shared.security import utc_now
from shared.ticketing import (
    apply_ai_classification,
    create_ai_draft,
    process_deferred_requeue,
    publish_ai_failure_note,
    publish_ai_internal_note,
    publish_ai_public_reply,
    record_status_change,
    request_requeue,
    route_ticket_after_ai,
)
from worker.codex_runner import CodexRunError, PreparedCodexRun, execute_codex_run, prepare_codex_run
from worker.ticket_loader import LoadedTicketContext, load_ticket_context


class TriageResultError(RuntimeError):
    """Raised when the canonical Codex output violates the Stage 1 contract."""


class RelevantPathResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    reason: str


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_class: Literal["support", "access_config", "data_ops", "bug", "feature", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    impact_level: Literal["low", "medium", "high", "unknown"]
    requester_language: str = Field(min_length=2)
    summary_short: str = Field(min_length=1, max_length=120)
    summary_internal: str = Field(min_length=1)
    development_needed: bool
    needs_clarification: bool
    clarifying_questions: list[str] = Field(max_length=3)
    incorrect_or_conflicting_details: list[str]
    evidence_found: bool
    relevant_paths: list[RelevantPathResult]
    recommended_next_action: Literal[
        "ask_clarification",
        "auto_public_reply",
        "auto_confirm_and_route",
        "draft_public_reply",
        "route_dev_ti",
    ]
    auto_public_reply_allowed: bool
    public_reply_markdown: str
    internal_note_markdown: str = Field(min_length=1)


@dataclass(frozen=True)
class PreparedRunContext:
    run_id: uuid.UUID
    ticket_id: uuid.UUID
    input_hash: str
    prepared_codex_run: PreparedCodexRun


def build_requester_visible_fingerprint(context: LoadedTicketContext) -> str:
    payload = {
        "title": context.ticket.title,
        "urgent": context.ticket.urgent,
        "status": context.ticket.status,
        "public_messages": [
            {
                "body_text": message.body_text,
                "author_type": message.author_type,
                "source": message.source,
            }
            for message in context.public_messages
        ],
        "attachment_sha256": [attachment.sha256 for attachment in context.public_attachments],
        "attachment_count": len(context.public_attachments),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_triage_result(payload: dict[str, object], settings: Settings) -> TriageResult:
    try:
        result = TriageResult.model_validate(payload)
    except ValidationError as exc:
        raise TriageResultError(f"Codex output failed schema validation: {exc}") from exc

    public_reply = result.public_reply_markdown.strip()
    internal_note = result.internal_note_markdown.strip()
    if not internal_note:
        raise TriageResultError("internal_note_markdown must not be blank")

    action = result.recommended_next_action
    if action == "ask_clarification":
        if not result.needs_clarification:
            raise TriageResultError("ask_clarification requires needs_clarification=true")
        if not public_reply:
            raise TriageResultError("ask_clarification requires a non-empty public reply")
    elif action == "auto_public_reply":
        if not result.auto_public_reply_allowed:
            raise TriageResultError("auto_public_reply requires auto_public_reply_allowed=true")
        if not result.evidence_found:
            raise TriageResultError("auto_public_reply requires evidence_found=true")
        if not public_reply:
            raise TriageResultError("auto_public_reply requires a non-empty public reply")
        if result.confidence < settings.auto_support_reply_min_confidence:
            raise TriageResultError("auto_public_reply confidence is below the configured threshold")
    elif action == "auto_confirm_and_route":
        if not result.auto_public_reply_allowed:
            raise TriageResultError("auto_confirm_and_route requires auto_public_reply_allowed=true")
        if not public_reply:
            raise TriageResultError("auto_confirm_and_route requires a non-empty public reply")
        if result.confidence < settings.auto_confirm_intent_min_confidence:
            raise TriageResultError("auto_confirm_and_route confidence is below the configured threshold")
    elif action == "draft_public_reply":
        if result.auto_public_reply_allowed:
            raise TriageResultError("draft_public_reply requires auto_public_reply_allowed=false")
        if not public_reply:
            raise TriageResultError("draft_public_reply requires a non-empty public reply")
    elif action == "route_dev_ti":
        pass
    else:
        raise TriageResultError(f"Unsupported recommended_next_action: {action}")

    if result.ticket_class == "unknown" and action == "auto_public_reply":
        raise TriageResultError("unknown tickets cannot use auto_public_reply")
    return result


def _prepare_run(settings: Settings, *, run_id) -> PreparedRunContext | None:
    with session_scope(settings) as db:
        run = db.get(AIRun, run_id)
        if run is None or run.status != "running":
            return None

        context = load_ticket_context(db, run.ticket_id)
        current_fingerprint = build_requester_visible_fingerprint(context)

        if run.triggered_by != "manual_rerun" and current_fingerprint == context.ticket.last_processed_hash:
            run.input_hash = current_fingerprint
            run.model_name = settings.codex_model or None
            run.error_text = None
            run.status = "skipped"
            run.ended_at = utc_now()
            process_deferred_requeue(db, ticket=context.ticket)
            return None

        if context.ticket.status != "ai_triage":
            record_status_change(
                db,
                ticket=context.ticket,
                to_status="ai_triage",
                changed_by_type="system",
                changed_at=utc_now(),
            )
            context = load_ticket_context(db, run.ticket_id)

        input_hash = build_requester_visible_fingerprint(context)
        prepared = prepare_codex_run(
            settings,
            ticket_id=context.ticket.id,
            run_id=run.id,
            context=context,
        )

        run.input_hash = input_hash
        run.model_name = settings.codex_model or None
        run.prompt_path = str(prepared.prompt_path)
        run.schema_path = str(prepared.schema_path)
        run.final_output_path = str(prepared.final_output_path)
        run.stdout_jsonl_path = str(prepared.stdout_jsonl_path)
        run.stderr_path = str(prepared.stderr_path)
        run.error_text = None

        return PreparedRunContext(
            run_id=run.id,
            ticket_id=context.ticket.id,
            input_hash=input_hash,
            prepared_codex_run=prepared,
        )


def _effective_next_action(ticket: Ticket, result: TriageResult) -> str:
    if result.recommended_next_action == "ask_clarification" and ticket.clarification_rounds >= 2:
        return "route_dev_ti"
    return result.recommended_next_action


def _mark_superseded_due_to_stale_input(db, *, run: AIRun, ticket: Ticket) -> None:
    if not ticket.requeue_requested:
        request_requeue(ticket, ticket.requeue_trigger or "requester_reply")
    run.status = "superseded"
    run.ended_at = utc_now()
    run.error_text = None
    process_deferred_requeue(db, ticket=ticket)


def _apply_success_result(settings: Settings, *, run_id, result: TriageResult) -> None:
    with session_scope(settings) as db:
        run = db.get(AIRun, run_id)
        if run is None:
            return
        context = load_ticket_context(db, run.ticket_id)
        publication_hash = build_requester_visible_fingerprint(context)

        if context.ticket.requeue_requested or publication_hash != run.input_hash:
            _mark_superseded_due_to_stale_input(db, run=run, ticket=context.ticket)
            return

        completed_at = utc_now()
        apply_ai_classification(
            context.ticket,
            ticket_class=result.ticket_class,
            confidence=result.confidence,
            impact_level=result.impact_level,
            development_needed=result.development_needed,
            requester_language=result.requester_language,
        )
        publish_ai_internal_note(
            db,
            ticket=context.ticket,
            ai_run_id=run.id,
            body_markdown=result.internal_note_markdown,
            created_at=completed_at,
        )

        action = _effective_next_action(context.ticket, result)
        if action == "ask_clarification":
            publish_ai_public_reply(
                db,
                ticket=context.ticket,
                ai_run_id=run.id,
                body_markdown=result.public_reply_markdown,
                next_status="waiting_on_user",
                last_ai_action="ask_clarification",
                increment_clarification_rounds=True,
                created_at=completed_at,
            )
        elif action == "auto_public_reply":
            publish_ai_public_reply(
                db,
                ticket=context.ticket,
                ai_run_id=run.id,
                body_markdown=result.public_reply_markdown,
                next_status="waiting_on_user",
                last_ai_action="auto_public_reply",
                created_at=completed_at,
            )
        elif action == "auto_confirm_and_route":
            publish_ai_public_reply(
                db,
                ticket=context.ticket,
                ai_run_id=run.id,
                body_markdown=result.public_reply_markdown,
                next_status="waiting_on_dev_ti",
                last_ai_action="auto_confirm_and_route",
                created_at=completed_at,
            )
        elif action == "draft_public_reply":
            create_ai_draft(
                db,
                ticket=context.ticket,
                ai_run_id=run.id,
                body_markdown=result.public_reply_markdown,
                created_at=completed_at,
            )
        elif action == "route_dev_ti":
            route_ticket_after_ai(
                db,
                ticket=context.ticket,
                next_status="waiting_on_dev_ti",
                last_ai_action="route_dev_ti",
                created_at=completed_at,
            )

        context.ticket.last_processed_hash = publication_hash
        run.status = "succeeded"
        run.ended_at = completed_at
        run.error_text = None
        process_deferred_requeue(db, ticket=context.ticket)


def _failure_note_body(error_text: str) -> str:
    return "\n".join(
        [
            "AI triage run failed and was routed to Dev/TI for manual review.",
            "",
            f"Error: {error_text}",
        ]
    )


def _mark_failed(settings: Settings, *, run_id, error_text: str) -> None:
    with session_scope(settings) as db:
        run = db.get(AIRun, run_id)
        if run is None:
            return
        ticket = db.get(Ticket, run.ticket_id)
        failed_at = utc_now()
        run.status = "failed"
        run.ended_at = failed_at
        run.error_text = error_text

        if ticket is not None:
            publish_ai_failure_note(
                db,
                ticket=ticket,
                ai_run_id=run.id,
                body_markdown=_failure_note_body(error_text),
                created_at=failed_at,
            )
            if ticket.status != "waiting_on_dev_ti":
                record_status_change(
                    db,
                    ticket=ticket,
                    to_status="waiting_on_dev_ti",
                    changed_by_type="system",
                    changed_at=failed_at,
                )
            process_deferred_requeue(db, ticket=ticket)


def process_ai_run(settings: Settings, *, run_id) -> None:
    terminal_run_id = run_id
    try:
        prepared = _prepare_run(settings, run_id=run_id)
        if prepared is None:
            return
        terminal_run_id = prepared.run_id
        artifacts = execute_codex_run(settings, prepared=prepared.prepared_codex_run)
        result = validate_triage_result(artifacts.output_payload, settings)
        _apply_success_result(settings, run_id=prepared.run_id, result=result)
    except (CodexRunError, TriageResultError) as exc:
        _mark_failed(settings, run_id=terminal_run_id, error_text=str(exc))
    except Exception as exc:
        _mark_failed(settings, run_id=terminal_run_id, error_text=f"Unexpected worker error: {exc}")
