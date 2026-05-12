"""Smoke tests for the Typer CLI surface (Path B s5/s6/s8).

Verifies the 7 sub-apps + 25 commands all render --help cleanly without
Rich/cp1252 crashes (the s5 unicode-sweep gate) and that the root app
routes to each sub-app.
"""

from __future__ import annotations

import unittest
from pathlib import Path

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
    # pack list-recipes --filter (v1.11.s53)
    # ----------------------------------------------------------------- #

    def test_pack_list_recipes_filter_by_tags(self) -> None:
        """v1.11.s53: --filter tags:smoke-test should match r1a_smoke only."""
        result = self.runner.invoke(
            self.app, ["pack", "list-recipes", "--filter", "tags:smoke-test"],
        )
        self.assertEqual(result.exit_code, 0, f"stdout: {result.stdout}")
        self.assertIn("r1a_smoke", result.stdout)
        # Should NOT include primitive_tech or roman (they have no smoke-test tag)
        self.assertNotIn("primitive_tech", result.stdout)
        self.assertNotIn("roman_arena", result.stdout)

    def test_pack_list_recipes_filter_by_genre(self) -> None:
        """--filter genre:reference_collection -> only r1a_smoke."""
        result = self.runner.invoke(
            self.app,
            ["pack", "list-recipes", "--filter", "genre:reference_collection"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("r1a_smoke", result.stdout)

    def test_pack_list_recipes_multiple_filters_and(self) -> None:
        """Multiple --filter values AND together; both must match."""
        result = self.runner.invoke(
            self.app,
            [
                "pack", "list-recipes",
                "--filter", "genre:reference_collection",
                "--filter", "theme:fantasy",
            ],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("r1a_smoke", result.stdout)

    def test_pack_list_recipes_filter_no_match_returns_zero_count(self) -> None:
        result = self.runner.invoke(
            self.app,
            ["pack", "list-recipes", "--filter", "genre:nonexistent_genre_XYZ"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("pack_list_recipes_count=0", result.stdout)

    def test_pack_list_recipes_filter_bad_shape_errors(self) -> None:
        """--filter 'malformed' (no colon) -> clean error."""
        result = self.runner.invoke(
            self.app, ["pack", "list-recipes", "--filter", "malformed_no_colon"],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("bad_filter_shape", result.stdout)

    def test_pack_list_recipes_json_with_filter_round_trip(self) -> None:
        """v1.11.s57: --json + --filter combo emits filtered list + filters_applied."""
        result = self.runner.invoke(
            self.app,
            ["pack", "list-recipes", "--filter", "genre:survival", "--json"],
        )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout)
        self.assertIn("filters_applied", data)
        self.assertEqual(data["filters_applied"], ["genre:survival"])
        # Should match exactly primitive_tech (sole survival-genre recipe).
        self.assertEqual(data["count"], 1)
        self.assertIn("primitive_tech", data["recipes"][0]["path"])
        self.assertEqual(data["recipes"][0]["genre"], "survival")

    def test_pack_list_recipes_json_includes_metadata(self) -> None:
        """JSON output for r1a_smoke must include genre/theme/style/tags."""
        result = self.runner.invoke(
            self.app, ["pack", "list-recipes", "--json"],
        )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout)
        r1a = [r for r in data["recipes"] if "r1a_smoke" in r["path"]]
        self.assertEqual(len(r1a), 1)
        entry = r1a[0]
        self.assertEqual(entry["genre"], "reference_collection")
        self.assertIn("historical", entry["theme"])
        self.assertIn("smoke-test", entry["tags"])

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
    # pack from-recipe --only filter (v1.9.s21)
    # ----------------------------------------------------------------- #

    ONLY_FILTER_RECIPE = (
        "recipe:\n"
        "  id: only_filter_test\n"
        "  game: sandbox\n"
        "packs:\n"
        "  - id: PACK_A\n"
        "    provider: polyhaven\n"
        "    acquisition_method: direct_url\n"
        "    assets:\n"
        "      - asset_id: a\n"
        "  - id: PACK_B\n"
        "    provider: kenney\n"
        "    acquisition_method: direct_url\n"
        "    assets:\n"
        "      - asset_id: b\n"
        "  - id: PACK_C\n"
        "    provider: ambientcg\n"
        "    acquisition_method: direct_url\n"
        "    assets:\n"
        "      - asset_id: c\n"
    )

    # ----------------------------------------------------------------- #
    # gen comfyui submit-workflow (v1.9.s25)
    # ----------------------------------------------------------------- #

    # ----------------------------------------------------------------- #
    # gen met-museum fetch (v1.10.s26)
    # ----------------------------------------------------------------- #

    def test_met_museum_fetch_help_renders(self) -> None:
        result = self.runner.invoke(
            self.app, ["gen", "met-museum", "fetch", "--help"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Met", result.stdout)
        self.assertIn("CC0", result.stdout)

    def test_met_museum_fetch_dry_run_no_matches_exits_zero(self) -> None:
        """Mock the runner to return an empty-match result; CLI should exit 0."""
        from unittest.mock import patch
        from assetboy.execution.met_museum_runner import MetMuseumResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = MetMuseumResult(
                pack_id="TEST", query="zzz", output_dir=Path(tmp),
                objects_matched=0, ok=True, error="no_matches",
            )
            with patch(
                "assetboy.execution.met_museum_runner.run_met_museum_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "met-museum", "fetch", "--query", "zzz", "--dry-run"],
                )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("gen_met_museum_matched=0", result.stdout)
        self.assertIn("no_matches", result.stdout)

    def test_met_museum_fetch_json_output_shape(self) -> None:
        """--json emits parseable JSON with expected keys."""
        from unittest.mock import patch
        from assetboy.execution.met_museum_runner import MetMuseumResult
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as tmp:
            fake = MetMuseumResult(
                pack_id="PACK", query="q", output_dir=Path(tmp),
                objects_matched=5, objects_public_domain=3,
                objects_downloaded=3, objects_skipped_non_pd=2, ok=True,
            )
            with patch(
                "assetboy.execution.met_museum_runner.run_met_museum_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "met-museum", "fetch", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        # Strip leading non-JSON noise if any; parse last JSON block.
        data = _json.loads(result.stdout.strip().split("\n", 0)[0] if False else result.stdout.strip())
        self.assertEqual(data["pack_id"], "PACK")
        self.assertEqual(data["objects_downloaded"], 3)
        self.assertEqual(data["objects_skipped_non_pd"], 2)
        self.assertTrue(data["ok"])

    # ----------------------------------------------------------------- #
    # gen wikimedia fetch (v1.10.s27)
    # ----------------------------------------------------------------- #

    def test_wikimedia_fetch_help_renders(self) -> None:
        result = self.runner.invoke(
            self.app, ["gen", "wikimedia", "fetch", "--help"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Wikimedia", result.stdout)
        self.assertIn("CC", result.stdout)

    def test_wikimedia_fetch_dry_run_no_matches_exits_zero(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.wikimedia_runner import WikimediaResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = WikimediaResult(
                pack_id="T", query="zzz", output_dir=Path(tmp),
                files_matched=0, ok=True, error="no_matches",
            )
            with patch(
                "assetboy.execution.wikimedia_runner.run_wikimedia_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "wikimedia", "fetch", "--query", "zzz", "--dry-run"],
                )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("gen_wikimedia_matched=0", result.stdout)
        self.assertIn("no_matches", result.stdout)

    def test_wikimedia_fetch_json_output_shape(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.wikimedia_runner import WikimediaResult
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as tmp:
            fake = WikimediaResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                files_matched=10, files_accepted_license=4,
                files_downloaded=4, files_skipped_restricted=6, ok=True,
            )
            with patch(
                "assetboy.execution.wikimedia_runner.run_wikimedia_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "wikimedia", "fetch", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["pack_id"], "P")
        self.assertEqual(data["files_downloaded"], 4)
        self.assertEqual(data["files_skipped_restricted"], 6)
        self.assertTrue(data["ok"])

    # ----------------------------------------------------------------- #
    # gen archive-org fetch (v1.10.s28)
    # ----------------------------------------------------------------- #

    def test_archive_org_fetch_help_renders(self) -> None:
        result = self.runner.invoke(
            self.app, ["gen", "archive-org", "fetch", "--help"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("archive.org", result.stdout.lower())
        self.assertIn("CC", result.stdout)

    def test_archive_org_fetch_dry_run_no_matches_exits_zero(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.archive_org_runner import ArchiveOrgResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = ArchiveOrgResult(
                pack_id="T", query="zzz", output_dir=Path(tmp),
                items_matched=0, ok=True, error="no_matches",
            )
            with patch(
                "assetboy.execution.archive_org_runner.run_archive_org_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "archive-org", "fetch", "--query", "zzz", "--dry-run"],
                )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("gen_archive_org_matched=0", result.stdout)
        self.assertIn("no_matches", result.stdout)

    def test_archive_org_fetch_json_output_shape(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.archive_org_runner import ArchiveOrgResult
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as tmp:
            fake = ArchiveOrgResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                items_matched=8, items_accepted_license=3,
                items_downloaded=3, items_skipped_restricted=5, ok=True,
            )
            with patch(
                "assetboy.execution.archive_org_runner.run_archive_org_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "archive-org", "fetch", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["pack_id"], "P")
        self.assertEqual(data["items_downloaded"], 3)
        self.assertEqual(data["items_skipped_restricted"], 5)
        self.assertTrue(data["ok"])

    # ----------------------------------------------------------------- #
    # gen scryfall fetch (v1.10.s29)
    # ----------------------------------------------------------------- #

    def test_scryfall_fetch_help_renders(self) -> None:
        result = self.runner.invoke(
            self.app, ["gen", "scryfall", "fetch", "--help"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Scryfall", result.stdout)
        self.assertIn("CC-BY-SA", result.stdout)

    def test_scryfall_fetch_dry_run_no_matches_exits_zero(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.scryfall_runner import ScryfallResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = ScryfallResult(
                pack_id="T", query="zzz", output_dir=Path(tmp),
                variant="art_crop", cards_matched=0, ok=True, error="no_matches",
            )
            with patch(
                "assetboy.execution.scryfall_runner.run_scryfall_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "scryfall", "fetch", "--query", "zzz", "--dry-run"],
                )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("gen_scryfall_matched=0", result.stdout)
        self.assertIn("no_matches", result.stdout)

    def test_scryfall_fetch_json_output_shape(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.scryfall_runner import ScryfallResult
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as tmp:
            fake = ScryfallResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                variant="png", cards_matched=4, cards_with_image=4,
                cards_downloaded=4, ok=True,
            )
            with patch(
                "assetboy.execution.scryfall_runner.run_scryfall_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "scryfall", "fetch", "--query", "q", "--variant", "png", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["pack_id"], "P")
        self.assertEqual(data["variant"], "png")
        self.assertEqual(data["cards_downloaded"], 4)
        self.assertTrue(data["ok"])

    # ----------------------------------------------------------------- #
    # gen iconify fetch (v1.10.s30)
    # ----------------------------------------------------------------- #

    def test_iconify_fetch_help_renders(self) -> None:
        result = self.runner.invoke(
            self.app, ["gen", "iconify", "fetch", "--help"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Iconify", result.stdout)
        self.assertIn("MIT", result.stdout)

    def test_iconify_fetch_dry_run_no_matches_exits_zero(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.iconify_runner import IconifyResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = IconifyResult(
                pack_id="T", query="zzz", output_dir=Path(tmp),
                icons_matched=0, ok=True, error="no_matches",
            )
            with patch(
                "assetboy.execution.iconify_runner.run_iconify_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "iconify", "fetch", "--query", "zzz", "--dry-run"],
                )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("gen_iconify_matched=0", result.stdout)
        self.assertIn("no_matches", result.stdout)

    def test_iconify_fetch_json_output_shape(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.iconify_runner import IconifyResult
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as tmp:
            fake = IconifyResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                icons_matched=30, icons_accepted_license=20,
                icons_downloaded=20, icons_skipped_restricted=10, ok=True,
            )
            with patch(
                "assetboy.execution.iconify_runner.run_iconify_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "iconify", "fetch", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["pack_id"], "P")
        self.assertEqual(data["icons_downloaded"], 20)
        self.assertEqual(data["icons_skipped_restricted"], 10)
        self.assertTrue(data["ok"])

    # ----------------------------------------------------------------- #
    # gen pexels photos / videos (v1.10.s31)
    # ----------------------------------------------------------------- #

    def test_pexels_photos_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "pexels", "photos", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Pexels", result.stdout)
        self.assertIn("PEXELS_API_KEY", result.stdout)

    def test_pexels_videos_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "pexels", "videos", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("video", result.stdout.lower())

    def test_pexels_photos_missing_api_key_exits_1(self) -> None:
        """Without PEXELS_API_KEY env, command exits with clean error."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PEXELS_API_KEY", None)
            result = self.runner.invoke(
                self.app, ["gen", "pexels", "photos", "--query", "x", "--dry-run"],
            )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("missing_api_key", result.stdout)

    def test_pexels_photos_json_output_shape(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.pexels_runner import PexelsResult
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as tmp:
            fake = PexelsResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                kind="photos", items_matched=3, items_downloaded=3, ok=True,
            )
            with patch(
                "assetboy.execution.pexels_runner.run_pexels_photo_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "pexels", "photos", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["kind"], "photos")
        self.assertEqual(data["items_downloaded"], 3)

    # ----------------------------------------------------------------- #
    # gen pixabay photos / videos (v1.10.s32)
    # ----------------------------------------------------------------- #

    def test_pixabay_photos_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "pixabay", "photos", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Pixabay", result.stdout)
        self.assertIn("PIXABAY_API_KEY", result.stdout)

    def test_pixabay_videos_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "pixabay", "videos", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("video", result.stdout.lower())

    def test_pixabay_photos_missing_api_key_exits_1(self) -> None:
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PIXABAY_API_KEY", None)
            result = self.runner.invoke(
                self.app, ["gen", "pixabay", "photos", "--query", "x", "--dry-run"],
            )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("missing_api_key", result.stdout)

    def test_pixabay_videos_json_output_shape(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.pixabay_runner import PixabayResult
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as tmp:
            fake = PixabayResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                kind="videos", items_matched=2, items_downloaded=2, ok=True,
            )
            with patch(
                "assetboy.execution.pixabay_runner.run_pixabay_video_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "pixabay", "videos", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["kind"], "videos")
        self.assertEqual(data["items_downloaded"], 2)

    # ----------------------------------------------------------------- #
    # gen rawg games (v1.10.s33)
    # ----------------------------------------------------------------- #

    def test_rawg_games_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "rawg", "games", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("RAWG", result.stdout)
        self.assertIn("REFERENCE", result.stdout)
        self.assertIn("RAWG_API_KEY", result.stdout)

    def test_rawg_games_missing_api_key_exits_1(self) -> None:
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RAWG_API_KEY", None)
            result = self.runner.invoke(
                self.app, ["gen", "rawg", "games", "--query", "x", "--dry-run"],
            )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("missing_api_key", result.stdout)

    def test_rawg_games_json_output_shape(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.rawg_runner import RawgResult
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as tmp:
            fake = RawgResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                games_matched=3, games_downloaded=3,
                screenshots_downloaded=9, ok=True,
            )
            with patch(
                "assetboy.execution.rawg_runner.run_rawg_games_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app, ["gen", "rawg", "games", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["games_downloaded"], 3)
        self.assertEqual(data["screenshots_downloaded"], 9)

    def test_rawg_games_stdout_shows_use_policy(self) -> None:
        """Plain-text output must include USE_POLICY banner so operator sees it."""
        from unittest.mock import patch
        from assetboy.execution.rawg_runner import RawgResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = RawgResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                games_matched=1, games_downloaded=1, ok=True,
            )
            with patch(
                "assetboy.execution.rawg_runner.run_rawg_games_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app, ["gen", "rawg", "games", "--query", "q"],
                )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("USE_POLICY", result.stdout)

    # ----------------------------------------------------------------- #
    # gen jamendo tracks (v1.10.s34)
    # ----------------------------------------------------------------- #

    def test_jamendo_tracks_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "jamendo", "tracks", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Jamendo", result.stdout)
        self.assertIn("CC", result.stdout)
        self.assertIn("JAMENDO_CLIENT_ID", result.stdout)

    def test_jamendo_tracks_missing_client_id_exits_1(self) -> None:
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("JAMENDO_CLIENT_ID", None)
            result = self.runner.invoke(
                self.app, ["gen", "jamendo", "tracks", "--query", "x", "--dry-run"],
            )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("missing_client_id", result.stdout)

    def test_jamendo_tracks_json_output_shape(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.jamendo_runner import JamendoResult
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as tmp:
            fake = JamendoResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                tracks_matched=5, tracks_accepted_license=3,
                tracks_downloaded=3, tracks_skipped_restricted=2, ok=True,
            )
            with patch(
                "assetboy.execution.jamendo_runner.run_jamendo_tracks_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app, ["gen", "jamendo", "tracks", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["tracks_downloaded"], 3)
        self.assertEqual(data["tracks_skipped_restricted"], 2)

    # ----------------------------------------------------------------- #
    # gen unsplash photos (v1.10.s35)
    # ----------------------------------------------------------------- #

    def test_unsplash_photos_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "unsplash", "photos", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Unsplash", result.stdout)
        self.assertIn("UNSPLASH_ACCESS_KEY", result.stdout)

    def test_unsplash_photos_missing_access_key_exits_1(self) -> None:
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UNSPLASH_ACCESS_KEY", None)
            result = self.runner.invoke(
                self.app, ["gen", "unsplash", "photos", "--query", "x", "--dry-run"],
            )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("missing_access_key", result.stdout)

    def test_unsplash_photos_json_output_shape(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.unsplash_runner import UnsplashResult
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as tmp:
            fake = UnsplashResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                photos_matched=4, photos_downloaded=4, download_pings=4, ok=True,
            )
            with patch(
                "assetboy.execution.unsplash_runner.run_unsplash_photo_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "unsplash", "photos", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["photos_downloaded"], 4)
        self.assertEqual(data["download_pings"], 4)

    # ----------------------------------------------------------------- #
    # gen inaturalist fetch (v1.13.s84)
    # ----------------------------------------------------------------- #

    def test_inaturalist_fetch_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "inaturalist", "fetch", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("iNaturalist", result.stdout)
        self.assertIn("CC", result.stdout)

    def test_inaturalist_fetch_dry_run_no_matches_exits_zero(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.inaturalist_runner import INaturalistResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = INaturalistResult(
                pack_id="T", query="zzz", output_dir=Path(tmp),
                observations_matched=0, ok=True, error="no_matches",
            )
            with patch(
                "assetboy.execution.inaturalist_runner.run_inaturalist_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "inaturalist", "fetch", "--query", "zzz", "--dry-run"],
                )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("gen_inaturalist_matched=0", result.stdout)
        self.assertIn("no_matches", result.stdout)

    def test_inaturalist_fetch_json_output_shape(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.inaturalist_runner import INaturalistResult
        import tempfile, json as _json

        with tempfile.TemporaryDirectory() as tmp:
            fake = INaturalistResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                observations_matched=10, observations_with_photo=6,
                photos_downloaded=6, photos_skipped_restricted=4, ok=True,
            )
            with patch(
                "assetboy.execution.inaturalist_runner.run_inaturalist_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "inaturalist", "fetch", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["photos_downloaded"], 6)
        self.assertEqual(data["photos_skipped_restricted"], 4)
        self.assertTrue(data["ok"])

    # ----------------------------------------------------------------- #
    # gen scout-by-license (v1.13.s94)
    # ----------------------------------------------------------------- #

    def test_scout_by_license_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "scout-by-license", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("license", result.stdout.lower())

    def test_scout_by_license_empty_token_exits_1(self) -> None:
        result = self.runner.invoke(
            self.app,
            ["gen", "scout-by-license", "--license", "  ", "--query", "x"],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("empty_license_token", result.stdout)

    def test_scout_by_license_cc0_matches_only_cc0_providers(self) -> None:
        """--license cc0 picks Met (CC0), Wikimedia (CC0/CC-BY/SA/PD), Pixabay (CC0-equivalent),
        iNaturalist (CC0/CC-BY/SA), archive-org (CC-BY/SA/CC0/PD); skips others.
        With env keys cleared, key-required providers report skipped."""
        import os
        from unittest.mock import patch
        from assetboy.execution.met_museum_runner import MetMuseumResult
        from assetboy.execution.wikimedia_runner import WikimediaResult
        from assetboy.execution.archive_org_runner import ArchiveOrgResult
        from assetboy.execution.inaturalist_runner import INaturalistResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {}, clear=False):
                for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY",
                          "UNSPLASH_ACCESS_KEY"):
                    os.environ.pop(k, None)
                with patch(
                    "assetboy.execution.met_museum_runner.run_met_museum_batch",
                    return_value=MetMuseumResult(
                        pack_id="x", query="q", output_dir=Path(tmp),
                        objects_matched=3, ok=True,
                    ),
                ), patch(
                    "assetboy.execution.wikimedia_runner.run_wikimedia_batch",
                    return_value=WikimediaResult(
                        pack_id="x", query="q", output_dir=Path(tmp),
                        files_matched=2, ok=True,
                    ),
                ), patch(
                    "assetboy.execution.archive_org_runner.run_archive_org_batch",
                    return_value=ArchiveOrgResult(
                        pack_id="x", query="q", output_dir=Path(tmp),
                        items_matched=1, ok=True,
                    ),
                ), patch(
                    "assetboy.execution.inaturalist_runner.run_inaturalist_batch",
                    return_value=INaturalistResult(
                        pack_id="x", query="q", output_dir=Path(tmp),
                        observations_matched=5, ok=True,
                    ),
                ), patch(
                    "assetboy.execution.iconify_runner.run_iconify_batch",
                    return_value=__import__(
                        "assetboy.execution.iconify_runner",
                        fromlist=["IconifyResult"],
                    ).IconifyResult(
                        pack_id="x", query="q", output_dir=Path(tmp),
                        icons_matched=4, ok=True,
                    ),
                ):
                    result = self.runner.invoke(
                        self.app,
                        ["gen", "scout-by-license",
                         "--license", "cc0", "--query", "stone",
                         "--dry-run", "--json"],
                    )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        # CC0 token matches: met, wikimedia, archive-org, iconify, iNat, pixabay = 6.
        self.assertEqual(data["providers_matched_by_license"], 6)
        # 5 no-key providers all mocked OK; pixabay skipped (no env key).
        self.assertEqual(data["providers_ok"], 5)
        self.assertEqual(data["providers_skipped"], 1)
        self.assertEqual(data["total_matched"], 3 + 2 + 1 + 5 + 4)

    def test_scout_by_license_mit_matches_only_iconify(self) -> None:
        """MIT is only in Iconify's license string."""
        from unittest.mock import patch
        from assetboy.execution.iconify_runner import IconifyResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "assetboy.execution.iconify_runner.run_iconify_batch",
                return_value=IconifyResult(
                    pack_id="x", query="q", output_dir=Path(tmp),
                    icons_matched=8, ok=True,
                ),
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "scout-by-license",
                     "--license", "mit", "--query", "sword",
                     "--dry-run", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["providers_matched_by_license"], 1)
        self.assertEqual(data["providers_ok"], 1)
        self.assertEqual(data["providers"][0]["provider"], "iconify")

    # ----------------------------------------------------------------- #
    # gen openlibrary fetch (v1.13.s91)
    # ----------------------------------------------------------------- #

    def test_openlibrary_fetch_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "openlibrary", "fetch", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Open Library", result.stdout)
        self.assertIn("REFERENCE-ONLY", result.stdout)

    def test_openlibrary_fetch_dry_run_no_matches_exits_zero(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.openlibrary_runner import OpenLibraryResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = OpenLibraryResult(
                pack_id="T", query="zzz", output_dir=Path(tmp),
                docs_matched=0, ok=True, error="no_matches",
            )
            with patch(
                "assetboy.execution.openlibrary_runner.run_openlibrary_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "openlibrary", "fetch", "--query", "zzz", "--dry-run"],
                )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("gen_openlibrary_matched=0", result.stdout)
        self.assertIn("no_matches", result.stdout)

    def test_openlibrary_fetch_use_policy_in_stdout(self) -> None:
        from unittest.mock import patch
        from assetboy.execution.openlibrary_runner import OpenLibraryResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fake = OpenLibraryResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                docs_matched=3, covers_with_id=3, covers_downloaded=3, ok=True,
            )
            with patch(
                "assetboy.execution.openlibrary_runner.run_openlibrary_batch",
                return_value=fake,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "openlibrary", "fetch", "--query", "q"],
                )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("USE_POLICY", result.stdout)

    # ----------------------------------------------------------------- #
    # gen all-no-key (v1.11.s37)
    # ----------------------------------------------------------------- #

    def test_all_no_key_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "all-no-key", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("no-key", result.stdout.lower())
        self.assertIn("Met Museum", result.stdout)

    def test_all_no_key_fans_out_with_mocked_runners(self) -> None:
        """Mock all 5 runners; verify aggregation logic."""
        from unittest.mock import patch
        from assetboy.execution.met_museum_runner import MetMuseumResult
        from assetboy.execution.wikimedia_runner import WikimediaResult
        from assetboy.execution.archive_org_runner import ArchiveOrgResult
        from assetboy.execution.scryfall_runner import ScryfallResult
        from assetboy.execution.iconify_runner import IconifyResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "assetboy.execution.met_museum_runner.run_met_museum_batch",
                return_value=MetMuseumResult(
                    pack_id="MET", query="q", output_dir=Path(tmp),
                    objects_matched=10, objects_downloaded=2, ok=True,
                ),
            ), patch(
                "assetboy.execution.wikimedia_runner.run_wikimedia_batch",
                return_value=WikimediaResult(
                    pack_id="WM", query="q", output_dir=Path(tmp),
                    files_matched=20, files_downloaded=2, ok=True,
                ),
            ), patch(
                "assetboy.execution.archive_org_runner.run_archive_org_batch",
                return_value=ArchiveOrgResult(
                    pack_id="AO", query="q", output_dir=Path(tmp),
                    items_matched=5, items_downloaded=2, ok=True,
                ),
            ), patch(
                "assetboy.execution.scryfall_runner.run_scryfall_batch",
                return_value=ScryfallResult(
                    pack_id="SF", query="q", output_dir=Path(tmp),
                    cards_matched=30, cards_downloaded=2, ok=True,
                ),
            ), patch(
                "assetboy.execution.iconify_runner.run_iconify_batch",
                return_value=IconifyResult(
                    pack_id="IC", query="q", output_dir=Path(tmp),
                    icons_matched=50, icons_downloaded=2, ok=True,
                ),
            ), patch(
                "assetboy.execution.inaturalist_runner.run_inaturalist_batch",
                return_value=__import__(
                    "assetboy.execution.inaturalist_runner",
                    fromlist=["INaturalistResult"],
                ).INaturalistResult(
                    pack_id="INAT", query="q", output_dir=Path(tmp),
                    observations_matched=7, photos_downloaded=2, ok=True,
                ),
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "all-no-key", "--query", "q", "--count", "2", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        # v1.13.s87: catalog grew to 6 providers (added iNaturalist).
        self.assertEqual(data["providers_run"], 6)
        self.assertEqual(data["providers_ok"], 6)
        self.assertEqual(data["total_matched"], 10 + 20 + 5 + 30 + 50 + 7)
        self.assertEqual(data["total_downloaded"], 12)  # 2*6 providers

    def test_all_no_key_parallel_dispatch_preserves_order(self) -> None:
        """v1.12.s64: --parallel returns same shape + preserves task order."""
        from unittest.mock import patch
        from assetboy.execution.met_museum_runner import MetMuseumResult
        from assetboy.execution.wikimedia_runner import WikimediaResult
        from assetboy.execution.archive_org_runner import ArchiveOrgResult
        from assetboy.execution.scryfall_runner import ScryfallResult
        from assetboy.execution.iconify_runner import IconifyResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "assetboy.execution.met_museum_runner.run_met_museum_batch",
                return_value=MetMuseumResult(
                    pack_id="MET", query="q", output_dir=Path(tmp),
                    objects_matched=1, objects_downloaded=1, ok=True,
                ),
            ), patch(
                "assetboy.execution.wikimedia_runner.run_wikimedia_batch",
                return_value=WikimediaResult(
                    pack_id="WM", query="q", output_dir=Path(tmp),
                    files_matched=2, files_downloaded=2, ok=True,
                ),
            ), patch(
                "assetboy.execution.archive_org_runner.run_archive_org_batch",
                return_value=ArchiveOrgResult(
                    pack_id="AO", query="q", output_dir=Path(tmp),
                    items_matched=3, items_downloaded=3, ok=True,
                ),
            ), patch(
                "assetboy.execution.scryfall_runner.run_scryfall_batch",
                return_value=ScryfallResult(
                    pack_id="SF", query="q", output_dir=Path(tmp),
                    cards_matched=4, cards_downloaded=4, ok=True,
                ),
            ), patch(
                "assetboy.execution.iconify_runner.run_iconify_batch",
                return_value=IconifyResult(
                    pack_id="IC", query="q", output_dir=Path(tmp),
                    icons_matched=5, icons_downloaded=5, ok=True,
                ),
            ), patch(
                "assetboy.execution.inaturalist_runner.run_inaturalist_batch",
                return_value=__import__(
                    "assetboy.execution.inaturalist_runner",
                    fromlist=["INaturalistResult"],
                ).INaturalistResult(
                    pack_id="IN", query="q", output_dir=Path(tmp),
                    observations_matched=6, photos_downloaded=6, ok=True,
                ),
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "all-no-key", "--query", "q", "--parallel", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        self.assertTrue(data["parallel"])
        # v1.13.s87: 6 providers now.
        self.assertEqual(data["providers_run"], 6)
        self.assertEqual(data["providers_ok"], 6)
        # Order: met_museum, wikimedia, archive_org, scryfall, iconify, inaturalist.
        expected_order = [
            "met_museum", "wikimedia", "archive_org", "scryfall", "iconify", "inaturalist",
        ]
        self.assertEqual([p["provider"] for p in data["providers"]], expected_order)
        # Counts (matched=1,2,3,4,5,6) preserved per provider.
        self.assertEqual([p["matched"] for p in data["providers"]], [1, 2, 3, 4, 5, 6])

    def test_all_no_key_parallel_isolates_crash(self) -> None:
        """--parallel: one provider crashing doesn't break the others."""
        from unittest.mock import patch
        from assetboy.execution.met_museum_runner import MetMuseumResult
        from assetboy.execution.wikimedia_runner import WikimediaResult
        from assetboy.execution.archive_org_runner import ArchiveOrgResult
        from assetboy.execution.scryfall_runner import ScryfallResult
        from assetboy.execution.iconify_runner import IconifyResult
        import tempfile

        def crash(*a, **kw):
            raise RuntimeError("simulated parallel crash")

        with tempfile.TemporaryDirectory() as tmp:
            ok = MetMuseumResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                objects_matched=1, objects_downloaded=1, ok=True,
            )
            with patch(
                "assetboy.execution.met_museum_runner.run_met_museum_batch",
                return_value=ok,
            ), patch(
                "assetboy.execution.wikimedia_runner.run_wikimedia_batch",
                side_effect=crash,
            ), patch(
                "assetboy.execution.archive_org_runner.run_archive_org_batch",
                return_value=ArchiveOrgResult(
                    pack_id="A", query="q", output_dir=Path(tmp),
                    items_matched=0, items_downloaded=0, ok=True,
                ),
            ), patch(
                "assetboy.execution.scryfall_runner.run_scryfall_batch",
                return_value=ScryfallResult(
                    pack_id="S", query="q", output_dir=Path(tmp),
                    cards_matched=0, cards_downloaded=0, ok=True,
                ),
            ), patch(
                "assetboy.execution.iconify_runner.run_iconify_batch",
                return_value=IconifyResult(
                    pack_id="I", query="q", output_dir=Path(tmp),
                    icons_matched=0, icons_downloaded=0, ok=True,
                ),
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "all-no-key", "--query", "q", "--parallel", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["providers_failed"], 1)
        wm = [p for p in data["providers"] if p["provider"] == "wikimedia"][0]
        self.assertFalse(wm["ok"])
        self.assertIn("crashed", wm["error"])

    # ----------------------------------------------------------------- #
    # pack manifest-stats (v1.12.s72)
    # ----------------------------------------------------------------- #

    def test_pack_manifest_stats_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["pack", "manifest-stats", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("manifest", result.stdout.lower())
        self.assertIn("R1A", result.stdout)

    def test_pack_manifest_stats_aggregates_from_synthetic_manifests(self) -> None:
        """Write 2 synthetic manifests to a tempdir; verify aggregation."""
        import tempfile, json as _json
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            # Synthetic Met Museum manifest.
            (tmp_p / "met_museum").mkdir()
            (tmp_p / "met_museum" / "met_museum_manifest.json").write_text(
                _json.dumps({
                    "source": "met_museum",
                    "objects_downloaded": 3,
                    "objects_skipped_non_pd": 2,
                    "objects_failed": 0,
                    "entries": [
                        {"bytes": 1000}, {"bytes": 2000}, {"bytes": 3000},
                    ],
                }),
                encoding="utf-8",
            )
            # Synthetic Wikimedia manifest in deeper subdir.
            (tmp_p / "wikimedia" / "pack_x").mkdir(parents=True)
            (tmp_p / "wikimedia" / "pack_x" / "wikimedia_manifest.json").write_text(
                _json.dumps({
                    "source": "wikimedia_commons",
                    "files_downloaded": 5,
                    "files_skipped_restricted": 7,
                    "files_failed": 1,
                    "entries": [{"bytes": 500}, {"bytes": 1500}],
                }),
                encoding="utf-8",
            )
            result = self.runner.invoke(
                self.app,
                ["pack", "manifest-stats", "--root", str(tmp_p), "--json"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.stdout)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["manifests_scanned"], 2)
        self.assertEqual(data["sources_seen"], 2)
        self.assertEqual(data["total_downloaded"], 3 + 5)
        self.assertEqual(data["total_skipped"], 2 + 7)
        self.assertEqual(data["total_failed"], 0 + 1)
        self.assertEqual(data["total_bytes"], 1000 + 2000 + 3000 + 500 + 1500)
        self.assertIn("met_museum", data["by_source"])
        self.assertIn("wikimedia_commons", data["by_source"])

    def test_pack_manifest_stats_source_filter_scopes_results(self) -> None:
        """v1.12.s77: --source met_museum filters out other sources."""
        import tempfile, json as _json
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            (tmp_p / "met").mkdir()
            (tmp_p / "met" / "met_museum_manifest.json").write_text(
                _json.dumps({
                    "source": "met_museum",
                    "objects_downloaded": 5,
                    "entries": [{"bytes": 1000}],
                }), encoding="utf-8",
            )
            (tmp_p / "wm").mkdir()
            (tmp_p / "wm" / "wikimedia_manifest.json").write_text(
                _json.dumps({
                    "source": "wikimedia_commons",
                    "files_downloaded": 99,
                    "entries": [{"bytes": 9999}],
                }), encoding="utf-8",
            )
            result = self.runner.invoke(
                self.app,
                ["pack", "manifest-stats",
                 "--root", str(tmp_p),
                 "--source", "met_museum",
                 "--json"],
            )
        self.assertEqual(result.exit_code, 0)
        data = _json.loads(result.stdout.strip())
        # 2 manifests scanned but only 1 met_museum kept.
        self.assertEqual(data["manifests_scanned"], 2)
        self.assertEqual(data["manifests_after_filter"], 1)
        self.assertEqual(data["sources_seen"], 1)
        self.assertEqual(data["total_downloaded"], 5)  # WM's 99 excluded
        self.assertIn("met_museum", data["by_source"])
        self.assertNotIn("wikimedia_commons", data["by_source"])
        self.assertEqual(data["source_filter"], "met_museum")

    def test_pack_manifest_stats_since_filter_scopes_by_mtime(self) -> None:
        """v1.13.s92: --since <ISO> filters out manifests older than the timestamp."""
        import tempfile, json as _json, os, time
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = Path(tmp)
            (tmp_p / "old").mkdir()
            (tmp_p / "new").mkdir()
            old_mf = tmp_p / "old" / "old_manifest.json"
            new_mf = tmp_p / "new" / "new_manifest.json"
            old_mf.write_text(_json.dumps({
                "source": "old_source",
                "objects_downloaded": 99,
                "entries": [],
            }), encoding="utf-8")
            new_mf.write_text(_json.dumps({
                "source": "new_source",
                "objects_downloaded": 7,
                "entries": [],
            }), encoding="utf-8")
            # Set old mtime to 1 year ago.
            old_time = time.time() - 365 * 86400
            os.utime(old_mf, (old_time, old_time))
            # New manifest keeps current mtime.
            # Filter: --since one day ago.
            from datetime import datetime, timedelta
            since_iso = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
            result = self.runner.invoke(
                self.app,
                ["pack", "manifest-stats",
                 "--root", str(tmp_p),
                 "--since", since_iso,
                 "--json"],
            )
        self.assertEqual(result.exit_code, 0, msg=result.stdout)
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["manifests_scanned"], 2)
        # Only new_source survives the --since filter.
        self.assertEqual(data["manifests_after_filter"], 1)
        self.assertEqual(data["sources_seen"], 1)
        self.assertIn("new_source", data["by_source"])
        self.assertNotIn("old_source", data["by_source"])
        self.assertEqual(data["since_filter"], since_iso)
        self.assertEqual(data["total_downloaded"], 7)

    def test_pack_manifest_stats_invalid_since_exits_1(self) -> None:
        """Malformed --since string -> clean exit 1."""
        result = self.runner.invoke(
            self.app,
            ["pack", "manifest-stats", "--since", "not-a-date"],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("invalid_since_timestamp", result.stdout)

    def test_pack_manifest_stats_missing_root_exits_1(self) -> None:
        result = self.runner.invoke(
            self.app, ["pack", "manifest-stats", "--root", "C:/nonexistent/path/xyz"],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("root_dir_not_found", result.stdout)

    # ----------------------------------------------------------------- #
    # gen bench-fanout (v1.12.s70)
    # ----------------------------------------------------------------- #

    def test_bench_fanout_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "bench-fanout", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Benchmark", result.stdout)
        self.assertIn("sequential", result.stdout.lower())
        self.assertIn("parallel", result.stdout.lower())

    def test_bench_fanout_runs_both_modes_with_mocked_runners(self) -> None:
        """Mock all 6 runners as no-ops; verify both modes execute + JSON shape."""
        from unittest.mock import patch
        from assetboy.execution.met_museum_runner import MetMuseumResult
        from assetboy.execution.wikimedia_runner import WikimediaResult
        from assetboy.execution.archive_org_runner import ArchiveOrgResult
        from assetboy.execution.scryfall_runner import ScryfallResult
        from assetboy.execution.iconify_runner import IconifyResult
        from assetboy.execution.inaturalist_runner import INaturalistResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch(
                "assetboy.execution.met_museum_runner.run_met_museum_batch",
                return_value=MetMuseumResult(
                    pack_id="x", query="q", output_dir=Path(tmp), ok=True,
                ),
            ), patch(
                "assetboy.execution.wikimedia_runner.run_wikimedia_batch",
                return_value=WikimediaResult(
                    pack_id="x", query="q", output_dir=Path(tmp), ok=True,
                ),
            ), patch(
                "assetboy.execution.archive_org_runner.run_archive_org_batch",
                return_value=ArchiveOrgResult(
                    pack_id="x", query="q", output_dir=Path(tmp), ok=True,
                ),
            ), patch(
                "assetboy.execution.scryfall_runner.run_scryfall_batch",
                return_value=ScryfallResult(
                    pack_id="x", query="q", output_dir=Path(tmp), ok=True,
                ),
            ), patch(
                "assetboy.execution.iconify_runner.run_iconify_batch",
                return_value=IconifyResult(
                    pack_id="x", query="q", output_dir=Path(tmp), ok=True,
                ),
            ), patch(
                "assetboy.execution.inaturalist_runner.run_inaturalist_batch",
                return_value=INaturalistResult(
                    pack_id="x", query="q", output_dir=Path(tmp), ok=True,
                ),
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "bench-fanout", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        for key in (
            "query", "providers", "sequential_total_s",
            "parallel_total_s", "speedup_x", "sequential_per_provider_s",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["query"], "q")
        # v1.13.s87: bench-fanout grew to 6 providers (added iNaturalist).
        self.assertEqual(len(data["providers"]), 6)
        # With mocked no-op runners, both times will be near zero — verify type + non-negative.
        self.assertGreaterEqual(data["sequential_total_s"], 0.0)
        self.assertGreaterEqual(data["parallel_total_s"], 0.0)
        self.assertGreaterEqual(data["speedup_x"], 0.0)

    def test_all_no_key_handles_one_provider_failure(self) -> None:
        """One provider crashes mid-fanout; others still complete."""
        from unittest.mock import patch
        from assetboy.execution.met_museum_runner import MetMuseumResult
        from assetboy.execution.wikimedia_runner import WikimediaResult
        from assetboy.execution.archive_org_runner import ArchiveOrgResult
        from assetboy.execution.scryfall_runner import ScryfallResult
        from assetboy.execution.iconify_runner import IconifyResult
        import tempfile

        def crash(*a: object, **kw: object) -> None:
            raise RuntimeError("simulated crash")

        with tempfile.TemporaryDirectory() as tmp:
            ok_result = MetMuseumResult(
                pack_id="P", query="q", output_dir=Path(tmp),
                objects_matched=5, objects_downloaded=1, ok=True,
            )
            with patch(
                "assetboy.execution.met_museum_runner.run_met_museum_batch",
                return_value=ok_result,
            ), patch(
                "assetboy.execution.wikimedia_runner.run_wikimedia_batch",
                side_effect=crash,  # this one crashes
            ), patch(
                "assetboy.execution.archive_org_runner.run_archive_org_batch",
                return_value=ArchiveOrgResult(
                    pack_id="A", query="q", output_dir=Path(tmp),
                    items_matched=2, items_downloaded=0, ok=True,
                ),
            ), patch(
                "assetboy.execution.scryfall_runner.run_scryfall_batch",
                return_value=ScryfallResult(
                    pack_id="S", query="q", output_dir=Path(tmp),
                    cards_matched=3, cards_downloaded=0, ok=True,
                ),
            ), patch(
                "assetboy.execution.iconify_runner.run_iconify_batch",
                return_value=IconifyResult(
                    pack_id="I", query="q", output_dir=Path(tmp),
                    icons_matched=7, icons_downloaded=0, ok=True,
                ),
            ), patch(
                "assetboy.execution.inaturalist_runner.run_inaturalist_batch",
                return_value=__import__(
                    "assetboy.execution.inaturalist_runner",
                    fromlist=["INaturalistResult"],
                ).INaturalistResult(
                    pack_id="N", query="q", output_dir=Path(tmp),
                    observations_matched=4, photos_downloaded=0, ok=True,
                ),
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "all-no-key", "--query", "q", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        # v1.13.s87: 6 providers (5 OK + 1 crashed = wikimedia).
        self.assertEqual(data["providers_run"], 6)
        self.assertEqual(data["providers_ok"], 5)
        self.assertEqual(data["providers_failed"], 1)
        # The crashed one has the error string.
        crashed = [p for p in data["providers"] if not p["ok"]]
        self.assertEqual(len(crashed), 1)
        self.assertIn("crashed", crashed[0]["error"])

    # ----------------------------------------------------------------- #
    # gen all-key (v1.11.s38)
    # ----------------------------------------------------------------- #

    def test_all_key_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "all-key", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("key-required", result.stdout)
        self.assertIn("PEXELS_API_KEY", result.stdout)
        self.assertIn("--include-video", result.stdout)

    def test_all_key_all_missing_keys_shows_all_skipped(self) -> None:
        """No env vars set -> every provider reports skipped."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=False):
            for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY",
                      "UNSPLASH_ACCESS_KEY", "RAWG_API_KEY", "JAMENDO_CLIENT_ID"):
                os.environ.pop(k, None)
            result = self.runner.invoke(
                self.app, ["gen", "all-key", "--query", "x", "--dry-run", "--json"],
            )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        # No --include-video, so 5 providers run (1 photo each from Pexels,
        # Pixabay, Unsplash + RAWG + Jamendo).
        self.assertEqual(data["providers_run"], 5)
        self.assertEqual(data["providers_skipped"], 5)
        self.assertEqual(data["providers_ok"], 0)
        for p in data["providers"]:
            self.assertTrue(p["skipped"])
            self.assertEqual(p["error"], "missing_env_key")

    def test_all_key_with_video_runs_7_providers(self) -> None:
        """--include-video adds Pexels videos + Pixabay videos (5 -> 7 providers)."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=False):
            for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY",
                      "UNSPLASH_ACCESS_KEY", "RAWG_API_KEY", "JAMENDO_CLIENT_ID"):
                os.environ.pop(k, None)
            result = self.runner.invoke(
                self.app,
                ["gen", "all-key", "--query", "x", "--include-video", "--json"],
            )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["providers_run"], 7)
        self.assertTrue(data["include_video"])

    def test_all_key_parallel_preserves_order_and_skips(self) -> None:
        """v1.12.s65: --parallel preserves task order; missing keys still SKIP."""
        import os
        from unittest.mock import patch
        from assetboy.execution.pexels_runner import PexelsResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"PEXELS_API_KEY": "k"}, clear=False):
                # Clear all others.
                for k in ("PIXABAY_API_KEY", "UNSPLASH_ACCESS_KEY",
                          "RAWG_API_KEY", "JAMENDO_CLIENT_ID"):
                    os.environ.pop(k, None)
                fake = PexelsResult(
                    pack_id="P", query="q", output_dir=Path(tmp),
                    kind="photos", items_matched=2, items_downloaded=2, ok=True,
                )
                with patch(
                    "assetboy.execution.pexels_runner.run_pexels_photo_batch",
                    return_value=fake,
                ):
                    result = self.runner.invoke(
                        self.app,
                        ["gen", "all-key", "--query", "q", "--parallel", "--json"],
                    )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        self.assertTrue(data["parallel"])
        self.assertEqual(data["providers_ok"], 1)
        self.assertEqual(data["providers_skipped"], 4)
        # Order: pexels_photos first, then pixabay_photos, unsplash, rawg, jamendo.
        expected_order = ["pexels_photos", "pixabay_photos", "unsplash", "rawg", "jamendo"]
        self.assertEqual([p["provider"] for p in data["providers"]], expected_order)
        # Only pexels_photos has ok=True; others skipped.
        ok = [p for p in data["providers"] if p["ok"]]
        self.assertEqual(len(ok), 1)
        self.assertEqual(ok[0]["provider"], "pexels_photos")

    def test_all_key_partial_env_runs_only_keyed_providers(self) -> None:
        """Set only PEXELS_API_KEY; mock its runner; others should still be SKIP."""
        import os
        from unittest.mock import patch
        from assetboy.execution.pexels_runner import PexelsResult
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"PEXELS_API_KEY": "test-key"}, clear=False):
                for k in ("PIXABAY_API_KEY", "UNSPLASH_ACCESS_KEY",
                          "RAWG_API_KEY", "JAMENDO_CLIENT_ID"):
                    os.environ.pop(k, None)
                fake = PexelsResult(
                    pack_id="P", query="x", output_dir=Path(tmp),
                    kind="photos", items_matched=3, items_downloaded=3, ok=True,
                )
                with patch(
                    "assetboy.execution.pexels_runner.run_pexels_photo_batch",
                    return_value=fake,
                ):
                    result = self.runner.invoke(
                        self.app,
                        ["gen", "all-key", "--query", "x", "--json"],
                    )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        self.assertEqual(data["providers_ok"], 1)
        self.assertEqual(data["providers_skipped"], 4)
        # Pexels photos must be the one that ran.
        ok = [p for p in data["providers"] if p["ok"]]
        self.assertEqual(len(ok), 1)
        self.assertEqual(ok[0]["provider"], "pexels_photos")
        self.assertEqual(ok[0]["matched"], 3)
        self.assertEqual(ok[0]["downloaded"], 3)

    # ----------------------------------------------------------------- #
    # gen list-providers (v1.11.s45)
    # ----------------------------------------------------------------- #

    def test_list_providers_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["gen", "list-providers", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Catalog", result.stdout)

    def test_list_providers_default_lists_all(self) -> None:
        """Stdout should list all 13 providers in catalog with header (v1.13.s86)."""
        result = self.runner.invoke(self.app, ["gen", "list-providers"])
        self.assertEqual(result.exit_code, 0)
        # Header counts (12 -> 13 after iNaturalist added).
        self.assertIn("gen_list_providers_total=13", result.stdout)
        # Each provider id appears.
        for provider_id in (
            "met-museum", "wikimedia", "archive-org", "scryfall", "iconify",
            "pexels", "pixabay", "unsplash", "rawg", "jamendo",
            "inaturalist", "comfyui", "sd",
        ):
            self.assertIn(provider_id, result.stdout)

    def test_list_providers_json_shape(self) -> None:
        import os
        from unittest.mock import patch
        # Clear all env vars to test annotation.
        with patch.dict(os.environ, {}, clear=False):
            for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY",
                      "UNSPLASH_ACCESS_KEY", "RAWG_API_KEY", "JAMENDO_CLIENT_ID"):
                os.environ.pop(k, None)
            result = self.runner.invoke(self.app, ["gen", "list-providers", "--json"])
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        # v1.13.s86 catalog: 13 providers (5 R1A no-key + 5 R1A keyed +
        # iNaturalist + comfyui + sd).
        self.assertEqual(data["total"], 13)
        self.assertEqual(data["no_key_count"], 8)  # 5 R1A no-key + iNat + comfyui + sd
        self.assertEqual(data["key_required_count"], 5)
        self.assertEqual(data["key_set_count"], 0)  # all cleared
        self.assertEqual(data["key_unset_count"], 5)
        # Each provider has expected fields.
        for p in data["providers"]:
            for key in ("id", "cli", "env_var", "license", "asset_class", "what", "env_set"):
                self.assertIn(key, p)

    def test_list_providers_filter_env_set_true(self) -> None:
        """v1.12.s71: --filter env_set:true returns only providers with keys SET."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"PEXELS_API_KEY": "test"}, clear=False):
            # Clear all others.
            for k in ("PIXABAY_API_KEY", "UNSPLASH_ACCESS_KEY",
                      "RAWG_API_KEY", "JAMENDO_CLIENT_ID"):
                os.environ.pop(k, None)
            result = self.runner.invoke(
                self.app,
                ["gen", "list-providers", "--filter", "env_set:true", "--json"],
            )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        # Only pexels should be in the list (it's the only key-set).
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["providers"][0]["id"], "pexels")
        self.assertEqual(data["filters_applied"], ["env_set:true"])

    def test_list_providers_filter_env_var_none(self) -> None:
        """--filter env_var:none returns only no-key providers."""
        result = self.runner.invoke(
            self.app,
            ["gen", "list-providers", "--filter", "env_var:none", "--json"],
        )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        # v1.13.s86: 5 R1A no-key + iNaturalist + comfyui + sd = 8
        self.assertEqual(data["total"], 8)
        for p in data["providers"]:
            self.assertIsNone(p["env_var"])

    def test_list_providers_bad_filter_shape_errors(self) -> None:
        result = self.runner.invoke(
            self.app,
            ["gen", "list-providers", "--filter", "no_colon_here"],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("bad_filter_shape", result.stdout)

    def test_list_providers_detects_set_env_var(self) -> None:
        """When PEXELS_API_KEY is set, env_set=True for pexels."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"PEXELS_API_KEY": "test"}, clear=False):
            result = self.runner.invoke(self.app, ["gen", "list-providers", "--json"])
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        pexels = [p for p in data["providers"] if p["id"] == "pexels"][0]
        self.assertTrue(pexels["env_set"])

    def test_comfy_submit_workflow_help_renders(self) -> None:
        result = self.runner.invoke(
            self.app, ["gen", "comfyui", "submit-workflow", "--help"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("ComfyUI workflow JSON", result.stdout)

    def test_comfy_submit_workflow_missing_file_errors_cleanly(self) -> None:
        result = self.runner.invoke(
            self.app,
            ["gen", "comfyui", "submit-workflow", "does_not_exist.json"],
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("workflow_not_found", result.stdout)

    def test_comfy_submit_workflow_server_down_errors_cleanly(self) -> None:
        """When ComfyUI :8188 isn't running, command exits 1 with clean error."""
        import tempfile, json as _json
        from unittest.mock import patch
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tf:
            _json.dump({"6": {"class_type": "x", "inputs": {}}}, tf)
            tmp = tf.name
        try:
            with patch(
                "assetboy.execution.comfyui_runner.is_comfyui_running",
                return_value=False,
            ):
                result = self.runner.invoke(
                    self.app, ["gen", "comfyui", "submit-workflow", tmp]
                )
            self.assertEqual(result.exit_code, 1)
            self.assertIn("comfyui_not_running", result.stdout)
        finally:
            import os
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def test_comfy_submit_workflow_bad_param_shape_errors(self) -> None:
        """--param 'malformed' (no = sign) -> clean error."""
        import tempfile, json as _json
        from unittest.mock import patch
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tf:
            _json.dump({"6": {"class_type": "x", "inputs": {"text": "old"}}}, tf)
            tmp = tf.name
        try:
            with patch(
                "assetboy.execution.comfyui_runner.is_comfyui_running",
                return_value=True,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["gen", "comfyui", "submit-workflow", tmp, "--param", "malformed"],
                )
            self.assertEqual(result.exit_code, 1)
            self.assertIn("bad_param_shape", result.stdout)
        finally:
            import os
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def test_pack_from_recipe_only_filters_to_named_pack(self) -> None:
        """v1.9.s21: --only PACK_B restricts to that pack only."""
        result = self.runner.invoke(
            self.app,
            ["pack", "from-recipe", "--inline-yaml", self.ONLY_FILTER_RECIPE,
             "--only", "PACK_B", "--dry-run", "--json"],
        )
        import json
        parsed = json.loads(result.stdout)
        # Total reflects how many were actually processed (1, not 3)
        self.assertEqual(parsed["total_packs"], 1)
        self.assertEqual(len(parsed["results"]), 1)
        self.assertEqual(parsed["results"][0]["pack_id"], "PACK_B")

    def test_pack_from_recipe_only_repeatable(self) -> None:
        """v1.9.s21: --only repeats to select multiple packs."""
        result = self.runner.invoke(
            self.app,
            ["pack", "from-recipe", "--inline-yaml", self.ONLY_FILTER_RECIPE,
             "--only", "PACK_A", "--only", "PACK_C", "--dry-run", "--json"],
        )
        import json
        parsed = json.loads(result.stdout)
        self.assertEqual(parsed["total_packs"], 2)
        pack_ids = sorted(r["pack_id"] for r in parsed["results"])
        self.assertEqual(pack_ids, ["PACK_A", "PACK_C"])

    # ----------------------------------------------------------------- #
    # library export (v1.9.s22)
    # ----------------------------------------------------------------- #

    def test_library_export_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["library", "export", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("manifest", result.stdout.lower())

    def test_library_export_when_server_down_exits_clean(self) -> None:
        """v1.9.s22: server-down -> clean error, not crash."""
        import tempfile
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as tf:
            out_path = tf.name
        try:
            result = self.runner.invoke(
                self.app,
                ["library", "export", out_path, "--server", "http://localhost:1"],
            )
            self.assertEqual(result.exit_code, 1)
            self.assertIn("library_export_error", result.stdout)
        finally:
            import os
            try:
                os.unlink(out_path)
            except OSError:
                pass

    def test_library_export_format_inferred_from_extension(self) -> None:
        """--out_path *.yaml -> yaml format, else json."""
        from unittest.mock import patch
        import tempfile, os, json as _json

        fake_ready = {
            "ready_assets": [
                {"id": "A", "provider": "polyhaven", "category": "texture", "name": "A name"},
                {"id": "B", "provider": "kenney", "category": "model", "name": "B name", "sha256": "abc123"},
            ]
        }

        # JSON output (default extension)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            out_json = tf.name
        try:
            with patch(
                "assetboy.cli.library._faw_post",
                return_value=fake_ready,
            ):
                result = self.runner.invoke(
                    self.app,
                    ["library", "export", out_json, "--include-checksums"],
                )
            self.assertEqual(result.exit_code, 0, f"stdout: {result.stdout}")
            self.assertIn("library_export_count=2", result.stdout)
            self.assertIn("library_export_format=json", result.stdout)
            # Verify the JSON shape matches bulk-install expectations
            parsed = _json.loads(open(out_json, encoding="utf-8").read())
            self.assertEqual(len(parsed), 2)
            self.assertEqual(parsed[0]["asset_id"], "A")
            self.assertEqual(parsed[1]["sha256"], "abc123")
        finally:
            try:
                os.unlink(out_json)
            except OSError:
                pass

    def test_pack_from_recipe_only_plus_skip_skip_wins(self) -> None:
        """v1.9.s21: --skip takes precedence over --only on overlap."""
        result = self.runner.invoke(
            self.app,
            ["pack", "from-recipe", "--inline-yaml", self.ONLY_FILTER_RECIPE,
             "--only", "PACK_A", "--only", "PACK_B",
             "--skip", "PACK_B",
             "--dry-run", "--json"],
        )
        import json
        parsed = json.loads(result.stdout)
        # Only PACK_A survives (only=[A,B], skip=[B] -> just A)
        self.assertEqual(parsed["total_packs"], 1)
        self.assertEqual(parsed["results"][0]["pack_id"], "PACK_A")

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

    def test_library_r1a_status_help_renders(self) -> None:
        """v1.12.s75: library r1a-status --help works."""
        result = self.runner.invoke(self.app, ["library", "r1a-status", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("R1A", result.stdout)

    def test_library_r1a_status_runs_with_clean_env(self) -> None:
        """library r1a-status runs without crash even with no env vars set."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=False):
            for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY",
                      "UNSPLASH_ACCESS_KEY", "RAWG_API_KEY", "JAMENDO_CLIENT_ID"):
                os.environ.pop(k, None)
            result = self.runner.invoke(self.app, ["library", "r1a-status"])
        self.assertEqual(result.exit_code, 0, msg=result.stdout)
        # v1.13.s86: catalog grew to 11 (added iNaturalist as 6th no-key).
        self.assertIn("library_r1a_status_providers_total=11", result.stdout)
        self.assertIn("library_r1a_status_providers_no_key=6", result.stdout)
        # 0/5 keys set (key-required count unchanged at 5).
        self.assertIn("library_r1a_status_providers_key_set=0/5", result.stdout)

    def test_library_r1a_status_check_live_with_mocked_probes(self) -> None:
        """v1.13.s80: --check-live runs probes; mock to verify wiring."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=False):
            for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY",
                      "UNSPLASH_ACCESS_KEY", "RAWG_API_KEY", "JAMENDO_CLIENT_ID"):
                os.environ.pop(k, None)
            with patch(
                "assetboy.execution.met_museum_runner.search_met_object_ids",
                return_value=[1, 2, 3],
            ), patch(
                "assetboy.execution.wikimedia_runner.search_wikimedia_files",
                return_value=["File:X.jpg"],
            ), patch(
                "assetboy.execution.archive_org_runner.search_archive_items",
                return_value=[{"identifier": "x"}],
            ), patch(
                "assetboy.execution.scryfall_runner.search_scryfall_cards",
                return_value=[{"id": "x"}],
            ), patch(
                "assetboy.execution.iconify_runner.search_iconify_icons",
                return_value=["mdi:sword"],
            ), patch(
                "assetboy.execution.inaturalist_runner.search_inaturalist_observations",
                return_value=[{"id": 1}],
            ):
                result = self.runner.invoke(
                    self.app,
                    ["library", "r1a-status", "--check-live", "--json"],
                )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        self.assertTrue(data["checked_live"])
        # v1.13.s86: 6 no-key providers probed OK; 5 keyed return live_ok=False.
        self.assertEqual(data["live_ok_count"], 6)
        self.assertEqual(data["live_failed_count"], 5)
        # Each provider has live_ok and live_error keys.
        for p in data["providers"]:
            self.assertIn("live_ok", p)
            self.assertIn("live_error", p)

    def test_library_r1a_status_no_check_live_leaves_probes_unset(self) -> None:
        """When --check-live omitted, all providers have live_ok=None."""
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=False):
            for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY",
                      "UNSPLASH_ACCESS_KEY", "RAWG_API_KEY", "JAMENDO_CLIENT_ID"):
                os.environ.pop(k, None)
            result = self.runner.invoke(
                self.app, ["library", "r1a-status", "--json"],
            )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        self.assertFalse(data["checked_live"])
        for p in data["providers"]:
            self.assertIsNone(p["live_ok"])

    def test_library_r1a_status_html_writes_file(self) -> None:
        """v1.13.s97: --html <path> writes a standalone HTML report; stdout shows path."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r1a_report.html"
            result = self.runner.invoke(
                self.app, ["library", "r1a-status", "--html", str(out)],
            )
        self.assertEqual(result.exit_code, 0, msg=result.stdout)
        self.assertIn("library_r1a_status_html_path=", result.stdout)
        # File should exist + be a non-trivial HTML doc.
        # (Tempdir is gone after the with; rebuild in single block.)

    def test_library_r1a_status_html_content_includes_providers(self) -> None:
        """HTML body contains every provider id + summary stats."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "r1a.html"
            result = self.runner.invoke(
                self.app, ["library", "r1a-status", "--html", str(out)],
            )
            self.assertEqual(result.exit_code, 0)
            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("<!doctype html>", content)
            self.assertIn("FAW R1A Provider Status", content)
            for pid in ("met-museum", "iconify", "pexels", "inaturalist"):
                self.assertIn(pid, content)
            # CSS bar class present.
            self.assertIn(".bar", content)

    def test_library_r1a_status_bars_renders_section(self) -> None:
        """v1.13.s90: --bars adds proportional ASCII bar section to plain output."""
        result = self.runner.invoke(
            self.app, ["library", "r1a-status", "--bars"],
        )
        self.assertEqual(result.exit_code, 0, msg=result.stdout)
        # Section header always present when --bars set.
        self.assertIn("Bytes-on-disk proportion", result.stdout)
        # Each provider id appears in a bar row (regardless of disk state).
        for pid in ("met-museum", "iconify", "inaturalist"):
            self.assertIn(pid, result.stdout)

    def test_library_r1a_status_bars_omitted_no_section(self) -> None:
        """Without --bars, the ASCII chart section is not present."""
        result = self.runner.invoke(self.app, ["library", "r1a-status"])
        self.assertEqual(result.exit_code, 0)
        self.assertNotIn("Bytes-on-disk proportion", result.stdout)

    def test_library_r1a_status_json_shape(self) -> None:
        """JSON mode includes per-provider rows + aggregates."""
        result = self.runner.invoke(
            self.app, ["library", "r1a-status", "--json"],
        )
        self.assertEqual(result.exit_code, 0)
        import json as _json
        data = _json.loads(result.stdout.strip())
        for key in (
            "manifests_scanned", "providers_total", "providers_no_key",
            "providers_key_set", "providers_key_unset",
            "total_downloaded_on_disk", "total_bytes_on_disk", "providers",
        ):
            self.assertIn(key, data)
        # v1.13.s86: catalog grew to 11 (added iNaturalist).
        self.assertEqual(data["providers_total"], 11)
        self.assertEqual(data["providers_no_key"], 6)
        # Each provider has merged env + disk data.
        for p in data["providers"]:
            for k in ("id", "env_var", "env_set", "license", "asset_class",
                      "manifest_source", "manifests_on_disk",
                      "downloaded_on_disk", "bytes_on_disk"):
                self.assertIn(k, p)

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

    # ----------------------------------------------------------------- #
    # pack validate-all (v1.8.s19)
    # ----------------------------------------------------------------- #

    def test_pack_validate_all_passes_all_shipped_recipes(self) -> None:
        """v1.8.s19 (updated v1.11.s42 +r1a_smoke): all 5 shipped recipes validate."""
        result = self.runner.invoke(self.app, ["pack", "validate-all"])
        self.assertEqual(result.exit_code, 0)
        # 5 recipes: primitive_tech, roman, sandbox/{one_pack,generator,r1a}_smoke
        self.assertIn("pack_validate_all_total=5", result.stdout)
        self.assertIn("pack_validate_all_passed=5", result.stdout)
        self.assertIn("r1a_smoke", result.stdout)
        self.assertIn("pack_validate_all_failed=0", result.stdout)

    def test_pack_validate_all_strict_fails_on_warnings(self) -> None:
        """--strict mode flips warnings (e.g. missing source_url) to errors."""
        result = self.runner.invoke(self.app, ["pack", "validate-all", "--strict"])
        # At least one of the shipped recipes has warnings (primitive_tech /
        # roman Mixamo packs missing source_url) -> exit 1 in strict mode.
        self.assertEqual(result.exit_code, 1)
        # Aggregate fail count > 0
        self.assertIn("pack_validate_all_failed=", result.stdout)
        # Verify not all 4 passed
        self.assertNotIn("pack_validate_all_failed=0", result.stdout)

    def test_pack_validate_all_json_mode(self) -> None:
        result = self.runner.invoke(self.app, ["pack", "validate-all", "--json"])
        self.assertEqual(result.exit_code, 0)
        import json
        parsed = json.loads(result.stdout)
        for k in ("total", "passed", "failed", "recipes", "aggregate_ok"):
            self.assertIn(k, parsed)
        self.assertTrue(parsed["aggregate_ok"])
        self.assertEqual(parsed["total"], 5)  # v1.11.s42 added r1a_smoke
        self.assertEqual(parsed["passed"], 5)

    # ----------------------------------------------------------------- #
    # library bulk-install (v1.8.s16)
    # ----------------------------------------------------------------- #

    def test_library_bulk_install_help_renders(self) -> None:
        result = self.runner.invoke(self.app, ["library", "bulk-install", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("manifest", result.stdout.lower())

    def test_library_bulk_install_missing_manifest_errors_cleanly(self) -> None:
        result = self.runner.invoke(
            self.app, ["library", "bulk-install", "does_not_exist.yaml"]
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("manifest_not_found", result.stdout)

    def test_library_bulk_install_malformed_manifest_errors_cleanly(self) -> None:
        """Manifest that isn't a list -> clean error."""
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as tf:
            tf.write("not: a: list:\n")
            tmp_path = tf.name
        try:
            result = self.runner.invoke(
                self.app, ["library", "bulk-install", tmp_path]
            )
            self.assertEqual(result.exit_code, 1)
            # Either manifest_parse_failed (yaml shape) or manifest_must_be_a_list
            self.assertTrue(
                "manifest_parse_failed" in result.stdout
                or "manifest_must_be_a_list" in result.stdout,
                f"stdout: {result.stdout[:200]}",
            )
        finally:
            import os
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def test_library_bulk_install_with_real_manifest_smoke(self) -> None:
        """End-to-end smoke: write a 2-asset manifest; expect exit 1 (server
        down, both fail) but the command itself shouldn't crash. Output
        should be parseable JSON in --json mode."""
        import json as _json
        import tempfile
        manifest = [
            {"asset_id": "test_01", "provider": "polyhaven", "category": "texture"},
            {"asset_id": "test_02", "provider": "kenney", "category": "model"},
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tf:
            _json.dump(manifest, tf)
            tmp_path = tf.name
        try:
            result = self.runner.invoke(
                self.app,
                ["library", "bulk-install", tmp_path,
                 "--server", "http://localhost:1",  # unreachable
                 "--json"],
            )
            # exit 1 expected (server unreachable -> both fail)
            self.assertEqual(result.exit_code, 1)
            parsed = _json.loads(result.stdout)
            self.assertEqual(parsed["total"], 2)
            self.assertEqual(parsed["failed"], 2)
            self.assertEqual(parsed["succeeded"], 0)
        finally:
            import os
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
