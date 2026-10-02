"""Put every FP/FN in exactly one bucket (checked in BUCKETS order) and pick worked examples."""
from __future__ import annotations

from collections import Counter, defaultdict

from lisa.eval.extraction_eval import UnitPair, spans

BUCKETS = ("wrong_type", "granularity", "quote_miss", "endpoint_missed", "wrong_relation", "spurious", "missed")


def _overlaps(a_spans, b_spans) -> bool:
    return any(min(a[1], b[1]) > max(a[0], b[0]) for a in a_spans for b in b_spans)


def _quote(item: dict) -> str:
    ev = item.get("evidence") or []
    return ev[0].get("quote", "") if ev else ""


def bucket_errors(pair: UnitPair, result: dict) -> list[dict]:
    strict, relaxed = result["strict"], result["relaxed"]
    gold_hit, gold_relaxed = set(strict.values()), set(relaxed.values())
    pn, gn = pair.pred["nodes"], pair.gold["nodes"]
    ps = {n["id"]: spans(n, pair.index) for n in pn}
    gs = {n["id"]: spans(n, pair.index) for n in gn}
    errs = []

    def err(side, item, bucket, x, typ):
        errs.append({"unit_id": pair.unit_id, "side": side, "item": item, "bucket": bucket, "type": typ,
                     "label": x.get("label", f"{x.get('source')} -> {x.get('target')}"), "quote": _quote(x)})

    for p in pn:
        if p["id"] in strict:
            continue
        if p["id"] in relaxed:
            b = "wrong_type"
        elif any(g["type"] == p["type"] and _overlaps(ps[p["id"]], gs[g["id"]]) for g in gn):
            b = "granularity"
        elif p.get("provenance") == "unverified":
            b = "quote_miss"
        else:
            b = "spurious"
        err("FP", "node", b, p, p["type"])
    for g in gn:
        if g["id"] in gold_hit:
            continue
        if g["id"] in gold_relaxed:
            b = "wrong_type"
        elif any(p["type"] == g["type"] and _overlaps(ps[p["id"]], gs[g["id"]]) for p in pn):
            b = "granularity"
        else:
            b = "missed"
        err("FN", "node", b, g, g["type"])

    pe, ge = pair.pred["edges"], pair.gold["edges"]
    hit_p = {i for i, _ in result["edge_pairs"]}
    hit_g = {j for _, j in result["edge_pairs"]}
    rel_p = {i for i, _ in result["edge_pairs_relaxed"]}
    rel_g = {j for _, j in result["edge_pairs_relaxed"]}
    for i, e in enumerate(pe):
        if i in hit_p:
            continue
        b = ("quote_miss" if e.get("provenance") == "unverified"
             else "wrong_relation" if i in rel_p else "spurious")
        err("FP", "edge", b, e, e["relation"])
    for j, e in enumerate(ge):
        if j in hit_g:
            continue
        if e["source"] not in gold_hit or e["target"] not in gold_hit:
            b = "endpoint_missed"
        elif j in rel_g:
            b = "wrong_relation"
        else:
            b = "missed"
        err("FN", "edge", b, e, e["relation"])
    return errs


def summarize(errors: list[dict], examples: int = 5) -> dict:
    counts: dict[str, Counter] = defaultdict(Counter)
    ex: dict[str, list] = defaultdict(list)
    for e in errors:
        counts[e["item"]][e["bucket"]] += 1
        if len(ex[e["bucket"]]) < examples:
            ex[e["bucket"]].append(e)
    return {"counts": {k: dict(v) for k, v in counts.items()}, "examples": dict(ex)}
