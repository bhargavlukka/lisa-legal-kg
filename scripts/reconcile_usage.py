"""Rewrite a KG run's token counts from the metering proxy ledger (out/llm_usage.jsonl).

Each ledger row carries the API message id; the Claude CLI transcript of the turn's SDK session lists the message ids
of that turn, so every metered call is attributed to exactly one question. Used once on qa_kg_metered*.jsonl, whose
revision turns (q08, q13, q24, q27) had under-counted output tokens before the agent.py fix.

    .venv/Scripts/python scripts/reconcile_usage.py out/eval/qa_kg_metered.jsonl [more run files]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSCRIPTS = Path.home() / ".claude" / "projects" / str(ROOT / "src" / "lisa" / "agent").replace(":", "-").replace(
    "\\", "-").replace("/", "-").replace(" ", "-")


def main(paths: list[str]) -> int:
    ledger = {}
    for line in open(ROOT / "out" / "llm_usage.jsonl", encoding="utf-8"):
        x = json.loads(line)
        ledger[x["id"]] = x
    trajs = [json.loads(line) for line in open(ROOT / "out" / "trajectories.jsonl", encoding="utf-8")]
    used: set = set()
    for path in map(Path, paths):
        recs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        for r in recs:
            sid = r.get("sdk_session_id") or next(
                t["sdk_session_id"] for t in reversed(trajs) if abs(t["latency_s"] - r["latency_s"]) < 0.05)
            ids = {json.loads(line)["message"].get("id")
                   for line in open(TRANSCRIPTS / f"{sid}.jsonl", encoding="utf-8")
                   if json.loads(line).get("type") == "assistant"}
            rows = [ledger[i] for i in ids if i in ledger]
            used |= {x["id"] for x in rows}
            new = {"input_tokens": sum(x["input_tokens"] for x in rows),
                   "output_tokens": sum(x["output_tokens"] for x in rows), "model_calls": len(rows),
                   "sdk_session_id": sid, "usage_source": "proxy_ledger"}
            if (r["input_tokens"], r["output_tokens"]) != (new["input_tokens"], new["output_tokens"]):
                print(f"{r['id']}: in {r['input_tokens']} -> {new['input_tokens']}, "
                      f"out {r['output_tokens']} -> {new['output_tokens']}")
            r.update(new)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    print(f"ledger calls attributed: {len(used)}/{len(ledger)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
