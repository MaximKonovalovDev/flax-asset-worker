"""Tests for assetboy.execution.quaternius_runner (Path B v1.7.s15)."""

from __future__ import annotations

import io
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class ResolveUrlTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.quaternius_runner import (
            QUATERNIUS_BASE,
            resolve_quaternius_zip_url,
        )
        self.resolve = resolve_quaternius_zip_url
        self.base = QUATERNIUS_BASE

    def test_direct_zip_url_returned_as_is(self) -> None:
        url = "https://quaternius.com/packs/nature-kit.zip"
        self.assertEqual(self.resolve(url), url)

    def test_bare_slug_expanded_to_base_plus_zip(self) -> None:
        self.assertEqual(
            self.resolve("nature-kit"),
            f"{self.base}nature-kit.zip",
        )

    def test_quaternius_page_url_gets_zip_suffix(self) -> None:
        self.assertEqual(
            self.resolve("https://quaternius.com/packs/nature-kit"),
            "https://quaternius.com/packs/nature-kit.zip",
        )

    def test_empty_source_uses_pack_id_slug(self) -> None:
        # SHARED_QUAT_NATURE_KIT_01 -> nature-kit
        result = self.resolve("", pack_id="SHARED_QUAT_NATURE_KIT_01")
        self.assertEqual(result, f"{self.base}nature-kit.zip")

    def test_empty_source_no_pack_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.resolve("", pack_id="")


class RunQuaternusBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.execution.quaternius_runner import run_quaternius_batch
        self.run = run_quaternius_batch

    def test_dry_run_emits_provenance_without_network(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir) / "quat_dry"
            result = self.run(
                pack_id="SHARED_QUAT_TEST_01",
                source_url="https://quaternius.com/packs/test.zip",
                output_dir=out,
                dry_run=True,
            )
            self.assertTrue(result.dry_run)
            self.assertIsNone(result.error)
            self.assertTrue(result.provenance_path.exists())
            # Provenance must declare the CC0 license
            prov = json.loads(result.provenance_path.read_text(encoding="utf-8"))
            self.assertEqual(prov["license"]["kind"], "cc0")
            self.assertTrue(prov["license"]["commercial_ok"])
            self.assertEqual(prov["source_adapter"], "quaternius")
            self.assertEqual(prov["lane"], "direct_url")

    def test_missing_pack_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.run(pack_id="")

    def test_download_failure_returns_error_result(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch(
                "assetboy.execution.quaternius_runner._download_bytes",
                side_effect=Exception("simulated network error"),
            ):
                result = self.run(
                    pack_id="SHARED_QUAT_NET_FAIL",
                    source_url="https://quaternius.com/packs/missing.zip",
                    output_dir=Path(tmp_dir) / "out",
                    dry_run=False,
                )
            self.assertIsNotNone(result.error)
            self.assertIn("download_failed", result.error)

    def test_bad_zip_returns_error_result(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch(
                "assetboy.execution.quaternius_runner._download_bytes",
                return_value=b"this is not a zip file",
            ):
                result = self.run(
                    pack_id="SHARED_QUAT_BAD_ZIP",
                    source_url="https://quaternius.com/packs/corrupt.zip",
                    output_dir=Path(tmp_dir) / "out",
                    dry_run=False,
                )
            self.assertIsNotNone(result.error)
            self.assertIn("zip_invalid", result.error)

    def test_real_zip_extracts_files_and_writes_provenance(self) -> None:
        """Stub _download_bytes with a real ZIP; verify extract + provenance."""
        with TemporaryDirectory() as tmp_dir:
            # Build a tiny in-memory ZIP
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("models/rock.glb", b"fake-glb-bytes")
                zf.writestr("models/tree.glb", b"more-glb-bytes")
                zf.writestr("readme.txt", b"Quaternius pack")
            zip_bytes = buf.getvalue()

            with patch(
                "assetboy.execution.quaternius_runner._download_bytes",
                return_value=zip_bytes,
            ):
                result = self.run(
                    pack_id="SHARED_QUAT_TEST_REAL_01",
                    source_url="https://quaternius.com/packs/test.zip",
                    output_dir=Path(tmp_dir) / "out",
                    dry_run=False,
                )

            self.assertIsNone(result.error, f"unexpected error: {result.error}")
            self.assertFalse(result.dry_run)
            self.assertEqual(len(result.files_extracted), 3)
            # Files actually on disk
            extracted_root = result.output_dir
            self.assertTrue((extracted_root / "models" / "rock.glb").exists())
            self.assertTrue((extracted_root / "models" / "tree.glb").exists())
            self.assertTrue((extracted_root / "readme.txt").exists())
            # Provenance
            prov = json.loads(result.provenance_path.read_text(encoding="utf-8"))
            self.assertEqual(prov["file_count"], 3)
            self.assertFalse(prov["dry_run"])

    def test_zip_slip_paths_are_skipped(self) -> None:
        """Defensive: ZIP entries with '..' or absolute paths are dropped."""
        with TemporaryDirectory() as tmp_dir:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("../escape.txt", b"evil")
                zf.writestr("/abs/path.txt", b"also evil")
                zf.writestr("models/safe.glb", b"safe content")
            zip_bytes = buf.getvalue()

            with patch(
                "assetboy.execution.quaternius_runner._download_bytes",
                return_value=zip_bytes,
            ):
                result = self.run(
                    pack_id="SHARED_QUAT_ZIPSLIP",
                    source_url="https://quaternius.com/packs/slip.zip",
                    output_dir=Path(tmp_dir) / "out",
                    dry_run=False,
                )

            # Only safe.glb should have been extracted
            self.assertEqual(len(result.files_extracted), 1)
            self.assertIn("models/safe.glb", result.files_extracted)


class PresetsTests(unittest.TestCase):
    def test_presets_have_expected_shape(self) -> None:
        from assetboy.execution.quaternius_runner import (
            QUATERNIUS_PRESETS,
            list_presets,
        )
        self.assertGreater(len(QUATERNIUS_PRESETS), 0)
        for preset in QUATERNIUS_PRESETS:
            self.assertEqual(len(preset), 3)
            pack_id, slug, desc = preset
            self.assertTrue(pack_id.startswith("SHARED_QUAT_"))
            self.assertIsInstance(slug, str)
            self.assertIsInstance(desc, str)
        # list_presets returns the same data
        self.assertEqual(list_presets(), QUATERNIUS_PRESETS)


class AcquisitionRouterIntegrationTests(unittest.TestCase):
    """v1.7.s15: acquisition_router._drive_quaternius wires the runner."""

    def setUp(self) -> None:
        from assetboy.workflows.acquisition_router import acquire_source_dir
        self.acquire = acquire_source_dir

    def test_router_routes_quaternius_to_driver(self) -> None:
        """provider: quaternius reaches _drive_quaternius (mocked runner)."""
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": tmp_dir}, clear=False
            ):
                fake_result_type = type(
                    "FakeResult",
                    (),
                    {"error": None, "files_extracted": ["model.glb"]},
                )
                with patch(
                    "assetboy.execution.quaternius_runner.run_quaternius_batch",
                    return_value=fake_result_type(),
                ) as mock_run:
                    result = self.acquire(
                        {
                            "id": "TP_QUAT_01",
                            "acquisition_method": "direct_url",
                            "provider": "quaternius",
                            "assets": [{"asset_id": "nature-kit"}],
                        },
                        {"recipe": {"game": "test"}},
                        dry_run=False,
                    )

        self.assertTrue(result.ok, f"unexpected: {result.error}")
        self.assertEqual(mock_run.call_count, 1)

    def test_router_quaternius_no_assets_uses_preset_lookup(self) -> None:
        """When assets[] is empty, the driver looks up the preset by pack_id."""
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": tmp_dir}, clear=False
            ):
                fake = type("FakeResult", (), {"error": None})()
                with patch(
                    "assetboy.execution.quaternius_runner.run_quaternius_batch",
                    return_value=fake,
                ) as mock_run:
                    result = self.acquire(
                        {
                            "id": "SHARED_QUAT_NATURE_KIT_01",
                            "acquisition_method": "direct_url",
                            "provider": "quaternius",
                            # No assets[] -- should match the preset
                        },
                        {"recipe": {"game": "test"}},
                        dry_run=False,
                    )

        self.assertTrue(result.ok)
        self.assertEqual(mock_run.call_count, 1)

    def test_router_quaternius_no_match_returns_clean_error(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": tmp_dir}, clear=False
            ):
                result = self.acquire(
                    {
                        "id": "UNKNOWN_PACK_NOT_IN_PRESETS",
                        "acquisition_method": "direct_url",
                        "provider": "quaternius",
                    },
                    {"recipe": {"game": "test"}},
                    dry_run=False,
                )

        self.assertFalse(result.ok)
        self.assertIn("no_assets_in_pack", result.error)


class ValidatorWhitelistTests(unittest.TestCase):
    """v1.7.s15: recipe_validator's DIRECT_URL_PROVIDERS now includes quaternius."""

    def test_quaternius_is_in_direct_url_whitelist(self) -> None:
        from assetboy.workflows.recipe_validator import DIRECT_URL_PROVIDERS
        self.assertIn("quaternius", DIRECT_URL_PROVIDERS)

    def test_quaternius_provider_recipe_passes_validation(self) -> None:
        from assetboy.workflows.recipe_validator import validate_recipe_doc
        doc = {
            "recipe": {"id": "test", "game": "sandbox"},
            "packs": [
                {
                    "id": "SHARED_QUAT_NATURE_KIT_01",
                    "provider": "quaternius",
                    "acquisition_method": "direct_url",
                    "asset_kind": "model",
                    "license": {"kind": "cc0", "commercial_ok": True},
                    "assets": [{"asset_id": "nature-kit"}],
                },
            ],
        }
        result = validate_recipe_doc(doc, "test.yaml")
        self.assertTrue(result.ok, f"errors: {result.errors}")


if __name__ == "__main__":
    unittest.main()
