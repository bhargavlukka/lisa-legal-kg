"""Thin wrapper: py -3 scripts/eval_extraction.py [--threshold 0.3]"""
import sys

from lisa.eval.cli import main

if __name__ == "__main__":
    sys.exit(main())
