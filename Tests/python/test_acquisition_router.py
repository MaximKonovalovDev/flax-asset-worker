"""Integration tests for assetboy.workflows.acquisition_router (Path B s11).

Tests the 3 acquisition lanes (direct_url / manual_browser / generator)
without requiring network or a real workspace. All probes use dry_run=True
or monkey-patch the underlying runners.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class AcquisitionRouterTests(unittest.TestCase):
    """Verify the v1.2.1 acquisition router contract holds."""

    def setUp(self) -> None:
        from assetboy.workflows.acquisition_router import (
            AcquisitionResult,
            SUPPORTED_METHODS,
            acquire_source_dir,
        )
        self.acquire_source_dir = acquire_source_dir
        self.AcquisitionResult = AcquisitionResult
        self.SUPPORTED_METHODS = SUPPORTED_METHODS

    # ----------------------------------------------------------------- #
    # Public surface
    # ----------------------------------------------------------------- #

    def test_supported_methods_are_the_three_canonical_lanes(self) -> None:
        self.assertEqual(
            self.SUPPORTED_METHODS,
            {"direct_url", "manual_browser", "generator"},
        )

    def test_unknown_method_returns_clean_error(self) -> None:
        result = self.acquire_source_dir(
            {"id": "TP1", "acquisition_method": "magic", "provider": "unicorn"},
            {"recipe": {"game": "test"}},
            dry_run=True,
        )
        self.assertFalse(result.ok)
        self.assertIn("unknown_method", result.error)
        self.assertIn("magic", result.error)

    def test_missing_method_treated_as_unknown(self) -> None:
        result = self.acquire_source_dir(
            {"id": "TP_NoMethod", "provider": "polyhaven"},
            {"recipe": {"game": "test"}},
            dry_run=True,
        )
        self.assertFalse(result.ok)
        self.assertIn("unknown_method", result.error)

    # ----------------------------------------------------------------- #
    # direct_url lane
    # ----------------------------------------------------------------- #

    def test_direct_url_dry_run_polyhaven_returns_ok(self) -> None:
        result = self.acquire_source_dir(
            {
                "id": "TP_PH",
                "acquisition_method": "direct_url",
                "provider": "polyhaven",
                "assets": [{"asset_id": "leaves_forest_ground"}],
            },
            {"recipe": {"game": "test"}},
            dry_run=True,
        )
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.source_dir)
        self.assertEqual(result.method, "direct_url")
        self.assertEqual(result.provider, "polyhaven")

    def test_direct_url_dry_run_kenney_returns_ok(self) -> None:
        result = self.acquire_source_dir(
            {
                "id": "TP_KN",
                "acquisition_method": "direct_url",
                "provider": "kenney",
                "assets": [{"asset_id": "nature-kit"}],
            },
            {"recipe": {"game": "test"}},
            dry_run=True,
        )
        self.assertTrue(result.ok)

    def test_direct_url_unsupported_provider_returns_clean_error(self) -> None:
        result = self.acquire_source_dir(
            {
                "id": "TP_X",
                "acquisition_method": "direct_url",
                "provider": "made_up_provider",
            },
            {"recipe": {"game": "test"}},
            dry_run=False,
        )
        self.assertFalse(result.ok)
        # Either unsupported_provider or workspace error depending on setup
        self.assertTrue(
            "unsupported_provider" in result.error
            or "workspace_not_configured" in result.error,
            f"unexpected error: {result.error}",
        )

    # ----------------------------------------------------------------- #
    # manual_browser lane
    # ----------------------------------------------------------------- #

    def test_manual_browser_dry_run_returns_ok_with_drop_dir(self) -> None:
        result = self.acquire_source_dir(
            {
                "id": "TP_FAB",
                "acquisition_method": "manual_browser",
                "provider": "fab",
                "source_url": "https://www.fab.com/listings/abc",
                "license": {"kind": "fab_standard"},
            },
            {"recipe": {"game": "test"}},
            dry_run=True,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.method, "manual_browser")
        self.assertEqual(result.provider, "fab")
        self.assertIsNotNone(result.source_dir)

    def test_manual_browser_real_mode_emits_wait_marker(self) -> None:
        """In real mode with empty drop dir, returns awaiting_manual=True + writes marker."""
        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir) / "workspace"
            tmp_root.mkdir(parents=True)

            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": str(tmp_root)}, clear=False
            ):
                result = self.acquire_source_dir(
                    {
                        "id": "TP_FAB_WAIT",
                        "acquisition_method": "manual_browser",
                        "provider": "fab",
                        "source_url": "https://www.fab.com/listings/wait_test",
                    },
                    {"recipe": {"game": "primitive_tech"}},
                    dry_run=False,
                )

            self.assertFalse(result.ok)
            self.assertTrue(result.awaiting_manual)
            self.assertIsNotNone(result.source_dir)
            # Marker file should exist
            marker = result.source_dir / ".manual_browser_wait.json"
            self.assertTrue(
                marker.exists(),
                f"wait marker not found at {marker}",
            )
            # Marker payload should be valid JSON with the expected keys
            payload = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(payload["pack_id"], "TP_FAB_WAIT")
            self.assertEqual(payload["provider"], "fab")
            self.assertEqual(payload["method"], "manual_browser")
            self.assertIn("operator_instructions", payload)
            self.assertGreaterEqual(len(payload["operator_instructions"]), 3)

    def test_manual_browser_returns_ok_when_files_already_dropped(self) -> None:
        """If the drop dir already has files, returns ok=True (operator already acted)."""
        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir) / "workspace"
            tmp_root.mkdir(parents=True)
            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": str(tmp_root)}, clear=False
            ):
                # First call: marker emitted (awaiting_manual=True)
                _r1 = self.acquire_source_dir(
                    {
                        "id": "TP_DROPPED",
                        "acquisition_method": "manual_browser",
                        "provider": "fab",
                    },
                    {"recipe": {"game": "primitive_tech"}},
                    dry_run=False,
                )
                # Simulate operator dropping a file:
                (_r1.source_dir / "asset.fbx").write_text("fake-fbx", encoding="utf-8")
                # Second call: ok=True now
                result = self.acquire_source_dir(
                    {
                        "id": "TP_DROPPED",
                        "acquisition_method": "manual_browser",
                        "provider": "fab",
                    },
                    {"recipe": {"game": "primitive_tech"}},
                    dry_run=False,
                )

            self.assertTrue(result.ok)
            self.assertFalse(result.awaiting_manual)
            self.assertIn("manual drop complete", result.notes)

    # ----------------------------------------------------------------- #
    # generator lane
    # ----------------------------------------------------------------- #

    def test_generator_dry_run_returns_ok(self) -> None:
        result = self.acquire_source_dir(
            {
                "id": "TP_GEN",
                "acquisition_method": "generator",
                "provider": "comfyui",
            },
            {"recipe": {"game": "test"}},
            dry_run=True,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.method, "generator")
        self.assertEqual(result.provider, "comfyui")

    def test_generator_comfyui_not_running_returns_clean_error(self) -> None:
        """When ComfyUI isn't running on :8188, returns ok=False with helpful note."""
        with patch(
            "assetboy.execution.comfyui_runner.is_comfyui_running",
            return_value=False,
        ):
            with TemporaryDirectory() as tmp_dir:
                with patch.dict(
                    "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": tmp_dir}, clear=False
                ):
                    result = self.acquire_source_dir(
                        {
                            "id": "TP_COMFY",
                            "acquisition_method": "generator",
                            "provider": "comfyui",
                        },
                        {"recipe": {"game": "test"}},
                        dry_run=False,
                    )

        self.assertFalse(result.ok)
        self.assertIn("comfyui_not_running", result.error)

    def test_generator_unsupported_provider_returns_error(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": tmp_dir}, clear=False
            ):
                result = self.acquire_source_dir(
                    {
                        "id": "TP_UNSUP_GEN",
                        "acquisition_method": "generator",
                        "provider": "midjourney",
                    },
                    {"recipe": {"game": "test"}},
                    dry_run=False,
                )

        self.assertFalse(result.ok)
        self.assertIn("unsupported_generator_provider", result.error)


if __name__ == "__main__":
    unittest.main()
