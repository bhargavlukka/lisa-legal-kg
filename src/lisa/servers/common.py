"""Shared wiring for the four MCP servers: config, store, auth, tracing, transport."""
from __future__ import annotations

import argparse
import functools
import inspect
import json
import time
import warnings

from lisa.common.auth import JWTVerifier
from lisa.common.config import (load_auth_settings, load_courtlistener_settings, load_serve_settings,
                                load_settings)
from lisa.common.tracing import setup_tracing, span


class Ctx:
    """Everything a server needs, loaded once."""

    def __init__(self, service: str, need_store: bool = True):
        self.settings = load_settings()
        self.serve = load_serve_settings()
        self.auth = load_auth_settings()
        self.cl_settings = load_courtlistener_settings()
        self.service = service
        setup_tracing(service, self.settings.out_dir)
        self._store = None
        self.need_store = need_store

    @property
    def store(self):
        if self._store is None:
            from lisa.store import open_store
            self._store = open_store(self.settings, self.serve)
        return self._store

    def courtlistener(self):
        from lisa.common.courtlistener import CourtListener
        return CourtListener(self.cl_settings, self.settings.out_dir / "cl_cache")


def traced(service: str):
    """Decorator: wrap a tool in an OTel span recording arguments, latency and outcome."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            bound = inspect.signature(fn).bind_partial(*args, **kwargs)
            t = time.perf_counter()
            with span(f"tool.{service}.{fn.__name__}", **{"tool.server": service, "tool.name": fn.__name__,
                                                         "tool.args": json.dumps(bound.arguments, default=str)}) as sp:
                try:
                    out = fn(*args, **kwargs)
                except (ValueError, PermissionError, KeyError) as e:
                    # anticipated failures (bad input, missing role): the reason is shown to the caller
                    from mcp.server.mcpserver.exceptions import ToolError
                    sp.set_attribute("tool.error", f"{type(e).__name__}: {e}")
                    raise ToolError(str(e)) from e
                except Exception as e:
                    sp.set_attribute("tool.error", f"{type(e).__name__}: {e}")
                    raise
                sp.set_attribute("tool.latency_ms", round((time.perf_counter() - t) * 1000, 2))
                if isinstance(out, dict):
                    for k in ("tier", "passed", "status"):
                        if k in out and isinstance(out[k], (str, bool)):
                            sp.set_attribute(f"tool.result.{k}", out[k])
                return out
        return wrapper
    return deco


def make_server(name: str, instructions: str, ctx: Ctx, auth_enabled: bool):
    from mcp.server.auth.settings import AuthSettings
    from mcp.server.mcpserver import MCPServer
    if not auth_enabled:
        return MCPServer(name, instructions=instructions)
    if not ctx.auth.secret:
        raise SystemExit("LISA_AUTH_SECRET is not set; run with --no-auth only for local debugging")
    port = ctx.serve.ports[ctx.service]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        settings = AuthSettings(issuer_url=f"http://{ctx.serve.host}:{port}", required_scopes=["lisa:read"],
                                resource_server_url=f"http://{ctx.serve.host}:{port}/mcp",
                                validate_token_resource=False)
    return MCPServer(name, instructions=instructions, token_verifier=JWTVerifier(ctx.auth), auth=settings)


def cli(service: str, build) -> None:
    ap = argparse.ArgumentParser(description=f"LISA {service} MCP server")
    ap.add_argument("--transport", choices=["streamable-http", "stdio"], default="streamable-http")
    ap.add_argument("--no-auth", action="store_true", help="disable bearer-token auth (local debugging only)")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    a = ap.parse_args()
    ctx = Ctx(service)
    auth_enabled = a.transport == "streamable-http" and not a.no_auth
    server = build(ctx, auth_enabled)
    if a.transport == "stdio":
        server.run("stdio")
        return
    import uvicorn
    host = a.host or ctx.serve.host
    app = server.streamable_http_app(host=host, json_response=True, stateless_http=True)
    uvicorn.run(app, host=host, port=a.port or ctx.serve.ports[service], log_level="warning")
