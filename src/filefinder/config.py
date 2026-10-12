import os
from pathlib import Path

from filefinder.models import ConfigError

CONFIG_NAME = "config.json"
DB_NAME = "index.sqlite"
MODEL_DIR = "models"


def default_config_dir() -> Path:
    override = os.environ.get("FF_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return (base / "file-finder").resolve()


def config_path(config_dir: Path) -> Path:
    return config_dir / CONFIG_NAME


def database_path(config_dir: Path) -> Path:
    return config_dir / DB_NAME


def model_cache_dir(config_dir: Path) -> Path:
    return config_dir / MODEL_DIR


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines. Existing environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            os.environ.setdefault(key, value)


def load_roots(config_dir: Path) -> list[Path]:
    path = config_path(config_dir)
    if not path.is_file():
        raise ConfigError(f"No roots yet. Run: ff init PATH [PATH...]")
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc
    roots = data.get("roots")
    if not isinstance(roots, list) or not all(isinstance(item, str) for item in roots):
        raise ConfigError(f"{path} must contain a roots list")
    if not roots:
        raise ConfigError(f"No roots in {path}. Run: ff init PATH [PATH...]")
    return [Path(item) for item in roots]


def save_roots(config_dir: Path, roots: list[Path]) -> None:
    import json

    config_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(config_dir, 0o700)
    unique: list[str] = []
    seen: set[str] = set()
    for root in roots:
        text = str(root.resolve())
        if text not in seen:
            seen.add(text)
            unique.append(text)
    path = config_path(config_dir)
    path.write_text(json.dumps({"roots": unique}, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def tighten(path: Path) -> None:
    if path.exists():
        os.chmod(path, 0o600)
    for suffix in ("-wal", "-shm"):
        extra = Path(str(path) + suffix)
        if extra.exists():
            os.chmod(extra, 0o600)
