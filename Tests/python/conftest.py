"""Pytest config: put assetboy package on sys.path for in-tree tests.

Layout:
    flax-asset-worker/
      Python/assetboy/...   <-- package we want importable
      Tests/python/         <-- this file lives here

We resolve Python/ as Tests/python/../../Python and prepend to sys.path so
``from assetboy import ...`` works without a pip install.

(The rescued conftest from game-factory pointed at a sibling 'src/' dir that
doesn't exist in this layout — replaced 2026-05-10 Path B Day 1.)
"""

from __future__ import annotations

import sys
from pathlib import Path

# Tests/python/conftest.py -> parents[2] is the repo root (flax-asset-worker/)
REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = REPO_ROOT / "Python"

if PYTHON_DIR.is_dir() and str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))
