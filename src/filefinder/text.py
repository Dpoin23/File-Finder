import re

from filefinder.models import Chunk

MAX_BYTES = 5 * 1024 * 1024
CHUNK_WORDS = 400
CHUNK_OVERLAP = 50

# Query words that mark a sentence about contents rather than a filename.
FUNCTION_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "we",
        "our",
        "you",
        "your",
        "how",
        "what",
        "why",
        "where",
        "when",
        "which",
        "who",
        "to",
        "for",
        "of",
        "and",
        "or",
        "in",
        "on",
        "at",
        "is",
        "are",
        "was",
        "were",
        "be",
        "do",
        "does",
        "did",
        "about",
        "with",
        "from",
        "that",
        "this",
        "it",
        "as",
        "by",
        "into",
        "over",
    }
)

# Dropped only when building a full-text query. Classification still sees them.
STOPWORDS = FUNCTION_WORDS

TEXT_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".c",
        ".h",
        ".hh",
        ".hpp",
        ".cpp",
        ".cc",
        ".cs",
        ".rb",
        ".php",
        ".swift",
        ".scala",
        ".lua",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".sql",
        ".md",
        ".markdown",
        ".txt",
        ".rst",
        ".adoc",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".xml",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".vue",
        ".svelte",
        ".graphql",
        ".gql",
        ".proto",
        ".csv",
        ".tsv",
        ".r",
        ".jl",
        ".ex",
        ".exs",
        ".erl",
        ".hrl",
        ".hs",
        ".ml",
        ".mli",
        ".clj",
        ".cljs",
        ".edn",
        ".vim",
        ".el",
        ".tex",
        ".bib",
        ".gradle",
        ".cmake",
        ".mk",
        ".make",
        ".dart",
        ".nim",
        ".zig",
        ".tf",
        ".hcl",
        ".sv",
        ".v",
    }
)

TEXT_NAMES = frozenset(
    {
        "dockerfile",
        "makefile",
        "license",
        "licence",
        "copying",
        "readme",
        "gemfile",
        "rakefile",
        "procfile",
        "changelog",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
        ".bashrc",
        ".zshrc",
        ".npmrc",
        ".prettierrc",
        ".eslintrc",
    }
)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TOKEN = re.compile(r"[A-Za-z0-9]+")
_WORD = re.compile(r"\S+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def is_textlike(path_name: str, suffix: str) -> bool:
    if path_name.lower() in TEXT_NAMES:
        return True
    return suffix.lower() in TEXT_EXTENSIONS


def tokens(text: str) -> list[str]:
    found: list[str] = []
    for match in _TOKEN.findall(text):
        pieces = _CAMEL.findall(match) or [match]
        for piece in pieces:
            lowered = piece.lower()
            if len(lowered) > 1:
                found.append(lowered)
    return found


def content_tokens(text: str) -> list[str]:
    return [token for token in tokens(text) if token not in STOPWORDS]


def classify(query: str) -> str:
    """Return exact, description, or name.

    Exact is a quoted string or a bare identifier (camel case or snake case).
    A description is a phrase or sentence. Anything short that looks like a
    filename fragment stays on the path lane.
    """
    text = query.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return "exact"
    if _IDENT.fullmatch(text) and ("_" in text or any(ch.isupper() for ch in text)):
        return "exact"
    words = text.split()
    cleaned = [word.strip(".,?;:").lower() for word in words]
    if any(word in FUNCTION_WORDS for word in cleaned):
        return "description"
    if len(words) >= 4:
        return "description"
    return "name"


def strip_quotes(query: str) -> str:
    text = query.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def fts_query(words: list[str]) -> str:
    parts: list[str] = []
    for word in words:
        cleaned = word.replace('"', "")
        if cleaned:
            parts.append(f'"{cleaned}"')
    return " OR ".join(parts)


def overlap(query_tokens: list[str], other_tokens: list[str]) -> float:
    if not query_tokens:
        return 0.0
    other = set(other_tokens)
    shared = sum(1 for token in query_tokens if token in other)
    return shared / len(query_tokens)


def chunk_text(text: str, size: int = CHUNK_WORDS, overlap_words: int = CHUNK_OVERLAP) -> list[Chunk]:
    matches = list(_WORD.finditer(text))
    if not matches:
        return []
    step = max(1, size - overlap_words)
    chunks: list[Chunk] = []
    start_i = 0
    ordinal = 0
    while start_i < len(matches):
        end_i = min(len(matches), start_i + size)
        start = matches[start_i].start()
        end = matches[end_i - 1].end()
        piece = text[start:end]
        if piece.strip():
            chunks.append(Chunk(ordinal=ordinal, start=start, end=end, text=piece))
            ordinal += 1
        if end_i >= len(matches):
            break
        start_i += step
    return chunks


def read_text(path) -> str | None:
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")
