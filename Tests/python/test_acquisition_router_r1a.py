"""Tests for v1.11.s41 R1A providers wired into acquisition_router."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class _BaseRouterR1aTest(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.workflows import acquisition_router
        self.mod = acquisition_router

    def _recipe(self) -> dict:
        return {"recipe": {"id": "r", "game": "test"}}

    def _patch_workspace_dir(self, tmp: Path):
        """Mock the workspace resolver so we don't need an FAW workspace."""
        return patch.object(
            self.mod,
            "_resolve_source_staging_dir",
            return_value=tmp,
        )


class MetMuseumRouterTests(_BaseRouterR1aTest):
    def test_met_museum_routes_to_driver(self) -> None:
        from assetboy.execution.met_museum_runner import MetMuseumResult
        pack = {
            "id": "PACK_MET",
            "provider": "met_museum",
            "acquisition_method": "direct_url",
            "search_terms": ["roman fresco"],
            "count": 3,
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fake = MetMuseumResult(
                pack_id="PACK_MET", query="roman fresco", output_dir=out,
                objects_matched=5, objects_downloaded=2,
                objects_skipped_non_pd=2, ok=True,
            )
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.met_museum_runner.run_met_museum_batch",
                    return_value=fake,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="PACK_MET", provider="met_museum",
                        dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "met_museum")
        self.assertIn("matched=5", result.notes)
        self.assertIn("downloaded=2", result.notes)

    def test_met_museum_alias_hyphenated(self) -> None:
        from assetboy.execution.met_museum_runner import MetMuseumResult
        pack = {
            "id": "M", "provider": "met-museum",
            "acquisition_method": "direct_url",
            "search_terms": ["roman"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fake = MetMuseumResult(
                pack_id="M", query="roman", output_dir=out,
                objects_matched=0, ok=True, error="no_matches",
            )
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.met_museum_runner.run_met_museum_batch",
                    return_value=fake,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="M", provider="met-museum",
                        dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "met_museum")


class WikimediaRouterTests(_BaseRouterR1aTest):
    def test_wikimedia_routes_to_driver(self) -> None:
        from assetboy.execution.wikimedia_runner import WikimediaResult
        pack = {
            "id": "WM", "provider": "wikimedia",
            "acquisition_method": "direct_url",
            "search_terms": ["stone wall"],
            "count": 5,
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            fake = WikimediaResult(
                pack_id="WM", query="stone wall", output_dir=out,
                files_matched=10, files_downloaded=4,
                files_skipped_restricted=6, ok=True,
            )
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.wikimedia_runner.run_wikimedia_batch",
                    return_value=fake,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="WM", provider="wikimedia",
                        dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "wikimedia")
        self.assertIn("matched=10", result.notes)


class ArchiveOrgRouterTests(_BaseRouterR1aTest):
    def test_archive_org_routes_with_mediatype(self) -> None:
        from assetboy.execution.archive_org_runner import ArchiveOrgResult
        pack = {
            "id": "AO", "provider": "archive_org",
            "acquisition_method": "direct_url",
            "search_terms": ["subject:roman"],
            "archive_mediatype": "image",
            "count": 4,
        }
        captured: dict = {}

        def capture(*a: object, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return ArchiveOrgResult(
                pack_id="AO", query="subject:roman",
                output_dir=Path("."),
                items_matched=3, items_downloaded=3, ok=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.archive_org_runner.run_archive_org_batch",
                    side_effect=capture,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="AO", provider="archive_org",
                        dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(captured["mediatype"], "image")


class ScryfallRouterTests(_BaseRouterR1aTest):
    def test_scryfall_routes_with_variant(self) -> None:
        from assetboy.execution.scryfall_runner import ScryfallResult
        pack = {
            "id": "SF", "provider": "scryfall",
            "acquisition_method": "direct_url",
            "search_terms": ["type:dragon"],
            "scryfall_variant": "png",
            "count": 3,
        }
        captured: dict = {}

        def capture(*a: object, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return ScryfallResult(
                pack_id="SF", query="type:dragon",
                output_dir=Path("."), variant="png",
                cards_matched=3, cards_downloaded=3, ok=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.scryfall_runner.run_scryfall_batch",
                    side_effect=capture,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="SF", provider="scryfall",
                        dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(captured["variant"], "png")


class IconifyRouterTests(_BaseRouterR1aTest):
    def test_iconify_routes_with_width_and_color(self) -> None:
        from assetboy.execution.iconify_runner import IconifyResult
        pack = {
            "id": "IC", "provider": "iconify",
            "acquisition_method": "direct_url",
            "search_terms": ["sword"],
            "iconify_width": 128,
            "iconify_color": "#FF6600",
            "count": 10,
        }
        captured: dict = {}

        def capture(*a: object, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return IconifyResult(
                pack_id="IC", query="sword", output_dir=Path("."),
                icons_matched=12, icons_downloaded=10, ok=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.iconify_runner.run_iconify_batch",
                    side_effect=capture,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="IC", provider="iconify",
                        dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(captured["width"], 128)
        self.assertEqual(captured["color"], "#FF6600")


class PackHelperTests(_BaseRouterR1aTest):
    def test_pack_search_query_from_search_terms(self) -> None:
        pack = {"search_terms": ["first term", "second"]}
        self.assertEqual(self.mod._pack_search_query(pack), "first term")

    def test_pack_search_query_from_assets_asset_id(self) -> None:
        pack = {"assets": [{"asset_id": "stone_wall_01"}]}
        self.assertEqual(self.mod._pack_search_query(pack), "stone_wall_01")

    def test_pack_search_query_from_assets_string(self) -> None:
        pack = {"assets": ["bare_string_asset"]}
        self.assertEqual(self.mod._pack_search_query(pack), "bare_string_asset")

    def test_pack_search_query_falls_back_to_pack_id(self) -> None:
        pack = {"id": "PACK_NO_HINTS"}
        # Underscores become spaces.
        self.assertEqual(self.mod._pack_search_query(pack), "PACK NO HINTS")

    def test_pack_count_explicit(self) -> None:
        self.assertEqual(self.mod._pack_count({"count": 7}), 7)

    def test_pack_count_from_assets(self) -> None:
        self.assertEqual(
            self.mod._pack_count({"assets": [1, 2, 3]}),
            3,
        )

    def test_pack_count_default(self) -> None:
        self.assertEqual(self.mod._pack_count({}, default=12), 12)


class PexelsRouterTests(_BaseRouterR1aTest):
    def test_pexels_photos_routes_to_driver(self) -> None:
        from assetboy.execution.pexels_runner import PexelsResult
        pack = {
            "id": "PX", "provider": "pexels",
            "acquisition_method": "direct_url",
            "search_terms": ["fire"], "count": 3,
            "pexels_variant": "large",
        }
        captured: dict = {}

        def capture(*a: object, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return PexelsResult(
                pack_id="PX", query="fire", output_dir=Path("."),
                kind="photos", items_matched=3, items_downloaded=3, ok=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.pexels_runner.run_pexels_photo_batch",
                    side_effect=capture,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="PX", provider="pexels", dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(captured["variant"], "large")

    def test_pexels_videos_routes_with_max_height(self) -> None:
        from assetboy.execution.pexels_runner import PexelsResult
        pack = {
            "id": "PV", "provider": "pexels_videos",
            "acquisition_method": "direct_url",
            "search_terms": ["fire"],
            "count": 2, "pexels_max_height": 720,
        }
        captured: dict = {}

        def capture(*a: object, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return PexelsResult(
                pack_id="PV", query="fire", output_dir=Path("."),
                kind="videos", items_matched=2, items_downloaded=2, ok=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.pexels_runner.run_pexels_video_batch",
                    side_effect=capture,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="PV", provider="pexels_videos", dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(captured["max_height"], 720)


class PixabayRouterTests(_BaseRouterR1aTest):
    def test_pixabay_photos_routes_with_image_type(self) -> None:
        from assetboy.execution.pixabay_runner import PixabayResult
        pack = {
            "id": "PB", "provider": "pixabay",
            "acquisition_method": "direct_url",
            "search_terms": ["leaf"],
            "count": 5,
            "pixabay_image_type": "vector",
        }
        captured: dict = {}

        def capture(*a: object, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return PixabayResult(
                pack_id="PB", query="leaf", output_dir=Path("."),
                kind="photos", items_matched=5, items_downloaded=5, ok=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.pixabay_runner.run_pixabay_photo_batch",
                    side_effect=capture,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="PB", provider="pixabay", dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(captured["image_type"], "vector")


class UnsplashRouterTests(_BaseRouterR1aTest):
    def test_unsplash_routes_with_orientation(self) -> None:
        from assetboy.execution.unsplash_runner import UnsplashResult
        pack = {
            "id": "US", "provider": "unsplash",
            "acquisition_method": "direct_url",
            "search_terms": ["mountain"],
            "count": 3,
            "unsplash_orientation": "landscape",
        }
        captured: dict = {}

        def capture(*a: object, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return UnsplashResult(
                pack_id="US", query="mountain", output_dir=Path("."),
                photos_matched=3, photos_downloaded=3, ok=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.unsplash_runner.run_unsplash_photo_batch",
                    side_effect=capture,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="US", provider="unsplash", dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(captured["orientation"], "landscape")


class RawgRouterTests(_BaseRouterR1aTest):
    def test_rawg_routes_with_genres_and_screenshots(self) -> None:
        from assetboy.execution.rawg_runner import RawgResult
        pack = {
            "id": "RG", "provider": "rawg",
            "acquisition_method": "direct_url",
            "search_terms": ["roguelike"],
            "count": 4,
            "rawg_genres": "strategy,role-playing-games-rpg",
            "rawg_max_screenshots": 5,
        }
        captured: dict = {}

        def capture(*a: object, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return RawgResult(
                pack_id="RG", query="roguelike", output_dir=Path("."),
                games_matched=4, games_downloaded=4, screenshots_downloaded=20, ok=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.rawg_runner.run_rawg_games_batch",
                    side_effect=capture,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="RG", provider="rawg", dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(captured["genres"], "strategy,role-playing-games-rpg")
        self.assertEqual(captured["max_screenshots_per_game"], 5)
        self.assertIn("REFERENCE-ONLY", result.notes)


class JamendoRouterTests(_BaseRouterR1aTest):
    def test_jamendo_routes_with_allow_restrictive(self) -> None:
        from assetboy.execution.jamendo_runner import JamendoResult
        pack = {
            "id": "JM", "provider": "jamendo",
            "acquisition_method": "direct_url",
            "search_terms": ["ambient"],
            "count": 2,
            "jamendo_allow_restrictive": True,
        }
        captured: dict = {}

        def capture(*a: object, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return JamendoResult(
                pack_id="JM", query="ambient", output_dir=Path("."),
                tracks_matched=2, tracks_downloaded=2, ok=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.jamendo_runner.run_jamendo_tracks_batch",
                    side_effect=capture,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="JM", provider="jamendo", dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertTrue(captured["allow_restrictive"])


class INaturalistRouterTests(_BaseRouterR1aTest):
    def test_inaturalist_routes_with_allow_restrictive(self) -> None:
        from assetboy.execution.inaturalist_runner import INaturalistResult
        pack = {
            "id": "IN", "provider": "inaturalist",
            "acquisition_method": "direct_url",
            "search_terms": ["oak tree"],
            "count": 3,
            "inaturalist_allow_restrictive": True,
        }
        captured: dict = {}

        def capture(*a: object, **kwargs: object):  # type: ignore[no-untyped-def]
            captured.update(kwargs)
            return INaturalistResult(
                pack_id="IN", query="oak tree", output_dir=Path("."),
                observations_matched=3, observations_with_photo=3,
                photos_downloaded=3, ok=True,
            )

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.inaturalist_runner.run_inaturalist_batch",
                    side_effect=capture,
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="IN", provider="inaturalist", dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertTrue(captured["allow_restrictive"])

    def test_inaturalist_alias_inat(self) -> None:
        from assetboy.execution.inaturalist_runner import INaturalistResult
        pack = {
            "id": "I", "provider": "inat",
            "acquisition_method": "direct_url",
            "search_terms": ["wolf"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                with patch(
                    "assetboy.execution.inaturalist_runner.run_inaturalist_batch",
                    return_value=INaturalistResult(
                        pack_id="I", query="wolf", output_dir=out, ok=True,
                    ),
                ):
                    result = self.mod._acquire_direct_url(
                        pack=pack, recipe=self._recipe(),
                        pack_id="I", provider="inat", dry_run=False,
                    )
        self.assertTrue(result.ok)
        self.assertEqual(result.provider, "inaturalist")


class UnsupportedProviderTests(_BaseRouterR1aTest):
    def test_unknown_provider_lists_all_supported_in_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self._patch_workspace_dir(out):
                result = self.mod._acquire_direct_url(
                    pack={"id": "X", "provider": "mystery"},
                    recipe=self._recipe(),
                    pack_id="X", provider="mystery", dry_run=False,
                )
        self.assertFalse(result.ok)
        for p in (
            "polyhaven", "met_museum", "wikimedia", "iconify",
            "pexels", "pixabay", "unsplash", "rawg", "jamendo",
            "inaturalist",
        ):
            self.assertIn(p, result.error)


if __name__ == "__main__":
    unittest.main()
