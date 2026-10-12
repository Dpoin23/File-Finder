from pathlib import Path

from filefinder.cli import main


def test_cli_init_index_and_query(tmp_path: Path, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "billing" / "auth.py").parent.mkdir(parents=True)
    (root / "billing" / "auth.py").write_text("print('ok')\n")
    config = tmp_path / "config"

    assert main(["--config-dir", str(config), "init", str(root)]) == 0
    assert main(["--config-dir", str(config), "index", "--skip-embed"]) == 0
    assert main(["--config-dir", str(config), "query", "auth"]) == 0

    output = capsys.readouterr().out
    assert "billing/auth.py" in output
    assert "[path]" in output


def test_cli_query_before_init(tmp_path: Path, capsys):
    code = main(["--config-dir", str(tmp_path / "missing"), "query", "auth"])
    assert code == 2
    assert "ff init" in capsys.readouterr().err


def test_cli_explain_is_local_by_default(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("FF_EXPLAIN_BASE_URL", raising=False)
    monkeypatch.delenv("FF_EXPLAIN_MODEL", raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "notes.txt").write_text("plain text\n")
    config = tmp_path / "config"

    assert main(["--config-dir", str(config), "init", str(root)]) == 0
    assert main(["--config-dir", str(config), "index", "--skip-embed"]) == 0
    assert main(["--config-dir", str(config), "query", "--explain", "notes"]) == 0
    output = capsys.readouterr().out
    assert "explain:" in output
    assert "notes.txt" in output
