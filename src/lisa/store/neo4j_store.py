"""Neo4j backend: Neo4j is the system of record; the serving working set is read from it with Cypher.

The 60-case graph (~4k nodes) fits in memory many times over, so the server reads it once at startup and answers
tool calls from the same code path as the memory backend (identical results by construction). Ad-hoc graph
questions go to Neo4j live through `run_cypher` (read-only, admin role).
"""
from __future__ import annotations

import json

from lisa.common.config import Settings
from lisa.store.memory import MemoryStore

_WRITE = ("create", "merge", "delete", "set ", "remove", "drop", "load csv", "call dbms", "call apoc")


def _decode(props: dict) -> tuple[dict, dict]:
    p = dict(props)
    meta = {"provenance": p.pop("provenance", "deterministic"), "confidence": p.pop("confidence", 1.0),
            "evidence": json.loads(p.pop("evidence", "[]") or "[]"), "extractor": p.pop("extractor", None)}
    return p, meta


class Neo4jStore(MemoryStore):
    backend = "neo4j"

    def __init__(self, settings: Settings):
        from neo4j import GraphDatabase
        self._driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
        nodes, edges = [], []
        with self._driver.session() as s:
            for rec in s.run("MATCH (n) RETURN labels(n)[0] AS label, properties(n) AS p"):
                props, meta = _decode(rec["p"])
                nodes.append({"id": props["id"], "label": rec["label"], "props": props, **meta})
            for rec in s.run("MATCH (a)-[r]->(b) RETURN type(r) AS t, a.id AS s, b.id AS d, properties(r) AS p"):
                props, meta = _decode(rec["p"])
                edges.append({"type": rec["t"], "source": rec["s"], "target": rec["d"], "props": props, **meta})
        super().__init__([{"nodes": nodes, "edges": edges}])

    def run_cypher(self, query: str, limit: int = 50) -> list[dict]:
        if any(w in query.lower() for w in _WRITE):
            raise PermissionError("run_cypher is read-only")
        with self._driver.session(default_access_mode="READ") as s:
            return [r.data() for r in s.run(query)][:limit]
