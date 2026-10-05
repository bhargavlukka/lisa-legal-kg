"""CourtListener REST v4 client engineered for the free-tier quota (5/min, 50/hour, 125/day).

- Disk cache keyed by request (citation lookups keyed by the canonical citation) - a cached answer costs nothing.
- Quota ledger persisted on disk, so the daily cap survives restarts; requests that would exceed it are refused
  locally instead of being sent.
- Exponential backoff on HTTP 429 (honours Retry-After), bounded retries.
- Graceful degradation: no token, quota exhausted, or network failure -> a structured `unavailable` result, never
  an exception, so the rest of the system keeps working on the local corpus.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import httpx

from lisa.common.config import CourtListenerSettings
from lisa.graph.canon import canon, squash

WINDOWS = {"minute": 60, "hour": 3600, "day": 86400}


def unavailable(reason: str, **extra) -> dict:
    return {"status": "unavailable", "reason": reason,
            "note": "External lookup unavailable; answer from the local corpus only and label external "
                    "authorities as unverified.", **extra}


class Quota:
    def __init__(self, path: Path, limits: dict[str, int], clock=time.time):
        self.path, self.limits, self.clock = path, limits, clock
        try:
            self.stamps: list[float] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.stamps = []

    def _prune(self) -> None:
        now = self.clock()
        self.stamps = [t for t in self.stamps if now - t < WINDOWS["day"]]

    def used(self) -> dict[str, int]:
        self._prune()
        now = self.clock()
        return {w: sum(1 for t in self.stamps if now - t < s) for w, s in WINDOWS.items()}

    def blocked_by(self) -> str | None:
        used = self.used()
        for w in ("day", "hour", "minute"):
            if used[w] >= self.limits[w]:
                return w
        return None

    def wait_s(self, window: str) -> float:
        span = WINDOWS[window]
        inside = sorted(t for t in self.stamps if self.clock() - t < span)
        return max(0.0, span - (self.clock() - inside[0])) if inside else 0.0

    def record(self) -> None:
        self._prune()
        self.stamps.append(self.clock())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.stamps), encoding="utf-8")


class CourtListener:
    def __init__(self, cfg: CourtListenerSettings, cache_dir: Path, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep, clock=time.time, max_minute_wait_s: float = 65.0):
        self.cfg, self.cache_dir, self.sleep = cfg, cache_dir, sleep
        self.quota = Quota(cache_dir / "_quota.json",
                           {"minute": cfg.per_minute, "hour": cfg.per_hour, "day": cfg.per_day}, clock)
        self.max_minute_wait_s = max_minute_wait_s
        self.stats = {"requests": 0, "cache_hits": 0, "rate_limited": 0, "refused_quota": 0, "errors": 0}
        self._http = httpx.Client(base_url=cfg.base_url, timeout=cfg.timeout_s, transport=transport,
                                  headers={"Authorization": f"Token {cfg.token}"} if cfg.token else {})

    # ---------- cache ----------
    def _key_path(self, key: str) -> Path:
        return self.cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()[:32]}.json"

    def cached(self, key: str) -> dict | None:
        p = self._key_path(key)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))["data"]
        return None

    def _store(self, key: str, data: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._key_path(key).write_text(json.dumps({"key": key, "fetched_at": time.time(), "data": data},
                                                  ensure_ascii=False), encoding="utf-8")

    # ---------- transport ----------
    def _request(self, method: str, path: str, key: str, **kw) -> dict:
        if (hit := self.cached(key)) is not None:
            self.stats["cache_hits"] += 1
            return {"status": "ok", "cached": True, "data": hit}
        if not self.cfg.token:
            return unavailable("COURTLISTENER_TOKEN not set")
        for attempt in range(self.cfg.max_retries + 1):
            if (w := self.quota.blocked_by()) is not None:
                wait = self.quota.wait_s(w)
                if w != "minute" or wait > self.max_minute_wait_s:
                    self.stats["refused_quota"] += 1
                    return unavailable(f"CourtListener {w} quota exhausted", retry_after_s=round(wait))
                self.sleep(wait)
            self.quota.record()
            self.stats["requests"] += 1
            try:
                r = self._http.request(method, path, **kw)
            except httpx.HTTPError as e:
                self.stats["errors"] += 1
                return unavailable(f"network error: {type(e).__name__}")
            if r.status_code == 429:
                self.stats["rate_limited"] += 1
                retry = r.headers.get("Retry-After")
                delay = float(retry) if retry and retry.isdigit() else 2.0 * 2 ** attempt
                if attempt == self.cfg.max_retries or delay > self.max_minute_wait_s:
                    return unavailable("CourtListener rate limit (429)", retry_after_s=round(delay))
                self.sleep(delay)
                continue
            if r.status_code in (401, 403):
                return unavailable(f"CourtListener auth failed ({r.status_code})")
            if r.status_code == 404:
                data = {"not_found": True}
                self._store(key, data)
                return {"status": "ok", "cached": False, "data": data}
            if r.status_code >= 400:
                self.stats["errors"] += 1
                return unavailable(f"CourtListener HTTP {r.status_code}")
            data = r.json()
            self._store(key, data)
            return {"status": "ok", "cached": False, "data": data}
        return unavailable("CourtListener retries exhausted")

    # ---------- API ----------
    def lookup_citation(self, citation: str) -> dict:
        """Resolve one reporter citation (e.g. '585 U.S. 198') via the citation-lookup API."""
        c = canon(citation)
        res = self._request("POST", "/citation-lookup/", f"cite:{c.id}", data={"text": squash(citation)})
        if res["status"] != "ok":
            return res
        rows = res["data"] if isinstance(res["data"], list) else []
        clusters = [cl for row in rows for cl in (row.get("clusters") or [])]
        if not clusters:
            return {"status": "not_found", "citation": citation, "cached": res["cached"]}
        cl = clusters[0]
        return {"status": "resolved", "citation": citation, "cached": res["cached"],
                "case_name": cl.get("case_name"), "date_filed": cl.get("date_filed"),
                "cluster_id": cl.get("id"), "url": "https://www.courtlistener.com" + (cl.get("absolute_url") or ""),
                "citations": [f"{x.get('volume')} {x.get('reporter')} {x.get('page')}" for x in cl.get("citations") or []],
                "docket_id": cl.get("docket_id")}

    def search(self, query: str, limit: int = 5) -> dict:
        res = self._request("GET", "/search/", f"search:{squash(query).lower()}", params={"q": query, "type": "o"})
        if res["status"] != "ok":
            return res
        hits = []
        for h in (res["data"].get("results") or [])[:limit]:
            hits.append({"case_name": h.get("caseName"), "citation": h.get("citation"), "court": h.get("court"),
                         "date_filed": h.get("dateFiled"), "cluster_id": h.get("cluster_id"),
                         "url": "https://www.courtlistener.com" + (h.get("absolute_url") or ""),
                         "snippet": squash(" ".join(o.get("snippet", "") for o in h.get("opinions") or []))[:400]})
        return {"status": "ok", "cached": res["cached"], "count": res["data"].get("count"), "results": hits}

    def cluster(self, cluster_id: int) -> dict:
        res = self._request("GET", f"/clusters/{int(cluster_id)}/", f"cluster:{int(cluster_id)}")
        if res["status"] != "ok":
            return res
        d = res["data"]
        return {"status": "ok", "cached": res["cached"], "case_name": d.get("case_name"),
                "date_filed": d.get("date_filed"), "judges": d.get("judges"), "docket": d.get("docket"),
                "citations": d.get("citations"), "precedential_status": d.get("precedential_status"),
                "opinions": d.get("sub_opinions"), "syllabus": squash(d.get("syllabus") or "")[:800],
                "url": "https://www.courtlistener.com" + (d.get("absolute_url") or "")}

    def docket(self, docket_id: int) -> dict:
        res = self._request("GET", f"/dockets/{int(docket_id)}/", f"docket:{int(docket_id)}")
        if res["status"] != "ok":
            return res
        d = res["data"]
        keep = ("case_name", "docket_number", "court_id", "date_filed", "date_terminated", "cause", "nature_of_suit")
        return {"status": "ok", "cached": res["cached"], **{k: d.get(k) for k in keep},
                "url": "https://www.courtlistener.com" + (d.get("absolute_url") or "")}

    def quota_status(self) -> dict:
        return {"token_configured": bool(self.cfg.token), "used": self.quota.used(),
                "limits": self.quota.limits, "stats": dict(self.stats)}
