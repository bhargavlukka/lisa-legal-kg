"""Ask the model for {"<key>": [...]} and get a Python list back, with one repair retry."""
from __future__ import annotations

import json
import re

from lisa.llm.budget import RunStats


class Truncated(Exception):
    """The reply hit the output-token limit (finish_reason == "length")."""


class ExtractionFailed(Exception):
    """The reply was still unusable after one repair retry."""


def parse_json(text: str):
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            return json.loads(t[i:j + 1])
        raise


def call_json(client, messages: list[dict], prompt_version: str, key: str, stats: RunStats) -> list:
    msgs = list(messages)
    for attempt in (1, 2):
        c = client.complete(msgs, prompt_version)
        if c.finish_reason == "length":
            stats.truncations += 1
            raise Truncated()
        try:
            obj = parse_json(c.text)
            items = obj.get(key) if isinstance(obj, dict) else None
            if not isinstance(items, list):
                raise ValueError(f'expected a JSON object with a "{key}" list')
            return items
        except ValueError as e:
            if attempt == 2:
                raise ExtractionFailed(str(e)) from e
            stats.repairs += 1
            msgs = msgs + [{"role": "assistant", "content": c.text[:4000]},
                           {"role": "user", "content": f"Your reply was not valid: {e}. Reply again with only "
                                                       f'the JSON object {{"{key}": [...]}} and nothing else.'}]
    raise AssertionError("unreachable")
