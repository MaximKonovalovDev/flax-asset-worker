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

    # ----------------------------------------------------------------- #
    # pack from-recipe: v1.6.s1 inline-yaml + stdin modes
    # ----------------------------------------------------------------- #

    INLINE_RECIPE = (
        "recipe:\n"
        "  id: inline_test\n"
        "  game: sandbox\n"
        "packs:\n"
        "  - id: INLINE_PACK_01\n"
        "    provider: polyhaven\n"
        "    acquisition_method: direct_url\n"
        "    assets:\n"
        "      - asset_id: test_asset\n"
    )

    def test_pack_from_recipe_inline_yaml_accepts_string(self) -> None:
        """v1.6.s1: --inline-yaml lets the facade send recipe content directly."""
        result = self.runner.invoke(
            self.app,
            ["pack", "from-recipe", "--inline-yaml", self.INLINE_RECIPE, "--dry-run", "--json"],
        )
        # In dry-run, the pack will fail at pack_pipeline level (no real source_dir)
        # but the CLI should accept the inline YAML cleanly and return JSON.
        import json
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nstdout: {result.stdout[:300]}")
        self.assertEqual(parsed["recipe_id"], "inline_test")
        self.assertEqual(parsed["game"], "sandbox")
        self.assertEqual(parsed["total_packs"], 1)

    def test_pack_from_recipe_no_source_errors_cleanly(self) -> None:
        """Missing both path and --inline-yaml -> clean error, not crash."""
        result = self.runner.invoke(
            self.app,
            ["pack", "from-recipe", "--json"],
        )
        # Empty string positional + no inline-yaml = missing source
        self.assertEqual(result.exit_code, 1)
        import json
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            # accept that some Typer versions exit before JSON output;
            # the important thing is non-zero exit
            return
        self.assertIn("missing_recipe_source", parsed.get("error", ""))

    def test_pack_from_recipe_inline_yaml_malformed_errors_cleanly(self) -> None:
        """Malformed inline YAML -> clean error, not crash."""
        result = self.runner.invoke(
            self.app,
            ["pack", "from-recipe", "--inline-yaml", "not: valid: yaml: shape:", "--json"],
        )
        self.assertEqual(result.exit_code, 1)
        import json
        try:
            parsed = json.loads(result.stdout)
            self.assertIn("inline_yaml_parse_failed", parsed.get("error", ""))
        except json.JSONDecodeError:
            # Non-zero exit alone is the key contract
            pass

    def test_pack_from_recipe_inline_yaml_non_dict_root_errors(self) -> None:
        """Inline YAML that parses to a list (not dict) -> clean error."""
        result = self.runner.invoke(
            self.app,
            ["pack", "from-recipe", "--inline-yaml", "- foo\n- bar\n", "--json"],
        )
        self.assertEqual(result.exit_code, 1)

    # ----------------------------------------------------------------- #
    # library asset (v1.6.s2)
    # ----------------------------------------------------------------- #

    def test_library_asset_command_exists(self) -> None:
        """v1.6.s2: library asset <id> command is wired into the library sub-app."""
        result = self.runner.invoke(self.app, ["library", "asset", "--help"])
        self.assertEqual(result.exit_code, 0)
        # The command should describe what it does
        self.assertIn("Fetch", result.stdout)
        self.assertIn("asset", result.stdout.lower())

    def test_library_readiness_help_renders(self) -> None:
        """v1.7.s13: library readiness --help works."""
        result = self.runner.invoke(self.app, ["library", "readiness", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("readiness", result.stdout.lower())

    def test_library_readiness_runs_without_crash(self) -> None:
        """v1.7.s13: library readiness exits cleanly + emits expected fields."""
        result = self.runner.invoke(self.app, ["library", "readiness"])
        self.assertEqual(result.exit_code, 0)
        # Should emit summary counts
        self.assertIn("library_readiness_total=", result.stdout)
        self.assertIn("library_readiness_ready_now=", result.stdout)
        self.assertIn("library_readiness_setup_required=", result.stdout)

    def test_library_readiness_json_mode(self) -> None:
        """v1.7.s13: --json emits parseable structured output."""
        result = self.runner.invoke(self.app, ["library", "readiness", "--json"])
        self.assertEqual(result.exit_code, 0)
        import json
        parsed = json.loads(result.stdout)
        self.assertIn("summary", parsed)
        self.assertIn("providers", parsed)
        self.assertIsInstance(parsed["providers"], list)

    def test_library_asset_when_server_down_exits_clean(self) -> None:
        """When FAW server isn't running, library asset must exit cleanly (not crash)."""
        result = self.runner.invoke(
            self.app,
            ["library", "asset", "NONEXISTENT_ID", "--server", "http://localhost:1"],
        )
        # Exit code 1 expected (server unreachable)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("library_asset_ok=false", result.stdout)

    # ----------------------------------------------------------------- #
    # pack run-pack (v1.6.s6)
    # ----------------------------------------------------------------- #

    INLINE_PACK = (
        "id: TEST_PACK_S6\n"
        "provider: polyhaven\n"
        "acquisition_method: direct_url\n"
        "assets:\n"
        "  - asset_id: brick_wall_04\n"
    )

    def test_run_pack_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["pack", "run-pack", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("single pack", result.stdout.lower())

    def test_run_pack_inline_accepts_pack_yaml(self) -> None:
        """v1.6.s6: --pack '<yaml>' runs one pack through pack_pipeline."""
        result = self.runner.invoke(
            self.app,
            [
                "pack", "run-pack",
                "--pack", self.INLINE_PACK,
                "--game", "sandbox",
                "--dry-run",
                "--json",
            ],
        )
        # Pack will land "failed" (dry-run with synthetic source_dir) or
        # "pending_manual_drop"; either way the CLI itself should produce
        # valid JSON ledger.
        import json
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            self.fail(f"stdout not valid JSON: {e}\nstdout: {result.stdout[:300]}")
        self.assertEqual(parsed.get("pack_id"), "TEST_PACK_S6")
        self.assertIn("status", parsed)
        self.assertIn("current_state", parsed)

    def test_run_pack_no_source_errors_cleanly(self) -> None:
        result = self.runner.invoke(self.app, ["pack", "run-pack"])
        self.assertEqual(result.exit_code, 1)
        self.assertIn("missing_pack_source", result.stdout)

    def test_run_pack_both_sources_errors_cleanly(self) -> None:
        result = self.runner.invoke(
            self.app,
            ["pack", "run-pack", "--pack", "id: X", "--pack-from-stdin"],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("conflicting_source", result.stdout)

    def test_run_pack_missing_id_errors_cleanly(self) -> None:
        result = self.runner.invoke(
            self.app,
            ["pack", "run-pack", "--pack", "provider: polyhaven\nassets: []", "--json"],
        )
        self.assertEqual(result.exit_code, 1)
        import json
        try:
            parsed = json.loads(result.stdout)
            self.assertIn("pack_missing_id", parsed.get("error", ""))
        except json.JSONDecodeError:
            # CLI emits human-mode on missing-id; accept that too
            self.assertIn("pack_missing_id", result.stdout)

    def test_run_pack_malformed_yaml_errors_cleanly(self) -> None:
        result = self.runner.invoke(
            self.app,
            ["pack", "run-pack", "--pack", "not: valid: yaml: structure:"],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("pack_yaml_parse_failed", result.stdout)

    def test_run_pack_non_dict_root_errors_cleanly(self) -> None:
        result = self.runner.invoke(
            self.app,
            ["pack", "run-pack", "--pack", "- one\n- two\n"],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("pack_must_be_a_mapping", result.stdout)

    # ----------------------------------------------------------------- #
    # gen status-all (v1.8.s18)
    # ----------------------------------------------------------------- #

    def test_gen_status_all_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "status-all", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("all 3 generator providers", result.stdout)

    def test_gen_status_all_runs_without_crash(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "status-all"])
        # exit 0 (at least one available) OR 1 (none available); both are non-crash
        self.assertIn(result.exit_code, (0, 1))
        self.assertIn("gen_status_all_any_available=", result.stdout)
        # All 3 generator providers should appear
        for prov in ("comfyui", "local_image", "stable_audio_open_small"):
            self.assertIn(prov, result.stdout)

    def test_gen_status_all_json_mode(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "status-all", "--json"])
        self.assertIn(result.exit_code, (0, 1))
        import json
        parsed = json.loads(result.stdout)
        self.assertIn("generators", parsed)
        self.assertIn("any_available", parsed)
        self.assertEqual(len(parsed["generators"]), 3)
        for entry in parsed["generators"]:
            self.assertIn("provider", entry)
            self.assertIn("available", entry)
            self.assertIn("notes", entry)


if __name__ == "__main__":
    unittest.main()
