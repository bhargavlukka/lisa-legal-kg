"""Persisted research-session memory: survives process restarts.

Two layers:
- the SDK session id (the CLI keeps the full transcript; we `resume` it when it still exists), and
- our own compact digest (questions, delivered answers, cases discussed) written atomically to
  out/sessions/<name>.json - injected into every prompt, so follow-ups like "compare that with the earlier case"
  work even when the CLI transcript is gone (fresh container, other machine).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_TURNS_IN_DIGEST = 6


class SessionMemory:
    def __init__(self, root: Path, name: str):
        if not _NAME.match(name):
            raise ValueError("session name: 1-64 chars of letters, digits, '_', '-', '.'")
        self.path = Path(root) / f"{name}.json"
        self.name = name
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {"name": name, "sdk_session_id": None, "turns": [], "created_at": time.time()}

    @property
    def sdk_session_id(self) -> str | None:
        return self.data.get("sdk_session_id")

    @property
    def turns(self) -> list[dict]:
        return self.data["turns"]

    def record(self, question: str, answer: str, cases: list[dict], status: str, sdk_session_id: str | None) -> None:
        self.data["turns"].append({"q": question, "answer": answer[:4000], "status": status, "ts": time.time(),
                                   "cases": cases})
        if sdk_session_id:
            self.data["sdk_session_id"] = sdk_session_id
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def digest(self) -> str:
        """Compact context for the next prompt; empty for a new session."""
        if not self.turns:
            return ""
        lines = [f"Research session '{self.name}' so far (most recent last):"]
        for i, t in enumerate(self.turns[-MAX_TURNS_IN_DIGEST:], 1):
            cases = ", ".join(f"{c.get('title') or c.get('case')} ({c.get('case_id') or c.get('citation') or ''})"
                              for c in t["cases"][:6])
            summary = re.sub(r"\s+", " ", t["answer"])[:400]
            lines.append(f"{i}. Q: {t['q']}\n   Cases discussed: {cases or 'none'}\n   Answer summary: {summary}")
        return "\n".join(lines)
