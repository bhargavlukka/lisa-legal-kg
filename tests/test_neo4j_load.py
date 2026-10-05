import copy
import json

import pytest

from lisa.common.config import load_settings
from lisa.graph.neo4j_load import Neo4jUnavailable, load, node_props

PREFIX = "zz_test:"


def test_node_props_flattens_for_neo4j():
    p = node_props({"props": {"a": 1, "b": None, "bases": ["name"]}, "provenance": "deterministic",
                    "confidence": 0.9, "evidence": [{"page": 2, "quote": "§ x"}], "extractor": "e/1"})
    assert p == {"a": 1, "bases": ["name"], "provenance": "deterministic", "confidence": 0.9,
                 "evidence": json.dumps([{"page": 2, "quote": "§ x"}], ensure_ascii=False), "extractor": "e/1"}


def _prefixed(graph):
    g = copy.deepcopy(graph)
    for n in g["nodes"]:
        n["id"] = PREFIX + n["id"]
    for e in g["edges"]:
        e["source"], e["target"] = PREFIX + e["source"], PREFIX + e["target"]
    return g


def test_load_is_idempotent(graph_all):
    try:
        settings = load_settings()
    except RuntimeError:
        pytest.skip("LISA settings not configured")
    from neo4j import GraphDatabase
    g = _prefixed(graph_all)
    try:
        load(g, settings)
        load(g, settings)
    except Neo4jUnavailable as e:
        pytest.skip(f"Neo4j not available: {e}")
    with GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)) as d:
        with d.session() as s:
            n = s.run("MATCH (n) WHERE n.id STARTS WITH $p RETURN count(n) AS c", p=PREFIX).single()["c"]
            r = s.run("MATCH (a)-[r]->() WHERE a.id STARTS WITH $p RETURN count(r) AS c", p=PREFIX).single()["c"]
            s.run("MATCH (n) WHERE n.id STARTS WITH $p DETACH DELETE n", p=PREFIX).consume()
    assert n == len(g["nodes"]) and r == len(g["edges"])


def test_malformed_uri_is_reported_as_unavailable(tmp_path, graph_all):
    from lisa.common.config import Settings
    s = Settings(data_dir=tmp_path, out_dir=tmp_path, neo4j_uri="localhost:7687", neo4j_user="neo4j",
                 neo4j_password="x" * 8)
    with pytest.raises(Neo4jUnavailable):
        load(graph_all, s)


def test_merge_labels_llm_edges_and_drops_dangling():
    from lisa.graph.neo4j_load import LABELS, REL_TYPES, merge
    det = {"nodes": [{"id": "c1", "label": "Case"}, {"id": "c2", "label": "Case"}], "edges": []}
    llm = {"nodes": [{"id": "d1", "label": "Doctrine"}, {"id": "c1", "label": "Shadow"}],
           "edges": [{"type": "FOLLOWS", "source": "c1", "target": "c2"},
                     {"type": "INVOKES_DOCTRINE", "source": "c1", "target": "d1"},
                     {"type": "FOLLOWS", "source": "c1", "target": "ghost"}]}
    m = merge([det, llm])
    assert {n["id"]: n["label"] for n in m["nodes"]} == {"c1": "Case", "c2": "Case", "d1": "Doctrine"}
    assert [(e["type"], e["source_label"], e["target_label"]) for e in m["edges"]] == [
        ("FOLLOWS", "Case", "Case"), ("INVOKES_DOCTRINE", "Case", "Doctrine")]
    assert {"Doctrine", "Judge"} <= set(LABELS) and {"FOLLOWS", "DISTINGUISHES", "OVERRULES"} <= set(REL_TYPES)
