"""Small text helpers shared by the store backends: tokenizing, BM25-style scoring, snippets."""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
STOP = frozenset("""a an and are as at be by for from has have in is it its of on or that the this to was were
which with what who whom how did does do not any all their there these those into under over than then
case cases court decision decisions""".split())


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOP and len(t) > 1]


class BM25:
    """Okapi BM25 over a fixed list of documents (k1=1.5, b=0.75)."""

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(tokens(d)) for d in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 0.0
        df: Counter = Counter()
        for c in self.tf:
            df.update(c.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query: str) -> list[float]:
        q = tokens(query)
        out = []
        for tf, ln in zip(self.tf, self.len):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * ln / (self.avg or 1)))
            out.append(s)
        return out


def snippet(text: str, query: str, width: int = 240) -> str:
    """The window of `text` around the first query-token hit (whitespace squashed)."""
    flat = re.sub(r"\s+", " ", text).strip()
    low = flat.lower()
    hits = [low.find(t) for t in tokens(query)]
    hits = [h for h in hits if h >= 0]
    start = max(0, min(hits) - width // 3) if hits else 0
    return ("…" if start else "") + flat[start:start + width] + ("…" if start + width < len(flat) else "")
