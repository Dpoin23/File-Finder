import os
from pathlib import Path

import numpy as np

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class Embedder:
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError


class FastEmbedder(Embedder):
    """Local fastembed model. File bytes are embedded on this machine."""

    def __init__(self, model_name: str, cache_dir: Path, *, local_files_only: bool) -> None:
        self.name = model_name
        cache_dir.mkdir(parents=True, exist_ok=True)
        from fastembed import TextEmbedding

        self._model = TextEmbedding(
            model_name=model_name,
            cache_dir=str(cache_dir),
            local_files_only=local_files_only,
            cuda=False,
        )
        self.dim = int(self._model.embedding_size)

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        rows = [np.asarray(vec, dtype=np.float32) for vec in self._model.passage_embed(texts)]
        return _normalize(np.vstack(rows))

    def embed_query(self, text: str) -> np.ndarray:
        row = np.asarray(next(iter(self._model.query_embed(text))), dtype=np.float32)
        return _normalize(row.reshape(1, -1))[0]


def load_embedder(config_dir: Path, *, local_files_only: bool) -> FastEmbedder:
    model = os.environ.get("FF_EMBED_MODEL", "").strip() or DEFAULT_MODEL
    cache = config_dir / "models"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache / "hf"))
    if local_files_only:
        os.environ["HF_HUB_OFFLINE"] = "1"
    else:
        os.environ.pop("HF_HUB_OFFLINE", None)
    return FastEmbedder(model, cache, local_files_only=local_files_only)


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def pack_vector(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def unpack_vector(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).copy()
