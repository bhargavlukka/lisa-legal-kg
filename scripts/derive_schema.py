"""Regenerate src/lisa/extract/schema_signatures.json from LISA_DATA_DIR/gold_standard."""
import json
import sys

from lisa.common.config import load_settings
from lisa.extract.schema import SIGNATURES_FILE, derive_signatures

if __name__ == "__main__":
    sigs = derive_signatures(load_settings().data_dir / "gold_standard")
    SIGNATURES_FILE.write_text(json.dumps(sigs, indent=1) + "\n", encoding="utf-8")
    print(f"{len(sigs)} signatures -> {SIGNATURES_FILE}")
    sys.exit(0)
