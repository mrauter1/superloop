# Test Author ↔ Test Auditor Feedback

- Task ID: standalone-implementation-plan-for-the-new-super-5226e1de
- Pair: test
- Phase ID: shared-prompt-loading-and-artifact-ownership-split
- Phase Directory Key: shared-prompt-loading-and-artifact-ownership-split
- Phase Title: Load prompts from shared templates and split artifact ownership rules
- Scope: phase-local authoritative verifier artifact

- Added a direct `run_codex_phase(...)` regression test for shared template provenance logging in task/run raw logs, and documented the phase coverage map for prompt sourcing, decisions-path preambles, and tracked-vs-exempt artifact behavior.
- TST-000 | non-blocking | No audit findings. The focused test set now covers shared-template prompt provenance in raw logs, the `AUTHORITATIVE SHARED DECISIONS FILE` prompt path, and the `decisions.txt` tracked-vs-verifier-exempt split without introducing flaky dependencies.
