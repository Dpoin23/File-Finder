from dataclasses import dataclass, field


class ConfigError(Exception):
    """The config directory, roots, or index are not usable."""


@dataclass
class Chunk:
    ordinal: int
    start: int
    end: int
    text: str


@dataclass
class IndexStats:
    files: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    chunks: int = 0


@dataclass
class Accum:
    """Signals collected for one path before rank fusion."""

    path: str
    exact_name: float = 0.0
    name_overlap: float = 0.0
    dir_overlap: float = 0.0
    content: float = 0.0
    vector: float = 0.0
    ripgrep: float = 0.0
    content_chunk: str = ""
    vector_chunk: str = ""
    path_chunk: str = ""
    rg_chunk: str = ""
    line: int | None = None
    contributions: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Hit:
    path: str
    score: float
    lane: str
    chunk: str
    line: int | None = None


@dataclass
class QueryResult:
    hits: list[Hit]
    sentence: str | None
    kind: str
