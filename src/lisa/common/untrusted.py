"""Untrusted-text handling: corpus text and external API text reach the model only fenced and labelled as data.

The fence tells the model the span is quoted material, never instructions; injection-like phrases are flagged
(not removed - the verifier must still be able to match quotes against the stored text byte-for-byte).
"""
from __future__ import annotations

import re

INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts?)|disregard (the )?(system|previous)|"
    r"you are now|new instructions?:|system prompt|<\s*/?\s*(system|assistant|tool)\s*>|"
    r"call the \w+ tool|exfiltrat|send (it|this|the \w+) to http|BEGIN (SYSTEM|ADMIN)", re.I)
FENCE_OPEN, FENCE_CLOSE = "<<<UNTRUSTED_CASE_TEXT", "UNTRUSTED_CASE_TEXT>>>"


def flags(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in INJECTION.finditer(text or "")})


def fence(text: str, source: str) -> dict:
    """Wrap untrusted text; any fence markers inside the text are defanged so it cannot close the fence early."""
    body = (text or "").replace("<<<", "‹‹‹").replace(">>>", "›››")
    out = {"text": f"{FENCE_OPEN} source={source}\n{body}\n{FENCE_CLOSE}", "untrusted": True}
    if f := flags(text):
        out["injection_flags"] = f
    return out
