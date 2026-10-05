import json

import httpx
import pytest

from lisa.common.config import CourtListenerSettings
from lisa.common.courtlistener import CourtListener

LOOKUP = [{"citation": "593 U.S. 155", "status": 200, "clusters": [
    {"id": 5, "case_name": "Niz-Chavez v. Garland", "date_filed": "2021-04-29", "absolute_url": "/opinion/5/niz/",
     "citations": [{"volume": 593, "reporter": "U.S.", "page": "155"}], "docket_id": 9}]}]


def cfg(token="tok", **over):
    base = dict(base_url="https://cl.test/api/rest/v4", token=token, per_minute=5, per_hour=50, per_day=125,
                timeout_s=5, max_retries=3)
    base.update(over)
    return CourtListenerSettings(**base)


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def client(tmp_path, handler, **over):
    clock = Clock()
    seen = []

    def h(req):
        seen.append(req)
        return handler(req, len(seen))
    c = CourtListener(cfg(**over), tmp_path / "cl", transport=httpx.MockTransport(h), sleep=clock.sleep, clock=clock)
    return c, seen, clock


def test_resolve_then_cache_hit_costs_nothing(tmp_path):
    c, seen, _ = client(tmp_path, lambda req, n: httpx.Response(200, json=LOOKUP))
    r = c.lookup_citation("593 U. S. 155")
    assert r["status"] == "resolved" and r["case_name"] == "Niz-Chavez v. Garland" and not r["cached"]
    assert seen[0].headers["Authorization"] == "Token tok"
    r2 = c.lookup_citation("593 U.S.\n155")                       # same canonical citation -> cache
    assert r2["cached"] and len(seen) == 1 and c.stats["cache_hits"] == 1


def test_no_token_degrades_without_network(tmp_path):
    c, seen, _ = client(tmp_path, lambda req, n: httpx.Response(200, json=LOOKUP), token=None)
    r = c.lookup_citation("593 U.S. 155")
    assert r["status"] == "unavailable" and "TOKEN" in r["reason"] and not seen


def test_429_backoff_then_success(tmp_path):
    c, seen, clock = client(tmp_path, lambda req, n: httpx.Response(429, headers={"Retry-After": "3"}) if n == 1
                            else httpx.Response(200, json=LOOKUP))
    t0 = clock.t
    assert c.lookup_citation("593 U.S. 155")["status"] == "resolved"
    assert len(seen) == 2 and clock.t - t0 >= 3 and c.stats["rate_limited"] == 1


def test_429_forever_degrades(tmp_path):
    c, seen, _ = client(tmp_path, lambda req, n: httpx.Response(429))
    r = c.lookup_citation("593 U.S. 155")
    assert r["status"] == "unavailable" and "429" in r["reason"] and len(seen) == 4


def test_daily_quota_refused_locally_and_persisted(tmp_path):
    c, seen, clock = client(tmp_path, lambda req, n: httpx.Response(200, json={"results": [], "count": 0}),
                            per_day=2, per_minute=10, per_hour=10)
    assert c.search("a")["status"] == "ok" and c.search("b")["status"] == "ok"
    r = c.search("c")
    assert r["status"] == "unavailable" and "day" in r["reason"] and len(seen) == 2
    again = CourtListener(cfg(per_day=2, per_minute=10, per_hour=10), tmp_path / "cl", clock=clock,
                          transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})))
    assert again.quota.blocked_by() == "day"                       # ledger survives restart
    assert c.search("a")["cached"]                                 # cache still serves while quota is exhausted


def test_minute_window_waits_instead_of_failing(tmp_path):
    c, seen, clock = client(tmp_path, lambda req, n: httpx.Response(200, json={"results": [], "count": 0}),
                            per_minute=2)
    t0 = clock.t
    for q in "abc":
        assert c.search(q)["status"] == "ok"
    assert len(seen) == 3 and clock.t - t0 >= 59


def test_network_error_and_not_found(tmp_path):
    def boom(req, n):
        raise httpx.ConnectError("down")
    c, _, _ = client(tmp_path, boom)
    assert c.cluster(1)["status"] == "unavailable"
    c2, _, _ = client(tmp_path / "x", lambda req, n: httpx.Response(200, json=[{"clusters": []}]))
    assert c2.lookup_citation("1 U.S. 1")["status"] == "not_found"


def test_search_shapes_results(tmp_path):
    body = {"count": 1, "results": [{"caseName": "Niz-Chavez", "citation": ["593 U.S. 155"], "court": "SCOTUS",
                                      "dateFiled": "2021-04-29", "cluster_id": 5, "absolute_url": "/o/5/",
                                      "opinions": [{"snippet": "notice  to\nappear"}]}]}
    c, seen, _ = client(tmp_path, lambda req, n: httpx.Response(200, json=body))
    r = c.search("niz chavez")
    assert r["results"][0]["snippet"] == "notice to appear" and seen[0].url.params["type"] == "o"
    assert json.loads((tmp_path / "cl" / "_quota.json").read_text())
