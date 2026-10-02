"""Few-shot blocks built at run time from two fixed gold units (never committed; excluded from scoring)."""
from __future__ import annotations

import json
from typing import Sequence

from lisa.extract.units import Unit, render_pages

NODE_KEYS = ("type", "label", "summary", "part", "author", "attrs")
EDGE_KEYS = ("source", "target", "relation", "stance", "basis", "part", "attrs")


def _ev(item: dict) -> list[dict]:
    return [{"page": e["page"], "quote": e["quote"]} for e in item.get("evidence") or []]


def _in_window(item: dict, pages: set[int]) -> bool:
    ev = item.get("evidence") or []
    return bool(ev) and all(e.get("page") in pages for e in ev)


def _window(gold: dict, unit: Unit, max_pages: int):
    pages = unit.pages[:max_pages]
    keep = {p.page for p in pages}
    nodes = [n for n in gold["nodes"] if _in_window(n, keep)]
    return pages, keep, nodes


def node_examples(gold: dict, unit: Unit, max_pages: int = 2) -> str:
    pages, _, nodes = _window(gold, unit, max_pages)
    out = [{**{k: n.get(k) for k in NODE_KEYS[:5]}, "evidence": _ev(n), "attrs": n.get("attrs") or {}}
           for n in nodes]
    return (f"### Example input\n{unit.header}{render_pages(pages)}\n### Example output\n"
            + json.dumps({"nodes": out}, ensure_ascii=False))


def edge_examples(gold: dict, unit: Unit, max_pages: int = 2) -> str:
    pages, keep, nodes = _window(gold, unit, max_pages)
    ids = {n["id"] for n in nodes}
    cat = [{"id": n["id"], "type": n["type"], "label": n["label"], "part": n.get("part"),
            "pages": sorted({e["page"] for e in n["evidence"]})} for n in nodes]
    edges = [{**{k: e.get(k) for k in EDGE_KEYS[:6]}, "evidence": _ev(e), "confidence": e.get("confidence"),
              "attrs": e.get("attrs") or {}}
             for e in gold["edges"] if e["source"] in ids and e["target"] in ids and _in_window(e, keep)]
    return (f"### Example input\n{unit.header}{render_pages(pages)}\nNODE CATALOG:\n"
            + "\n".join(json.dumps(c, ensure_ascii=False) for c in cat)
            + "\nSOURCE NODES: all\n### Example output\n" + json.dumps({"edges": edges}, ensure_ascii=False))


def build_fewshot(golds: dict[str, dict], units: dict[str, Unit], ids: Sequence[str]) -> tuple[str, str]:
    present = [i for i in ids if i in golds and i in units]
    return ("\n\n".join(node_examples(golds[i], units[i]) for i in present),
            "\n\n".join(edge_examples(golds[i], units[i]) for i in present))
