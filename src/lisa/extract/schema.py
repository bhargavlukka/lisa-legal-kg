"""Gold extraction schema: vocabularies, allowed (source_type, relation, target_type) signatures, validation."""
from __future__ import annotations

import json
from pathlib import Path

NODE_TYPES = ("opinion", "issue", "fact", "rule", "holding", "reasoning", "outcome", "authority_ref")
RELATIONS = ("presents_issue", "states_fact", "states_rule", "holds", "has_outcome", "supports", "applies_rule",
             "relies_on", "relevant_to", "resolves", "agrees_with", "disagrees_with")
STANCES = ("follows", "distinguishes", "overrules", "criticizes", "relies_on", "cites_without_treatment")
PARTS = ("headnote", "syllabus", "front_matter_or_syllabus", "majority", "per_curiam", "concurrence", "dissent",
         "concurrence_and_dissent", "body_unsegmented")
AUTHORITY_KINDS = ("case", "statute", "regulation", "constitution", "other")
SIGNATURES_FILE = Path(__file__).with_name("schema_signatures.json")
SIGNATURES: frozenset[tuple[str, str, str]] = frozenset(
    tuple(s) for s in json.loads(SIGNATURES_FILE.read_text(encoding="utf-8")))


def _evidence(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    return [{"page": e.get("page"), "quote": e["quote"]} for e in raw
            if isinstance(e, dict) and isinstance(e.get("quote"), str) and e["quote"].strip()]


def _common(raw: dict) -> dict:
    out = {"part": raw.get("part") if raw.get("part") in PARTS else None,
           "evidence": _evidence(raw.get("evidence"))}
    if "confidence" in raw:
        out["confidence"] = raw["confidence"]
    out["attrs"] = dict(raw["attrs"]) if isinstance(raw.get("attrs"), dict) else {}
    return out


def validate_node(raw) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, "not an object"
    if raw.get("type") not in NODE_TYPES:
        return None, f"unknown node type: {raw.get('type')}"
    label = raw.get("label").strip() if isinstance(raw.get("label"), str) else ""
    if not label:
        return None, "missing label"
    c = _common(raw)
    if not c["evidence"]:
        return None, "missing evidence"
    if raw["type"] == "authority_ref":
        if not str(c["attrs"].get("cite_string") or "").strip():
            return None, "authority_ref without cite_string"
        if c["attrs"].get("kind") not in AUTHORITY_KINDS:
            c["attrs"]["kind"] = "other"
    author = raw.get("author") if isinstance(raw.get("author"), str) and raw["author"].strip() else None
    node = {"type": raw["type"], "label": label,
            "summary": raw["summary"].strip() if isinstance(raw.get("summary"), str) else "",
            "part": c["part"], "author": author, "evidence": c["evidence"]}
    if "confidence" in c:
        node["confidence"] = c["confidence"]
    node["attrs"] = c["attrs"]
    return node, None


def validate_edge(raw, types: dict[str, str]) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, "not an object"
    for end in ("source", "target"):
        if raw.get(end) not in types:
            return None, f"unknown node id: {raw.get(end)}"
    rel = raw.get("relation")
    if rel not in RELATIONS:
        return None, f"unknown relation: {rel}"
    sig = (types[raw["source"]], rel, types[raw["target"]])
    if sig not in SIGNATURES:
        return None, f"disallowed signature: {sig[0]} -{rel}-> {sig[2]}"
    c = _common(raw)
    stance = (raw.get("stance") if raw.get("stance") in STANCES else "relies_on") if rel == "relies_on" else None
    basis = raw.get("basis") if raw.get("basis") in ("explicit", "inferred") else "explicit"
    if basis == "inferred" and not str(c["attrs"].get("inference_reason") or "").strip():
        c["attrs"]["inference_reason"] = "(not given)"
    edge = {"source": raw["source"], "target": raw["target"], "relation": rel, "stance": stance, "basis": basis,
            "part": c["part"], "evidence": c["evidence"]}
    if "confidence" in c:
        edge["confidence"] = c["confidence"]
    edge["attrs"] = c["attrs"]
    return edge, None


def derive_signatures(gold_dir: Path) -> list[list[str]]:
    sigs = set()
    for f in sorted(Path(gold_dir).glob("*.json")):
        g = json.loads(f.read_text(encoding="utf-8"))
        types = {n["id"]: n["type"] for n in g["nodes"]}
        for e in g["edges"]:
            if e["source"] in types and e["target"] in types:
                sigs.add((types[e["source"]], e["relation"], types[e["target"]]))
    return [list(s) for s in sorted(sigs)]
