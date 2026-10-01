"""Thin wrapper: py -3 scripts/build_graph.py --dataset all --check"""
import sys

from lisa.graph.cli import main

if __name__ == "__main__":
    sys.exit(main())
