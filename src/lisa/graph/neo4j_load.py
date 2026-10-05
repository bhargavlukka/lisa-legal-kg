"""Load graph JSON into Neo4j. Idempotent: MERGE on id; labels/types are whitelisted (never from data)."""
from __future__ import annotations

import json
from collections import defaultdict

from neo4j import GraphDatabase
from neo4j.exceptions import DriverError, Neo4jError

from lisa.common.config import Settings

LABELS = ("Case", "Authority", "Statute", "Regulation", "Page", "Doctrine", "Judge")
REL_TYPES = ("CITES", "MENTIONS_STATUTE", "HAS_PAGE",                                   # deterministic tier
             "FOLLOWS", "DISTINGUISHES", "OVERRULES", "CITES_LLM", "INVOKES_DOCTRINE", "AUTHORED_BY")  # LLM tier
BATCH = 500


class Neo4jUnavailable(RuntimeError):
    pass


def node_props(item: dict) -> dict:
    p = {k: v for k, v in item["props"].items() if v is not None}
    p.update(provenance=item["provenance"], confidence=item["confidence"],
             evidence=json.dumps(item["evidence"], ensure_ascii=False), extractor=item["extractor"])
    return p


def _first_line(e: Exception) -> str:
    return (str(e).strip().splitlines() or [type(e).__name__])[0]


def _chunks(rows: list) -> list[list]:
    return [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]


def merge(graphs: list[dict]) -> dict:
    """Deterministic graph first, LLM-tier graphs after; first node per id wins, dangling edges dropped."""
    nodes: dict[str, dict] = {}
    for g in graphs:
        for n in g["nodes"]:
            nodes.setdefault(n["id"], n)
    edges, seen = [], set()
    for g in graphs:
        for e in g["edges"]:
            key = (e["type"], e["source"], e["target"])
            if key in seen or e["source"] not in nodes or e["target"] not in nodes:
                continue
            seen.add(key)
            edges.append({**e, "source_label": nodes[e["source"]]["label"], "target_label": nodes[e["target"]]["label"]})
    return {"nodes": list(nodes.values()), "edges": edges}


def load(graph: dict, settings: Settings) -> dict:
    if not settings.neo4j_password:
        raise Neo4jUnavailable("NEO4J_PASSWORD is not set")
    try:
        driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    except (DriverError, Neo4jError, ValueError) as e:
        raise Neo4jUnavailable(_first_line(e)) from e
    try:
        driver.verify_connectivity()
    except (DriverError, Neo4jError, OSError) as e:
        driver.close()
        raise Neo4jUnavailable(_first_line(e)) from e

    nodes: dict[str, list] = defaultdict(list)
    edges: dict[tuple, list] = defaultdict(list)
    for n in graph["nodes"]:
        if n["label"] not in LABELS:
            raise ValueError(f"unknown node label {n['label']!r}")
        nodes[n["label"]].append({"id": n["id"], "props": node_props(n)})
    for e in graph["edges"]:
        if e["type"] not in REL_TYPES:
            raise ValueError(f"unknown edge type {e['type']!r}")
        edges[(e["type"], e["source_label"], e["target_label"])].append(
            {"source": e["source"], "target": e["target"], "props": node_props(e)})

    try:
        with driver.session() as s:
            for label in LABELS:
                s.run(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
                      f"FOR (n:{label}) REQUIRE n.id IS UNIQUE").consume()
            for label, rows in nodes.items():
                for chunk in _chunks(rows):
                    s.run(f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row.props",
                          rows=chunk).consume()
            for (etype, sl, tl), rows in edges.items():
                for chunk in _chunks(rows):
                    s.run(f"UNWIND $rows AS row MATCH (a:{sl} {{id: row.source}}) MATCH (b:{tl} {{id: row.target}}) "
                          f"MERGE (a)-[r:{etype}]->(b) SET r += row.props", rows=chunk).consume()
    except (DriverError, Neo4jError) as e:
        raise Neo4jUnavailable(f"load interrupted: {_first_line(e)}") from e
    finally:
        driver.close()
    return {"nodes": sum(len(v) for v in nodes.values()), "edges": sum(len(v) for v in edges.values())}
