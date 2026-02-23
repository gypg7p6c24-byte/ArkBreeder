from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3

from arkbreedingtool.config import database_path, ensure_app_dirs

SCHEMA = '''
CREATE TABLE IF NOT EXISTS creatures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT,
    blueprint TEXT,
    name TEXT NOT NULL,
    species TEXT NOT NULL,
    sex TEXT NOT NULL,
    level INTEGER NOT NULL,
    stats_json TEXT NOT NULL,
    imprinting_quality REAL,
    mutations_maternal INTEGER NOT NULL DEFAULT 0,
    mutations_paternal INTEGER NOT NULL DEFAULT 0,
    mother_id INTEGER,
    father_id INTEGER,
    mother_external_id TEXT,
    father_external_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_creatures_species ON creatures(species);
CREATE UNIQUE INDEX IF NOT EXISTS idx_creatures_external_id
    ON creatures(external_id) WHERE external_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
'''


def get_connection(path: Path | None = None) -> sqlite3.Connection:
    ensure_app_dirs()
    db_path = path or database_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _ensure_column(conn, "creatures", "external_id", "TEXT")
    _ensure_column(conn, "creatures", "blueprint", "TEXT")
    _ensure_column(conn, "creatures", "updated_at", "TEXT")
    _ensure_column(conn, "creatures", "imprinting_quality", "REAL")
    _ensure_column(conn, "creatures", "mother_external_id", "TEXT")
    _ensure_column(conn, "creatures", "father_external_id", "TEXT")
    conn.execute(
        "UPDATE creatures SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)"
    )
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    except sqlite3.OperationalError:
        pass


@contextmanager
def db_session(path: Path | None = None):
    conn = get_connection(path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()
