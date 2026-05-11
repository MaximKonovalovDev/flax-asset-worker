"""Tests for execution/rawg_runner.py (v1.10.s33)."""

from __future__ import annotations

import json
import os
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


def _binary_response(blob: bytes) -> FakeHttpResponse:
    return FakeHttpResponse(blob)


class RawgApiKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.rawg_runner import get_api_key
        self.fn = get_api_key

    def test_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RAWG_API_KEY", None)
            self.assertIsNone(self.fn())

    def test_set(self) -> None:
        with patch.dict(os.environ, {"RAWG_API_KEY": "rkey"}):
            self.assertEqual(self.fn(), "rkey")


class RawgSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import rawg_runner
        self.mod = rawg_runner

    def test_search_returns_results(self) -> None:
        payload = {"count": 2, "results": [{"id": 1}, {"id": 2}]}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            results = self.mod.search_rawg_games("rogue", api_key="k")
        self.assertEqual(len(results), 2)

    def test_search_includes_genres_param(self) -> None:
        captured_urls: list[str] = []

        def capture(req: object, *a: object, **kw: object) -> FakeHttpResponse:
            captured_urls.append(str(req.full_url))
            return _json_response({"results": []})

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=capture):
            self.mod.search_rawg_games("x", api_key="k", genres="strategy,rpg")
        self.assertEqual(len(captured_urls), 1)
        self.assertIn("genres=strategy", captured_urls[0])


class RawgRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import rawg_runner
        self.mod = rawg_runner

    def test_missing_api_key_returns_ok_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("RAWG_API_KEY", None)
                result = self.mod.run_rawg_games_batch(
                    query="x", pack_id="P", count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("missing_api_key", result.error or "")

    def test_batch_downloads_cover_only_when_screenshots_disabled(self) -> None:
        search = _json_response({
            "results": [
                {
                    "id": 1, "name": "Test Game", "slug": "test-game",
                    "released": "2020-01-01", "rating": 4.2,
                    "background_image": "https://rawg/cover.jpg",
                    "short_screenshots": [
                        {"id": 10, "image": "https://rawg/s10.jpg"},
                    ],
                    "genres": [{"name": "Strategy"}],
                    "platforms": [{"platform": {"name": "PC"}}],
                },
            ],
        })
        cover_blob = _binary_response(b"\xff\xd8cover")
        responses = iter([search, cover_blob])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_rawg_games_batch(
                        query="x", api_key="k", pack_id="P",
                        count=1, include_screenshots=False, output_dir=out,
                    )

            self.assertTrue(result.ok)
            self.assertEqual(result.games_downloaded, 1)
            self.assertEqual(result.screenshots_downloaded, 0)
            self.assertEqual(len(result.downloaded_paths), 1)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "rawg.io")
            self.assertIn("REFERENCE", manifest["use_policy_notice"])
            self.assertEqual(manifest["entries"][0]["screenshots"], [])

    def test_batch_downloads_cover_and_screenshots(self) -> None:
        search = _json_response({
            "results": [
                {
                    "id": 1, "name": "Game", "slug": "game",
                    "background_image": "https://rawg/cover.jpg",
                    "short_screenshots": [
                        {"id": 10, "image": "https://rawg/s10.jpg"},
                        {"id": 11, "image": "https://rawg/s11.jpg"},
                    ],
                    "genres": [], "platforms": [],
                },
            ],
        })
        responses = iter([
            search,
            _binary_response(b"cover"),
            _binary_response(b"shot10"),
            _binary_response(b"shot11"),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_rawg_games_batch(
                        query="x", api_key="k", pack_id="P",
                        count=1, include_screenshots=True,
                        max_screenshots_per_game=3, output_dir=out,
                    )
            self.assertTrue(result.ok)
            self.assertEqual(result.games_downloaded, 1)
            self.assertEqual(result.screenshots_downloaded, 2)
            self.assertEqual(len(result.downloaded_paths), 3)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["entries"][0]["screenshots"]), 2)

    def test_batch_caps_screenshots(self) -> None:
        """max_screenshots_per_game=1 takes only the first screenshot."""
        search = _json_response({
            "results": [
                {
                    "id": 1, "name": "G", "slug": "g",
                    "background_image": "https://rawg/c.jpg",
                    "short_screenshots": [
                        {"id": 10, "image": "https://r/s10.jpg"},
                        {"id": 11, "image": "https://r/s11.jpg"},
                        {"id": 12, "image": "https://r/s12.jpg"},
                    ],
                    "genres": [], "platforms": [],
                },
            ],
        })
        responses = iter([
            search,
            _binary_response(b"c"),
            _binary_response(b"s10"),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_rawg_games_batch(
                        query="x", api_key="k", pack_id="C", count=1,
                        max_screenshots_per_game=1, output_dir=out,
                    )
            self.assertEqual(result.screenshots_downloaded, 1)
            self.assertEqual(len(result.downloaded_paths), 2)  # cover + 1 shot

    def test_batch_dry_run(self) -> None:
        search = _json_response({
            "results": [
                {
                    "id": 1, "name": "G", "slug": "g",
                    "background_image": "https://rawg/c.jpg",
                    "short_screenshots": [{"id": 10, "image": "https://r/s.jpg"}],
                    "genres": [], "platforms": [],
                },
            ],
        })
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=search
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_rawg_games_batch(
                        query="x", api_key="k", pack_id="D",
                        count=1, output_dir=out, dry_run=True,
                    )
            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.games_downloaded, 1)
            for p in result.downloaded_paths:
                self.assertFalse(p.exists())
            self.assertTrue(result.manifest_path.exists())

    def test_batch_search_failure(self) -> None:
        def boom(*a: object, **kw: object) -> None:
            raise urllib.error.URLError("net")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.mod.urllib.request, "urlopen", side_effect=boom):
                result = self.mod.run_rawg_games_batch(
                    query="x", api_key="k", pack_id="F",
                    count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("search_failed", result.error or "")


if __name__ == "__main__":
    unittest.main()
