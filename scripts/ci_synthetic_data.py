"""Write the synthetic test corpus (tests/conftest.py fixtures) as a LISA data dir, for CI and container smoke tests.

  python scripts/ci_synthetic_data.py /tmp/lisa_data

The real case package is never used outside the developer machine; this corpus has the same layout and a valid
manifest (real sha256 of the synthetic files), so the production checks run unchanged.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.conftest import IMM, LIT, REPORT, write_jsonl  # noqa: E402


def main(dest: str) -> None:
    d = Path(dest)
    write_jsonl(d / "pack_immigration" / "records.jsonl", IMM)
    write_jsonl(d / "pack_litigation" / "records.jsonl", LIT)
    files = []
    for rel in ("pack_immigration/records.jsonl", "pack_litigation/records.jsonl"):
        b = (d / rel).read_bytes()
        files.append({"path": rel, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})
    (d / "manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    (d / "selection_report.json").write_text(json.dumps(REPORT), encoding="utf-8")
    print(f"synthetic corpus -> {d}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ci_data")
