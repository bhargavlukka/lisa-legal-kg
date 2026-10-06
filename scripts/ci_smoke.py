"""Smoke-test a running LISA stack (compose or serve_all) over real HTTP: auth, role separation, tool results.

  python scripts/ci_smoke.py            # servers on 127.0.0.1:8101-8104, LISA_AUTH_SECRET from the environment

Exit code 0 only if every check passes.
"""
import sys
import time

import httpx

from lisa.agent.mcp_http import HEADERS, MCPCallError, call_tool
from lisa.common.auth import issue_token
from lisa.common.config import load_auth_settings, load_serve_settings

SERVE = load_serve_settings()
URL = {s: f"http://127.0.0.1:{p}/mcp" for s, p in SERVE.ports.items()}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}"[:240], flush=True)
    if not ok:
        failures.append(name)


def wait_up(timeout: float = 120) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if all(httpx.post(u, json=TOOLS_LIST, headers=HEADERS, timeout=3).status_code == 401 for u in URL.values()):
                return
        except httpx.HTTPError:
            pass
        time.sleep(2)
    raise SystemExit("servers did not come up")


def main() -> int:
    wait_up()
    auth = load_auth_settings()
    researcher, admin = issue_token(auth, "ci", "researcher"), issue_token(auth, "ci", "admin")
    for s, u in URL.items():
        r = httpx.post(u, json=TOOLS_LIST, headers=HEADERS, timeout=10)
        check(f"{s}: no token -> 401", r.status_code == 401, str(r.status_code))
        r = httpx.post(u, json=TOOLS_LIST, headers=HEADERS | {"Authorization": f"Bearer {researcher}"}, timeout=10)
        tools = [t["name"] for t in r.json().get("result", {}).get("tools", [])] if r.status_code == 200 else []
        check(f"{s}: researcher tools/list", bool(tools), ", ".join(tools))
    hits = call_tool(URL["graph"], researcher, "search_cases", {"query": "Pereira"})
    check("graph: search_cases returns results", bool(hits.get("results")), str(len(hits.get("results", []))))
    try:
        call_tool(URL["graph"], researcher, "graph_stats", {})
        check("graph: researcher refused admin tool", False, "graph_stats succeeded")
    except MCPCallError as e:
        check("graph: researcher refused admin tool", "admin" in str(e), str(e))
    stats = call_tool(URL["graph"], admin, "graph_stats", {})
    check("graph: admin graph_stats", bool(stats), str(stats)[:120])
    ext = call_tool(URL["external"], researcher, "resolve_citation", {"citation": "585 U.S. 198"})
    check("external: no CourtListener token degrades to 'unavailable'", ext.get("status") == "unavailable", str(ext))
    v = call_tool(URL["verifier"], researcher, "verify_answer", {"answer": "The Board held X.", "citations": []})
    check("verifier: uncited answer fails the gate", v.get("passed") is False, str(v.get("problems"))[:120])
    print(f"\n{len(failures)} failure(s)" + (": " + ", ".join(failures) if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
