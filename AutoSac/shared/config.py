from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
import os

from shared.contracts import (
    DEFAULT_MANUALS_MOUNT_DIR,
    DEFAULT_REPO_MOUNT_DIR,
    DEFAULT_TRIAGE_WORKSPACE_DIR,
    DEFAULT_UPLOADS_DIR,
)


class SettingsError(RuntimeError):
    """Raised when required environment configuration is missing or invalid."""


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SettingsError(f"Missing required environment variable: {name}")
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return Path(raw).expanduser()


def get_database_url() -> str:
    return _required_env("DATABASE_URL")


@dataclass(frozen=True)
class Settings:
    app_base_url: str
    app_secret_key: str
    database_url: str
    uploads_dir: Path
    triage_workspace_dir: Path
    repo_mount_dir: Path
    manuals_mount_dir: Path
    codex_bin: str
    codex_api_key: str
    codex_model: str
    codex_timeout_seconds: int
    worker_poll_seconds: int
    auto_support_reply_min_confidence: float
    auto_confirm_intent_min_confidence: float
    max_images_per_message: int
    max_image_bytes: int
    session_default_hours: int
    session_remember_days: int

    @property
    def secure_cookies(self) -> bool:
        return urlparse(self.app_base_url).scheme.lower() == "https"

    @property
    def runs_dir(self) -> Path:
        return self.triage_workspace_dir / "runs"

    @property
    def workspace_skill_path(self) -> Path:
        return self.triage_workspace_dir / ".agents/skills/stage1-triage/SKILL.md"

    @property
    def workspace_agents_path(self) -> Path:
        return self.triage_workspace_dir / "AGENTS.md"

    def validate_contracts(self) -> None:
        if self.max_images_per_message <= 0:
            raise SettingsError("MAX_IMAGES_PER_MESSAGE must be positive")
        if self.max_image_bytes <= 0:
            raise SettingsError("MAX_IMAGE_BYTES must be positive")
        if self.session_default_hours <= 0:
            raise SettingsError("SESSION_DEFAULT_HOURS must be positive")
        if self.session_remember_days <= 0:
            raise SettingsError("SESSION_REMEMBER_DAYS must be positive")
        if self.worker_poll_seconds <= 0:
            raise SettingsError("WORKER_POLL_SECONDS must be positive")
        if self.codex_timeout_seconds <= 0:
            raise SettingsError("CODEX_TIMEOUT_SECONDS must be positive")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings(
        app_base_url=_required_env("APP_BASE_URL"),
        app_secret_key=_required_env("APP_SECRET_KEY"),
        database_url=get_database_url(),
        uploads_dir=_env_path("UPLOADS_DIR", DEFAULT_UPLOADS_DIR),
        triage_workspace_dir=_env_path("TRIAGE_WORKSPACE_DIR", DEFAULT_TRIAGE_WORKSPACE_DIR),
        repo_mount_dir=_env_path("REPO_MOUNT_DIR", DEFAULT_REPO_MOUNT_DIR),
        manuals_mount_dir=_env_path("MANUALS_MOUNT_DIR", DEFAULT_MANUALS_MOUNT_DIR),
        codex_bin=_required_env("CODEX_BIN"),
        codex_api_key=_required_env("CODEX_API_KEY"),
        codex_model=os.environ.get("CODEX_MODEL", "").strip(),
        codex_timeout_seconds=_env_int("CODEX_TIMEOUT_SECONDS", 75),
        worker_poll_seconds=_env_int("WORKER_POLL_SECONDS", 10),
        auto_support_reply_min_confidence=_env_float("AUTO_SUPPORT_REPLY_MIN_CONFIDENCE", 0.85),
        auto_confirm_intent_min_confidence=_env_float("AUTO_CONFIRM_INTENT_MIN_CONFIDENCE", 0.90),
        max_images_per_message=_env_int("MAX_IMAGES_PER_MESSAGE", 3),
        max_image_bytes=_env_int("MAX_IMAGE_BYTES", 5 * 1024 * 1024),
        session_default_hours=_env_int("SESSION_DEFAULT_HOURS", 12),
        session_remember_days=_env_int("SESSION_REMEMBER_DAYS", 30),
    )
    settings.validate_contracts()
    return settings
