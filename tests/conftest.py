from pathlib import Path

import pytest

from filefinder.config import save_roots
from filefinder.index import index_roots
from tests.stub_embed import LexiconEmbedder


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    path = tmp_path / "config"
    path.mkdir()
    return path


@pytest.fixture
def embedder() -> LexiconEmbedder:
    return LexiconEmbedder()


def index_tree(config_dir: Path, root: Path, embedder=None):
    save_roots(config_dir, [root])
    return index_roots(config_dir, embedder=embedder)
