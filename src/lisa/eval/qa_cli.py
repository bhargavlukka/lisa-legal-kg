"""Run the Phase 5 golden questions through the KG agent and/or the RAG baseline, then write the comparison report.

  py scripts/eval_qa.py --system rag                  # RAG baseline (needs SharedLLM keys; LLM cache makes reruns free)
  py scripts/eval_qa.py --system kg --ids q01,q07     # KG agent (needs the four servers: scripts/serve_all.py)
  py scripts/eval_qa.py --report-only                 # rescore saved runs -> out/eval/qa_report.md
  py scripts/eval_qa.py --system kg --tag no_token    # degradation run: start the servers without COURTLISTENER_TOKEN

Runs append to out/eval/qa_<system>[_<tag>].jsonl and skip questions already answered there (--redo to rerun).
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import sys
from pathlib import Path

from lisa.common.config import REPO_ROOT, load_settings
from lisa.eval.qa import aggregate, load_golden, render_markdown, score

GOLDEN = REPO_ROOT / "config" / "eval" / "golden_questions.yaml"


def _load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    recs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["id"]: r for r in recs}                          # later lines win (reruns)


def _append(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _servers_up(agent) -> list[str]:
    down = []
    for name, url in agent.urls.items():
        host, port = url.split("//", 1)[1].split("/", 1)[0].rsplit(":", 1)
        try:
            socket.create_connection((host, int(port)), timeout=2).close()
        except OSError:
            down.append(f"{name} ({url})")
    return down


_PROVIDER_ERROR = re.compile(r"API Error|\b429\b|usage limit|rate.?limit", re.I)


def model_failed(rec: dict) -> str | None:
    """Why a turn is not a real result (model never answered, or the provider failed mid-turn), else None."""
    if rec.get("status") == "error":
        return "agent error"
    # some gateway routes report no usage, so zero tokens only means "no answer" when no draft was parsed either
    if not rec.get("input_tokens") and not rec.get("output_tokens") and not (rec.get("draft") or {}).get("parsed"):
        return "model never answered"
    if _PROVIDER_ERROR.search(str((rec.get("draft") or {}).get("answer") or "")):
        return "provider error in draft"
    return None


def run_kg(questions: list[dict], path: Path) -> int:
    import anyio

    from lisa.agent.agent import ResearchAgent
    agent = ResearchAgent(subject="lisa-eval")
    down = _servers_up(agent)
    if down:
        print("MCP servers not reachable: " + ", ".join(down) + " - start them with scripts/serve_all.py")
        return 2
    for q in questions:
        r = anyio.run(agent.ask, q["question"], None)
        rec = {"id": q["id"], "system": "kg", "status": r.status, "text": r.text, "draft": r.draft,
               "report": r.report, "latency_s": round(r.latency_s, 2), "input_tokens": r.trajectory.input_tokens,
               "output_tokens": r.trajectory.output_tokens, "model_calls": r.trajectory.model_calls,
               "tools": r.trajectory.names(), "revisions": r.revisions, "gate_calls": r.gate_calls}
        why = model_failed(rec)
        if why:
            # the model path failed (quota, 429, outage), possibly mid-turn: not a result - stop so a rerun resumes
            print(f"{q['id']}: {why}, not recorded - stopping (rerun to resume)\n{r.text[-300:]}", flush=True)
            return 3
        _append(path, rec)
        print(f"{q['id']}: {r.status} {r.latency_s:.0f}s tools={len(r.trajectory.tools)}", flush=True)
    return 0


def run_rag(questions: list[dict], path: Path, max_requests: int) -> int:
    from lisa.common.config import load_llm_settings, load_serve_settings
    from lisa.eval.rag import RagBaseline, fastembed_embedder
    from lisa.llm.budget import Budget, BudgetExhausted, RunStats
    from lisa.llm.cache import Cache
    from lisa.llm.client import LLMClient, LLMError
    from lisa.servers.common import Ctx
    from lisa.store import open_store
    from lisa.tools.verifier import Verifier

    settings, llm = load_settings(), load_llm_settings()
    store = open_store(settings, load_serve_settings())
    client = LLMClient(llm, Cache(settings.out_dir / "llm_cache"), Budget(max_requests), RunStats())
    rag = RagBaseline(store, client, Verifier(store, Ctx("lisa-eval", need_store=False).courtlistener()),
                      fastembed_embedder(), cache_dir=settings.out_dir / "eval")
    for q in questions:
        try:
            rec = rag.ask(q["question"])
        except BudgetExhausted:
            print("request budget exhausted - rerun to continue (cache keeps finished calls)")
            return 3
        except LLMError as e:
            print(f"{q['id']}: llm error: {e}")
            return 2
        _append(path, {"id": q["id"], "system": "rag", **rec})
        print(f"{q['id']}: {rec['status']} {rec['latency_s']:.0f}s{' (cached)' if rec['cached'] else ''}", flush=True)
    return 0


def report(eval_dir: Path, golden: list[dict]) -> Path:
    from lisa.agent.agent import MCP_TOOLS, META_TOOLS
    allowed = set(MCP_TOOLS + META_TOOLS)
    by_id = {q["id"]: q for q in golden}
    summary, rows = {}, {}
    for path in sorted(eval_dir.glob("qa_*.jsonl")):
        name = path.stem[3:]
        recs = _load(path)
        rows[name] = [score(by_id[i], recs[i], allowed) for i in by_id if i in recs]
        summary[name] = aggregate(rows[name])
    notes = [f"golden set: {len(golden)} questions ({GOLDEN.relative_to(REPO_ROOT).as_posix()})"]
    notes += [f"{s}: {summary[s]['n']}/{len(golden)} questions run" for s in summary]
    out = eval_dir / "qa_report.md"
    out.write_text(render_markdown(summary, rows, notes), encoding="utf-8")
    (eval_dir / "qa_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--system", choices=["kg", "rag"])
    ap.add_argument("--ids", help="comma-separated question ids (default: all)")
    ap.add_argument("--tag", help="suffix for the run file, e.g. no_token")
    ap.add_argument("--redo", action="store_true", help="rerun questions already in the run file")
    ap.add_argument("--max-requests", type=int, default=60, help="RAG LLM request budget for this run")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    golden = load_golden(GOLDEN)
    eval_dir = load_settings().out_dir / "eval"
    code = 0
    if not a.report_only:
        if not a.system:
            ap.error("--system is required unless --report-only")
        path = eval_dir / f"qa_{a.system}{'_' + a.tag if a.tag else ''}.jsonl"
        wanted = set(a.ids.split(",")) if a.ids else None
        done = set() if a.redo else set(_load(path))
        todo = [q for q in golden if (wanted is None or q["id"] in wanted) and q["id"] not in done]
        print(f"{a.system}: {len(todo)} questions to run -> {path}")
        code = run_kg(todo, path) if a.system == "kg" else run_rag(todo, path, a.max_requests)
    print(f"report: {report(eval_dir, golden)}")
    return code
