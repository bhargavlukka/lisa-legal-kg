"""Locate a match in page text and return a verbatim, page-anchored quote."""
from __future__ import annotations

import re

from lisa.graph.canon import squash


def cite_pattern(cite: str) -> re.Pattern:
    """Whitespace-insensitive pattern for a citation string, bounded so 15 never matches inside 115."""
    chars = [ch for ch in squash(cite) if not ch.isspace()]
    return re.compile(r"(?<!\d)" + r"\s*".join(re.escape(ch) for ch in chars) + r"(?!\d)")


def find_evidence(pages: list[dict], pattern: re.Pattern, ctx: int = 60) -> dict | None:
    for p in pages:
        text = p["text"]
        m = pattern.search(text)
        if m:
            return {"page": p["page"], "quote": text[max(0, m.start() - ctx): m.end() + ctx]}
    return None
