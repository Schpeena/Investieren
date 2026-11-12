"""Zkratka: CACHE_DIR=/tmp/democache NO_GH=1 python tests/demo_setup.py  (logika je v pipeline/demo_setup.py)"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.demo_setup import main
main()
