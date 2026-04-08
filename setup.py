"""
AuriOS setup script — creates the SQLite database with the required schema.
Run: python setup.py
"""

import os
import sqlite3

DB_DIR = os.path.join(os.path.dirname(__file__), "data")
DB_PATH = os.path.join(DB_DIR, "aurjos.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    role      TEXT,
    content   TEXT,
    metadata  TEXT
);

CREATE TABLE IF NOT EXISTS file_access (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    filepath        TEXT,
    last_accessed   DATETIME,
    access_count    INTEGER DEFAULT 1,
    file_type       TEXT,
    project_context TEXT
);

CREATE TABLE IF NOT EXISTS preferences (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    key        TEXT UNIQUE,
    value      TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS installation_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
    preset_name TEXT,
    software    TEXT,
    status      TEXT,
    duration_s  REAL,
    error_log   TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id           TEXT PRIMARY KEY,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    status       TEXT,
    preset       TEXT,
    progress     INTEGER DEFAULT 0,
    current_step TEXT
);
"""


def main() -> None:
    os.makedirs(DB_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()

        print(f"Database created at: {DB_PATH}")
        print("Tables:", [t[0] for t in tables])
    finally:
        conn.close()


if __name__ == "__main__":
    main()
