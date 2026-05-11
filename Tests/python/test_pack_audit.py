"""Tests for assetboy.workflows.pack_audit (Path B v1.6.s3)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


class PackAuditTests(unittest.TestCase):
    """Verify build_pack_audit_report aggregates ledgers correctly."""

    def setUp(self) -> None:
        from assetboy.workflows.pack_audit import build_pack_audit_report
        self.build = build_pack_audit_report

    def _seed_ledgers(self, root: Path, layout: dict[str, dict[str, dict]]) -> None:
        """Build a state/pack_pipeline/<game>/<pack_id>.json tree.

        layout = {game_scope: {pack_id: ledger_dict, ...}, ...}
        """
        pipeline_dir = root / "pack_pipeline"
        pipeline_dir.mkdir(parents=True, exist_ok=True)
        for game_scope, packs in layout.items():
            game_dir = pipeline_dir / game_scope
            game_dir.mkdir(parents=True, exist_ok=True)
            for pack_id, ledger in packs.items():
                (game_dir / f"{pack_id}.json").write_text(
                    json.dumps(ledger, indent=2), encoding="utf-8"
                )

    def _patch_state_root(self, tmp_root: Path):
        """Mock state_root to point at our tmp dir."""
        from assetboy.workflows import pack_audit
        return patch.object(pack_audit, "state_root", return_value=tmp_root)

    # ------------------------------------------------------------------ #
    # Empty / missing dir
    # ------------------------------------------------------------------ #

    def test_missing_pipeline_dir_returns_empty_report(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            with self._patch_state_root(Path(tmp_dir)):
                report = self.build()
        self.assertEqual(report["summary"]["total_ledgers"], 0)
        self.assertEqual(report["games"], {})
        self.assertFalse(report["pipeline_dir_exists"])

    def test_empty_pipeline_dir_returns_empty_summary(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            (tmp_root / "pack_pipeline").mkdir()
            with self._patch_state_root(tmp_root):
                report = self.build()
        self.assertEqual(report["summary"]["total_ledgers"], 0)
        self.assertEqual(report["games"], {})
        self.assertTrue(report["pipeline_dir_exists"])

    # ------------------------------------------------------------------ #
    # Single game, multiple packs, mixed status
    # ------------------------------------------------------------------ #

    def test_aggregates_by_status_per_game(self) -> None:
        layout = {
            "primitive_tech": {
                "PACK_01": {"status": "completed", "current_state": "packeted"},
                "PACK_02": {"status": "completed", "current_state": "packeted"},
                "PACK_03": {"status": "failed", "current_state": "failed"},
                "PACK_04": {"status": "pending", "current_state": "awaiting_cleanup_artifacts"},
            },
        }
        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            self._seed_ledgers(tmp_root, layout)
            with self._patch_state_root(tmp_root):
                report = self.build()

        self.assertEqual(report["summary"]["total_ledgers"], 4)
        self.assertEqual(report["summary"]["by_status"]["completed"], 2)
        self.assertEqual(report["summary"]["by_status"]["failed"], 1)
        self.assertEqual(report["summary"]["by_status"]["pending"], 1)
        pt = report["games"]["primitive_tech"]
        self.assertEqual(pt["total"], 4)
        self.assertEqual(pt["by_status"]["completed"], 2)

    # ------------------------------------------------------------------ #
    # Multiple games
    # ------------------------------------------------------------------ #

    def test_multiple_games_aggregated_separately(self) -> None:
        layout = {
            "primitive_tech": {
                "PT_01": {"status": "completed"},
                "PT_02": {"status": "failed"},
            },
            "roman_arena": {
                "RA_01": {"status": "completed"},
                "RA_02": {"status": "completed"},
                "RA_03": {"status": "pending"},
            },
        }
        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            self._seed_ledgers(tmp_root, layout)
            with self._patch_state_root(tmp_root):
                report = self.build()

        self.assertEqual(report["summary"]["total_ledgers"], 5)
        self.assertIn("primitive_tech", report["games"])
        self.assertIn("roman_arena", report["games"])
        self.assertEqual(report["games"]["primitive_tech"]["total"], 2)
        self.assertEqual(report["games"]["roman_arena"]["total"], 3)

    # ------------------------------------------------------------------ #
    # Broken ledger tolerance
    # ------------------------------------------------------------------ #

    def test_broken_ledger_counted_as_unreadable(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            pipeline_dir = tmp_root / "pack_pipeline" / "sandbox"
            pipeline_dir.mkdir(parents=True, exist_ok=True)
            # Valid ledger
            (pipeline_dir / "VALID.json").write_text(
                json.dumps({"status": "completed"}), encoding="utf-8"
            )
            # Malformed JSON
            (pipeline_dir / "BROKEN.json").write_text("{not valid json", encoding="utf-8")
            with self._patch_state_root(tmp_root):
                report = self.build()

        self.assertEqual(report["summary"]["total_ledgers"], 2)
        self.assertEqual(report["summary"]["by_status"]["completed"], 1)
        self.assertEqual(report["summary"]["by_status"].get("unreadable_json"), 1)

    # ------------------------------------------------------------------ #
    # include_ledgers + max_ledgers
    # ------------------------------------------------------------------ #

    def test_include_ledgers_returns_per_pack_summaries(self) -> None:
        layout = {
            "sandbox": {
                "PACK_X": {
                    "status": "completed",
                    "current_state": "packeted",
                    "updated_at_utc": "2026-05-11T00:00:00Z",
                },
            },
        }
        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            self._seed_ledgers(tmp_root, layout)
            with self._patch_state_root(tmp_root):
                report = self.build(include_ledgers=True)

        self.assertEqual(len(report["ledgers"]), 1)
        entry = report["ledgers"][0]
        self.assertEqual(entry["pack_id"], "PACK_X")
        self.assertEqual(entry["game_scope"], "sandbox")
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(entry["current_state"], "packeted")

    def test_no_ledgers_omits_per_pack_list(self) -> None:
        layout = {"sandbox": {"X": {"status": "completed"}}}
        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            self._seed_ledgers(tmp_root, layout)
            with self._patch_state_root(tmp_root):
                report = self.build(include_ledgers=False)
        self.assertIsNone(report["ledgers"])

    def test_max_ledgers_caps_response(self) -> None:
        # Seed 5 ledgers; cap at 2
        layout = {
            "sandbox": {
                f"PACK_{i:02d}": {"status": "completed"} for i in range(5)
            },
        }
        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            self._seed_ledgers(tmp_root, layout)
            with self._patch_state_root(tmp_root):
                report = self.build(include_ledgers=True, max_ledgers=2)
        # Summary still counts all 5
        self.assertEqual(report["summary"]["total_ledgers"], 5)
        # But ledgers list is capped at 2
        self.assertEqual(len(report["ledgers"]), 2)


class PackAuditCliTests(unittest.TestCase):
    """Smoke-test the `pack audit` Typer command (via CliRunner)."""

    def setUp(self) -> None:
        from assetboy.cli.app import app
        from typer.testing import CliRunner
        self.app = app
        self.runner = CliRunner()

    def test_audit_command_runs_without_crash(self) -> None:
        result = self.runner.invoke(self.app, ["pack", "audit", "--json"])
        # exit 0 even when state/pack_pipeline doesn't exist (empty report)
        self.assertEqual(result.exit_code, 0, f"stdout: {result.stdout[:200]}")
        parsed = json.loads(result.stdout)
        self.assertIn("summary", parsed)
        self.assertIn("games", parsed)
        self.assertIn("pipeline_dir", parsed)

    def test_audit_command_human_output(self) -> None:
        result = self.runner.invoke(self.app, ["pack", "audit"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("pack_audit_total_ledgers=", result.stdout)
        self.assertIn("pack_audit_game_count=", result.stdout)


if __name__ == "__main__":
    unittest.main()
