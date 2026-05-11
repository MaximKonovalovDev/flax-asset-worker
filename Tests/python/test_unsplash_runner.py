"""Tests for execution/unsplash_runner.py (v1.10.s35)."""

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


def _empty_response() -> FakeHttpResponse:
    return FakeHttpResponse(b"")


class UnsplashAccessKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.unsplash_runner import get_access_key
        self.fn = get_access_key

    def test_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UNSPLASH_ACCESS_KEY", None)
            self.assertIsNone(self.fn())

    def test_set(self) -> None:
        with patch.dict(os.environ, {"UNSPLASH_ACCESS_KEY": "uak"}):
            self.assertEqual(self.fn(), "uak")


class UnsplashSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import unsplash_runner
        self.mod = unsplash_runner

    def test_search_returns_results(self) -> None:
        payload = {"total": 2, "results": [{"id": "a"}, {"id": "b"}]}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            photos = self.mod.search_unsplash_photos("x", access_key="k")
        self.assertEqual(len(photos), 2)

    def test_search_invalid_orientation_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.mod.search_unsplash_photos("x", access_key="k", orientation="diagonal")

    def test_search_accepts_valid_orientation(self) -> None:
        payload = {"results": []}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            self.mod.search_unsplash_photos("x", access_key="k", orientation="landscape")
        # No exception = pass.


class UnsplashRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import unsplash_runner
        self.mod = unsplash_runner

    def test_missing_access_key_returns_ok_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("UNSPLASH_ACCESS_KEY", None)
                result = self.mod.run_unsplash_photo_batch(
                    query="x", pack_id="P", count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("missing_access_key", result.error or "")

    def test_invalid_variant_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.mod.run_unsplash_photo_batch(
                query="x", pack_id="V", count=1, variant="8k_giant",
                output_dir=Path(tmp),
            )
        self.assertFalse(result.ok)
        self.assertIn("invalid_variant", result.error or "")

    def test_batch_downloads_and_pings_download_endpoint(self) -> None:
        search = _json_response({
            "results": [
                {
                    "id": "abc123",
                    "width": 1920, "height": 1080,
                    "description": "Stone wall",
                    "alt_description": "stones",
                    "urls": {
                        "raw": "https://i.unsplash.com/abc123-raw",
                        "regular": "https://i.unsplash.com/abc123-regular",
                        "small": "https://i.unsplash.com/abc123-small",
                    },
                    "user": {
                        "name": "Test Photog",
                        "links": {"html": "https://unsplash.com/@testphotog"},
                    },
                    "links": {"html": "https://unsplash.com/photos/abc123"},
                },
            ],
        })
        img_blob = _binary_response(b"\xff\xd8\xff\xe0fake-jpg")
        ping_resp = _empty_response()
        responses = iter([search, img_blob, ping_resp])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_unsplash_photo_batch(
                        query="stone", access_key="k", pack_id="P",
                        count=1, output_dir=out,
                    )

            self.assertTrue(result.ok)
            self.assertEqual(result.photos_matched, 1)
            self.assertEqual(result.photos_downloaded, 1)
            self.assertEqual(result.photos_failed, 0)
            self.assertEqual(result.download_pings, 1)  # ping succeeded
            for p in result.downloaded_paths:
                self.assertTrue(p.exists())
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "unsplash")
            self.assertFalse(manifest["attribution_required"])
            self.assertTrue(manifest["attribution_appreciated"])
            entry = manifest["entries"][0]
            self.assertTrue(entry["download_ping_triggered"])
            self.assertIn("Photo by Test Photog", entry["attribution_suggested"])

    def test_batch_skip_download_ping(self) -> None:
        """--skip-download-ping bypasses the analytics endpoint call."""
        search = _json_response({
            "results": [
                {
                    "id": "x", "urls": {"regular": "https://i/x.jpg"},
                    "user": {"name": "U"}, "links": {"html": ""},
                },
            ],
        })
        blob = _binary_response(b"fake")
        # Only 2 urlopen calls expected (search + image download), NO ping.
        responses = iter([search, blob])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_unsplash_photo_batch(
                        query="x", access_key="k", pack_id="S",
                        count=1, output_dir=out, skip_download_ping=True,
                    )
            self.assertTrue(result.ok)
            self.assertEqual(result.photos_downloaded, 1)
            self.assertEqual(result.download_pings, 0)

    def test_batch_dry_run_no_image_no_ping(self) -> None:
        search = _json_response({
            "results": [
                {
                    "id": "x", "urls": {"regular": "https://i/x.jpg"},
                    "user": {"name": "U"}, "links": {},
                },
            ],
        })
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=search
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_unsplash_photo_batch(
                        query="x", access_key="k", pack_id="D",
                        count=1, output_dir=out, dry_run=True,
                    )
            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.photos_downloaded, 1)
            self.assertEqual(result.download_pings, 0)
            for p in result.downloaded_paths:
                self.assertFalse(p.exists())
            self.assertTrue(result.manifest_path.exists())

    def test_batch_search_failure(self) -> None:
        def boom(*a: object, **kw: object) -> None:
            raise urllib.error.URLError("dead")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.mod.urllib.request, "urlopen", side_effect=boom):
                result = self.mod.run_unsplash_photo_batch(
                    query="x", access_key="k", pack_id="F",
                    count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("search_failed", result.error or "")

    def test_batch_falls_back_to_regular_when_requested_variant_missing(self) -> None:
        search = _json_response({
            "results": [
                {
                    "id": "x",
                    "urls": {"small": "https://i/x-s.jpg"},  # no 'raw' or 'regular'
                    "user": {"name": "U"}, "links": {},
                },
            ],
        })
        blob = _binary_response(b"fake")
        ping = _empty_response()
        responses = iter([search, blob, ping])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_unsplash_photo_batch(
                        query="x", access_key="k", pack_id="FB",
                        count=1, variant="raw", output_dir=out,
                    )
            self.assertTrue(result.ok)
            self.assertEqual(result.photos_downloaded, 1)
            # 'raw' missing, 'regular' also missing — falls back to 'small'.

    def test_trigger_download_endpoint_returns_false_on_failure(self) -> None:
        from assetboy.execution.unsplash_runner import _trigger_download_endpoint

        def boom(*a: object, **kw: object) -> None:
            raise urllib.error.URLError("down")

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=boom):
            result = _trigger_download_endpoint("x", "k")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
