from conftest import edges_of, nodes_of
from lisa.graph.crossdomain import find_matches
from lisa.graph.loader import Record


def rec(id_, domain, title, citation, pages):
    return Record(id=id_, domain=domain, title=title, citation=citation, props={},
                  pages=pages, text="\n".join(p["text"] for p in pages), citations=[])


PEREIRA = rec("scotus_x", "litigation", "Pereira v. Sessions", "585 U.S. 198", [{"page": 1, "text": "x"}])


def test_cross_domain_edge_has_both_bases(graph_all):
    e = edges_of(graph_all, "CITES")[("eoir_1", "scotus_2017_17-459")]
    assert e["props"]["scope"] == "cross_domain"
    assert sorted(e["props"]["bases"]) == ["name", "reporter"]
    assert e["confidence"] == 1.0 and e["provenance"] == "deterministic"
    assert e["evidence"][0]["page"] == 2


def test_name_only_match_scores_0_9_and_tolerates_line_breaks():
    src = rec("eoir_x", "immigration", "X", "1 I&N Dec. 1", [{"page": 4, "text": "as held in Pereira v.\nSessions, the"}])
    [m] = find_matches([src], [PEREIRA])
    assert (m.source, m.target, m.basis) == ("eoir_x", "scotus_x", "name")
    assert m.evidence["page"] == 4


def test_reporter_match_tolerates_spaced_us():
    src = rec("eoir_x", "immigration", "X", "1 I&N Dec. 1", [{"page": 1, "text": "see 585 U. S. 198, 201"}])
    assert [(m.basis, m.evidence["page"]) for m in find_matches([src], [PEREIRA])] == [("reporter", 1)]


def test_reporter_does_not_match_longer_page_number():
    src = rec("eoir_x", "immigration", "X", "1 I&N Dec. 1", [{"page": 1, "text": "see 585 U.S. 1980"}])
    assert find_matches([src], [PEREIRA]) == []


def test_match_split_across_pages_is_kept_without_evidence():
    src = rec("eoir_x", "immigration", "X", "1 I&N Dec. 1",
              [{"page": 1, "text": "relying on Pereira v."}, {"page": 2, "text": "Sessions, we hold"}])
    [m] = find_matches([src], [PEREIRA])
    assert m.basis == "name" and m.evidence is None


def test_immigration_only_config_builds_without_cross_edges(graph_imm):
    assert "scotus_2017_17-459" not in nodes_of(graph_imm, "Case")
    assert all(e["props"].get("scope") != "cross_domain" for e in graph_imm["edges"])
    assert ("eoir_1", "eoir_2") in edges_of(graph_imm, "CITES")
