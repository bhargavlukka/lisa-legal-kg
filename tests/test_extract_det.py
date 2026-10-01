import json

from conftest import IMM, build_json, edges_of, nodes_of
from lisa.graph.evidence import cite_pattern, find_evidence


def test_case_nodes_carry_metadata_and_unverified_status(graph_all):
    cases = nodes_of(graph_all, "Case")
    assert set(cases) == {"eoir_1", "eoir_2", "scotus_2017_17-459"}
    c = cases["eoir_1"]
    assert c["props"]["canon_cite"] == "in_dec:22_100"
    assert c["props"]["legal_status"] == "not verified"
    assert c["props"]["domain"] == "immigration"
    assert c["props"]["dataset"] == "all"
    assert c["provenance"] == "deterministic" and c["confidence"] == 1.0
    assert c["extractor"] == "lisa.graph.extract_det/1"


def test_pages_are_nodes(graph_all):
    assert set(nodes_of(graph_all, "Page")) == {"eoir_1#p1", "eoir_1#p2", "eoir_2#p1", "scotus_2017_17-459#p1"}
    assert ("eoir_1", "eoir_1#p2") in edges_of(graph_all, "HAS_PAGE")


def test_internal_cite_dedups_whitespace_variants_and_has_verbatim_quote(graph_all):
    e = edges_of(graph_all, "CITES")[("eoir_1", "eoir_2")]
    assert e["props"] == {"scope": "internal", "bases": ["detected_citation"]}
    assert e["provenance"] == "deterministic" and e["confidence"] == 1.0
    assert len(e["evidence"]) == 1
    ev = e["evidence"][0]
    assert ev["page"] == 1
    assert "22 I&N\nDec. 200" in ev["quote"]
    assert ev["quote"] in IMM[0]["pages"][0]["text"]


def test_out_of_corpus_citation_becomes_unverified_authority(graph_all):
    a = nodes_of(graph_all, "Authority")["auth:in_dec:19_546"]
    assert a["props"]["in_corpus"] is False and a["props"]["resolved"] is False
    assert a["props"]["display"] == "19 I&N Dec. 546"
    e = edges_of(graph_all, "CITES")[("eoir_1", "auth:in_dec:19_546")]
    assert e["props"]["scope"] == "external"
    assert e["provenance"] == "unverified" and e["confidence"] == 0.5 and e["evidence"] == []


def test_statute_and_regulation_mentions(graph_all):
    m = edges_of(graph_all, "MENTIONS_STATUTE")
    assert m[("eoir_1", "usc:8_1182")]["props"]["count"] == 2
    assert ("eoir_1", "cfr:8_1003") in m
    assert ("scotus_2017_17-459", "usc:28_1253") in m
    assert ("scotus_2017_17-459", "usc:8_1229") in m
    assert nodes_of(graph_all, "Regulation")["cfr:8_1003"]["props"]["display"] == "8 C.F.R. Part 1003"
    assert m[("eoir_1", "cfr:8_1003")]["evidence"][0]["page"] == 2


def test_statute_citations_are_not_cites_edges(graph_all):
    targets = [t for (_, t) in edges_of(graph_all, "CITES")]
    assert not any(t.startswith(("auth:usc", "auth:cfr")) for t in targets)


def test_edges_know_endpoint_labels(graph_all):
    e = edges_of(graph_all, "CITES")[("eoir_1", "auth:in_dec:19_546")]
    assert (e["source_label"], e["target_label"]) == ("Case", "Authority")


def test_output_is_deterministic(mini_data):
    assert json.dumps(build_json(mini_data, "all")) == json.dumps(build_json(mini_data, "all"))


def test_find_evidence_respects_digit_boundaries():
    pages = [{"page": 1, "text": "see 115 I&N Dec. 7750 and later"},
             {"page": 2, "text": "and 15 I&N\nDec. 775 here"}]
    ev = find_evidence(pages, cite_pattern("15 I&N Dec. 775"))
    assert ev["page"] == 2
    assert "15 I&N\nDec. 775" in ev["quote"]


def test_case_without_citation_gets_placeholder_canon_and_no_self_match():
    from lisa.common.config import load_dataset
    from lisa.graph.extract_det import build_graph
    from lisa.graph.loader import Record
    recs = [Record(id="scotus_2025_x", domain="litigation", title="Hamm v. Smith", citation=None, props={},
                   pages=[{"page": 1, "text": "cites 585 U.S. 198"}], text="cites 585 U.S. 198",
                   citations=["585 U.S. 198"])]
    g = build_graph(recs, load_dataset("all")).to_json()
    case = nodes_of(g, "Case")["scotus_2025_x"]
    assert case["props"]["canon_cite"] == "nocite:scotus_2025_x"
    assert ("scotus_2025_x", "auth:us:585_198") in edges_of(g, "CITES")
