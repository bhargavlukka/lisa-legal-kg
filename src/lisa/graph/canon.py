"""Canonical citation ids: the same real-world authority gets the same id regardless of typography."""
from __future__ import annotations

import re
from dataclasses import dataclass

_FED = r"F\.\s?(?:2d|3d|4th)|F\.\s?Supp\.(?:\s?[23]d)?|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|Fed\.\s?Appx\."


@dataclass(frozen=True)
class Canon:
    id: str
    kind: str      # case | statute | regulation | other
    display: str


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def canon(cite: str) -> Canon:
    c = squash(cite)
    if m := re.search(r"(\d+)\s*I&N\s*Dec\.?\s*(\d+)", c):
        return Canon(f"in_dec:{m[1]}_{m[2]}", "case", f"{m[1]} I&N Dec. {m[2]}")
    if m := re.search(r"(\d+)\s*U\.\s*S\.\s*C\.\s*(?:A\.\s*)?§*\s*(\d+[a-z]?)", c):
        return Canon(f"usc:{m[1]}_{m[2].lower()}", "statute", f"{m[1]} U.S.C. § {m[2]}")
    if m := re.search(r"(\d+)\s*C\.\s*F\.\s*R\.\s*§*\s*(\d+)", c):
        return Canon(f"cfr:{m[1]}_{m[2]}", "regulation", f"{m[1]} C.F.R. Part {m[2]}")
    if m := re.search(r"(\d+)\s*U\.\s*S\.\s*(\d+)", c):
        return Canon(f"us:{m[1]}_{m[2]}", "case", f"{m[1]} U.S. {m[2]}")
    if m := re.search(rf"(\d+)\s+({_FED})\s*(\d+)", c):
        rep = re.sub(r"[^a-z0-9]+", "", m[2].lower())
        return Canon(f"{rep}:{m[1]}_{m[3]}", "case", f"{m[1]} {squash(m[2])} {m[3]}")
    slug = re.sub(r"[^a-z0-9]+", "_", c.lower()).strip("_")[:60]
    return Canon(f"other:{slug}", "other", c)
