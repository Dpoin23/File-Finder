import json
import os
import urllib.request

from filefinder.models import Hit

_SNIPPET_CAP = 15
_SNIPPET_CHARS = 500


def explain(query: str, hits: list[Hit]) -> tuple[list[Hit], str]:
    """Reorder the shortlist and return one sentence.

    A remote model runs only when FF_EXPLAIN_BASE_URL and FF_EXPLAIN_MODEL
    are set. It sees at most 15 snippets. Otherwise the original order stands
    and the sentence is written locally.
    """
    if not hits:
        return hits, ""
    base = os.environ.get("FF_EXPLAIN_BASE_URL", "").strip()
    model = os.environ.get("FF_EXPLAIN_MODEL", "").strip()
    if not base or not model:
        return hits, local_sentence(hits[0])
    short = hits[:_SNIPPET_CAP]
    try:
        order, sentence = _remote(base, model, query, short)
    except Exception as exc:
        return hits, f"{local_sentence(hits[0])} Remote rerank failed: {exc}"
    reordered = _apply_order(short, order)
    return reordered + hits[_SNIPPET_CAP:], sentence or local_sentence(reordered[0])


def local_sentence(hit: Hit) -> str:
    snippet = " ".join(hit.chunk.split())
    if len(snippet) > 140:
        snippet = snippet[:139].rstrip() + "…"
    if snippet:
        return f"Top result {hit.path} matched on {hit.lane}: {snippet}"
    return f"Top result {hit.path} matched on {hit.lane}."


def _apply_order(hits: list[Hit], order: list[int]) -> list[Hit]:
    used: set[int] = set()
    ranked: list[Hit] = []
    for index in order:
        if isinstance(index, int) and 0 <= index < len(hits) and index not in used:
            used.add(index)
            ranked.append(hits[index])
    for index, hit in enumerate(hits):
        if index not in used:
            ranked.append(hit)
    return ranked


def _remote(base: str, model: str, query: str, hits: list[Hit]) -> tuple[list[int], str]:
    snippets = [
        {"index": index, "path": hit.path, "lane": hit.lane, "text": _clip(hit.chunk)}
        for index, hit in enumerate(hits[:_SNIPPET_CAP])
    ]
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Reorder file-search snippets for the query. Reply with JSON only: "
                    '{"order": [indices], "sentence": "one sentence"}. '
                    "Indices refer to the snippets array. Do not add snippets."
                ),
            },
            {"role": "user", "content": json.dumps({"query": query, "snippets": snippets})},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=body,
        headers=_headers(),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
    message = json.loads(raw)["choices"][0]["message"]["content"]
    parsed = _parse_model_json(message)
    order = parsed.get("order", [])
    sentence = parsed.get("sentence", "")
    if not isinstance(order, list):
        order = []
    if not isinstance(sentence, str):
        sentence = ""
    return order, sentence.strip()


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("FF_EXPLAIN_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _clip(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SNIPPET_CHARS:
        return collapsed
    return collapsed[: _SNIPPET_CHARS - 1].rstrip() + "…"


def _parse_model_json(message: str) -> dict:
    text = message.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("model did not return JSON")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model JSON was not an object")
    return parsed
