import time
from pathlib import Path

import pytest

from filefinder.cli import main
from filefinder.ui_view import build_tree, catalog_summary, execute_search, lane_states, open_argv
from tests.conftest import index_tree


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "billing").mkdir(parents=True)
    (root / "billing" / "auth.py").write_text("def authorize():\n    return True\n", encoding="utf-8")
    (root / "readme.md").write_text("notes\n", encoding="utf-8")
    return root


def test_name_search_builds_path_and_tree(tmp_path: Path, config_dir: Path):
    root = _repo(tmp_path)
    index_tree(config_dir, root)

    view = execute_search(config_dir, "auth", limit=20, explain=False)

    assert view.kind == "name"
    assert view.error is None
    assert view.hits
    hit = view.hits[0]
    assert hit.name == "auth.py"
    assert hit.relative == "billing/auth.py"
    assert hit.crumbs[0] == "repo"
    assert hit.crumbs[-1] == "auth.py"
    assert [lane.key for lane in view.lanes if lane.state == "on"] == ["path", "content"]
    assert view.tree[0].name == "repo"
    assert view.tree[0].children[0].name == "billing"
    assert view.tree[0].children[0].children[0].path.endswith("billing/auth.py")


def test_exact_query_lights_ripgrep_lane(tmp_path: Path, config_dir: Path):
    index_tree(config_dir, _repo(tmp_path))
    view = execute_search(config_dir, "ValidateRefund", limit=5, explain=False)
    assert view.kind == "exact"
    assert {lane.key for lane in view.lanes if lane.state == "on"} == {"path", "content", "ripgrep"}


def test_description_without_embedder_marks_vectors_missing(tmp_path: Path, config_dir: Path):
    index_tree(config_dir, _repo(tmp_path))
    view = execute_search(
        config_dir,
        "how we authorize a user",
        limit=5,
        explain=False,
        embedder=None,
        embedder_error="model missing",
    )
    assert view.kind == "description"
    vector = next(lane for lane in view.lanes if lane.key == "vector")
    assert vector.state == "missing"
    assert view.notice == "model missing"


def test_empty_query_is_blank(config_dir: Path):
    view = execute_search(config_dir, "   ", limit=5, explain=False)
    assert view.hits == []
    assert view.error is None
    assert all(lane.state == "off" for lane in view.lanes)


def test_missing_index_is_an_error(config_dir: Path, tmp_path: Path):
    from filefinder.config import save_roots

    save_roots(config_dir, [tmp_path])
    view = execute_search(config_dir, "auth", limit=5, explain=False)
    assert view.error
    assert "ff index" in view.error


def test_catalog_summary_counts_files(tmp_path: Path, config_dir: Path):
    index_tree(config_dir, _repo(tmp_path))
    summary = catalog_summary(config_dir)
    assert "2 files" in summary
    assert "repo" in summary


def test_tree_puts_directories_before_files():
    from filefinder.ui_view import HitView

    hits = [
        HitView("r/a.txt", "a.txt", "r", "a.txt", ("r", "a.txt"), "path", None, "", ""),
        HitView("r/b/c.txt", "c.txt", "r", "b/c.txt", ("r", "b", "c.txt"), "path", None, "", ""),
    ]
    children = build_tree(hits)[0].children
    assert [child.name for child in children] == ["b", "a.txt"]
    assert children[0].path is None
    assert children[1].path == "r/a.txt"


def test_duplicate_root_names_use_full_path():
    from filefinder.ui_view import HitView

    hits = [
        HitView("/work/app/a.txt", "a.txt", "/work/app", "a.txt", ("app", "a.txt"), "path", None, "", ""),
        HitView("/other/app/b.txt", "b.txt", "/other/app", "b.txt", ("app", "b.txt"), "path", None, "", ""),
    ]
    names = [node.name for node in build_tree(hits)]
    assert "/work/app" in names
    assert "/other/app" in names


def test_lane_states_for_unknown_kind_are_off():
    assert all(lane.state == "off" for lane in lane_states(""))


def test_open_argv_uses_editor_and_line(monkeypatch):
    monkeypatch.setenv("FF_EDITOR", "nvim")
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    assert open_argv("/tmp/auth.py", 12) == ["nvim", "+12", "/tmp/auth.py"]


def test_open_argv_vscode_goto(monkeypatch):
    monkeypatch.setenv("FF_EDITOR", "code")
    assert open_argv("/tmp/auth.py", 4) == ["code", "--goto", "/tmp/auth.py:4"]


def test_open_argv_default_opener(monkeypatch):
    monkeypatch.delenv("FF_EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr("filefinder.ui_view.sys.platform", "linux")
    assert open_argv("/tmp/auth.py", None) == ["xdg-open", "/tmp/auth.py"]
    monkeypatch.setattr("filefinder.ui_view.sys.platform", "darwin")
    assert open_argv("/tmp/auth.py", None) == ["open", "/tmp/auth.py"]
    monkeypatch.setattr("filefinder.ui_view.sys.platform", "win32")
    assert open_argv("/tmp/auth.py", None) is None


def test_original_commands_remain(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    for command in ("init", "index", "query", "ui"):
        assert command in help_text

    with pytest.raises(SystemExit) as caught:
        main(["ui", "--help"])
    assert caught.value.code == 0
    assert "Those commands stay the same" in capsys.readouterr().out


def test_cli_ui_dispatches(tmp_path: Path, monkeypatch):
    seen = {}

    def fake(config_dir, *, limit, explain):
        seen["dir"] = config_dir
        seen["limit"] = limit
        seen["explain"] = explain
        return 0

    monkeypatch.setattr("filefinder.ui.run_ui", fake)
    code = main(["--config-dir", str(tmp_path), "ui", "--limit", "7", "--explain"])
    assert code == 0
    assert seen["limit"] == 7
    assert seen["explain"] is True
    assert seen["dir"] == tmp_path.resolve()


def test_cli_ui_rejects_bad_limit(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setattr("filefinder.ui.run_ui", lambda *args, **kwargs: 0)
    assert main(["--config-dir", str(tmp_path), "ui", "--limit", "0"]) == 2
    assert "--limit" in capsys.readouterr().err


def _display_ok() -> bool:
    try:
        import tkinter as tk
    except ImportError:
        return False
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


@pytest.mark.skipif(not _display_ok(), reason="no display for tkinter")
def test_window_renders_hit_path_and_tree(tmp_path: Path, config_dir: Path):
    from filefinder.ui import Launcher

    index_tree(config_dir, _repo(tmp_path))
    window = Launcher(config_dir, limit=20, explain=False)
    window.withdraw()
    try:
        view = execute_search(config_dir, "auth", limit=20, explain=False)
        window.apply_view(view)
        window.update_idletasks()
        labels = _labels(window.result_box)
        assert "auth.py" in labels
        assert "billing/auth.py" in labels
        crumbs = [widget.cget("text") for widget in window.crumb_row.winfo_children()]
        assert "auth.py" in crumbs
        assert "billing" in crumbs
        assert window.tree.get_children()
        assert "auth.py" in window.match.get("1.0", "end")
        assert "1 result" in window.status.cget("text")
        assert "files" in window.catalog.cget("text")
    finally:
        window.destroy()


@pytest.mark.skipif(not _display_ok(), reason="no display for tkinter")
def test_window_searches_as_you_type(tmp_path: Path, config_dir: Path):
    from filefinder.ui import Launcher

    index_tree(config_dir, _repo(tmp_path))
    window = Launcher(config_dir, limit=20, explain=False)
    window.withdraw()
    deadline = time.monotonic() + 3

    def poll() -> None:
        if window._view.hits and window._view.query == "auth":
            window.quit()
            return
        if time.monotonic() >= deadline:
            window.quit()
            return
        window.after(40, poll)

    window.after(0, lambda: window.query_var.set("auth"))
    window.after(40, poll)
    try:
        window.mainloop()
        assert window._view.hits
        assert window._view.hits[0].name == "auth.py"
        assert "billing" in _labels(window.crumb_row)
        assert window.tree.get_children()
    finally:
        window.destroy()


def _labels(widget) -> list[str]:
    import tkinter as tk

    found: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            found.append(str(child.cget("text")))
        found.extend(_labels(child))
    return found
