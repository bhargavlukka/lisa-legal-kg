"""Acceptance check: the graph must contain every edge documented in selection_report.json."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CheckResult:
    expected: int
    missing: list[tuple] = field(default_factory=list)
    extra: list[tuple] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing


def _expected(report: dict, case_ids: set[str]) -> set[tuple]:
    exp = set()
    for key in ("immigration_internal_edges_list", "litigation_internal_edges_list"):
        for e in report.get(key, []):
            exp.add((e["from"], e["to"], "internal"))
    for e in report.get("cross_domain_edges_list", []):
        exp.add((e["from"], e["to"], e["basis"]))
    return {x for x in exp if x[0] in case_ids and x[1] in case_ids}


def _actual(graph: dict) -> set[tuple]:
    out = set()
    for e in graph["edges"]:
        if e["type"] != "CITES" or e["target_label"] != "Case":
            continue
        if e["props"]["scope"] == "internal":
            out.add((e["source"], e["target"], "internal"))
        else:
            for b in e["props"].get("bases", []):
                out.add((e["source"], e["target"], b))
    return out


def check(graph: dict, report: dict) -> CheckResult:
    case_ids = {n["id"] for n in graph["nodes"] if n["label"] == "Case"}
    exp, act = _expected(report, case_ids), _actual(graph)
    return CheckResult(expected=len(exp), missing=sorted(exp - act), extra=sorted(act - exp))
