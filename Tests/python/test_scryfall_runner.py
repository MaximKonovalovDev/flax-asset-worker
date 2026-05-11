"""Tests for execution/scryfall_runner.py (v1.10.s29)."""

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


class ScryfallSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import scryfall_runner
        self.mod = scryfall_runner

    def test_search_returns_data_list(self) -> None:
        payload = {
            "data": [
                {"id": "a1", "name": "Card A"},
                {"id": "b2", "name": "Card B"},
            ],
            "has_more": False,
        }
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            cards = self.mod.search_scryfall_cards("type:dragon")
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["id"], "a1")

    def test_search_empty_data(self) -> None:
        payload = {"data": []}
        with patch.object(
            self.mod.urllib.request, "urlopen", return_value=_json_response(payload)
        ):
            cards = self.mod.search_scryfall_cards("zzzzzz")
        self.assertEqual(cards, [])


class ScryfallRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution import scryfall_runner
        self.mod = scryfall_runner

    def test_invalid_variant_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.mod.run_scryfall_batch(
                query="x", pack_id="V",
                count=2, variant="huge_4k",  # not in allowed set
                output_dir=Path(tmp),
            )
        self.assertFalse(result.ok)
        self.assertIn("invalid_variant", result.error or "")

    def test_batch_downloads_art_crop(self) -> None:
        search = _json_response({
            "data": [
                {
                    "id": "abcdef12-3456",
                    "name": "Test Dragon",
                    "artist": "Test Artist",
                    "set_name": "Test Set",
                    "scryfall_uri": "https://scryfall.com/x",
                    "image_uris": {
                        "art_crop": "https://cards.scryfall.io/art_crop/x.jpg",
                        "normal": "https://cards.scryfall.io/normal/x.jpg",
                    },
                },
                {
                    "id": "fedcba98-7654",
                    "name": "Other Card",
                    "artist": "Artist2",
                    "set_name": "Set2",
                    "scryfall_uri": "https://scryfall.com/y",
                    "image_uris": {
                        "art_crop": "https://cards.scryfall.io/art_crop/y.jpg",
                        "normal": "https://cards.scryfall.io/normal/y.jpg",
                    },
                },
            ],
        })
        img1 = _binary_response(b"\xff\xd8\xff\xe0image-1")
        img2 = _binary_response(b"\xff\xd8\xff\xe0image-2")
        responses = iter([search, img1, img2])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_scryfall_batch(
                        query="type:dragon", pack_id="P",
                        count=5, variant="art_crop", output_dir=out,
                    )

            self.assertTrue(result.ok)
            self.assertEqual(result.cards_matched, 2)
            self.assertEqual(result.cards_with_image, 2)
            self.assertEqual(result.cards_downloaded, 2)
            self.assertEqual(result.cards_failed, 0)
            for p in result.downloaded_paths:
                self.assertTrue(p.exists())
                self.assertTrue(p.suffix == ".jpg")  # art_crop variant
            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], "scryfall")
            self.assertEqual(manifest["variant"], "art_crop")
            self.assertTrue(manifest["attribution_required"])
            self.assertEqual(len(manifest["entries"]), 2)
            for entry in manifest["entries"]:
                self.assertIn("CC-BY-SA", entry["license"])
                self.assertTrue(entry["artist"])

    def test_batch_falls_back_to_card_faces_image_uris(self) -> None:
        """Two-faced cards have image_uris under card_faces[0]."""
        search = _json_response({
            "data": [
                {
                    "id": "x",
                    "name": "Two-Faced",
                    "artist": "A",
                    "set_name": "S",
                    "image_uris": None,  # top-level missing
                    "card_faces": [
                        {
                            "image_uris": {
                                "png": "https://cards.scryfall.io/png/x.png",
                                "art_crop": "https://cards.scryfall.io/art/x.jpg",
                            },
                        },
                    ],
                },
            ],
        })
        img = _binary_response(b"\x89PNG-2faced")
        responses = iter([search, img])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_scryfall_batch(
                        query="x", pack_id="TF",
                        count=1, variant="png", output_dir=out,
                    )

            self.assertTrue(result.ok)
            self.assertEqual(result.cards_downloaded, 1)
            for p in result.downloaded_paths:
                self.assertTrue(p.exists())
                self.assertEqual(p.suffix, ".png")

    def test_batch_dry_run_skips_downloads(self) -> None:
        search = _json_response({
            "data": [
                {
                    "id": "id1",
                    "name": "Card",
                    "image_uris": {
                        "art_crop": "https://cards.scryfall.io/x.jpg",
                    },
                },
            ],
        })
        responses = iter([search])  # NO image download response

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(
                self.mod.urllib.request, "urlopen",
                side_effect=lambda *a, **kw: next(responses),
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_scryfall_batch(
                        query="x", pack_id="D",
                        count=3, output_dir=out, dry_run=True,
                    )

            self.assertTrue(result.ok)
            self.assertTrue(result.dry_run)
            self.assertEqual(result.cards_downloaded, 1)
            for p in result.downloaded_paths:
                self.assertFalse(p.exists())
            self.assertTrue(result.manifest_path.exists())

    def test_batch_404_search_treated_as_no_matches(self) -> None:
        """Scryfall returns HTTP 404 for empty result queries; we treat that as ok+no_matches."""
        def http_404(*a: object, **kw: object) -> None:
            raise urllib.error.HTTPError(
                url="x", code=404, msg="Not Found",
                hdrs=None, fp=None,  # type: ignore[arg-type]
            )

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.mod.urllib.request, "urlopen", side_effect=http_404):
                result = self.mod.run_scryfall_batch(
                    query="zzz", pack_id="F", count=2, output_dir=Path(tmp),
                )
        self.assertTrue(result.ok)
        self.assertEqual(result.error, "no_matches")

    def test_batch_500_search_returns_ok_false(self) -> None:
        def http_500(*a: object, **kw: object) -> None:
            raise urllib.error.HTTPError(
                url="x", code=500, msg="Internal Error",
                hdrs=None, fp=None,  # type: ignore[arg-type]
            )

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.mod.urllib.request, "urlopen", side_effect=http_500):
                result = self.mod.run_scryfall_batch(
                    query="x", pack_id="F", count=2, output_dir=Path(tmp),
                )
        self.assertFalse(result.ok)
        self.assertIn("HTTP 500", result.error or "")

    def test_batch_card_without_image_counted_as_failed(self) -> None:
        search = _json_response({
            "data": [
                {"id": "x", "name": "NoArt", "image_uris": {}},  # no variants
            ],
        })
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(
                self.mod.urllib.request, "urlopen", return_value=search
            ):
                with patch.object(self.mod.time, "sleep"):
                    result = self.mod.run_scryfall_batch(
                        query="x", pack_id="N", count=2, output_dir=Path(tmp),
                    )
        self.assertTrue(result.ok)
        self.assertEqual(result.cards_matched, 1)
        self.assertEqual(result.cards_with_image, 0)
        self.assertEqual(result.cards_downloaded, 0)
        self.assertEqual(result.cards_failed, 1)


if __name__ == "__main__":
    unittest.main()
