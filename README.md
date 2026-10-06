# LISA — Legal Knowledge-Graph Research Agent

**Problem.** An immigration litigation team needs research answers it can trust: which decisions cite a precedent,
how BIA decisions rely on Supreme Court holdings, which statutes dominate a corpus. LLM answers over case law
fabricate citations and quotes. LISA answers from a knowledge graph of two corpora (30 BIA / Attorney General
decisions, 30 U.S. Supreme Court opinions) plus CourtListener, through an agent whose every citation is checked by
a deterministic verifier: quotes must exist on the stored page, cases must exist, uncited legal claims are blocked.
An answer that cannot pass is salvaged to its verified parts or refused.

## Where things are

| deliverable | location |
|---|---|
| Architecture (+ diagram) | [docs/architecture.md](docs/architecture.md), [diagrams/architecture.mmd](diagrams/architecture.mmd) |
| Decision log (each choice vs alternatives) | [docs/decision_log.md](docs/decision_log.md) |
| Threat model | [docs/threat_model.md](docs/threat_model.md) |
| Model-constraints memo | [docs/model_constraints.md](docs/model_constraints.md) |
| Evaluation report (RAG vs KG, extraction P/R, failures) | [docs/evaluation_report.md](docs/evaluation_report.md), raw: [docs/eval/](docs/eval/) |
| Golden question set (28) | [config/eval/golden_questions.yaml](config/eval/golden_questions.yaml) |
| Graph build / LLM extraction | `src/lisa/graph`, `src/lisa/extract` |
| MCP servers | `src/lisa/servers` (graph, citation_verifier, analytics_server, external_law_server) |
| Agent: skill, subagent, memory, guardrails | `src/lisa/agent` (`.claude/skills/legal-research`, `subagents/`, `memory/`, `guardrails/`) |
| Evaluation code | `src/lisa/eval` (extraction_eval, qa, rag, qa_cli) |
| Config (domains, datasets, model, limits) | `config/` |
| Data checksums + rebuild | `data_manifest/manifest.json`, `scripts/rebuild.sh`, `scripts/rebuild.ps1` |
| Compose / images | `docker-compose.yml`, `Dockerfile` |

## Architecture in one paragraph

A deterministic tier builds Case / Authority / Statute / Page nodes and CITES / MENTIONS_STATUTE edges from detected
citations; an LLM tier (through the SharedLLM gateway) adds doctrines, judges and FOLLOWS /
DISTINGUISHES / OVERRULES, each kept only if its supporting quote is found on the page. Both tiers carry
provenance and confidence and are stored separately, loaded into Neo4j or served from memory. Four MCP servers
(graph, citation-verifier, analytics, external-law/CourtListener) expose the graph over HTTP with signed JWTs and
researcher/admin roles. A Claude Agent SDK agent with a legal-research skill, a citation-chaser subagent and
persistent session memory calls those tools; a code gate runs the verifier on every draft before delivery.
OpenTelemetry traces go to Jaeger. Details: [docs/architecture.md](docs/architecture.md).

## Setup

Requirements: Python 3.12, the `LISA_Project_Package` (case data is **not** in this repo), a SharedLLM key (the
model path is in [model_constraints.md](docs/model_constraints.md)), optionally a CourtListener token, Docker for
the compose stack.

```bash
py -3 -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev,agent,rag]"     # Linux/macOS: .venv/bin/python
cp .env.example .env     # set LISA_DATA_DIR, NEO4J_PASSWORD, SHAREDLLM_API_KEY, LISA_AUTH_SECRET (>= 32 random chars),
                         # COURTLISTENER_TOKEN (optional)
.venv/Scripts/python -m pytest                                 # ~257 tests, no network
```

## Build the graph

```bash
scripts/rebuild.sh            # or scripts/rebuild.ps1 - verifies checksums, builds every graph, replays LLM tier
scripts/rebuild.sh --live     # allow model calls for anything not in out/llm_cache
```

Step by step: `scripts/build_graph.py --dataset all --check` (deterministic tier; `--check` asserts all 138 edges of
`selection_report.json`), `scripts/extract_llm.py --dataset gold_eval` (LLM tier on the gold units),
`scripts/enrich_llm.py` (LLM tier on the 60 served cases), `scripts/load_neo4j.py`. Switching corpus is config only:
`--dataset immigration` / `litigation` uses `config/datasets/*.yaml` and `config/domains/*.yaml`.

## Run

Local processes (no Docker needed):

```bash
.venv/Scripts/python scripts/serve_all.py                                   # 4 servers on 127.0.0.1:8101-8104
.venv/Scripts/python scripts/ask.py "Which BIA decisions rely on Pereida v. Wilkinson?"
.venv/Scripts/python scripts/ask.py --session matter-42                     # interactive; memory survives restarts
.venv/Scripts/python scripts/issue_token.py me admin                        # token for direct MCP access
```

Full stack with Docker:

```bash
docker compose --env-file .env up -d --build                                # neo4j, jaeger, 4 servers
docker compose --env-file .env run --rm agent "Which immigration decisions cite Pereira v. Sessions?"
```

Traces: Jaeger UI at http://localhost:16686 (set `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` when running
locally); every service also writes `out/traces/<service>.jsonl`. Neo4j browser: http://localhost:7474.

## Reproduce the evaluation

```bash
.venv/Scripts/python scripts/eval_extraction.py                   # extraction P/R vs gold -> out/eval/extraction_report.md
.venv/Scripts/python scripts/eval_qa.py --system rag              # RAG baseline on the golden set
.venv/Scripts/python scripts/eval_qa.py --system kg               # KG agent (servers must be running)
COURTLISTENER_TOKEN= .venv/Scripts/python scripts/serve_all.py    # restart servers without the token, then:
.venv/Scripts/python scripts/eval_qa.py --system kg --tag no_token --ids q24,q25    # degradation run
.venv/Scripts/python scripts/eval_qa.py --report-only             # -> out/eval/qa_report.md, qa_summary.json
```

All LLM responses are cached in `out/llm_cache`, so extraction and RAG reruns cost no model calls; QA runs append to
`out/eval/qa_<system>.jsonl` and skip questions already answered (`--redo` to rerun).

## Security notes

Secrets only via environment (`.env` is git-ignored); compose binds every port to 127.0.0.1 and gives the LLM keys
only to the agent. Case text reaches the model inside untrusted-text fences, and the verifier gate - not the prompt -
decides what is delivered. See [docs/threat_model.md](docs/threat_model.md).
