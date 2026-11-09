"""Web UI: tool-result summaries for the activity feed, the page, and the /api/ask event stream (fake agent)."""
import json
from types import SimpleNamespace

from starlette.testclient import TestClient

from lisa.common.config import _fast_settings
from lisa.web.app import make_app, summarize


def mcp(payload):
    return [{"type": "text", "text": json.dumps(payload)}]


def test_summarize_lists_case_labels_and_strips_untrusted_fences():
    out = summarize("mcp__graph__find_citing_cases", mcp({"case_id": "x", "citing": [
        {"case_id": "eoir_1", "title": "MORADEL", "citation": "28 I&N Dec. 310"},
        {"case_id": "eoir_2", "title": "<<<UNTRUSTED_CASE_TEXT source=x\nLAPARRA\nUNTRUSTED_CASE_TEXT>>>"}]}))
    assert out == {"headline": "2 citing", "items": ["MORADEL (28 I&N Dec. 310)", "LAPARRA"]}


def test_summarize_verifier_page_and_unavailable_results():
    assert summarize("mcp__verifier__verify_answer", {"passed": True})["headline"] == "all citations verified"
    bad = summarize("mcp__verifier__verify_answer", {"passed": False, "problems": [{"kind": "dangling_marker"}]})
    assert bad == {"headline": "1 problem(s) found", "items": ["dangling_marker"]}
    page = summarize("mcp__graph__read_page", mcp({"case_id": "eoir_1", "page": 3, "text": "one two three"}))
    assert page["headline"] == "read page 3 of eoir_1 (3 words)"
    off = summarize("mcp__external__resolve_citation", {"status": "unavailable", "reason": "no token"})
    assert off["headline"] == "unavailable: no token"
    assert summarize("Skill", {"success": True})["headline"] == "procedure loaded"


class FakeAgent:
    def __init__(self, tmp_path):
        self.settings = SimpleNamespace(out_dir=tmp_path)
        self.agent = SimpleNamespace(sessions_dir="sessions")
        self.asked = []

    async def ask(self, question, memory=None, on_event=None):
        self.asked.append((question, memory.name))
        on_event({"type": "start", "question": question})
        on_event({"type": "tool_start", "tool": "mcp__graph__search_cases", "input": {"query": "Pereira"}})
        on_event({"type": "tool_end", "tool": "mcp__graph__search_cases", "ms": 4,
                  "result": mcp({"results": [{"case_id": "s1", "title": "Pereira v. Sessions"}]})})
        traj = SimpleNamespace(tools=[{"name": "mcp__graph__search_cases"}], model_calls=2, input_tokens=10,
                               output_tokens=5, names=lambda: ["mcp__graph__search_cases"])
        return SimpleNamespace(status="verified", text="Answer [1].", latency_s=1.23, trajectory=traj, revisions=0,
                               draft={"answer": "Answer [1].", "citations": []}, report={"passed": True})


def events(client, url):
    with client.stream("GET", url) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]


def test_ask_streams_progress_then_done(tmp_path):
    agent = FakeAgent(tmp_path)
    with TestClient(make_app(agent)) as c:
        assert "<title>LISA Research</title>" in c.get("/").text
        ev = events(c, "/api/ask?q=Who+cites+Pereira%3F&session=demo/../x")
    assert [e["type"] for e in ev] == ["start", "tool_start", "tool_end", "done"]
    assert "result" not in ev[2] and ev[2]["headline"] == "1 results" and ev[2]["items"] == ["Pereira v. Sessions"]
    assert ev[-1]["status"] == "verified" and ev[-1]["latency_s"] == 1.2 and ev[-1]["tool_names"]
    assert agent.asked == [("Who cites Pereira?", "demox")]          # session name sanitised


def test_ask_rejects_an_empty_question(tmp_path):
    agent = FakeAgent(tmp_path)
    with TestClient(make_app(agent)) as c:
        ev = events(c, "/api/ask?q=")
    assert ev == [{"type": "done", "status": "error", "text": "empty question"}] and agent.asked == []


def test_fast_settings_defaults_and_env_override(monkeypatch):
    monkeypatch.delenv("LISA_AGENT_FAST", raising=False)
    assert _fast_settings({}) == {}
    on = _fast_settings({"enabled": True, "max_turns": 12})
    assert on == {"fast": True, "soft_deadline_s": 30.0, "hard_deadline_s": 52.0, "wrapup_s": 30.0, "max_turns": 12}
    monkeypatch.setenv("LISA_AGENT_FAST", "0")
    assert _fast_settings({"enabled": True}) == {}
    monkeypatch.setenv("LISA_AGENT_FAST", "1")
    assert _fast_settings({})["fast"] is True
