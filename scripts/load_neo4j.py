"""Load the served graph (deterministic + LLM tiers, per config serve:) into Neo4j."""
import sys

from lisa.common.config import load_serve_settings, load_settings
from lisa.graph.neo4j_load import Neo4jUnavailable, load, merge
from lisa.store import graph_files
import json

settings, serve = load_settings(), load_serve_settings()
graphs = [json.loads(p.read_text(encoding="utf-8")) for p in graph_files(settings, serve) if p.exists()]
try:
    print("neo4j:", load(merge(graphs), settings))
except Neo4jUnavailable as e:
    print(f"neo4j unavailable: {e}", file=sys.stderr)
    sys.exit(2)
