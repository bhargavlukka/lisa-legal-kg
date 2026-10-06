"""The four MCP servers over real streamable HTTP: auth (401), role separation, tool results."""
import json
import socket
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
import uvicorn

from lisa.common.auth import issue_token
from lisa.common.config import AuthSettings, ServeSettings
from lisa.servers import analytics_server, citation_verifier, external_law_server, graph_server
from lisa.store.memory import MemoryStore

AUTH = AuthSettings(issuer="lisa-auth", audience="lisa-mcp", token_ttl_s=600, secret="k" * 64)
H = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
     "MCP-Protocol-Version": "2025-06-18"}


class FakeCL:
    def __init__(self):
        self.cache_dir = None

    def lookup_citation(self, c):
        return {"status": "unavailable", "reason": "COURTLISTENER_TOKEN not set"}

    def quota_status(self):
        return {"token_configured": False}


def serve(build, store, service, **kw):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    ctx = SimpleNamespace(store=store, auth=AUTH, service=service,
                          serve=ServeSettings("all", (), "memory", "127.0.0.1", {service: port}))
    app = build(ctx, True, **kw).streamable_http_app(host="127.0.0.1", json_response=True, stateless_http=True)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}/mcp", server


def call(url, tool, args, token):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    r = httpx.post(url, json=body, headers=H | ({"Authorization": f"Bearer {token}"} if token else {}), timeout=20)
    if r.status_code != 200:
        return r.status_code, None
    res = r.json()["result"]
    return 200, (res["content"][0]["text"] if res.get("isError") else json.loads(res["content"][0]["text"]))


@pytest.fixture
def researcher():
    return issue_token(AUTH, "alice", "researcher")


@pytest.fixture
def admin():
    return issue_token(AUTH, "root", "admin")


def test_graph_server_auth_and_roles(graph_all, researcher, admin):
    url, srv = serve(graph_server.build, MemoryStore([graph_all]), "graph")
    try:
        assert call(url, "search_cases", {"query": "Pereira"}, None)[0] == 401
        assert call(url, "search_cases", {"query": "Pereira"}, "not-a-jwt")[0] == 401
        code, out = call(url, "search_cases", {"query": "Pereira v. Sessions"}, researcher)
        assert code == 200 and out["results"][0]["case_id"] == "scotus_2017_17-459"
        _, page = call(url, "read_page", {"case_id": "eoir_1", "page": 2}, researcher)
        assert page["untrusted"] and page["text"].startswith("<<<UNTRUSTED_CASE_TEXT")
        _, err = call(url, "graph_stats", {}, researcher)
        assert isinstance(err, str) and "admin role required" in err
        _, stats = call(url, "graph_stats", {}, admin)
        assert stats["nodes"]["Case"] == 3
        _, err = call(url, "get_case", {"case_id": "Nonexistent v. Nobody"}, researcher)
        assert "not in corpus" in err
    finally:
        srv.should_exit = True


def test_verifier_analytics_external_servers(graph_all, researcher, admin):
    store = MemoryStore([graph_all])
    v_url, v = serve(citation_verifier.build, store, "verifier", external=FakeCL())
    a_url, a = serve(analytics_server.build, store, "analytics")
    e_url, e = serve(external_law_server.build, store, "external", client=FakeCL())
    try:
        _, r = call(v_url, "verify_citation", {"case": "eoir_1", "quote": "the notice was defective under", "page": 2},
                    researcher)
        assert r["tier"] == "unverified"                         # words exist but not in this order
        _, r = call(v_url, "verify_citation", {"case": "eoir_1", "quote": "Sessions, 585 U. S. 198 (2018), the notice was defective", "page": 2}, researcher)
        assert r["tier"] == "verified_in_corpus"
        _, r = call(v_url, "verify_citation", {"case": "593 U.S. 155"}, researcher)
        assert r["tier"] == "unverified" and "TOKEN" in r["reason"]      # graceful degradation
        _, r = call(a_url, "cross_corpus_bridges", {}, researcher)
        assert r["unique_pairs"] == 1
        assert "admin" in call(a_url, "refresh_analytics", {}, researcher)[1]
        assert call(a_url, "refresh_analytics", {}, admin)[1]["status"] == "ok"
        _, r = call(e_url, "resolve_citation", {"citation": "593 U.S. 155"}, researcher)
        assert r["status"] == "unavailable"
        assert call(e_url, "quota_status", {}, researcher)[1] == {"token_configured": False}
    finally:
        for s in (v, a, e):
            s.should_exit = True
