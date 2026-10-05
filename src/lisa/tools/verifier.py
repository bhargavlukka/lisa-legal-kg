"""Citation firewall: deterministic checks that every cited case exists and every quote is on the stored page.

Provenance tiers (spec §2.4):
  verified_in_corpus   case is in the graph AND the quote matches its stored page text
  resolved_externally  case is outside the corpus AND CourtListener resolved the citation
  unverified           anything else (quote not found, unknown case, external lookup unavailable)
"""
from __future__ import annotations

import re

from lisa.extract.verify import MIN_QUOTE, PageIndex, squash
from lisa.graph.canon import canon
from lisa.store.memory import STATUS

VERIFIED, EXTERNAL, UNVERIFIED = "verified_in_corpus", "resolved_externally", "unverified"

# A sentence asserting current validity is only allowed with an explicit "not verified" qualifier nearby.
STATUS_CLAIM = re.compile(r"\b(still|remains?|is|continues to be)\s+(good|valid|binding|controlling)\s+(law|precedent)\b"
                          r"|\bhas\s+(not|never)\s+been\s+(overruled|abrogated|reversed|superseded)\b"
                          r"|\bis\s+(no longer|not)\s+good\s+law\b", re.I)
STATUS_QUALIFIER = re.compile(r"not (been )?verified|unverified|cannot (be )?(confirm|verif)|no citator", re.I)
LEGAL_CUES = re.compile(r"\b(held|holds|holding|ruled|rules|concluded|decided|found|determined|reasoned|applied|"
                        r"applies|distinguished|overruled|affirmed|reversed|remanded|dismissed|sustained|"
                        r"requires?|eligib\w*|removab\w*|inadmissib\w*|deportab\w*|statute|section|§|U\.\s?S\.\s?C|"
                        r"I&N|Board|Court|Attorney General|Congress|INA)\b")
CASE_CITE = re.compile(r"\b\d{1,3}\s+(?:I&N\s*Dec\.|U\.\s?S\.|S\.\s?Ct\.|F\.\s?(?:2d|3d|4th)|F\.\s?Supp\.)\s*\d{1,4}\b")
MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
EXEMPT = re.compile(r"^\s*(#|\*\*?(provenance|sources|citations|disclaimer)|provenance|sources?:|disclaimer|note:|"
                    r"this is (legal )?research|i (could|did) not find|no (case|result))", re.I)


class Verifier:
    def __init__(self, store, external=None):
        self.store, self.external = store, external
        self._idx: dict[str, PageIndex] = {}

    def _index(self, cid: str) -> PageIndex:
        if cid not in self._idx:
            self._idx[cid] = PageIndex(dict(self.store.pages.get(cid, {})))
        return self._idx[cid]

    def check_quote(self, cid: str, quote: str, page: int | None = None) -> dict:
        idx = self._index(cid)
        if not quote or len(squash(quote)) < MIN_QUOTE:
            return {"quote_match": False, "reason": f"quote missing or shorter than {MIN_QUOTE} characters"}
        candidates = [page] if page in idx.pages else []
        candidates += [p for p in idx.pages if p != page]
        for p in candidates:
            sp = idx.locate(quote, p)
            if sp:
                return {"quote_match": True, "matched_page": sp.page,
                        "page_note": None if page in (None, sp.page) else f"quote found on page {sp.page}, not {page}"}
        return {"quote_match": False, "reason": "quote not found in stored page text"}

    def verify_citation(self, case: str, quote: str | None = None, page: int | None = None) -> dict:
        cid = self.store.resolve(case)
        if cid is not None:
            out = {"case": case, "case_id": cid, "in_corpus": True, **self.store.case_summary(cid)}
            if not quote:
                return out | {"tier": UNVERIFIED, "reason": "in-corpus citation needs a supporting quote + page"}
            q = self.check_quote(cid, quote, page)
            return out | q | {"tier": VERIFIED if q["quote_match"] else UNVERIFIED}
        c = canon(case)
        if c.kind != "case" or c.id.startswith("other:"):
            return {"case": case, "in_corpus": False, "tier": UNVERIFIED,
                    "reason": "not in the corpus and not a reporter citation - give a citation like '585 U.S. 198'"}
        if self.external is None:
            return {"case": case, "in_corpus": False, "tier": UNVERIFIED, "reason": "external resolution disabled"}
        ext = self.external.lookup_citation(case)
        if ext.get("status") == "resolved":
            return {"case": case, "in_corpus": False, "tier": EXTERNAL, "external": ext, "legal_status": STATUS}
        return {"case": case, "in_corpus": False, "tier": UNVERIFIED,
                "reason": ext.get("reason") or "CourtListener did not resolve the citation", "external": ext}

    def verify_answer(self, answer: str, citations: list[dict]) -> dict:
        """Gate for a draft answer: numbered markers [n] -> citations[n-1] = {case, quote?, page?}."""
        results = [self.verify_citation(str(c.get("case", "")), c.get("quote"), _int(c.get("page")))
                   for c in citations]
        problems = []
        used = {int(n) for m in MARKER.finditer(answer) for n in m.group(1).split(",")}
        for n in sorted(used):
            if not 1 <= n <= len(citations):
                problems.append({"kind": "dangling_marker", "marker": n})
        for i, r in enumerate(results, 1):
            if r["tier"] == UNVERIFIED:
                problems.append({"kind": "unverified_citation", "marker": i, "case": r["case"], "reason": r.get("reason")})
        for s in sentences(answer):
            if EXEMPT.search(s):
                continue
            if LEGAL_CUES.search(s) and not MARKER.search(s):
                problems.append({"kind": "uncited_claim", "sentence": s[:300]})
            for m in CASE_CITE.finditer(s):
                if not MARKER.search(s):
                    problems.append({"kind": "uncited_case_reference", "cite": m.group(0)})
            if STATUS_CLAIM.search(s) and not STATUS_QUALIFIER.search(s):
                problems.append({"kind": "unqualified_status_claim", "sentence": s[:300]})
        tiers = {t: sum(r["tier"] == t for r in results) for t in (VERIFIED, EXTERNAL, UNVERIFIED)}
        return {"passed": not problems and bool(citations), "tiers": tiers, "citations": results,
                "problems": problems if citations else problems + [{"kind": "no_citations"}]}


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def sentences(text: str) -> list[str]:
    """Split prose into sentences/bullets; abbreviations common in legal text do not end a sentence."""
    t = re.sub(r"\b(v|U\.S|Dec|No|Nos|Cir|Inc|Co|Corp|Stat|Supp|App|art|cf|e\.g|i\.e|etc|seq|Ct|Ed|Fed|F|S|L)\.",
               lambda m: m.group(0).replace(".", "․"), text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(\[])|\n+\s*(?:[-*•]|\d+\.)?\s*", t)
    return [p.replace("․", ".").strip() for p in parts if p and p.strip()]
