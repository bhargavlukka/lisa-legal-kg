from lisa.extract.mapping import judge_id, map_units, surname
from lisa.graph.loader import Record

RECS = [Record("eoir_1", "immigration", "ALPHA", "22 I&N Dec. 100", {"court": "BIA"}, [], "", []),
        Record("eoir_2", "immigration", "BETA", "22 I&N Dec. 200", {"court": "BIA"}, [], "", [])]
EV = [{"page": 1, "quote": "We follow Matter of Beta", "verified": True}]


def nd(id_, type_, prov="llm", **kw):
    return {"id": id_, "type": type_, "label": kw.pop("label", id_), "part": kw.pop("part", "majority"),
            "author": kw.pop("author", None), "evidence": EV, "attrs": kw.pop("attrs", {}), "provenance": prov,
            "confidence": 0.9, **kw}


def ed(src, tgt, stance, prov="llm"):
    return {"source": src, "target": tgt, "relation": "relies_on", "stance": stance, "evidence": EV,
            "provenance": prov, "confidence": 0.8}


def unit(nodes, edges):
    return {"unit_id": "eoir_1__u1of1", "case_id": "eoir_1", "nodes": nodes, "edges": edges}


def by_type(g, t):
    return {(e["source"], e["target"]): e for e in g["edges"] if e["type"] == t}


def test_surname_and_judge_id():
    assert surname("Kennedy, J.") == "Kennedy"
    assert surname("Lory Diana Rosenberg, Board Member") == "Rosenberg"
    assert judge_id("BIA", "JONES") == "judge:bia:jones"
    assert judge_id(None, "Thomas") == "judge:unknown:thomas"


def test_stance_edges_resolve_in_corpus_and_external():
    nodes = [nd("r", "reasoning"),
             nd("a1", "authority_ref", attrs={"cite_string": "Matter of Beta, 22 I&N Dec. 200", "kind": "case"}),
             nd("a2", "authority_ref", attrs={"cite_string": "Pereira v. Sessions, 585 U.S. 198", "kind": "case"}),
             nd("a3", "authority_ref", attrs={"cite_string": "Old case, 9 I&N Dec. 1", "kind": "case"}),
             nd("s", "authority_ref", attrs={"cite_string": "8 U.S.C. § 1182(h)", "kind": "statute"})]
    edges = [ed("r", "a1", "follows"), ed("r", "a2", "distinguishes"), ed("r", "a3", "overrules"),
             ed("r", "s", "follows"), ed("r", "a2", "cites_without_treatment")]
    g = map_units([unit(nodes, edges)], RECS)
    assert set(by_type(g, "FOLLOWS")) == {("eoir_1", "eoir_2")}
    assert set(by_type(g, "DISTINGUISHES")) == {("eoir_1", "auth:us:585_198")}
    assert set(by_type(g, "OVERRULES")) == {("eoir_1", "auth:in_dec:9_1")}
    cites = by_type(g, "CITES_LLM")
    assert cites[("eoir_1", "auth:us:585_198")]["props"]["treatment"] == ["cites_without_treatment"]
    auth = {n["id"]: n for n in g["nodes"] if n["label"] == "Authority"}
    assert set(auth) == {"auth:us:585_198", "auth:in_dec:9_1"}
    assert auth["auth:us:585_198"]["props"]["kind"] == "case"
    f = by_type(g, "FOLLOWS")[("eoir_1", "eoir_2")]
    assert f["provenance"] == "llm" and f["evidence"][0]["quote"] == "We follow Matter of Beta"
    assert f["evidence"][0]["unit_id"] == "eoir_1__u1of1" and f["extractor"] == "lisa.extract.mapping/1"


def test_self_citation_is_skipped():
    nodes = [nd("r", "reasoning"),
             nd("a", "authority_ref", attrs={"cite_string": "22 I&N Dec. 100", "kind": "case"})]
    assert map_units([unit(nodes, [ed("r", "a", "follows")])], RECS)["edges"] == []


def test_judges_and_doctrines_merge_across_units():
    u1 = unit([nd("o", "opinion", author="Jones", part="dissent"),
               nd("k", "rule", label="Categorical approach rule", attrs={"doctrine": "Categorical Approach"})], [])
    u2 = {"unit_id": "eoir_2__u1of1", "case_id": "eoir_2",
          "nodes": [nd("k2", "rule", label="Categorical approach", attrs={})], "edges": []}
    g = map_units([u1, u2], RECS)
    ab = by_type(g, "AUTHORED_BY")
    assert ab[("eoir_1", "judge:bia:jones")]["props"]["part"] == ["dissent"]
    inv = by_type(g, "INVOKES_DOCTRINE")
    assert set(inv) == {("eoir_1", "doctrine:categorical_approach"), ("eoir_2", "doctrine:categorical_approach")}
    doc = [n for n in g["nodes"] if n["label"] == "Doctrine"]
    assert len(doc) == 1 and doc[0]["props"]["name"] == "categorical approach"


def test_unverified_excluded_unless_asked_and_gold_counts_as_verified():
    nodes = [nd("o", "opinion", prov="unverified", author="Jones")]
    assert map_units([unit(nodes, [])], RECS)["edges"] == []
    assert len(map_units([unit(nodes, [])], RECS, include_unverified=True)["edges"]) == 1
    gold = unit([{k: v for k, v in nd("o", "opinion", author="Jones").items() if k != "provenance"}], [])
    assert len(map_units([gold], RECS)["edges"]) == 1


def test_output_is_sorted_and_deterministic():
    nodes = [nd("o", "opinion", author="Jones"), nd("k", "rule", attrs={"doctrine": "x"})]
    a = map_units([unit(nodes, [])], RECS)
    assert a == map_units([unit(list(reversed(nodes)), [])], RECS)
    assert [e["type"] for e in a["edges"]] == ["AUTHORED_BY", "INVOKES_DOCTRINE"]
