"""Deterministic mapping from the gold-schema LLM tier to the spec tier, joined to Phase 1 node ids.

relies_on + stance follows/distinguishes/overrules -> FOLLOWS/DISTINGUISHES/OVERRULES (case -> Case or Authority)
other relies_on stances on case authorities        -> CITES_LLM (props.treatment)
opinion.author                                     -> Judge + AUTHORED_BY (props.part)
rule                                               -> Doctrine + INVOKES_DOCTRINE (id from attrs.doctrine or label)"""
from __future__ import annotations

import re

from lisa.extract.stage_nodes import slug
from lisa.graph.canon import canon
from lisa.graph.loader import Record

EXTRACTOR = "lisa.extract.mapping/1"
STANCE_EDGE = {"follows": "FOLLOWS", "distinguishes": "DISTINGUISHES", "overrules": "OVERRULES"}
MAX_EVIDENCE = 3
_TITLES = {"j", "jj", "c", "chief", "justice", "board", "member", "judge", "appellate", "immigration", "acting",
           "vice", "chairman", "chair", "deputy", "senior", "temporary"}


def surname(author: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z'’\-]*", author) if w.lower().strip(".") not in _TITLES]
    return words[-1].title() if words else author.strip().title()


def judge_id(court: str | None, author: str) -> str:
    return f"judge:{slug(court or 'unknown', 30)}:{slug(surname(author), 30)}"


class _G:
    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}

    def node(self, nid: str, label: str, props: dict) -> None:
        self.nodes.setdefault(nid, {"id": nid, "label": label, "props": props, "provenance": "llm",
                                    "confidence": 1.0, "evidence": [], "extractor": EXTRACTOR})

    def edge(self, etype, src, tgt, item: dict, unit_id: str, props: dict | None = None) -> None:
        e = self.edges.setdefault((etype, src, tgt), {
            "type": etype, "source": src, "target": tgt, "props": {}, "provenance": "unverified",
            "confidence": 0.0, "evidence": [], "extractor": EXTRACTOR})
        for k, v in (props or {}).items():
            if v not in e["props"].setdefault(k, []):
                e["props"][k].append(v)
        if item.get("provenance", "llm") == "llm":
            e["provenance"] = "llm"
        e["confidence"] = max(e["confidence"], float(item.get("confidence") or 0.0))
        for ev in item.get("evidence") or []:
            x = {"page": ev.get("page"), "quote": ev.get("quote"), "unit_id": unit_id}
            if x not in e["evidence"] and len(e["evidence"]) < MAX_EVIDENCE:
                e["evidence"].append(x)

    def to_json(self) -> dict:
        return {"extractor": EXTRACTOR, "nodes": [self.nodes[k] for k in sorted(self.nodes)],
                "edges": [self.edges[k] for k in sorted(self.edges)]}


def map_units(units: list[dict], records: list[Record], include_unverified: bool = False) -> dict:
    own = {canon(r.citation).id: r.id for r in records if r.citation}
    court = {r.id: r.props.get("court") for r in records}
    g = _G()

    def ok(item: dict) -> bool:
        return include_unverified or item.get("provenance", "llm") == "llm"

    for u in sorted(units, key=lambda u: u["unit_id"]):
        case, uid = u["case_id"], u["unit_id"]
        nodes = {n["id"]: n for n in u["nodes"]}
        for n in sorted(nodes.values(), key=lambda n: n["id"]):
            if not ok(n):
                continue
            attrs = n.get("attrs") or {}
            author = n.get("author") or attrs.get("author")
            if n["type"] == "opinion" and author:
                jid = judge_id(court.get(case), author)
                g.node(jid, "Judge", {"name": surname(author), "court": court.get(case)})
                g.edge("AUTHORED_BY", case, jid, n, uid, {"part": n.get("part")})
            elif n["type"] == "rule":
                name = re.sub(r"\s+", " ", str(attrs.get("doctrine") or n["label"])).strip().lower()
                did = f"doctrine:{slug(name)}"
                g.node(did, "Doctrine", {"name": name})
                g.edge("INVOKES_DOCTRINE", case, did, n, uid)
        for e in u["edges"]:
            tgt = nodes.get(e["target"])
            if e["relation"] != "relies_on" or not ok(e) or not tgt or tgt["type"] != "authority_ref":
                continue
            attrs = tgt.get("attrs") or {}
            if attrs.get("kind") != "case" or not attrs.get("cite_string"):
                continue
            c = canon(attrs["cite_string"])
            if c.id in own:
                tid = own[c.id]
            else:
                tid = f"auth:{c.id}"
                g.node(tid, "Authority", {"canon_id": c.id, "display": c.display, "kind": "case",
                                          "in_corpus": False, "resolved": False})
            if tid == case:
                continue
            stance = e.get("stance") or "relies_on"
            etype = STANCE_EDGE.get(stance, "CITES_LLM")
            g.edge(etype, case, tid, e, uid, {"treatment": stance} if etype == "CITES_LLM" else None)
    return g.to_json()
