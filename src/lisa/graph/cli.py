"""Build the knowledge graph for one dataset config: verify -> extract -> (check) -> (load)."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from lisa.common.config import load_dataset, load_settings
from lisa.graph.check import check
from lisa.graph.extract_det import build_graph
from lisa.graph.loader import ChecksumError, load_records, verify_manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, help="name of config/datasets/<name>.yaml (all, immigration, litigation, gold_eval)")
    ap.add_argument("--check", action="store_true", help="compare edges with selection_report.json")
    ap.add_argument("--no-load", action="store_true", help="write graph JSON only; skip Neo4j")
    a = ap.parse_args(argv)

    try:
        settings = load_settings()
    except RuntimeError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    ds = load_dataset(a.dataset)
    try:
        verify_manifest(settings.data_dir, [s.path for s in ds.sources])
    except ChecksumError as e:
        print(f"checksum error: {e}", file=sys.stderr)
        return 2

    records, quarantine = load_records(settings.data_dir, ds)
    graph = build_graph(records, ds).to_json()
    settings.out_dir.mkdir(parents=True, exist_ok=True)
    (settings.out_dir / f"graph_{ds.name}.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=1), encoding="utf-8")
    (settings.out_dir / f"quarantine_{ds.name}.json").write_text(
        json.dumps(quarantine, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{ds.name}: {len(records)} records, {len(quarantine)} quarantined")
    print("nodes:", dict(sorted(Counter(n["label"] for n in graph["nodes"]).items())))
    print("edges:", dict(sorted(Counter(e["type"] for e in graph["edges"]).items())))
    print("unverified edges:", sum(e["provenance"] == "unverified" for e in graph["edges"]))

    rc = 0
    if a.check:
        report = json.loads((settings.data_dir / "selection_report.json").read_text(encoding="utf-8"))
        r = check(graph, report)
        print(f"check vs selection_report: expected {r.expected}, missing {len(r.missing)}, extra {len(r.extra)}")
        for m in r.missing:
            print("  MISSING", *m)
        for x in r.extra:
            print("  extra  ", *x)
        rc = 0 if r.ok else 1

    if not a.no_load:
        from lisa.graph.neo4j_load import Neo4jUnavailable, load
        try:
            print("neo4j:", load(graph, settings))
        except Neo4jUnavailable as e:
            print(f"neo4j load failed: {e} (graph JSON was written)", file=sys.stderr)
            return rc or 3
    return rc
