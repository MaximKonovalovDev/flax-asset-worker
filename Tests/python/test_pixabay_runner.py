"""Tests for execution/pixabay_runner.py (v1.10.s32)."""

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


class PixabayApiKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.pixabay_runner import get_api_key
        self.fn = get_api_key

    def test_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PIXABAY_API_KEY", None)
            self.assertIsNone(self.fn())

    def test_set(self) -> None:
        with patch.dict(os.environ, {"PIXABAY_API_KEY": "abc"}):
            self.assertEqual(self.fn(), "abc")


class PixabaySearchTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import pixabay_runner
        self.mod = pixabay_runner

    def test_search_photos_returns_hits(self) -> None:
        payload = {"hits": [{"id": 1}, {"id": 2}]}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            hits = self.mod.search_pixabay_photos("x", api_key="k")
        self.assertEqual(len(hits), 2)

    def test_search_photos_invalid_image_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.mod.search_pixabay_photos("x", api_key="k", image_type="bogus")

    def test_search_photos_orientation_added_to_url(self) -> None:
        """v1.24.s165: orientation='horizontal' adds to URL params."""
        captured_urls: list[str] = []

        def capture(req, *a, **kw):
            captured_urls.append(str(req.full_url))
            return _json_response({"hits": []})

        with patch.object(
            self.mod.urllib.request, "urlopen", side_effect=capture
        ):
            self.mod.search_pixabay_photos(
                "x", api_key="k", orientation="horizontal",
            )
        self.assertTrue(
            any("orientation=horizontal" in u for u in captured_urls),
            f"missing orientation; got {captured_urls}",
        )

    def test_search_photos_invalid_orientation_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.mod.search_pixabay_photos(
                "x", api_key="k", orientation="diagonal",
            )

    def test_search_photos_no_orientation_omits_param(self) -> None:
        """When orientation is None, the URL must not contain 'orientation='."""
        captured_urls: list[str] = []

        def capture(req, *a, **kw):
            captured_urls.append(str(req.full_url))
            return _json_response({"hits": []})

        with patch.object(
            self.mod.urllib.request, "urlopen", side_effect=capture
        ):
            self.mod.search_pixabay_photos("x", api_key="k")
        self.assertFalse(
            any("orientation=" in u for u in captured_urls),
            f"unexpected orientation; got {captured_urls}",
        )

    def test_search_videos_returns_hits(self) -> None:
        payload = {"hits": [{"id": 99}]}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            hits = self.mod.search_pixabay_videos("x", api_key="k")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["id"], 99)


class PixabayPickVideoQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.pixabay_runner import pick_video_quality
        self.fn = pick_video_quality

    def test_picks_requested_variant(self) -> None:
        hit = {"videos": {
            "large": {"url": "L", "width": 1920, "height": 1080},
            "medium": {"url": "M", "width": 1280, "height": 720},
            "small": {"url": "S", "width": 960, "height": 540},
        }}
        got = self.fn(hit, variant="medium")
        self.assertEqual(got["url"], "M")

    def test_falls_back_when_requested_missing(self) -> None:
        hit = {"videos": {
            "small": {"url": "S", "width": 960, "height": 540},
        }}
        got = self.fn(hit, variant="large")
        self.assertEqual(got["url"], "S")

    def test_returns_none_when_no_videos(self) -> None:
        self.assertIsNone(self.fn({"videos": {}}, variant="medium"))
        self.assertIsNone(self.fn({}, variant="medium"))


class PixabayPhotoRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import pixabay_runner
        self.mod = pixabay_runner

    def test_missing_api_key_returns_ok_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PIXABAY_API_KEY", None)
                result = self.mod.run_pixabay_photo_batch(
                    query="x", pack_id="P", count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("missing_api_key", result.error or "")

    def test_invalid_variant_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.mod.run_pixabay_photo_batch(
                query="x", pack_id="V", count=1, variant="someBogusKey",
                output_dir=Path(tmp),
            )
        self.assertFalse(result.ok)
        self.assertIn("invalid_variant", result.error or "")

    def test_photo_batch_downloads(self) -> None:
        search = _json_response({
            "hits": [
                {
                    "id": 100, "type": "photo", "tags": "stone wall",
                    "user": "U", "pageURL": "https://p/100",
                    "largeImageURL": "https://i/100_large.jpg",
                    "webformatURL": "https://i/100_web.jpg",
                    "imageWidth": 1920, "imageHeight": 1080,
                },
            ],
        })
        blob = _binary_response(b"\xff\xd8\xff\xe0fake")
        responses = iter([search, blob])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_pixabay_photo_batch(
                        query="stone", api_key="k", pack_id="P",
                        count=1, output_dir=out,
                    )
            self.assertTrue(result.ok)
            self.assertEqual(result.kind, "photos")
            self.assertEqual(result.items_downloaded, 1)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "pixabay")
            self.assertFalse(manifest["attribution_required"])
            self.assertEqual(manifest["entries"][0]["variant"], "largeImageURL")

    def test_photo_batch_falls_back_to_smaller_variant(self) -> None:
        """If requested largeImageURL missing, falls back through chain."""
        search = _json_response({
            "hits": [
                {
                    "id": 200, "type": "vector",
                    "webformatURL": "https://i/200_web.jpg",
                    # NO largeImageURL — must fall back.
                },
            ],
        })
        blob = _binary_response(b"\xff\xd8fake")
        responses = iter([search, blob])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_pixabay_photo_batch(
                        query="x", api_key="k", pack_id="FB",
                        count=1, variant="largeImageURL", output_dir=out,
                    )
            self.assertTrue(result.ok)
            self.assertEqual(result.items_downloaded, 1)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["entries"][0]["variant"], "webformatURL")


class PixabayVideoRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import pixabay_runner
        self.mod = pixabay_runner

    def test_video_batch_downloads_chosen_variant(self) -> None:
        search = _json_response({
            "hits": [
                {
                    "id": 50, "tags": "fire", "user": "U", "pageURL": "u",
                    "duration": 15,
                    "videos": {
                        "large": {"url": "https://v/L.mp4", "width": 1920, "height": 1080, "size": 1000},
                        "medium": {"url": "https://v/M.mp4", "width": 1280, "height": 720, "size": 500},
                    },
                },
            ],
        })
        blob = _binary_response(b"\x00\x00\x00\x18ftyp-fake")
        responses = iter([search, blob])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_pixabay_video_batch(
                        query="fire", api_key="k", pack_id="V",
                        count=1, variant="medium", output_dir=out,
                    )
            self.assertTrue(result.ok)
            self.assertEqual(result.kind, "videos")
            self.assertEqual(result.items_downloaded, 1)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["entries"][0]["height"], 720)

    def test_video_invalid_variant_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.mod.run_pixabay_video_batch(
                query="x", pack_id="V", count=1, variant="huge_8k",
                output_dir=Path(tmp),
            )
        self.assertFalse(result.ok)
        self.assertIn("invalid_variant", result.error or "")


if __name__ == "__main__":
    unittest.main()
