from __future__ import annotations

import json
from typing import Any


def get_setting(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return row["value"]


def set_setting(conn, key: str, value: str) -> None:
    existing = conn.execute("SELECT 1 FROM settings WHERE key = ?", (key,)).fetchone()
    if existing is None:
        conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))
    else:
        conn.execute("UPDATE settings SET value = ? WHERE key = ?", (value, key))


def get_server_settings(conn) -> dict[str, Any] | None:
    raw = get_setting(conn, "server_settings")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_server_settings(conn, payload: dict[str, Any]) -> None:
    set_setting(conn, "server_settings", json.dumps(payload))
