"""SharedLLM chat client (OpenAI-compatible /chat/completions) with disk cache, request budget and backoff."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass

import httpx

from lisa.common.config import LLMSettings
from lisa.llm.budget import Budget, RunStats, retry_delay
from lisa.llm.cache import Cache

MAX_ATTEMPTS = 6


class LLMError(RuntimeError):
    pass


class CacheMiss(LLMError):
    pass


@dataclass(frozen=True)
class Completion:
    text: str
    finish_reason: str
    input_tokens: int
    output_tokens: int
    cached: bool


def _completion(payload: dict, cached: bool) -> Completion:
    try:
        choice = payload["choices"][0]
        text = choice["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"malformed response: {str(payload)[:200]}") from None
    usage = payload.get("usage") or {}
    return Completion(text, choice.get("finish_reason") or "stop", int(usage.get("prompt_tokens") or 0),
                      int(usage.get("completion_tokens") or 0), cached)


class LLMClient:
    def __init__(self, settings: LLMSettings, cache: Cache, budget: Budget, stats: RunStats, *,
                 offline: bool = False, transport: httpx.BaseTransport | None = None, sleep=time.sleep,
                 rng: random.Random | None = None):
        self.settings, self.cache, self.budget, self.stats = settings, cache, budget, stats
        self.offline, self.sleep, self.rng = offline, sleep, rng or random.Random()
        self._http = None
        if not offline and settings.api_key:
            self._http = httpx.Client(
                base_url=settings.base_url.rstrip("/") + "/", timeout=settings.timeout_s, transport=transport,
                headers={"X-SharedLLM-Key": settings.api_key, "Authorization": f"Bearer {settings.api_key}"})

    def _params(self) -> dict:
        p = {"model": self.settings.model, "temperature": self.settings.temperature,
             "max_tokens": self.settings.max_output_tokens}
        if self.settings.json_mode:
            p["response_format"] = {"type": "json_object"}
        return p

    def complete(self, messages: list[dict], prompt_version: str) -> Completion:
        params = self._params()
        key = Cache.key(prompt_version, params, messages)
        hit = self.cache.get(key)
        if hit is not None:
            self.stats.cache_hits += 1
            return _completion(hit, cached=True)
        if self.offline:
            raise CacheMiss(f"offline and not cached: {key[:12]}")
        if self._http is None:
            raise LLMError("SHAREDLLM_API_KEY is not set (add it to .env)")
        body = {**params, "messages": messages}
        status, err = None, ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.budget.charge()
            self.stats.requests += 1
            retry_after = None
            try:
                r = self._http.post("chat/completions", json=body)
            except httpx.TransportError as e:
                status, err = None, f"{type(e).__name__}: {e}"
            else:
                if r.status_code == 200:
                    payload = r.json()
                    self.cache.put(key, payload)
                    c = _completion(payload, cached=False)
                    self.stats.input_tokens += c.input_tokens
                    self.stats.output_tokens += c.output_tokens
                    return c
                status, err, retry_after = r.status_code, r.text[:300], r.headers.get("Retry-After")
                if status == 429:
                    self.stats.rate_limited += 1
                elif status < 500:
                    raise LLMError(f"HTTP {status}: {err}")
            if attempt < MAX_ATTEMPTS:
                self.stats.retries += 1
                self.sleep(retry_delay(attempt, retry_after, self.rng))
        raise LLMError(f"gave up after {MAX_ATTEMPTS} attempts: {status} {err}")
