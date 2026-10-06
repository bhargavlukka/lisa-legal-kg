"""Minimal MCP streamable-HTTP tool call (JSON response mode) used by code paths that must not depend on the model."""
from __future__ import annotations

import json

import httpx

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
           "MCP-Protocol-Version": "2025-06-18"}


class MCPCallError(RuntimeError):
    pass


def call_tool(url: str, token: str, name: str, arguments: dict, timeout: float = 120) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    r = httpx.post(url, json=body, headers=HEADERS | {"Authorization": f"Bearer {token}"}, timeout=timeout)
    if r.status_code != 200:
        raise MCPCallError(f"{name}: HTTP {r.status_code} {r.text[:200]}")
    msg = r.json()
    if "error" in msg:
        raise MCPCallError(f"{name}: {msg['error']}")
    res = msg["result"]
    text = res["content"][0]["text"] if res.get("content") else "{}"
    if res.get("isError"):
        raise MCPCallError(f"{name}: {text}")
    return res.get("structuredContent") or json.loads(text)
