from __future__ import annotations

from pathlib import Path
import os

APP_NAME = "ARK Breeder"
APP_SLUG = "ark-breeder"


def user_data_dir() -> Path:
    base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_SLUG


def ensure_app_dirs() -> Path:
    data_dir = user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def database_path() -> Path:
    return user_data_dir() / "arkbreeder.db"
