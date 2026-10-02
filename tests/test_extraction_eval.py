import copy
import random

from lisa.eval.extraction_eval import (Counts, UnitPair, evaluate, mapped_tier, match_edges, match_nodes,
                                       node_score, spans, threshold_sweep)
from lisa.extract.verify import PageIndex
from lisa.graph.loader import Record

WORDS = [f"word{i}" for i in range(400)]
PAGES = {1: " ".join(WORDS[:200]), 2: " ".join(WORDS[200:])}
IDX = PageIndex(PAGES)
TYPES = ["fact", "issue", "rule", "holding", "reasoning"]


def q(a, b):
    return " ".join(WORDS[a:b])


def gold_unit(n=20):
    nodes = [{"id": f"g:{TYPES[i % 5]}:{i}", "type": TYPES[i % 5], "label": f"label {i}", "summary": "",
              "evidence": [{"page": 1 + (i * 10) // 200, "quote": q(i * 10 + 1, i * 10 + 9)}]} for i in range(n)]
    edges = [{"source": nodes[i]["id"], "target": nodes[i + 1]["id"], "relation": "supports"} for i in range(n - 1)]
    return {"nodes": nodes, "edges": edges}


def as_pred(gold):
    p = copy.deepcopy(gold)
    rename = {n["id"]: n["id"].replace("g:", "p:") for n in p["nodes"]}
    for n in p["nodes"]:
        n["id"] = rename[n["id"]]
        n["provenance"] = "llm"
    for e in p["edges"]:
        e["source"], e["target"] = rename[e["source"]], rename[e["target"]]
        e["provenance"] = "llm"
    return p


def pair(pred, gold, domain="immigration", uid="u1"):
    return UnitPair(uid, domain, pred, gold, IDX)


def test_counts():
    c = Counts(tp=8, fp=2, fn=8)
    assert (c.p, c.r, round(c.f1, 4)) == (0.8, 0.5, 0.6154)
    assert Counts().p == 0.0 and Counts().f1 == 0.0


def test_spans_and_score():
    g = gold_unit()["nodes"][0]
    assert spans(g, IDX) and node_score(g, g, spans(g, IDX), spans(g, IDX)) > 0.99
    other = {"type": "fact", "label": "zzz", "summary": "", "evidence": [{"page": 2, "quote": q(300, 309)}]}
    assert node_score(other, g, spans(other, IDX), spans(g, IDX)) == 0.0


def test_gold_vs_itself_is_perfect():
    g = gold_unit()
    r = evaluate([pair(as_pred(g), g)], 0.3)
    for k in ("nodes_strict", "nodes_relaxed", "edges_strict", "edges_relaxed"):
        assert r["micro"][k]["p"] == 1.0 and r["micro"][k]["r"] == 1.0, k


def test_dropping_20pct_nodes_lowers_recall_only():
    g = gold_unit()
    p = as_pred(g)
    p["nodes"] = p["nodes"][:16]
    r = evaluate([pair(p, g)], 0.3)["micro"]["nodes_strict"]
    assert r["p"] == 1.0 and r["r"] == 0.8


def test_shuffled_relations_keep_nodes_and_drop_edges():
    g = gold_unit()
    p = as_pred(g)
    for e in p["edges"]:
        e["relation"] = "applies_rule"
    r = evaluate([pair(p, g)], 0.3)["micro"]
    assert r["nodes_strict"]["f1"] == 1.0 and r["edges_strict"]["f1"] == 0.0 and r["edges_relaxed"]["f1"] == 1.0


def test_wrong_type_matches_only_relaxed():
    g = gold_unit(5)
    p = as_pred(g)
    p["nodes"][0]["type"] = "outcome"
    m_strict = match_nodes(p["nodes"], g["nodes"], IDX, 0.3)
    m_relaxed = match_nodes(p["nodes"], g["nodes"], IDX, 0.3, relaxed=True)
    assert "p:fact:0" not in m_strict and m_relaxed["p:fact:0"] == "g:fact:0"


def test_matching_is_one_to_one():
    g = gold_unit(5)
    p = as_pred(g)
    p["nodes"].append({**p["nodes"][0], "id": "p:dup"})
    m = match_nodes(p["nodes"], g["nodes"], IDX, 0.3)
    assert len(set(m.values())) == len(m) == 5


def test_edge_matching_needs_both_endpoints():
    g = gold_unit(3)
    p = as_pred(g)
    pairs = match_edges(p["edges"], g["edges"], {"p:fact:0": "g:fact:0", "p:issue:1": "g:issue:1"})
    assert pairs == [(0, 0)]


def test_threshold_monotonic_recall():
    rng = random.Random(0)
    g = gold_unit()
    p = as_pred(g)
    for n in p["nodes"]:
        a = rng.randint(0, 6)
        i = int(n["id"].split(":")[-1])
        n["evidence"] = [{"page": 1 + (i * 10) // 200, "quote": q(i * 10 + 1 + a, i * 10 + 9 + a)}]
        n["label"] = "something else"
    sweep = threshold_sweep([pair(p, g)])
    recalls = [s["nodes_strict"]["r"] for s in sweep]
    assert recalls == sorted(recalls, reverse=True) and [s["threshold"] for s in sweep][0] == 0.1


def test_per_type_per_domain_macro_and_provenance():
    g = gold_unit()
    p = as_pred(g)
    p["nodes"][0]["provenance"] = "unverified"
    r = evaluate([pair(p, g, "immigration", "u1"), pair(as_pred(g), g, "litigation", "u2")], 0.3)
    assert set(r["by_domain"]) == {"immigration", "litigation"}
    assert r["by_node_type"]["fact"]["tp"] == 8 and r["by_relation"]["supports"]["tp"] == 38
    assert r["macro"]["nodes_strict"]["f1"] == 1.0
    assert r["provenance"]["unverified"]["count"] == 1 and r["provenance"]["unverified"]["precision"] == 1.0
    assert r["units"][0]["unit_id"] == "u1"


def test_mapped_tier():
    recs = [Record("c1", "litigation", "A", "1 U.S. 1", {"court": "SCOTUS"}, [], "", []),
            Record("c2", "litigation", "B", "2 U.S. 2", {"court": "SCOTUS"}, [], "", [])]
    ev = [{"page": 1, "quote": "x"}]
    gold = {"unit_id": "c1__u1of1", "case_id": "c1", "nodes": [
        {"id": "o", "type": "opinion", "author": "Kagan", "evidence": ev, "attrs": {}},
        {"id": "r", "type": "reasoning", "evidence": ev, "attrs": {}},
        {"id": "a", "type": "authority_ref", "evidence": ev, "attrs": {"cite_string": "2 U.S. 2", "kind": "case"}}],
        "edges": [{"source": "r", "target": "a", "relation": "relies_on", "stance": "follows", "evidence": ev}]}
    pred = copy.deepcopy(gold)
    pred["edges"][0]["stance"] = "distinguishes"
    out = mapped_tier([pred], [gold], recs, Counts(tp=3, fp=1, fn=1))
    assert out["AUTHORED_BY"]["tp"] == 1 and out["FOLLOWS"]["fn"] == 1 and out["DISTINGUISHES"]["fp"] == 1
    assert out["Doctrine(rule)"]["tp"] == 3
