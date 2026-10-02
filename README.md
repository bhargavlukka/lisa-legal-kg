# LISA — Legal Knowledge-Graph Research Agent

Self-hosted legal research over two U.S. case-law corpora (30 BIA/AG immigration decisions, 30 Supreme Court
opinions): a knowledge graph exposed as MCP tools, driven by an LLM agent, with mechanically verified citations.

> Status: **Phase 1 — graph foundation** (deterministic extraction tier + Neo4j). Later phases: LLM extraction &
> gold-standard eval, four MCP servers, agent, evaluation, security/ops.

## Setup
```bash
py -3 -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
cp .env.example .env        # set LISA_DATA_DIR to LISA_Project_Package/data and NEO4J_PASSWORD
docker compose --env-file .env up -d neo4j
```
The case data is **not** in this repo. Every input file is verified against the package's `manifest.json` SHA-256 before use.

## Build the graph
```bash
.venv/Scripts/python scripts/build_graph.py --dataset all --check   # both corpora + cross-domain edges
.venv/Scripts/python scripts/build_graph.py --dataset immigration   # one domain — same code, different YAML
.venv/Scripts/python -m pytest
```
`--check` asserts every edge in `selection_report.json` (27 immigration-internal, 61 SCOTUS-internal,
50 cross-domain entries) is present. Output: `out/graph_<dataset>.json`; Neo4j browser at http://localhost:7474.
Without a reachable Neo4j the JSON is still written and the command exits with code 3; use `--no-load` to skip loading.

Current result on the provided packs: 60 cases, 138/138 expected edges found, 0 extra, 0 unverified edges.

## Graph schema (deterministic tier)
Nodes: `Case`, `Authority` (out-of-corpus citation), `Statute`, `Regulation`, `Page`.
Edges: `CITES` (`scope`: internal / cross_domain / external; `bases`: detected_citation / name / reporter),
`MENTIONS_STATUTE`, `HAS_PAGE`. Every node and edge has `provenance`, `confidence`, and page-anchored `evidence`.
Case legal status is always `not verified`. Cases without a U.S. Reports citation yet (recent slip opinions) get
`canon_cite = nocite:<id>`.

## Domains are configuration
`config/domains/*.yaml` maps record fields and statute patterns; `config/datasets/*.yaml` picks files and cross-domain
rules. Adding or switching a corpus requires no code changes.

## Phase 2 — LLM extraction tier and gold evaluation

Needs an LLM key in `.env` (see `.env.example`). Endpoint, auth style, model and limits live in
`config/settings.yaml` → `llm:` (currently `gpt-oss:120b` on Ollama Cloud with `OLLAMA_API_KEY`; the SharedLLM
gateway is a config switch — see `docs/decision_log.md`).

```bash
.venv/Scripts/python scripts/extract_llm.py --dataset gold_eval          # exit 3 = budget reached; rerun to resume
.venv/Scripts/python scripts/eval_extraction.py                           # -> out/eval/extraction_report.md
.venv/Scripts/python scripts/extract_llm.py --dataset immigration         # then litigation
.venv/Scripts/python scripts/extract_llm.py --dataset gold_eval --offline # replay from cache, no API calls
```

Outputs: `out/llm_<ds>.json` (gold schema per unit, `llm`/`unverified` provenance by quote verification),
`out/graph_<ds>_llm.json` (FOLLOWS / DISTINGUISHES / OVERRULES / CITES_LLM / AUTHORED_BY / INVOKES_DOCTRINE,
joined to Phase 1 node ids), `out/llm_runs/*.json` (requests, tokens, 429s, failures per run).
The deterministic tier (`out/graph_<ds>.json`) is not changed by Phase 2. Results: `docs/eval/extraction_report.md`.

## Docs
- Design: `docs/design/phase1-graph-foundation.md`
- Plan: `docs/plans/phase1-graph-foundation.md`
- Phase 2 design / plan: `docs/design/phase2-llm-extraction.md`, `docs/plans/phase2-llm-extraction.md`
- Decisions: `docs/decision_log.md`; extraction results: `docs/eval/extraction_report.md`
