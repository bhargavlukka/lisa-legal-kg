"""Local metering proxy between the Claude CLI and the SharedLLM Anthropic route (spec 4.3 allows a local proxy).

Why: on streamed /v1/messages the gateway reports `input_tokens: 0` in message_start and never sends the real count,
and the CLI always streams - so the agent's input tokens (and hence cost per query) were unrecorded. The proxy sends
each streamed request upstream NON-streamed (that reply carries full usage), appends the usage to a JSONL ledger, and
replays the reply to the CLI as the equivalent Anthropic SSE event sequence. Errors pass through with their status.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import httpx

_HOP = {"host", "content-length", "connection", "accept-encoding", "transfer-encoding"}


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


def make_app(upstream: str, ledger: Path | None = None, transport: httpx.AsyncBaseTransport | None = None):
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
        stream = False
        if request.method == "POST" and path.endswith("/v1/messages") and body:
            payload = json.loads(body)
            stream = bool(payload.pop("stream", False))
            body = json.dumps(payload).encode()
        t0 = time.time()
        r = await client.request(request.method, upstream + path, params=request.query_params, headers=headers,
                                 content=body)
        passthru = {k: v for k, v in r.headers.items() if k.lower().startswith(("x-", "retry-after", "request-id"))}
        if r.status_code != 200 or not path.endswith("/v1/messages") or request.method != "POST":
            return Response(r.content, status_code=r.status_code, headers=passthru,
                            media_type=r.headers.get("content-type"))
        msg = r.json()
        record(path, msg, time.time() - t0)
        if not stream:
            return Response(r.content, headers=passthru, media_type="application/json")
        return Response(b"".join(sse_events(msg)), headers={**passthru, "cache-control": "no-cache"},
                        media_type="text/event-stream")

    return Starlette(routes=[Route("/{rest:path}", forward, methods=["GET", "POST"])])


def start(upstream: str, ledger: Path | None = None) -> str:
    """Serve the proxy on 127.0.0.1 in a daemon thread; returns its base URL."""
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(make_app(upstream, ledger), host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="off"))
    threading.Thread(target=server.run, daemon=True, name="usage-proxy").start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("usage proxy did not start")
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}"
