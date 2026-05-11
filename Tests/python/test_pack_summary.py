"""Tests for assetboy.workflows.pack_summary (Path B v1.8.s17)."""

from __future__ import annotations

import unittest

from assetboy.workflows.pack_summary import render_pack_summary


class RenderPackSummaryTests(unittest.TestCase):
    """Verify the markdown report shape + content."""

    def test_empty_recipe_still_renders(self) -> None:
        md = render_pack_summary({})
        self.assertIn("# Pack Summary", md)
        self.assertIn("<unknown>", md)

    def test_recipe_id_and_game_appear_in_output(self) -> None:
        doc = {
            "recipe": {"id": "test_recipe", "game": "sandbox"},
            "packs": [],
        }
        md = render_pack_summary(doc, fetch_ledger=lambda *a, **kw: None)
        self.assertIn("test_recipe", md)
        self.assertIn("sandbox", md)

    def test_pack_table_includes_each_pack(self) -> None:
        doc = {
            "recipe": {"id": "x", "game": "test"},
            "packs": [
                {"id": "A", "provider": "polyhaven", "acquisition_method": "direct_url"},
                {"id": "B", "provider": "fab", "acquisition_method": "manual_browser"},
            ],
        }
        md = render_pack_summary(doc, fetch_ledger=lambda *a, **kw: None)
        self.assertIn("`A`", md)
        self.assertIn("`B`", md)
        self.assertIn("`polyhaven`", md)
        self.assertIn("`fab`", md)
        self.assertIn("## Per-pack status", md)

    def test_completed_status_shows_OK_marker(self) -> None:
        doc = {
            "recipe": {"id": "x", "game": "test"},
            "packs": [{"id": "A", "provider": "polyhaven"}],
        }

        def fake_fetch(pack_id, game_scope):
            return {"exists": True, "status": "completed", "current_state": "packeted"}

        md = render_pack_summary(doc, fetch_ledger=fake_fetch)
        # Status counts section
        self.assertIn("| completed | 1 |", md)
        # Per-pack table has OK marker
        self.assertIn("OK", md)

    def test_failed_status_shows_RED_marker_and_error_section(self) -> None:
        doc = {
            "recipe": {"id": "x", "game": "test"},
            "packs": [{"id": "A", "provider": "polyhaven", "acquisition_method": "direct_url"}],
        }

        def fake_fetch(pack_id, game_scope):
            return {
                "exists": True,
                "status": "failed",
                "current_state": "failed",
                "error": "download_timeout",
            }

        md = render_pack_summary(doc, fetch_ledger=fake_fetch)
        self.assertIn("RED", md)
        self.assertIn("## Failed packs", md)
        self.assertIn("download_timeout", md)

    def test_pending_manual_drop_shows_WAIT_and_manual_section(self) -> None:
        doc = {
            "recipe": {"id": "x", "game": "test"},
            "packs": [{"id": "A", "provider": "fab", "acquisition_method": "manual_browser"}],
        }

        def fake_fetch(pack_id, game_scope):
            return {
                "exists": True,
                "status": "pending_manual_drop",
                "current_state": "awaiting_manual_browser_drop",
                "drop_dir": "C:/some/path",
                "next_step": "drop your files into C:/some/path then re-run",
            }

        md = render_pack_summary(doc, fetch_ledger=fake_fetch)
        self.assertIn("WAIT", md)
        self.assertIn("## Manual drops required", md)
        self.assertIn("C:/some/path", md)

    def test_not_run_status_when_no_ledger(self) -> None:
        doc = {
            "recipe": {"id": "x", "game": "test"},
            "packs": [{"id": "A", "provider": "polyhaven"}],
        }
        # Ledger fetch returns None
        md = render_pack_summary(doc, fetch_ledger=lambda *a, **kw: None)
        self.assertIn("not_run", md)
        self.assertIn("never run", md)

    def test_recommended_actions_section_appears_when_work_remains(self) -> None:
        doc = {
            "recipe": {"id": "x", "game": "test"},
            "packs": [
                {"id": "A", "provider": "polyhaven"},
                {"id": "B", "provider": "fab", "acquisition_method": "manual_browser"},
            ],
        }
        states = {
            "A": {"exists": True, "status": "failed", "error": "x"},
            "B": {"exists": True, "status": "pending_manual_drop", "drop_dir": "/tmp"},
        }

        def fake_fetch(pack_id, game_scope):
            return states[pack_id]

        md = render_pack_summary(doc, fetch_ledger=fake_fetch)
        self.assertIn("## Recommended next actions", md)
        self.assertIn("pack rerun-failed", md)


class CliExportSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        from assetboy.cli.app import app
        from typer.testing import CliRunner
        self.app = app
        self.runner = CliRunner()

    def test_export_summary_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["pack", "export-summary", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("markdown summary", result.stdout)

    def test_export_summary_sandbox_recipe_to_stdout(self) -> None:
        """Smoke: render summary for a real shipped recipe; verify shape."""
        result = self.runner.invoke(
            self.app, ["pack", "export-summary", "sandbox/one_pack_smoke.yaml"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("# Pack Summary", result.stdout)
        self.assertIn("sandbox_one_pack_smoke", result.stdout)
        self.assertIn("SANDBOX_POLY_TEX_BRICK_WALL_01", result.stdout)

    def test_export_summary_missing_recipe_errors(self) -> None:
        result = self.runner.invoke(
            self.app, ["pack", "export-summary", "does_not_exist.yaml"]
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("recipe_not_found", result.stdout)


if __name__ == "__main__":
    unittest.main()
