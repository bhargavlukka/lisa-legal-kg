"""Verify a local copy of the LISA package against the checksums committed in data_manifest/manifest.json,
and check that the packs contain exactly the 60 cases selection_report.json selected."""
from __future__ import annotations

import json
import sys

from lisa.common.config import REPO_ROOT, load_settings
from lisa.graph.loader import _sha256


def main() -> int:
    data = load_settings().data_dir
    committed = json.loads((REPO_ROOT / "data_manifest" / "manifest.json").read_text(encoding="utf-8"))
    bad = []
    for f in committed["files"]:
        p = data / f["path"]
        if not p.exists():
            bad.append(f"missing: {f['path']}")
        elif _sha256(p) != f["sha256"]:
            bad.append(f"sha256 mismatch: {f['path']}")
    report = json.loads((data / "selection_report.json").read_text(encoding="utf-8"))
    selected = set(report["per_case_reasons"])
    ids = set()
    for rel in ("pack_immigration/records.jsonl", "pack_litigation/records.jsonl"):
        with open(data / rel, encoding="utf-8") as fh:
            ids |= {json.loads(line)["id"] for line in fh if line.strip()}
    if ids != selected:
        bad.append(f"pack ids != selection_report: extra {sorted(ids - selected)[:5]}, missing {sorted(selected - ids)[:5]}")
    for line in bad:
        print("FAIL", line, file=sys.stderr)
    print(f"{len(committed['files'])} files checked, {len(ids)} pack cases vs {len(selected)} selected: "
          f"{'OK' if not bad else 'FAILED'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
