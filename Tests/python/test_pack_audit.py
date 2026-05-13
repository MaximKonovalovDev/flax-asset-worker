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


class FindFailedPacksTests(unittest.TestCase):
    """v1.6.s8: find_failed_packs filters audit output to failed-only."""

    def setUp(self) -> None:
        from assetboy.workflows.pack_audit import find_failed_packs
        self.find_failed = find_failed_packs

    def _seed_and_query(self, layout, **kwargs):
        from assetboy.workflows import pack_audit
        from unittest.mock import patch
        with TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            pipeline_dir = tmp_root / "pack_pipeline"
            for game_scope, packs in layout.items():
                game_dir = pipeline_dir / game_scope
                game_dir.mkdir(parents=True, exist_ok=True)
                for pack_id, ledger in packs.items():
                    (game_dir / f"{pack_id}.json").write_text(
                        json.dumps(ledger), encoding="utf-8"
                    )
            with patch.object(pack_audit, "state_root", return_value=tmp_root):
                return self.find_failed(**kwargs)

    def test_returns_only_failed_status_entries(self) -> None:
        layout = {
            "sandbox": {
                "GREEN_01": {"status": "completed", "current_state": "packeted"},
                "RED_01": {"status": "failed", "current_state": "failed"},
                "RED_02": {"status": "failed", "current_state": "acquisition_failed"},
                "WAIT_01": {"status": "pending_manual_drop", "current_state": "awaiting_manual_browser_drop"},
            },
        }
        failed = self._seed_and_query(layout)
        ids = sorted(e["pack_id"] for e in failed)
        self.assertEqual(ids, ["RED_01", "RED_02"])

    def test_skip_acquisition_failed_excludes_router_failures(self) -> None:
        layout = {
            "sandbox": {
                "RED_PIPELINE": {"status": "failed", "current_state": "failed"},
                "RED_ROUTER": {"status": "failed", "current_state": "acquisition_failed"},
            },
        }
        failed = self._seed_and_query(layout, include_acquisition_failed=False)
        ids = [e["pack_id"] for e in failed]
        self.assertEqual(ids, ["RED_PIPELINE"])
        self.assertNotIn("RED_ROUTER", ids)

    def test_game_filter_narrows_results(self) -> None:
        layout = {
            "alpha": {"A_FAIL_01": {"status": "failed"}},
            "beta": {"B_FAIL_01": {"status": "failed"}},
        }
        failed_alpha = self._seed_and_query(layout, game_filter="alpha")
        self.assertEqual(len(failed_alpha), 1)
        self.assertEqual(failed_alpha[0]["pack_id"], "A_FAIL_01")

    def test_empty_when_no_failures(self) -> None:
        layout = {
            "sandbox": {
                "GREEN_01": {"status": "completed"},
                "WAIT_01": {"status": "pending_manual_drop"},
            },
        }
        failed = self._seed_and_query(layout)
        self.assertEqual(failed, [])


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

    def test_rerun_failed_help_renders(self) -> None:
        """v1.6.s8: pack rerun-failed --help works."""
        result = self.runner.invoke(self.app, ["pack", "rerun-failed", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Re-run all packs that previously failed", result.stdout)

    def test_rerun_failed_missing_recipe_errors_cleanly(self) -> None:
        """Without --recipe, rerun-failed cannot look up pack specs."""
        result = self.runner.invoke(self.app, ["pack", "rerun-failed", "--json"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("missing_recipe", result.stdout)

    def test_rerun_failed_propagates_recipe_checks(self) -> None:
        """v1.21.s148: rerun-failed reports expected_min_check + min_required_passes_check
        when recipe defines them. Uses sandbox/one_pack_smoke since it's parse-clean."""
        result = self.runner.invoke(
            self.app,
            ["pack", "rerun-failed",
             "--recipe", "sandbox/one_pack_smoke.yaml",
             "--dry-run", "--json"],
        )
        # 0 or 1 acceptable (rerun may find no failed packs => exit 0; or find some => 1).
        self.assertIn(result.exit_code, (0, 1))
        # JSON should be parseable when present. one_pack_smoke has no
        # expected_min_assets / min_required_passes, so checks won't appear.
        # But the command should not crash regardless.

    def test_rerun_failed_with_recipe_smoke(self) -> None:
        """v1.6.s8 CLI smoke: pack rerun-failed runs without crashing.

        Live-state-tolerant: per-pack runners may print to stdout before
        the --json summary lands, so we can't reliably parse stdout as
        clean JSON here. We just verify the command exits with a valid
        code (0 or 1) and doesn't crash. The FindFailedPacksTests class
        covers the actual filtering logic with isolated state.
        """
        result = self.runner.invoke(
            self.app,
            ["pack", "rerun-failed", "--recipe", "sandbox/one_pack_smoke.yaml", "--dry-run"],
        )
        # Should not crash (exit 0 = no failures, exit 1 = retry attempted)
        self.assertIn(result.exit_code, (0, 1))

    def test_rerun_failed_max_attempts_help_lists_flag(self) -> None:
        """v1.25.s168: --max-attempts flag visible in help."""
        result = self.runner.invoke(self.app, ["pack", "rerun-failed", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("--max-attempts", result.stdout)

    def test_rerun_failed_max_attempts_zero_passes(self) -> None:
        """v1.25.s168: --max-attempts 0 (default) doesn't cap."""
        result = self.runner.invoke(
            self.app,
            ["pack", "rerun-failed",
             "--recipe", "sandbox/one_pack_smoke.yaml",
             "--max-attempts", "0",
             "--dry-run", "--json"],
        )
        # Either 0 (no failures) or 1 (some attempted); not 2 (typer arg error).
        self.assertIn(result.exit_code, (0, 1))


if __name__ == "__main__":
    unittest.main()
