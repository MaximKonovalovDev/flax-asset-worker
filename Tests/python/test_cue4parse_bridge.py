from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from assetboy.providers.cue4parse_bridge import emit_cue4parse_job


class Cue4ParseBridgeTests(unittest.TestCase):
    def test_emit_cue4parse_job_writes_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_cue4parse_job(
                pack_id="RA_PACK_ENV_ARCH_UE_SLICE_01",
                game_scope="roman_arena",
                source_package_name="Roman Arena Kit",
                source_url="https://www.fab.com/listings/example",
                license_note="Owned package",
                input_path_hint=r"C:\Temp\DummyProject\Content",
                output_dir=Path(temp_dir),
            )
            self.assertTrue(artifacts.job_spec_path.exists())
            self.assertTrue(artifacts.provenance_template_path.exists())
            self.assertTrue(artifacts.command_template_path.exists())
            self.assertTrue(artifacts.cleanup_plan_path.exists())
            payload = json.loads(artifacts.job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_adapter"], "cue4parse")
            self.assertEqual(payload["mesh_output_format"], "psk")
