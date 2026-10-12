import json

from filefinder.explain import explain
from filefinder.models import Hit


def _hit(path: str, chunk: str) -> Hit:
    return Hit(path=path, score=1.0, lane="content", chunk=chunk)


def test_explain_without_a_model_stays_local(monkeypatch):
    monkeypatch.delenv("FF_EXPLAIN_BASE_URL", raising=False)
    monkeypatch.delenv("FF_EXPLAIN_MODEL", raising=False)

    def fail(*_args, **_kwargs):
        raise AssertionError("explain tried to use the network")

    monkeypatch.setattr("filefinder.explain.urllib.request.urlopen", fail)
    hits = [_hit("/repo/a.txt", "alpha"), _hit("/repo/b.txt", "beta")]

    ranked, sentence = explain("how billing works", hits)

    assert [hit.path for hit in ranked] == ["/repo/a.txt", "/repo/b.txt"]
    assert "a.txt" in sentence
    assert "alpha" in sentence


def test_explain_sends_only_fifteen_snippets_and_reorders(monkeypatch):
    monkeypatch.setenv("FF_EXPLAIN_BASE_URL", "http://models.example/v1")
    monkeypatch.setenv("FF_EXPLAIN_MODEL", "reranker")
    monkeypatch.delenv("FF_EXPLAIN_API_KEY", raising=False)
    hits = [_hit(f"/repo/file{i}.txt", f"snippet {i} " + ("x" * 800)) for i in range(20)]
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            body = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"order": [1, 0], "sentence": "The second snippet is the billing note."}
                            )
                        }
                    }
                ]
            }
            return json.dumps(body).encode()

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode())
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("filefinder.explain.urllib.request.urlopen", fake_urlopen)

    ranked, sentence = explain("how we bill annual customers", hits)

    snippets = json.loads(captured["body"]["messages"][1]["content"])["snippets"]
    assert captured["url"] == "http://models.example/v1/chat/completions"
    assert len(snippets) == 15
    assert "file15.txt" not in json.dumps(snippets)
    assert all(len(item["text"]) <= 500 for item in snippets)
    assert [hit.path for hit in ranked[:2]] == ["/repo/file1.txt", "/repo/file0.txt"]
    assert ranked[2].path == "/repo/file2.txt"
    assert ranked[-1].path == "/repo/file19.txt"
    assert sentence == "The second snippet is the billing note."
