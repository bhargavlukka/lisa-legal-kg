"""Read dataset JSONL files into Records, after verifying SHA-256 against manifest.json."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from lisa.common.config import DatasetConfig

REQUIRED = ("id", "title")  # citation may be absent (slip opinions not yet in U.S. Reports)


class ChecksumError(RuntimeError):
    pass


@dataclass
class Record:
    id: str
    domain: str
    title: str
    citation: str | None
    props: dict
    pages: list[dict]
    text: str
    citations: list[str]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_manifest(data_dir: Path, rel_paths: list[str]) -> None:
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = {f["path"]: f["sha256"] for f in manifest["files"]}
    for rel in rel_paths:
        if rel not in expected:
            raise ChecksumError(f"{rel}: not listed in manifest.json")
        actual = _sha256(data_dir / rel)
        if actual != expected[rel]:
            raise ChecksumError(f"{rel}: sha256 mismatch (manifest {expected[rel][:12]}, file {actual[:12]})")


def load_records(data_dir: Path, ds: DatasetConfig) -> tuple[list[Record], list[dict]]:
    records: list[Record] = []
    quarantine: list[dict] = []
    for src in ds.sources:
        with open(data_dir / src.path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as e:
                    quarantine.append({"source": src.path, "line": lineno, "reason": f"bad json: {e}"})
                    continue
                missing = [k for k in REQUIRED if not raw.get(src.fields[k])]
                pages = raw.get("pages") or []
                if not pages:
                    missing.append("pages")
                if missing:
                    quarantine.append({"source": src.path, "line": lineno, "id": raw.get(src.fields["id"]),
                                       "reason": f"missing: {missing}"})
                    continue
                props = {k: raw.get(v) for k, v in src.fields.items()}
                props.update({k: raw.get(k) for k in src.extra})
                pages = [{"page": p["page"], "text": p["text"]} for p in pages]
                records.append(Record(
                    id=raw[src.fields["id"]],
                    domain=src.domain,
                    title=raw[src.fields["title"]],
                    citation=raw.get(src.fields["citation"]) or None,
                    props=props,
                    pages=pages,
                    text=raw.get("text") or "\n".join(p["text"] for p in pages),
                    citations=list(raw.get("citations_detected") or []),
                ))
    return records, quarantine
