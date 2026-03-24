#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
INSTALL_ROOT="${SUPERLOOP_INSTALL_ROOT:-$HOME/.local/share/superloop}"
BIN_DIR="${SUPERLOOP_BIN_DIR:-$HOME/.local/bin}"
APP_DIR="$INSTALL_ROOT/app"
VENV_DIR="$INSTALL_ROOT/venv"
LAUNCHER_PATH="$BIN_DIR/superloop"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
CODEX_SKILLS_DIR="${CODEX_SKILLS_DIR:-$CODEX_HOME_DIR/skills}"
CODEX_AGENTS_SKILLS_DIR="${CODEX_AGENTS_SKILLS_DIR:-$HOME/.agents/skills}"
SKILL_NAME="superloop"
SKILL_SOURCE_DIR="$REPO_ROOT/skills/$SKILL_NAME"
SKILL_DEST_DIR_PRIMARY="$CODEX_SKILLS_DIR/$SKILL_NAME"
SKILL_DEST_DIR_SECONDARY="$CODEX_AGENTS_SKILLS_DIR/$SKILL_NAME"

log() {
  printf '[superloop-installer] %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'ERROR: required command not found: %s\n' "$1" >&2
    exit 1
  fi
}

require_cmd python3
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 7) else 1)' >/dev/null 2>&1; then
  printf 'ERROR: python3 version must be 3.7 or higher.\n' >&2
  exit 1
fi

for required_path in superloop.py loop_control.py templates "skills/$SKILL_NAME"; do
  if [[ ! -e "$REPO_ROOT/$required_path" ]]; then
    printf 'ERROR: expected %s in repository root: %s\n' "$required_path" "$REPO_ROOT" >&2
    exit 1
  fi
done

log "Preparing directories"
mkdir -p "$INSTALL_ROOT" "$APP_DIR" "$BIN_DIR" "$CODEX_SKILLS_DIR" "$CODEX_AGENTS_SKILLS_DIR"

log "Copying Superloop files to $APP_DIR"
cp "$REPO_ROOT/superloop.py" "$APP_DIR/superloop.py"
cp "$REPO_ROOT/loop_control.py" "$APP_DIR/loop_control.py"
rm -rf "$APP_DIR/templates"
cp -R "$REPO_ROOT/templates" "$APP_DIR/templates"
rm -f "$APP_DIR/requirements.txt"
if [[ -f "$REPO_ROOT/requirements.txt" ]]; then
  cp "$REPO_ROOT/requirements.txt" "$APP_DIR/requirements.txt"
fi

install_skill_dir() {
  local destination="$1"
  rm -rf "$destination"
  mkdir -p "$destination"
  cp -R "$SKILL_SOURCE_DIR"/. "$destination"/
}

log "Installing Codex skill to $SKILL_DEST_DIR_PRIMARY"
install_skill_dir "$SKILL_DEST_DIR_PRIMARY"
log "Installing Codex skill to $SKILL_DEST_DIR_SECONDARY"
install_skill_dir "$SKILL_DEST_DIR_SECONDARY"

if [[ ! -d "$VENV_DIR" ]]; then
  log "Creating virtual environment at $VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"

if [[ "${SUPERLOOP_SKIP_PIP_UPGRADE:-0}" == "1" ]]; then
  log "Skipping pip tooling upgrade because SUPERLOOP_SKIP_PIP_UPGRADE=1"
else
  log "Upgrading pip tooling (best-effort)"
  if ! "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel; then
    log "WARNING: pip tooling upgrade failed; continuing install."
  fi
fi

if [[ -f "$APP_DIR/requirements.txt" ]]; then
  log "Installing Python dependencies from requirements.txt"
  "$VENV_PYTHON" -m pip install -r "$APP_DIR/requirements.txt"
else
  log "No requirements.txt found, installing minimum dependency set"
  "$VENV_PYTHON" -m pip install pyyaml
fi

log "Writing launcher to $LAUNCHER_PATH"
cat > "$LAUNCHER_PATH" <<LAUNCHER
#!/usr/bin/env bash
set -euo pipefail
VENV_PYTHON="$VENV_PYTHON"
SUPERLOOP_ENTRY="$APP_DIR/superloop.py"
exec "\$VENV_PYTHON" "\$SUPERLOOP_ENTRY" "\$@"
LAUNCHER
chmod +x "$LAUNCHER_PATH"

if command -v codex >/dev/null 2>&1; then
  log "Codex CLI detected."
else
  log "Codex CLI not found; install with: npm i -g @openai/codex"
fi

if command -v git >/dev/null 2>&1; then
  log "Git detected."
else
  log "Git not found; Superloop can run with --no-git."
fi

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  log "Add this directory to PATH to use 'superloop' globally: $BIN_DIR"
fi

log "Install complete."
log "Run: superloop --help"
log "Skill installed: $SKILL_DEST_DIR_PRIMARY/SKILL.md"
log "Skill installed: $SKILL_DEST_DIR_SECONDARY/SKILL.md"
log "If Codex is already running, restart it to pick up updated skills."
