"""
test_mixamo_glb_runner.py — Smoke tests for the Mixamo-to-Flax GLB merger runner.
No actual Blender invocation in CI — dry_run=True only.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from assetboy.execution.mixamo_glb_runner import run_mixamo_glb_merge


class MixamoGlbRunnerTests(unittest.TestCase):

    def test_dry_run_writes_merge_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "merge_out"
            result = run_mixamo_glb_merge(
                pack_id="RA_PACK_CHR_PLAYER_SLICE_01",
                char_fbx=Path(tmp) / "fake_char.fbx",
                anim_fbxs=[Path(tmp) / "idle.fbx", Path(tmp) / "slash.fbx"],
                output_dir=out,
                game_scope="roman_arena",
                dry_run=True,
            )
            self.assertTrue(result.dry_run)
            self.assertTrue(result.merge_plan_path.exists(), "merge_plan.json should be created in dry-run")
            plan = json.loads(result.merge_plan_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["pack_id"], "RA_PACK_CHR_PLAYER_SLICE_01")
            self.assertEqual(plan["game_scope"], "roman_arena")
            self.assertEqual(len(plan["expected_clips"]), 2)
            self.assertIn("idle", plan["expected_clips"])
            self.assertIn("slash", plan["expected_clips"])

    def test_dry_run_writes_provenance(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "merge_out"
            result = run_mixamo_glb_merge(
                pack_id="RA_PACK_CHR_PLAYER_SLICE_01",
                char_fbx=Path(tmp) / "fake_char.fbx",
                anim_fbxs=[],
                output_dir=out,
                game_scope="roman_arena",
                dry_run=True,
            )
            self.assertTrue(result.provenance_path.exists(), "provenance.json should be created in dry-run")
            prov = json.loads(result.provenance_path.read_text(encoding="utf-8"))
            self.assertEqual(prov["source_adapter"], "mixamo_manual_browser")
            self.assertIn("Mixamo", prov["author"])

    def test_dry_run_blender_cmd_has_background_flag(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "merge_out"
            result = run_mixamo_glb_merge(
                pack_id="TEST_PACK",
                char_fbx=Path(tmp) / "char.fbx",
                anim_fbxs=[Path(tmp) / "walk.fbx"],
                output_dir=out,
                dry_run=True,
            )
            self.assertIn("--background", result.blender_cmd)
            self.assertIn("--python", result.blender_cmd)
            # pack-id is passed after --
            self.assertIn("TEST_PACK", result.blender_cmd)

    def test_output_paths_structured_correctly(self) -> None:
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "merge_out"
            result = run_mixamo_glb_merge(
                pack_id="MY_PACK",
                char_fbx=Path(tmp) / "char.fbx",
                anim_fbxs=[Path(tmp) / "a.fbx"],
                output_dir=out,
                dry_run=True,
            )
            self.assertEqual(result.char_glb.name, "MY_PACK.glb")
            self.assertEqual(result.anims_dir.name, "anims")


if __name__ == "__main__":
    unittest.main()
