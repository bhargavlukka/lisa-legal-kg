"""In-process graph store over the neutral graph JSON (deterministic tier + LLM tier merged).

Same public interface as the Neo4j backend (lisa.store.neo4j_store); every method returns plain JSON-able data
so the MCP servers stay backend-agnostic.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from pathlib import Path

from lisa.graph.canon import canon, squash
from lisa.store.text import BM25, snippet, tokens

CITATION_EDGES = ("CITES", "FOLLOWS", "DISTINGUISHES", "OVERRULES", "CITES_LLM")
STATUS = "not verified; may have subsequent treatment"


def _edge_view(e: dict, other: dict | None, direction: str) -> dict:
    return {"type": e["type"], "direction": direction,
            "case_id" if other and other["label"] == "Case" else "authority_id": e["target" if direction == "out" else "source"],
            "title": (other or {}).get("props", {}).get("title") or (other or {}).get("props", {}).get("display"),
            "citation": (other or {}).get("props", {}).get("citation") or (other or {}).get("props", {}).get("display"),
            "domain": (other or {}).get("props", {}).get("domain"),
            "scope": e["props"].get("scope"), "bases": e["props"].get("bases"),
            "provenance": e["provenance"], "confidence": e["confidence"], "evidence": e["evidence"][:2]}


class MemoryStore:
    backend = "memory"

    def __init__(self, graphs: list[dict]):
        self.nodes: dict[str, dict] = {}
        self.out: dict[str, list[dict]] = defaultdict(list)
        self.inc: dict[str, list[dict]] = defaultdict(list)
        self.edges: list[dict] = []
        seen: set[tuple] = set()
        for g in graphs:                                   # deterministic graph first: its nodes win on id clashes
            for n in g["nodes"]:
                self.nodes.setdefault(n["id"], n)
            for e in g["edges"]:
                key = (e["type"], e["source"], e["target"])
                if key in seen or e["source"] not in self.nodes or e["target"] not in self.nodes:
                    continue
                seen.add(key)
                self.edges.append(e)
                self.out[e["source"]].append(e)
                self.inc[e["target"]].append(e)
        self.cases = sorted((n for n in self.nodes.values() if n["label"] == "Case"), key=lambda n: n["id"])
        self.pages: dict[str, dict[int, str]] = defaultdict(dict)
        for n in self.nodes.values():
            if n["label"] == "Page":
                self.pages[n["props"]["case_id"]][n["props"]["page_no"]] = n["props"]["text"]
        self.by_cite = {n["props"]["canon_cite"]: n["id"] for n in self.cases if n["props"].get("canon_cite")}
        self._page_keys = [(cid, p) for cid in sorted(self.pages) for p in sorted(self.pages[cid])]
        self._page_bm25 = BM25([self.pages[c][p] for c, p in self._page_keys])
        self._case_bm25 = BM25([self._case_doc(n) for n in self.cases])

    @classmethod
    def from_files(cls, paths: list[Path]) -> "MemoryStore":
        return cls([json.loads(Path(p).read_text(encoding="utf-8")) for p in paths if Path(p).exists()])

    # ---------- lookup ----------
    @staticmethod
    def _case_doc(n: dict) -> str:
        p = n["props"]
        return " ".join(str(p.get(k) or "") for k in ("title", "title", "title", "citation", "docket_number",
                                                     "publisher_description", "index_label"))

    def resolve(self, ref: str) -> str | None:
        """Case id from an id, a reporter citation, or a case name; None when not in the corpus."""
        ref = squash(ref or "")
        if not ref:
            return None
        if ref in self.nodes and self.nodes[ref]["label"] == "Case":
            return ref
        c = canon(ref)
        if c.id in self.by_cite:
            return self.by_cite[c.id]
        if c.kind == "case" and not c.id.startswith("other:"):
            return None                                     # a well-formed citation that is not in the corpus
        name = re.sub(r"^(in re|matter of)\s+", "", ref.lower()).strip(" ,.")
        for n in self.cases:
            title = n["props"].get("title", "").lower()
            t = re.sub(r"^(in re|matter of)\s+", "", title)
            if name and (name == t or name == title or (len(name) > 5 and (name in title or t.startswith(name)))):
                return n["id"]
        return None

    def case_summary(self, cid: str) -> dict:
        p = self.nodes[cid]["props"]
        return {"case_id": cid, "title": p.get("title"), "citation": p.get("citation"), "domain": p.get("domain"),
                "court": p.get("court"), "decision_date": p.get("decision_date"), "legal_status": STATUS}

    # ---------- graph-server operations ----------
    def search_cases(self, query: str, domain: str | None = None, limit: int = 10) -> list[dict]:
        direct = self.resolve(query)
        meta = self._case_bm25.score(query)
        text: dict[str, float] = defaultdict(float)
        best_page: dict[str, int] = {}
        for (cid, page), s in zip(self._page_keys, self._page_bm25.score(query)):
            if s > text[cid]:
                text[cid], best_page[cid] = s, page
        scored = []
        for n, m in zip(self.cases, meta):
            cid = n["id"]
            if domain and n["props"].get("domain") != domain:
                continue
            s = 2.0 * m + text.get(cid, 0.0) + (100.0 if cid == direct else 0.0)
            if s > 0:
                scored.append((s, cid))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out = []
        for s, cid in scored[:limit]:
            hit = self.case_summary(cid) | {"score": round(s, 3)}
            if cid in best_page:
                hit["best_page"] = best_page[cid]
                hit["snippet"] = snippet(self.pages[cid][best_page[cid]], query)
            out.append(hit)
        return out

    def search_pages(self, query: str, case_id: str | None = None, limit: int = 8) -> list[dict]:
        scored = [(s, k) for k, s in zip(self._page_keys, self._page_bm25.score(query))
                  if s > 0 and (case_id is None or k[0] == case_id)]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [{"case_id": c, "page": p, "score": round(s, 3), "title": self.nodes[c]["props"].get("title"),
                 "snippet": snippet(self.pages[c][p], query, 400)} for s, (c, p) in scored[:limit]]

    def get_case(self, cid: str) -> dict | None:
        if cid not in self.nodes or self.nodes[cid]["label"] != "Case":
            return None
        n = self.nodes[cid]
        keep = ("title", "citation", "domain", "court", "decision_date", "decision_year", "docket_number", "term",
                "document_type", "publisher_description", "source_url", "sha256", "page_count",
                "precedent_status_at_publication", "current_legal_status")
        out = {"case_id": cid, **{k: n["props"].get(k) for k in keep if n["props"].get(k) is not None},
               "legal_status": STATUS, "provenance": n["provenance"]}
        out["pages"] = sorted(self.pages.get(cid, {}))
        statutes = [(e["props"].get("count", 1), e["target"]) for e in self.out[cid] if e["type"] == "MENTIONS_STATUTE"]
        out["statutes"] = [{"id": t, "display": self.nodes[t]["props"].get("display"), "mentions": c}
                           for c, t in sorted(statutes, key=lambda x: (-x[0], x[1]))[:15]]
        out["doctrines"] = [{"id": e["target"], "label": self.nodes[e["target"]]["props"].get("name")
                             or self.nodes[e["target"]]["props"].get("label"), "provenance": e["provenance"],
                             "confidence": e["confidence"]}
                            for e in self.out[cid] if e["type"] == "INVOKES_DOCTRINE"]
        out["judges"] = [{"id": e["target"], "name": self.nodes[e["target"]]["props"].get("name"),
                          "part": e["props"].get("part"), "provenance": e["provenance"]}
                         for e in self.out[cid] if e["type"] == "AUTHORED_BY"]
        out["cites_count"] = sum(1 for e in self.out[cid] if e["type"] in CITATION_EDGES)
        out["cited_by_count"] = sum(1 for e in self.inc[cid] if e["type"] in CITATION_EDGES)
        return out

    def get_page(self, cid: str, page: int) -> str | None:
        return self.pages.get(cid, {}).get(page)

    def find_citing(self, cid: str) -> list[dict]:
        return [_edge_view(e, self.nodes.get(e["source"]), "in") | {"case_id": e["source"]}
                for e in sorted(self.inc[cid], key=lambda e: (e["source"], e["type"])) if e["type"] in CITATION_EDGES]

    def find_cited(self, cid: str, in_corpus_only: bool = False) -> list[dict]:
        out = []
        for e in sorted(self.out[cid], key=lambda e: (e["target"], e["type"])):
            if e["type"] not in CITATION_EDGES:
                continue
            tgt = self.nodes.get(e["target"])
            if in_corpus_only and tgt["label"] != "Case":
                continue
            out.append(_edge_view(e, tgt, "out"))
        return out

    def precedent_chain(self, cid: str, max_depth: int = 3, to_domain: str | None = "litigation") -> list[dict]:
        """Shortest citation paths from `cid` to in-corpus cases of `to_domain` (or all reachable cases)."""
        prev: dict[str, tuple[str, dict] | None] = {cid: None}
        depth = {cid: 0}
        q = deque([cid])
        while q:
            u = q.popleft()
            if depth[u] >= max_depth:
                continue
            for e in sorted(self.out[u], key=lambda e: (e["target"], e["type"])):
                v = e["target"]
                if e["type"] in CITATION_EDGES and v not in prev and self.nodes[v]["label"] == "Case":
                    prev[v], depth[v] = (u, e), depth[u] + 1
                    q.append(v)
        chains = []
        for v in sorted(prev, key=lambda x: (depth[x], x)):
            if v == cid or (to_domain and self.nodes[v]["props"].get("domain") != to_domain):
                continue
            hops, w = [], v
            while prev[w] is not None:
                u, e = prev[w]
                hops.append({"from": u, "to": w, "type": e["type"], "provenance": e["provenance"],
                             "confidence": e["confidence"], "evidence": e["evidence"][:1]})
                w = u
            hops.reverse()
            chains.append({"target": self.case_summary(v), "depth": depth[v], "hops": hops})
        return chains

    # ---------- analytics snapshot ----------
    def snapshot(self) -> tuple[dict[str, dict], list[dict]]:
        """(nodes without Page text, edges without HAS_PAGE) for analytics."""
        nodes = {k: v for k, v in self.nodes.items() if v["label"] != "Page"}
        return nodes, [e for e in self.edges if e["type"] != "HAS_PAGE"]

    def stats(self) -> dict:
        from collections import Counter
        return {"backend": self.backend, "nodes": dict(Counter(n["label"] for n in self.nodes.values())),
                "edges": dict(Counter(e["type"] for e in self.edges)),
                "provenance": dict(Counter(e["provenance"] for e in self.edges))}


def tokens_overlap(a: str, b: str) -> float:
    ta, tb = set(tokens(a)), set(tokens(b))
    return len(ta & tb) / len(ta) if ta else 0.0
