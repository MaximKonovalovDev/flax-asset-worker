from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from assetboy.providers.engine_bridge import EngineBridgeKind, build_engine_export_job, emit_engine_export_job


class EngineBridgeTests(unittest.TestCase):
    def test_build_engine_export_job_uses_expected_defaults(self) -> None:
        job = build_engine_export_job(
            engine=EngineBridgeKind.UNITY,
            pack_id="RA_PACK_ENV_ARCH_SLICE_01",
            game_scope="roman_arena",
            source_url="https://assetstore.unity.com/packages/example",
            license_note="Licensed Unity Asset Store package owned by operator.",
        )
        self.assertEqual(job.engine, EngineBridgeKind.UNITY)
        self.assertIn("models", job.asset_types)
        self.assertIn("plugins", job.skip_types)

    def test_emit_engine_export_job_writes_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_engine_export_job(
                engine="unreal",
                pack_id="RA_PACK_ENV_ARCH_SLICE_01",
                game_scope="roman_arena",
                source_url="https://www.fab.com/listings/example",
                license_note="Licensed Fab package owned by operator.",
                source_package_name="Roman Arena Kit",
                output_dir=Path(temp_dir),
            )
            self.assertTrue(artifacts.job_spec_path.exists())
            self.assertTrue(artifacts.provenance_template_path.exists())
            self.assertTrue(artifacts.review_checklist_path.exists())
            self.assertTrue(artifacts.payload_target_path_file.exists())
            self.assertTrue(artifacts.cleanup_plan_path.exists())

            payload = json.loads(artifacts.job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["engine"], "unreal")
            self.assertEqual(payload["source_package_name"], "Roman Arena Kit")
