"""Markdown rendering of the extraction report."""
from __future__ import annotations

KEYS = ("nodes_strict", "nodes_relaxed", "edges_strict", "edges_relaxed")


def _row(name: str, c: dict) -> str:
    return f"| {name} | {c.get('p', 0):.3f} | {c.get('r', 0):.3f} | {c.get('f1', 0):.3f} | {c.get('tp', '')} | {c.get('fp', '')} | {c.get('fn', '')} |"


def _table(title: str, rows: dict) -> list[str]:
    return [f"### {title}", "", "| | P | R | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|",
            *[_row(k, v) for k, v in rows.items()], ""]


def render_markdown(r: dict) -> str:
    h = r["headline"]
    out = ["# LISA Phase 2 — LLM extraction vs gold standard", "",
           f"Model `{r['model']}` · prompts {r['prompt_versions']} · match threshold {r['threshold']} · "
           f"{r['scored_units']} scored units (few-shot units excluded: {', '.join(r['excluded_units'])})", "",
           "## Headline (micro)", ""]
    out += _table("All units", {k: h["micro"][k] for k in KEYS})
    out += ["Macro (mean per unit): " + ", ".join(f"{k} F1 {h['macro'][k]['f1']:.3f}" for k in KEYS), ""]
    for d, v in h.get("by_domain", {}).items():
        out += _table(f"Domain: {d}", v)
    out += ["## Per type", ""] + _table("Node types (strict)", h.get("by_node_type", {}))
    out += _table("Relations (strict)", h.get("by_relation", {}))
    out += ["## Mapped spec tier", "", "OVERRULES occurs once in gold: its P/R is not statistically meaningful. "
            "Doctrine is scored as rule-node P/R (gold has no canonical doctrine names).", ""]
    out += _table("Mapped edges", r.get("mapped", {}))
    out += ["## Provenance", "", "| provenance | count | precision |", "|---|---|---|",
            *[f"| {k} | {v['count']} | {v['precision']:.3f} |" for k, v in h.get("provenance", {}).items()], ""]
    out += ["## Threshold sweep (strict)", "", "| threshold | node P | node R | edge P | edge R |", "|---|---|---|---|---|",
            *[f"| {s['threshold']} | {s['nodes_strict']['p']:.3f} | {s['nodes_strict']['r']:.3f} | "
              f"{s['edges_strict']['p']:.3f} | {s['edges_strict']['r']:.3f} |" for s in r.get("sweep", [])], ""]
    errs = r["errors"]
    out += ["## Error analysis", "", "Each FP/FN is in exactly one bucket, checked in this order: wrong_type, "
            "granularity, quote_miss, endpoint_missed, wrong_relation, spurious/missed.", ""]
    for item, c in errs["counts"].items():
        out.append(f"- **{item}**: " + ", ".join(f"{b} {n}" for b, n in sorted(c.items(), key=lambda x: -x[1])))
    out.append("")
    for b, exs in errs["examples"].items():
        out += [f"### {b}", ""]
        out += [f"- {e['side']} {e['item']} `{e['type']}` in `{e['unit_id']}` — {e['label']}: “{e['quote']}”"
                for e in exs]
        out.append("")
    out += ["## Run cost", "", *[f"- {k}: {v}" for k, v in r.get("cost", {}).items()], ""]
    return "\n".join(out)
