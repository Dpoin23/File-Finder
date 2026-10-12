#!/usr/bin/env python3
"""Import the package and run one offline index plus name query."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    from filefinder.config import save_roots
    from filefinder.index import index_roots
    from filefinder.query import search
    from filefinder.text import chunk_text, classify

    if classify("auth middleware") != "name":
        raise SystemExit("name query was not classified as name")
    if classify("how we bill annual customers") != "description":
        raise SystemExit("description query was misclassified")
    if classify("ValidateRefund") != "exact":
        raise SystemExit("identifier query was not classified as exact")
    if not chunk_text("alpha beta gamma"):
        raise SystemExit("chunker returned nothing for plain text")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        (root / "auth.py").write_text("print('ok')\n", encoding="utf-8")
        config = Path(tmp) / "config"
        save_roots(config, [root])
        stats = index_roots(config)
        if stats.files != 1:
            raise SystemExit(f"expected 1 indexed file, got {stats.files}")
        result = search(config, "auth")
        if not result.hits or not result.hits[0].path.endswith("auth.py"):
            raise SystemExit(f"query missed auth.py: {result.hits}")

    print("smoke ok")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as err:
        print(f"smoke failed: {err}", file=sys.stderr)
        sys.exit(1)
