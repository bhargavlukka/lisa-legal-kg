import json
import random

import httpx
import pytest

from fakes import chat_payload, llm_settings
from lisa.llm.budget import Budget, BudgetExhausted, RunStats, retry_delay
from lisa.llm.cache import Cache
from lisa.llm.client import CacheMiss, LLMClient, LLMError

MSG = [{"role": "user", "content": "hi"}]


def make(tmp_path, responses, *, budget=100, offline=False, **over):
    seen, sleeps = [], []

    def handler(request):
        seen.append(request)
        status, body, headers = responses.pop(0)
        return httpx.Response(status, json=body, headers=headers)

    stats = RunStats()
    c = LLMClient(llm_settings(**over), Cache(tmp_path / "cache"), Budget(budget), stats, offline=offline,
                  transport=httpx.MockTransport(handler), sleep=sleeps.append, rng=random.Random(0))
    return c, stats, seen, sleeps


def test_success_sends_headers_body_and_caches(tmp_path):
    c, stats, seen, _ = make(tmp_path, [(200, chat_payload('{"a":1}'), {})])
    out = c.complete(MSG, "v1")
    assert out.text == '{"a":1}' and out.finish_reason == "stop" and not out.cached
    req = seen[0]
    assert str(req.url) == "https://llm.test/openai/v1/chat/completions"
    assert req.headers["X-SharedLLM-Key"] == "k-test"
    # the gateway forwards a supplied Authorization header to the upstream provider as-is (-> 401 there)
    assert "authorization" not in req.headers
    body = json.loads(req.content)
    assert body["model"] == "test-model" and body["temperature"] == 0.0 and body["max_tokens"] == 1000
    assert body["response_format"] == {"type": "json_object"} and body["messages"] == MSG
    assert (stats.requests, stats.input_tokens, stats.output_tokens) == (1, 11, 7)
    again = c.complete(MSG, "v1")
    assert again.cached and again.text == '{"a":1}' and len(seen) == 1 and stats.cache_hits == 1


def test_prompt_version_changes_cache_key(tmp_path):
    c, _, seen, _ = make(tmp_path, [(200, chat_payload("x"), {}), (200, chat_payload("y"), {})])
    assert c.complete(MSG, "v1").text == "x"
    assert c.complete(MSG, "v2").text == "y" and len(seen) == 2


def test_429_honors_retry_after(tmp_path):
    c, stats, _, sleeps = make(tmp_path, [(429, {}, {"Retry-After": "7"}), (200, chat_payload("ok"), {})])
    assert c.complete(MSG, "v1").text == "ok"
    assert sleeps == [7.0] and stats.rate_limited == 1 and stats.retries == 1 and stats.requests == 2


def test_5xx_backoff_then_give_up(tmp_path):
    c, stats, seen, sleeps = make(tmp_path, [(503, {}, {})] * 6)
    with pytest.raises(LLMError, match="gave up after 6 attempts"):
        c.complete(MSG, "v1")
    assert len(seen) == 6 and len(sleeps) == 5 and all(0 < s <= 120 for s in sleeps)


def test_4xx_is_not_retried(tmp_path):
    c, _, seen, sleeps = make(tmp_path, [(401, {"error": "bad key"}, {})])
    with pytest.raises(LLMError, match="HTTP 401"):
        c.complete(MSG, "v1")
    assert len(seen) == 1 and sleeps == []


def test_budget_exhausted_mid_retry(tmp_path):
    c, _, _, _ = make(tmp_path, [(429, {}, {}), (200, chat_payload("ok"), {})], budget=1)
    with pytest.raises(BudgetExhausted):
        c.complete(MSG, "v1")


def test_offline_hit_and_miss(tmp_path):
    online, _, _, _ = make(tmp_path, [(200, chat_payload("cached"), {})])
    online.complete(MSG, "v1")
    off, stats, _, _ = make(tmp_path, [], offline=True, api_key=None)
    assert off.complete(MSG, "v1").text == "cached" and stats.requests == 0
    with pytest.raises(CacheMiss):
        off.complete([{"role": "user", "content": "new"}], "v1")


def test_missing_key_is_clear_error(tmp_path):
    c, _, _, _ = make(tmp_path, [], api_key=None)
    with pytest.raises(LLMError, match="SHAREDLLM_API_KEY is not set"):
        c.complete(MSG, "v1")


def test_malformed_payload_is_llm_error(tmp_path):
    c, _, _, _ = make(tmp_path, [(200, {"nope": 1}, {})])
    with pytest.raises(LLMError, match="malformed response"):
        c.complete(MSG, "v1")


def test_json_mode_off_omits_response_format(tmp_path):
    c, _, seen, _ = make(tmp_path, [(200, chat_payload("x"), {})], json_mode=False)
    c.complete(MSG, "v1")
    assert "response_format" not in json.loads(seen[0].content)


def test_retry_delay_bounds():
    rng = random.Random(1)
    assert retry_delay(1, "3", rng) == 3.0
    assert retry_delay(1, "999", rng) == 120.0
    assert 1.0 <= retry_delay(1, None, rng) <= 2.0
    assert 60.0 <= retry_delay(10, "soon", rng) <= 120.0


def test_cache_put_is_atomic_and_readable(tmp_path):
    cache = Cache(tmp_path / "c")
    k = Cache.key("v", {"model": "m"}, MSG)
    assert cache.get(k) is None
    cache.put(k, {"x": "ü"})
    assert cache.get(k) == {"x": "ü"} and not list((tmp_path / "c").glob("*.tmp"))


def test_bearer_auth_sends_authorization_only(tmp_path):
    c, _, seen, _ = make(tmp_path, [(200, chat_payload("x"), {})], auth="bearer", api_key_env="OLLAMA_API_KEY")
    c.complete(MSG, "v1")
    assert seen[0].headers["Authorization"] == "Bearer k-test"
    assert "x-sharedllm-key" not in seen[0].headers


def test_missing_key_error_names_the_configured_env_var(tmp_path):
    c, _, _, _ = make(tmp_path, [], api_key=None, auth="bearer", api_key_env="OLLAMA_API_KEY")
    with pytest.raises(LLMError, match="OLLAMA_API_KEY is not set"):
        c.complete(MSG, "v1")


def test_sharedllm_byok_sends_gateway_key_and_provider_bearer(tmp_path):
    c, _, seen, _ = make(tmp_path, [(200, chat_payload("x"), {})], auth="sharedllm_byok",
                         provider_key="prov-key", provider_key_env="OLLAMA_API_KEY")
    c.complete(MSG, "v1")
    assert seen[0].headers["X-SharedLLM-Key"] == "k-test"
    assert seen[0].headers["Authorization"] == "Bearer prov-key"


def test_sharedllm_byok_requires_provider_key(tmp_path):
    c, _, _, _ = make(tmp_path, [], auth="sharedllm_byok", provider_key=None, provider_key_env="OLLAMA_API_KEY")
    with pytest.raises(LLMError, match="OLLAMA_API_KEY is not set"):
        c.complete(MSG, "v1")


def test_sharedllm_sends_only_virtual_key_and_asks_for_uncompressed_replies(tmp_path):
    # the gateway pads replies with leading whitespace, which breaks gzip decoding (DecodingError, 2026-10-05)
    c, _, seen, _ = make(tmp_path, [(200, chat_payload("x"), {})], auth="sharedllm")
    c.complete(MSG, "v1")
    assert seen[0].headers["X-SharedLLM-Key"] == "k-test"
    assert "Authorization" not in seen[0].headers
    assert seen[0].headers["Accept-Encoding"] == "identity"


def test_reasoning_cap_is_sent_and_part_of_the_cache_key(tmp_path):
    # glm-flash otherwise spends the whole output budget on hidden reasoning (finish_reason length, empty content)
    c, _, seen, _ = make(tmp_path, [(200, chat_payload("x"), {})], reasoning={"max_tokens": 2048})
    c.complete(MSG, "v1")
    assert json.loads(seen[0].content)["reasoning"] == {"max_tokens": 2048}
    assert c._params()["reasoning"] == {"max_tokens": 2048}
    plain, _, seen2, _ = make(tmp_path / "p", [(200, chat_payload("x"), {})])
    plain.complete(MSG, "v1")
    assert "reasoning" not in json.loads(seen2[0].content)


def test_truncated_or_empty_replies_are_returned_but_never_cached(tmp_path):
    c, stats, _, _ = make(tmp_path, [(200, chat_payload("", "length"), {}), (200, chat_payload("", "stop"), {}),
                                     (200, chat_payload('{"ok": 1}'), {}), ])
    assert c.complete(MSG, "v1").finish_reason == "length"     # caller still sees the truncation
    assert c.complete(MSG, "v1").text == ""                     # not replayed from cache: a fresh request
    assert c.complete(MSG, "v1").text == '{"ok": 1}'
    assert c.complete(MSG, "v1").cached and stats.requests == 3  # only the good reply was cached


def test_non_json_200_is_an_llm_error(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, text="<html>gateway</html>")
    c = LLMClient(llm_settings(), Cache(tmp_path / "c"), Budget(5), RunStats(), transport=httpx.MockTransport(handler),
                  sleep=lambda s: None, rng=random.Random(0))
    with pytest.raises(LLMError, match="malformed"):
        c.complete(MSG, "v1")
