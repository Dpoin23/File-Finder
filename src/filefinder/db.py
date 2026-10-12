import os
import sqlite3
from pathlib import Path

from filefinder.config import tighten

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roots (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    root_id INTEGER NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
    rel_path TEXT NOT NULL,
    name TEXT NOT NULL,
    extension TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    is_text INTEGER NOT NULL,
    UNIQUE (root_id, rel_path)
);

CREATE VIRTUAL TABLE IF NOT EXISTS path_fts USING fts5(
    name,
    dirs,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    text TEXT NOT NULL,
    UNIQUE (file_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
    text,
    file_id UNINDEXED,
    tokenize = 'porter unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS vectors (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    dim INTEGER NOT NULL,
    vec BLOB NOT NULL
);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        con.executescript(SCHEMA)
    except sqlite3.OperationalError as exc:
        con.close()
        raise RuntimeError(f"SQLite FTS5 is required but unavailable: {exc}") from exc
    tighten(path)
    return con


def get_meta(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return None
    return str(row["value"])


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def delete_file(con: sqlite3.Connection, file_id: int) -> None:
    con.execute(
        "DELETE FROM vectors WHERE chunk_id IN (SELECT id FROM chunks WHERE file_id = ?)",
        (file_id,),
    )
    con.execute("DELETE FROM chunk_fts WHERE file_id = ?", (file_id,))
    con.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    con.execute("DELETE FROM path_fts WHERE rowid = ?", (file_id,))
    con.execute("DELETE FROM files WHERE id = ?", (file_id,))


def delete_root(con: sqlite3.Connection, root_id: int) -> None:
    rows = con.execute("SELECT id FROM files WHERE root_id = ?", (root_id,)).fetchall()
    for row in rows:
        delete_file(con, int(row["id"]))
    con.execute("DELETE FROM roots WHERE id = ?", (root_id,))
