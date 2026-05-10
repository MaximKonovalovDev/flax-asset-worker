from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from assetboy.providers.fab_hybrid import (
    FabHybridDownloader,
    build_online_fab_library_map,
    render_online_fab_library_map_markdown,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200
        self.content = json.dumps(payload).encode("utf-8")

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class FabHybridDownloaderTests(unittest.TestCase):
    def test_pick_download_file_prefers_fbx_over_blender_project(self) -> None:
        chosen_format, chosen_file = FabHybridDownloader._pick_download_file(
            [
                {
                    "assetFormatType": {"code": "blender"},
                    "files": [{"uid": "blend-1", "fileSize": 5000}],
                },
                {
                    "assetFormatType": {"code": "fbx"},
                    "files": [{"uid": "fbx-1", "fileSize": 1000}],
                },
            ]
        )

        self.assertEqual(chosen_format, "fbx")
        self.assertEqual(chosen_file["uid"], "fbx-1")

    def test_build_auth_state_preserves_storage_entries(self) -> None:
        state = FabHybridDownloader._build_auth_state(
            cookies_dict=[{"name": "fab_csrftoken", "value": "abc"}],
            local_storage_json='{"accessToken":"token-123"}',
            session_storage_json='{"foo":"bar"}',
        )

        self.assertEqual(state["cookies"][0]["name"], "fab_csrftoken")
        origin = state["origins"][0]
        self.assertEqual(origin["origin"], "https://www.fab.com")
        self.assertEqual(origin["localStorage"][0]["name"], "accessToken")
        self.assertEqual(origin["localStorage"][0]["value"], "token-123")
        self.assertEqual(origin["sessionStorage"][0]["name"], "foo")

    def test_auth_lock_blocks_concurrent_runs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            downloader = FabHybridDownloader(
                auth_state_path=str(root / "fab_auth_state.json"),
                browser_profile_dir=str(root / "fab_browser_profile"),
                debug=False,
            )

            with downloader.auth_lock():
                with self.assertRaises(RuntimeError):
                    with downloader.auth_lock():
                        pass

    def test_auth_status_reports_profile_and_authenticated_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth_state_path = root / "fab_auth_state.json"
            profile_cookie_db = root / "fab_browser_profile" / "Default" / "Network" / "Cookies"
            profile_cookie_db.parent.mkdir(parents=True, exist_ok=True)
            profile_cookie_db.write_text("cookie-db", encoding="utf-8")
            auth_state_path.write_text(json.dumps({"cookies": [], "origins": []}), encoding="utf-8")

            downloader = FabHybridDownloader(
                auth_state_path=str(auth_state_path),
                browser_profile_dir=str(root / "fab_browser_profile"),
                debug=False,
            )

            with patch.object(downloader, "create_cffi_session", return_value=object()):
                with patch.object(downloader, "is_authenticated", return_value=True):
                    status = downloader.auth_status()

            self.assertTrue(status["auth_state_exists"])
            self.assertTrue(status["browser_profile_has_state"])
            self.assertTrue(status["authenticated"])
            self.assertFalse(status["auth_state_stale"])
            self.assertEqual(status["repair_command"], "python scripts/cli.py asset-factory fab-auth --reuse-profile")
            self.assertEqual(status["error"], "")

    def test_auth_status_marks_stale_saved_state_for_repair(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth_state_path = root / "fab_auth_state.json"
            auth_state_path.write_text(
                json.dumps(
                    {
                        "authenticated": True,
                        "saved_at": "2026-01-01T00:00:00+00:00",
                        "cookies": [],
                        "origins": [],
                    }
                ),
                encoding="utf-8",
            )

            downloader = FabHybridDownloader(
                auth_state_path=str(auth_state_path),
                browser_profile_dir=str(root / "fab_browser_profile"),
                debug=False,
            )
            status = downloader.auth_status()

        self.assertFalse(status["authenticated"])
        self.assertTrue(status["auth_state_stale"])
        self.assertTrue(status["repair_recommended"])
        self.assertEqual(status["repair_reason"], "auth_state_stale")

    def test_interactive_auth_uses_shared_profile_without_ephemeral_fallback(self) -> None:
        downloader = FabHybridDownloader(debug=False)
        fake_browser = SimpleNamespace(stop=lambda: None)

        async def _run() -> None:
            with patch.object(downloader, "_start_browser", return_value=fake_browser) as start_browser:
                with patch.object(downloader, "_open_fab_page", return_value=None):
                    with patch.object(downloader, "_save_browser_state", return_value={"cookies": [], "origins": []}):
                        with patch("builtins.input", return_value=""):
                            with patch("asyncio.sleep", return_value=None):
                                await downloader.acquire_session_interactive(timeout_seconds=0.1)
            start_browser.assert_called_once_with(allow_ephemeral_fallback=False)

        import asyncio

        asyncio.run(_run())

    def test_inspect_listing_reports_direct_access_without_mutating_library(self) -> None:
        downloader = FabHybridDownloader(debug=False)

        with patch.object(downloader, "load_auth_state", return_value={"cookies": [], "origins": []}):
            with patch.object(downloader, "create_cffi_session", return_value=object()):
                with patch.object(downloader, "is_authenticated", return_value=True):
                    with patch.object(
                        downloader,
                        "get_listing_details",
                        return_value={"title": "Roman Shield", "catalogItemId": "catalog-roman", "seller": {"displayName": "FabSeller"}},
                    ):
                        with patch.object(
                            downloader,
                            "get_asset_formats",
                            return_value=[
                                {"assetFormatType": {"code": "fbx"}, "files": [{"uid": "file-1", "fileSize": 123}]}
                            ],
                        ):
                            with patch.object(downloader, "get_prices_info", return_value={"offers": []}):
                                with patch.object(downloader, "get_free_offer_id", return_value=None):
                                    with patch.object(downloader, "get_ownership_status", return_value={"owned": False, "status_code": 404}):
                                        with patch.object(downloader, "ensure_listing_in_library") as ensure_listing:
                                            info = downloader.inspect_listing("roman-shield-123")

        self.assertEqual(info["route"], "direct")
        self.assertEqual(info["download_access"], "library-or-purchase-required")
        self.assertEqual(info["title"], "Roman Shield")
        self.assertEqual(info["catalog_item_id"], "catalog-roman")
        self.assertEqual(info["seller_name"], "FabSeller")
        self.assertFalse(info["owned"])
        self.assertFalse(info["is_free"])
        ensure_listing.assert_not_called()

    def test_build_online_fab_library_map_summarizes_routes_and_keywords(self) -> None:
        downloader = FabHybridDownloader(debug=False)
        fake_session = unittest.mock.Mock()

        first_page = {
            "results": [
                {
                    "uid": "asset-1",
                    "createdAt": "2026-03-25T00:00:00+00:00",
                    "canRequestDownloadUrl": True,
                    "entitlement": {
                        "licenses": [
                            {"path": "license/standard/reference-plus-source"},
                        ]
                    },
                    "listing": {
                        "uid": "listing-1",
                        "title": "Ancient Roman Sword Gladius",
                        "listingType": "3d-model",
                        "publisher": {"sellerName": "FabSeller"},
                        "assetFormats": [
                            {"assetFormatType": {"code": "fbx"}},
                            {"assetFormatType": {"code": "glb"}},
                        ],
                    },
                }
            ],
            "next": "https://www.fab.com/i/library/search?cursor=next",
        }
        second_page = {
            "results": [
                {
                    "uid": "asset-2",
                    "createdAt": "2026-03-24T00:00:00+00:00",
                    "canRequestDownloadUrl": True,
                    "entitlement": {
                        "licenses": [
                            {"path": "license/legacy/uem"},
                        ]
                    },
                    "listing": {
                        "uid": "listing-2",
                        "title": "Animation Starter Pack",
                        "listingType": "animation",
                        "publisher": {"sellerName": "Epic Games"},
                        "assetFormats": [
                            {"assetFormatType": {"code": "unreal-engine"}},
                        ],
                    },
                }
            ],
            "next": None,
        }

        def _fake_get(url: str, *args, **kwargs):
            if url == "https://www.fab.com/i/users/me":
                return _FakeResponse({"displayName": "angryowl91"})
            if url == "https://www.fab.com/i/library/search":
                return _FakeResponse(first_page)
            if url == "https://www.fab.com/i/library/search?cursor=next":
                return _FakeResponse(second_page)
            raise AssertionError(f"Unexpected URL: {url}")

        fake_session.get.side_effect = _fake_get

        with patch.object(FabHybridDownloader, "load_auth_state", return_value={"cookies": [], "origins": []}):
            with patch.object(FabHybridDownloader, "create_cffi_session", return_value=fake_session):
                with patch.object(FabHybridDownloader, "is_authenticated", return_value=True):
                    report = build_online_fab_library_map(timeout_seconds=1.0)

        self.assertEqual(report["account_display_name"], "angryowl91")
        self.assertEqual(report["summary"]["total_records"], 2)
        self.assertEqual(report["summary"]["downloadable_records"], 2)
        self.assertEqual(report["summary"]["neutral_or_mixed_records"], 1)
        self.assertEqual(report["summary"]["unreal_only_records"], 1)
        self.assertEqual(report["summary"]["roman_candidate_count"], 2)
        self.assertEqual(report["records"][0]["route"], "neutral_or_mixed")
        self.assertEqual(report["records"][1]["route"], "unreal_only")

    def test_render_online_fab_library_map_markdown_mentions_counts(self) -> None:
        markdown = render_online_fab_library_map_markdown(
            {
                "account_display_name": "angryowl91",
                "summary": {
                    "total_records": 147,
                    "downloadable_records": 147,
                    "neutral_or_mixed_records": 60,
                    "unreal_only_records": 87,
                    "page_count": 7,
                    "roman_candidate_count": 5,
                    "format_counts": {"unreal-engine": 100, "fbx": 32},
                    "listing_type_counts": {"3d-model": 50, "animation": 12},
                    "publisher_counts": {"Epic Games": 15},
                },
                "roman_candidates": [
                    {
                        "title": "Ancient Roman Sword Gladius",
                        "route": "neutral_or_mixed",
                        "format_codes": ["fbx", "glb"],
                        "publisher_name": "FabSeller",
                    }
                ],
                "records": [
                    {
                        "title": "Ancient Roman Sword Gladius",
                        "listing_type": "3d-model",
                        "route": "neutral_or_mixed",
                        "format_codes": ["fbx", "glb"],
                    }
                ],
            }
        )

        self.assertIn("Total owned listings: `147`", markdown)
        self.assertIn("Neutral or mixed-format listings: `60`", markdown)
        self.assertIn("Ancient Roman Sword Gladius", markdown)


if __name__ == "__main__":
    unittest.main()
