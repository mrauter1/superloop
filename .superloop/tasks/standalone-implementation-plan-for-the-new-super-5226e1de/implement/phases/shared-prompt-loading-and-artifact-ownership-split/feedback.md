# Implement ↔ Code Reviewer Feedback

- Task ID: standalone-implementation-plan-for-the-new-super-5226e1de
- Pair: implement
- Phase ID: shared-prompt-loading-and-artifact-ownership-split
- Phase Directory Key: shared-prompt-loading-and-artifact-ownership-split
- Phase Title: Load prompts from shared templates and split artifact ownership rules
- Scope: phase-local authoritative verifier artifact

- IMP-000 | non-blocking | No review findings. Prompt construction is sourced from shared in-memory templates, prompt preambles include the authoritative `decisions.txt` path, and verifier scope enforcement now keeps runtime bookkeeping exempt while still flagging edits to `decisions.txt`.
