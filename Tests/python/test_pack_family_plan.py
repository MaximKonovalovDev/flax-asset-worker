from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from assetboy.library.shared_packs import planned_shared_pack_families
from assetboy.workflows.pack_family_plan import emit_pack_family_plan


class PackFamilyPlanTests(unittest.TestCase):
    def test_planned_shared_pack_families_are_split_by_wave(self) -> None:
        wave_one = {family.pack_id for family in planned_shared_pack_families(wave=1)}
        wave_two = {family.pack_id for family in planned_shared_pack_families(wave=2)}

        self.assertIn("shared_chr_human_base_core", wave_one)
        self.assertIn("shared_mat_surface_core", wave_two)
        self.assertTrue(wave_one.isdisjoint(wave_two))

    def test_emit_pack_family_plan_writes_artifacts_for_one_family(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_pack_family_plan(
                game_scope="shared_library",
                pack_ids=("shared_font_ui_core",),
                output_dir=Path(temp_dir),
            )

            self.assertTrue(artifacts.manifest_path.exists())
            self.assertTrue(artifacts.summary_path.exists())

            payload = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["family_count"], 1)
            family_entry = payload["families"][0]
            self.assertEqual(family_entry["family"]["pack_id"], "shared_font_ui_core")
            self.assertEqual(family_entry["primary"]["bridge_id"], "google_fonts")
            queue_template = Path(family_entry["primary"]["queue_template_path"])
            self.assertTrue(queue_template.exists())

    def test_emit_pack_family_plan_uses_engine_bridge_artifacts_for_engine_fallbacks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            artifacts = emit_pack_family_plan(
                game_scope="shared_library",
                pack_ids=("shared_anm_locomotion_core",),
                output_dir=Path(temp_dir),
            )

            payload = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
            family_entry = payload["families"][0]
            unity_fallback = next(
                fallback for fallback in family_entry["fallbacks"] if fallback["bridge_id"] == "unity_engine_bridge"
            )
            engine_job = Path(unity_fallback["job_spec_path"])
            self.assertTrue(engine_job.exists())
