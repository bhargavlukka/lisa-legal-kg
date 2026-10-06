"""Run the LLM tier for one dataset config: units -> nodes -> edges -> verify -> outputs + run manifest."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from lisa.common.config import EvalSettings, LLMSettings, Settings, load_dataset
from lisa.extract.fewshot import build_fewshot
from lisa.extract.mapping import map_units
from lisa.extract.prompts import build_system
from lisa.extract.stage_edges import extract_edges
from lisa.extract.stage_nodes import extract_nodes
from lisa.extract.units import Unit, build_units
from lisa.graph.loader import load_records, verify_manifest
from lisa.llm.budget import Budget, BudgetExhausted, RunStats
from lisa.llm.cache import Cache
from lisa.llm.client import CacheMiss, LLMClient

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class RunResult:
    status: str
    output: Path
    graph: Path
    manifest: Path


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _fewshot(settings: Settings, ev: EvalSettings) -> tuple[str, str]:
    if not ev.fewshot_units:
        return "", ""
    gold_paths = [f"gold_standard/{u}.json" for u in ev.fewshot_units]
    ds = load_dataset("gold_eval")
    verify_manifest(settings.data_dir, [s.path for s in ds.sources] + gold_paths)
    recs, _ = load_records(settings.data_dir, ds)
    units = {u.unit_id: u for r in recs for u in build_units(r) if u.unit_id in ev.fewshot_units}
    golds = {u: json.loads((settings.data_dir / p).read_text(encoding="utf-8"))
             for u, p in zip(ev.fewshot_units, gold_paths)}
    return build_fewshot(golds, units, ev.fewshot_units)


def run(dataset: str, *, settings: Settings, llm: LLMSettings, ev: EvalSettings, offline: bool = False,
        max_requests: int | None = None, only_units: set[str] | None = None, transport=None,
        sleep=time.sleep, workers: int | None = None) -> RunResult:
    t0, started = time.monotonic(), datetime.now(timezone.utc)
    ds = load_dataset(dataset)
    verify_manifest(settings.data_dir, [s.path for s in ds.sources])
    records, _ = load_records(settings.data_dir, ds)
    units: list[Unit] = [u for r in records for u in build_units(r)
                         if u.unit_id not in ev.fewshot_units and (not only_units or u.unit_id in only_units)]
    node_fs, edge_fs = _fewshot(settings, ev)
    v_nodes, sys_nodes = build_system("nodes", node_fs)
    v_edges, sys_edges = build_system("edges", edge_fs)
    stats = RunStats()
    budget = Budget(max_requests or llm.max_requests_per_run)
    client = LLMClient(llm, Cache(settings.out_dir / "llm_cache"), budget, stats, offline=offline,
                       transport=transport, sleep=sleep)

    def one(u: Unit) -> dict | None:
        """Extract one unit; None when the request budget ran out (the unit stays pending)."""
        try:
            nodes = extract_nodes(u, client, sys_nodes, v_nodes, llm.window_pages, stats)
            edges = extract_edges(u, nodes, client, sys_edges, v_edges, llm.edge_split_chars, stats)
            ustatus = "partial" if any(f.get("unit") == u.unit_id for f in stats.failed) else "ok"
        except BudgetExhausted:
            return None
        except CacheMiss:
            nodes, edges, ustatus = [], [], "not_cached"
        return {"unit_id": u.unit_id, "case_id": u.case_id, "dataset": u.domain, "status": ustatus,
                "nodes": nodes, "edges": edges}

    # Units are independent, so they run concurrently; results keep the unit order and the cache makes reruns resume.
    with ThreadPoolExecutor(max_workers=max(1, workers or llm.workers)) as pool:
        results = list(pool.map(one, units))
    done = [r for r in results if r is not None]
    pending = [u.unit_id for u, r in zip(units, results) if r is None]
    status = "budget_exhausted" if pending else "complete"

    out_dir = settings.out_dir
    output, graph = out_dir / f"llm_{ds.name}.json", out_dir / f"graph_{ds.name}_llm.json"
    _write(output, {"schema_version": SCHEMA_VERSION, "dataset": ds.name, "model": llm.model,
                    "prompt_versions": {"nodes": v_nodes, "edges": v_edges}, "units": done, "pending": pending})
    _write(graph, {"dataset": ds.name, **map_units(done, records, llm.include_unverified_in_graph)})
    manifest = out_dir / "llm_runs" / f"{started.strftime('%Y%m%dT%H%M%S%fZ')}_{ds.name}.json"
    _write(manifest, {"dataset": ds.name, "model": llm.model, "status": status, "offline": offline,
                      "started_at": started.isoformat(), "wall_s": round(time.monotonic() - t0, 1),
                      "budget": budget.max_requests, "units_total": len(units), "units_done": len(done),
                      "prompt_versions": {"nodes": v_nodes, "edges": v_edges}, **stats.to_json()})
    return RunResult(status, output, graph, manifest)
