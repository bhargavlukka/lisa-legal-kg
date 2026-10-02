from lisa.eval.error_analysis import BUCKETS, bucket_errors, summarize
from lisa.eval.extraction_eval import UnitPair, evaluate
from lisa.eval.report import render_markdown
from lisa.extract.verify import PageIndex

W = [f"w{i}" for i in range(300)]
IDX = PageIndex({1: " ".join(W)})


def q(a, b):
    return " ".join(W[a:b])


def n(id_, type_, a, b, prov="llm", label="x"):
    return {"id": id_, "type": type_, "label": label, "summary": "", "provenance": prov,
            "evidence": [{"page": 1, "quote": q(a, b)}]}


GOLD = {"nodes": [n("g1", "fact", 0, 10), n("g2", "issue", 20, 30), n("g3", "rule", 40, 60), n("g4", "holding", 100, 110),
                  n("g5", "reasoning", 200, 210)],
        "edges": [{"source": "g1", "target": "g2", "relation": "relevant_to"},
                  {"source": "g5", "target": "g4", "relation": "supports"},
                  {"source": "g4", "target": "g3", "relation": "applies_rule"}]}
PRED = {"nodes": [n("p1", "fact", 0, 10), n("p2", "holding", 20, 30),          # wrong type
                  n("p3", "rule", 40, 44, label="tiny piece"),                  # granularity (IoU 0.2 -> 0.16)
                  n("p4", "reasoning", 150, 160, prov="unverified"),            # quote_miss
                  n("p5", "holding", 100, 110), n("p6", "outcome", 250, 260)],  # match; spurious
        "edges": [{"source": "p1", "target": "p2", "relation": "relevant_to"},  # endpoint unmatched strictly
                  {"source": "p5", "target": "p3", "relation": "supports"}]}


def test_each_error_gets_exactly_one_bucket():
    pair = UnitPair("u1", "immigration", PRED, GOLD, IDX)
    res = evaluate([pair], 0.3)["_results"]["u1"]
    errs = bucket_errors(pair, res)
    got = {(e["side"], e["item"], e["label"] if e["item"] == "node" else e["type"], e["bucket"]) for e in errs}
    assert ("FP", "node", "x", "wrong_type") in got
    nodes = {(e["side"], e["type"]): e["bucket"] for e in errs if e["item"] == "node"}
    assert nodes[("FP", "holding")] == "wrong_type" and nodes[("FN", "issue")] == "wrong_type"
    assert nodes[("FP", "rule")] == "granularity" and nodes[("FN", "rule")] == "granularity"
    assert nodes[("FP", "reasoning")] == "quote_miss" and nodes[("FP", "outcome")] == "spurious"
    assert nodes[("FN", "reasoning")] == "missed"
    edges = {(e["side"], e["type"]): e["bucket"] for e in errs if e["item"] == "edge"}
    assert edges[("FN", "relevant_to")] == "endpoint_missed" and edges[("FN", "supports")] == "endpoint_missed"
    assert edges[("FN", "applies_rule")] == "endpoint_missed" and edges[("FP", "supports")] == "spurious"
    assert all(e["bucket"] in BUCKETS for e in errs)


def test_summarize_and_markdown():
    pair = UnitPair("u1", "immigration", PRED, GOLD, IDX)
    r = evaluate([pair], 0.3)
    s = summarize(bucket_errors(pair, r["_results"]["u1"]), examples=2)
    assert s["counts"]["node"]["wrong_type"] == 2 and len(s["examples"]["wrong_type"]) == 2
    md = render_markdown({"headline": {k: v for k, v in r.items() if not k.startswith("_")}, "sweep": [],
                          "mapped": {}, "errors": s, "cost": {"requests": 5}, "scored_units": 1,
                          "excluded_units": ["a"], "threshold": 0.3, "model": "m", "prompt_versions": {}})
    assert "| nodes_strict |" in md and "## Error analysis" in md and "wrong_type" in md and "a" in md
