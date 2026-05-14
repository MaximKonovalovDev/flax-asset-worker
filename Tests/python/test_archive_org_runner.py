"""Tests for execution/archive_org_runner.py (v1.10.s28)."""

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


def _binary_response(blob: bytes) -> FakeHttpResponse:
    return FakeHttpResponse(blob)


class ArchiveOrgLicenseFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.archive_org_runner import is_license_accepted
        self.fn = is_license_accepted

    def test_cc_by_accepted(self) -> None:
        self.assertTrue(self.fn("https://creativecommons.org/licenses/by/4.0/"))
        self.assertTrue(self.fn("http://creativecommons.org/licenses/by/2.0/"))

    def test_cc_by_sa_accepted(self) -> None:
        self.assertTrue(self.fn("https://creativecommons.org/licenses/by-sa/4.0/"))

    def test_publicdomain_accepted(self) -> None:
        self.assertTrue(self.fn("https://creativecommons.org/publicdomain/zero/1.0/"))
        self.assertTrue(self.fn("https://creativecommons.org/publicdomain/mark/1.0/"))

    def test_cc_by_nc_rejected(self) -> None:
        """Non-commercial is rejected (we want commercial-ok)."""
        self.assertFalse(self.fn("https://creativecommons.org/licenses/by-nc/4.0/"))

    def test_cc_by_nd_rejected(self) -> None:
        self.assertFalse(self.fn("https://creativecommons.org/licenses/by-nd/4.0/"))

    def test_empty_or_none_rejected(self) -> None:
        self.assertFalse(self.fn(""))
        self.assertFalse(self.fn("   "))


class PickDownloadFileTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.archive_org_runner import pick_download_file
        self.fn = pick_download_file

    def test_prefers_allowlist_format(self) -> None:
        meta = {
            "files": [
                {"name": "raw.tiff", "format": "Single Page Original TIFF"},
                {"name": "preview.jpg", "format": "JPEG"},
                {"name": "metadata.xml", "format": "Metadata"},
            ],
        }
        got = self.fn(meta, "image")
        self.assertEqual(got["name"], "preview.jpg")

    def test_falls_back_to_first_named_when_no_allowlist_match(self) -> None:
        meta = {
            "files": [
                {"name": "weird.xyz", "format": "WhoKnows"},
                {"name": "second.abc", "format": "AlsoWeird"},
            ],
        }
        got = self.fn(meta, "image")
        self.assertEqual(got["name"], "weird.xyz")

    def test_returns_none_for_empty_files(self) -> None:
        self.assertIsNone(self.fn({"files": []}, "image"))
        self.assertIsNone(self.fn({}, "image"))


class ArchiveOrgRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import archive_org_runner
        self.mod = archive_org_runner

    def test_search_includes_collection_clause(self) -> None:
        """v1.20.s140: --collection adds 'AND collection:<id>' clause to q."""
        captured_urls: list[str] = []

        def capture(req, *a, **kw):
            captured_urls.append(str(req.full_url))
            return _json_response({"response": {"docs": []}})

        with patch.object(self.mod.urllib.request, "urlopen", side_effect=capture):
            self.mod.search_archive_items("subject:roman", collection="prelinger")
        self.assertIn("collection%3Aprelinger", captured_urls[0])

    def test_search_returns_docs(self) -> None:
        payload = {
            "response": {
                "docs": [
                    {"identifier": "abc", "title": "T", "licenseurl": "x", "mediatype": "image"},
                    {"identifier": "def", "title": "U", "licenseurl": "y", "mediatype": "audio"},
                ],
            },
        }
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            docs = self.mod.search_archive_items("roman")
        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0]["identifier"], "abc")

    def test_search_empty_returns_empty(self) -> None:
        payload = {"response": {"docs": []}}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            docs = self.mod.search_archive_items("zzz")
        self.assertEqual(docs, [])

    def test_fetch_metadata_passthrough(self) -> None:
        payload = {
            "metadata": {"identifier": "abc"},
            "files": [{"name": "x.jpg", "format": "JPEG"}],
        }
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            got = self.mod.fetch_archive_metadata("abc")
        self.assertIn("files", got)
        self.assertEqual(got["files"][0]["name"], "x.jpg")

    def test_batch_downloads_only_cc_pd_items(self) -> None:
        search_payload = _json_response({
            "response": {
                "docs": [
                    {"identifier": "good", "title": "GoodItem",
                     "licenseurl": "https://creativecommons.org/publicdomain/zero/1.0/",
                     "mediatype": "image"},
                    {"identifier": "bad", "title": "BadItem",
                     "licenseurl": "https://creativecommons.org/licenses/by-nc/4.0/",
                     "mediatype": "image"},
                    {"identifier": "good2", "title": "Good2",
                     "licenseurl": "https://creativecommons.org/licenses/by/4.0/",
                     "mediatype": "image"},
                ],
            },
        })
        good_meta = _json_response({
            "files": [{"name": "preview.jpg", "format": "JPEG", "size": 12345}],
        })
        good_blob = _binary_response(b"\x89PNG-good")
        good2_meta = _json_response({
            "files": [{"name": "p.jpg", "format": "JPEG", "size": 999}],
        })
        good2_blob = _binary_response(b"\x89PNG-good2")

        # Iterator: search, then for each accepted item: meta + binary download.
        # Bad item is skipped BEFORE metadata fetch (license check is on doc itself).
        responses = iter([
            search_payload,
            good_meta, good_blob,
            good2_meta, good2_blob,
        ])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_archive_org_batch(
                        query="roman", mediatype="image",
                        pack_id="TEST", count=5, output_dir=out,
                    )

            self.assertTrue(result.ok)
            self.assertEqual(result.items_matched, 3)
            self.assertEqual(result.items_accepted_license, 2)
            self.assertEqual(result.items_downloaded, 2)
            self.assertEqual(result.items_skipped_restricted, 1)
            self.assertEqual(result.items_failed, 0)
            for p in result.downloaded_paths:
                self.assertTrue(p.exists())
                self.assertGreater(p.stat().st_size, 0)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "archive_org")
            self.assertEqual(len(manifest["entries"]), 2)
            for entry in manifest["entries"]:
                self.assertTrue(entry["license_accepted"])

    def test_batch_dry_run_skips_downloads(self) -> None:
        search_payload = _json_response({
            "response": {
                "docs": [
                    {"identifier": "x", "title": "X",
                     "licenseurl": "https://creativecommons.org/publicdomain/zero/1.0/",
                     "mediatype": "image"},
                ],
            },
        })
        meta = _json_response({
            "files": [{"name": "x.jpg", "format": "JPEG"}],
        })
        responses = iter([search_payload, meta])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_archive_org_batch(
                        query="x", pack_id="DRY",
                        count=3, output_dir=out, dry_run=True,
                    )

            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.items_downloaded, 1)
            for p in result.downloaded_paths:
                self.assertFalse(p.exists())
            self.assertTrue(result.manifest_path.exists())
            mf = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(mf["dry_run"])

    def test_batch_search_failure_returns_ok_false(self) -> None:
        def boom(*a: object, **kw: object) -> None:
            raise urllib.error.URLError("net down")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.mod.urllib.request, "urlopen", side_effect=boom):
                result = self.mod.run_archive_org_batch(
                    query="x", pack_id="F", count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("search_failed", result.error or "")

    def test_batch_no_matches(self) -> None:
        empty = _json_response({"response": {"docs": []}})
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=empty
            ):
                result = self.mod.run_archive_org_batch(
                    query="zzz", pack_id="E", count=2, output_dir=Path(tmp),
                )
        self.assertTrue(result.ok)
        self.assertEqual(result.items_matched, 0)
        self.assertEqual(result.error, "no_matches")


class ArchiveOrgLicenseTokenResolutionTests(unittest.TestCase):
    """v1.44.s245 — resolve_archive_license_tokens maps filter to allow-tuple."""

    def setUp(self) -> None:
        from assetboy.execution.archive_org_runner import (
            resolve_archive_license_tokens, is_license_accepted,
        )
        self.fn = resolve_archive_license_tokens
        self.is_ok = is_license_accepted

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(self.fn(""))
        self.assertIsNone(self.fn(None))

    def test_cc0_narrows_tuple(self) -> None:
        result = self.fn("cc0")
        self.assertIsNotNone(result)
        # CC0 family includes /publicdomain/zero and /publicdomain/mark.
        self.assertTrue(any("publicdomain" in t for t in result))

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.fn("commercial-only")

    def test_is_license_accepted_honors_allow_tokens(self) -> None:
        """With allow_tokens=cc0 family, CC-BY licenseurl is NOT accepted."""
        cc0 = ("creativecommons.org/publicdomain/zero",)
        self.assertTrue(self.is_ok(
            "https://creativecommons.org/publicdomain/zero/1.0/",
            allow_tokens=cc0,
        ))
        self.assertFalse(self.is_ok(
            "https://creativecommons.org/licenses/by/4.0/",
            allow_tokens=cc0,
        ))


class ArchiveOrgYearRangeTests(unittest.TestCase):
    """v1.40.s229 — year_from / year_to URL injection."""

    def setUp(self) -> None:
        from assetboy.execution import archive_org_runner
        self.mod = archive_org_runner

    def test_year_range_appears_in_url(self) -> None:
        captured: list[str] = []

        def capture(req, *a, **kw):
            captured.append(str(req.full_url))
            return _json_response({"response": {"docs": []}})

        with patch.object(
            self.mod.urllib.request, "urlopen", side_effect=capture
        ):
            self.mod.search_archive_items(
                "x", year_from=1900, year_to=1950,
            )
        joined = " ".join(captured)
        # year clause encoded with year:[1900 TO 1950] (URL-encoded brackets).
        self.assertTrue(
            "year" in joined and "1900" in joined and "1950" in joined,
            f"missing year clause; got {joined}",
        )

    def test_year_from_only_open_ended_high(self) -> None:
        captured: list[str] = []

        def capture(req, *a, **kw):
            captured.append(str(req.full_url))
            return _json_response({"response": {"docs": []}})

        with patch.object(
            self.mod.urllib.request, "urlopen", side_effect=capture
        ):
            self.mod.search_archive_items("x", year_from=2000)
        joined = " ".join(captured)
        self.assertIn("2000", joined)
        # `*` may be URL-encoded as %2A
        self.assertTrue("*" in joined or "%2A" in joined,
                        f"missing open-ended upper bound: {joined}")

    def test_year_to_only_open_ended_low(self) -> None:
        captured: list[str] = []

        def capture(req, *a, **kw):
            captured.append(str(req.full_url))
            return _json_response({"response": {"docs": []}})

        with patch.object(
            self.mod.urllib.request, "urlopen", side_effect=capture
        ):
            self.mod.search_archive_items("x", year_to=1800)
        joined = " ".join(captured)
        self.assertIn("1800", joined)

    def test_no_year_no_clause(self) -> None:
        captured: list[str] = []

        def capture(req, *a, **kw):
            captured.append(str(req.full_url))
            return _json_response({"response": {"docs": []}})

        with patch.object(
            self.mod.urllib.request, "urlopen", side_effect=capture
        ):
            self.mod.search_archive_items("x")
        joined = " ".join(captured)
        # Neither year: nor [ TO ] should appear in the query.
        self.assertNotIn("year%3A", joined)
        self.assertNotIn("year:", joined)


if __name__ == "__main__":
    unittest.main()
