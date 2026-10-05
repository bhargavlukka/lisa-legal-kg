"""citation-verifier: deterministic firewall - cited cases must exist, quotes must match stored page text."""
from __future__ import annotations

from lisa.servers.common import Ctx, cli, make_server, traced
from lisa.tools.verifier import Verifier

INSTRUCTIONS = ("Deterministic citation firewall. Tiers: verified_in_corpus (case in graph + quote matches the "
                "stored page), resolved_externally (outside corpus, resolved by CourtListener), unverified. "
                "Run verify_answer on every draft answer before delivering it.")


def build(ctx: Ctx, auth_enabled: bool = True, external=None):
    mcp = make_server("lisa-citation-verifier", INSTRUCTIONS, ctx, auth_enabled)
    v = Verifier(ctx.store, external if external is not None else ctx.courtlistener())
    t = traced("verifier")

    @mcp.tool()
    @t
    def verify_citation(case: str, quote: str | None = None, page: int | None = None) -> dict:
        """Check one citation. case: corpus case id, name or reporter citation. For in-corpus cases give a verbatim
        quote and its page. Returns tier verified_in_corpus | resolved_externally | unverified with reasons."""
        return v.verify_citation(case, quote, page)

    @mcp.tool()
    @t
    def verify_answer(answer: str, citations: list[dict]) -> dict:
        """Gate a draft answer. Every legal sentence carries markers like [1]; citations[n-1] = {case, quote, page}.
        passed=false lists problems: uncited_claim, unverified_citation, dangling_marker, uncited_case_reference,
        unqualified_status_claim, no_citations. Fix them and re-verify before answering."""
        return v.verify_answer(answer, citations)

    return mcp


def main() -> None:
    cli("verifier", build)


if __name__ == "__main__":
    main()
