"""Deterministic extraction tier: case metadata, detected citations, statute mentions. No LLM."""
from __future__ import annotations

from lisa.common.config import DatasetConfig
from lisa.graph import crossdomain
from lisa.graph.canon import canon
from lisa.graph.evidence import cite_pattern, find_evidence
from lisa.graph.loader import Record
from lisa.graph.statutes import extract_mentions

EXTRACTOR = "lisa.graph.extract_det/1"
MAX_EVIDENCE = 3
METADATA = {"page": None, "quote": None, "basis": "record_metadata"}


class Graph:
    def __init__(self, dataset: str):
        self.dataset = dataset
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}

    def add_node(self, node_id, label, props, evidence=None, provenance="deterministic", confidence=1.0) -> dict:
        n = self.nodes.get(node_id)
        if n is None:
            n = {"id": node_id, "label": label, "props": props, "provenance": provenance,
                 "confidence": confidence, "evidence": list(evidence or []), "extractor": EXTRACTOR}
            self.nodes[node_id] = n
        elif evidence and n["provenance"] == "unverified":
            n.update(evidence=list(evidence), provenance=provenance, confidence=confidence)
        return n

    def add_edge(self, etype, source, target, *, basis=None, confidence=1.0, evidence=None, props=None) -> dict:
        key = (etype, source, target)
        e = self.edges.get(key)
        if e is None:
            e = {"type": etype, "source": source, "target": target, "props": {},
                 "provenance": "unverified", "confidence": 0.5, "evidence": [], "extractor": EXTRACTOR}
            self.edges[key] = e
        e["props"].update(props or {})
        if basis and basis not in e["props"].setdefault("bases", []):
            e["props"]["bases"].append(basis)
        if evidence:
            if e["provenance"] == "unverified":
                e["provenance"], e["confidence"] = "deterministic", confidence
            else:
                e["confidence"] = max(e["confidence"], confidence)
            if evidence not in e["evidence"] and len(e["evidence"]) < MAX_EVIDENCE:
                e["evidence"].append(evidence)
        return e

    def to_json(self) -> dict:
        edges = []
        for key in sorted(self.edges):
            e = dict(self.edges[key])
            e["source_label"] = self.nodes[e["source"]]["label"]
            e["target_label"] = self.nodes[e["target"]]["label"]
            edges.append(e)
        return {"dataset": self.dataset, "extractor": EXTRACTOR,
                "nodes": [self.nodes[k] for k in sorted(self.nodes)], "edges": edges}


def _canon_id(r: Record) -> str:
    return canon(r.citation).id if r.citation else f"nocite:{r.id}"


def _add_cases_and_pages(g: Graph, records: list[Record], ds: DatasetConfig) -> None:
    for r in records:
        g.add_node(r.id, "Case", {**r.props, "canon_cite": _canon_id(r), "dataset": ds.name,
                                  "domain": r.domain, "legal_status": "not verified"}, evidence=[METADATA])
        for p in r.pages:
            pid = f"{r.id}#p{p['page']}"
            g.add_node(pid, "Page", {"case_id": r.id, "page_no": p["page"], "text": p["text"]}, evidence=[METADATA])
            g.add_edge("HAS_PAGE", r.id, pid, evidence={"page": p["page"], "quote": None})


def _add_citations(g: Graph, records: list[Record]) -> None:
    own = {canon(r.citation).id: r for r in records if r.citation}
    for r in records:
        self_id = _canon_id(r)
        for raw in r.citations:
            c = canon(raw)
            if c.kind != "case" or c.id == self_id:
                continue
            ev = find_evidence(r.pages, cite_pattern(raw))
            if c.id in own:
                target = own[c.id]
                tgt_id, scope = target.id, ("internal" if target.domain == r.domain else "cross_domain")
            else:
                tgt_id, scope = f"auth:{c.id}", "external"
                g.add_node(tgt_id, "Authority",
                           {"canon_id": c.id, "display": c.display, "kind": c.kind,
                            "in_corpus": False, "resolved": False},
                           evidence=[{**ev, "case_id": r.id}] if ev else [],
                           provenance="deterministic" if ev else "unverified",
                           confidence=1.0 if ev else 0.5)
            g.add_edge("CITES", r.id, tgt_id, basis="detected_citation", confidence=1.0, evidence=ev,
                       props={"scope": scope})


def _title_section(canon_id: str) -> dict:
    """usc:8_1182 -> title 8, section 1182; cfr:8_1003 -> title 8, part 1003; ina:245 -> section 245."""
    scheme, _, rest = canon_id.partition(":")
    if scheme == "ina":
        return {"title_no": None, "section": rest}
    title, _, num = rest.partition("_")
    return {"title_no": title, "part" if scheme == "cfr" else "section": num}


def _add_statutes(g: Graph, records: list[Record], ds: DatasetConfig) -> None:
    patterns = {s.domain: s.statute_patterns for s in ds.sources}
    for r in records:
        grouped: dict[str, list] = {}
        for m in extract_mentions(r.pages, patterns[r.domain]):
            grouped.setdefault(m.canon_id, []).append(m)
        for cid, ms in grouped.items():
            label = "Regulation" if ms[0].kind == "regulation" else "Statute"
            g.add_node(cid, label, {"canon_id": cid, "display": ms[0].display, **_title_section(cid)},
                       evidence=[{"case_id": r.id, "page": ms[0].page, "quote": ms[0].quote}])
            for m in ms[:MAX_EVIDENCE]:
                g.add_edge("MENTIONS_STATUTE", r.id, cid, confidence=1.0,
                           evidence={"page": m.page, "quote": m.quote}, props={"count": len(ms)})


def _add_cross_domain(g: Graph, records: list[Record], ds: DatasetConfig) -> None:
    for from_domain, to_domain in ds.cross_domain:
        sources = [r for r in records if r.domain == from_domain]
        targets = [r for r in records if r.domain == to_domain]
        for m in crossdomain.find_matches(sources, targets):
            g.add_edge("CITES", m.source, m.target, basis=m.basis, confidence=crossdomain.CONFIDENCE[m.basis],
                       evidence=m.evidence, props={"scope": "cross_domain"})


def build_graph(records: list[Record], ds: DatasetConfig) -> Graph:
    g = Graph(ds.name)
    _add_cases_and_pages(g, records, ds)
    _add_citations(g, records)
    _add_statutes(g, records, ds)
    _add_cross_domain(g, records, ds)
    return g
