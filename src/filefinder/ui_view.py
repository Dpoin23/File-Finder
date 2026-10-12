"""View data for the search popup. No widgets, so it can be tested headless."""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

from filefinder.config import database_path, load_roots
from filefinder.db import connect
from filefinder.models import ConfigError, Hit
from filefinder.query import search
from filefinder.text import classify

_LANES = (
    ("path", "Path"),
    ("content", "Content"),
    ("vector", "Vectors"),
    ("ripgrep", "Ripgrep"),
)

_ACTIVE = {
    "name": frozenset({"path", "content"}),
    "description": frozenset({"path", "content", "vector"}),
    "exact": frozenset({"path", "content", "ripgrep"}),
}

_KIND_LABEL = {
    "name": "Name",
    "description": "Description",
    "exact": "Exact",
}

_PLUS_LINE = frozenset({"vi", "vim", "nvim", "nano", "emacs", "hx", "helix"})
_GOTO = frozenset({"code", "codium", "cursor", "code-insiders", "subl", "sublime_text"})


@dataclass(frozen=True)
class LaneState:
    key: str
    label: str
    state: str  # on, off, missing


@dataclass(frozen=True)
class HitView:
    path: str
    name: str
    root: str
    relative: str
    crumbs: tuple[str, ...]
    lane: str
    line: int | None
    snippet: str
    detail: str


@dataclass
class TreeNode:
    name: str
    path: str | None = None
    children: list[TreeNode] = field(default_factory=list)


@dataclass
class SearchView:
    query: str
    kind: str
    kind_label: str
    lanes: list[LaneState]
    hits: list[HitView]
    tree: list[TreeNode]
    sentence: str | None
    error: str | None
    notice: str | None

    @classmethod
    def blank(cls) -> SearchView:
        return cls(
            query="",
            kind="",
            kind_label="",
            lanes=lane_states(""),
            hits=[],
            tree=[],
            sentence=None,
            error=None,
            notice=None,
        )


def lane_states(kind: str, *, vectors_ready: bool = True) -> list[LaneState]:
    active = _ACTIVE.get(kind, frozenset())
    states: list[LaneState] = []
    for key, label in _LANES:
        if key not in active:
            state = "off"
        elif key == "vector" and not vectors_ready:
            state = "missing"
        else:
            state = "on"
        states.append(LaneState(key, label, state))
    return states


def execute_search(
    config_dir: Path,
    query: str,
    *,
    limit: int,
    explain: bool,
    embedder=None,
    embedder_error: str | None = None,
) -> SearchView:
    text = query.strip()
    if not text:
        return SearchView.blank()
    kind = classify(text)
    vectors_ready = embedder is not None
    notice = None
    if kind == "description" and embedder is None:
        notice = embedder_error or "Local embedding model is unavailable. Word overlap still ran."
    try:
        roots = load_roots(config_dir)
        result = search(
            config_dir,
            text,
            embedder=embedder if kind == "description" else None,
            limit=limit,
            explain_result=explain,
        )
    except ConfigError as exc:
        return SearchView(
            query=text,
            kind=kind,
            kind_label=_KIND_LABEL[kind],
            lanes=lane_states(kind, vectors_ready=vectors_ready),
            hits=[],
            tree=[],
            sentence=None,
            error=str(exc),
            notice=notice,
        )
    hits = [_hit_view(hit, roots) for hit in result.hits]
    return SearchView(
        query=text,
        kind=kind,
        kind_label=_KIND_LABEL[kind],
        lanes=lane_states(kind, vectors_ready=vectors_ready),
        hits=hits,
        tree=build_tree(hits),
        sentence=result.sentence,
        error=None,
        notice=notice,
    )


def catalog_summary(config_dir: Path) -> str:
    try:
        roots = load_roots(config_dir)
    except ConfigError as exc:
        return str(exc)
    path = database_path(config_dir)
    if not path.is_file():
        return "No index yet. Run ff index."
    con = connect(path)
    try:
        files = int(con.execute("SELECT COUNT(*) FROM files").fetchone()[0])
        chunks = int(con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
    finally:
        con.close()
    names = ", ".join(Path(root).name or str(root) for root in roots)
    return f"{files} files · {chunks} chunks · {names}"


def build_tree(hits: list[HitView]) -> list[TreeNode]:
    labels = _root_labels([hit.root for hit in hits if hit.root])
    roots: dict[str, TreeNode] = {}
    for hit in hits:
        if hit.root:
            node = roots.get(hit.root)
            if node is None:
                node = TreeNode(labels.get(hit.root, Path(hit.root).name or hit.root))
                roots[hit.root] = node
            _attach(node, Path(hit.relative).parts, hit.path)
        else:
            node = roots.get(hit.path)
            if node is None:
                roots[hit.path] = TreeNode(hit.name, path=hit.path)
    ordered = list(roots.values())
    for node in ordered:
        _sort_tree(node)
    ordered.sort(key=lambda node: node.name.lower())
    return ordered


def open_argv(path: str, line: int | None) -> list[str] | None:
    """Argv for the editor, or None when the platform default opener should run."""
    editor = (
        os.environ.get("FF_EDITOR", "").strip()
        or os.environ.get("VISUAL", "").strip()
        or os.environ.get("EDITOR", "").strip()
    )
    if not editor:
        if sys.platform == "darwin":
            return ["open", path]
        if sys.platform == "win32":
            return None
        return ["xdg-open", path]
    parts = shlex.split(editor)
    if not parts:
        return ["xdg-open", path]
    program = Path(parts[0]).name.lower()
    if line is not None and program in _PLUS_LINE:
        return [*parts, f"+{line}", path]
    if line is not None and program in _GOTO:
        return [*parts, "--goto", f"{path}:{line}"]
    return [*parts, path]


def clip(text: str, limit: int) -> str:
    snippet = " ".join(text.split())
    if len(snippet) <= limit:
        return snippet
    return snippet[: limit - 1].rstrip() + "…"


def _hit_view(hit: Hit, roots: list[Path]) -> HitView:
    root, relative = _locate(hit.path, roots)
    name = Path(hit.path).name or hit.path
    crumbs = _crumbs(root, relative, hit.path)
    return HitView(
        path=hit.path,
        name=name,
        root=root,
        relative=relative or name,
        crumbs=tuple(crumbs),
        lane=hit.lane,
        line=hit.line,
        snippet=clip(hit.chunk, 160),
        detail=clip(hit.chunk, 700),
    )


def _locate(path: str, roots: list[Path]) -> tuple[str, str]:
    candidate = Path(path)
    best: tuple[int, Path, Path] | None = None
    for root in roots:
        try:
            relative = candidate.resolve().relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        depth = len(relative.parts)
        if best is None or depth < best[0]:
            best = (depth, root.resolve(), relative)
    if best is None:
        return "", ""
    _, root, relative = best
    return str(root), relative.as_posix()


def _crumbs(root: str, relative: str, path: str) -> list[str]:
    if root and relative:
        parts = [Path(root).name or root, *Path(relative).parts]
    else:
        parts = [part for part in Path(path).parts if part not in {"/", ""}]
    if len(parts) <= 6:
        return parts
    return [parts[0], "…", *parts[-4:]]


def _root_labels(roots: list[str]) -> dict[str, str]:
    unique = list(dict.fromkeys(roots))
    names = [Path(root).name or root for root in unique]
    if len(names) == len(set(names)):
        return dict(zip(unique, names, strict=True))
    return {root: root for root in unique}


def _attach(node: TreeNode, parts: tuple[str, ...], path: str) -> None:
    current = node
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        child = next((item for item in current.children if item.name == part), None)
        if child is None:
            child = TreeNode(part, path=path if last else None)
            current.children.append(child)
        elif last:
            child.path = path
        current = child


def _sort_tree(node: TreeNode) -> None:
    for child in node.children:
        _sort_tree(child)
    node.children.sort(key=lambda child: (child.path is not None, child.name.lower()))
