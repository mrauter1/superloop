# Implement ↔ Code Reviewer Feedback

- Task ID: standalone-implementation-plan-for-the-new-super-5226e1de
- Pair: implement
- Phase ID: template-and-artifact-contract-alignment
- Phase Directory Key: template-and-artifact-contract-alignment
- Phase Title: Align templates and scaffolded artifact layout
- Scope: phase-local authoritative verifier artifact

## IMP-000 `non-blocking`
No findings. The scoped implementation replaces the six shared prompt templates, removes prompt-copy and run-log/summary scaffolding, adds task-root `decisions.txt`, removes redundant phase artifacts from scaffold generation, and updates tests to cover the final artifact layout and in-memory prompt sourcing.
