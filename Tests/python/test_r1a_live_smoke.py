"""Opt-in live-API smoke tests for R1A providers (v1.11.s59, v1.13.s79).

These tests are SKIPPED by default. Enable with:

    $env:FAW_RUN_LIVE_TESTS = "1"
    python -m pytest Tests/python/test_r1a_live_smoke.py -v

No-key providers (always testable once FAW_RUN_LIVE_TESTS=1):
  Met Museum, Wikimedia Commons, Archive.org, Scryfall, Iconify

Keyed providers (v1.13.s79): additionally require their env var to be set.
  Pexels      requires PEXELS_API_KEY
  Pixabay     requires PIXABAY_API_KEY
  Unsplash    requires UNSPLASH_ACCESS_KEY
  RAWG        requires RAWG_API_KEY
  Jamendo     requires JAMENDO_CLIENT_ID
A keyed test SKIPS individually when its env var is missing, even with
FAW_RUN_LIVE_TESTS=1.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Hack to import LIVE_TESTS_SKIP from conftest.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import LIVE_TESTS_SKIP  # noqa: E402


def _require_env(var_name: str):
    """Compose LIVE_TESTS_SKIP with an additional env-var gate."""
    return unittest.skipUnless(
        os.environ.get(var_name, "").strip(),
        f"keyed live test needs {var_name} set",
    )


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


# --------------------------------------------------------------------------- #
# v1.13.s79 — keyed providers (need env var + FAW_RUN_LIVE_TESTS)
# --------------------------------------------------------------------------- #

@LIVE_TESTS_SKIP
@_require_env("PEXELS_API_KEY")
class PexelsLiveTests(unittest.TestCase):
    def test_search_photos_returns_results(self) -> None:
        from assetboy.execution.pexels_runner import search_pexels_photos, get_api_key
        key = get_api_key()
        self.assertIsNotNone(key)
        photos = search_pexels_photos("fire", api_key=key, per_page=3)
        self.assertIsInstance(photos, list)
        self.assertGreater(len(photos), 0)
        # Sanity: each photo has src.large.
        for p in photos:
            self.assertIn("src", p)


@LIVE_TESTS_SKIP
@_require_env("PIXABAY_API_KEY")
class PixabayLiveTests(unittest.TestCase):
    def test_search_photos_returns_hits(self) -> None:
        from assetboy.execution.pixabay_runner import search_pixabay_photos, get_api_key
        key = get_api_key()
        self.assertIsNotNone(key)
        hits = search_pixabay_photos("stone wall", api_key=key, per_page=3)
        self.assertIsInstance(hits, list)
        self.assertGreater(len(hits), 0)


@LIVE_TESTS_SKIP
@_require_env("UNSPLASH_ACCESS_KEY")
class UnsplashLiveTests(unittest.TestCase):
    def test_search_photos_returns_results(self) -> None:
        from assetboy.execution.unsplash_runner import search_unsplash_photos, get_access_key
        key = get_access_key()
        self.assertIsNotNone(key)
        photos = search_unsplash_photos("mountain", access_key=key, per_page=3)
        self.assertIsInstance(photos, list)
        self.assertGreater(len(photos), 0)


@LIVE_TESTS_SKIP
@_require_env("RAWG_API_KEY")
class RawgLiveTests(unittest.TestCase):
    def test_search_games_returns_results(self) -> None:
        from assetboy.execution.rawg_runner import search_rawg_games, get_api_key
        key = get_api_key()
        self.assertIsNotNone(key)
        games = search_rawg_games("roguelike", api_key=key, page_size=3)
        self.assertIsInstance(games, list)
        self.assertGreater(len(games), 0)


@LIVE_TESTS_SKIP
@_require_env("JAMENDO_CLIENT_ID")
class JamendoLiveTests(unittest.TestCase):
    def test_search_tracks_returns_results(self) -> None:
        from assetboy.execution.jamendo_runner import search_jamendo_tracks, get_client_id
        cid = get_client_id()
        self.assertIsNotNone(cid)
        tracks = search_jamendo_tracks("ambient cinematic", client_id=cid, limit=3)
        self.assertIsInstance(tracks, list)
        # Note: Jamendo search may return [] for very obscure queries; just
        # verify type. Most "ambient cinematic" queries return something.


if __name__ == "__main__":
    unittest.main()
