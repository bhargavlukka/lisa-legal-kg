"""Prompt texts (versioned) and system-message assembly."""
from __future__ import annotations

import re
from pathlib import Path

from lisa.extract.schema import SIGNATURES

PROMPT_DIR = Path(__file__).with_name("prompts")


def load_prompt(name: str) -> tuple[str, str]:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    first, _, body = text.partition("\n")
    m = re.fullmatch(r"PROMPT_VERSION:\s*(\S+)", first.strip())
    if not m:
        raise ValueError(f"{name}.md: first line must be 'PROMPT_VERSION: <id>'")
    return m[1], body.strip()


def build_system(name: str, fewshot: str) -> tuple[str, str]:
    version, body = load_prompt(name)
    sigs = "\n".join(f"- {s} -{r}-> {t}" for s, r, t in sorted(SIGNATURES))
    examples = f"## Examples\n{fewshot}" if fewshot else ""
    return version, body.replace("{{SIGNATURES}}", sigs).replace("{{FEWSHOT}}", examples).strip()
