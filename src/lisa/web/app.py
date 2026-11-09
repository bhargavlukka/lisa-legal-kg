"""LISA web UI: ask a question in the browser and watch the agent work live (tool calls, model calls, verifier).

  python scripts/web.py            # http://127.0.0.1:8200  (the four MCP servers must be running)

GET /api/ask?q=...&session=...  streams the turn as server-sent events: one JSON object per progress event, then a
final {"type": "done", ...} with the rendered answer. One question runs at a time (the agent shares one proxy).
GET /api/live  streams the events of every turn, whoever asked it (the page uses it to show runs started elsewhere).
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from lisa.agent import usage_proxy
from lisa.agent.agent import ResearchAgent
from lisa.agent.memory.store import SessionMemory

STATIC = Path(__file__).resolve().parent / "static"
_FENCE = re.compile(r"<<<UNTRUSTED_CASE_TEXT[^\n]*\n?|\n?UNTRUSTED_CASE_TEXT>>>")
_NAME_KEYS = ("title", "case_name", "name", "citation", "case_id", "authority", "statute", "display")


def _clean(s) -> str:
    return _FENCE.sub("", str(s)).strip()


def _payload(resp):
    """MCP tool_response (content blocks, JSON text or dict) -> the tool's result dict, best effort."""
    if isinstance(resp, dict) and "content" in resp and not any(k in resp for k in ("results", "citing", "cited")):
        resp = resp.get("structuredContent") or resp["content"]
    if isinstance(resp, list):
        texts = [b.get("text", "") for b in resp if isinstance(b, dict) and b.get("type") == "text"]
        resp = "".join(texts) if texts else resp
    if isinstance(resp, str):
        try:
            return json.loads(resp)
        except ValueError:
            return resp
    return resp


def _label(item) -> str:
    if not isinstance(item, dict):
        return _clean(item)[:80]
    for k in _NAME_KEYS:
        if item.get(k):
            v = _clean(item[k])
            cit = _clean(item.get("citation") or "") if k != "citation" else ""
            return (f"{v} ({cit})" if cit and cit not in v else v)[:90]
    return ""


def summarize(tool: str, resp) -> dict:
    """Short human summary of a tool result for the activity feed: headline + up to 6 item labels."""
    p = _payload(resp)
    if tool == "Skill":
        return {"headline": "procedure loaded", "items": []}
    if isinstance(p, str):
        return {"headline": _clean(p)[:160], "items": []}
    if not isinstance(p, dict):
        return {"headline": "", "items": []}
    if p.get("status") == "unavailable":
        return {"headline": f"unavailable: {_clean(p.get('reason') or p.get('detail') or '')[:120]}", "items": []}
    if "passed" in p:                                       # verify_answer / verify_citation
        probs = p.get("problems") or []
        return {"headline": "all citations verified" if p["passed"] else f"{len(probs)} problem(s) found",
                "items": [_clean(x.get("detail") or x.get("kind"))[:110] for x in probs[:6] if isinstance(x, dict)]}
    if "text" in p and "page" in p:                         # read_page
        words = len(_clean(p["text"]).split())
        return {"headline": f"read page {p['page']} of {p.get('case_id')} ({words} words)", "items": []}
    for key in ("results", "citing", "cited", "chains", "precedents", "statutes", "bridges", "rows", "doctrines"):
        v = p.get(key)
        if isinstance(v, list):
            labels = [lab for lab in (_label(x) for x in v) if lab]
            n = p.get("count", len(v))
            return {"headline": f"{n} {key}", "items": list(dict.fromkeys(labels))[:6]}
    lab = _label(p)
    return {"headline": lab or ", ".join(list(p)[:6]), "items": []}


def make_app(agent=None):
    """agent: a ResearchAgent (default) or any object with the same ask()/settings/agent attributes (tests)."""
    from starlette.applications import Starlette
    from starlette.responses import FileResponse, StreamingResponse
    from starlette.routing import Route

    agent = agent or ResearchAgent()
    lock = asyncio.Lock()
    watchers: set[asyncio.Queue] = set()

    async def index(request):
        return FileResponse(STATIC / "index.html")

    async def ask(request):
        q = (request.query_params.get("q") or "").strip()
        session = re.sub(r"[^A-Za-z0-9_-]", "", request.query_params.get("session") or "web") or "web"
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def push(e: dict) -> None:
            if e.get("type") == "tool_end":
                e = dict(e)
                e.update(summarize(e.get("tool", ""), e.pop("result", None)))
            for qu in (queue, *watchers):
                loop.call_soon_threadsafe(qu.put_nowait, e)

        async def run():
            if lock.locked():
                push({"type": "note", "text": "Another question is running - waiting for it to finish..."})
            async with lock:
                usage_proxy.LISTENERS.append(push)
                try:
                    mem = SessionMemory(agent.settings.out_dir / agent.agent.sessions_dir, session)
                    r = await agent.ask(q, mem, on_event=push)
                    push({"type": "done", "question": q, "status": r.status, "text": r.text,
                          "latency_s": round(r.latency_s, 1), "tools": len(r.trajectory.tools),
                          "tool_names": r.trajectory.names(), "model_calls": r.trajectory.model_calls,
                          "revisions": r.revisions, "draft": r.draft, "report": r.report,
                          "input_tokens": r.trajectory.input_tokens, "output_tokens": r.trajectory.output_tokens})
                except Exception as e:                                  # surface, never hang the stream
                    push({"type": "done", "status": "error", "text": f"{type(e).__name__}: {e}"})
                finally:
                    usage_proxy.LISTENERS.remove(push)

        async def stream():
            if not q:
                yield f"data: {json.dumps({'type': 'done', 'status': 'error', 'text': 'empty question'})}\n\n"
                return
            task = asyncio.create_task(run())
            try:
                while True:
                    e = await queue.get()
                    yield f"data: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"
                    if e.get("type") == "done":
                        break
            finally:
                if not task.done():
                    await asyncio.wait({task}, timeout=0)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"cache-control": "no-cache"})

    async def live(request):
        queue: asyncio.Queue = asyncio.Queue()
        watchers.add(queue)

        async def stream():
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        e = await asyncio.wait_for(queue.get(), 15)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {json.dumps(e, ensure_ascii=False, default=str)}\n\n"
            finally:
                watchers.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"cache-control": "no-cache"})

    return Starlette(routes=[Route("/", index), Route("/api/ask", ask), Route("/api/live", live)])


def main(argv: list[str] | None = None) -> int:
    import argparse
    import uvicorn

    ap = argparse.ArgumentParser(description="LISA web UI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8200)
    a = ap.parse_args(argv)
    uvicorn.run(make_app(), host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
