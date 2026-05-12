"""Tests for execution/openlibrary_runner.py (v1.13.s91)."""

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

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self) -> bytes:
        return self._payload


def _json_response(payload: dict) -> FakeHttpResponse:
    return FakeHttpResponse(json.dumps(payload).encode("utf-8"))


def _binary_response(blob: bytes) -> FakeHttpResponse:
    return FakeHttpResponse(blob)


class OpenLibrarySearchTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import openlibrary_runner
        self.mod = openlibrary_runner

    def test_search_returns_docs(self) -> None:
        payload = {"numFound": 2, "docs": [{"cover_i": 1}, {"cover_i": 2}]}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            docs = self.mod.search_openlibrary("alchemy")
        self.assertEqual(len(docs), 2)

    def test_search_with_author_uses_author_param(self) -> None:
        """v1.18.s128: author= param appears in URL when author supplied."""
        captured_urls: list[str] = []

        def capture(req, *a, **kw):
            captured_urls.append(str(req.full_url))
            return _json_response({"docs": []})

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=capture):
            self.mod.search_openlibrary("", author="ursula k le guin")
        self.assertEqual(len(captured_urls), 1)
        self.assertIn("author=ursula", captured_urls[0])

    def test_search_without_author_uses_q_param(self) -> None:
        captured_urls: list[str] = []

        def capture(req, *a, **kw):
            captured_urls.append(str(req.full_url))
            return _json_response({"docs": []})

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=capture):
            self.mod.search_openlibrary("alchemy")
        self.assertIn("q=alchemy", captured_urls[0])
        self.assertNotIn("author=", captured_urls[0])


class OpenLibraryRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import openlibrary_runner
        self.mod = openlibrary_runner

    def test_invalid_size_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.mod.run_openlibrary_batch(
                query="x", pack_id="P", count=1, size="XL",
                output_dir=Path(tmp),
            )
        self.assertFalse(result.ok)
        self.assertIn("invalid_size", result.error or "")

    def test_batch_downloads_covers(self) -> None:
        search = _json_response({
            "docs": [
                {
                    "key": "/works/OL1W", "cover_i": 100,
                    "title": "Test Book", "author_name": ["Test Author"],
                    "first_publish_year": 1900,
                    "subject": ["alchemy", "magic"],
                },
                {
                    "key": "/works/OL2W", "cover_i": 200,
                    "title": "Another", "author_name": ["B"],
                },
                # Doc without cover_i — should be skipped silently.
                {"key": "/works/OL3W", "title": "No Cover"},
            ],
        })
        blob1 = _binary_response(b"\xff\xd8book1")
        blob2 = _binary_response(b"\xff\xd8book2")
        responses = iter([search, blob1, blob2])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_openlibrary_batch(
                        query="alchemy", pack_id="OL", count=3,
                        output_dir=out,
                    )
            self.assertTrue(result.ok)
            self.assertEqual(result.docs_matched, 3)
            self.assertEqual(result.covers_with_id, 2)
            self.assertEqual(result.covers_downloaded, 2)
            self.assertEqual(result.covers_failed, 0)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "openlibrary")
            self.assertEqual(len(manifest["entries"]), 2)
            self.assertIn("REFERENCE-ONLY", manifest["use_policy_notice"])
            self.assertEqual(manifest["entries"][0]["title"], "Test Book")

    def test_batch_dry_run(self) -> None:
        search = _json_response({
            "docs": [{"key": "/x", "cover_i": 1, "title": "T"}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=search
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_openlibrary_batch(
                        query="x", pack_id="D", count=1,
                        output_dir=out, dry_run=True,
                    )
            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.covers_downloaded, 1)
            for p in result.downloaded_paths:
                self.assertFalse(p.exists())
            self.assertTrue(result.manifest_path.exists())

    def test_batch_search_failure(self) -> None:
        def boom(*a, **kw):
            raise urllib.error.URLError("net")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.mod.urllib.request, "urlopen", side_effect=boom):
                result = self.mod.run_openlibrary_batch(
                    query="x", pack_id="F", count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("search_failed", result.error or "")

    def test_batch_no_matches(self) -> None:
        empty = _json_response({"docs": []})
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=empty
            ):
                result = self.mod.run_openlibrary_batch(
                    query="zzz", pack_id="E", count=2, output_dir=Path(tmp),
                )
        self.assertTrue(result.ok)
        self.assertEqual(result.docs_matched, 0)
        self.assertEqual(result.error, "no_matches")


if __name__ == "__main__":
    unittest.main()
