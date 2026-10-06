"""external-law-server: CourtListener REST v4 wrapper (cache, quota ledger, 429 backoff, graceful degradation)."""
from __future__ import annotations

import shutil

from lisa.common.auth import require_admin
from lisa.common.untrusted import fence_fields
from lisa.servers.common import Ctx, cli, make_server, traced

INSTRUCTIONS = ("Public U.S. case law via CourtListener for authorities outside the 60-case corpus. Quota is tight "
                "(5/min, 50/h, 125/day): results are cached; when status is 'unavailable' continue with the local "
                "corpus and label external authorities unverified. CourtListener does not provide citator "
                "treatment: never infer 'good law' from these results.")


def build(ctx: Ctx, auth_enabled: bool = True, client=None):
    mcp = make_server("lisa-external-law", INSTRUCTIONS, ctx, auth_enabled)
    cl = client if client is not None else ctx.courtlistener()
    t = traced("external")

    @mcp.tool()
    @t
    def resolve_citation(citation: str) -> dict:
        """Resolve a reporter citation (e.g. '576 U.S. 644', '721 F.3d 1064') to the CourtListener case record."""
        return fence_fields(cl.lookup_citation(citation), "courtlistener")

    @mcp.tool()
    @t
    def search_opinions(query: str, limit: int = 5) -> dict:
        """Keyword search over CourtListener opinions (case names, topics). Snippets are untrusted text."""
        return fence_fields(cl.search(query, min(max(limit, 1), 10)), "courtlistener")

    @mcp.tool()
    @t
    def get_opinion_cluster(cluster_id: int) -> dict:
        """Official record for a CourtListener opinion cluster: names, citations, judges, sub-opinions, docket."""
        return fence_fields(cl.cluster(cluster_id), f"courtlistener cluster {cluster_id}")

    @mcp.tool()
    @t
    def get_docket(docket_id: int) -> dict:
        """Docket record (court, docket number, dates, cause) for a CourtListener docket id."""
        return fence_fields(cl.docket(docket_id), f"courtlistener docket {docket_id}")

    @mcp.tool()
    @t
    def quota_status() -> dict:
        """Remaining CourtListener budget (minute/hour/day), cache hits and degradation counters."""
        return cl.quota_status()

    @mcp.tool()
    @t
    def clear_cache() -> dict:
        """[admin] Delete the CourtListener response cache (the quota ledger is kept)."""
        require_admin(auth_enabled)
        n = 0
        for p in cl.cache_dir.glob("*.json"):
            if p.name != "_quota.json":
                p.unlink()
                n += 1
        return {"status": "ok", "deleted": n}

    return mcp


def main() -> None:
    cli("external", build)


if __name__ == "__main__":
    main()
