"""Phase 5 QA evaluation: score KG-agent and RAG-baseline turns against the golden question set.

A turn record (both systems) = {id, system, status, text, report, latency_s, input_tokens, output_tokens,
model_calls, tools: [names] | None, revisions}. Only citations the verifier placed in tier verified_in_corpus count
toward recall, so an answer cannot score by naming cases it could not back with a stored quote.
"""
from __future__ import annotations

import statistics
from pathlib import Path

import yaml

from lisa.agent.guardrails.gate import DISCLAIMER
from lisa.tools.verifier import MARKER, STATUS_CLAIM, STATUS_QUALIFIER, UNVERIFIED, VERIFIED, sentences

ANSWERED = ("verified", "salvaged")
VERIFY_TOOL = "mcp__verifier__verify_answer"


def load_golden(path: Path) -> list[dict]:
    qs = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["questions"]
    ids = [q["id"] for q in qs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate question ids in golden set")
    return qs


def cited_cases(report: dict, answer: str | None = None) -> list[str]:
    """Verified in-corpus cases; with the draft answer given, only citations it references by a [n] marker."""
    marks = None if answer is None else {int(n) for m in MARKER.finditer(answer) for n in m.group(1).split(",")}
    out = []
    for i, c in enumerate(report.get("citations", []), 1):
        if marks is not None and i not in marks:
            continue
        if c.get("tier") == VERIFIED and c.get("case_id") and c["case_id"] not in out:
            out.append(c["case_id"])
    return out


def unqualified_status_claims(text: str) -> int:
    return sum(bool(STATUS_CLAIM.search(s)) and not STATUS_QUALIFIER.search(s) for s in sentences(text or ""))


def score(q: dict, rec: dict, allowed_tools: set[str] | None = None) -> dict:
    expected = set(q.get("expected_cases") or [])
    cited = cited_cases(rec.get("report") or {}, (rec.get("draft") or {}).get("answer"))
    hit = expected & set(cited)
    expect, status = q.get("expect", "answer"), rec.get("status")
    if expect == "refuse":
        behaviour = not cited                      # declined, or answered without inventing in-corpus support
    elif expect == "disclaimer":
        behaviour = DISCLAIMER in (rec.get("text") or "")
    else:
        behaviour = status in ANSWERED
    row = {"id": q["id"], "category": q.get("category"), "system": rec.get("system"), "status": status,
           "behaviour_ok": behaviour,
           "recall": round(len(hit) / len(expected), 3) if expected else None,
           "precision": round(len(hit) / len(cited), 3) if expected and cited else None,
           "cited": cited, "missed": sorted(expected - set(cited)),
           "unverified_citations": sum(c.get("tier") == UNVERIFIED for c in (rec.get("report") or {}).get("citations", [])),
           "status_claims": unqualified_status_claims(rec.get("text")),
           "latency_s": rec.get("latency_s"), "input_tokens": rec.get("input_tokens", 0),
           "output_tokens": rec.get("output_tokens", 0), "model_calls": rec.get("model_calls", 0),
           "revisions": rec.get("revisions", 0)}
    tools = rec.get("tools")
    if tools is not None:                          # trajectory checks (KG agent only)
        needs = q.get("needs_tools") or []
        row["needs_tools_ok"] = all(any(n in t for t in tools) for n in needs)
        row["only_allowed_tools"] = allowed_tools is None or all(t in allowed_tools for t in tools)
        row["self_verified"] = VERIFY_TOOL in tools
        row["tool_calls"] = len(tools)
    return row


def _mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 3) if xs else None


def _rate(rows, key) -> float | None:
    xs = [r[key] for r in rows if key in r]
    return round(sum(map(bool, xs)) / len(xs), 3) if xs else None


def aggregate(rows: list[dict]) -> dict:
    lat = [r["latency_s"] for r in rows if r.get("latency_s") is not None]
    out = {"n": len(rows), "recall": _mean(r["recall"] for r in rows), "precision": _mean(r["precision"] for r in rows),
           "behaviour_ok": _rate(rows, "behaviour_ok"),
           "answered": round(sum(r["status"] in ANSWERED for r in rows) / len(rows), 3) if rows else None,
           "status_claims": sum(r["status_claims"] for r in rows),
           "unverified_citations": sum(r["unverified_citations"] for r in rows),
           "latency_mean_s": round(statistics.fmean(lat), 1) if lat else None,
           "latency_p50_s": round(statistics.median(lat), 1) if lat else None,
           "latency_max_s": round(max(lat), 1) if lat else None,
           "input_tokens": sum(r["input_tokens"] for r in rows), "output_tokens": sum(r["output_tokens"] for r in rows),
           "model_calls": sum(r["model_calls"] for r in rows)}
    for k in ("needs_tools_ok", "only_allowed_tools", "self_verified"):
        if any(k in r for r in rows):
            out[k] = _rate(rows, k)
    cats: dict[str, list] = {}
    for r in rows:
        cats.setdefault(r["category"], []).append(r)
    out["by_category"] = {c: {"n": len(rs), "recall": _mean(r["recall"] for r in rs),
                              "behaviour_ok": _rate(rs, "behaviour_ok")} for c, rs in sorted(cats.items())}
    return out


def _fmt(v) -> str:
    return "-" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)


def render_markdown(summary: dict[str, dict], rows: dict[str, list[dict]], notes: list[str] | None = None) -> str:
    systems = list(summary)
    keys = ["n", "recall", "precision", "behaviour_ok", "answered", "status_claims", "unverified_citations",
            "needs_tools_ok", "only_allowed_tools", "self_verified", "latency_mean_s", "latency_p50_s",
            "latency_max_s", "model_calls", "input_tokens", "output_tokens"]
    out = ["# LISA Phase 5 - question answering: KG agent vs RAG baseline", ""]
    out += [f"- {n}" for n in notes or []] + ([""] if notes else [])
    out += ["## Summary", "", "| metric | " + " | ".join(systems) + " |", "|---" * (len(systems) + 1) + "|"]
    out += [f"| {k} | " + " | ".join(_fmt(summary[s].get(k)) for s in systems) + " |" for k in keys]
    out += ["", "Recall/precision count only citations the verifier placed in verified_in_corpus. behaviour_ok: "
            "answer -> verified or salvaged; refuse -> no in-corpus case cited; disclaimer -> advice disclaimer shown.",
            "", "## By category (recall / behaviour_ok)", "",
            "| category | " + " | ".join(systems) + " |", "|---" * (len(systems) + 1) + "|"]
    cats = sorted({c for s in systems for c in summary[s]["by_category"]})
    for c in cats:
        cells = []
        for s in systems:
            v = summary[s]["by_category"].get(c)
            cells.append(f"{_fmt(v['recall'])} / {_fmt(v['behaviour_ok'])}" if v else "-")
        out.append(f"| {c} | " + " | ".join(cells) + " |")
    out += ["", "## Per question", ""]
    for s in systems:
        out += [f"### {s}", "", "| id | category | status | recall | behaviour | latency s | missed |",
                "|---|---|---|---|---|---|---|"]
        for r in rows[s]:
            out.append(f"| {r['id']} | {r['category']} | {r['status']} | {_fmt(r['recall'])} | "
                       f"{'ok' if r['behaviour_ok'] else 'FAIL'} | {_fmt(r['latency_s'])} | "
                       f"{', '.join(r['missed'][:6])}{' ...' if len(r['missed']) > 6 else ''} |")
        out.append("")
    return "\n".join(out)
