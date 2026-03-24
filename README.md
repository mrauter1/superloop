# Autoloop

Protocol-driven agent loops for shipping real code with less babysitting.

Autoloop is a stateful orchestration runtime for repository work. It runs plan, implement, and test producer/verifier pairs with durable state, resumable runs, phase scoping, and git-backed checkpoints.

## Requirements

- Python 3.10+
- `codex`
- `git` is optional when running with `--no-git`

## Install

Install from PyPI:

```bash
pip install autoloop
autoloop --help
```

Install from this repository:

```bash
python -m pip install -e .
autoloop --help
python -m autoloop --help
```

Or use the bundled installer:

```bash
./install_autoloop.sh
```

## Configuration

Autoloop reads configuration from these directories, in this order:

1. `$XDG_CONFIG_HOME/autoloop/` or `~/.config/autoloop/`
2. the selected workspace root passed to `--workspace`

Within each directory it looks for:

- `autoloop.yaml`
- `autoloop.config`
- legacy read-only fallback: `superloop.yaml`
- legacy read-only fallback: `superloop.config`

If more than one config file exists in the same directory, Autoloop fails fast instead of guessing.

## Runtime State

Fresh runs write state under `.autoloop/`.

For the first Autoloop release, resume and task listing can still read legacy `.superloop/` workspaces when no `.autoloop/` state exists for the requested task or run.

## Skill

The packaged Codex skill lives at `src/autoloop/skill/SKILL.md`.
