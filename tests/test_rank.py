from filefinder.models import Accum
from filefinder.query import rank_accums
from filefinder.text import classify


def _only(**signals) -> Accum:
    path = signals.pop("path")
    accum = Accum(path=path, path_chunk=path, content_chunk="body", vector_chunk="body", rg_chunk="line")
    for name, value in signals.items():
        setattr(accum, name, value)
    return accum


def test_query_shape():
    assert classify("auth middleware") == "name"
    assert classify("how we bill annual customers") == "description"
    assert classify("ValidateRefund") == "exact"
    assert classify('"annual invoice"') == "exact"


def test_name_rank_order():
    ranked = rank_accums(
        "name",
        [
            _only(path="vector", vector=1),
            _only(path="content", content=1),
            _only(path="directory", dir_overlap=1),
            _only(path="filename", name_overlap=1),
            _only(path="exact", exact_name=1),
        ],
    )
    assert [hit.path for hit in ranked] == ["exact", "filename", "directory", "content", "vector"]


def test_description_rank_order():
    ranked = rank_accums(
        "description",
        [
            _only(path="filename", name_overlap=1),
            _only(path="directory", dir_overlap=1),
            _only(path="content", content=1),
            _only(path="vector", vector=1),
        ],
    )
    assert [hit.path for hit in ranked] == ["vector", "content", "directory", "filename"]


def test_exact_filename_still_wins_a_descriptive_score():
    ranked = rank_accums(
        "description",
        [
            _only(path="vector", vector=1),
            _only(path="exact", exact_name=1),
        ],
    )
    assert ranked[0].path == "exact"
    assert ranked[0].lane == "path"
