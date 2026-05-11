"""Opt-in live-API smoke tests for R1A no-key providers (v1.11.s59).

These tests are SKIPPED by default. Enable with:

    $env:FAW_RUN_LIVE_TESTS = "1"
    python -m pytest Tests/python/test_r1a_live_smoke.py -v

Why no-key only here: key-required providers need env vars set, which
adds a second axis of "did this fail because of network or because of
missing key". No-key tests are the cleanest live-smoke gate.

These cover Met Museum, Wikimedia, Archive.org, Scryfall, and Iconify.
Each runs one minimal search to verify the API is up + response shape
hasn't drifted.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# Hack to import LIVE_TESTS_SKIP from conftest.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import LIVE_TESTS_SKIP  # noqa: E402


@LIVE_TESTS_SKIP
class MetMuseumLiveTests(unittest.TestCase):
    def test_search_returns_object_ids(self) -> None:
        from assetboy.execution.met_museum_runner import search_met_object_ids
        ids = search_met_object_ids("vermeer", has_images=True)
        self.assertIsInstance(ids, list)
        # Vermeer is a famous artist with multiple Met PD works; should be > 0.
        self.assertGreater(len(ids), 0)

    def test_fetch_object_metadata_shape(self) -> None:
        from assetboy.execution.met_museum_runner import (
            search_met_object_ids, fetch_met_object,
        )
        ids = search_met_object_ids("vermeer", has_images=True)
        self.assertGreater(len(ids), 0)
        obj = fetch_met_object(ids[0])
        # Verify expected keys are present (contract not drifted).
        for key in ("objectID", "isPublicDomain", "title"):
            self.assertIn(key, obj)


@LIVE_TESTS_SKIP
class WikimediaLiveTests(unittest.TestCase):
    def test_search_namespace_6_returns_titles(self) -> None:
        from assetboy.execution.wikimedia_runner import search_wikimedia_files
        titles = search_wikimedia_files("stone wall", limit=3)
        self.assertIsInstance(titles, list)
        self.assertGreater(len(titles), 0)
        # All titles should start with "File:" since we restricted ns=6.
        for t in titles:
            self.assertTrue(t.startswith("File:"), f"unexpected title shape: {t!r}")


@LIVE_TESTS_SKIP
class ArchiveOrgLiveTests(unittest.TestCase):
    def test_search_returns_docs(self) -> None:
        from assetboy.execution.archive_org_runner import search_archive_items
        docs = search_archive_items("subject:roman", rows=3)
        self.assertIsInstance(docs, list)
        self.assertGreater(len(docs), 0)


@LIVE_TESTS_SKIP
class ScryfallLiveTests(unittest.TestCase):
    def test_search_returns_cards(self) -> None:
        from assetboy.execution.scryfall_runner import search_scryfall_cards
        cards = search_scryfall_cards("type:dragon")
        self.assertIsInstance(cards, list)
        self.assertGreater(len(cards), 0)
        # Verify card shape — id and name should be present.
        for k in ("id", "name"):
            self.assertIn(k, cards[0])


@LIVE_TESTS_SKIP
class IconifyLiveTests(unittest.TestCase):
    def test_search_returns_icon_ids(self) -> None:
        from assetboy.execution.iconify_runner import search_iconify_icons
        icons = search_iconify_icons("sword", limit=5)
        self.assertIsInstance(icons, list)
        self.assertGreater(len(icons), 0)
        # Icon IDs are 'prefix:name' shape.
        for icon_id in icons:
            self.assertIn(":", icon_id)


if __name__ == "__main__":
    unittest.main()
