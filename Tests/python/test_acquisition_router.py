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

    # ----------------------------------------------------------------- #
    # s11.1 ComfyUI driver
    # ----------------------------------------------------------------- #

    def test_generator_comfyui_with_prompts_calls_runner(self) -> None:
        """When ComfyUI is up and pack has prompts, the runner is invoked."""
        fake_batch_result = [
            type("FakeRes", (), {
                "pack_id": "TP_GEN_COMFY",
                "prompt": "stone wall mossy",
                "asset_type": "texture",
                "output_dir": Path("/tmp/fake"),
                "outputs": ["fake_output.png"],
                "job_spec_path": None,
                "dry_run": False,
                "error": None,
            })()
        ]
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": tmp_dir}, clear=False
            ):
                with patch(
                    "assetboy.execution.comfyui_runner.is_comfyui_running",
                    return_value=True,
                ):
                    with patch(
                        "assetboy.execution.comfyui_runner.run_comfyui_batch",
                        return_value=fake_batch_result,
                    ) as mock_run:
                        result = self.acquire_source_dir(
                            {
                                "id": "TP_GEN_COMFY",
                                "acquisition_method": "generator",
                                "provider": "comfyui",
                                "asset_kind": "surface_pbr",
                                "prompts": [
                                    {"id": "p1", "text": "stone wall mossy", "width": 512},
                                    {"id": "p2", "text": "weathered wood planks"},
                                ],
                            },
                            {"recipe": {"game": "test"}},
                            dry_run=False,
                        )

        self.assertTrue(result.ok, f"expected ok=True, got: {result.error}")
        self.assertEqual(mock_run.call_count, 2)  # 2 prompts -> 2 invocations
        # First call should map surface_pbr -> "texture" asset_type
        first_call_kwargs = mock_run.call_args_list[0].kwargs
        self.assertEqual(first_call_kwargs["asset_type"], "texture")
        self.assertEqual(first_call_kwargs["width"], 512)  # override applied
        # Second call uses default width
        second_call_kwargs = mock_run.call_args_list[1].kwargs
        self.assertEqual(second_call_kwargs["width"], 1024)

    def test_generator_comfyui_no_prompts_returns_clean_error(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": tmp_dir}, clear=False
            ):
                with patch(
                    "assetboy.execution.comfyui_runner.is_comfyui_running",
                    return_value=True,
                ):
                    result = self.acquire_source_dir(
                        {
                            "id": "TP_GEN_COMFY_NOPROMPTS",
                            "acquisition_method": "generator",
                            "provider": "comfyui",
                        },
                        {"recipe": {"game": "test"}},
                        dry_run=False,
                    )

        self.assertFalse(result.ok)
        self.assertIn("no_prompts_in_pack", result.error)

    def test_generator_local_image_with_prompts_calls_runner(self) -> None:
        """When local_image provider used, run_local_image_batch is called."""
        fake_batch = type("FakeBatch", (), {"outputs": ["out.png"], "error": None})()
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": tmp_dir}, clear=False
            ):
                with patch(
                    "assetboy.execution.local_image_runner.run_local_image_batch",
                    return_value=fake_batch,
                ) as mock_run:
                    result = self.acquire_source_dir(
                        {
                            "id": "TP_GEN_SD",
                            "acquisition_method": "generator",
                            "provider": "local_image",
                            "prompts": [
                                {"id": "p1", "text": "stone wall", "count": 3, "width": 512},
                            ],
                        },
                        {"recipe": {"game": "test"}},
                        dry_run=False,
                    )

        self.assertTrue(result.ok, f"expected ok, got: {result.error}")
        self.assertEqual(mock_run.call_count, 1)
        kw = mock_run.call_args.kwargs
        self.assertEqual(kw["prompt"], "stone wall")
        self.assertEqual(kw["count"], 3)
        self.assertEqual(kw["width"], 512)

    def test_generator_sd_cpp_alias_routes_to_local_image(self) -> None:
        """provider: sd.cpp should route to the same driver as provider: local_image."""
        fake_batch = type("FakeBatch", (), {"outputs": ["out.png"]})()
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": tmp_dir}, clear=False
            ):
                with patch(
                    "assetboy.execution.local_image_runner.run_local_image_batch",
                    return_value=fake_batch,
                ) as mock_run:
                    result = self.acquire_source_dir(
                        {
                            "id": "TP_GEN_SDCPP",
                            "acquisition_method": "generator",
                            "provider": "sd.cpp",
                            "prompts": ["test prompt"],
                        },
                        {"recipe": {"game": "test"}},
                        dry_run=False,
                    )

        self.assertTrue(result.ok)
        self.assertEqual(mock_run.call_count, 1)

    def test_generator_stable_audio_still_TBD(self) -> None:
        """stable_audio_open_small driver is queued for v1.4; returns clean error."""
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": tmp_dir}, clear=False
            ):
                result = self.acquire_source_dir(
                    {
                        "id": "TP_GEN_SA",
                        "acquisition_method": "generator",
                        "provider": "stable_audio_open_small",
                        "prompts": ["forest dawn ambience"],
                    },
                    {"recipe": {"game": "test"}},
                    dry_run=False,
                )

        self.assertFalse(result.ok)
        self.assertIn("stable_audio_open_small_driver_TBD", result.error)

    def test_generator_comfyui_string_prompts_also_work(self) -> None:
        """Recipes can supply prompts as plain strings (not dicts)."""
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(
                "os.environ", {"ASSETBOY_FLAX_REPO_ROOT": tmp_dir}, clear=False
            ):
                with patch(
                    "assetboy.execution.comfyui_runner.is_comfyui_running",
                    return_value=True,
                ):
                    with patch(
                        "assetboy.execution.comfyui_runner.run_comfyui_batch",
                        return_value=[type("FakeRes", (), {"outputs": ["x.png"]})()],
                    ) as mock_run:
                        result = self.acquire_source_dir(
                            {
                                "id": "TP_GEN_COMFY_STR",
                                "acquisition_method": "generator",
                                "provider": "comfyui",
                                "prompts": ["just a string prompt"],
                            },
                            {"recipe": {"game": "test"}},
                            dry_run=False,
                        )

        self.assertTrue(result.ok)
        self.assertEqual(mock_run.call_count, 1)
        kw = mock_run.call_args.kwargs
        self.assertEqual(kw["prompt"], "just a string prompt")
        self.assertEqual(kw["width"], 1024)  # default kicks in for string prompts


if __name__ == "__main__":
    unittest.main()
