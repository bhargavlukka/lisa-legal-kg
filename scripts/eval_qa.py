"""Thin wrapper: py scripts/eval_qa.py --system kg|rag [--ids q01,q02] | --report-only"""
import sys

from lisa.eval.qa_cli import main

if __name__ == "__main__":
    sys.exit(main())
