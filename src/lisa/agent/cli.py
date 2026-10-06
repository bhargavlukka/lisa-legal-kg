"""Ask LISA a legal research question. Sessions persist in out/sessions/<name>.json across restarts."""
from __future__ import annotations

import argparse
import json
import sys

import anyio

from lisa.agent.agent import ResearchAgent
from lisa.agent.memory.store import SessionMemory


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("question", nargs="?", help="omit for an interactive session")
    ap.add_argument("--session", default="default", help="research session name (memory survives restarts)")
    ap.add_argument("--json", action="store_true", help="print the full turn record as JSON")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    agent = ResearchAgent()
    mem = SessionMemory(agent.settings.out_dir / agent.agent.sessions_dir, a.session)
    questions = [a.question] if a.question else iter(lambda: input("\nLISA> ").strip(), "exit")
    for q in questions:
        if not q:
            continue
        r = anyio.run(agent.ask, q, mem)
        if a.json:
            print(json.dumps({"status": r.status, "text": r.text, "revisions": r.revisions,
                              "latency_s": round(r.latency_s, 1), "tools": r.trajectory.names(),
                              "tokens": [r.trajectory.input_tokens, r.trajectory.output_tokens]}, indent=1))
        else:
            print(r.text)
            print(f"\n[{r.status} | {r.latency_s:.0f}s | tools: {len(r.trajectory.tools)} | revisions: {r.revisions}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
