from __future__ import annotations

from pathlib import Path
import os

APP_NAME = "ARK Breeder"
APP_SLUG = "ark-breeder"
DEFAULT_EXPORT_DIR = (
    Path.home()
    / ".steam"
    / "steam"
    / "steamapps"
    / "common"
    / "ARK"
    / "ShooterGame"
    / "Saved"
    / "DinoExports"
)


def user_data_dir() -> Path:
    base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_SLUG


def ensure_app_dirs() -> Path:
    data_dir = user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def database_path() -> Path:
    return user_data_dir() / "arkbreeder.db"


def export_dir() -> Path:
    override = os.getenv("ARKBREEDER_EXPORT_DIR")
    if override:
        return Path(override).expanduser()
    return DEFAULT_EXPORT_DIR


def bundled_values_path() -> Path:
    return Path(__file__).resolve().parent / "resources" / "values.default.json"
