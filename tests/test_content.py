from pathlib import Path

from filefinder.query import search
from tests.conftest import index_tree


def test_description_reuses_the_files_words(tmp_path: Path, config_dir: Path, embedder):
    root = tmp_path / "repo"
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "random.txt").write_text(
        "The annual invoice export writes a CSV for each account.\n"
    )
    (root / "annual_invoice_export.py").write_text("print('hello')\n")
    index_tree(config_dir, root, embedder=embedder)

    result = search(config_dir, "where is the annual invoice export", embedder=embedder)

    assert result.kind == "description"
    assert result.hits[0].path.endswith("notes/random.txt")
    assert "annual invoice export" in result.hits[0].chunk
    assert result.hits[0].lane in {"content", "vector"}


def test_paraphrase_uses_vectors_without_shared_words(tmp_path: Path, config_dir: Path, embedder):
    root = tmp_path / "repo"
    (root / "billing").mkdir(parents=True)
    (root / "billing" / "subscriptions.md").write_text(
        "Each active account is charged through subscription invoicing at the start of the term.\n"
    )
    (root / "ui").mkdir()
    (root / "ui" / "buttons.md").write_text(
        "The primary button uses a blue fill and rounded corners.\n"
    )
    index_tree(config_dir, root, embedder=embedder)

    result = search(config_dir, "how we bill annual customers", embedder=embedder)

    assert result.hits[0].path.endswith("billing/subscriptions.md")
    assert result.hits[0].lane == "vector"
    assert "subscription invoicing" in result.hits[0].chunk
    assert not any(hit.path.endswith("buttons.md") and hit.score >= result.hits[0].score for hit in result.hits[1:])


def test_filename_query_prefers_the_path_catalog(tmp_path: Path, config_dir: Path, embedder):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "auth.py").write_text("print('totals')\n")
    (root / "payments.md").write_text("The auth module is documented here.\n")
    index_tree(config_dir, root, embedder=embedder)

    result = search(config_dir, "auth", embedder=embedder)

    assert result.kind == "name"
    assert result.hits[0].path.endswith("auth.py")
    assert result.hits[0].lane == "path"
    assert any(hit.path.endswith("payments.md") for hit in result.hits)
    assert result.hits[0].score > next(hit.score for hit in result.hits if hit.path.endswith("payments.md"))
