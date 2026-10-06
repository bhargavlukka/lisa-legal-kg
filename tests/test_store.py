from lisa.store.memory import MemoryStore
from lisa.tools.analytics import Analytics, pagerank

LLM = {"nodes": [{"id": "doctrine:stop_time", "label": "Doctrine", "props": {"name": "stop-time rule"},
                  "provenance": "llm", "confidence": 0.9, "evidence": []},
                 {"id": "eoir_1", "label": "Case", "props": {"title": "SHADOW"}, "provenance": "llm",
                  "confidence": 0.1, "evidence": []}],
       "edges": [{"type": "INVOKES_DOCTRINE", "source": "eoir_1", "target": "doctrine:stop_time", "props": {},
                  "provenance": "llm", "confidence": 0.9, "evidence": [{"page": 2, "quote": "q"}]},
                 {"type": "FOLLOWS", "source": "eoir_1", "target": "eoir_2", "props": {"scope": "internal"},
                  "provenance": "llm", "confidence": 0.8, "evidence": []},
                 {"type": "FOLLOWS", "source": "eoir_1", "target": "missing_node", "props": {},
                  "provenance": "llm", "confidence": 0.8, "evidence": []}]}


def test_merge_keeps_deterministic_nodes_and_drops_dangling_edges(graph_all):
    s = MemoryStore([graph_all, LLM])
    assert s.nodes["eoir_1"]["props"]["title"] == "ALPHA"          # deterministic node wins
    assert "doctrine:stop_time" in s.nodes
    assert not any(e["target"] == "missing_node" for e in s.edges)


def test_resolve_by_id_citation_and_name(graph_all):
    s = MemoryStore([graph_all])
    assert s.resolve("eoir_1") == "eoir_1"
    assert s.resolve("22 I&N\nDec. 200") == "eoir_2"
    assert s.resolve("585 U. S. 198") == "scotus_2017_17-459"
    assert s.resolve("Pereira v. Sessions") == "scotus_2017_17-459"
    assert s.resolve("Matter of Alpha") == "eoir_1"
    assert s.resolve("999 U.S. 1") is None                       # well-formed but not in corpus
    assert s.resolve("") is None


def test_search_cases_ranks_direct_hit_first_and_filters_domain(graph_all):
    s = MemoryStore([graph_all])
    assert s.search_cases("Pereira v. Sessions")[0]["case_id"] == "scotus_2017_17-459"
    hits = s.search_cases("notice defective", domain="immigration")
    assert hits and all(h["domain"] == "immigration" for h in hits)
    assert hits[0]["case_id"] == "eoir_1" and hits[0]["best_page"] == 2


def test_get_case_and_pages(graph_all):
    s = MemoryStore([graph_all, LLM])
    c = s.get_case("eoir_1")
    assert c["pages"] == [1, 2] and c["legal_status"].startswith("not verified")
    assert {x["id"] for x in c["statutes"]} >= {"usc:8_1182"}
    assert c["doctrines"][0]["label"] == "stop-time rule"
    assert s.get_case("auth:in_dec:19_546") is None
    assert "Pereira" in s.get_page("eoir_1", 2)
    assert s.get_page("eoir_1", 9) is None


def test_citing_cited_and_chain(graph_all):
    s = MemoryStore([graph_all, LLM])
    citing = s.find_citing("scotus_2017_17-459")
    assert [c["case_id"] for c in citing] == ["eoir_1"] and citing[0]["scope"] == "cross_domain"
    cited = s.find_cited("eoir_1", in_corpus_only=True)
    assert {(c.get("case_id"), c["type"]) for c in cited} >= {("eoir_2", "CITES"), ("eoir_2", "FOLLOWS")}
    chains = s.precedent_chain("eoir_1")
    assert [c["target"]["case_id"] for c in chains] == ["scotus_2017_17-459"]
    assert chains[0]["hops"][0]["from"] == "eoir_1"
    assert {c["target"]["case_id"] for c in s.precedent_chain("eoir_1", to_domain=None)} == {"eoir_2", "scotus_2017_17-459"}


def test_pagerank_sums_to_one_and_ranks_sink_highest():
    pr = pagerank(["a", "b", "c"], [("a", "c"), ("b", "c")])
    assert abs(sum(pr.values()) - 1) < 1e-9 and max(pr, key=pr.get) == "c"


def test_analytics(graph_all):
    a = Analytics(MemoryStore([graph_all, LLM]))
    top = a.most_cited(5, scope="in_corpus")
    assert {r["id"] for r in top} == {"eoir_2", "scotus_2017_17-459"}
    assert a.statute_frequency(3)[0]["cases"] >= 1
    assert a.statute_frequency(10, domain="litigation")[0]["id"] == "usc:28_1253"
    b = a.cross_corpus_bridges()
    assert b["unique_pairs"] == 1 and b["bridges"][0]["id"] == "scotus_2017_17-459"
    assert set(b["bridges"][0]["citing_cases"][0]["bases"]) == {"name", "reporter"}
    d = a.doctrine_influence()
    assert d[0]["doctrine"] == "stop-time rule" and d[0]["cases"] == ["eoir_1"]
