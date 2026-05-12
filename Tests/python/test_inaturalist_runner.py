"""Tests for execution/inaturalist_runner.py (v1.13.s84)."""

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


class INaturalistLicenseFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.inaturalist_runner import is_license_accepted
        self.fn = is_license_accepted

    def test_cc0_accepted(self) -> None:
        self.assertTrue(self.fn("cc0"))
        self.assertTrue(self.fn("CC0"))

    def test_cc_by_accepted(self) -> None:
        self.assertTrue(self.fn("cc-by"))

    def test_cc_by_sa_accepted(self) -> None:
        self.assertTrue(self.fn("cc-by-sa"))

    def test_cc_by_nc_rejected_default(self) -> None:
        self.assertFalse(self.fn("cc-by-nc"))

    def test_cc_by_nc_accepted_when_permissive(self) -> None:
        self.assertTrue(self.fn("cc-by-nc", allow_restrictive=True))

    def test_empty_rejected(self) -> None:
        self.assertFalse(self.fn(""))
        self.assertFalse(self.fn("all-rights-reserved"))


class INaturalistSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import inaturalist_runner
        self.mod = inaturalist_runner

    def test_search_returns_results(self) -> None:
        payload = {"results": [{"id": 1}, {"id": 2}]}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            obs = self.mod.search_inaturalist_observations("oak tree")
        self.assertEqual(len(obs), 2)


class INaturalistRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import inaturalist_runner
        self.mod = inaturalist_runner

    def test_batch_filters_restrictive_licenses(self) -> None:
        search = _json_response({
            "results": [
                {
                    "id": 100,
                    "taxon": {"name": "Quercus alba", "preferred_common_name": "White Oak"},
                    "observed_on": "2024-06-15",
                    "place_guess": "Vermont, USA",
                    "observation_photos": [{
                        "photo": {
                            "url": "https://inat/100/square.jpg",
                            "license_code": "cc0",
                            "attribution": "Anon",
                            "original_dimensions": {"width": 1600, "height": 1200},
                        },
                    }],
                },
                {
                    "id": 200,
                    "taxon": {"name": "Restricted Sp", "preferred_common_name": ""},
                    "observation_photos": [{
                        "photo": {
                            "url": "https://inat/200/square.jpg",
                            "license_code": "cc-by-nc-nd",  # rejected
                            "attribution": "X",
                        },
                    }],
                },
                {
                    "id": 300,
                    "taxon": {"name": "Pine", "preferred_common_name": "Pine"},
                    "observation_photos": [{
                        "photo": {
                            "url": "https://inat/300/square.jpg",
                            "license_code": "cc-by-sa",
                            "attribution": "Pine Person",
                        },
                    }],
                },
            ],
        })
        blob1 = _binary_response(b"\xff\xd8oak")
        blob3 = _binary_response(b"\xff\xd8pine")
        responses = iter([search, blob1, blob3])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_inaturalist_batch(
                        query="trees", pack_id="P", count=5,
                        output_dir=out,
                    )

            self.assertTrue(result.ok)
            self.assertEqual(result.observations_matched, 3)
            self.assertEqual(result.observations_with_photo, 2)  # 2 OK photos
            self.assertEqual(result.photos_downloaded, 2)
            self.assertEqual(result.photos_skipped_restricted, 1)
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "inaturalist")
            self.assertEqual(len(manifest["entries"]), 2)
            # First entry should have attribution_required=False (CC0).
            entries_by_id = {e["observation_id"]: e for e in manifest["entries"]}
            self.assertFalse(entries_by_id[100]["attribution_required"])  # CC0
            self.assertTrue(entries_by_id[300]["attribution_required"])  # CC-BY-SA

    def test_batch_dry_run(self) -> None:
        search = _json_response({
            "results": [
                {
                    "id": 1, "taxon": {"name": "x", "preferred_common_name": ""},
                    "observation_photos": [{
                        "photo": {
                            "url": "https://inat/1/square.jpg",
                            "license_code": "cc0",
                        },
                    }],
                },
            ],
        })
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=search
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_inaturalist_batch(
                        query="x", pack_id="D", count=1,
                        output_dir=out, dry_run=True,
                    )
            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.photos_downloaded, 1)
            for p in result.downloaded_paths:
                self.assertFalse(p.exists())
            self.assertTrue(result.manifest_path.exists())

    def test_batch_search_failure(self) -> None:
        def boom(*a: object, **kw: object) -> None:
            raise urllib.error.URLError("net")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.mod.urllib.request, "urlopen", side_effect=boom):
                result = self.mod.run_inaturalist_batch(
                    query="x", pack_id="F", count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("search_failed", result.error or "")

    def test_batch_no_matches(self) -> None:
        empty = _json_response({"results": []})
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=empty
            ):
                result = self.mod.run_inaturalist_batch(
                    query="zzzz", pack_id="E", count=2, output_dir=Path(tmp),
                )
        self.assertTrue(result.ok)
        self.assertEqual(result.observations_matched, 0)
        self.assertEqual(result.error, "no_matches")


if __name__ == "__main__":
    unittest.main()
