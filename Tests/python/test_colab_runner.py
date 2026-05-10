from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from assetboy.execution.colab_runner import submit_batch_to_colab
from assetboy.providers.generator import emit_generator_setup


class ColabRunnerTests(unittest.TestCase):
    def test_submit_batch_to_colab_writes_handoff_and_drive_plan(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifacts = emit_generator_setup(
                profile_id="hunyuan3d2.production",
                pack_id="RA_PACK_WPN_COMBAT_SLICE_01",
                game_scope="roman_arena",
                output_dir=root / "generator",
            )

            result = submit_batch_to_colab(
                batch_path=artifacts.prompt_batch_path,
                output_dir=root / "colab",
                drive_folder="AssetBoy/colab/hunyuan3d2.production/RA_PACK_WPN_COMBAT_SLICE_01",
                dry_run=True,
            )

            self.assertTrue(result.handoff_manifest_path.exists())
            self.assertTrue(result.drive_stage_plan_path.exists())

            manifest = json.loads(result.handoff_manifest_path.read_text(encoding="utf-8"))
            stage_plan = json.loads(result.drive_stage_plan_path.read_text(encoding="utf-8"))

            self.assertEqual(manifest["schema_version"], "assetboy.colab_handoff.v1")
            self.assertEqual(manifest["drive_folder"], "AssetBoy/colab/hunyuan3d2.production/RA_PACK_WPN_COMBAT_SLICE_01")
            self.assertEqual(manifest["profile_id"], "hunyuan3d2.production")
            self.assertEqual(manifest["pack_id"], "RA_PACK_WPN_COMBAT_SLICE_01")
            self.assertIn("prompt_batch", {item["role"] for item in manifest["upload_items"]})
            self.assertIn("colab_notebook", {item["role"] for item in manifest["upload_items"]})
            self.assertIn("provenance_template", {item["role"] for item in manifest["upload_items"]})
            self.assertIn("review_checklist", {item["role"] for item in manifest["upload_items"]})
            self.assertIn("cleanup_plan", {item["role"] for item in manifest["upload_items"]})
            self.assertIn("payload_target", {item["role"] for item in manifest["upload_items"]})
            self.assertEqual(stage_plan["schema_version"], "assetboy.gdrive_stage_plan.v1")
            self.assertEqual(stage_plan["drive_folder"], manifest["drive_folder"])
            self.assertEqual(stage_plan["upload_items"], manifest["upload_items"])
            self.assertTrue((result.output_dir / "colab_handoff.md").exists())
