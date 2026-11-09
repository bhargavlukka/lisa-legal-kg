"""Local metering proxy between the Claude CLI and the SharedLLM Anthropic route (spec 4.3 allows a local proxy).

Why: on streamed /v1/messages the gateway reports `input_tokens: 0` in message_start and never sends the real count,
and the CLI always streams - so the agent's input tokens (and hence cost per query) were unrecorded. The proxy sends
each streamed request upstream NON-streamed (that reply carries full usage), appends the usage to a JSONL ledger, and
replays the reply to the CLI as the equivalent Anthropic SSE event sequence. Errors pass through with their status.

Optional OpenAI route (`openai_url`): glm-flash's hidden reasoning is unbounded on the Anthropic route (30-85 s per call,
a `reasoning` cap is ignored there), while the gateway's OpenAI chat.completions route honours `reasoning: {max_tokens}`
(~5 s per call). So each /v1/messages is translated to chat.completions with the cap injected, and the reply translated
back to an Anthropic message before the same metering and SSE replay.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from pathlib import Path

import httpx

_HOP = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding"}
LISTENERS: list = []        # callables(event: dict), called from the proxy thread on each model call (live UI)


def _notify(event: dict) -> None:
    for fn in list(LISTENERS):
        try:
            fn(event)
        except Exception:
            pass


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def sse_events(msg: dict) -> list[bytes]:
    """A complete Anthropic Messages reply -> the SSE byte chunks a streamed request would have produced."""
    usage = dict(msg.get("usage") or {})
    head = {k: v for k, v in msg.items() if k not in ("content", "stop_reason", "stop_sequence", "usage")}
    out = [_sse("message_start", {"type": "message_start", "message": {
        **head, "content": [], "stop_reason": None, "stop_sequence": None, "usage": usage}})]
    # full usage already in message_start: the CLI snapshots usage per content block, before message_delta arrives
    for i, b in enumerate(msg.get("content") or []):
        t = b.get("type")
        if t == "text":
            start, deltas = {"type": "text", "text": ""}, [{"type": "text_delta", "text": b.get("text", "")}]
        elif t == "thinking":
            start = {"type": "thinking", "thinking": "", "signature": ""}
            deltas = [{"type": "thinking_delta", "thinking": b.get("thinking", "")}]
            if b.get("signature"):
                deltas.append({"type": "signature_delta", "signature": b["signature"]})
        elif t == "tool_use":
            start = {**b, "input": {}}
            deltas = [{"type": "input_json_delta", "partial_json": json.dumps(b.get("input") or {}, ensure_ascii=False)}]
        else:                                           # redacted_thinking etc.: whole block in the start event
            start, deltas = b, []
        out.append(_sse("content_block_start", {"type": "content_block_start", "index": i, "content_block": start}))
        out += [_sse("content_block_delta", {"type": "content_block_delta", "index": i, "delta": d}) for d in deltas]
        out.append(_sse("content_block_stop", {"type": "content_block_stop", "index": i}))
    out.append(_sse("message_delta", {"type": "message_delta", "usage": usage, "delta": {
        "stop_reason": msg.get("stop_reason") or "end_turn", "stop_sequence": msg.get("stop_sequence")}}))
    out.append(_sse("message_stop", {"type": "message_stop"}))
    return out


def _text(content) -> str:
    """Anthropic content (string or blocks) -> plain text; images become a marker (no vision on this route)."""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") if b.get("type") == "text" else f"[{b.get('type')}]"
                     for b in content or [] if isinstance(b, dict))


def to_openai(req: dict, reasoning: dict | None = None, min_tokens: int = 8192) -> dict:
    """Anthropic Messages request -> OpenAI chat.completions request (thinking blocks dropped from history)."""
    msgs = [{"role": "system", "content": _text(req["system"])}] if req.get("system") else []
    for m in req.get("messages") or []:
        content = m.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
        if m.get("role") == "assistant":
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            calls = [{"id": b["id"], "type": "function", "function": {
                "name": b["name"], "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}}
                for b in blocks if b.get("type") == "tool_use"]
            if text or calls:
                msgs.append({"role": "assistant", "content": text or None, **({"tool_calls": calls} if calls else {})})
            continue
        # user turn: tool results must directly follow the assistant's tool_calls, so they go first as role=tool
        for b in blocks:
            if b.get("type") == "tool_result":
                out = _text(b.get("content"))
                msgs.append({"role": "tool", "tool_call_id": b["tool_use_id"],
                             "content": f"[tool error] {out}" if b.get("is_error") else out})
        rest = _text([b for b in blocks if b.get("type") not in ("tool_result", "thinking", "redacted_thinking")])
        if rest:
            msgs.append({"role": "user", "content": rest})
    out = {"model": req.get("model"), "messages": msgs,
           # reasoning tokens count against max_tokens: a small request would leave no room for the answer
           "max_tokens": max(int(req.get("max_tokens") or 0), min_tokens)}
    for a, o in (("temperature", "temperature"), ("top_p", "top_p"), ("stop_sequences", "stop")):
        if req.get(a) is not None:
            out[o] = req[a]
    tools = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                               "parameters": t.get("input_schema") or {"type": "object"}}}
             for t in req.get("tools") or [] if "input_schema" in t]          # server tools (web_search...) skipped
    if tools:
        out["tools"] = tools
        tc = req.get("tool_choice") or {}
        kind = tc.get("type")
        if kind in ("auto", "any", "none"):
            out["tool_choice"] = {"auto": "auto", "any": "required", "none": "none"}[kind]
        elif kind == "tool":
            out["tool_choice"] = {"type": "function", "function": {"name": tc["name"]}}
        if tc.get("disable_parallel_tool_use"):
            out["parallel_tool_calls"] = False
    if reasoning:
        out["reasoning"] = reasoning
    return out


def from_openai(resp: dict, model: str | None) -> dict:
    """OpenAI chat.completion -> Anthropic message (OpenAI call ids kept as tool_use ids; reasoning text dropped)."""
    choice = (resp.get("choices") or [{}])[0]
    m = choice.get("message") or {}
    content = [{"type": "text", "text": m["content"]}] if m.get("content") else []
    for c in m.get("tool_calls") or []:
        f = c.get("function") or {}
        try:
            args = json.loads(f.get("arguments") or "{}")
        except ValueError:
            args = {}
        content.append({"type": "tool_use", "id": c.get("id") or f"toolu_{uuid.uuid4().hex[:24]}",
                        "name": f.get("name"), "input": args if isinstance(args, dict) else {}})
    has_calls = any(b["type"] == "tool_use" for b in content)
    fin = choice.get("finish_reason")
    stop = "tool_use" if has_calls or fin == "tool_calls" else "max_tokens" if fin == "length" else "end_turn"
    u = resp.get("usage") or {}
    return {"id": f"msg_{resp.get('id') or uuid.uuid4().hex}", "type": "message", "role": "assistant",
            "model": model or resp.get("model"), "content": content or [{"type": "text", "text": ""}],
            "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": int(u.get("prompt_tokens") or 0),
                      "output_tokens": int(u.get("completion_tokens") or 0)}}


def make_app(upstream: str, ledger: Path | None = None, transport: httpx.AsyncBaseTransport | None = None,
             openai_url: str | None = None, reasoning: dict | None = None):
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Route

    upstream = upstream.rstrip("/")
    client = httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=30.0), transport=transport)

    def record(path: str, msg: dict, latency: float) -> None:
        if ledger is None:
            return
        u = msg.get("usage") or {}
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "path": path, "model": msg.get("model"), "id": msg.get("id"),
                                "input_tokens": int(u.get("input_tokens") or 0),
                                "output_tokens": int(u.get("output_tokens") or 0),
                                "latency_s": round(latency, 2)}) + "\n")

    async def forward(request):
        path = request.url.path
        headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP}
        headers["accept-encoding"] = "identity"
        body = await request.body()
        stream, payload = False, None
        if request.method == "POST" and path.endswith("/v1/messages") and body:
            payload = json.loads(body)
            stream = bool(payload.pop("stream", False))
            body = json.dumps(payload).encode()
        t0 = time.time()
        is_msg = request.method == "POST" and path.endswith("/v1/messages")
        if is_msg:
            _notify({"type": "model_start"})
        if is_msg and openai_url and payload is not None:
            return await translated(path, payload, headers, stream, t0)
        r = await client.request(request.method, upstream + path, params=request.query_params, headers=headers,
                                 content=body)
        passthru = {k: v for k, v in r.headers.items() if k.lower().startswith(("x-", "retry-after", "request-id"))}
        if r.status_code != 200 or not path.endswith("/v1/messages") or request.method != "POST":
            return Response(r.content, status_code=r.status_code, headers=passthru,
                            media_type=r.headers.get("content-type"))
        return reply(path, r.json(), passthru, stream, t0, r.content)

    def reply(path, msg, passthru, stream, t0, raw=None):
        record(path, msg, time.time() - t0)
        u = msg.get("usage") or {}
        _notify({"type": "model_end", "s": round(time.time() - t0, 1), "output_tokens": int(u.get("output_tokens") or 0),
                 "tools": [b.get("name") for b in msg.get("content") or [] if b.get("type") == "tool_use"]})
        if not stream:
            return Response(raw or json.dumps(msg).encode(), headers=passthru, media_type="application/json")
        return Response(b"".join(sse_events(msg)), headers={**passthru, "cache-control": "no-cache"},
                        media_type="text/event-stream")

    async def translated(path, payload, headers, stream, t0):
        # the OpenAI route authenticates with X-SharedLLM-Key alone (the bearer may be a provider key)
        h = {"x-sharedllm-key": headers.get("x-sharedllm-key", ""), "content-type": "application/json",
             "accept-encoding": "identity"}
        r = await client.post(openai_url, headers=h, content=json.dumps(to_openai(payload, reasoning)).encode())
        passthru = {k: v for k, v in r.headers.items() if k.lower().startswith(("x-", "retry-after", "request-id"))}
        try:
            resp = r.json() if r.status_code == 200 else None
        except ValueError:
            resp = None
        if not resp or not resp.get("choices"):     # Anthropic-shaped error so the CLI's retry logic still applies
            err = {"type": "error", "error": {"type": "api_error", "message": r.text[:2000]}}
            return Response(json.dumps(err).encode(), status_code=r.status_code if r.status_code != 200 else 502,
                            headers=passthru, media_type="application/json")
        return reply(path, from_openai(resp, payload.get("model")), passthru, stream, t0)

    return Starlette(routes=[Route("/{rest:path}", forward, methods=["GET", "POST"])])


def start(upstream: str, ledger: Path | None = None, openai_url: str | None = None,
          reasoning: dict | None = None) -> str:
    """Serve the proxy on 127.0.0.1 in a daemon thread; returns its base URL."""
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(make_app(upstream, ledger, openai_url=openai_url, reasoning=reasoning), host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="off"))
    threading.Thread(target=server.run, daemon=True, name="usage-proxy").start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("usage proxy did not start")
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}"
