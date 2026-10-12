import argparse
import sys
from pathlib import Path

from filefinder.config import default_config_dir, load_dotenv, save_roots
from filefinder.embed import load_embedder
from filefinder.index import index_roots
from filefinder.models import ConfigError
from filefinder.query import format_results, search
from filefinder.text import classify


def cli() -> None:
    raise SystemExit(main())


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env")
    parser = argparse.ArgumentParser(
        prog="ff",
        description="Search local folders by filename or by a description of the contents.",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        help="Config and index directory. Defaults to FF_CONFIG_DIR or ~/.config/file-finder.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Write the list of folders to index")
    init.add_argument("paths", nargs="+", help="Directories to search")

    index = sub.add_parser("index", help="Walk the roots into the local index")
    index.add_argument(
        "--skip-embed",
        action="store_true",
        help="Build the path and content indexes without local embeddings",
    )

    query = sub.add_parser("query", help="Rank files for a name fragment or description")
    query.add_argument("text", nargs="+", help="Filename fragment, sentence, or exact symbol")
    query.add_argument("--limit", type=int, default=20, help="Maximum paths to print")
    query.add_argument(
        "--explain",
        action="store_true",
        help="Add one sentence. A remote model reranks only when FF_EXPLAIN_BASE_URL is set.",
    )

    args = parser.parse_args(argv)
    config_dir = Path(args.config_dir).expanduser().resolve() if args.config_dir else default_config_dir()
    try:
        if args.command == "init":
            return _init(config_dir, args.paths)
        if args.command == "index":
            return _index(config_dir, skip_embed=args.skip_embed)
        return _query(config_dir, " ".join(args.text), limit=args.limit, explain_result=args.explain)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _init(config_dir: Path, paths: list[str]) -> int:
    roots = [Path(path).expanduser().resolve() for path in paths]
    missing = [root for root in roots if not root.is_dir()]
    if missing:
        listed = ", ".join(str(root) for root in missing)
        print(f"Not a directory: {listed}", file=sys.stderr)
        return 2
    save_roots(config_dir, roots)
    print(f"Wrote {len(roots)} root(s) to {config_dir}")
    for root in roots:
        print(root)
    return 0


def _index(config_dir: Path, *, skip_embed: bool) -> int:
    embedder = None
    if not skip_embed:
        try:
            embedder = load_embedder(config_dir, local_files_only=False)
        except Exception as exc:
            print(f"Could not load the local embedding model: {exc}", file=sys.stderr)
            print("Name and word-overlap search can still be built with: ff index --skip-embed", file=sys.stderr)
            return 1
    stats = index_roots(config_dir, embedder=embedder)
    print(
        f"files {stats.files}, updated {stats.updated}, unchanged {stats.unchanged}, "
        f"removed {stats.removed}, chunks in index {stats.chunks}"
    )
    return 0


def _query(config_dir: Path, text: str, *, limit: int, explain_result: bool) -> int:
    if limit < 1:
        print("--limit must be at least 1", file=sys.stderr)
        return 2
    kind = classify(text)
    embedder = None
    if kind == "description":
        try:
            embedder = load_embedder(config_dir, local_files_only=True)
        except Exception as exc:
            print(
                f"Local embedding model is unavailable ({exc}). Word overlap still ran.",
                file=sys.stderr,
            )
    result = search(
        config_dir,
        text,
        embedder=embedder,
        limit=limit,
        explain_result=explain_result,
    )
    if not result.hits:
        print("no matches", file=sys.stderr)
        return 0
    sys.stdout.write(format_results(result))
    return 0
