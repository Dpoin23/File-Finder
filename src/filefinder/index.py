import sqlite3
from pathlib import Path

from filefinder.config import database_path, load_roots, tighten
from filefinder.db import connect, delete_file, delete_root, get_meta, set_meta
from filefinder.embed import pack_vector
from filefinder.models import ConfigError, IndexStats
from filefinder.text import chunk_text, is_textlike, read_text, tokens
from filefinder.walk import iter_files

_EMBED_BATCH = 32


def index_roots(config_dir: Path, embedder=None) -> IndexStats:
    roots = load_roots(config_dir)
    missing = [root for root in roots if not root.is_dir()]
    if missing:
        listed = ", ".join(str(root) for root in missing)
        raise ConfigError(f"Root is not a directory: {listed}")

    db_path = database_path(config_dir)
    con = connect(db_path)
    stats = IndexStats()
    try:
        root_ids = _sync_roots(con, roots)
        if embedder is not None:
            previous = get_meta(con, "embed_model")
            if previous not in (None, embedder.name):
                con.execute("DELETE FROM vectors")

        pending: list[tuple[int, str]] = []
        seen: set[tuple[int, str]] = set()
        for root in roots:
            root_id = root_ids[str(root.resolve())]
            for path, st in iter_files(root):
                rel = path.relative_to(root.resolve()).as_posix()
                seen.add((root_id, rel))
                stats.files += 1
                pending.extend(_sync_file(con, root_id, rel, path, st, embedder, stats))

        stats.removed = _remove_unseen(con, seen)
        if embedder is not None and pending:
            _embed_pending(con, embedder, pending)
        if embedder is not None:
            set_meta(con, "embed_model", embedder.name)
        total = con.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
        stats.chunks = int(total["n"]) if total is not None else 0
        con.commit()
    finally:
        con.close()
        tighten(db_path)
    return stats


def _sync_roots(con: sqlite3.Connection, roots: list[Path]) -> dict[str, int]:
    desired = [str(root.resolve()) for root in roots]
    desired_set = set(desired)
    for row in con.execute("SELECT id, path FROM roots"):
        if row["path"] not in desired_set:
            delete_root(con, int(row["id"]))
    ids: dict[str, int] = {}
    for path in desired:
        row = con.execute("SELECT id FROM roots WHERE path = ?", (path,)).fetchone()
        if row is None:
            cur = con.execute("INSERT INTO roots(path) VALUES (?)", (path,))
            ids[path] = int(cur.lastrowid)
        else:
            ids[path] = int(row["id"])
    return ids


def _sync_file(con, root_id, rel, path: Path, st, embedder, stats: IndexStats) -> list[tuple[int, str]]:
    row = con.execute(
        "SELECT id, size, mtime_ns, is_text FROM files WHERE root_id = ? AND rel_path = ?",
        (root_id, rel),
    ).fetchone()
    if row is not None and int(row["size"]) == st.st_size and int(row["mtime_ns"]) == st.st_mtime_ns:
        file_id = int(row["id"])
        if embedder is not None and int(row["is_text"]) and _missing_vectors(con, file_id):
            stats.updated += 1
            return _pending_for_file(con, file_id)
        stats.unchanged += 1
        return []

    text = None
    textlike = is_textlike(path.name, path.suffix)
    if textlike:
        text = read_text(path)
        textlike = text is not None
    if row is None:
        cur = con.execute(
            """
            INSERT INTO files(root_id, rel_path, name, extension, size, mtime_ns, is_text)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (root_id, rel, path.name, path.suffix.lower(), st.st_size, st.st_mtime_ns, int(textlike)),
        )
        file_id = int(cur.lastrowid)
    else:
        file_id = int(row["id"])
        con.execute(
            """
            UPDATE files
            SET name = ?, extension = ?, size = ?, mtime_ns = ?, is_text = ?
            WHERE id = ?
            """,
            (path.name, path.suffix.lower(), st.st_size, st.st_mtime_ns, int(textlike), file_id),
        )
    _replace_path(con, file_id, rel, path.name)
    pending = _replace_chunks(con, file_id, text if textlike and text is not None else "")
    stats.updated += 1
    if embedder is None:
        return []
    return pending


def _replace_path(con: sqlite3.Connection, file_id: int, rel: str, name: str) -> None:
    parent = Path(rel).parent.as_posix()
    dirs = "" if parent == "." else parent
    # Repeat camel-case pieces so a filename token match does not depend on
    # the FTS tokenizer splitting ValidateRefund into one word.
    name_tokens = " ".join(tokens(name))
    con.execute("DELETE FROM path_fts WHERE rowid = ?", (file_id,))
    con.execute(
        "INSERT INTO path_fts(rowid, name, dirs) VALUES (?, ?, ?)",
        (file_id, f"{name} {name_tokens}".strip(), dirs),
    )


def _replace_chunks(con: sqlite3.Connection, file_id: int, text: str) -> list[tuple[int, str]]:
    con.execute(
        "DELETE FROM vectors WHERE chunk_id IN (SELECT id FROM chunks WHERE file_id = ?)",
        (file_id,),
    )
    con.execute("DELETE FROM chunk_fts WHERE file_id = ?", (file_id,))
    con.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    pending: list[tuple[int, str]] = []
    for chunk in chunk_text(text):
        cur = con.execute(
            """
            INSERT INTO chunks(file_id, ordinal, start_char, end_char, text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (file_id, chunk.ordinal, chunk.start, chunk.end, chunk.text),
        )
        chunk_id = int(cur.lastrowid)
        con.execute(
            "INSERT INTO chunk_fts(text, file_id) VALUES (?, ?)",
            (chunk.text, file_id),
        )
        pending.append((chunk_id, chunk.text))
    return pending


def _missing_vectors(con: sqlite3.Connection, file_id: int) -> bool:
    chunks = con.execute("SELECT COUNT(*) AS n FROM chunks WHERE file_id = ?", (file_id,)).fetchone()
    if chunks is None or int(chunks["n"]) == 0:
        return False
    vectors = con.execute(
        """
        SELECT COUNT(*) AS n
        FROM vectors v
        JOIN chunks c ON c.id = v.chunk_id
        WHERE c.file_id = ?
        """,
        (file_id,),
    ).fetchone()
    return vectors is None or int(vectors["n"]) < int(chunks["n"])


def _pending_for_file(con: sqlite3.Connection, file_id: int) -> list[tuple[int, str]]:
    rows = con.execute(
        """
        SELECT c.id, c.text
        FROM chunks c
        LEFT JOIN vectors v ON v.chunk_id = c.id
        WHERE c.file_id = ? AND v.chunk_id IS NULL
        ORDER BY c.ordinal
        """,
        (file_id,),
    )
    return [(int(row["id"]), str(row["text"])) for row in rows]


def _embed_pending(con: sqlite3.Connection, embedder, pending: list[tuple[int, str]]) -> None:
    for start in range(0, len(pending), _EMBED_BATCH):
        batch = pending[start : start + _EMBED_BATCH]
        matrix = embedder.embed([text for _, text in batch])
        for (chunk_id, _), vec in zip(batch, matrix, strict=True):
            con.execute(
                "INSERT OR REPLACE INTO vectors(chunk_id, dim, vec) VALUES (?, ?, ?)",
                (chunk_id, int(vec.shape[0]), pack_vector(vec)),
            )


def _remove_unseen(con: sqlite3.Connection, seen: set[tuple[int, str]]) -> int:
    removed = 0
    for row in con.execute("SELECT id, root_id, rel_path FROM files"):
        key = (int(row["root_id"]), str(row["rel_path"]))
        if key not in seen:
            delete_file(con, int(row["id"]))
            removed += 1
    return removed
