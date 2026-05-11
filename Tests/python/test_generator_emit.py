from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from assetboy.providers.generator import emit_generator_setup, profile_ids
from assetboy.cli_legacy import build_parser


class GeneratorEmitTests(unittest.TestCase):
    def test_profile_ids_include_required_colab_lanes(self) -> None:
        self.assertEqual(
            profile_ids(),
            ("animationgpt.pilot", "hunyuan3d2.production", "trellis.secondary"),
        )

    def test_emit_generator_setup_writes_expected_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_generator_setup(
                profile_id="hunyuan3d2.production",
                pack_id="RA_PACK_WPN_COMBAT_SLICE_01",
                game_scope="roman_arena",
                output_dir=Path(temp_dir),
            )

            self.assertTrue(artifacts.prompt_batch_path.exists())
            self.assertTrue(artifacts.provenance_template_path.exists())
            self.assertTrue(artifacts.payload_target_path_file.exists())
            self.assertTrue(artifacts.review_checklist_path.exists())
            self.assertTrue(artifacts.cleanup_plan_path.exists())

            payload = json.loads(artifacts.prompt_batch_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["profile"]["profile_id"], "hunyuan3d2.production")
            self.assertEqual(payload["pack_id"], "RA_PACK_WPN_COMBAT_SLICE_01")
            self.assertGreaterEqual(len(payload["jobs"]), 1)
            review_text = artifacts.review_checklist_path.read_text(encoding="utf-8")
            self.assertIn("## Setup", review_text)
            self.assertIn("## Progression", review_text)

    def test_hunyuan_cli_default_output_dir_is_dynamic(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "emit-hunyuan-batch",
                "--pack-id",
                "RA_PACK_WPN_BRIDGE_CHECK_01",
                "--game-scope",
                "roman_arena",
            ]
        )

        self.assertIsNone(args.output_dir)

    def test_animationgpt_cli_default_output_dir_is_dynamic(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "emit-animationgpt-pilot",
                "--pack-id",
                "RA_PACK_ANM_BRIDGE_CHECK_01",
                "--game-scope",
                "roman_arena",
            ]
        )

        self.assertIsNone(args.output_dir)
