"""Thin wrapper: py -3 scripts/extract_llm.py --dataset gold_eval [--max-requests N] [--offline] [--units ID,...]"""
import sys

from lisa.extract.cli import main

if __name__ == "__main__":
    sys.exit(main())
