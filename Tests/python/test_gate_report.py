import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from assetboy.cli import _default_gate_path
from assetboy.library.paths import project_root
from assetboy.providers.lanes import ProviderLane
from assetboy.workflows.gate_report import load_gate_report
from tests.helpers import write_roman_fixture


class GateReportTests(unittest.TestCase):
    @staticmethod
    def _gate_path() -> Path:
        latest_gate = project_root() / "artifacts" / "quality" / "asset-gates" / "latest.json"
        if latest_gate.exists():
            return latest_gate
        return _default_gate_path()

    def test_load_gate_report_reads_live_roman_gate_shape(self) -> None:
        gate_path = self._gate_path()
        report = load_gate_report(gate_path)
        raw = json.loads(gate_path.read_text(encoding="utf-8-sig"))
        dashboard = raw.get("dashboard", {}) or raw.get("gate", {}).get("dashboard", {})
        expected_count = int(dashboard.get("counts", {}).get("manifest_unresolved_slots", 0))

        self.assertEqual(report.recipe, "fps")
        self.assertEqual(len(report.unresolved_slots), expected_count)

    def test_lane_assignment_is_stable_for_sample_roman_gate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            gate_path, _ = write_roman_fixture(temp_dir)
            report = load_gate_report(gate_path)
        lane_by_slot = {slot.slot: slot.lane for slot in report.unresolved_slots}

        self.assertEqual(lane_by_slot["player_prefab"], ProviderLane.MANUAL_BROWSER)
        self.assertEqual(lane_by_slot["hud_texture"], ProviderLane.DIRECT_URL)
        self.assertEqual(lane_by_slot["music_clip"], ProviderLane.DIRECT_URL)
        self.assertEqual(lane_by_slot["sfx_library"], ProviderLane.DIRECT_URL)
        self.assertEqual(lane_by_slot["weapon_prefab"], ProviderLane.GENERATOR)

    def test_gate_report_includes_name_hints(self) -> None:
        with TemporaryDirectory() as temp_dir:
            gate_path, _ = write_roman_fixture(temp_dir)
            report = load_gate_report(gate_path)
            player = next(slot for slot in report.unresolved_slots if slot.slot == "player_prefab")
            self.assertIn("character", player.name_hints)
