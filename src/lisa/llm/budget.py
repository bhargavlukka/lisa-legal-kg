"""Per-run request budget, run statistics and retry delays."""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field

BASE_DELAY_S = 2.0
MAX_DELAY_S = 120.0


class BudgetExhausted(RuntimeError):
    pass


class Budget:
    def __init__(self, max_requests: int):
        self.max_requests = max_requests
        self.used = 0

    def charge(self) -> None:
        if self.used >= self.max_requests:
            raise BudgetExhausted(f"request budget of {self.max_requests} reached")
        self.used += 1


@dataclass
class RunStats:
    requests: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    rate_limited: int = 0
    retries: int = 0
    repairs: int = 0
    truncations: int = 0
    failed: list[dict] = field(default_factory=list)
    schema_rejects: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


def retry_delay(attempt: int, retry_after: str | None, rng: random.Random) -> float:
    if retry_after:
        try:
            return min(float(retry_after), MAX_DELAY_S)
        except ValueError:
            pass
    return min(MAX_DELAY_S, BASE_DELAY_S * 2 ** (attempt - 1)) * (0.5 + rng.random() / 2)
