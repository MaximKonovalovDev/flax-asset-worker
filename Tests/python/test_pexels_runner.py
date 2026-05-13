"""Tests for execution/pexels_runner.py (v1.10.s31)."""

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


class PexelsApiKeyTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.pexels_runner import get_api_key, PEXELS_API_KEY_ENV
        self.fn = get_api_key
        self.env = PEXELS_API_KEY_ENV

    def test_unset_returns_none(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(self.env, None)
            self.assertIsNone(self.fn())

    def test_empty_returns_none(self) -> None:
        with patch.dict(os.environ, {self.env: "   "}):
            self.assertIsNone(self.fn())

    def test_set_returns_value(self) -> None:
        with patch.dict(os.environ, {self.env: "abc123"}):
            self.assertEqual(self.fn(), "abc123")


class PexelsSearchOrientationTests(unittest.TestCase):
    """v1.24.s166 — orientation filter for search_pexels_photos."""

    def setUp(self) -> None:
        from assetboy.execution import pexels_runner
        self.mod = pexels_runner

    def test_orientation_added_to_url(self) -> None:
        captured_urls: list[str] = []

        def capture(req, *a, **kw):
            captured_urls.append(str(req.full_url))
            import io
            return io.BytesIO(b'{"photos": []}')

        with patch.object(
            self.mod.urllib.request, "urlopen", side_effect=capture
        ):
            self.mod.search_pexels_photos(
                "x", api_key="k", orientation="portrait",
            )
        self.assertTrue(
            any("orientation=portrait" in u for u in captured_urls),
            f"missing orientation; got {captured_urls}",
        )

    def test_invalid_orientation_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.mod.search_pexels_photos(
                "x", api_key="k", orientation="diagonal",
            )

    def test_no_orientation_omits_param(self) -> None:
        captured_urls: list[str] = []

        def capture(req, *a, **kw):
            captured_urls.append(str(req.full_url))
            import io
            return io.BytesIO(b'{"photos": []}')

        with patch.object(
            self.mod.urllib.request, "urlopen", side_effect=capture
        ):
            self.mod.search_pexels_photos("x", api_key="k")
        self.assertFalse(
            any("orientation=" in u for u in captured_urls),
            f"unexpected orientation param; got {captured_urls}",
        )


class PexelsPickVideoFileTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.pexels_runner import pick_video_file
        self.fn = pick_video_file

    def test_picks_highest_under_max(self) -> None:
        video = {"video_files": [
            {"link": "a", "height": 480},
            {"link": "b", "height": 1080},
            {"link": "c", "height": 720},
            {"link": "d", "height": 2160},  # > max
        ]}
        got = self.fn(video, max_height=1080)
        self.assertEqual(got["link"], "b")

    def test_falls_back_when_all_above_max(self) -> None:
        video = {"video_files": [
            {"link": "x", "height": 2160},
            {"link": "y", "height": 4320},
        ]}
        got = self.fn(video, max_height=1080)
        # Falls back to first file with link.
        self.assertEqual(got["link"], "x")

    def test_returns_none_when_no_files(self) -> None:
        self.assertIsNone(self.fn({"video_files": []}, max_height=720))
        self.assertIsNone(self.fn({}, max_height=720))


class PexelsPhotoRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import pexels_runner
        self.mod = pexels_runner

    def test_missing_api_key_returns_ok_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PEXELS_API_KEY", None)
                result = self.mod.run_pexels_photo_batch(
                    query="x", pack_id="P", count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("missing_api_key", result.error or "")

    def test_explicit_api_key_overrides_env(self) -> None:
        """Passing api_key= bypasses env var requirement."""
        search = _json_response({"photos": []})
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("PEXELS_API_KEY", None)
                with patch.object(
                    self.mod.urllib.request, "urlopen", return_value=search
                ):
                    result = self.mod.run_pexels_photo_batch(
                        query="x", api_key="test-key",
                        pack_id="P", count=2, output_dir=Path(tmp),
                    )
        self.assertTrue(result.ok)  # no matches but valid call
        self.assertEqual(result.items_matched, 0)
        self.assertEqual(result.error, "no_matches")

    def test_photo_batch_downloads_and_writes_manifest(self) -> None:
        search = _json_response({
            "photos": [
                {
                    "id": 100, "width": 1920, "height": 1080,
                    "url": "https://www.pexels.com/photo/100/",
                    "photographer": "P One",
                    "photographer_url": "https://www.pexels.com/@pone",
                    "alt": "Stone",
                    "src": {
                        "original": "https://images.pexels.com/photos/100/orig.jpg",
                        "large": "https://images.pexels.com/photos/100/large.jpg",
                        "medium": "https://images.pexels.com/photos/100/medium.jpg",
                    },
                },
            ],
        })
        img_blob = _binary_response(b"\xff\xd8\xff\xe0fake-jpeg")
        responses = iter([search, img_blob])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_pexels_photo_batch(
                        query="stone", api_key="k", pack_id="P",
                        count=5, variant="large", output_dir=out,
                    )

            self.assertTrue(result.ok)
            self.assertEqual(result.kind, "photos")
            self.assertEqual(result.items_matched, 1)
            self.assertEqual(result.items_downloaded, 1)
            for p in result.downloaded_paths:
                self.assertTrue(p.exists())
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "pexels")
            self.assertEqual(manifest["kind"], "photos")
            self.assertFalse(manifest["attribution_required"])
            self.assertEqual(len(manifest["entries"]), 1)
            self.assertEqual(manifest["entries"][0]["variant"], "large")

    def test_photo_batch_dry_run(self) -> None:
        search = _json_response({
            "photos": [
                {"id": 1, "src": {"large": "https://x/1.jpg"},
                 "photographer": "P", "url": "u"},
            ],
        })
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=search
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_pexels_photo_batch(
                        query="x", api_key="k", pack_id="D",
                        count=1, output_dir=out, dry_run=True,
                    )
            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.items_downloaded, 1)
            for p in result.downloaded_paths:
                self.assertFalse(p.exists())
            self.assertTrue(result.manifest_path.exists())

    def test_photo_batch_http_error(self) -> None:
        def http_401(*a: object, **kw: object) -> None:
            raise urllib.error.HTTPError(
                url="x", code=401, msg="Unauthorized",
                hdrs=None, fp=None,  # type: ignore[arg-type]
            )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.mod.urllib.request, "urlopen", side_effect=http_401):
                result = self.mod.run_pexels_photo_batch(
                    query="x", api_key="bad", pack_id="F",
                    count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("HTTP 401", result.error or "")


class PexelsRetryIntegrationTests(unittest.TestCase):
    """v1.12.s67: verify _authed_get_json now retries 429s."""

    def setUp(self) -> None:
        from assetboy.execution import pexels_runner
        self.mod = pexels_runner

    def test_search_retries_on_429_then_succeeds(self) -> None:
        """Pexels /search responding 429 once -> retry -> 200 returns parsed JSON."""
        call_count = {"n": 0}

        def fake_urlopen(req, *a, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise urllib.error.HTTPError(
                    url="x", code=429, msg="Too Many",
                    hdrs=None, fp=None,  # type: ignore[arg-type]
                )
            return _json_response({"photos": [{"id": 1}]})

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=fake_urlopen):
            with patch("assetboy.execution._http_retry.time.sleep"):
                photos = self.mod.search_pexels_photos("x", api_key="k")
        self.assertEqual(call_count["n"], 2)  # 1 initial 429 + 1 retry success
        self.assertEqual(len(photos), 1)

    def test_search_retries_exhaust_re_raises(self) -> None:
        """All retries return 429 -> final HTTPError propagates."""
        def always_429(*a, **kw):
            raise urllib.error.HTTPError(
                url="x", code=429, msg="Too Many",
                hdrs=None, fp=None,  # type: ignore[arg-type]
            )

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=always_429):
            with patch("assetboy.execution._http_retry.time.sleep"):
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    self.mod.search_pexels_photos("x", api_key="k")
        self.assertEqual(ctx.exception.code, 429)


class PexelsVideoRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import pexels_runner
        self.mod = pexels_runner

    def test_video_batch_picks_best_quality_under_max(self) -> None:
        search = _json_response({
            "videos": [
                {
                    "id": 200, "duration": 12,
                    "url": "https://www.pexels.com/video/200/",
                    "user": {"name": "VidPerson"},
                    "video_files": [
                        {"link": "https://v/480.mp4", "height": 480,
                         "width": 854, "quality": "sd", "file_type": "video/mp4"},
                        {"link": "https://v/1080.mp4", "height": 1080,
                         "width": 1920, "quality": "hd", "file_type": "video/mp4"},
                        {"link": "https://v/2160.mp4", "height": 2160,
                         "width": 3840, "quality": "uhd", "file_type": "video/mp4"},
                    ],
                },
            ],
        })
        vid_blob = _binary_response(b"\x00\x00\x00\x18ftypisom-fake")
        responses = iter([search, vid_blob])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_pexels_video_batch(
                        query="x", api_key="k", pack_id="V",
                        count=1, max_height=1080, output_dir=out,
                    )
            self.assertTrue(result.ok)
            self.assertEqual(result.kind, "videos")
            self.assertEqual(result.items_downloaded, 1)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            entry = manifest["entries"][0]
            self.assertEqual(entry["height"], 1080)  # picked 1080 not 2160 or 480
            self.assertEqual(entry["quality"], "hd")


class PexelsVideoMinDurationTests(unittest.TestCase):
    """v1.28.s183 — min_duration_s filter."""

    def setUp(self) -> None:
        from assetboy.execution import pexels_runner
        self.mod = pexels_runner

    def test_min_duration_filters_out_short_videos(self) -> None:
        """Three videos of duration 3/5/10s; min_duration=8 should keep only the 10s one."""
        search = _json_response({
            "videos": [
                {"id": 1, "duration": 3,
                 "url": "https://p/1/", "user": {"name": "U"},
                 "video_files": [{"link": "https://v/1.mp4", "height": 720,
                                  "width": 1280, "quality": "hd",
                                  "file_type": "video/mp4"}]},
                {"id": 2, "duration": 5,
                 "url": "https://p/2/", "user": {"name": "U"},
                 "video_files": [{"link": "https://v/2.mp4", "height": 720,
                                  "width": 1280, "quality": "hd",
                                  "file_type": "video/mp4"}]},
                {"id": 3, "duration": 10,
                 "url": "https://p/3/", "user": {"name": "U"},
                 "video_files": [{"link": "https://v/3.mp4", "height": 720,
                                  "width": 1280, "quality": "hd",
                                  "file_type": "video/mp4"}]},
            ],
        })
        vid_blob = _binary_response(b"\x00\x00\x00\x18ftypisom-fake")
        # Only one binary fetch expected (the 10s video).
        responses = iter([search, vid_blob])

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_pexels_video_batch(
                        query="x", api_key="k", pack_id="V",
                        count=5, max_height=1080,
                        min_duration_s=8.0,
                        output_dir=Path(tmp),
                    )
        self.assertTrue(result.ok)
        self.assertEqual(result.items_downloaded, 1)

    def test_min_duration_zero_keeps_all(self) -> None:
        """min_duration=0.0 keeps all (default behavior)."""
        search = _json_response({
            "videos": [
                {"id": 1, "duration": 2,
                 "url": "https://p/1/", "user": {"name": "U"},
                 "video_files": [{"link": "https://v/1.mp4", "height": 720,
                                  "width": 1280, "quality": "hd",
                                  "file_type": "video/mp4"}]},
            ],
        })
        vid_blob = _binary_response(b"\x00\x00\x00\x18ftypisom-fake")
        responses = iter([search, vid_blob])

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_pexels_video_batch(
                        query="x", api_key="k", pack_id="V",
                        count=5, max_height=1080,
                        output_dir=Path(tmp),
                    )
        self.assertEqual(result.items_downloaded, 1)


if __name__ == "__main__":
    unittest.main()
