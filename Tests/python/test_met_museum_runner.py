"""Tests for execution/met_museum_runner.py (v1.10.s26).

Mocks urllib so we never hit the live Met API in CI.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


class FakeHttpResponse:
    """Minimal urlopen-compatible context manager."""

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


class MetMuseumRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import met_museum_runner
        self.mod = met_museum_runner

    def test_search_returns_object_ids(self) -> None:
        payload = {"total": 3, "objectIDs": [10, 20, 30]}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            ids = self.mod.search_met_object_ids("roman")
        self.assertEqual(ids, [10, 20, 30])

    def test_search_empty_returns_empty_list_not_none(self) -> None:
        """API returns objectIDs=null for no-match queries; we coerce to []."""
        payload = {"total": 0, "objectIDs": None}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            ids = self.mod.search_met_object_ids("zzzzzz_nomatch")
        self.assertEqual(ids, [])

    def test_fetch_object_returns_metadata(self) -> None:
        meta = {
            "objectID": 42,
            "isPublicDomain": True,
            "primaryImage": "https://images.metmuseum.org/blob/42/main.jpg",
            "title": "Test Title",
        }
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(meta)
        ):
            got = self.mod.fetch_met_object(42)
        self.assertEqual(got["objectID"], 42)
        self.assertTrue(got["isPublicDomain"])

    def test_batch_downloads_public_domain_only(self) -> None:
        """Mixed PD + non-PD search results: only PD images get downloaded."""
        search_payload = _json_response({"total": 3, "objectIDs": [1, 2, 3]})
        obj_pd_with_image = _json_response({
            "objectID": 1,
            "isPublicDomain": True,
            "primaryImage": "https://images.metmuseum.org/x/1.jpg",
            "title": "PD One",
            "artistDisplayName": "Anon",
            "objectDate": "100 BCE",
            "medium": "fresco",
            "classification": "painting",
            "department": "Greek and Roman Art",
            "objectURL": "https://www.metmuseum.org/art/collection/search/1",
        })
        obj_not_pd = _json_response({"objectID": 2, "isPublicDomain": False})
        obj_pd_two = _json_response({
            "objectID": 3,
            "isPublicDomain": True,
            "primaryImage": "https://images.metmuseum.org/x/3.jpg",
            "title": "PD Two",
            "artistDisplayName": "Anon",
            "objectDate": "200 BCE",
            "medium": "marble",
            "classification": "sculpture",
            "department": "Greek and Roman Art",
            "objectURL": "https://www.metmuseum.org/art/collection/search/3",
        })
        img_blob = _binary_response(b"\x89PNG\r\n\x1a\nfake-image-bytes")
        img_blob2 = _binary_response(b"\x89PNG\r\n\x1a\nfake-image-bytes-2")

        responses = iter([
            search_payload,    # /search
            obj_pd_with_image, # /objects/1
            img_blob,          # download img 1
            obj_not_pd,        # /objects/2 (skipped)
            obj_pd_two,        # /objects/3
            img_blob2,         # download img 3
        ])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_met_museum_batch(
                        query="roman fresco",
                        pack_id="TEST_PACK",
                        count=10,
                        output_dir=out,
                    )

            self.assertTrue(result.ok)
            self.assertEqual(result.objects_matched, 3)
            self.assertEqual(result.objects_public_domain, 2)
            self.assertEqual(result.objects_downloaded, 2)
            self.assertEqual(result.objects_skipped_non_pd, 1)
            self.assertEqual(result.objects_failed, 0)
            self.assertEqual(len(result.downloaded_paths), 2)
            for p in result.downloaded_paths:
                self.assertTrue(p.exists())
                self.assertGreater(p.stat().st_size, 0)
            self.assertIsNotNone(result.manifest_path)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "met_museum")
            self.assertEqual(manifest["objects_downloaded"], 2)
            self.assertEqual(len(manifest["entries"]), 2)
            for entry in manifest["entries"]:
                self.assertTrue(entry["is_public_domain"])
                self.assertEqual(entry["license"], "CC0")

    def test_batch_dry_run_skips_image_downloads(self) -> None:
        """dry_run=True hits search + per-object metadata, but no image bytes downloaded."""
        search_payload = _json_response({"total": 1, "objectIDs": [99]})
        obj_pd = _json_response({
            "objectID": 99,
            "isPublicDomain": True,
            "primaryImage": "https://images.metmuseum.org/x/99.jpg",
            "title": "T", "artistDisplayName": "", "objectDate": "",
            "medium": "", "classification": "", "department": "",
            "objectURL": "",
        })
        # Only 2 urlopen calls expected (search + object meta), NO image download.
        responses = iter([search_payload, obj_pd])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_met_museum_batch(
                        query="x", pack_id="DRY", count=5,
                        output_dir=out, dry_run=True,
                    )

            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.objects_downloaded, 1)
            self.assertEqual(result.objects_failed, 0)
            for p in result.downloaded_paths:
                self.assertFalse(p.exists())
            self.assertTrue(result.manifest_path.exists())
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["dry_run"])
            self.assertEqual(len(manifest["entries"]), 1)
            self.assertFalse(manifest["entries"][0]["downloaded"])

    def test_batch_search_failure_returns_ok_false(self) -> None:
        """When /search raises URLError, result.ok=False + error set."""
        def boom(*a: object, **kw: object) -> None:
            raise urllib.error.URLError("network down")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.mod.urllib.request, "urlopen", side_effect=boom):
                result = self.mod.run_met_museum_batch(
                    query="x", pack_id="FAIL", count=2, output_dir=Path(tmp),
                )

        self.assertFalse(result.ok)
        self.assertIn("search_failed", result.error or "")

    def test_batch_no_matches_is_ok_with_note(self) -> None:
        """Empty objectIDs is not a failure — ok=True, error=no_matches."""
        empty = _json_response({"total": 0, "objectIDs": None})
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=empty
            ):
                result = self.mod.run_met_museum_batch(
                    query="zzzzzzz", pack_id="EMPTY", count=4, output_dir=Path(tmp),
                )

        self.assertTrue(result.ok)
        self.assertEqual(result.objects_matched, 0)
        self.assertEqual(result.objects_downloaded, 0)
        self.assertEqual(result.error, "no_matches")


if __name__ == "__main__":
    unittest.main()
