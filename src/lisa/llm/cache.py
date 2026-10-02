"""Disk cache of raw LLM responses: out/llm_cache/<sha256>.json. Reruns are free; --offline serves only from here."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


class Cache:
    def __init__(self, root: Path):
        self.root = Path(root)

    @staticmethod
    def key(prompt_version: str, params: dict, messages: list[dict]) -> str:
        blob = json.dumps({"v": prompt_version, "p": params, "m": messages}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        p = self.root / f"{key}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def put(self, key: str, payload: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f"{key}.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.root / f"{key}.json")
