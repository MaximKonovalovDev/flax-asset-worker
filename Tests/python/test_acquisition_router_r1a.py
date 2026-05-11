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
        for p in ("polyhaven", "met_museum", "wikimedia", "iconify"):
            self.assertIn(p, result.error)


if __name__ == "__main__":
    unittest.main()
