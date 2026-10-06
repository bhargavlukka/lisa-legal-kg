import pytest

from fakes import FakeClient
from lisa.extract.calljson import ExtractionFailed, Truncated, call_json, parse_json
from lisa.llm.budget import RunStats

MSG = [{"role": "user", "content": "x"}]


def test_parse_json_plain_fenced_and_prose():
    assert parse_json('{"nodes": []}') == {"nodes": []}
    assert parse_json('```json\n{"nodes": [1]}\n```') == {"nodes": [1]}
    assert parse_json('Here you go:\n{"nodes": [2]}\nThanks!') == {"nodes": [2]}


def test_parse_json_garbage_raises():
    with pytest.raises(ValueError):
        parse_json("no json here")


def test_call_json_returns_list():
    assert call_json(FakeClient(lambda m: '{"nodes": [{"a": 1}]}'), MSG, "v", "nodes", RunStats()) == [{"a": 1}]


def test_call_json_repairs_once_then_succeeds():
    replies = iter(['{"nodes": [', '{"nodes": [{"a": 2}]}'])
    stats = RunStats()
    fc = FakeClient(lambda m: next(replies))
    assert call_json(fc, MSG, "v", "nodes", stats) == [{"a": 2}]
    assert stats.repairs == 1 and "not valid" in fc.calls[1][-1]["content"]


def test_call_json_repairs_once_then_fails():
    with pytest.raises(ExtractionFailed):
        call_json(FakeClient(lambda m: '{"edges": []}'), MSG, "v", "nodes", RunStats())


def test_call_json_truncation():
    stats = RunStats()
    with pytest.raises(Truncated):
        call_json(FakeClient(lambda m: ('{"nodes": [', "length")), MSG, "v", "nodes", stats)
    assert stats.truncations == 1
