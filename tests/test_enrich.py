import json

from fakes import FakeClient
from lisa.common.config import load_dataset
from lisa.extract.enrich import Enricher, SYS_CASE
from lisa.graph.loader import load_records
from lisa.llm.budget import RunStats

PEREIRA_Q = "Under Pereira v. Sessions, 585 U. S. 198 (2018), the notice was defective"


def make(mini_data, graph_all, responder):
    recs, _ = load_records(mini_data, load_dataset("all"))
    return Enricher(recs, graph_all, FakeClient(responder), RunStats())


def test_treatment_verified_quote_becomes_spec_edge(mini_data, graph_all):
    def reply(msgs):
        if "Pereira" in msgs[1]["content"].split("\n")[1]:
            return json.dumps({"treatment": "follows", "confidence": 0.9, "quote": PEREIRA_Q, "page": 2})
        return json.dumps({"treatment": "distinguishes", "confidence": 0.8, "quote": "not on any page at all", "page": 1})
    en = make(mini_data, graph_all, reply)
    pairs = en.treatment_pairs()
    assert {(e["source"], e["target"]) for e in pairs} == {("eoir_1", "eoir_2"), ("eoir_1", "scotus_2017_17-459")}
    for e in pairs:
        en.treat(e)
    out = en.to_json("all")
    assert [(e["type"], e["target"], e["provenance"]) for e in out["edges"]] == [("FOLLOWS", "scotus_2017_17-459", "llm")]
    assert out["edges"][0]["evidence"][0] == {"page": 2, "quote": PEREIRA_Q, "verified": True}
    assert out["edges"][0]["props"]["scope"] == "cross_domain"
    assert en.dropped["treatment_unverified_quote"] == 1


def test_plain_cites_adds_nothing(mini_data, graph_all):
    en = make(mini_data, graph_all, lambda m: json.dumps({"treatment": "cites", "quote": PEREIRA_Q, "page": 2}))
    for e in en.treatment_pairs():
        en.treat(e)
    assert en.to_json("all")["edges"] == [] and en.dropped["treatment_cites"] == 2


def test_case_meta_doctrines_and_author_need_verified_quotes(mini_data, graph_all):
    def reply(msgs):
        assert msgs[0]["content"] == SYS_CASE
        return json.dumps({"doctrines": [
            {"name": "Stop-Time  Rule", "quote": PEREIRA_Q, "page": 2},
            {"name": "invented doctrine", "quote": "this sentence is nowhere in the case", "page": 1}],
            "author": {"name": "Judge Alpha", "quote": "In re ALPHA. We follow Matter of Beta", "page": 1}})
    en = make(mini_data, graph_all, reply)
    en.case_meta("eoir_1")
    out = en.to_json("all")
    assert {n["id"] for n in out["nodes"]} == {"doctrine:stop_time_rule", "judge:bia:alpha"}
    assert {(e["type"], e["target"]) for e in out["edges"]} == {("INVOKES_DOCTRINE", "doctrine:stop_time_rule"),
                                                               ("AUTHORED_BY", "judge:bia:alpha")}
    assert en.dropped["doctrine_unverified_quote"] == 1


def test_author_quote_must_contain_the_name(mini_data, graph_all):
    en = make(mini_data, graph_all, lambda m: json.dumps(
        {"doctrines": [], "author": {"name": "Justice Nobody", "quote": PEREIRA_Q, "page": 2}}))
    en.case_meta("eoir_1")
    assert en.to_json("all")["nodes"] == [] and en.dropped["author_unverified"] == 1
