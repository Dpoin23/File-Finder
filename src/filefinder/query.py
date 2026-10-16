import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np

from filefinder.config import config_path, database_path, load_roots
from filefinder.db import connect, get_meta
from filefinder.embed import unpack_vector
from filefinder.explain import explain
from filefinder.models import Accum, ConfigError, Hit, QueryResult
from filefinder.text import classify, content_tokens, fts_query, overlap, strip_quotes, tokens
from filefinder.walk import SKIP_DIRS

# Priority weights from the design rank order. A signal at 1.0 beats every
# weaker signal at 1.0. Exact filename still outranks a descriptive hit.
_WEIGHTS = {
    "name": {
        "exact_name": 16.0,
        "name_overlap": 8.0,
        "dir_overlap": 4.0,
        "content": 2.0,
        "vector": 0.5,
    },
    "description": {
        "exact_name": 16.0,
        "vector": 8.0,
        "content": 5.0,
        "dir_overlap": 1.5,
        "name_overlap": 0.75,
    },
    "exact": {
        "ripgrep": 16.0,
        "exact_name": 10.0,
        "content": 6.0,
        "name_overlap": 3.0,
        "dir_overlap": 1.0,
    },
}

_LANE = {
    "exact_name": "path",
    "name_overlap": "path",
    "dir_overlap": "path",
    "content": "content",
    "vector": "vector",
    "ripgrep": "ripgrep",
}

# Default local model (bge-small) scores unrelated chunks around 0.4-0.5
# and a real paraphrase higher. The floor drops the unrelated tail.
_VECTOR_MIN = 0.55


def search(
    config_dir: Path,
    query: str,
    *,
    embedder=None,
    limit: int = 20,
    explain_result: bool = False,
) -> QueryResult:
    text = query.strip()
    if not text:
        raise ConfigError("Query is empty")
    if not config_path(config_dir).is_file():
        raise ConfigError("No roots yet. Run: ff init PATH [PATH...]")
    if not database_path(config_dir).is_file():
        raise ConfigError("No index yet. Run: ff index")
    roots = load_roots(config_dir)
    kind = classify(text)
    con = connect(database_path(config_dir))
    try:
        accums: dict[str, Accum] = {}
        _path_lane(con, text, accums)
        if kind != "exact":
            _content_lane(con, text, accums)
            if embedder is not None:
                _vector_lane(con, text, embedder, accums)
        else:
            _content_lane(con, strip_quotes(text), accums)
            _ripgrep_lane(roots, strip_quotes(text), accums)
        hits = rank_accums(kind, list(accums.values()))[:limit]
    finally:
        con.close()
    sentence = None
    if explain_result:
        hits, sentence = explain(text, hits)
    return QueryResult(hits=hits, sentence=sentence, kind=kind)


def rank_accums(kind: str, accums: list[Accum]) -> list[Hit]:
    weights = _WEIGHTS[kind]
    hits: list[Hit] = []
    for accum in accums:
        contributions = {
            "exact_name": weights.get("exact_name", 0.0) * accum.exact_name,
            "name_overlap": weights.get("name_overlap", 0.0) * accum.name_overlap,
            "dir_overlap": weights.get("dir_overlap", 0.0) * accum.dir_overlap,
            "content": weights.get("content", 0.0) * accum.content,
            "vector": weights.get("vector", 0.0) * accum.vector,
            "ripgrep": weights.get("ripgrep", 0.0) * accum.ripgrep,
        }
        score = sum(contributions.values())
        if score <= 0:
            continue
        lane_name = max(contributions, key=contributions.get)
        hits.append(
            Hit(
                path=accum.path,
                score=score,
                lane=_LANE[lane_name],
                chunk=_chunk_for(accum, lane_name),
                line=accum.line if lane_name == "ripgrep" else None,
            )
        )
    hits.sort(key=lambda hit: (-hit.score, hit.path))
    return hits


def _chunk_for(accum: Accum, lane_name: str) -> str:
    if lane_name == "ripgrep":
        return accum.rg_chunk or accum.path_chunk
    if lane_name == "vector":
        return accum.vector_chunk or accum.content_chunk or accum.path_chunk
    if lane_name == "content":
        return accum.content_chunk or accum.vector_chunk or accum.path_chunk
    return accum.path_chunk or accum.content_chunk


def _path_lane(con, query: str, accums: dict[str, Accum]) -> None:
    query_tokens = content_tokens(query) or tokens(query)
    bare = strip_quotes(query.strip().lower())
    ids: set[int] = set()
    match = fts_query(query_tokens)
    if match:
        try:
            for row in con.execute(
                "SELECT rowid FROM path_fts WHERE path_fts MATCH ? ORDER BY bm25(path_fts) LIMIT 200",
                (match,),
            ):
                ids.add(int(row["rowid"]))
        except sqlite3.OperationalError as exc:
            # Continue with exact/stem fallback matching if FTS query is unavailable.
            print(f"Warning: path FTS query failed: {exc}", file=sys.stderr)
    for row in con.execute(
        """
        SELECT id FROM files
        WHERE lower(name) = ?
           OR (
                extension != ''
                AND lower(substr(name, 1, length(name) - length(extension))) = ?
           )
        """,
        (bare, bare),
    ):
        ids.add(int(row["id"]))
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    id_list = list(ids)
    files = con.execute(
        f"""
        SELECT f.id, f.name, f.extension, f.rel_path, r.path AS root
        FROM files f
        JOIN roots r ON r.id = f.root_id
        WHERE f.id IN ({placeholders})
        """,
        id_list,
    ).fetchall()
    dirs_by_id = {
        int(row["rowid"]): str(row["dirs"] or "")
        for row in con.execute(
            f"SELECT rowid, dirs FROM path_fts WHERE rowid IN ({placeholders})",
            id_list,
        )
    }
    for row in files:
        file_id = int(row["id"])
        absolute = str(Path(row["root"]) / row["rel_path"])
        name = str(row["name"])
        extension = str(row["extension"])
        stem = name[: -len(extension)] if extension else name
        exact = 1.0 if bare in {name.lower(), stem.lower()} else 0.0
        name_score = overlap(query_tokens, tokens(name))
        dir_score = overlap(query_tokens, tokens(dirs_by_id.get(file_id, "")))
        if exact == 0 and name_score == 0 and dir_score == 0:
            continue
        accum = _accum(accums, absolute, str(row["rel_path"]))
        accum.exact_name = max(accum.exact_name, exact)
        accum.name_overlap = max(accum.name_overlap, name_score)
        accum.dir_overlap = max(accum.dir_overlap, dir_score)


def _content_lane(con, query: str, accums: dict[str, Accum]) -> None:
    match = fts_query(content_tokens(query))
    if not match:
        return
    try:
        rows = con.execute(
            """
            SELECT file_id, text, bm25(chunk_fts) AS score
            FROM chunk_fts
            WHERE chunk_fts MATCH ?
            ORDER BY score
            LIMIT 200
            """,
            (match,),
        ).fetchall()
    except sqlite3.OperationalError:
        return
    paths = _file_paths(con)
    best: dict[str, tuple[float, str]] = {}
    for row in rows:
        path = paths.get(int(row["file_id"]))
        if path is None:
            continue
        raw = max(0.0, -float(row["score"]))
        strength = raw / (raw + 2.0)
        current = best.get(path)
        if current is None or strength > current[0]:
            best[path] = (strength, str(row["text"]))
    for path, (strength, text) in best.items():
        accum = _accum(accums, path, Path(path).name)
        if strength > accum.content or not accum.content_chunk:
            accum.content = strength
            accum.content_chunk = text


def _vector_lane(con, query: str, embedder, accums: dict[str, Accum]) -> None:
    rows = con.execute(
        """
        SELECT v.dim, v.vec, c.text, c.file_id
        FROM vectors v
        JOIN chunks c ON c.id = v.chunk_id
        """
    ).fetchall()
    if not rows:
        return
    stored_model = get_meta(con, "embed_model")
    if stored_model and getattr(embedder, "name", None) not in (None, stored_model):
        return
    if hasattr(embedder, "embed_query"):
        query_vec = np.asarray(embedder.embed_query(query), dtype=np.float32)
    else:
        query_vec = embedder.embed([query])[0]
    if int(rows[0]["dim"]) != int(query_vec.shape[0]):
        return
    matrix = np.vstack([unpack_vector(row["vec"]) for row in rows])
    scores = matrix @ query_vec
    if len(scores) > 50:
        chosen = np.argpartition(-scores, 50)[:50]
    else:
        chosen = np.arange(len(scores))
    chosen = chosen[np.argsort(-scores[chosen])]
    paths = _file_paths(con)
    for index in chosen:
        score = float(scores[int(index)])
        if score < _VECTOR_MIN:
            continue
        row = rows[int(index)]
        path = paths.get(int(row["file_id"]))
        if path is None:
            continue
        accum = _accum(accums, path, Path(path).name)
        if score > accum.vector:
            accum.vector = score
            accum.vector_chunk = str(row["text"])


def _ripgrep_lane(roots: list[Path], pattern: str, accums: dict[str, Accum]) -> None:
    if not pattern.strip():
        return
    binary = shutil.which("rg")
    if binary is None:
        return
    command = [
        binary,
        "--json",
        "--fixed-strings",
        "--max-count",
        "3",
        "--max-filesize",
        "5M",
        "--glob",
        "!.git/**",
    ]
    for name in sorted(SKIP_DIRS):
        command.extend(["--glob", f"!{name}/**"])
    command.append(pattern)
    command.extend(str(root) for root in roots)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    if completed.returncode not in (0, 1):
        return
    seen: set[str] = set()
    for line in completed.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data") or {}
        path_text = ((data.get("path") or {}).get("text")) or ""
        if not path_text or path_text in seen:
            continue
        seen.add(path_text)
        snippet = ((data.get("lines") or {}).get("text")) or ""
        line_number = data.get("line_number")
        absolute = str(Path(path_text).resolve())
        accum = _accum(accums, absolute, Path(absolute).name)
        accum.ripgrep = 1.0
        accum.rg_chunk = snippet.strip("\n")
        if isinstance(line_number, int):
            accum.line = line_number
        if len(seen) >= 40:
            break


def _file_paths(con) -> dict[int, str]:
    rows = con.execute(
        """
        SELECT f.id, f.rel_path, r.path AS root
        FROM files f JOIN roots r ON r.id = f.root_id
        """
    )
    return {int(row["id"]): str(Path(row["root"]) / row["rel_path"]) for row in rows}


def _accum(accums: dict[str, Accum], path: str, rel_chunk: str) -> Accum:
    accum = accums.get(path)
    if accum is None:
        accum = Accum(path=path, path_chunk=rel_chunk)
        accums[path] = accum
    elif not accum.path_chunk:
        accum.path_chunk = rel_chunk
    return accum


def format_hit(hit: Hit) -> str:
    loc = hit.path if hit.line is None else f"{hit.path}:{hit.line}"
    lines = [f"{loc}  [{hit.lane}]"]
    snippet = " ".join(hit.chunk.split())
    if len(snippet) > 240:
        snippet = snippet[:239].rstrip() + "…"
    if snippet:
        lines.append(f"  {snippet}")
    return "\n".join(lines)


def format_results(result: QueryResult) -> str:
    parts = [format_hit(hit) for hit in result.hits]
    body = "\n\n".join(parts)
    if result.sentence:
        if body:
            body += "\n\n"
        body += f"explain: {result.sentence}"
    if body and not body.endswith("\n"):
        body += "\n"
    return body
