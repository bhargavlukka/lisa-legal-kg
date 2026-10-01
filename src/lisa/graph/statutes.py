"""Statute / regulation mentions in page text, each with page number and verbatim quote."""
from __future__ import annotations

import re
from dataclasses import dataclass

# INA section -> 8 U.S.C. section (most-cited sections in the immigration corpus)
INA_TO_USC = {
    "101": "1101", "208": "1158", "212": "1182", "235": "1225", "237": "1227",
    "239": "1229", "240": "1229a", "240A": "1229b", "240B": "1229c", "241": "1231",
}

_PATTERNS = {
    "usc": re.compile(r"(?<!\d)(\d+)\s*U\.\s*S\.\s*C\.\s*(?:A\.\s*)?§*\s*(\d+[a-z]?)"),
    "cfr": re.compile(r"(?<!\d)(\d+)\s*C\.\s*F\.\s*R\.\s*(?:§+\s*)?(\d+)(?:\.\d+)?"),
    "ina_symbol": re.compile(r"\bINA\s*§+\s*(\d+[A-Z]?)"),
    "ina_section": re.compile(
        r"\bsection\s+(\d+[A-Z]?)(?:\([0-9a-zA-Z]+\))*\s+of\s+the\s+(?:Immigration\s+and\s+Nationality\s+)?Act\b",
        re.IGNORECASE),
}


@dataclass(frozen=True)
class Mention:
    canon_id: str
    kind: str      # statute | regulation
    display: str
    page: int
    quote: str


def _ina(section: str) -> tuple[str, str, str]:
    sec = section.upper()
    usc = INA_TO_USC.get(sec)
    if usc:
        return f"usc:8_{usc.lower()}", "statute", f"8 U.S.C. § {usc}"
    return f"ina:{sec}", "statute", f"INA § {sec}"


def _resolve(name: str, m: re.Match) -> tuple[str, str, str]:
    if name == "usc":
        return f"usc:{m[1]}_{m[2].lower()}", "statute", f"{m[1]} U.S.C. § {m[2]}"
    if name == "cfr":
        return f"cfr:{m[1]}_{m[2]}", "regulation", f"{m[1]} C.F.R. Part {m[2]}"
    return _ina(m[1])


def extract_mentions(pages: list[dict], patterns: list[str], ctx: int = 60) -> list[Mention]:
    unknown = [p for p in patterns if p not in _PATTERNS]
    if unknown:
        raise ValueError(f"unknown statute pattern(s): {unknown}")
    out: list[Mention] = []
    for p in pages:
        text = p["text"]
        for name in patterns:
            for m in _PATTERNS[name].finditer(text):
                cid, kind, display = _resolve(name, m)
                quote = text[max(0, m.start() - ctx): m.end() + ctx]
                out.append(Mention(cid, kind, display, p["page"], quote))
    return out
