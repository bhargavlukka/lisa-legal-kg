"""analytics-server: precedence (PageRank), statute frequency, doctrine influence, cross-corpus bridges."""
from __future__ import annotations

from lisa.common.auth import require_admin
from lisa.servers.common import Ctx, cli, make_server, traced
from lisa.tools.analytics import Analytics

INSTRUCTIONS = ("Graph analytics over both corpora. Counts come from deterministic citation/statute edges; doctrine "
                "results come from the LLM tier (provenance llm).")


def build(ctx: Ctx, auth_enabled: bool = True):
    mcp = make_server("lisa-analytics", INSTRUCTIONS, ctx, auth_enabled)
    a = Analytics(ctx.store)
    t = traced("analytics")

    @mcp.tool()
    @t
    def most_cited_precedents(k: int = 10, scope: str = "all", method: str = "pagerank") -> dict:
        """Top-k cited authorities. scope: all (corpus cases + external authorities) | in_corpus.
        method: pagerank | indegree. Each row: cited_by count, pagerank, citing domains."""
        return {"scope": scope, "method": method, "results": a.most_cited(min(max(k, 1), 50), scope, method)}

    @mcp.tool()
    @t
    def statute_frequency(k: int = 10, domain: str | None = None) -> dict:
        """Statutes/regulations ranked by number of citing cases (then total mentions). domain optional."""
        return {"domain": domain, "results": a.statute_frequency(min(max(k, 1), 50), domain)}

    @mcp.tool()
    @t
    def doctrine_influence(k: int = 10) -> dict:
        """Legal doctrines (LLM-extracted) ranked by number of invoking cases and PageRank-weighted influence."""
        return {"results": a.doctrine_influence(min(max(k, 1), 50))}

    @mcp.tool()
    @t
    def cross_corpus_bridges(k: int = 20) -> dict:
        """SCOTUS opinions cited by BIA/AG decisions (cross-domain edges), with the citing cases and match basis."""
        return a.cross_corpus_bridges(min(max(k, 1), 60))

    @mcp.tool()
    @t
    def refresh_analytics() -> dict:
        """[admin] Recompute analytics from the current graph store."""
        require_admin(auth_enabled)
        nonlocal a
        a = Analytics(ctx.store)
        return {"status": "ok", "nodes": len(a.nodes), "edges": len(a.edges)}

    return mcp


def main() -> None:
    cli("analytics", build)


if __name__ == "__main__":
    main()
