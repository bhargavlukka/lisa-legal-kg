import json

from lisa.graph.check import check


def test_check_passes_on_mini(graph_all, mini_data):
    report = json.loads((mini_data / "selection_report.json").read_text(encoding="utf-8"))
    r = check(graph_all, report)
    assert r.ok and r.expected == 3 and r.missing == [] and r.extra == []


def test_check_reports_missing_edge(graph_all, mini_data):
    report = json.loads((mini_data / "selection_report.json").read_text(encoding="utf-8"))
    report["immigration_internal_edges_list"].append({"from": "eoir_2", "to": "eoir_1"})
    r = check(graph_all, report)
    assert not r.ok and r.missing == [("eoir_2", "eoir_1", "internal")]


def test_check_ignores_cases_not_loaded(graph_imm, mini_data):
    report = json.loads((mini_data / "selection_report.json").read_text(encoding="utf-8"))
    r = check(graph_imm, report)
    assert r.ok and r.expected == 1
