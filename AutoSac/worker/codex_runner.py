from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import subprocess

from shared.config import Settings
from shared.contracts import TRIAGE_OUTPUT_SCHEMA, TRIAGE_PROMPT_TEMPLATE
from worker.ticket_loader import LoadedTicketContext


class CodexRunError(RuntimeError):
    """Raised when Codex execution fails or does not produce a canonical result."""


@dataclass(frozen=True)
class PreparedCodexRun:
    run_dir: Path
    prompt: str
    prompt_path: Path
    schema_path: Path
    final_output_path: Path
    stdout_jsonl_path: Path
    stderr_path: Path
    image_paths: list[Path]


@dataclass(frozen=True)
class CodexRunArtifacts:
    prepared: PreparedCodexRun
    completed_process: subprocess.CompletedProcess[str]
    output_payload: dict[str, object]


def _format_messages(messages) -> str:
    if not messages:
        return "(none)"
    blocks: list[str] = []
    for index, message in enumerate(messages, start=1):
        blocks.append(
            "\n".join(
                [
                    f"{index}. author_type={message.author_type}; source={message.source}; created_at={message.created_at.isoformat()}",
                    message.body_text,
                ]
            )
        )
    return "\n\n".join(blocks)


def build_triage_prompt(context: LoadedTicketContext) -> str:
    return TRIAGE_PROMPT_TEMPLATE.format(
        REFERENCE=context.ticket.reference,
        TITLE=context.ticket.title,
        STATUS=context.ticket.status,
        URGENT="yes" if context.ticket.urgent else "no",
        PUBLIC_MESSAGES=_format_messages(context.public_messages),
        INTERNAL_MESSAGES=_format_messages(context.internal_messages),
    )


def prepare_codex_run(
    settings: Settings,
    *,
    ticket_id,
    run_id,
    context: LoadedTicketContext,
) -> PreparedCodexRun:
    run_dir = settings.runs_dir / str(ticket_id) / str(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_triage_prompt(context)
    prompt_path = run_dir / "prompt.txt"
    schema_path = run_dir / "schema.json"
    final_output_path = run_dir / "final.json"
    stdout_jsonl_path = run_dir / "stdout.jsonl"
    stderr_path = run_dir / "stderr.txt"

    prompt_path.write_text(prompt, encoding="utf-8")
    schema_path.write_text(TRIAGE_OUTPUT_SCHEMA, encoding="utf-8")

    image_paths = [Path(attachment.stored_path) for attachment in context.public_attachments]
    return PreparedCodexRun(
        run_dir=run_dir,
        prompt=prompt,
        prompt_path=prompt_path,
        schema_path=schema_path,
        final_output_path=final_output_path,
        stdout_jsonl_path=stdout_jsonl_path,
        stderr_path=stderr_path,
        image_paths=image_paths,
    )


def build_codex_command(
    settings: Settings,
    *,
    prepared: PreparedCodexRun,
) -> tuple[list[str], dict[str, str]]:
    command = [
        settings.codex_bin,
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--ask-for-approval",
        "never",
        "--json",
        "--output-schema",
        str(prepared.schema_path),
        "--output-last-message",
        str(prepared.final_output_path),
        "-c",
        'web_search="disabled"',
    ]
    if settings.codex_model:
        command.extend(["--model", settings.codex_model])
    for image_path in prepared.image_paths:
        command.extend(["--image", str(image_path)])
    command.append(prepared.prompt)
    env = os.environ.copy()
    env["CODEX_API_KEY"] = settings.codex_api_key
    return command, env


def _write_stream(path: Path, contents: str | None) -> None:
    path.write_text(contents or "", encoding="utf-8")


def _load_final_output(final_output_path: Path) -> dict[str, object]:
    if not final_output_path.is_file():
        raise CodexRunError("Codex did not write final.json")
    try:
        payload = json.loads(final_output_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexRunError("Codex final.json was missing or invalid JSON") from exc
    if not isinstance(payload, dict):
        raise CodexRunError("Codex final.json must contain a JSON object")
    return payload


def execute_codex_run(settings: Settings, *, prepared: PreparedCodexRun) -> CodexRunArtifacts:
    command, env = build_codex_command(settings, prepared=prepared)
    try:
        completed = subprocess.run(
            command,
            cwd=settings.triage_workspace_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=settings.codex_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _write_stream(prepared.stdout_jsonl_path, exc.stdout)
        _write_stream(prepared.stderr_path, exc.stderr)
        raise CodexRunError(
            f"Codex timed out after {settings.codex_timeout_seconds} seconds"
        ) from exc

    _write_stream(prepared.stdout_jsonl_path, completed.stdout)
    _write_stream(prepared.stderr_path, completed.stderr)
    if completed.returncode != 0:
        raise CodexRunError(f"Codex exited with status {completed.returncode}")
    payload = _load_final_output(prepared.final_output_path)
    return CodexRunArtifacts(prepared=prepared, completed_process=completed, output_payload=payload)
