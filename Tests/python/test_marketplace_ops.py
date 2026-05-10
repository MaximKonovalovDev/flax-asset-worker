from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from assetboy.providers.marketplace_ops import ClaimMethod, emit_marketplace_claim_job


class MarketplaceOpsTests(unittest.TestCase):
    def test_emit_marketplace_claim_job_for_fab_auto_redeemer(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_marketplace_claim_job(
                method=ClaimMethod.FAB_AUTO_REDEEMER,
                pack_id="RA_PACK_ENV_ARCH_FREE_01",
                game_scope="roman_arena",
                output_dir=Path(temp_dir),
            )
            self.assertTrue(artifacts.job_spec_path.exists())
            self.assertTrue(artifacts.review_checklist_path.exists())
            self.assertTrue(artifacts.command_template_path.exists())
            payload = json.loads(artifacts.job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["method"], "fab_auto_redeemer")
            self.assertEqual(payload["source_adapter"], "fab_auto_claim")

    def test_emit_marketplace_claim_job_for_free_games_claimer(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_marketplace_claim_job(
                method=ClaimMethod.FREE_GAMES_CLAIMER,
                pack_id="RA_PACK_ENV_ARCH_FREE_02",
                game_scope="roman_arena",
                output_dir=Path(temp_dir),
            )
            self.assertTrue(artifacts.command_template_path.exists())
            commands = artifacts.command_template_path.read_text(encoding="utf-8")
            self.assertIn("docker compose", commands)
