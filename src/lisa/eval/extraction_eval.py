"""Evidence-anchored matching of predicted vs gold extractions, and P/R/F1.

Node score = 0.8 * max span-IoU of located quotes (cited page, +-1) + 0.2 * token-Jaccard(label + summary).
Greedy 1:1 assignment by descending score above the threshold. Edges match when both endpoints matched to the
gold edge's endpoints and (strict) the relation is equal."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from lisa.extract.mapping import map_units
from lisa.extract.verify import PageIndex

W_SPAN, W_TEXT = 0.8, 0.2
SWEEP = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
MAPPED_TYPES = ("FOLLOWS", "DISTINGUISHES", "OVERRULES", "CITES_LLM", "AUTHORED_BY")


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def p(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def r(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        return 2 * self.p * self.r / (self.p + self.r) if self.p + self.r else 0.0

    def add(self, o: "Counts") -> None:
        self.tp, self.fp, self.fn = self.tp + o.tp, self.fp + o.fp, self.fn + o.fn

    def to_json(self) -> dict:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn,
                "p": round(self.p, 4), "r": round(self.r, 4), "f1": round(self.f1, 4)}


@dataclass
class UnitPair:
    unit_id: str
    domain: str
    pred: dict
    gold: dict
    index: PageIndex


def spans(item: dict, index: PageIndex) -> list[tuple[int, int]]:
    out = []
    for e in item.get("evidence") or []:
        page = e.get("page") if isinstance(e.get("page"), int) else None
        sp = index.locate(e.get("quote") or "", page)
        if sp:
            out.append((sp.start, sp.end))
    return out


def _iou(a, b) -> float:
    inter = min(a[1], b[1]) - max(a[0], b[0])
    return inter / (max(a[1], b[1]) - min(a[0], b[0])) if inter > 0 else 0.0


def _tokens(n: dict) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", f"{n.get('label', '')} {n.get('summary', '')}".lower()))


def node_score(p: dict, g: dict, pspans, gspans) -> float:
    span = max((_iou(a, b) for a in pspans for b in gspans), default=0.0)
    tp, tg = _tokens(p), _tokens(g)
    jac = len(tp & tg) / len(tp | tg) if tp | tg else 0.0
    return W_SPAN * span + W_TEXT * jac


def match_nodes(pred, gold, index, threshold, relaxed=False) -> dict[str, str]:
    ps = {n["id"]: spans(n, index) for n in pred}
    gs = {n["id"]: spans(n, index) for n in gold}
    cands = []
    for p in pred:
        for g in gold:
            if not relaxed and p["type"] != g["type"]:
                continue
            s = node_score(p, g, ps[p["id"]], gs[g["id"]])
            if s >= threshold:
                cands.append((-s, p["id"], g["id"]))
    out, used = {}, set()
    for _, pid, gid in sorted(cands):
        if pid not in out and gid not in used:
            out[pid] = gid
            used.add(gid)
    return out


def match_edges(pred, gold, node_map, relaxed=False) -> list[tuple[int, int]]:
    free = defaultdict(list)
    for j, g in enumerate(gold):
        free[(g["source"], g["target"], None if relaxed else g["relation"])].append(j)
    out = []
    for i, p in enumerate(pred):
        s, t = node_map.get(p["source"]), node_map.get(p["target"])
        key = (s, t, None if relaxed else p["relation"])
        if s and t and free.get(key):
            out.append((i, free[key].pop(0)))
    return out


def _unit(pair: UnitPair, threshold: float) -> dict:
    pn, gn, pe, ge = pair.pred["nodes"], pair.gold["nodes"], pair.pred["edges"], pair.gold["edges"]
    strict = match_nodes(pn, gn, pair.index, threshold)
    relaxed = match_nodes(pn, gn, pair.index, threshold, relaxed=True)
    es, er = match_edges(pe, ge, strict), match_edges(pe, ge, relaxed, relaxed=True)
    c = {"nodes_strict": Counts(len(strict), len(pn) - len(strict), len(gn) - len(strict)),
         "nodes_relaxed": Counts(len(relaxed), len(pn) - len(relaxed), len(gn) - len(relaxed)),
         "edges_strict": Counts(len(es), len(pe) - len(es), len(ge) - len(es)),
         "edges_relaxed": Counts(len(er), len(pe) - len(er), len(ge) - len(er))}
    return {"counts": c, "strict": strict, "relaxed": relaxed, "edge_pairs": es, "edge_pairs_relaxed": er}


def _per_key(items_p, items_g, matched_p: set, matched_g: set, key) -> dict[str, Counts]:
    out: dict[str, Counts] = defaultdict(Counts)
    for x in items_p:
        out[key(x)].tp += x["_i"] in matched_p
        out[key(x)].fp += x["_i"] not in matched_p
    for x in items_g:
        out[key(x)].fn += x["_i"] not in matched_g
    return out


def evaluate(pairs: list[UnitPair], threshold: float) -> dict:
    micro = defaultdict(Counts)
    by_domain: dict[str, dict] = defaultdict(lambda: defaultdict(Counts))
    by_type, by_rel = defaultdict(Counts), defaultdict(Counts)
    prov = defaultdict(lambda: {"count": 0, "tp": 0})
    units, results = [], {}
    for pair in pairs:
        u = _unit(pair, threshold)
        results[pair.unit_id] = u
        for k, c in u["counts"].items():
            micro[k].add(c)
            by_domain[pair.domain][k].add(c)
        pn = [{**n, "_i": n["id"]} for n in pair.pred["nodes"]]
        gn = [{**n, "_i": n["id"]} for n in pair.gold["nodes"]]
        for t, c in _per_key(pn, gn, set(u["strict"]), set(u["strict"].values()), lambda x: x["type"]).items():
            by_type[t].add(c)
        pe = [{**e, "_i": i} for i, e in enumerate(pair.pred["edges"])]
        ge = [{**e, "_i": j} for j, e in enumerate(pair.gold["edges"])]
        mp, mg = {i for i, _ in u["edge_pairs"]}, {j for _, j in u["edge_pairs"]}
        for t, c in _per_key(pe, ge, mp, mg, lambda x: x["relation"]).items():
            by_rel[t].add(c)
        for n in pair.pred["nodes"]:
            b = prov[n.get("provenance", "llm")]
            b["count"] += 1
            b["tp"] += n["id"] in u["strict"]
        units.append({"unit_id": pair.unit_id, "domain": pair.domain,
                      **{k: c.to_json() for k, c in u["counts"].items()}})
    keys = ("nodes_strict", "nodes_relaxed", "edges_strict", "edges_relaxed")
    macro = {k: {m: round(sum(x[k][m] for x in units) / len(units), 4) if units else 0.0 for m in ("p", "r", "f1")}
             for k in keys}
    return {"threshold": threshold, "micro": {k: micro[k].to_json() for k in keys}, "macro": macro,
            "by_domain": {d: {k: v[k].to_json() for k in keys} for d, v in sorted(by_domain.items())},
            "by_node_type": {t: c.to_json() for t, c in sorted(by_type.items())},
            "by_relation": {t: c.to_json() for t, c in sorted(by_rel.items())},
            "provenance": {k: {"count": v["count"], "precision": round(v["tp"] / v["count"], 4) if v["count"] else 0.0}
                           for k, v in sorted(prov.items())},
            "units": units, "_results": results}


def threshold_sweep(pairs: list[UnitPair], thresholds=SWEEP) -> list[dict]:
    out = []
    for t in thresholds:
        r = evaluate(pairs, t)
        out.append({"threshold": t, **{k: r["micro"][k] for k in ("nodes_strict", "edges_strict")}})
    return out


def mapped_tier(pred_units: list[dict], gold_units: list[dict], records, node_rule: Counts) -> dict[str, dict]:
    def keys(g):
        out = defaultdict(set)
        for e in g["edges"]:
            out[e["type"]].add((e["source"], e["target"]))
        return out
    pk = keys(map_units(pred_units, records))
    gk = keys(map_units(gold_units, records, include_unverified=True))
    out = {}
    for t in MAPPED_TYPES:
        tp = len(pk[t] & gk[t])
        out[t] = Counts(tp, len(pk[t]) - tp, len(gk[t]) - tp).to_json()
    out["Doctrine(rule)"] = node_rule.to_json()
    return out
