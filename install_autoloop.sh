#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
INSTALL_ROOT="${AUTOLOOP_INSTALL_ROOT:-$HOME/.local/share/autoloop}"
BIN_DIR="${AUTOLOOP_BIN_DIR:-$HOME/.local/bin}"
VENV_DIR="$INSTALL_ROOT/venv"
LAUNCHER_PATH="$BIN_DIR/autoloop"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
CODEX_SKILLS_DIR="${CODEX_SKILLS_DIR:-$CODEX_HOME_DIR/skills}"
CODEX_AGENTS_SKILLS_DIR="${CODEX_AGENTS_SKILLS_DIR:-$HOME/.agents/skills}"
SKILL_NAME="autoloop"
SKILL_SOURCE_FILE="$REPO_ROOT/src/autoloop/skill/SKILL.md"
SKILL_DEST_DIR_PRIMARY="$CODEX_SKILLS_DIR/$SKILL_NAME"
SKILL_DEST_DIR_SECONDARY="$CODEX_AGENTS_SKILLS_DIR/$SKILL_NAME"

log() {
  printf '[autoloop-installer] %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'ERROR: required command not found: %s\n' "$1" >&2
    exit 1
  fi
}

require_cmd python3
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
  printf 'ERROR: python3 version must be 3.10 or higher.\n' >&2
  exit 1
fi

for required_path in pyproject.toml src/autoloop/main.py src/autoloop/loop_control.py src/autoloop/templates src/autoloop/skill/SKILL.md; do
  if [[ ! -e "$REPO_ROOT/$required_path" ]]; then
    printf 'ERROR: expected %s in repository root: %s\n' "$required_path" "$REPO_ROOT" >&2
    exit 1
  fi
done

log "Preparing directories"
mkdir -p "$INSTALL_ROOT" "$BIN_DIR" "$CODEX_SKILLS_DIR" "$CODEX_AGENTS_SKILLS_DIR"

log "Installing Autoloop skill to $SKILL_DEST_DIR_PRIMARY"
mkdir -p "$SKILL_DEST_DIR_PRIMARY"
cp "$SKILL_SOURCE_FILE" "$SKILL_DEST_DIR_PRIMARY/SKILL.md"
log "Installing Autoloop skill to $SKILL_DEST_DIR_SECONDARY"
mkdir -p "$SKILL_DEST_DIR_SECONDARY"
cp "$SKILL_SOURCE_FILE" "$SKILL_DEST_DIR_SECONDARY/SKILL.md"

log "Creating virtual environment at $VENV_DIR"
rm -rf "$VENV_DIR"
python3 -m venv "$VENV_DIR"

VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

if [[ "${AUTOLOOP_SKIP_PIP_UPGRADE:-0}" == "1" ]]; then
  log "Skipping pip tooling upgrade because AUTOLOOP_SKIP_PIP_UPGRADE=1"
else
  log "Upgrading pip tooling (best-effort)"
  if ! "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel; then
    log "WARNING: pip tooling upgrade failed; continuing install."
  fi
fi

if [[ "${AUTOLOOP_SKIP_DEP_INSTALL:-0}" == "1" ]]; then
  log "Skipping package installation because AUTOLOOP_SKIP_DEP_INSTALL=1"
else
  log "Installing Autoloop package into the virtual environment"
  "$VENV_PIP" install "$REPO_ROOT"
fi

log "Writing launcher to $LAUNCHER_PATH"
install -d "$BIN_DIR"
cat > "$LAUNCHER_PATH" <<LAUNCHER
#!/usr/bin/env bash
set -euo pipefail
exec "$VENV_DIR/bin/autoloop" "\$@"
LAUNCHER
chmod +x "$LAUNCHER_PATH"

if command -v codex >/dev/null 2>&1; then
  log "Codex CLI detected."
else
  log "Codex CLI not found; install it if you plan to use provider.name=codex: npm i -g @openai/codex"
fi

if command -v claude >/dev/null 2>&1; then
  log "Claude CLI detected."
else
  log "Claude CLI not found; install it and run 'claude auth status' if you plan to use provider.name=claude."
fi

if command -v git >/dev/null 2>&1; then
  log "Git detected."
else
  log "Git not found; Autoloop can run with --no-git."
fi

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  log "Add this directory to PATH to use 'autoloop' globally: $BIN_DIR"
fi

log "Install complete."
log "Run: autoloop --help"
log "Skill installed: $SKILL_DEST_DIR_PRIMARY/SKILL.md"
log "Skill installed: $SKILL_DEST_DIR_SECONDARY/SKILL.md"
log "If your coding agent is already running, restart it to pick up updated skills."
