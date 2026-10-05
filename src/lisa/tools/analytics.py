"""Graph analytics over a store snapshot: PageRank precedence, statute frequency, doctrine influence, bridges."""
from __future__ import annotations

from collections import Counter, defaultdict

from lisa.store.memory import CITATION_EDGES


def pagerank(nodes: list[str], edges: list[tuple[str, str]], d: float = 0.85, iters: int = 100,
             tol: float = 1e-10) -> dict[str, float]:
    """Power-iteration PageRank; dangling mass is spread uniformly."""
    n = len(nodes)
    if n == 0:
        return {}
    out: dict[str, list[str]] = defaultdict(list)
    for s, t in edges:
        out[s].append(t)
    pr = {v: 1.0 / n for v in nodes}
    for _ in range(iters):
        dangling = sum(pr[v] for v in nodes if not out[v])
        nxt = {v: (1 - d) / n + d * dangling / n for v in nodes}
        for s in nodes:
            if out[s]:
                share = d * pr[s] / len(out[s])
                for t in out[s]:
                    nxt[t] += share
        delta = sum(abs(nxt[v] - pr[v]) for v in nodes)
        pr = nxt
        if delta < tol:
            break
    return pr


class Analytics:
    def __init__(self, store):
        self.store = store
        self.nodes, self.edges = store.snapshot()

    def _label(self, nid: str) -> dict:
        n = self.nodes[nid]
        p = n["props"]
        return {"id": nid, "kind": n["label"], "title": p.get("title") or p.get("display") or p.get("name"),
                "citation": p.get("citation") or p.get("display"), "domain": p.get("domain"),
                "in_corpus": n["label"] == "Case"}

    def most_cited(self, k: int = 10, scope: str = "all", method: str = "pagerank") -> list[dict]:
        """Top precedents. scope: all | in_corpus. method: pagerank | indegree."""
        cites = [(e["source"], e["target"]) for e in self.edges if e["type"] in CITATION_EDGES]
        keep = {nid for nid, n in self.nodes.items() if n["label"] in ("Case", "Authority")}
        if scope == "in_corpus":
            keep = {nid for nid in keep if self.nodes[nid]["label"] == "Case"}
        cites = [(s, t) for s, t in cites if s in keep and t in keep]
        indeg = Counter(t for _, t in set(cites))
        citers = defaultdict(set)
        for s, t in cites:
            citers[t].add(s)
        pr = pagerank(sorted(keep), sorted(set(cites)))
        key = (lambda v: (-pr[v], -indeg[v], v)) if method == "pagerank" else (lambda v: (-indeg[v], -pr[v], v))
        ranked = sorted((v for v in keep if indeg[v] > 0), key=key)[:k]
        return [self._label(v) | {"rank": i, "cited_by": indeg[v], "pagerank": round(pr[v], 6),
                                  "citing_domains": dict(Counter(self.nodes[s]["props"].get("domain") for s in citers[v]))}
                for i, v in enumerate(ranked, 1)]

    def statute_frequency(self, k: int = 10, domain: str | None = None) -> list[dict]:
        cases, mentions = Counter(), Counter()
        for e in self.edges:
            if e["type"] != "MENTIONS_STATUTE":
                continue
            if domain and self.nodes[e["source"]]["props"].get("domain") != domain:
                continue
            cases[e["target"]] += 1
            mentions[e["target"]] += int(e["props"].get("count", 1))
        ranked = sorted(cases, key=lambda s: (-cases[s], -mentions[s], s))[:k]
        return [{"rank": i, "id": s, "display": self.nodes[s]["props"].get("display"), "kind": self.nodes[s]["label"],
                 "cases": cases[s], "mentions": mentions[s]} for i, s in enumerate(ranked, 1)]

    def doctrine_influence(self, k: int = 10) -> list[dict]:
        """Doctrines (LLM tier) ranked by how many cases invoke them, weighted by those cases' PageRank."""
        cases = [nid for nid, n in self.nodes.items() if n["label"] == "Case"]
        pr = pagerank(cases, [(e["source"], e["target"]) for e in self.edges
                              if e["type"] in CITATION_EDGES and e["target"] in self.nodes
                              and self.nodes[e["target"]]["label"] == "Case"])
        users: dict[str, set] = defaultdict(set)
        conf: dict[str, list] = defaultdict(list)
        for e in self.edges:
            if e["type"] == "INVOKES_DOCTRINE":
                users[e["target"]].add(e["source"])
                conf[e["target"]].append(e["confidence"])
        score = {d: sum(pr.get(c, 0) for c in cs) for d, cs in users.items()}
        ranked = sorted(users, key=lambda d: (-len(users[d]), -score[d], d))[:k]
        return [{"rank": i, "id": d, "doctrine": self.nodes[d]["props"].get("name") or self.nodes[d]["props"].get("label"),
                 "cases": sorted(users[d]), "influence": round(score[d], 6), "provenance": "llm",
                 "mean_confidence": round(sum(conf[d]) / len(conf[d]), 3)} for i, d in enumerate(ranked, 1)]

    def cross_corpus_bridges(self, k: int = 20) -> dict:
        """Cross-domain CITES (BIA -> SCOTUS) grouped by the SCOTUS case they lean on."""
        by_target: dict[str, list] = defaultdict(list)
        for e in self.edges:
            if e["type"] in CITATION_EDGES and e["props"].get("scope") == "cross_domain":
                by_target[e["target"]].append(e)
        ranked = sorted(by_target, key=lambda t: (-len({e["source"] for e in by_target[t]}), t))[:k]
        bridges = []
        for t in ranked:
            es = by_target[t]
            bridges.append(self._label(t) | {
                "citing_cases": [{"case_id": e["source"], "title": self.nodes[e["source"]]["props"].get("title"),
                                  "type": e["type"], "bases": e["props"].get("bases"), "provenance": e["provenance"],
                                  "confidence": e["confidence"]} for e in sorted(es, key=lambda e: e["source"])]})
        pairs = {(e["source"], e["target"]) for es in by_target.values() for e in es}
        return {"unique_pairs": len(pairs), "bridged_scotus_cases": len(by_target), "bridges": bridges}
