"""Guardrails enforced in code, after the model and before the user sees anything.

1. Parse the agent's final {answer, citations} JSON (no JSON -> no citations -> fails the gate).
2. The citation-verifier MCP server checks the draft (`verify_answer`); the model cannot skip this - the runner
   calls it, whatever the model did.
3. On failure the runner asks the model to revise (bounded); if it still fails, `salvage` keeps only sentences
   whose every marker points to a verified/resolved citation and drops the rest - or refuses outright.
4. Provenance labels, the unverified-legal-status notice and (for advice-type questions) a disclaimer are
   appended by code, not left to the model.
"""
from __future__ import annotations

import json
import re

from lisa.tools.verifier import EXTERNAL, MARKER, UNVERIFIED, VERIFIED, sentences

ADVICE = re.compile(
    r"\b(should I|should my|can I|could I|am I|will I|do I (need|have)|my (case|client|application|hearing|visa|"
    r"green card|status|removal|deportation|asylum|petition|options)|what are my|what should|advise|advice|"
    r"best (strategy|option)|chances|likely to (win|succeed)|my (husband|wife|son|daughter|father|mother))\b", re.I)
DISCLAIMER = ("Disclaimer: this is legal research drawn from a 60-case corpus and public data, not legal advice. "
              "Consult a licensed immigration attorney about any individual situation.")
STATUS_NOTE = ("Legal status: none of the cited authorities has been checked against a citator; each is "
               "\"not verified; may have subsequent treatment\" and is not stated as current law.")
TIER_LABEL = {VERIFIED: "verified in-corpus", EXTERNAL: "resolved externally (CourtListener)", UNVERIFIED: "unverified"}


def is_advice(question: str) -> bool:
    return bool(ADVICE.search(question or ""))


def parse_final(text: str) -> dict:
    """The last JSON object carrying an "answer" key (fenced or bare); else the raw text with no citations."""
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.S)
    if not candidates:
        start = (text or "").rfind('{"answer"')
        if start < 0:
            start = (text or "").find("{")
        if start >= 0:
            candidates = [text[start:text.rfind("}") + 1]]
    for raw in reversed(candidates):
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("answer"), str):
            cits = obj.get("citations") if isinstance(obj.get("citations"), list) else []
            return {"answer": obj["answer"].strip(),
                    "citations": [c for c in cits if isinstance(c, dict) and c.get("case")], "parsed": True}
    return {"answer": (text or "").strip(), "citations": [], "parsed": False}


def revision_prompt(report: dict) -> str:
    lines = ["Your draft FAILED the citation-verifier. Fix every problem below, re-run verify_answer, then reply "
             "with the corrected final JSON only."]
    for p in report.get("problems", [])[:12]:
        lines.append("- " + json.dumps(p, ensure_ascii=False))
    lines.append("Rules: each legal sentence needs a [n] marker; in-corpus quotes must be copied verbatim from "
                 "read_page with the right page; drop any claim you cannot support; never assert current legal status.")
    return "\n".join(lines)


def salvage(draft: dict, report: dict) -> dict | None:
    """Keep only sentences fully backed by non-unverified citations; renumber markers. None if nothing survives."""
    ok = {i for i, r in enumerate(report["citations"], 1) if r["tier"] != UNVERIFIED}
    flagged = {p.get("sentence") for p in report["problems"] if p.get("sentence")}
    kept, used = [], []
    for s in sentences(draft["answer"]):
        nums = [int(n) for m in MARKER.finditer(s) for n in m.group(1).split(",")]
        if not nums or not set(nums) <= ok or s[:300] in flagged:
            continue
        for n in nums:
            if n not in used:
                used.append(n)
        kept.append(s)
    if not kept:
        return None
    remap = {old: new for new, old in enumerate(used, 1)}
    text = " ".join(MARKER.sub(lambda m: "[" + ", ".join(str(remap[int(n)]) for n in m.group(1).split(",")) + "]", s)
                    for s in kept)
    return {"answer": text, "citations": [draft["citations"][n - 1] for n in used]}


def render(question: str, answer: str, report: dict, status: str, notes: list[str] | None = None) -> str:
    """Final user-facing text: answer + code-generated sources with provenance tiers + status notice (+ disclaimer)."""
    out = [answer.strip(), "", "Sources (checked by the citation-verifier):"]
    for i, r in enumerate(report.get("citations", []), 1):
        name = r.get("title") or (r.get("external") or {}).get("case_name") or r.get("case")
        cite = r.get("citation") or (r.get("external") or {}).get("citation") or ""
        where = f", p. {r['matched_page']}" if r.get("matched_page") else ""
        out.append(f"[{i}] {name} {cite}{where} - {TIER_LABEL[r['tier']]}")
    out += ["", STATUS_NOTE]
    for n in notes or []:
        out.append(n)
    if status != "verified":
        out.append(f"Verification status: {status}.")
    if is_advice(question):
        out += ["", DISCLAIMER]
    return "\n".join(out)


REFUSAL = ("I could not produce an answer whose every legal claim passes the citation-verifier, so I am not "
           "giving one. Try narrowing the question or naming a specific case.")
