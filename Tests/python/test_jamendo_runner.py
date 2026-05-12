"""Tests for execution/jamendo_runner.py (v1.10.s34)."""

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


class JamendoClientIdTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.jamendo_runner import get_client_id
        self.fn = get_client_id

    def test_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JAMENDO_CLIENT_ID", None)
            self.assertIsNone(self.fn())

    def test_set(self) -> None:
        with patch.dict(os.environ, {"JAMENDO_CLIENT_ID": "j-id"}):
            self.assertEqual(self.fn(), "j-id")


class JamendoLicenseFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.jamendo_runner import is_license_accepted
        self.fn = is_license_accepted

    def test_cc_by_accepted(self) -> None:
        self.assertTrue(self.fn("https://creativecommons.org/licenses/by/4.0/"))

    def test_cc_by_sa_accepted(self) -> None:
        self.assertTrue(self.fn("https://creativecommons.org/licenses/by-sa/4.0/"))

    def test_cc_by_nc_rejected_default(self) -> None:
        self.assertFalse(self.fn("https://creativecommons.org/licenses/by-nc/4.0/"))

    def test_cc_by_nd_rejected_default(self) -> None:
        self.assertFalse(self.fn("https://creativecommons.org/licenses/by-nd/4.0/"))

    def test_cc_by_nc_sa_rejected_default(self) -> None:
        self.assertFalse(self.fn("https://creativecommons.org/licenses/by-nc-sa/4.0/"))

    def test_allow_restrictive_accepts_nc(self) -> None:
        self.assertTrue(self.fn(
            "https://creativecommons.org/licenses/by-nc/4.0/",
            require_commercial=False, require_derivative=True,
        ))

    def test_publicdomain_accepted(self) -> None:
        self.assertTrue(self.fn("https://creativecommons.org/publicdomain/zero/1.0/"))

    def test_empty_rejected(self) -> None:
        self.assertFalse(self.fn(""))


class JamendoSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import jamendo_runner
        self.mod = jamendo_runner

    def test_search_includes_instrument_param(self) -> None:
        """v1.21.s146: instrument= maps to fuzzytags= URL param."""
        captured_urls: list[str] = []

        def capture(req, *a, **kw):
            captured_urls.append(str(req.full_url))
            return _json_response({"results": []})

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=capture):
            self.mod.search_jamendo_tracks(
                "x", client_id="cid", instrument="piano",
            )
        self.assertIn("fuzzytags=piano", captured_urls[0])

    def test_search_returns_results(self) -> None:
        payload = {"results": [{"id": 1}, {"id": 2}]}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            tracks = self.mod.search_jamendo_tracks("x", client_id="cid")
        self.assertEqual(len(tracks), 2)


class JamendoRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import jamendo_runner
        self.mod = jamendo_runner

    def test_missing_client_id_returns_ok_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("JAMENDO_CLIENT_ID", None)
                result = self.mod.run_jamendo_tracks_batch(
                    query="x", pack_id="P", count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("missing_client_id", result.error or "")

    def test_batch_filters_nc_tracks_by_default(self) -> None:
        search = _json_response({
            "results": [
                {
                    "id": 1, "name": "OK Track", "artist_name": "Artist1",
                    "album_name": "A", "duration": 120,
                    "license_ccurl": "https://creativecommons.org/licenses/by/4.0/",
                    "audiodownload": "https://j/1.mp3",
                    "shareurl": "https://j.com/1",
                    "musicinfo": {"tags": {"genres": ["ambient"]}},
                },
                {
                    "id": 2, "name": "NC Track", "artist_name": "Artist2",
                    "license_ccurl": "https://creativecommons.org/licenses/by-nc/4.0/",
                    "audiodownload": "https://j/2.mp3",
                    "musicinfo": {},
                },
                {
                    "id": 3, "name": "SA Track", "artist_name": "Artist3",
                    "license_ccurl": "https://creativecommons.org/licenses/by-sa/4.0/",
                    "audiodownload": "https://j/3.mp3",
                    "musicinfo": {},
                },
            ],
        })
        mp3_blob1 = _binary_response(b"ID3fakeMP31")
        mp3_blob3 = _binary_response(b"ID3fakeMP33")
        responses = iter([search, mp3_blob1, mp3_blob3])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_jamendo_tracks_batch(
                        query="x", client_id="cid", pack_id="P",
                        count=5, output_dir=out,
                    )

            self.assertTrue(result.ok)
            self.assertEqual(result.tracks_matched, 3)
            self.assertEqual(result.tracks_accepted_license, 2)
            self.assertEqual(result.tracks_downloaded, 2)
            self.assertEqual(result.tracks_skipped_restricted, 1)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(manifest["allow_restrictive"])
            self.assertEqual(len(manifest["entries"]), 2)
            for entry in manifest["entries"]:
                self.assertTrue(entry["license_accepted"])
                self.assertIn("Artist", entry["attribution_text"])

    def test_batch_allow_restrictive_accepts_nc(self) -> None:
        search = _json_response({
            "results": [
                {
                    "id": 1, "name": "NC Track", "artist_name": "A",
                    "license_ccurl": "https://creativecommons.org/licenses/by-nc/4.0/",
                    "audiodownload": "https://j/1.mp3",
                    "musicinfo": {},
                },
            ],
        })
        blob = _binary_response(b"mp3-bytes")
        responses = iter([search, blob])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_jamendo_tracks_batch(
                        query="x", client_id="cid", pack_id="R",
                        count=1, allow_restrictive=True, output_dir=out,
                    )
            self.assertTrue(result.ok)
            self.assertEqual(result.tracks_downloaded, 1)
            self.assertEqual(result.tracks_skipped_restricted, 0)

    def test_batch_dry_run(self) -> None:
        search = _json_response({
            "results": [
                {
                    "id": 1, "name": "T", "artist_name": "A",
                    "license_ccurl": "https://creativecommons.org/licenses/by/4.0/",
                    "audiodownload": "https://j/1.mp3",
                    "musicinfo": {},
                },
            ],
        })
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=search
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_jamendo_tracks_batch(
                        query="x", client_id="cid", pack_id="D",
                        count=1, output_dir=out, dry_run=True,
                    )
            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.tracks_downloaded, 1)
            for p in result.downloaded_paths:
                self.assertFalse(p.exists())
            self.assertTrue(result.manifest_path.exists())

    def test_batch_search_failure(self) -> None:
        def boom(*a: object, **kw: object) -> None:
            raise urllib.error.URLError("dead")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.mod.urllib.request, "urlopen", side_effect=boom):
                result = self.mod.run_jamendo_tracks_batch(
                    query="x", client_id="cid", pack_id="F",
                    count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("search_failed", result.error or "")


if __name__ == "__main__":
    unittest.main()
