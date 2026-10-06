#!/usr/bin/env bash
# Full rebuild from the LISA package (LISA_DATA_DIR in .env). Every LLM step replays from out/llm_cache when the
# cache is present, so a rebuild with a warm cache makes zero model calls. Add --live to allow model calls.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python}
OFFLINE="--offline"; [[ "${1:-}" == "--live" ]] && OFFLINE=""

$PY -m lisa.graph.verify_data                                   # checksums + 60-case subset
for ds in all immigration litigation gold_eval; do               # deterministic tier (no LLM)
  $PY scripts/build_graph.py --dataset "$ds" --no-load
done
$PY scripts/extract_llm.py --dataset gold_eval $OFFLINE          # LLM tier on the gold cases
$PY scripts/eval_extraction.py                                   # precision / recall vs gold
$PY scripts/enrich_llm.py $OFFLINE                               # LLM tier on the 60 served cases
$PY scripts/load_neo4j.py || echo "neo4j not reachable - graph JSON is still served by the memory backend"
echo "rebuild complete: out/graph_*.json, out/eval/extraction_report.md"
