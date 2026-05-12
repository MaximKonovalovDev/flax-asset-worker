"""Tests for execution/iconify_runner.py (v1.10.s30)."""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


class FakeHttpResponse:
    def __init__(self, payload_bytes: bytes) -> None:
        self._payload = payload_bytes

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _json_response(payload: dict) -> FakeHttpResponse:
    return FakeHttpResponse(json.dumps(payload).encode("utf-8"))


def _text_response(text: str) -> FakeHttpResponse:
    return FakeHttpResponse(text.encode("utf-8"))


class IconifyLicenseFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.iconify_runner import is_license_accepted
        self.fn = is_license_accepted

    def test_mit_accepted(self) -> None:
        self.assertTrue(self.fn("MIT"))
        self.assertTrue(self.fn("mit"))

    def test_apache_accepted(self) -> None:
        self.assertTrue(self.fn("Apache-2.0"))

    def test_cc0_accepted(self) -> None:
        self.assertTrue(self.fn("CC0-1.0"))

    def test_ofl_accepted(self) -> None:
        self.assertTrue(self.fn("OFL-1.1"))

    def test_proprietary_rejected(self) -> None:
        self.assertFalse(self.fn("Proprietary"))
        self.assertFalse(self.fn("All-rights-reserved"))
        self.assertFalse(self.fn(""))


class IconifySearchTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import iconify_runner
        self.mod = iconify_runner

    def test_search_returns_icon_ids(self) -> None:
        payload = {
            "icons": ["mdi:sword", "tabler:sword", "game-icons:broadsword"],
            "total": 3,
        }
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            icons = self.mod.search_iconify_icons("sword")
        self.assertEqual(len(icons), 3)
        self.assertEqual(icons[0], "mdi:sword")

    def test_search_includes_prefix_param(self) -> None:
        """v1.20.s138: prefix= maps to Iconify's prefixes= URL param."""
        captured_urls: list[str] = []

        def capture(req, *a, **kw):
            captured_urls.append(str(req.full_url))
            return _json_response({"icons": []})

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=capture):
            self.mod.search_iconify_icons("sword", prefix="game-icons")
        self.assertIn("prefixes=game-icons", captured_urls[0])

    def test_search_no_prefix_no_param(self) -> None:
        captured_urls: list[str] = []

        def capture(req, *a, **kw):
            captured_urls.append(str(req.full_url))
            return _json_response({"icons": []})

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=capture):
            self.mod.search_iconify_icons("sword")
        self.assertNotIn("prefixes=", captured_urls[0])

    def test_search_clamps_limit(self) -> None:
        """limit=200 should clamp to 64 max per Iconify docs."""
        payload = {"icons": [], "total": 0}
        urls_captured: list[str] = []

        def capture(req: object, *a: object, **kw: object) -> FakeHttpResponse:
            urls_captured.append(str(req.full_url if hasattr(req, "full_url") else req))
            return _json_response(payload)

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=capture):
            self.mod.search_iconify_icons("x", limit=200)
        self.assertTrue(urls_captured)
        self.assertIn("limit=64", urls_captured[0])

    def test_fetch_icon_svg_returns_svg_text(self) -> None:
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="64"><path/></svg>'
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_text_response(svg)
        ):
            got = self.mod.fetch_icon_svg("mdi:sword", width=64)
        self.assertTrue(got.startswith("<svg"))

    def test_fetch_icon_svg_rejects_malformed_id(self) -> None:
        with self.assertRaises(ValueError):
            self.mod.fetch_icon_svg("not_a_prefix_name")


class IconifyRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import iconify_runner
        self.mod = iconify_runner

    def test_batch_downloads_only_open_license_icons(self) -> None:
        search_payload = _json_response({
            "icons": ["mdi:sword", "proprietary-set:weapon", "game-icons:dragon"],
        })
        collections_payload = _json_response({
            "mdi": {
                "name": "Material Design Icons",
                "license": {"spdx": "Apache-2.0", "title": "Apache 2.0", "url": "x"},
            },
            "proprietary-set": {
                "name": "Proprietary",
                "license": {"spdx": "Proprietary", "title": "Restricted", "url": "y"},
            },
            "game-icons": {
                "name": "Game Icons",
                "license": {"spdx": "CC-BY-4.0", "title": "CC BY 4.0", "url": "z"},
            },
        })
        svg_sword = _text_response('<svg id="sword"/>')
        svg_dragon = _text_response('<svg id="dragon"/>')
        responses = iter([
            search_payload, collections_payload,
            svg_sword, svg_dragon,
        ])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_iconify_batch(
                        query="sword", pack_id="P",
                        count=10, output_dir=out,
                    )

            self.assertTrue(result.ok)
            self.assertEqual(result.icons_matched, 3)
            self.assertEqual(result.icons_accepted_license, 2)
            self.assertEqual(result.icons_downloaded, 2)
            self.assertEqual(result.icons_skipped_restricted, 1)
            for p in result.downloaded_paths:
                self.assertTrue(p.exists())
                self.assertEqual(p.suffix, ".svg")
                self.assertGreater(p.stat().st_size, 0)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "iconify")
            self.assertEqual(len(manifest["entries"]), 2)
            for entry in manifest["entries"]:
                self.assertIn(entry["license_spdx"].lower(), {"apache-2.0", "cc-by-4.0"})

    def test_batch_dry_run_skips_svg_fetches(self) -> None:
        search = _json_response({"icons": ["mdi:home"]})
        collections = _json_response({
            "mdi": {"name": "MDI", "license": {"spdx": "Apache-2.0"}},
        })
        responses = iter([search, collections])  # NO svg fetch

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_iconify_batch(
                        query="home", pack_id="D",
                        count=2, output_dir=out, dry_run=True,
                    )
            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.icons_downloaded, 1)
            for p in result.downloaded_paths:
                self.assertFalse(p.exists())
            self.assertTrue(result.manifest_path.exists())

    def test_batch_skip_collections_check_downloads_all(self) -> None:
        """--skip-license-check bypasses /collections fetch and license filter."""
        search = _json_response({"icons": ["unknown:x", "weird:y"]})
        svg1 = _text_response('<svg/>')
        svg2 = _text_response('<svg/>')
        responses = iter([search, svg1, svg2])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_iconify_batch(
                        query="x", pack_id="S",
                        count=5, output_dir=out,
                        skip_collections_check=True,
                    )
            self.assertTrue(result.ok)
            self.assertEqual(result.icons_downloaded, 2)
            self.assertEqual(result.icons_skipped_restricted, 0)

    def test_batch_search_failure_returns_ok_false(self) -> None:
        def boom(*a: object, **kw: object) -> None:
            raise urllib.error.URLError("down")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.mod.urllib.request, "urlopen", side_effect=boom):
                result = self.mod.run_iconify_batch(
                    query="x", pack_id="F", count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("search_failed", result.error or "")

    def test_batch_no_matches(self) -> None:
        empty = _json_response({"icons": []})
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=empty
            ):
                result = self.mod.run_iconify_batch(
                    query="zzz", pack_id="E", count=2, output_dir=Path(tmp),
                )
        self.assertTrue(result.ok)
        self.assertEqual(result.icons_matched, 0)
        self.assertEqual(result.error, "no_matches")


if __name__ == "__main__":
    unittest.main()
