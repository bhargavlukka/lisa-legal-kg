"""Score out/llm_gold_eval.json against the gold standard -> out/eval/extraction_report.{json,md}."""
from __future__ import annotations

import argparse
import json
import sys

from lisa.common.config import load_dataset, load_eval_settings, load_settings
from lisa.eval.error_analysis import bucket_errors, summarize
from lisa.eval.extraction_eval import Counts, UnitPair, evaluate, mapped_tier, threshold_sweep
from lisa.eval.report import render_markdown
from lisa.extract.units import build_units
from lisa.extract.verify import PageIndex
from lisa.graph.loader import ChecksumError, load_records, verify_manifest

COST_KEYS = ("requests", "cache_hits", "input_tokens", "output_tokens", "rate_limited", "retries", "repairs",
             "truncations", "wall_s")


def _cost(out_dir) -> dict:
    total = dict.fromkeys(COST_KEYS, 0)
    runs = sorted((out_dir / "llm_runs").glob("*_gold_eval.json"))
    for p in runs:
        m = json.loads(p.read_text(encoding="utf-8"))
        for k in COST_KEYS:
            total[k] += m.get(k) or 0
    return {"runs": len(runs), **total}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--threshold", type=float, help="override eval.match_threshold")
    a = ap.parse_args(argv)
    try:
        settings, ev = load_settings(), load_eval_settings()
    except RuntimeError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    pred_path = settings.out_dir / "llm_gold_eval.json"
    if not pred_path.exists():
        print(f"{pred_path} not found - run scripts/extract_llm.py --dataset gold_eval first", file=sys.stderr)
        return 2
    pred = json.loads(pred_path.read_text(encoding="utf-8"))
    ds = load_dataset("gold_eval")
    gold_files = sorted((settings.data_dir / "gold_standard").glob("*.json"))
    try:
        verify_manifest(settings.data_dir, [s.path for s in ds.sources]
                        + [f"gold_standard/{p.name}" for p in gold_files])
    except ChecksumError as e:
        print(f"checksum error: {e}", file=sys.stderr)
        return 2
    records, _ = load_records(settings.data_dir, ds)
    units = {u.unit_id: u for r in records for u in build_units(r)}
    golds = {g["unit_id"]: g for g in (json.loads(p.read_text(encoding="utf-8")) for p in gold_files)}
    preds = {u["unit_id"]: u for u in pred["units"]}
    scored = sorted(uid for uid in golds if uid not in ev.fewshot_units)
    empty = {"nodes": [], "edges": []}
    pairs = [UnitPair(uid, units[uid].domain, preds.get(uid, empty), golds[uid], PageIndex(units[uid].raw_pages))
             for uid in scored]
    threshold = a.threshold if a.threshold is not None else ev.match_threshold
    head = evaluate(pairs, threshold)
    errors = [e for p in pairs for e in bucket_errors(p, head["_results"][p.unit_id])]
    rule = head["by_node_type"].get("rule", {})
    report = {
        "model": pred.get("model"), "prompt_versions": pred.get("prompt_versions"), "threshold": threshold,
        "scored_units": len(scored), "excluded_units": list(ev.fewshot_units),
        "missing_predictions": [u for u in scored if u not in preds],
        "headline": {k: v for k, v in head.items() if not k.startswith("_")},
        "sweep": threshold_sweep(pairs),
        "mapped": mapped_tier([preds[u] for u in scored if u in preds], [golds[u] for u in scored], records,
                              Counts(rule.get("tp", 0), rule.get("fp", 0), rule.get("fn", 0))),
        "errors": summarize(errors), "cost": _cost(settings.out_dir)}
    out = settings.out_dir / "eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / "extraction_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "extraction_report.md").write_text(render_markdown(report), encoding="utf-8")
    m = report["headline"]["micro"]
    print(f"scored {len(scored)} units; node F1 strict {m['nodes_strict']['f1']:.3f} relaxed "
          f"{m['nodes_relaxed']['f1']:.3f}; edge F1 strict {m['edges_strict']['f1']:.3f} relaxed "
          f"{m['edges_relaxed']['f1']:.3f}")
    print(f"wrote {out / 'extraction_report.md'}")
    return 0
