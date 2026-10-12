from pathlib import Path

from filefinder.query import search
from tests.conftest import index_tree


def test_bare_identifier_returns_the_exact_line(tmp_path: Path, config_dir: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "refund.py").write_text("def ValidateRefund(order):\n    return order\n")
    (root / "other.py").write_text("def ship(order):\n    return order\n")
    index_tree(config_dir, root)

    result = search(config_dir, "ValidateRefund")

    assert result.kind == "exact"
    assert result.hits[0].path.endswith("refund.py")
    assert result.hits[0].line == 1
    assert result.hits[0].lane == "ripgrep"
    assert "ValidateRefund" in result.hits[0].chunk


def test_quoted_string_returns_the_exact_line(tmp_path: Path, config_dir: Path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "billing.txt").write_text("prepare the annual invoice before monday\n")
    index_tree(config_dir, root)

    result = search(config_dir, '"annual invoice"')

    assert result.kind == "exact"
    assert result.hits[0].path.endswith("billing.txt")
    assert result.hits[0].line == 1
    assert "annual invoice" in result.hits[0].chunk
