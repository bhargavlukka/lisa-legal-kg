"""Graph store backends behind one interface; `open_store` picks one from config (graph.backend)."""
from __future__ import annotations

from lisa.common.config import ServeSettings, Settings


def graph_files(settings: Settings, serve: ServeSettings) -> list:
    """Deterministic graph first, then every LLM-tier graph listed in config."""
    out = settings.out_dir
    return [out / f"graph_{serve.dataset}.json"] + [out / f"graph_{d}_llm.json" for d in serve.llm_graphs]


def open_store(settings: Settings, serve: ServeSettings):
    if serve.backend == "neo4j":
        from lisa.store.neo4j_store import Neo4jStore
        return Neo4jStore(settings)
    from lisa.store.memory import MemoryStore
    files = graph_files(settings, serve)
    if not files[0].exists():
        raise RuntimeError(f"{files[0]} not found - run scripts/build_graph.py --dataset {serve.dataset} first")
    return MemoryStore.from_files(files)
