from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import json
import os
import unittest
from unittest.mock import patch

from assetboy.workflows.execution_kit import emit_roman_execution_kit
from tests.helpers import write_roman_first_playable_fixture


class RomanExecutionKitTests(unittest.TestCase):
    def test_emit_roman_execution_kit_writes_bridge_outputs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root, gate_path, catalog_path = write_roman_first_playable_fixture(temp_dir)
            with patch.dict(os.environ, {"ASSETBOY_FLAX_REPO_ROOT": str(repo_root)}, clear=False):
                artifacts = emit_roman_execution_kit(
                    gate_path=gate_path,
                    catalog_path=catalog_path,
                    output_dir=Path(temp_dir),
                )

            self.assertTrue(artifacts.manifest_path.exists())
            self.assertTrue(artifacts.summary_path.exists())
            self.assertIsNotNone(artifacts.queue_template_path)
            self.assertTrue(artifacts.queue_template_path.exists())

            manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["game_scope"], "roman_arena")
            self.assertEqual(manifest["roman_pack_count"], 11)
            self.assertEqual(manifest["blocking_pack_count"], 10)
            self.assertEqual(manifest["ready_reviewed_pack_count"], 1)
            self.assertEqual(len(manifest["tasks"]), 10)

            with artifacts.queue_template_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertGreaterEqual(len(rows), 2)
            self.assertIn("RA_PACK_AUD_MUSIC_SLICE_01", {row["pack_id"] for row in rows})
            self.assertIn("RA_PACK_AUD_SFX_SLICE_01", {row["pack_id"] for row in rows})

            self.assertTrue((Path(temp_dir) / "browser" / "RA_PACK_CHR_CORE_SLICE_01" / "browser_job.json").exists())
            self.assertTrue((Path(temp_dir) / "browser" / "RA_PACK_WPN_COMBAT_SLICE_01" / "browser_job.json").exists())
            self.assertFalse((Path(temp_dir) / "browser" / "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01" / "browser_job.json").exists())
