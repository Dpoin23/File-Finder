import os
import sqlite3
from pathlib import Path

from filefinder.config import database_path
from filefinder.query import search
from tests.conftest import index_tree


def test_filename_beats_directory_and_hides_unrelated(tmp_path: Path, config_dir: Path):
    root = tmp_path / "repo"
    (root / "billing").mkdir(parents=True)
    (root / "auth").mkdir()
    (root / "notes").mkdir()
    (root / "billing" / "auth.py").write_text("print('totals')\n")
    (root / "auth" / "readme.md").write_text("project notes\n")
    (root / "notes" / "unrelated.txt").write_text("gardening\n")
    index_tree(config_dir, root)

    result = search(config_dir, "auth")
    paths = [hit.path for hit in result.hits]

    assert paths[0].endswith("billing/auth.py")
    assert result.hits[0].lane == "path"
    assert any(path.endswith("auth/readme.md") for path in paths)
    assert paths.index(next(path for path in paths if path.endswith("billing/auth.py"))) < paths.index(
        next(path for path in paths if path.endswith("auth/readme.md"))
    )
    assert not any(path.endswith("unrelated.txt") for path in paths)


def test_ignore_rules(tmp_path: Path, config_dir: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("secret.txt\n*.log\n!keep.log\n")
    (root / "secret.txt").write_text("hidden\n")
    (root / "app.log").write_text("noise\n")
    (root / "keep.log").write_text("visible log\n")
    (root / "kept.txt").write_text("visible\n")
    nested = root / "nested"
    nested.mkdir()
    (nested / ".gitignore").write_text("skip.txt\n")
    (nested / "skip.txt").write_text("nope\n")
    (nested / "keep.txt").write_text("yes\n")
    modules = root / "node_modules" / "pkg"
    modules.mkdir(parents=True)
    (modules / "index.js").write_text("module.exports = 1\n")
    git = root / ".git"
    git.mkdir()
    (git / "config").write_text("bare\n")
    (root / "photo.png").write_bytes(b"\x89PNG\r\n")
    (root / "huge.txt").write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    (root / ".env").write_text("TOKEN=secret\n")

    index_tree(config_dir, root)
    con = sqlite3.connect(database_path(config_dir))
    names = {row[0] for row in con.execute("SELECT name FROM files")}
    con.close()

    assert "kept.txt" in names
    assert "keep.txt" in names
    assert "keep.log" in names
    assert database_path(config_dir).stat().st_mode & 0o777 == 0o600
    assert "secret.txt" not in names
    assert "app.log" not in names
    assert "skip.txt" not in names
    assert "index.js" not in names
    assert "config" not in names
    assert "photo.png" not in names
    assert "huge.txt" not in names
    assert ".env" not in names


def test_second_index_skips_unchanged_files(tmp_path: Path, config_dir: Path, embedder):
    root = tmp_path / "repo"
    root.mkdir()
    target = root / "notes.txt"
    target.write_text("alpha beta gamma\n")
    other = root / "other.txt"
    other.write_text("delta epsilon\n")

    class Counting:
        name = embedder.name
        dim = embedder.dim

        def __init__(self):
            self.calls = 0

        def embed(self, texts):
            self.calls += 1
            return embedder.embed(texts)

    counter = Counting()
    first = index_tree(config_dir, root, embedder=counter)
    assert first.updated == 2
    assert first.unchanged == 0
    assert counter.calls == 1

    con = sqlite3.connect(database_path(config_dir))
    before = list(con.execute("SELECT id, file_id, text FROM chunks ORDER BY id"))
    con.close()

    second = index_tree(config_dir, root, embedder=counter)
    assert second.updated == 0
    assert second.unchanged == 2
    assert counter.calls == 1

    con = sqlite3.connect(database_path(config_dir))
    after = list(con.execute("SELECT id, file_id, text FROM chunks ORDER BY id"))
    con.close()
    assert before == after

    target.write_text("alpha beta gamma rewritten\n")
    os.utime(target, (target.stat().st_atime, target.stat().st_mtime + 5))
    third = index_tree(config_dir, root, embedder=counter)
    assert third.updated == 1
    assert third.unchanged == 1
    assert counter.calls == 2

    other.unlink()
    fourth = index_tree(config_dir, root, embedder=counter)
    assert fourth.removed == 1
    result = search(config_dir, "other")
    assert result.hits == []
