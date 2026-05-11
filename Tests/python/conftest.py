"""Pytest config: put assetboy package on sys.path for in-tree tests.

Layout:
    flax-asset-worker/
      Python/assetboy/...   <-- package we want importable
      Tests/python/         <-- this file lives here

We resolve Python/ as Tests/python/../../Python and prepend to sys.path so
``from assetboy import ...`` works without a pip install.

(The rescued conftest from game-factory pointed at a sibling 'src/' dir that
doesn't exist in this layout — replaced 2026-05-10 Path B Day 1.)

v1.11.s59: also exposes `RUN_LIVE_TESTS` flag (env var `FAW_RUN_LIVE_TESTS`)
for opt-in live-API tests. Default OFF.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Tests/python/conftest.py -> parents[2] is the repo root (flax-asset-worker/)
REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = REPO_ROOT / "Python"

if PYTHON_DIR.is_dir() and str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))


# v1.11.s59 — live-test gate.
# Tests that hit real external APIs should be marked with @LIVE_TESTS_SKIP
# (a unittest.skipUnless decorator). They run only when FAW_RUN_LIVE_TESTS=1.
#
# Why opt-in rather than opt-out:
#   - CI flakiness from network blips becomes silent (not red).
#   - External APIs have rate limits we shouldn't burn during routine pytest.
#   - Tests-as-documentation: the live-test decorator says "this needs network".
#
# Usage in a test file:
#   from conftest import LIVE_TESTS_ENABLED, LIVE_TESTS_SKIP
#
#   class MyLiveTest(unittest.TestCase):
#       @LIVE_TESTS_SKIP
#       def test_real_met_museum_search(self):
#           from assetboy.execution.met_museum_runner import search_met_object_ids
#           ids = search_met_object_ids("vermeer", has_images=True)
#           self.assertGreater(len(ids), 0)
import unittest

LIVE_TESTS_ENABLED: bool = bool(os.environ.get("FAW_RUN_LIVE_TESTS", "").strip())

LIVE_TESTS_SKIP = unittest.skipUnless(
    LIVE_TESTS_ENABLED,
    "live-network tests disabled (set FAW_RUN_LIVE_TESTS=1 to enable)",
)
