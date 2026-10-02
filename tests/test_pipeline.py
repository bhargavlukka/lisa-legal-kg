import json
import re

import httpx
import pytest

from fakes import chat_payload, llm_settings
from lisa.common.config import EvalSettings, load_settings
from lisa.extract import cli
from lisa.extract.pipeline import run

NODES = {"nodes": [
    {"type": "opinion", "label": "Majority opinion", "part": "majority", "author": "Jones", "confidence": 0.9,
     "evidence": [{"page": 1, "quote": "In re ALPHA. We follow Matter of Beta"}], "attrs": {}},
    {"type": "reasoning", "label": "Beta controls", "part": "majority", "confidence": 0.8,
     "evidence": [{"page": 1, "quote": "See section 212(h) of the Act and 8 U.S.C."}], "attrs": {}},
    {"type": "authority_ref", "label": "Matter of Beta", "part": "majority", "confidence": 0.9,
     "evidence": [{"page": 1, "quote": "We follow Matter of Beta, 22 I&N Dec. 200 (BIA 1998)"}],
     "attrs": {"cite_string": "Matter of Beta, 22 I&N Dec. 200", "kind": "case"}}]}
EDGES = {"edges": [{"source": "eoir_1:reasoning:beta_controls", "target": "eoir_1:authority_ref:matter_of_beta",
                    "relation": "relies_on", "stance": "follows", "basis": "explicit", "confidence": 0.9,
                    "evidence": [{"page": 1, "quote": "We follow Matter of Beta, 22 I&N"}]}]}


def transport(calls):
    def handler(request):
        user = json.loads(request.content)["messages"][-1]["content"]
        calls.append(user)
        case = re.search(r"CASE_ID: (\S+)", user).group(1)
        if "NODE CATALOG" in user:
            body = EDGES if case == "eoir_1" else {"edges": []}
        else:
            body = NODES if case == "eoir_1" else {"nodes": []}
        return httpx.Response(200, json=chat_payload(json.dumps(body)))
    return httpx.MockTransport(handler)


@pytest.fixture
def env(mini_data, tmp_path, monkeypatch):
    monkeypatch.setenv("LISA_DATA_DIR", str(mini_data))
    monkeypatch.setenv("LISA_OUT_DIR", str(tmp_path / "out"))
    return load_settings(env_file=None)


EV = EvalSettings(match_threshold=0.3, fewshot_units=())


def test_run_writes_tier_graph_and_manifest(env):
    calls = []
    r = run("immigration", settings=env, llm=llm_settings(), ev=EV, transport=transport(calls))
    assert r.status == "complete" and len(calls) == 3   # eoir_1 nodes+edges, eoir_2 nodes (no nodes -> no edge call)
    out = json.loads(r.output.read_text(encoding="utf-8"))
    assert out["model"] == "test-model" and out["prompt_versions"] == {"nodes": "nodes-v1", "edges": "edges-v1"}
    u1 = next(u for u in out["units"] if u["case_id"] == "eoir_1")
    assert u1["status"] == "ok" and len(u1["nodes"]) == 3 and len(u1["edges"]) == 1
    assert all(n["provenance"] == "llm" for n in u1["nodes"]) and out["pending"] == []
    g = json.loads(r.graph.read_text(encoding="utf-8"))
    assert {(e["type"], e["source"], e["target"]) for e in g["edges"]} >= {
        ("FOLLOWS", "eoir_1", "eoir_2"), ("AUTHORED_BY", "eoir_1", "judge:bia:jones")}
    m = json.loads(r.manifest.read_text(encoding="utf-8"))
    assert m["status"] == "complete" and m["requests"] == 3 and m["units_done"] == 2 and m["dataset"] == "immigration"


def test_rerun_offline_is_free_and_identical(env):
    first = run("immigration", settings=env, llm=llm_settings(), ev=EV, transport=transport([]))
    a = first.output.read_text(encoding="utf-8")
    second = run("immigration", settings=env, llm=llm_settings(api_key=None), ev=EV, offline=True)
    assert second.output.read_text(encoding="utf-8") == a
    assert json.loads(second.manifest.read_text(encoding="utf-8"))["requests"] == 0


def test_budget_stop_then_resume_matches_full_run(env, tmp_path):
    full = run("immigration", settings=env, llm=llm_settings(), ev=EV, transport=transport([])).output.read_text(
        encoding="utf-8")
    for p in (env.out_dir / "llm_cache").glob("*.json"):
        p.unlink()
    r1 = run("immigration", settings=env, llm=llm_settings(), ev=EV, max_requests=1, transport=transport([]))
    assert r1.status == "budget_exhausted"
    part = json.loads(r1.output.read_text(encoding="utf-8"))
    assert part["pending"] and len(part["units"]) + len(part["pending"]) == 2
    calls = []
    r2 = run("immigration", settings=env, llm=llm_settings(), ev=EV, transport=transport(calls))
    assert r2.status == "complete" and len(calls) == 2 and r2.output.read_text(encoding="utf-8") == full


def test_offline_cache_miss_marks_unit(env):
    r = run("immigration", settings=env, llm=llm_settings(api_key=None), ev=EV, offline=True)
    out = json.loads(r.output.read_text(encoding="utf-8"))
    assert r.status == "complete" and {u["status"] for u in out["units"]} == {"not_cached"}


def test_only_units_filter(env):
    calls = []
    r = run("immigration", settings=env, llm=llm_settings(), ev=EV, only_units={"eoir_2__u1of1"},
            transport=transport(calls))
    assert [u["unit_id"] for u in json.loads(r.output.read_text(encoding="utf-8"))["units"]] == ["eoir_2__u1of1"]


def test_cli_missing_key_exits_2(env, monkeypatch, capsys):
    monkeypatch.delenv("SHAREDLLM_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_llm_settings", lambda: llm_settings(api_key=None))
    monkeypatch.setattr(cli, "load_eval_settings", lambda: EV)   # mini data has no gold few-shot files
    assert cli.main(["--dataset", "immigration"]) == 2
    assert "SHAREDLLM_API_KEY is not set" in capsys.readouterr().err


def test_cli_bad_dataset_exits_2(env, capsys):
    assert cli.main(["--dataset", "nope"]) == 2
    assert "cannot load dataset" in capsys.readouterr().err
