from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest
from unittest.mock import patch

from assetboy.workflows.roman_blockers import build_summary_markdown, plan_roman_blockers
from tests.helpers import write_roman_first_playable_fixture


class RomanBlockerPlanTests(unittest.TestCase):
    @staticmethod
    def _plan_from_fixture(temp_dir: str | Path):
        repo_root, gate_path, catalog_path = write_roman_first_playable_fixture(temp_dir)
        with patch.dict(os.environ, {"ASSETBOY_FLAX_REPO_ROOT": str(repo_root)}, clear=False):
            return plan_roman_blockers(gate_path, catalog_path)

    def test_plan_roman_blockers_tracks_canonical_roman_pack_ids(self) -> None:
        with TemporaryDirectory() as temp_dir:
            plan = self._plan_from_fixture(temp_dir)
            task_by_pack = {task.pack_id: task for task in plan.tasks}

            self.assertEqual(len(plan.tasks), 11)
            self.assertIn("RA_PACK_CHR_CORE_SLICE_01", task_by_pack)
            self.assertIn("RA_PACK_CHR_DUELIST_SLICE_01", task_by_pack)
            self.assertIn("RA_PACK_AUD_MUSIC_SLICE_01", task_by_pack)

    def test_plan_roman_blockers_uses_pack_first_lane_choices(self) -> None:
        with TemporaryDirectory() as temp_dir:
            plan = self._plan_from_fixture(temp_dir)
            lane_by_pack = {task.pack_id: task.lane.value for task in plan.tasks}

            self.assertEqual(lane_by_pack["RA_PACK_CHR_CORE_SLICE_01"], "manual_browser")
            self.assertEqual(lane_by_pack["RA_PACK_WPN_COMBAT_SLICE_01"], "manual_browser")
            self.assertEqual(lane_by_pack["RA_PACK_AUD_SFX_SLICE_01"], "direct_url")
            self.assertEqual(lane_by_pack["RA_PACK_AUD_MUSIC_SLICE_01"], "direct_url")

    def test_plan_roman_blockers_carries_real_audit_statuses(self) -> None:
        with TemporaryDirectory() as temp_dir:
            plan = self._plan_from_fixture(temp_dir)
            task_by_pack = {task.pack_id: task for task in plan.tasks}

            self.assertEqual(task_by_pack["RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01"].audit_status, "reviewed_real")
            self.assertEqual(task_by_pack["RA_PACK_MAT_AND_POLISH_SLICE_01"].user_maturity_label, "usable_with_manual_steps")
            self.assertEqual(task_by_pack["RA_PACK_CHR_SKIRMISHER_SLICE_01"].audit_status, "payload_only_stub")
            self.assertEqual(task_by_pack["RA_PACK_WPN_COMBAT_SLICE_01"].audit_status, "reviewed_but_content_thin")

    def test_build_summary_markdown_mentions_shared_pack_families(self) -> None:
        with TemporaryDirectory() as temp_dir:
            plan = self._plan_from_fixture(temp_dir)
            summary = build_summary_markdown(plan)
            self.assertIn("Roman Blocker Summary", summary)
            self.assertIn("historic_roman_materials_core", summary)
            self.assertIn("shared_combat_animation_baseline", summary)
            self.assertIn("RA_PACK_CHR_CORE_SLICE_01", summary)

    def test_plan_roman_blockers_ignores_zero_gate_result_when_packs_are_thin(self) -> None:
        with TemporaryDirectory() as temp_dir:
            plan = self._plan_from_fixture(temp_dir)
            self.assertEqual(len(plan.gate_report.unresolved_slots), 0)
            self.assertGreater(len(plan.blocking_tasks), 0)

    def test_plan_roman_blockers_prefers_actual_provenance_adapter_when_present(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root, gate_path, catalog_path = write_roman_first_playable_fixture(temp_dir)
            provenance_path = (
                Path(repo_root)
                / "artifacts"
                / "library"
                / "FlaxAssetLibrary"
                / "publish"
                / "flax_intake"
                / "roman_arena"
                / "RA_PACK_CHR_SKIRMISHER_SLICE_01"
                / "provenance.json"
            )
            provenance_path.parent.mkdir(parents=True, exist_ok=True)
            provenance_path.write_text(
                '{"lane":"manual_browser","source_adapter":"mixamo"}',
                encoding="utf-8",
            )
            packet_path = provenance_path.parent / "packet.json"
            packet_path.write_text('{"pack_id":"RA_PACK_CHR_SKIRMISHER_SLICE_01","game_scope":"roman_arena","packet_status":"reviewed"}', encoding="utf-8")

            with patch.dict(os.environ, {"ASSETBOY_FLAX_REPO_ROOT": str(repo_root)}, clear=False):
                plan = plan_roman_blockers(gate_path, catalog_path)

            task_by_pack = {task.pack_id: task for task in plan.tasks}
            self.assertEqual(task_by_pack["RA_PACK_CHR_SKIRMISHER_SLICE_01"].source_adapter, "mixamo")
