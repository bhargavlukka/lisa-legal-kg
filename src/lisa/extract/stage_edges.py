"""Stage 2: unit text + node catalog -> gold-schema edges (signature-checked, verified)."""
from __future__ import annotations

import json

from lisa.extract.calljson import ExtractionFailed, Truncated, call_json
from lisa.extract.schema import validate_edge
from lisa.extract.units import Unit, UnitPage, render_pages
from lisa.extract.verify import PageIndex, verify_item
from lisa.llm.budget import RunStats

SHARED_TYPES = ("issue", "authority_ref", "holding", "outcome")   # visible to every part-split call
MAX_SPLIT_DEPTH = 3


def _pages(n: dict) -> list[int]:
    return sorted({e["page"] for e in n["evidence"] if isinstance(e.get("page"), int)})


def catalog(nodes: list[dict]) -> list[dict]:
    return [{"id": n["id"], "type": n["type"], "label": n["label"], "part": n.get("part"), "pages": _pages(n)}
            for n in nodes]


def plan_calls(unit: Unit, nodes: list[dict], split_chars: int):
    if len(unit.text) <= split_chars:
        return [(unit.pages, nodes, None)]
    calls, claimed = [], set()
    for seg in unit.segments:
        pages = tuple(p for p in unit.pages if seg.start_page <= p.page <= seg.end_page)
        if not pages:
            continue
        own = [n for n in nodes if n["id"] not in claimed and n.get("part") == seg.part
               and any(seg.start_page <= pg <= seg.end_page for pg in _pages(n))]
        if not own:
            continue
        claimed.update(n["id"] for n in own)
        own_ids = [n["id"] for n in own]
        shared = [n for n in nodes if n["type"] in SHARED_TYPES and n["id"] not in own_ids]
        calls.append((pages, own + shared, own_ids))
    rest = [n for n in nodes if n["id"] not in claimed]
    if rest:
        calls.append((unit.pages, nodes, [n["id"] for n in rest]))
    return calls


def _message(unit: Unit, pages, cat_nodes, sources) -> str:
    cat = "\n".join(json.dumps(c, ensure_ascii=False) for c in catalog(cat_nodes))
    src = "all" if sources is None else json.dumps(sources)
    return f"{unit.header}{render_pages(pages)}\nNODE CATALOG:\n{cat}\nSOURCE NODES: {src}\nExtract the edges."


def _call(unit, pages, cat_nodes, sources, client, system, version, stats, depth=0) -> list[tuple[dict, list | None]]:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": _message(unit, pages, cat_nodes, sources)}]
    where = {"unit": unit.unit_id, "stage": "edges", "pages": [pages[0].page, pages[-1].page]}
    try:
        return [(it, sources) for it in call_json(client, msgs, version, "edges", stats)]
    except Truncated:
        ids = sources if sources is not None else [n["id"] for n in cat_nodes]
        if depth < MAX_SPLIT_DEPTH and len(ids) > 1:
            h = len(ids) // 2
            return (_call(unit, pages, cat_nodes, ids[:h], client, system, version, stats, depth + 1)
                    + _call(unit, pages, cat_nodes, ids[h:], client, system, version, stats, depth + 1))
        stats.failed.append({**where, "reason": "truncated"})
    except ExtractionFailed as e:
        stats.failed.append({**where, "reason": f"invalid output: {e}"})
    return []


def extract_edges(unit: Unit, nodes: list[dict], client, system: str, version: str, split_chars: int,
                  stats: RunStats) -> list[dict]:
    if not nodes:
        return []
    types = {n["id"]: n["type"] for n in nodes}
    parts = {n["id"]: n.get("part") for n in nodes}
    index = PageIndex(unit.raw_pages)
    out: dict[tuple[str, str, str], dict] = {}
    for pages, cat_nodes, sources in plan_calls(unit, nodes, split_chars):
        for raw, allowed in _call(unit, pages, cat_nodes, sources, client, system, version, stats):
            where = {"unit": unit.unit_id, "stage": "edges"}
            e, why = validate_edge(raw, types)
            if e is None:
                stats.schema_rejects.append({**where, "reason": why})
                continue
            if allowed is not None and e["source"] not in allowed:
                stats.schema_rejects.append({**where, "reason": "source not in this request"})
                continue
            key = (e["source"], e["relation"], e["target"])
            if key in out:
                continue
            e = verify_item(e, index)
            e["part"] = e["part"] or parts[e["source"]]
            e["case_id"] = unit.case_id
            out[key] = e
    return list(out.values())
