# Implementation Notes

- Task ID: i-made-the-remaining-fixes-and-revalidated-the-u-5a08fdb7
- Pair: implement
- Phase ID: ai-worker
- Phase Directory Key: ai-worker
- Phase Title: AI Worker and Codex Orchestration
- Scope: phase-local producer artifact

## Files changed
- `shared/ticketing.py`
- `worker/codex_runner.py`
- `worker/main.py`
- `worker/triage.py`
- `tests/test_ai_worker.py`

## Symbols touched
- `shared.ticketing.apply_ai_classification`
- `shared.ticketing.publish_ai_internal_note`
- `shared.ticketing.publish_ai_failure_note`
- `shared.ticketing.publish_ai_public_reply`
- `shared.ticketing.create_ai_draft`
- `shared.ticketing.route_ticket_after_ai`
- `shared.ticketing.process_deferred_requeue`
- `worker.codex_runner.PreparedCodexRun`
- `worker.codex_runner.CodexRunArtifacts`
- `worker.codex_runner.prepare_codex_run`
- `worker.codex_runner.build_triage_prompt`
- `worker.codex_runner.build_codex_command`
- `worker.codex_runner.execute_codex_run`
- `worker.triage.build_requester_visible_fingerprint`
- `worker.triage.validate_triage_result`
- `worker.triage.process_ai_run`
- `worker.main.emit_worker_heartbeat`
- `worker.main.heartbeat_loop`
- `worker.main.start_heartbeat_thread`
- `worker.main.main`

## Checklist mapping
- Phase 4 queue/loop: the worker now claims the oldest pending run, marks it running, processes it, and continues heartbeat updates.
- Reviewer fixup: heartbeat writes now run on a dedicated background loop so long Codex executions do not violate the 60-second worker heartbeat contract.
- Reviewer fixup: `process_ai_run` now converts unexpected post-claim errors on both the exec/validation path and the success-publication path into `_mark_failed()` so claimed runs do not get stranded in `running`.
- Phase 4 Codex contract: prompt/schema/final/stdout/stderr artifacts are written under `runs/{ticket_id}/{run_id}/`, and Codex is invoked with the required read-only/non-interactive flags.
- Phase 4 stale-run handling: automatic-trigger/publication fingerprinting, skip logic, supersede-on-change, and deferred requeue processing are implemented on the worker path.
- Phase 4 publication order: successful non-superseded runs now validate output, apply classification, publish exactly one internal AI note, execute one action path, update `last_processed_hash`, and then mark the run succeeded.
- Phase 4 failure handling: Codex/process/schema failures now create one internal failure note, move the ticket to `waiting_on_dev_ti`, and drain any deferred requeue.

## Assumptions
- A stale publication fingerprint without an already-set `requeue_requested` flag is treated as requester-visible input drift and requeued with the safe fallback trigger `requester_reply`.
- The worker records the pre-exec `ai_triage` status transition as `changed_by_type = system`, reserving `changed_by_type = ai` for post-result action-path transitions.

## Preserved invariants
- The worker remains the only component that invokes Codex.
- Internal messages are prompt context only and stay out of both fingerprint calculations.
- Successful non-superseded runs publish exactly one internal AI note and no second internal AI message on the action path.
- Deferred requeue creation still depends on the one-active-run DB invariant rather than a parallel in-memory queue.
- Claimed runs now have a best-effort terminal-state fallback for any unexpected exception that occurs after the worker has taken ownership of the row.

## Intended behavior changes
- Pending AI runs now execute end to end through prompt generation, Codex invocation, structured validation, and publication.
- Ops ticket detail can now read real worker-produced `final.json` artifacts and the canonical internal AI note/message stream.

## Known non-changes
- The worker still does not modify repository files, propose patches, inspect databases, or use web search.
- Title normalization to `[Class] {summary_short}` remains intentionally unimplemented because the PRD marks it optional.

## Expected side effects
- New successful runs now create prompt/schema/output/stdout/stderr artifacts even when the final action is draft-only or route-only.
- Deferred requeue checks flush the just-finished run status before probing for active runs so `autoflush=False` sessions do not suppress legitimate follow-up runs.
- Heartbeat writes now continue independently while the main loop is blocked inside Codex execution.

## Validation performed
- `python -m compileall worker shared tests`
- `pytest -q tests/test_foundation_persistence.py tests/test_auth_requester.py tests/test_ops_workflow.py tests/test_ai_worker.py`
- `pytest -q`

## Deduplication / centralization decisions
- Worker publication/state transitions were added to `shared.ticketing` so route and worker paths continue to share the same status-history and `updated_at` semantics.
- Codex subprocess/artifact handling stays isolated in `worker.codex_runner`, while `worker.triage` owns only run lifecycle, validation, and publication decisions.
- Heartbeat scheduling was moved into `worker.main` rather than the Codex runner so heartbeat liveness remains orthogonal to subprocess execution and run-state mutation logic.
