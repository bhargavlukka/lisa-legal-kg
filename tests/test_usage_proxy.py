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
