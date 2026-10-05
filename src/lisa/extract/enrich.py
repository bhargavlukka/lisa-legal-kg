"""LLM tier for the served 60-case graph (the gold cases are a disjoint set, so Phase 2 output does not cover it).

Two small, targeted call types instead of full gold-schema extraction (~200 calls instead of ~1000+):
  treatment - one call per in-corpus CITES pair: does the citing case follow / distinguish / overrule the cited
              case, or merely cite it? -> FOLLOWS / DISTINGUISHES / OVERRULES edge (spec L1 LLM tier)
  case      - one call per case on its opening pages: doctrines invoked and the authoring judge/Board member
              -> Doctrine + INVOKES_DOCTRINE, Judge + AUTHORED_BY
Every claim carries a quote; a claim enters the graph only if its quote is found verbatim on the case's pages
(lisa.extract.verify), otherwise it is dropped (counted in the run manifest). Provenance llm, confidence from the
model capped by verification.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone

from lisa.common.config import load_dataset, load_llm_settings, load_settings
from lisa.extract.calljson import ExtractionFailed, Truncated, parse_json
from lisa.extract.mapping import judge_id, surname
from lisa.extract.stage_nodes import slug
from lisa.extract.verify import PageIndex
from lisa.graph.loader import load_records, verify_manifest
from lisa.llm.budget import Budget, BudgetExhausted, RunStats
from lisa.llm.cache import Cache
from lisa.llm.client import CacheMiss, LLMClient, LLMError

EXTRACTOR = "lisa.extract.enrich/1"
V_TREAT, V_CASE = "enrich-treatment-v1", "enrich-case-v1"
TREAT_EDGE = {"follows": "FOLLOWS", "distinguishes": "DISTINGUISHES", "overrules": "OVERRULES"}
WINDOW_CHARS = 9000

SYS_TREAT = """You classify how one court decision treats a precedent it cites. Answer from the given pages only.
Treatments:
- follows: relies on the precedent as controlling or persuasive and applies its rule/holding
- distinguishes: explains why the precedent does not control because facts/issues differ
- overrules: expressly overrules, abrogates, supersedes or withdraws from the precedent (or says a later
  decision did so and treats it as no longer binding)
- cites: mentions it without one of the above (background, string cite, procedural history)
Reply with JSON only: {"treatment": "follows|distinguishes|overrules|cites", "confidence": 0.0-1.0,
"quote": "<one passage copied verbatim from the pages, 15-60 words, that shows the treatment>", "page": <int>}"""

SYS_CASE = """You extract metadata from the opening pages of one court decision. Answer from the given pages only.
Reply with JSON only:
{"doctrines": [{"name": "<short canonical name of a legal doctrine/test the decision applies, lowercase, e.g.
"stop-time rule", "categorical approach", "particularly serious crime">", "quote": "<verbatim passage, 10-50 words,
showing it>", "page": <int>}],
 "author": {"name": "<judge, Justice or Board member who wrote the majority/opinion, as printed>", "quote":
"<verbatim passage naming them>", "page": <int>} or null}
List at most 4 doctrines. Copy quotes exactly; do not use "..." inside a quote."""


def _window(pages: dict[int, str], page: int | None, n_after: int = 1) -> tuple[str, list[int]]:
    keys = sorted(pages)
    if page not in pages:
        page = keys[0]
    i = keys.index(page)
    chosen = keys[max(i - 1, 0): i + 1 + n_after]
    text = "\n".join(f"===== [[PAGE {p}]] =====\n{pages[p]}" for p in chosen)
    return text[:WINDOW_CHARS], chosen


def _ask(client, system: str, user: str, version: str, stats: RunStats) -> dict:
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in (1, 2):
        c = client.complete(msgs, version)
        if c.finish_reason == "length":
            stats.truncations += 1
            raise Truncated()
        try:
            obj = parse_json(c.text)
            if not isinstance(obj, dict):
                raise ValueError("expected a JSON object")
            return obj
        except ValueError as e:
            if attempt == 2:
                raise ExtractionFailed(str(e)) from e
            stats.repairs += 1
            msgs += [{"role": "assistant", "content": c.text[:3000]},
                     {"role": "user", "content": f"Not valid JSON ({e}). Reply with only the JSON object."}]
    raise AssertionError("unreachable")


def _conf(v, default=0.7) -> float:
    try:
        return round(min(max(float(v), 0.0), 1.0), 3)
    except (TypeError, ValueError):
        return default


class Enricher:
    def __init__(self, records, det_graph: dict, client, stats: RunStats):
        self.recs = {r.id: r for r in records}
        self.pages = {r.id: {p["page"]: p["text"] for p in r.pages} for r in records}
        self.index = {cid: PageIndex(p) for cid, p in self.pages.items()}
        self.det = det_graph
        self.client, self.stats = client, stats
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple, dict] = {}
        self.dropped: Counter = Counter()

    def _verified(self, cid: str, quote, page) -> dict | None:
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = None
        if not isinstance(quote, str):
            return None
        sp = self.index[cid].locate(quote, page) if page else None
        if sp is None:
            for p in self.index[cid].pages:
                if (sp := self.index[cid].locate(quote, p)):
                    break
        return {"page": sp.page, "quote": quote, "verified": True} if sp else None

    def _edge(self, etype, src, tgt, ev, conf, props=None):
        self.edges[(etype, src, tgt)] = {"type": etype, "source": src, "target": tgt, "props": props or {},
                                         "provenance": "llm", "confidence": conf, "evidence": [ev],
                                         "extractor": EXTRACTOR}

    def _node(self, nid, label, props):
        self.nodes.setdefault(nid, {"id": nid, "label": label, "props": props, "provenance": "llm",
                                    "confidence": 1.0, "evidence": [], "extractor": EXTRACTOR})

    def treatment_pairs(self) -> list[dict]:
        cases = {n["id"] for n in self.det["nodes"] if n["label"] == "Case"}
        return [e for e in self.det["edges"] if e["type"] == "CITES" and e["target"] in cases and e["source"] in cases]

    def treat(self, e: dict) -> None:
        src, tgt = e["source"], e["target"]
        cited = self.recs[tgt]
        page = (e["evidence"][0] or {}).get("page") if e["evidence"] else None
        text, _ = _window(self.pages[src], page)
        user = (f"Citing decision: {self.recs[src].title} ({self.recs[src].citation or src})\n"
                f"Cited precedent: {cited.title} ({cited.citation or tgt})\n\nPages of the citing decision:\n{text}")
        obj = _ask(self.client, SYS_TREAT, user, V_TREAT, self.stats)
        t = str(obj.get("treatment", "")).lower().strip()
        if t not in TREAT_EDGE:
            self.dropped["treatment_cites"] += 1
            return
        ev = self._verified(src, obj.get("quote"), obj.get("page"))
        if ev is None:
            self.dropped["treatment_unverified_quote"] += 1
            return
        self._edge(TREAT_EDGE[t], src, tgt, ev, _conf(obj.get("confidence")),
                   {"scope": e["props"].get("scope"), "treatment": t})

    def case_meta(self, cid: str) -> None:
        text, _ = _window(self.pages[cid], sorted(self.pages[cid])[0], n_after=1)
        rec = self.recs[cid]
        obj = _ask(self.client, SYS_CASE, f"Decision: {rec.title} ({rec.citation or cid})\n\n{text}", V_CASE,
                   self.stats)
        for d in (obj.get("doctrines") or [])[:4]:
            if not isinstance(d, dict) or not str(d.get("name", "")).strip():
                continue
            ev = self._verified(cid, d.get("quote"), d.get("page"))
            if ev is None:
                self.dropped["doctrine_unverified_quote"] += 1
                continue
            name = " ".join(str(d["name"]).lower().split())
            did = f"doctrine:{slug(name)}"
            self._node(did, "Doctrine", {"name": name})
            self._edge("INVOKES_DOCTRINE", cid, did, ev, 0.8)
        a = obj.get("author")
        if isinstance(a, dict) and str(a.get("name", "")).strip():
            ev = self._verified(cid, a.get("quote"), a.get("page"))
            if ev is None or surname(a["name"]).lower() not in ev["quote"].lower():
                self.dropped["author_unverified"] += 1
                return
            court = rec.props.get("court")
            jid = judge_id(court, a["name"])
            self._node(jid, "Judge", {"name": surname(a["name"]), "court": court})
            self._edge("AUTHORED_BY", cid, jid, ev, 0.8)

    def to_json(self, dataset: str) -> dict:
        return {"dataset": dataset, "extractor": EXTRACTOR, "nodes": [self.nodes[k] for k in sorted(self.nodes)],
                "edges": [self.edges[k] for k in sorted(self.edges)]}


def run(dataset: str = "all", offline: bool = False, max_requests: int | None = None, transport=None) -> dict:
    settings, llm = load_settings(), load_llm_settings()
    ds = load_dataset(dataset)
    verify_manifest(settings.data_dir, [s.path for s in ds.sources])
    records, _ = load_records(settings.data_dir, ds)
    det = json.loads((settings.out_dir / f"graph_{dataset}.json").read_text(encoding="utf-8"))
    stats, budget = RunStats(), Budget(max_requests or llm.max_requests_per_run)
    client = LLMClient(llm, Cache(settings.out_dir / "llm_cache"), budget, stats, offline=offline, transport=transport)
    en = Enricher(records, det, client, stats)
    t0, started, status, failed = time.monotonic(), datetime.now(timezone.utc), "complete", Counter()
    jobs = [("treatment", e) for e in en.treatment_pairs()] + [("case", r.id) for r in records]
    done = 0
    for kind, job in jobs:
        try:
            en.treat(job) if kind == "treatment" else en.case_meta(job)
            done += 1
        except BudgetExhausted:
            status = "budget_exhausted"
            break
        except CacheMiss:
            failed["not_cached"] += 1
        except (Truncated, ExtractionFailed, LLMError) as e:
            failed[type(e).__name__] += 1
    out = settings.out_dir / f"graph_{dataset}_llm.json"
    out.write_text(json.dumps(en.to_json(dataset), ensure_ascii=False, indent=1), encoding="utf-8")
    manifest = {"dataset": dataset, "model": llm.model, "status": status, "offline": offline,
                "started_at": started.isoformat(), "wall_s": round(time.monotonic() - t0, 1),
                "jobs_total": len(jobs), "jobs_done": done, "prompt_versions": [V_TREAT, V_CASE],
                "edges": dict(Counter(e["type"] for e in en.edges.values())), "dropped": dict(en.dropped),
                "failed": dict(failed), **{k: v for k, v in stats.to_json().items() if k not in ("failed",)}}
    mpath = settings.out_dir / "llm_runs" / f"{started.strftime('%Y%m%dT%H%M%S%fZ')}_enrich_{dataset}.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", default="all")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--max-requests", type=int)
    a = ap.parse_args(argv)
    m = run(a.dataset, a.offline, a.max_requests)
    print(json.dumps(m, indent=1))
    return 3 if m["status"] == "budget_exhausted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
