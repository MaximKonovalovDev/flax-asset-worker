from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from assetboy.cleanup.blender_batch import emit_blender_psk_batch_job


class BlenderBatchTests(unittest.TestCase):
    def test_emit_blender_psk_batch_job_writes_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            input_dir = Path(temp_dir) / "cue4parse_exports"
            input_dir.mkdir(parents=True, exist_ok=True)
            artifacts = emit_blender_psk_batch_job(
                pack_id="RA_PACK_ENV_ARCH_UE_SLICE_01",
                game_scope="roman_arena",
                input_dir=input_dir,
                output_dir=Path(temp_dir) / "blender_batch",
            )
            self.assertTrue(artifacts.job_spec_path.exists())
            self.assertTrue(artifacts.blender_script_path.exists())
            self.assertTrue(artifacts.powershell_path.exists())
            payload = json.loads(artifacts.job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_format"], "psk")
            self.assertIn("fbx", payload["export_targets"])
