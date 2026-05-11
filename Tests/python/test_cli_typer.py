"""Smoke tests for the Typer CLI surface (Path B s5/s6/s8).

Verifies the 7 sub-apps + 25 commands all render --help cleanly without
Rich/cp1252 crashes (the s5 unicode-sweep gate) and that the root app
routes to each sub-app.
"""

from __future__ import annotations

import unittest

from typer.testing import CliRunner


class TyperCliSmokeTests(unittest.TestCase):
    """Path B v1.3.1 regression catchers for the Typer CLI."""

    def setUp(self) -> None:
        from assetboy.cli.app import app
        self.app = app
        self.runner = CliRunner()

    # ----------------------------------------------------------------- #
    # Root help renders 7 sub-apps
    # ----------------------------------------------------------------- #

    def test_root_help_shows_all_seven_sub_apps(self) -> None:
        result = self.runner.invoke(self.app, ["--help"])
        self.assertEqual(result.exit_code, 0)
        for sub_app in ("fab", "library", "import", "unity", "epic", "gen", "pack"):
            self.assertIn(sub_app, result.stdout, f"sub-app {sub_app!r} missing from root help")

    # ----------------------------------------------------------------- #
    # Each sub-app's help renders cleanly
    # ----------------------------------------------------------------- #

    def test_fab_sub_app_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["fab", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ("auth", "auth-status", "download", "library"):
            self.assertIn(cmd, result.stdout)

    def test_library_sub_app_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["library", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ("search", "install", "ready", "audit"):
            self.assertIn(cmd, result.stdout)

    def test_import_sub_app_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["import", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ("file", "watch"):
            self.assertIn(cmd, result.stdout)

    def test_unity_sub_app_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["unity", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ("status", "list-installs", "owned", "download"):
            self.assertIn(cmd, result.stdout)

    def test_epic_sub_app_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["epic", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ("status", "inventory", "catalog"):
            self.assertIn(cmd, result.stdout)

    def test_gen_sub_app_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ("comfyui", "sd", "list-presets"):
            self.assertIn(cmd, result.stdout)

    def test_pack_sub_app_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["pack", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ("list-recipes", "from-recipe", "status"):
            self.assertIn(cmd, result.stdout)

    # ----------------------------------------------------------------- #
    # Nested sub-app under gen (comfyui + sd are themselves sub-apps)
    # ----------------------------------------------------------------- #

    def test_gen_comfyui_nested_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "comfyui", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ("status", "run"):
            self.assertIn(cmd, result.stdout)

    def test_gen_sd_nested_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "sd", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("run", result.stdout)

    # ----------------------------------------------------------------- #
    # Sample real call: pack list-recipes (no network)
    # ----------------------------------------------------------------- #

    def test_pack_list_recipes_runs_without_crash(self) -> None:
        """Verify the YAML loader + recipe enumeration work end-to-end."""
        result = self.runner.invoke(self.app, ["pack", "list-recipes"])
        # Exit 0 if recipes/ exists (it should in this repo)
        self.assertEqual(result.exit_code, 0, f"stdout: {result.stdout}")
        # Should mention at least primitive_tech or roman_arena
        self.assertTrue(
            "primitive_tech" in result.stdout or "roman_arena" in result.stdout,
            f"expected recipe references in stdout, got: {result.stdout[:200]}",
        )

    # ----------------------------------------------------------------- #
    # Sample real call: fab auth-status (no network; reads disk only)
    # ----------------------------------------------------------------- #

    def test_fab_auth_status_runs_without_crash(self) -> None:
        result = self.runner.invoke(self.app, ["fab", "auth-status"])
        # Exit 0 if authed, 1 if not authed -- both are non-crash.
        self.assertIn(result.exit_code, (0, 1))
        # Should emit fab_auth_state_* lines
        self.assertIn("fab_auth_state_path=", result.stdout)

    # ----------------------------------------------------------------- #
    # gen list-presets (v1.5.5: --provider filter)
    # ----------------------------------------------------------------- #

    def test_gen_list_presets_default_shows_all_three_providers(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "list-presets"])
        self.assertEqual(result.exit_code, 0)
        # All 3 generator providers should appear in default output
        self.assertIn("gen_comfyui_preset_count=", result.stdout)
        self.assertIn("gen_local_image_preset_count=", result.stdout)
        self.assertIn("gen_stable_audio_preset_count=", result.stdout)

    def test_gen_list_presets_provider_filter_stable_audio(self) -> None:
        result = self.runner.invoke(
            self.app, ["gen", "list-presets", "--provider", "stable_audio"]
        )
        self.assertEqual(result.exit_code, 0)
        # Should show only stable_audio
        self.assertIn("gen_stable_audio_preset_count=", result.stdout)
        self.assertNotIn("gen_comfyui_preset_count=", result.stdout)
        self.assertNotIn("gen_local_image_preset_count=", result.stdout)

    def test_gen_list_presets_provider_filter_comfyui_resolves_ids(self) -> None:
        """v1.5.5 fix: ComfyUI preset dicts use pack_id, not id; previously
        showed 'name=?' for all. Verify the fix actually resolves names."""
        result = self.runner.invoke(
            self.app, ["gen", "list-presets", "--provider", "comfyui"]
        )
        self.assertEqual(result.exit_code, 0)
        # Should NOT contain "id=?" or "name=?" (the v1.5.5 fix)
        self.assertNotIn("id=?", result.stdout)
        self.assertNotIn("name=?", result.stdout)
        # Should contain at least one real preset id
        self.assertIn("SHARED_MAT_", result.stdout)

    def test_gen_list_presets_json_mode(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "list-presets", "--json"])
        self.assertEqual(result.exit_code, 0)
        import json
        parsed = json.loads(result.stdout)
        for key in (
            "comfyui_material_presets",
            "local_image_ui_prompts",
            "stable_audio_presets",
        ):
            self.assertIn(key, parsed)


if __name__ == "__main__":
    unittest.main()
