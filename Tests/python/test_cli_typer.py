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
        """v1.8.s19: all 4 shipped recipes validate cleanly in default mode."""
        result = self.runner.invoke(self.app, ["pack", "validate-all"])
        self.assertEqual(result.exit_code, 0)
        # Both summary fields should show 4 = all pass
        self.assertIn("pack_validate_all_total=4", result.stdout)
        self.assertIn("pack_validate_all_passed=4", result.stdout)
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
        self.assertEqual(parsed["total"], 4)
        self.assertEqual(parsed["passed"], 4)

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
