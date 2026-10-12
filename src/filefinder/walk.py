import os
import stat
from pathlib import Path

import pathspec

from filefinder.text import MAX_BYTES

SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".jj",
        ".bzr",
        "node_modules",
        "bower_components",
        "vendor",
        "venv",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",
        ".tox",
        ".nox",
        "site-packages",
        ".next",
        ".nuxt",
        ".cache",
        "Pods",
        "coverage",
        ".gradle",
        ".idea",
    }
)

BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".tif",
        ".tiff",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".odt",
        ".ods",
        ".odp",
        ".zip",
        ".tar",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".mkv",
        ".wav",
        ".flac",
        ".ogg",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".o",
        ".a",
        ".obj",
        ".class",
        ".jar",
        ".war",
        ".pyc",
        ".pyo",
        ".wasm",
        ".bin",
        ".dat",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".parquet",
        ".feather",
        ".arrow",
        ".npy",
        ".npz",
        ".pickle",
        ".pkl",
        ".psd",
        ".ai",
        ".sketch",
    }
)

_KEY_NAMES = frozenset({"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519"})
_KEY_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx"})


def is_sensitive(path: Path) -> bool:
    name = path.name
    if name == ".env" or (name.startswith(".env.") and not name.endswith((".example", ".sample"))):
        return True
    if name in _KEY_NAMES or path.suffix.lower() in _KEY_SUFFIXES:
        return True
    return False


def _load_spec(path: Path) -> pathspec.PathSpec | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    kept = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not kept:
        return None
    return pathspec.PathSpec.from_lines("gitignore", kept)


def _ignored(path: Path, specs: list[tuple[Path, pathspec.PathSpec]]) -> bool:
    """Last matching gitignore pattern wins, from parent specs down to the child."""
    ignored = False
    for base, spec in specs:
        try:
            rel = path.relative_to(base).as_posix()
        except ValueError:
            continue
        candidates = [rel]
        if path.is_dir():
            candidates.append(rel + "/")
        for pattern in spec.patterns:
            regex = getattr(pattern, "regex", None)
            include = getattr(pattern, "include", None)
            if regex is None or include is None:
                continue
            if any(regex.match(candidate) for candidate in candidates):
                # include=True means the pattern selects the path (a normal
                # gitignore rule). include=False is a negation (!pattern).
                ignored = bool(include)
    return ignored


def iter_files(root: Path):
    """Yield regular files under root that pass ignore rules."""
    root = root.resolve()
    specs: list[tuple[Path, pathspec.PathSpec]] = []
    root_spec = _load_spec(root / ".gitignore")
    if root_spec is not None:
        specs.append((root, root_spec))

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        specs = [(base, spec) for base, spec in specs if current == base or base in current.parents]
        gitignore = current / ".gitignore"
        if gitignore.is_file() and not any(base == current for base, _ in specs):
            spec = _load_spec(gitignore)
            if spec is not None:
                specs.append((current, spec))

        kept_dirs: list[str] = []
        for name in dirnames:
            if name in SKIP_DIRS:
                continue
            child = current / name
            if child.is_symlink():
                continue
            if _ignored(child, specs):
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in filenames:
            path = current / name
            if path.is_symlink():
                continue
            if path.suffix.lower() in BINARY_EXTENSIONS or is_sensitive(path):
                continue
            if _ignored(path, specs):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):
                continue
            if st.st_size > MAX_BYTES:
                continue
            yield path, st
