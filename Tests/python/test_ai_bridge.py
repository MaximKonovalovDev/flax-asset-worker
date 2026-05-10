from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from assetboy.providers.ai_bridge import default_ai_prompt_jobs, emit_ai_bridge_job


class AIBridgeTests(unittest.TestCase):
    def test_default_ai_prompt_jobs_for_chatgpt_pro_are_ui_focused(self) -> None:
        jobs = default_ai_prompt_jobs("chatgpt_pro", pack_id="RA_PACK_UI_COMBAT_SLICE_01")
        self.assertGreaterEqual(len(jobs), 2)
        self.assertEqual(jobs[0].asset_category.value, "ui_hud")

    def test_emit_ai_bridge_job_writes_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_ai_bridge_job(
                provider_id="chatgpt_pro",
                pack_id="RA_PACK_UI_COMBAT_SLICE_01",
                game_scope="roman_arena",
                output_dir=Path(temp_dir),
            )
            self.assertTrue(artifacts.job_spec_path.exists())
            self.assertTrue(artifacts.provenance_template_path.exists())
            self.assertTrue(artifacts.review_checklist_path.exists())
            payload = json.loads(artifacts.job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["provider"]["provider_id"], "chatgpt_pro")
            review_text = artifacts.review_checklist_path.read_text(encoding="utf-8")
            self.assertIn("## Setup", review_text)
            self.assertIn("## Progression", review_text)
