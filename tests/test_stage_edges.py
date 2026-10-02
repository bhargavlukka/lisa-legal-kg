import json
import re

from fakes import FakeClient
from lisa.extract.stage_edges import catalog, extract_edges, plan_calls
from lisa.extract.units import Segment, Unit, UnitPage
from lisa.llm.budget import RunStats

TEXTS = {1: "The majority holds that the waiver under section 212(h) is unavailable to this respondent.",
         2: "The respondent relies on Matter of Michel, 21 I&N Dec. 1101, which we distinguish today.",
         3: "Board Member Rosenberg dissents because the statute plainly allows this waiver here."}
SEGS = (Segment("c#s0", "majority", "Jones", 1, 0, 3, 0), Segment("c#s1", "dissent", "Rosenberg", 3, 0, 3, 90))
UNIT = Unit("c__u1of1", "c", "immigration", "CASE_ID: c\n", tuple(UnitPage(i, None, t) for i, t in TEXTS.items()),
            dict(TEXTS), SEGS, None)


def n(id_, type_, part, page):
    return {"id": id_, "type": type_, "label": id_, "part": part,
            "evidence": [{"page": page, "quote": TEXTS[page][:40], "verified": True}]}


NODES = [n("c:reasoning:r", "reasoning", "majority", 1), n("c:holding:h", "holding", "majority", 1),
         n("c:authority_ref:michel", "authority_ref", "majority", 2), n("c:holding:d", "holding", "dissent", 3)]


def edge(src, tgt, rel, page, **kw):
    return {"source": src, "target": tgt, "relation": rel, "evidence": [{"page": page, "quote": TEXTS[page][:45]}],
            "confidence": 0.8, **kw}


GOOD = [edge("c:reasoning:r", "c:holding:h", "supports", 1),
        edge("c:reasoning:r", "c:authority_ref:michel", "relies_on", 2, stance="distinguishes"),
        edge("c:holding:d", "c:holding:h", "disagrees_with", 3)]


def test_catalog_shape():
    assert catalog(NODES)[2] == {"id": "c:authority_ref:michel", "type": "authority_ref",
                                 "label": "c:authority_ref:michel", "part": "majority", "pages": [2]}


def test_plan_single_call_when_small():
    [(pages, nodes, sources)] = plan_calls(UNIT, NODES, 60000)
    assert len(pages) == 3 and len(nodes) == 4 and sources is None


def test_plan_splits_per_part_when_large():
    calls = plan_calls(UNIT, NODES, 10)
    assert [[p.page for p in c[0]] for c in calls] == [[1, 2, 3], [3]]
    assert calls[0][2] == ["c:reasoning:r", "c:holding:h", "c:authority_ref:michel"]
    assert calls[1][2] == ["c:holding:d"]
    assert {x["id"] for x in calls[1][1]} == {"c:holding:d", "c:holding:h", "c:authority_ref:michel"}


def test_extract_edges_verified_and_typed():
    stats = RunStats()
    out = extract_edges(UNIT, NODES, FakeClient(lambda m: json.dumps({"edges": GOOD})), "S", "edges-v1", 60000, stats)
    assert [(e["relation"], e["stance"]) for e in out] == [("supports", None), ("relies_on", "distinguishes"),
                                                          ("disagrees_with", None)]
    assert all(e["provenance"] == "llm" and e["case_id"] == "c" for e in out)
    assert out[0]["part"] == "majority" and stats.schema_rejects == []


def test_edges_drop_unknown_ids_and_bad_signatures():
    bad = GOOD + [edge("c:ghost", "c:holding:h", "supports", 1),
                  edge("c:holding:h", "c:reasoning:r", "supports", 1),
                  GOOD[0]]   # duplicate
    stats = RunStats()
    out = extract_edges(UNIT, NODES, FakeClient(lambda m: json.dumps({"edges": bad})), "S", "v", 60000, stats)
    assert len(out) == 3
    assert [r["reason"] for r in stats.schema_rejects] == ["unknown node id: c:ghost",
                                                           "disallowed signature: holding -supports-> reasoning"]


def test_edges_outside_source_set_are_rejected_in_split_mode():
    stats = RunStats()
    out = extract_edges(UNIT, NODES, FakeClient(lambda m: json.dumps({"edges": GOOD})), "S", "v", 10, stats)
    assert sorted(e["relation"] for e in out) == ["disagrees_with", "relies_on", "supports"]
    assert sum(r["reason"] == "source not in this request" for r in stats.schema_rejects) == 3


def test_truncation_halves_source_ids():
    def responder(messages):
        user = messages[-1]["content"]
        if "SOURCE NODES: all" in user:
            return ("{", "length")
        ids = json.loads(re.search(r"SOURCE NODES: (\[.*\])", user).group(1))
        return json.dumps({"edges": [e for e in GOOD if e["source"] in ids]})
    fc, stats = FakeClient(responder), RunStats()
    out = extract_edges(UNIT, NODES, fc, "S", "v", 60000, stats)
    assert len(out) == 3 and len(fc.calls) == 3 and stats.failed == []
