from pathlib import Path
from tempfile import TemporaryDirectory
import io
import json
import os
from contextlib import redirect_stdout
from unittest.mock import patch
import unittest

from assetboy.cleanup.blender_mcp import build_cleanup_plan
from assetboy import cli
from assetboy.execution.blender_runner import (
    _build_blender_mcp_calls,
    run_roman_blender_cleanup_wave,
)
from tests.helpers import write_roman_first_playable_fixture


class BlenderRunnerTests(unittest.TestCase):
    def test_static_cleanup_plan_uses_real_blender_mcp_tools(self) -> None:
        plan = build_cleanup_plan(
            pack_id="RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
            asset_kind="environment",
            source_lane="generator",
            animated=False,
        )
        calls = _build_blender_mcp_calls(
            plan,
            Path("C:/temp/in"),
            Path("C:/temp/out"),
            ["glb", "fbx"],
        )
        self.assertTrue(any(call.startswith("scene_get_overview(") for call in calls))
        self.assertTrue(any("viewport_screenshot_angles" in call for call in calls))
        self.assertTrue(any("unity_validate_mesh" in call for call in calls))
        self.assertTrue(any("unity_export_fbx" in call for call in calls))
        self.assertTrue(any("export_scene.gltf" in call for call in calls))
        self.assertTrue(any("lods_created" in call for call in calls))

    def test_animated_cleanup_plan_includes_rig_validation(self) -> None:
        plan = build_cleanup_plan(
            pack_id="RA_PACK_CHR_CORE_SLICE_01",
            asset_kind="character",
            source_lane="manual_browser",
            animated=True,
        )
        calls = _build_blender_mcp_calls(
            plan,
            Path("C:/temp/in"),
            Path("C:/temp/out"),
            ["fbx"],
        )
        self.assertTrue(any("unity_validate_rig" in call for call in calls))
        self.assertFalse(any("lods_created" in call for call in calls))

    def test_run_roman_cleanup_wave_discovers_real_inputs_and_ignores_mock_only_dirs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root, _, _ = write_roman_first_playable_fixture(temp_dir)
            mixamo_dir = (
                repo_root
                / "artifacts"
                / "library"
                / "FlaxAssetLibrary"
                / "inbox"
                / "downloads"
                / "manual_drop"
                / "mixamo"
                / "RA_PACK_CHR_CORE_SLICE_01"
            )
            mixamo_dir.mkdir(parents=True, exist_ok=True)
            (mixamo_dir / "shared_male_body.fbx").write_text("fbx\n", encoding="utf-8")
            skirmisher_fallback_dir = (
                repo_root
                / "artifacts"
                / "library"
                / "FlaxAssetLibrary"
                / "inbox"
                / "downloads"
                / "manual_drop"
                / "mixamo"
                / "RA_PACK_CHR_SKIRMISHER_SLICE_01"
            )
            skirmisher_fallback_dir.mkdir(parents=True, exist_ok=True)
            (skirmisher_fallback_dir / "skirmisher_body.fbx").write_text("fbx\n", encoding="utf-8")

            with patch.dict(os.environ, {"ASSETBOY_FLAX_REPO_ROOT": str(repo_root)}, clear=False):
                result = run_roman_blender_cleanup_wave(
                    game_scope="roman_arena",
                    pack_ids=(
                        "RA_PACK_CHR_CORE_SLICE_01",
                        "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
                        "RA_PACK_CHR_SKIRMISHER_SLICE_01",
                        "RA_PACK_MAT_AND_POLISH_SLICE_01",
                    ),
                    output_dir=Path(temp_dir) / "roman_cleanup_wave",
                    dry_run=True,
                )

            self.assertTrue(result.manifest_path.exists())
            self.assertTrue(result.summary_path.exists())
            self.assertEqual(result.total_packs, 4)
            self.assertEqual(result.cleanup_ready_packs, 3)
            self.assertEqual(result.blocked_packs, 0)
            self.assertEqual(result.skipped_packs, 1)

            by_pack = {item.pack_id: item for item in result.packs}
            self.assertEqual(by_pack["RA_PACK_CHR_CORE_SLICE_01"].status, "cleanup_ready")
            self.assertIn("mixamo", str(by_pack["RA_PACK_CHR_CORE_SLICE_01"].input_dir))
            self.assertTrue(by_pack["RA_PACK_CHR_CORE_SLICE_01"].cleanup_plan_path.exists())

            self.assertEqual(by_pack["RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01"].status, "cleanup_ready")
            self.assertIn("publish", str(by_pack["RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01"].input_dir))

            self.assertEqual(by_pack["RA_PACK_CHR_SKIRMISHER_SLICE_01"].status, "cleanup_ready")
            self.assertIn("mixamo", str(by_pack["RA_PACK_CHR_SKIRMISHER_SLICE_01"].input_dir))

            self.assertEqual(by_pack["RA_PACK_MAT_AND_POLISH_SLICE_01"].status, "skipped_no_blender")

            manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["cleanup_ready_packs"], 3)
            self.assertEqual(manifest["blocked_packs"], 0)

    def test_run_roman_cleanup_wave_cli_prints_summary(self) -> None:
        fake_result = unittest.mock.Mock(
            output_dir=Path("scripts/asset_factory/state/generated/roman_cleanup"),
            manifest_path=Path("scripts/asset_factory/state/generated/roman_cleanup/roman_blender_cleanup_wave.json"),
            summary_path=Path("scripts/asset_factory/state/generated/roman_cleanup/README.md"),
            total_packs=3,
            blender_required_packs=2,
            cleanup_ready_packs=1,
            blocked_packs=1,
            skipped_packs=1,
            packs=[
                unittest.mock.Mock(pack_id="RA_PACK_CHR_CORE_SLICE_01", status="cleanup_ready", asset_kind="character", animated=True),
                unittest.mock.Mock(pack_id="RA_PACK_CHR_SKIRMISHER_SLICE_01", status="missing_input", asset_kind="character", animated=True),
                unittest.mock.Mock(pack_id="RA_PACK_MAT_AND_POLISH_SLICE_01", status="skipped_no_blender", asset_kind="material", animated=False),
            ],
        )
        stdout = io.StringIO()
        with patch("assetboy.execution.blender_runner.run_roman_blender_cleanup_wave", return_value=fake_result):
            with redirect_stdout(stdout):
                result = cli.main(
                    [
                        "run-roman-cleanup-wave",
                        "--pack-id",
                        "RA_PACK_CHR_CORE_SLICE_01",
                        "--dry-run",
                    ]
                )

        self.assertEqual(result, 0)
        output = stdout.getvalue()
        self.assertIn("roman_cleanup_ready=1", output)
        self.assertIn("roman_cleanup_blocked=1", output)
        self.assertIn("roman_cleanup_pack=RA_PACK_CHR_CORE_SLICE_01 status=cleanup_ready", output)
