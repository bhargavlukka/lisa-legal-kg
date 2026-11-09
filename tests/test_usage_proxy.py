import json

import httpx
from starlette.testclient import TestClient

from lisa.agent.usage_proxy import make_app, sse_events
from lisa.eval.qa import aggregate, render_markdown

MSG = {"id": "msg_1", "type": "message", "role": "assistant", "model": "m", "stop_reason": "tool_use",
       "stop_sequence": None, "usage": {"input_tokens": 171, "output_tokens": 41},
       "content": [{"type": "thinking", "thinking": "hmm", "signature": "sig"},
                   {"type": "text", "text": "Looking it up."},
                   {"type": "tool_use", "id": "call_1", "name": "get_case", "input": {"case_id": "eoir_4018"}}]}


def parse(chunks) -> list[tuple[str, dict]]:
    out = []
    for c in chunks:
        ev, data = c.decode().strip().split("\n")
        out.append((ev.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def rebuild(events) -> dict:
    """Accumulate SSE events the way an Anthropic streaming client does."""
    msg, blocks, partial = None, [], {}
    for ev, d in events:
        if ev == "message_start":
            msg = d["message"]
        elif ev == "content_block_start":
            blocks.append(dict(d["content_block"]))
        elif ev == "content_block_delta":
            b, dl = blocks[d["index"]], d["delta"]
            if dl["type"] == "text_delta":
                b["text"] += dl["text"]
            elif dl["type"] == "thinking_delta":
                b["thinking"] += dl["thinking"]
            elif dl["type"] == "signature_delta":
                b["signature"] = dl["signature"]
            elif dl["type"] == "input_json_delta":
                partial[d["index"]] = partial.get(d["index"], "") + dl["partial_json"]
        elif ev == "content_block_stop" and d["index"] in partial:
            blocks[d["index"]]["input"] = json.loads(partial[d["index"]])
        elif ev == "message_delta":
            msg.update(d["delta"])
            msg["usage"] = {**msg["usage"], **d["usage"]}
    return {**msg, "content": blocks}


def test_sse_replay_reconstructs_the_message_with_real_input_tokens():
    events = parse(sse_events(MSG))
    assert [e for e, _ in events][0] == "message_start" and events[-1][0] == "message_stop"
    assert events[0][1]["message"]["usage"]["input_tokens"] == 171         # the gateway's own stream sends 0 here
    assert rebuild(events) == MSG


def test_proxy_unstreams_upstream_call_records_usage_and_passes_errors(tmp_path):
    seen = []

    def upstream(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append((str(req.url), body, req.headers.get("x-sharedllm-key"), req.headers.get("accept-encoding")))
        if body["model"] == "busy":
            return httpx.Response(429, json={"error": "rate"}, headers={"retry-after": "7"})
        return httpx.Response(200, json=MSG, headers={"x-sharedllm-request-id": "r1"})

    ledger = tmp_path / "usage.jsonl"
    app = make_app("https://gw.example/anthropic", ledger, transport=httpx.MockTransport(upstream))
    with TestClient(app) as c:
        r = c.post("/v1/messages", json={"model": "m", "stream": True, "messages": []}, headers={"X-SharedLLM-Key": "k"})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert rebuild(parse(r.content.split(b"\n\n")[:-1])) == MSG
        assert r.headers["x-sharedllm-request-id"] == "r1"
        plain = c.post("/v1/messages", json={"model": "m", "messages": []})
        assert plain.json() == MSG
        busy = c.post("/v1/messages", json={"model": "busy", "stream": True, "messages": []})
        assert busy.status_code == 429 and busy.headers["retry-after"] == "7"
    url, body, key, enc = seen[0]
    assert url == "https://gw.example/anthropic/v1/messages" and "stream" not in body and key == "k" and enc == "identity"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [(x["input_tokens"], x["output_tokens"]) for x in rows] == [(171, 41), (171, 41)]   # errors not metered


def test_cost_per_query_and_missing_input_count():
    rows = [{"id": "q1", "category": "c", "status": "verified", "behaviour_ok": True, "recall": 1.0, "precision": 1.0,
             "status_claims": 0, "unverified_citations": 0, "latency_s": 1.0, "input_tokens": 1_000_000,
             "output_tokens": 0, "model_calls": 1, "missed": []},
            {"id": "q2", "category": "c", "status": "verified", "behaviour_ok": True, "recall": 1.0, "precision": 1.0,
             "status_claims": 0, "unverified_citations": 0, "latency_s": 1.0, "input_tokens": 0,
             "output_tokens": 2_000_000, "model_calls": 1, "missed": []}]
    s = aggregate(rows, {"input_per_mtok": 0.02, "output_per_mtok": 0.5})
    assert s["cost_total_usd"] == 1.02 and s["cost_per_query_usd"] == 0.51 and s["input_tokens_missing"] == 1
    assert "| cost_per_query_usd | $0.510000 |" in render_markdown({"kg": s}, {"kg": rows})
    assert "cost_per_query_usd" not in aggregate(rows)


def test_message_start_carries_final_usage_and_revision_passes_are_summed():
    from lisa.agent.agent import Trajectory
    start = parse(sse_events(MSG))[0][1]["message"]["usage"]
    assert start == {"input_tokens": 171, "output_tokens": 41}   # the CLI snapshots usage before message_delta
    t = Trajectory()
    t.calls = {"m1": (100, 0), "m2": (200, 0)}                   # per-call output missing
    t.passes = [(100, 30), (200, 50)]                            # first draft + one revision
    t.tally()
    assert (t.input_tokens, t.output_tokens) == (300, 80)


# ---- OpenAI-route translation (route: openai) ----
from lisa.agent.usage_proxy import from_openai, to_openai  # noqa: E402

TOOLS = [{"name": "get_case", "description": "Fetch a case", "input_schema": {
    "type": "object", "properties": {"case_id": {"type": "string"}}, "required": ["case_id"]}},
    {"type": "web_search_20250305", "name": "web_search"}]


def test_to_openai_maps_system_history_tools_and_injects_reasoning_cap():
    req = {"model": "m", "max_tokens": 1024, "stream": False, "temperature": 0,
           "system": [{"type": "text", "text": "You are LISA."}, {"type": "text", "text": "Cite.", "cache_control": {}}],
           "tools": TOOLS, "tool_choice": {"type": "any", "disable_parallel_tool_use": True},
           "messages": [{"role": "user", "content": "Who cites Pereira?"},
                        {"role": "assistant", "content": [
                            {"type": "thinking", "thinking": "hmm", "signature": "s"},
                            {"type": "text", "text": "Looking."},
                            {"type": "tool_use", "id": "call_a", "name": "get_case", "input": {"case_id": "x"}},
                            {"type": "tool_use", "id": "call_b", "name": "get_case", "input": {"case_id": "y"}}]},
                        {"role": "user", "content": [
                            {"type": "tool_result", "tool_use_id": "call_a", "content": "found x"},
                            {"type": "tool_result", "tool_use_id": "call_b", "is_error": True,
                             "content": [{"type": "text", "text": "no such case"}]},
                            {"type": "text", "text": "Continue."}]}]}
    o = to_openai(req, {"max_tokens": 200})
    assert o["reasoning"] == {"max_tokens": 200} and o["max_tokens"] == 8192 and o["temperature"] == 0
    assert "stream" not in o and o["tool_choice"] == "required" and o["parallel_tool_calls"] is False
    assert o["tools"] == [{"type": "function", "function": {"name": "get_case", "description": "Fetch a case",
                                                            "parameters": TOOLS[0]["input_schema"]}}]
    m = o["messages"]
    assert m[0] == {"role": "system", "content": "You are LISA.\nCite."}
    assert m[1] == {"role": "user", "content": "Who cites Pereira?"}
    assert m[2]["role"] == "assistant" and m[2]["content"] == "Looking."           # thinking dropped
    assert [(c["id"], c["function"]["name"], json.loads(c["function"]["arguments"])) for c in m[2]["tool_calls"]] == \
        [("call_a", "get_case", {"case_id": "x"}), ("call_b", "get_case", {"case_id": "y"})]
    assert m[3] == {"role": "tool", "tool_call_id": "call_a", "content": "found x"}
    assert m[4] == {"role": "tool", "tool_call_id": "call_b", "content": "[tool error] no such case"}
    assert m[5] == {"role": "user", "content": "Continue."} and len(m) == 6
    big = to_openai({"model": "m", "max_tokens": 20000, "system": "s", "messages": [],
                     "tools": TOOLS, "tool_choice": {"type": "tool", "name": "get_case"}})
    assert big["max_tokens"] == 20000 and big["messages"] == [{"role": "system", "content": "s"}]
    assert big["tool_choice"] == {"type": "function", "function": {"name": "get_case"}} and "reasoning" not in big


def test_from_openai_maps_parallel_tool_calls_stop_reasons_and_usage():
    resp = {"id": "chatcmpl-1", "model": "z", "usage": {"prompt_tokens": 900, "completion_tokens": 60},
            "choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                         "reasoning": "hidden", "tool_calls": [
                             {"id": "call_1", "type": "function", "function": {"name": "a", "arguments": '{"q": 1}'}},
                             {"id": "call_2", "type": "function", "function": {"name": "b", "arguments": "{bad"}}]}}]}
    msg = from_openai(resp, "m")
    assert msg["id"] == "msg_chatcmpl-1" and msg["model"] == "m" and msg["stop_reason"] == "tool_use"
    assert msg["content"] == [{"type": "tool_use", "id": "call_1", "name": "a", "input": {"q": 1}},
                              {"type": "tool_use", "id": "call_2", "name": "b", "input": {}}]
    assert msg["usage"] == {"input_tokens": 900, "output_tokens": 60}
    assert rebuild(parse(sse_events(msg))) == msg                       # replays as SSE like a native reply

    def one(fin, content="hi"):
        return from_openai({"choices": [{"finish_reason": fin, "message": {"content": content}}]}, "m")
    assert one("stop")["stop_reason"] == "end_turn" and one("stop")["content"] == [{"type": "text", "text": "hi"}]
    assert one("length")["stop_reason"] == "max_tokens" and one("stop", None)["content"] == [{"type": "text", "text": ""}]


def test_proxy_openai_route_round_trip_meters_and_wraps_errors(tmp_path):
    seen = []

    def upstream(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append((str(req.url), body, dict(req.headers)))
        if body["messages"][-1]["content"] == "busy":
            return httpx.Response(429, text="rate limited", headers={"retry-after": "3"})
        if body["messages"][-1]["role"] == "tool":
            return httpx.Response(200, json={"id": "c2", "usage": {"prompt_tokens": 50, "completion_tokens": 5},
                                             "choices": [{"finish_reason": "stop", "message": {"content": "Done."}}]})
        return httpx.Response(200, json={"id": "c1", "usage": {"prompt_tokens": 40, "completion_tokens": 9},
                                         "choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
                                             {"id": "call_9", "function": {"name": "get_case",
                                                                           "arguments": '{"case_id": "e1"}'}}]}}]})

    ledger = tmp_path / "usage.jsonl"
    app = make_app("https://gw.example/anthropic", ledger, transport=httpx.MockTransport(upstream),
                   openai_url="https://gw.example/custom-openai/v1/chat/completions", reasoning={"max_tokens": 200})
    hdr = {"X-SharedLLM-Key": "k", "Authorization": "Bearer pk", "anthropic-version": "2023-06-01"}
    with TestClient(app) as c:
        q = {"model": "m", "max_tokens": 32000, "stream": True, "tools": TOOLS[:1],
             "messages": [{"role": "user", "content": "q"}]}
        first = rebuild(parse(c.post("/v1/messages", json=q, headers=hdr).content.split(b"\n\n")[:-1]))
        assert first["stop_reason"] == "tool_use" and first["usage"] == {"input_tokens": 40, "output_tokens": 9}
        tu = first["content"][0]
        assert (tu["id"], tu["name"], tu["input"]) == ("call_9", "get_case", {"case_id": "e1"})
        q["messages"] += [{"role": "assistant", "content": first["content"]}, {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_9", "content": [{"type": "text", "text": "case e1"}]}]}]
        second = c.post("/v1/messages", json={**q, "stream": False}, headers=hdr).json()
        assert second["content"] == [{"type": "text", "text": "Done."}] and second["stop_reason"] == "end_turn"
        busy = c.post("/v1/messages", json={**q, "messages": [{"role": "user", "content": "busy"}]}, headers=hdr)
        assert busy.status_code == 429 and busy.headers["retry-after"] == "3"
        assert busy.json()["type"] == "error" and "rate limited" in busy.json()["error"]["message"]
    url, body, h = seen[0]
    assert url == "https://gw.example/custom-openai/v1/chat/completions"
    assert body["reasoning"] == {"max_tokens": 200} and body["max_tokens"] == 32000 and body["model"] == "m"
    assert h["x-sharedllm-key"] == "k" and "authorization" not in h and h["accept-encoding"] == "identity"
    assert seen[1][1]["messages"][1]["tool_calls"][0]["id"] == "call_9"
    assert seen[1][1]["messages"][2] == {"role": "tool", "tool_call_id": "call_9", "content": "case e1"}
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [(x["input_tokens"], x["output_tokens"]) for x in rows] == [(40, 9), (50, 5)]   # errors not metered
