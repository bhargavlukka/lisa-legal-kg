"""Cross-domain CITES derived from full text: target case titles and U.S.-reporter citations."""
from __future__ import annotations

import re
from dataclasses import dataclass

from lisa.graph.canon import canon, squash
from lisa.graph.evidence import find_evidence
from lisa.graph.loader import Record

CONFIDENCE = {"name": 0.9, "reporter": 1.0}


@dataclass(frozen=True)
class Match:
    source: str
    target: str
    basis: str
    evidence: dict | None


def _name_pattern(title: str) -> re.Pattern:
    return re.compile(r"\s+".join(re.escape(w) for w in squash(title).split(" ")), re.IGNORECASE)


def _reporter_pattern(citation: str | None) -> re.Pattern | None:
    if not citation:
        return None
    c = canon(citation)
    if not c.id.startswith("us:"):
        return None
    vol, page = c.id[3:].split("_")
    return re.compile(rf"(?<!\d){vol}\s*U\.\s*S\.\s*{page}(?!\d)")


def find_matches(sources: list[Record], targets: list[Record]) -> list[Match]:
    pats = []
    for t in targets:
        pats.append((t.id, "name", _name_pattern(t.title)))
        rp = _reporter_pattern(t.citation)
        if rp is not None:
            pats.append((t.id, "reporter", rp))
    out = []
    for s in sources:
        for tid, basis, pat in pats:
            ev = find_evidence(s.pages, pat)
            if ev is not None:
                out.append(Match(s.id, tid, basis, ev))
            elif pat.search(s.text):
                out.append(Match(s.id, tid, basis, None))
    return out
