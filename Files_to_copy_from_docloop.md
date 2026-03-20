# Superloop standalone repo: exact files to copy

Use this checklist to split a standalone Superloop repository out of this monorepo.

## 1) Minimal runnable Superloop (production)

Copy exactly these files:

- `superloop.py`
- `loop_control.py`

Also install runtime dependencies in the new repo environment:

- `PyYAML` (needed when using explicit `phase_plan.yaml` flows)

## 2) If you also want Superloop tests in the new repo

Copy these additional test files:

- `tests/test_loop_control.py`
- `tests/test_superloop_git_tracking.py`
- `tests/test_superloop_observability.py`
- `tests/fixtures/loop_control/canonical_invalid_kind.txt`
- `tests/fixtures/loop_control/canonical_unknown_schema.txt`
- `tests/fixtures/loop_control/canonical_malformed_json.txt`
- `tests/fixtures/loop_control/canonical_multiple_blocks.txt`
- `tests/fixtures/loop_control/canonical_mixed_with_legacy.txt`
- `tests/fixtures/loop_control/canonical_leading_prose.txt`
- `tests/fixtures/loop_control/canonical_trailing_prose.txt`
- `tests/fixtures/loop_control/canonical_question.txt`
- `tests/fixtures/loop_control/canonical_question_best_supposition.txt`
- `tests/fixtures/loop_control/canonical_invalid_promise.txt`
- `tests/fixtures/loop_control/canonical_promise_complete.txt`
- `tests/fixtures/loop_control/canonical_promise_incomplete.txt`
- `tests/fixtures/loop_control/legacy_question_only.txt`
- `tests/fixtures/loop_control/legacy_multiline_question.txt`
- `tests/fixtures/loop_control/legacy_promise_only.txt`
- `tests/fixtures/loop_control/legacy_promise_in_prose.txt`
- `tests/fixtures/loop_control/legacy_question_and_promise.txt`
- `tests/fixtures/loop_control/no_control.txt`

## 3) Suggested copy commands (from repo root)

### Minimal runnable set

```bash
mkdir -p /path/to/new-superloop-repo
cp superloop.py loop_control.py /path/to/new-superloop-repo/
```

### Include tests too

```bash
mkdir -p /path/to/new-superloop-repo/tests/fixtures/loop_control
cp tests/test_loop_control.py tests/test_superloop_git_tracking.py tests/test_superloop_observability.py /path/to/new-superloop-repo/tests/
cp tests/fixtures/loop_control/*.txt /path/to/new-superloop-repo/tests/fixtures/loop_control/
```
