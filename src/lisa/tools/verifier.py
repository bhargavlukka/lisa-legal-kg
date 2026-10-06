"""Citation firewall: deterministic checks that every cited case exists and every quote is on the stored page.

Provenance tiers (spec §2.4):
  verified_in_corpus   case is in the graph AND the quote matches its stored page text
  resolved_externally  case is outside the corpus AND CourtListener resolved the citation
  unverified           anything else (quote not found, unknown case, external lookup unavailable)
"""
from __future__ import annotations

import re

from lisa.extract.verify import _ELLIPSIS, MIN_QUOTE, PageIndex, squash
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
                        r"I&N|Board|Court|Attorney General|Congress|INA)\b|§", re.I)
CASE_CITE = re.compile(r"\b\d{1,3}\s+(?:I&N\s*Dec\.|U\.\s?S\.|S\.\s?Ct\.|F\.\s?(?:2d|3d|4th)|F\.\s?Supp\.)\s*\d{1,4}\b")
MARKER = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
QUOTED = re.compile(r"[\"“«]([^\"“”«»]+)[\"”»]"            # a quotation in the answer prose: double quotes,
                    r"|(?<!\w)['‘]([^'‘’\n]{12,}?)['’](?!\w)")  # guillemets, or single quotes (not apostrophes)
QUOTE_MIN_WORDS = 3                                     # one- or two-word quoted spans are terms, not quotations
# Legal-quotation alterations: a changed or dropped letter group ("[b]ut", "treat[]", "rule[s]"). Anything longer in
# brackets ("[did not]") is an insertion and stays literal, so it can only match if the source has it verbatim.
ALTERATION = re.compile(r"\[[A-Za-z]{0,3}\]")
NAME_STOP = {"matter", "united", "states", "the", "and", "rel."}
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
            bad = _name_mismatch(case, ext.get("case_name") or "")
            if bad:
                return {"case": case, "in_corpus": False, "tier": UNVERIFIED, "external": ext, "reason": bad}
            if quote:
                return {"case": case, "in_corpus": False, "tier": UNVERIFIED, "external": ext,
                        "reason": "quote cannot be checked: the external source text is not stored - cite without a quote"}
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
        for i in range(1, len(citations) + 1):
            if i not in used:
                problems.append({"kind": "unused_citation", "marker": i})
        for i, r in enumerate(results, 1):
            if r["tier"] == UNVERIFIED:
                problems.append({"kind": "unverified_citation", "marker": i, "case": r["case"], "reason": r.get("reason")})
        for s in sentences(answer):
            if EXEMPT.search(s) or _is_heading(s):
                continue
            if LEGAL_CUES.search(s) and not MARKER.search(s):
                problems.append({"kind": "uncited_claim", "sentence": s[:300]})
            for m in CASE_CITE.finditer(s):
                if not MARKER.search(s):
                    problems.append({"kind": "uncited_case_reference", "cite": m.group(0)})
            for q in (a or b for a, b in QUOTED.findall(s)):
                if len(q.split()) < QUOTE_MIN_WORDS or CASE_CITE.fullmatch(q.strip(" ,.;")):
                    continue                                # a quoted term ("Chevron deference") or a bare citation
                if not self._quote_on_cited_page(q, s, results):
                    problems.append({"kind": "unverified_quote", "quote": q[:200]})
            if STATUS_CLAIM.search(s) and not STATUS_QUALIFIER.search(s):
                problems.append({"kind": "unqualified_status_claim", "sentence": s[:300]})
        tiers = {t: sum(r["tier"] == t for r in results) for t in (VERIFIED, EXTERNAL, UNVERIFIED)}
        return {"passed": not problems and bool(citations), "tiers": tiers, "citations": results,
                "problems": problems if citations else problems + [{"kind": "no_citations"}]}


    def _quote_on_cited_page(self, quote: str, sentence: str, results: list[dict]) -> bool:
        """A quotation in the prose must be on a page of an in-corpus case cited in that sentence (any, if unmarked)."""
        marks = {int(n) for m in MARKER.finditer(sentence) for n in m.group(1).split(",")}
        cids = {r["case_id"] for i, r in enumerate(results, 1)
                if r.get("in_corpus") and r.get("case_id") and (not marks or i in marks)}
        literal = len(squash(quote)) >= MIN_QUOTE and any(self.check_quote(c, quote)["quote_match"] for c in cids)
        if literal or not ALTERATION.search(quote):      # brackets can be in the source itself ("say[ing]")
            return literal
        # each ellipsis-separated segment must match contiguously on one page, an alteration standing for at most
        # 4 letters - never a gap of arbitrary text
        segs = [seg.strip(" .,;:") for seg in _ELLIPSIS.split(quote)]
        segs = [seg for seg in segs if seg]
        if sum(len(squash(ALTERATION.sub("", seg))) for seg in segs) < MIN_QUOTE:
            return False
        pats = [re.compile(_alteration_pattern(seg)) for seg in segs]
        return any(all(pt.search(sq) for pt in pats)
                   for c in cids for sq in (squash(t) for t in self.store.pages.get(c, {}).values()))


def _alteration_pattern(seg: str) -> str:
    """Regex over squashed page text for one quote segment. "[b]" is a case change (the same letter, either case);
    "[]" marks letters omitted from the source (0-4). Additive brackets ("[un]", "[s not]") stay literal."""
    out, pos = [], 0
    for m in ALTERATION.finditer(seg):
        out.append(re.escape(squash(seg[pos:m.start()])))
        inner = m.group(0)[1:-1]
        out.append("[A-Za-z]{0,4}" if not inner else "".join(f"[{c.lower()}{c.upper()}]" for c in inner))
        pos = m.end()
    out.append(re.escape(squash(seg[pos:])))
    return "".join(out)


HOLDING = re.compile(r"(held|holds|holding|ruled|rules|concluded|decided|found|determined|granted|denied|"
                     r"affirmed|reversed|remanded|overruled|must|requires?|is|are|was|were)", re.I)


def _is_heading(s: str) -> bool:
    """A short all-caps line with no assertion ("SUPREME COURT", "OPINION OF THE COURT") is a heading."""
    return s.isupper() and len(s.split()) <= 6 and not s.rstrip().endswith(".") and not HOLDING.search(s)


def _name_mismatch(cited: str, resolved: str) -> str | None:
    """The case name given with an external citation must share a word with the name CourtListener resolved."""
    m = CASE_CITE.search(cited)
    head = cited[:m.start()].lower() if m else ""
    words = {w for w in re.findall(r"[a-z][a-z'-]{3,}", head) if w not in NAME_STOP}
    if not words or not resolved or any(w in resolved.lower() for w in words):
        return None
    return f"cited name does not match the case CourtListener resolved: {resolved!r}"


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
