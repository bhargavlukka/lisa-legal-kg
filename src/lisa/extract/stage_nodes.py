"""Stage 1: page windows -> gold-schema nodes, verified, deduped across windows, with code-assigned ids."""
from __future__ import annotations

import re
from typing import Sequence

from lisa.extract.calljson import ExtractionFailed, Truncated, call_json
from lisa.extract.schema import validate_node
from lisa.extract.units import Unit, UnitPage, active_part, render_pages
from lisa.extract.verify import PageIndex, evidence_strength, verify_item
from lisa.llm.budget import RunStats

MERGE_OVERLAP = 0.5


def slug(s: str, n: int = 60) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:n].strip("_") or "x"


def make_windows(unit: Unit, window_pages: int) -> list[tuple[UnitPage, ...]]:
    pages, step = unit.pages, max(window_pages - 1, 1)
    if len(pages) <= window_pages:
        return [pages]
    out, i = [], 0
    while True:
        out.append(pages[i:i + window_pages])
        if i + window_pages >= len(pages):
            return out
        i += step


def window_message(unit: Unit, pages: Sequence[UnitPage]) -> str:
    a = active_part(unit.segments, pages[0].page)
    part = f"PART ACTIVE AT TOP OF WINDOW (page {pages[0].page}): {a.part} | {a.label}\n" if a else ""
    return f"{unit.header}{part}{render_pages(pages)}\nExtract the nodes from the pages above."


def _norm(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


def _overlap(a: list[int], b: list[int]) -> float:
    inter = min(a[1], b[1]) - max(a[0], b[0])
    return inter / max(min(a[1] - a[0], b[1] - b[0]), 1) if inter > 0 else 0.0


def _spans(n: dict) -> list[list[int]]:
    return [e["span"] for e in n["evidence"] if e.get("span")]


def _same(a: dict, b: dict) -> bool:
    if a["type"] != b["type"]:
        return False
    if _norm(a["label"]) == _norm(b["label"]):
        return True
    return any(_overlap(x, y) >= MERGE_OVERLAP for x in _spans(a) for y in _spans(b))


def _merge(into: dict, other: dict) -> None:
    seen = {(e["page"], e["quote"]) for e in into["evidence"]}
    for e in other["evidence"]:
        if (e["page"], e["quote"]) not in seen and not any(
                e.get("span") and f.get("span") and _overlap(e["span"], f["span"]) >= MERGE_OVERLAP
                for f in into["evidence"]):
            into["evidence"].append(e)
            seen.add((e["page"], e["quote"]))
    if any(e["verified"] for e in into["evidence"]):
        into["evidence"] = [e for e in into["evidence"] if e["verified"]]
        into["provenance"], into["evidence_verified"] = "llm", True
    into["confidence"] = max(into["confidence"], other["confidence"])
    into["evidence_strength"] = evidence_strength([e["quote"] for e in into["evidence"] if e["verified"]])


def dedupe(nodes: list[dict]) -> list[dict]:
    out: list[dict] = []
    for n in nodes:
        for m in out:
            if _same(m, n):
                _merge(m, n)
                break
        else:
            out.append({**n, "evidence": list(n["evidence"])})
    return out


def assign_ids(case_id: str, nodes: list[dict]) -> list[dict]:
    seen, out = set(), []
    for n in nodes:
        base = f"{case_id}:{n['type']}:{slug(n['label'])}"
        nid, k = base, 2
        while nid in seen:
            nid, k = f"{base}_{k}", k + 1
        seen.add(nid)
        out.append({"id": nid, **n, "case_id": case_id})
    return out


def _window(unit, pages, client, system, version, stats, splits_left=1) -> list[dict]:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": window_message(unit, pages)}]
    where = {"unit": unit.unit_id, "stage": "nodes", "pages": [p.page for p in pages]}
    try:
        items = call_json(client, msgs, version, "nodes", stats)
    except Truncated:
        if splits_left and len(pages) > 1:
            h = len(pages) // 2
            return (_window(unit, pages[:h], client, system, version, stats, splits_left - 1)
                    + _window(unit, pages[h:], client, system, version, stats, splits_left - 1))
        stats.failed.append({**where, "reason": "truncated"})
        return []
    except ExtractionFailed as e:
        stats.failed.append({**where, "reason": f"invalid output: {e}"})
        return []
    out = []
    for it in items:
        n, why = validate_node(it)
        if n is None:
            stats.schema_rejects.append({**where, "reason": why})
        else:
            out.append(n)
    return out


def extract_nodes(unit: Unit, client, system: str, version: str, window_pages: int, stats: RunStats) -> list[dict]:
    index = PageIndex(unit.raw_pages)
    raw: list[dict] = []
    for pages in make_windows(unit, window_pages):
        raw += _window(unit, pages, client, system, version, stats)
    nodes = [verify_item(n, index) for n in raw]
    if unit.repeated_page is not None:
        nodes = [n for n in nodes
                 if not (n["evidence_verified"] and all(e["page"] == unit.repeated_page for e in n["evidence"]))]
    return assign_ids(unit.case_id, dedupe(nodes))
