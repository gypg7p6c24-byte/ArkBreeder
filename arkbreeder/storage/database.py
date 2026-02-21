from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3

from arkbreeder.config import database_path, ensure_app_dirs

SCHEMA = '''
CREATE TABLE IF NOT EXISTS creatures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    species TEXT NOT NULL,
    sex TEXT NOT NULL,
    level INTEGER NOT NULL,
    stats_json TEXT NOT NULL,
    mutations_maternal INTEGER NOT NULL DEFAULT 0,
    mutations_paternal INTEGER NOT NULL DEFAULT 0,
    mother_id INTEGER,
    father_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_creatures_species ON creatures(species);
'''


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    ensure_app_dirs()
    db_path = path or database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


@contextmanager
def db_session(path: Path | None = None):
    conn = get_connection(path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()
