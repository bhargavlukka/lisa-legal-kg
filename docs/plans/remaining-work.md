# Remaining work — resume point

Branch `phase3-mcp-servers` (stacked on phase 2). Model path: SharedLLM pool, `~z-ai/glm-flash-latest`
(config/settings.yaml). Tests: `.venv/Scripts/python -m pytest -q` (275 pass).

## Status (2026-10-05 evening)

| # | Task | Status |
|---|---|---|
| 1 | RAG baseline, 28 golden questions | done (`out/eval/qa_rag.jsonl`) |
| 2 | KG agent run, 28 questions | done 28/28 verified (3 shards: `qa_kg.jsonl`, `qa_kg_s2.jsonl`, `qa_kg_s3.jsonl`; the report merges them) |
| 3 | Degradation run (no CourtListener token) | done: q24, q25 -> `qa_kg_no_token.jsonl` (servers on 8112/8114 with `LISA_OUT_DIR=out_notoken`, empty cache) |
| 4 | Review fixes (cache, verifier, fencing, JWT, compose, docs) + 3 security-review rounds on the verifier | done |
| 5 | Offline re-verification of stored KG drafts with the hardened gate (4 security-review rounds) | done: `scripts/eval_qa.py --reverify kg` -> `out/eval/reverify_kg.md` (25/25 pass) |
| 6 | Docker build + compose live | done: GitHub Actions `docker-stack` passes (both images, compose up, auth/roles/tools/degradation smoke, Neo4j backend, agent image); fixes: editable install, container UID for the ./out mount |
| 7 | `--report-only` + `--reverify kg` (25/28) / `kg_no_token` (2/2), reports copied to `docs/eval/` | done |
| 8 | `docs/evaluation_report.md` sections 2-4 | done (final numbers being refreshed for 28/28) |
| 9 | PR `phase3-mcp-servers` -> `main` (contains phase 2), links to the owner | done (PR #2 merged) |
| 10 | Cost per query (spec §7 #11): metering proxy, gateway pricing, metered KG rerun (`qa_kg_metered*.jsonl`) | done |

## Resume commands

```bash
# servers (if not running)
.venv/Scripts/python scripts/serve_all.py
# finish any unfinished KG questions (each command skips questions already in its file)
.venv/Scripts/python scripts/eval_qa.py --system kg --ids q13,q14,q15,q16,q17,q18
.venv/Scripts/python scripts/eval_qa.py --system kg --tag s2 --ids q19,q20,q21,q22,q23
.venv/Scripts/python scripts/eval_qa.py --system kg --tag s3 --ids q24,q25,q26,q27,q28
# merge shards, then report
cat out/eval/qa_kg_s2.jsonl out/eval/qa_kg_s3.jsonl >> out/eval/qa_kg.jsonl && rm out/eval/qa_kg_s2.jsonl out/eval/qa_kg_s3.jsonl
.venv/Scripts/python scripts/eval_qa.py --report-only
.venv/Scripts/python scripts/eval_qa.py --reverify kg
```
