"""Quote verification against stored page text. Provenance, confidence and evidence_strength are set by rule."""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

MIN_QUOTE = 12          # squashed chars; shorter quotes ("the Court") match anywhere and prove nothing
DEFAULT_CONFIDENCE = 0.7

_MARKERS = re.compile(r"<<<PART BEGINS:[^>]*>>>|=====\s*\[\[PAGE[^\]]*\]\]\s*=====")
_ELLIPSIS = re.compile(r"\[?(?:\.\s*){3}\]?|…")
_DROP = re.compile("[\\s\\-­‐-―\"'`‘-‟′″�]+")


def squash(s: str) -> str:
    """Matching key: page/part markers removed, then whitespace, hyphens/dashes and all quote marks dropped."""
    return _DROP.sub("", _MARKERS.sub("", s))


def _pieces(quote: str) -> list[str]:
    """Squashed quote pieces split at ellipses; edge punctuation a model adds ("... residence.") is dropped."""
    return [p for p in (squash(x).strip(".,;:") for x in _ELLIPSIS.split(quote or "")) if p]


@dataclass(frozen=True)
class Span:
    page: int
    start: int
    end: int


class PageIndex:
    """Squashed text of a unit's pages, concatenated, with page offsets."""

    def __init__(self, raw_pages: dict[int, str]):
        self.pages = sorted(raw_pages)
        self._start: dict[int, int] = {}
        self._end: dict[int, int] = {}
        parts, pos = [], 0
        for p in self.pages:
            s = squash(raw_pages[p])
            self._start[p], self._end[p] = pos, pos + len(s)
            parts.append(s)
            pos += len(s)
        self.text = "".join(parts)
        self._starts = [self._start[p] for p in self.pages]

    def page_at(self, offset: int) -> int:
        return self.pages[bisect.bisect_right(self._starts, offset) - 1]

    def locate(self, quote: str, page: int | None) -> Span | None:
        pieces = _pieces(quote)
        if not pieces or max(map(len, pieces)) < MIN_QUOTE or page not in self._start:
            return None
        i = self.pages.index(page)
        prev, nxt = self.pages[max(i - 1, 0)], self.pages[min(i + 1, len(self.pages) - 1)]
        for lo, hi in ((self._start[page], self._end[nxt]), (self._start[prev], self._end[nxt])):
            pos, start = lo, None
            for piece in pieces:          # every piece verbatim, in order
                k = self.text.find(piece, pos, hi)
                if k < 0:
                    break
                start = k if start is None else start
                pos = k + len(piece)
            else:
                return Span(self.page_at(start), start, pos)
        return None


def evidence_strength(verified_quotes: list[str]) -> str:
    if len(verified_quotes) >= 2 or any(len(q.split()) >= 15 for q in verified_quotes):
        return "strong"
    return "moderate" if verified_quotes else "weak"


def _as_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def verify_item(item: dict, index: PageIndex) -> dict:
    out = dict(item)
    ev = item.get("evidence")
    raw = [e for e in ev if isinstance(e, dict) and isinstance(e.get("quote"), str)] if isinstance(ev, list) else []
    kept = []
    for e in raw:
        sp = index.locate(e["quote"], _as_int(e.get("page")))
        if sp:
            kept.append({"page": sp.page, "quote": e["quote"], "verified": True, "span": [sp.start, sp.end]})
    try:
        conf = min(max(float(item.get("confidence", DEFAULT_CONFIDENCE)), 0.0), 1.0)
    except (TypeError, ValueError):
        conf = DEFAULT_CONFIDENCE
    if kept:
        evidence, prov = kept, "llm"
        if len(kept) < len(raw):
            conf *= 0.8
    else:
        evidence, prov = [{"page": _as_int(e.get("page")), "quote": e["quote"], "verified": False} for e in raw], "unverified"
        conf = min(conf, 0.3)
    out.update(evidence=evidence, provenance=prov, evidence_verified=bool(kept), confidence=round(conf, 4),
               evidence_strength=evidence_strength([e["quote"] for e in kept]))
    return out
