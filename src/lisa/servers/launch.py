"""Start all four MCP servers as separate processes and wait until each accepts connections."""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time

from lisa.common.config import load_serve_settings

MODULES = {"graph": "lisa.servers.graph_server", "verifier": "lisa.servers.citation_verifier",
           "analytics": "lisa.servers.analytics_server", "external": "lisa.servers.external_law_server"}


def wait_port(host: str, port: int, timeout: float = 60) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.3)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", choices=sorted(MODULES), help="subset of servers")
    a = ap.parse_args(argv)
    serve = load_serve_settings()
    names = a.only or list(MODULES)
    procs = {n: subprocess.Popen([sys.executable, "-m", MODULES[n]]) for n in names}
    try:
        for n in names:
            ok = wait_port(serve.host, serve.ports[n])
            print(f"{n:9s} {'up  ' if ok else 'FAILED'} http://{serve.host}:{serve.ports[n]}/mcp", flush=True)
            if not ok:
                return 1
        print("all servers up - Ctrl+C to stop", flush=True)
        while all(p.poll() is None for p in procs.values()):
            time.sleep(1)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for p in procs.values():
            p.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
