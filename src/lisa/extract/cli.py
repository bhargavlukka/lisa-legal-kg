"""LLM extraction tier for one dataset config. Rerunning resumes from the cache."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from lisa.common.config import load_eval_settings, load_llm_settings, load_settings
from lisa.extract.pipeline import run
from lisa.graph.loader import ChecksumError
from lisa.llm.client import LLMError


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, help="gold_eval | immigration | litigation | all")
    ap.add_argument("--max-requests", type=int, help="override llm.max_requests_per_run")
    ap.add_argument("--offline", action="store_true", help="serve only from out/llm_cache; never call the API")
    ap.add_argument("--units", help="comma-separated unit ids to run (default: all)")
    a = ap.parse_args(argv)
    try:
        settings, llm, ev = load_settings(), load_llm_settings(), load_eval_settings()
    except (RuntimeError, KeyError) as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    try:
        r = run(a.dataset, settings=settings, llm=llm, ev=ev, offline=a.offline, max_requests=a.max_requests,
                only_units=set(a.units.split(",")) if a.units else None)
    except (FileNotFoundError, KeyError) as e:
        print(f"config error: cannot load dataset {a.dataset!r}: {e}", file=sys.stderr)
        return 2
    except ChecksumError as e:
        print(f"checksum error: {e}", file=sys.stderr)
        return 2
    except LLMError as e:
        print(f"llm error: {e}", file=sys.stderr)
        return 2
    out = json.loads(r.output.read_text(encoding="utf-8"))
    m = json.loads(r.manifest.read_text(encoding="utf-8"))
    print(f"{a.dataset}: {r.status}; units {m['units_done']}/{m['units_total']} "
          f"({dict(Counter(u['status'] for u in out['units']))}); pending {len(out['pending'])}")
    print(f"requests {m['requests']} (cache hits {m['cache_hits']}, 429s {m['rate_limited']}), "
          f"tokens in/out {m['input_tokens']}/{m['output_tokens']}, failed {len(m['failed'])}, "
          f"schema rejects {len(m['schema_rejects'])}")
    print(f"wrote {r.output}, {r.graph}, {r.manifest}")
    if r.status == "budget_exhausted":
        print("budget reached - rerun the same command to resume from the cache", file=sys.stderr)
        return 3
    return 0
