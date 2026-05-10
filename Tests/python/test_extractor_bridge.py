from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from assetboy.providers.extractor_bridge import emit_extractor_job


class ExtractorBridgeTests(unittest.TestCase):
    def test_emit_extractor_job_writes_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_extractor_job(
                tool="asset_ripper",
                pack_id="RA_PACK_ENV_ARCH_SLICE_01",
                game_scope="roman_arena",
                source_package_name="Roman Arena Kit",
                source_url="https://assetstore.unity.com/packages/example",
                license_note="Owned licensed package.",
                input_path_hint="C:\\Temp\\RomanArenaKit",
                output_dir=Path(temp_dir),
            )
            self.assertTrue(artifacts.job_spec_path.exists())
            self.assertTrue(artifacts.cleanup_plan_path.exists())
            payload = json.loads(artifacts.job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["tool"], "asset_ripper")
