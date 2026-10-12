#!/usr/bin/env python3
"""Verify the CLI process can init, index, and query without a model download."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC) if not current else str(SRC) + os.pathsep + current
    return env


def _run(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [sys.executable, "-m", "filefinder", *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise SystemExit(f"{' '.join(args)} failed ({completed.returncode}): {detail}")
    return completed


def main() -> int:
    env = _env()
    _run(["--help"], env)

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        (root / "auth.py").write_text("print('ok')\n", encoding="utf-8")
        config = Path(tmp) / "config"
        _run(["--config-dir", str(config), "init", str(root)], env)
        _run(["--config-dir", str(config), "index", "--skip-embed"], env)
        queried = _run(["--config-dir", str(config), "query", "auth"], env)
        if "auth.py" not in queried.stdout:
            raise SystemExit(f"query output did not include auth.py:\n{queried.stdout}")

    print("runnable ok: ff init, index --skip-embed, query")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as err:
        print(f"runnable check failed: {err}", file=sys.stderr)
        sys.exit(1)
