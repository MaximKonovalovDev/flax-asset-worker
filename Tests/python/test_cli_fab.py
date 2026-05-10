import io
import json
import os
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from assetboy import cli


class _NonInteractiveStdin(io.StringIO):
    def isatty(self) -> bool:
        return False


class CliFabTests(unittest.TestCase):
    def test_build_parser_allows_fab_commands_without_workspace_root(self) -> None:
        with patch.dict(os.environ, {"ASSETBOY_FLAX_REPO_ROOT": ""}, clear=False):
            parser = cli.build_parser()
            args = parser.parse_args(["fab-auth"])
            self.assertEqual(args.command, "fab-auth")

    def test_fab_auth_requires_explicit_browser_permission_without_reuse_profile(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = cli.main(["fab-auth"])

        self.assertEqual(result, 1)
        self.assertIn("fab_auth_error=Browser launch blocked by default.", stdout.getvalue())

    def test_mixamo_auth_requires_explicit_browser_permission_without_reuse_profile(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = cli.main(["mixamo-auth"])

        self.assertEqual(result, 1)
        self.assertIn("mixamo_auth_error=Browser launch blocked by default.", stdout.getvalue())

    def test_unity_auth_requires_explicit_browser_permission_without_reuse_profile(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            result = cli.main(["unity-auth"])

        self.assertEqual(result, 1)
        self.assertIn("unity_auth_error=Browser launch blocked by default.", stdout.getvalue())

    def test_fab_auth_allow_browser_requires_interactive_terminal(self) -> None:
        stdout = io.StringIO()
        with patch.object(cli.sys, "stdin", _NonInteractiveStdin()):
            with redirect_stdout(stdout):
                result = cli.main(["fab-auth", "--allow-browser"])

        self.assertEqual(result, 1)
        self.assertIn("fab_auth_error=Interactive terminal required for --allow-browser.", stdout.getvalue())
        self.assertIn("Browser launch skipped", stdout.getvalue())

    def test_mixamo_auth_allow_browser_requires_interactive_terminal(self) -> None:
        stdout = io.StringIO()
        with patch.object(cli.sys, "stdin", _NonInteractiveStdin()):
            with redirect_stdout(stdout):
                result = cli.main(["mixamo-auth", "--allow-browser"])

        self.assertEqual(result, 1)
        self.assertIn("mixamo_auth_error=Interactive terminal required for --allow-browser.", stdout.getvalue())
        self.assertIn("Browser launch skipped", stdout.getvalue())

    def test_unity_auth_allow_browser_requires_interactive_terminal(self) -> None:
        stdout = io.StringIO()
        with patch.object(cli.sys, "stdin", _NonInteractiveStdin()):
            with redirect_stdout(stdout):
                result = cli.main(["unity-auth", "--allow-browser"])

        self.assertEqual(result, 1)
        self.assertIn("unity_auth_error=Interactive terminal required for --allow-browser.", stdout.getvalue())
        self.assertIn("Browser launch skipped", stdout.getvalue())

    def test_uevault_repair_config_rewrites_safe_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "uevaultmanager.safe.ini"
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = cli.main(["uevault-repair-config", "--config-path", str(config_path)])
            self.assertEqual(result, 0)
            self.assertIn("uevault_safe_config_rewritten=true", stdout.getvalue())
            self.assertTrue(config_path.exists())

    def test_uevault_status_uses_wrapper(self) -> None:
        fake_result = unittest.mock.Mock(returncode=0, stdout='{"Epic account":"angryowl91"}', stderr="")
        stdout = io.StringIO()
        with patch.object(cli, "run_uevaultmanager_command", return_value=fake_result) as run_command:
            with redirect_stdout(stdout):
                result = cli.main(["uevault-status"])

        self.assertEqual(result, 0)
        self.assertIn("uevault_exit_code=0", stdout.getvalue())
        run_command.assert_called_once()

    def test_uevault_list_owned_reports_invalid_output_cleanly(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "owned.json"
            fake_result = unittest.mock.Mock(returncode=0, stdout="", stderr="")
            def _fake_run(*_args, **_kwargs):
                output_path.write_text("", encoding="utf-8")
                return fake_result
            stdout = io.StringIO()
            with patch.object(cli, "run_uevaultmanager_command", side_effect=_fake_run):
                with patch.object(cli, "parse_uevault_owned_asset_count", side_effect=ValueError("bad json")):
                    with redirect_stdout(stdout):
                        result = cli.main(["uevault-list-owned", "--output", str(output_path)])

        self.assertEqual(result, 1)
        self.assertIn("uevault_warning=Owned output file is invalid or empty", stdout.getvalue())

    def test_uevault_install_owned_uses_wrapper(self) -> None:
        fake_result = unittest.mock.Mock(returncode=0, stdout="installed", stderr="")
        with TemporaryDirectory() as temp_dir:
            download_dir = Path(temp_dir) / "epic_raw"
            stdout = io.StringIO()
            with patch.object(cli, "run_uevaultmanager_command", return_value=fake_result) as run_command:
                with redirect_stdout(stdout):
                    result = cli.main(
                        [
                            "uevault-install-owned",
                            "--vault-item",
                            "Roman Arena Kit",
                            "--download-dir",
                            str(download_dir),
                        ]
                    )

        self.assertEqual(result, 0)
        self.assertIn("uevault_vault_item=Roman Arena Kit", stdout.getvalue())
        self.assertIn("uevault_download_dir=", stdout.getvalue())
        run_command.assert_called_once()

    def test_legendary_status_uses_wrapper(self) -> None:
        fake_report = {
            "legendary_path": "C:/Tools/legendary.exe",
            "session": {"config_path": "C:/Users/me/AppData/Local/EpicGamesLauncher/Saved/Config/Windows/GameUserSettings.ini", "remember_me_present": False, "remember_me_data_present": False},
            "status": {"account": "<not logged in>", "games_available": 0, "games_installed": 0, "config_directory": "C:/Users/me/.config/legendary"},
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
        }
        stdout = io.StringIO()
        with patch.object(cli, "build_legendary_status_report", return_value=fake_report):
            with redirect_stdout(stdout):
                result = cli.main(["legendary-status"])

        self.assertEqual(result, 0)
        self.assertIn("legendary_account=<not logged in>", stdout.getvalue())

    def test_legendary_import_auth_reports_failure(self) -> None:
        fake_report = {
            "legendary_path": "C:/Tools/legendary.exe",
            "session": {"config_path": "C:/Users/me/AppData/Local/EpicGamesLauncher/Saved/Config/Windows/GameUserSettings.ini", "remember_me_present": False, "remember_me_data_present": False},
            "exit_code": 1,
            "stdout": "",
            "stderr": "No EGS login session found",
            "error": "legendary auth import failed",
        }
        stdout = io.StringIO()
        with patch.object(cli, "import_legendary_auth", return_value=fake_report):
            with redirect_stdout(stdout):
                result = cli.main(["legendary-import-auth"])

        self.assertEqual(result, 1)
        self.assertIn("legendary_recommendation=If RememberMe is missing", stdout.getvalue())

    def test_legendary_list_ue_writes_reports(self) -> None:
        fake_report = {
            "legendary_path": "C:/Tools/legendary.exe",
            "session": {"remember_me_present": True, "remember_me_data_present": True},
            "summary": {"total_records": 12, "has_titles": 12},
            "records": [{"app_name": "GameAnimationSample", "app_title": "Game Animation Sample"}],
            "exit_code": 0,
            "stdout": "[]",
            "stderr": "",
        }
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "legendary_ue"
            stdout = io.StringIO()
            with patch.object(cli, "list_legendary_ue_assets", return_value=fake_report):
                with redirect_stdout(stdout):
                    result = cli.main(["legendary-list-ue", "--output-dir", str(output_dir)])

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "legendary_ue_assets.json").exists())
            self.assertTrue((output_dir / "legendary_ue_assets.md").exists())
            self.assertIn("legendary_ue_total_records=12", stdout.getvalue())

    def test_legendary_install_owned_reports_failure(self) -> None:
        fake_report = {
            "legendary_path": "C:/Tools/legendary.exe",
            "app_name": "Game Animation Sample",
            "base_path": "C:/Temp/downloads",
            "exit_code": 1,
            "stdout": "",
            "stderr": "not found",
            "error": "legendary install failed",
        }
        stdout = io.StringIO()
        with patch.object(cli, "install_legendary_asset", return_value=fake_report):
            with redirect_stdout(stdout):
                result = cli.main(["legendary-install-owned", "--app-name", "Game Animation Sample"])

        self.assertEqual(result, 1)
        self.assertIn("legendary_recommendation=If install fails while you own the item", stdout.getvalue())

    def test_inventory_epic_vault_cache_writes_reports(self) -> None:
        fake_entries = [
            {
                "title": "Lighthouse Pack",
                "listing_uid": "uid-1",
                "format": "unreal-engine",
                "cache_path": "C:/VaultCache/Lighthouse",
                "classification": "environment_art_heavy",
                "extractability_notes": "Good candidate for static mesh + texture extraction.",
                "stats": {
                    "static_mesh_candidates": 12,
                    "skeletal_mesh_candidates": 0,
                    "animation_candidates": 0,
                    "texture_candidates": 30,
                    "sound_candidates": 0,
                    "blueprint_candidates": 2,
                    "umap_files": 1,
                },
            }
        ]
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "inventory"
            stdout = io.StringIO()
            with patch.object(cli, "build_local_epic_vault_inventory", return_value=fake_entries):
                with redirect_stdout(stdout):
                    result = cli.main(["inventory-epic-vault-cache", "--output-dir", str(output_dir)])

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "epic_vault_inventory.json").exists())
            self.assertTrue((output_dir / "epic_vault_inventory.md").exists())
            self.assertIn("epic_vault_inventory_count=1", stdout.getvalue())

    def test_inventory_epic_vault_cache_include_launcher_cache_writes_combined_report(self) -> None:
        fake_report = {
            "confirmed_cached_entries": [{"title": "Lighthouse Pack"}],
            "launcher_cache_candidates": [{"family": "Lyra"}],
            "extraction_readiness": {"can_extract_now": True, "recommended_path": "Use FModel"},
        }
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "inventory"
            stdout = io.StringIO()
            with patch.object(cli, "build_local_epic_library_report", return_value=fake_report):
                with redirect_stdout(stdout):
                    result = cli.main(["inventory-epic-vault-cache", "--include-launcher-cache", "--output-dir", str(output_dir)])

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "epic_library_report.json").exists())
            self.assertTrue((output_dir / "epic_library_report.md").exists())
            self.assertIn("epic_library_confirmed_cached=1", stdout.getvalue())

    def test_inventory_epic_launcher_cache_writes_reports(self) -> None:
        fake_entries = [{"family": "Lyra", "display_name": "Lyra", "classification": "character_animation", "confidence": "launcher_cache_candidate", "notes": "note", "versions": [], "raw_hits": [], "source_files": []}]
        fake_readiness = {"can_extract_now": True, "recommended_path": "Use FModel"}
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "inventory"
            stdout = io.StringIO()
            with patch.object(cli, "build_local_epic_launcher_cache_candidates", return_value=fake_entries):
                with patch.object(cli, "build_local_epic_extraction_readiness", return_value=fake_readiness):
                    with redirect_stdout(stdout):
                        result = cli.main(["inventory-epic-launcher-cache", "--output-dir", str(output_dir)])

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "epic_launcher_inventory.json").exists())
            self.assertTrue((output_dir / "epic_launcher_inventory.md").exists())
            self.assertIn("epic_launcher_candidate_count=1", stdout.getvalue())

    def test_emit_epic_cache_extractor_wave_writes_manifest(self) -> None:
        fake_entries = [{"title": "Lighthouse Pack"}]
        fake_jobs = [{"pack_id": "SHARED_EPIC_LIGHTHOUSE_01"}]
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "extractors"
            stdout = io.StringIO()
            with patch.object(cli, "build_local_epic_vault_inventory", return_value=fake_entries):
                with patch.object(cli, "emit_epic_cache_extractor_wave", return_value=fake_jobs):
                    with redirect_stdout(stdout):
                        result = cli.main(["emit-epic-cache-extractor-wave", "--output-dir", str(output_dir)])

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "epic_cache_extractor_wave.json").exists())
            self.assertIn("epic_cache_extractor_jobs=1", stdout.getvalue())

    def test_map_epic_library_writes_reports(self) -> None:
        fake_report = {
            "account_display_name": "angryowl91",
            "summary": {
                "total_records": 68,
                "ue_marketplace_records": 51,
                "engine_records": 8,
                "marketplace_asset_records": 30,
                "marketplace_sample_records": 13,
                "game_or_app_records": 17,
            },
            "records": [],
        }
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "epic_map"
            stdout = io.StringIO()
            with patch.object(cli, "build_online_epic_library_map", return_value=fake_report):
                with redirect_stdout(stdout):
                    result = cli.main(["map-epic-library", "--output-dir", str(output_dir)])

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "epic_online_library_map.json").exists())
            self.assertTrue((output_dir / "epic_online_library_map.md").exists())
            self.assertIn("epic_online_library_total=68", stdout.getvalue())

    def test_map_fab_library_writes_reports(self) -> None:
        fake_report = {
            "account_display_name": "angryowl91",
            "summary": {
                "total_records": 147,
                "downloadable_records": 147,
                "neutral_or_mixed_records": 60,
                "unreal_only_records": 87,
                "page_count": 7,
                "roman_candidate_count": 5,
                "format_counts": {"unreal-engine": 100, "fbx": 32},
                "listing_type_counts": {"3d-model": 50},
                "publisher_counts": {"Epic Games": 15},
            },
            "roman_candidates": [],
            "records": [],
        }
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "fab_map"
            stdout = io.StringIO()
            with patch("assetboy.providers.fab_hybrid.build_online_fab_library_map", return_value=fake_report):
                with redirect_stdout(stdout):
                    result = cli.main(["map-fab-library", "--output-dir", str(output_dir)])

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "fab_online_library_map.json").exists())
            self.assertTrue((output_dir / "fab_online_library_map.md").exists())
            self.assertIn("fab_online_library_total=147", stdout.getvalue())

    def test_map_quixel_library_writes_reports(self) -> None:
        fake_report = {
            "api": {"reachable": False, "megascans_folder": "", "zip_folders": [], "asset_count": 0, "category_counts": {}, "error": ""},
            "detected_roots": ["D:/Megascans"],
            "scanned_roots": [],
            "summary": {
                "detected_root_count": 1,
                "total_assets": 42,
                "category_counts": {"3d": 20, "surface": 22},
                "bridge_api_reachable": False,
            },
        }
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "quixel_map"
            stdout = io.StringIO()
            with patch.object(cli, "build_local_quixel_library_map", return_value=fake_report):
                with redirect_stdout(stdout):
                    result = cli.main(["map-quixel-library", "--output-dir", str(output_dir)])

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "quixel_library_map.json").exists())
            self.assertTrue((output_dir / "quixel_library_map.md").exists())
            self.assertIn("quixel_total_assets=42", stdout.getvalue())

    def test_map_all_libraries_writes_combined_reports(self) -> None:
        fake_report = {
            "summary": {
                "fab_owned_total": 147,
                "fab_neutral_or_mixed": 60,
                "fab_unreal_only": 86,
                "fab_roman_candidates": 32,
                "epic_online_total": 68,
                "epic_marketplace_assets": 13,
                "epic_engines": 38,
                "epic_local_cached": 4,
                "epic_launcher_candidates": 19,
                "quixel_detected_roots": 1,
                "quixel_total_assets": 250,
                "detected_tool_count": 3,
            },
            "source_of_truth": {},
            "tools": {"FModel": "C:/SHARE/Tools/FModel/FModel.exe"},
            "high_value": {"fab_roman_candidates": [], "local_extract_candidates": []},
            "fab_online": {"summary": {"total_records": 147}, "records": [], "roman_candidates": []},
            "epic_online": {"summary": {"total_records": 68}, "records": []},
            "epic_local": {"confirmed_cached_entries": [], "launcher_cache_candidates": [], "extraction_readiness": {}},
            "quixel_local": {
                "api": {"reachable": False},
                "detected_roots": ["D:/Megascans"],
                "scanned_roots": [],
                "summary": {"detected_root_count": 1, "total_assets": 250, "category_counts": {}, "bridge_api_reachable": False},
            },
        }
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "combined_map"
            stdout = io.StringIO()
            with patch.object(cli, "build_combined_library_map", return_value=fake_report):
                with redirect_stdout(stdout):
                    result = cli.main(["map-all-libraries", "--output-dir", str(output_dir)])

            self.assertEqual(result, 0)
            self.assertTrue((output_dir / "combined_library_map.json").exists())
            self.assertTrue((output_dir / "combined_library_map.md").exists())
            self.assertTrue((output_dir / "fab_online_library_map.json").exists())
            self.assertTrue((output_dir / "epic_online_library_map.json").exists())
            self.assertTrue((output_dir / "epic_library_report.json").exists())
            self.assertTrue((output_dir / "quixel_library_map.json").exists())
            self.assertIn("combined_fab_owned_total=147", stdout.getvalue())
            self.assertIn("combined_quixel_total_assets=250", stdout.getvalue())

    def test_emit_fab_dummy_project_wave_writes_reports(self) -> None:
        fake_report = {
            "do_first": [{"pack_id": "SHARED_EPIC_ANM_GAME_ANIMATION_SAMPLE_ABCD1234", "title": "Game Animation Sample"}],
            "do_later": [{"pack_id": "SHARED_EPIC_ENV_CITY_SAMPLE_BUILDINGS_1234ABCD", "title": "City Sample Buildings"}],
            "skip": [{"pack_id": "SHARED_EPIC_MISC_BASIC_MONTAGE_1234ABCD", "title": "Basic Montage Sequence Manager"}],
            "emitted_jobs": [
                {
                    "pack_id": "SHARED_EPIC_ANM_GAME_ANIMATION_SAMPLE_ABCD1234",
                    "job_output_dir": "C:/Temp/fab_dummy_project_wave/SHARED_EPIC_ANM_GAME_ANIMATION_SAMPLE_ABCD1234",
                }
            ],
        }
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "fab_dummy_project_wave"
            stdout = io.StringIO()
            with patch.object(cli, "emit_fab_dummy_project_wave", return_value=fake_report):
                with redirect_stdout(stdout):
                    result = cli.main(
                        [
                            "emit-fab-dummy-project-wave",
                            "--output-dir",
                            str(output_dir),
                            "--max-jobs",
                            "1",
                        ]
                    )

            self.assertEqual(result, 0)
            self.assertIn("fab_dummy_project_do_first=1", stdout.getvalue())
            self.assertIn("fab_dummy_project_emitted_jobs=1", stdout.getvalue())
            self.assertIn("fab_dummy_project_pack=SHARED_EPIC_ANM_GAME_ANIMATION_SAMPLE_ABCD1234", stdout.getvalue())

    def test_emit_arena_owned_wave_writes_reports(self) -> None:
        fake_report = {
            "summary": {
                "direct_candidate_count": 4,
                "dummy_animation_job_count": 3,
                "dummy_environment_job_count": 1,
                "cached_animation_source_count": 2,
                "cached_environment_source_count": 1,
                "action_source_count": 5,
            },
            "roman_targets": {
                "RA_PACK_CHR_CORE_SLICE_01": {
                    "primary_direct_candidate": {"title": "Survival Character FREE"},
                },
                "RA_PACK_CHR_DUELIST_SLICE_01": {
                    "primary_direct_candidate": {"title": "Warrior"},
                },
            },
        }
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "arena_owned_wave"
            stdout = io.StringIO()
            with patch.object(cli, "emit_arena_owned_wave", return_value=fake_report):
                with redirect_stdout(stdout):
                    result = cli.main(
                        [
                            "emit-arena-owned-wave",
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            self.assertEqual(result, 0)
            self.assertIn("arena_owned_wave_direct_candidates=4", stdout.getvalue())
            self.assertIn("arena_owned_wave_primary=RA_PACK_CHR_CORE_SLICE_01:Survival Character FREE", stdout.getvalue())

    def test_emit_arena_extraction_wave_writes_reports(self) -> None:
        fake_report = {
            "summary": {
                "cached_extractors": 3,
                "dummy_project_extractors": 4,
                "total_extractors": 7,
            },
            "local_cached_extractors": [
                {"pack_id": "SHARED_EPIC_GASP_BASIC_TEMPLATE_FOR_FPS_WITH_02"},
            ],
            "dummy_project_extractors": [
                {"pack_id": "SHARED_EPIC_ANM_GAMEANIMATIONSAMPLE_880E319A"},
            ],
        }
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "arena_extraction_wave"
            stdout = io.StringIO()
            with patch.object(cli, "emit_arena_extraction_wave", return_value=fake_report):
                with redirect_stdout(stdout):
                    result = cli.main(
                        [
                            "emit-arena-extraction-wave",
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            self.assertEqual(result, 0)
            self.assertIn("arena_extraction_cached_extractors=3", stdout.getvalue())
            self.assertIn("arena_extraction_dummy_pack=SHARED_EPIC_ANM_GAMEANIMATIONSAMPLE_880E319A", stdout.getvalue())

    def test_fab_download_accepts_listing_url(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "fab-download",
                "--listing-url",
                "https://www.fab.com/listings/1234-5678-ABCD?ref=search",
                "--output",
                str(Path("downloads") / "asset.zip"),
            ]
        )
        self.assertEqual(args.command, "fab-download")
        self.assertEqual(args.listing_id, None)
        self.assertIn("/listings/1234-5678-ABCD", args.listing_url)

    def test_fab_download_direct_route_still_downloads_file(self) -> None:
        fake_downloader = unittest.mock.Mock()
        fake_downloader.inspect_listing.return_value = {
            "listing_id": "1234-5678-ABCD",
            "route": "direct",
            "download_access": "batch-direct",
            "format_codes": ["blender"],
            "asset_formats": [],
        }
        fake_downloader.download_listing_asset.return_value = {
            "format_code": "blender",
            "file_name": "asset.blend",
        }

        stdout = io.StringIO()
        with patch("assetboy.providers.fab_hybrid.FabHybridDownloader", return_value=fake_downloader):
            with redirect_stdout(stdout):
                result = cli.main(
                    [
                        "fab-download",
                        "--listing-id",
                        "1234-5678-ABCD",
                        "--output",
                        str(Path("downloads") / "asset.zip"),
                    ]
                )

        self.assertEqual(result, 0)
        self.assertIn("fab_download_route=direct", stdout.getvalue())
        self.assertIn("fab_download_success=", stdout.getvalue())
        fake_downloader.download_listing_asset.assert_called_once_with(
            "1234-5678-ABCD",
            str(Path("downloads") / "asset.zip"),
        )

    def test_fab_download_unreal_only_route_emits_epic_jobs(self) -> None:
        fake_downloader = unittest.mock.Mock()
        fake_downloader.inspect_listing.return_value = {
            "listing_id": "7630c789-72d9-437c-be26-5d1d5a7617bf",
            "route": "unreal-engine-only",
            "download_access": "unreal-engine-only",
            "format_codes": ["unreal-engine"],
            "title": "Factory Environment Collection",
            "catalog_item_id": "83fe932aaaca47b089e8d58f9a21fa74",
            "asset_formats": [],
        }
        uevault_artifacts = unittest.mock.Mock()
        uevault_artifacts.to_dict.return_value = {
            "output_dir": "C:\\temp\\ue",
            "job_spec_path": "C:\\temp\\ue\\epic_vault_job.json",
            "review_checklist_path": "C:\\temp\\ue\\review_checklist.md",
            "provenance_template_path": "C:\\temp\\ue\\provenance_template.json",
            "payload_target_path_file": "C:\\temp\\ue\\payload_target.txt",
            "script_path": "C:\\temp\\ue\\run_uevaultmanager.ps1",
            "command_template_path": "C:\\temp\\ue\\commands.txt",
            "uproject_path": "C:\\temp\\ue\\DummyProject.uproject",
            "download_target_path": "C:\\temp\\ue\\download",
            "staging_target_path": "C:\\temp\\ue\\staging",
        }
        dummy_artifacts = unittest.mock.Mock()
        dummy_artifacts.to_dict.return_value = {
            "output_dir": "C:\\temp\\dummy",
            "job_spec_path": "C:\\temp\\dummy\\epic_vault_job.json",
            "review_checklist_path": "C:\\temp\\dummy\\review_checklist.md",
            "provenance_template_path": "C:\\temp\\dummy\\provenance_template.json",
            "payload_target_path_file": "C:\\temp\\dummy\\payload_target.txt",
            "script_path": "C:\\temp\\dummy\\prepare_dummy_project.ps1",
            "command_template_path": "C:\\temp\\dummy\\commands.txt",
            "uproject_path": "C:\\temp\\dummy\\DummyProject.uproject",
            "download_target_path": "C:\\temp\\dummy\\download",
            "staging_target_path": "C:\\temp\\dummy\\staging",
        }

        stdout = io.StringIO()
        with patch("assetboy.providers.fab_hybrid.FabHybridDownloader", return_value=fake_downloader):
            with patch.object(cli, "has_unreal_editor_installation", return_value=True):
                with patch.object(cli, "emit_uevaultmanager_job", return_value=uevault_artifacts) as emit_uevaultmanager_job:
                    with patch.object(cli, "emit_epic_dummy_project_job", return_value=dummy_artifacts) as emit_epic_dummy_project_job:
                        with redirect_stdout(stdout):
                            result = cli.main(
                                [
                                    "fab-download",
                                    "--listing-id",
                                    "7630c789-72d9-437c-be26-5d1d5a7617bf",
                                    "--output",
                                    str(Path("downloads") / "asset.zip"),
                                ]
                            )

        self.assertEqual(result, 0)
        self.assertIn("fab_download_route=unreal-engine-only", stdout.getvalue())
        self.assertIn("fab_download_access=unreal-engine-only", stdout.getvalue())
        self.assertIn("fab_download_fallback=epic_vault", stdout.getvalue())
        self.assertIn("fab_download_vault_item=Factory Environment Collection", stdout.getvalue())
        self.assertIn("fab_download_unreal_editor_detected=true", stdout.getvalue())
        self.assertIn("fab_download_recommendation=If run_uevaultmanager.ps1 reports zero owned entries or metadata unavailable, switch to epic dummy-project fallback.", stdout.getvalue())
        self.assertIn("fab_download_recommended_script=C:\\temp\\dummy\\prepare_dummy_project.ps1", stdout.getvalue())
        emit_uevaultmanager_job.assert_called_once()
        emit_epic_dummy_project_job.assert_called_once()
        emitted_pack_id = emit_uevaultmanager_job.call_args.kwargs["pack_id"]
        self.assertTrue(emitted_pack_id.startswith("RA_PACK_FAB_7630C789"))
        self.assertEqual(
            emit_uevaultmanager_job.call_args.kwargs["vault_item"],
            "Factory Environment Collection",
        )
        self.assertEqual(emit_epic_dummy_project_job.call_args.kwargs["pack_id"], emitted_pack_id)

    def test_fab_download_unreal_only_without_unreal_editor_skips_listing(self) -> None:
        fake_downloader = unittest.mock.Mock()
        fake_downloader.inspect_listing.return_value = {
            "listing_id": "2ee66462-8c2b-4303-892c-83f7fc0d9b3e",
            "route": "unreal-engine-only",
            "download_access": "unreal-engine-only",
            "format_codes": ["unreal-engine"],
            "title": "Factory Environment Collection",
            "catalog_item_id": "83fe932aaaca47b089e8d58f9a21fa74",
            "asset_formats": [],
        }

        stdout = io.StringIO()
        with patch("assetboy.providers.fab_hybrid.FabHybridDownloader", return_value=fake_downloader):
            with patch.object(cli, "has_unreal_editor_installation", return_value=False):
                with patch.object(cli, "emit_uevaultmanager_job") as emit_uevaultmanager_job:
                    with patch.object(cli, "emit_epic_dummy_project_job") as emit_epic_dummy_project_job:
                        with redirect_stdout(stdout):
                            result = cli.main(
                                [
                                    "fab-download",
                                    "--listing-id",
                                    "2ee66462-8c2b-4303-892c-83f7fc0d9b3e",
                                    "--output",
                                    str(Path("downloads") / "asset.zip"),
                                ]
                            )

        self.assertEqual(result, 0)
        self.assertIn("fab_download_unreal_editor_detected=false", stdout.getvalue())
        self.assertIn("fab_download_skipped=true", stdout.getvalue())
        self.assertIn("fab_download_skip_reason=unreal-engine-only-without-unreal-editor", stdout.getvalue())
        self.assertIn("Skipping Unreal-only Fab listing because no Unreal Engine installation was detected on this machine.", stdout.getvalue())
        emit_uevaultmanager_job.assert_not_called()
        emit_epic_dummy_project_job.assert_not_called()

    def test_run_fab_batch_writes_summary_and_skip_report(self) -> None:
        fake_downloader = unittest.mock.Mock()
        fake_downloader.inspect_listing.side_effect = [
            {
                "listing_id": "direct-123",
                "route": "direct",
                "download_access": "batch-direct",
                "format_codes": ["blender"],
                "title": "Direct Asset",
                "catalog_item_id": "catalog-direct",
                "asset_formats": [],
            },
            {
                "listing_id": "ue-456",
                "route": "unreal-engine-only",
                "download_access": "unreal-engine-only",
                "format_codes": ["unreal-engine"],
                "title": "UE Asset",
                "catalog_item_id": "catalog-ue",
                "asset_formats": [],
            },
            RuntimeError("listing lookup failed"),
        ]
        fake_downloader.download_listing_asset.return_value = {
            "format_code": "blender",
            "file_name": "asset.blend",
        }

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            listing_file = root / "fab_listings.txt"
            listing_file.write_text(
                "\n".join(
                    [
                        "# comment",
                        "https://www.fab.com/listings/direct-123",
                        "https://www.fab.com/listings/ue-456",
                        "https://www.fab.com/listings/bad-789",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            output_dir = root / "fab_batch"

            stdout = io.StringIO()
            with patch("assetboy.providers.fab_hybrid.FabHybridDownloader", return_value=fake_downloader):
                with redirect_stdout(stdout):
                    result = cli.main(
                        [
                            "run-fab-batch",
                            "--listing-file",
                            str(listing_file),
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            self.assertEqual(result, 0)
            self.assertIn("fab_batch_total=3", stdout.getvalue())
            self.assertIn("fab_batch_downloaded=1", stdout.getvalue())
            self.assertIn("fab_batch_skipped=1", stdout.getvalue())
            self.assertIn("fab_batch_failed=1", stdout.getvalue())

            summary = json.loads((output_dir / "fab_batch_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["total"], 3)
            self.assertEqual(summary["downloaded"], 1)
            self.assertEqual(summary["skipped"], 1)
            self.assertEqual(summary["failed"], 1)
            self.assertEqual(summary["fallback_actions_path"], str(output_dir / "fab_batch_fallback_actions.json"))
            self.assertEqual(summary["fallback_actions_markdown_path"], str(output_dir / "fab_batch_fallback_actions.md"))

            skip_report = json.loads((output_dir / "fab_batch_skipped.json").read_text(encoding="utf-8"))
            self.assertEqual(skip_report["total_skipped"], 1)
            self.assertEqual(skip_report["items"][0]["listing_id"], "ue-456")
            self.assertEqual(skip_report["items"][0]["skip_reason"], "unreal-engine-only")

            fallback_actions = json.loads((output_dir / "fab_batch_fallback_actions.json").read_text(encoding="utf-8"))
            self.assertEqual(fallback_actions["total_actions"], 1)
            first_action = fallback_actions["actions"][0]
            self.assertEqual(first_action["listing_id"], "ue-456")
            self.assertEqual(first_action["skip_reason"], "unreal-engine-only")
            self.assertTrue(any("pwsh -NoProfile -ExecutionPolicy Bypass -File" in command for command in first_action["commands"]))
            self.assertTrue((output_dir / "fab_batch_fallback_actions.md").exists())

    def test_run_fab_batch_skips_direct_listing_that_needs_manual_library_or_purchase_flow(self) -> None:
        fake_downloader = unittest.mock.Mock()
        fake_downloader.inspect_listing.return_value = {
            "listing_id": "manual-123",
            "route": "direct",
            "download_access": "library-or-purchase-required",
            "format_codes": ["fbx", "glb"],
            "title": "Manual Roman Kit",
            "catalog_item_id": "catalog-manual",
            "asset_formats": [],
            "owned": False,
            "is_free": False,
        }

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            listing_file = root / "fab_listings.txt"
            listing_file.write_text("https://www.fab.com/listings/manual-123\n", encoding="utf-8")
            output_dir = root / "fab_batch"

            stdout = io.StringIO()
            with patch("assetboy.providers.fab_hybrid.FabHybridDownloader", return_value=fake_downloader):
                with redirect_stdout(stdout):
                    result = cli.main(
                        [
                            "run-fab-batch",
                            "--listing-file",
                            str(listing_file),
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            self.assertEqual(result, 0)
            self.assertIn("fab_batch_skipped=1", stdout.getvalue())
            summary = json.loads((output_dir / "fab_batch_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["skipped"], 1)
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["items"][0]["skip_reason"], "library-or-purchase-required")
            fake_downloader.download_listing_asset.assert_not_called()

    def test_run_fab_batch_emits_browser_fallback_job_for_library_or_purchase_skip(self) -> None:
        fake_downloader = unittest.mock.Mock()
        fake_downloader.inspect_listing.return_value = {
            "listing_id": "manual-123",
            "route": "direct",
            "download_access": "library-or-purchase-required",
            "format_codes": ["fbx", "glb"],
            "title": "Manual Roman Kit",
            "catalog_item_id": "catalog-manual",
            "asset_formats": [],
            "owned": False,
            "is_free": False,
        }

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            listing_file = root / "fab_listings.txt"
            listing_file.write_text("https://www.fab.com/listings/manual-123\n", encoding="utf-8")
            output_dir = root / "fab_batch"
            fake_browser_artifacts = unittest.mock.Mock(
                job_spec_path=output_dir / "fallback_jobs" / "RA_PACK_FAB_MANUAL12" / "browser_claim" / "browser_job.json"
            )

            with patch("assetboy.providers.fab_hybrid.FabHybridDownloader", return_value=fake_downloader):
                with patch.object(cli, "emit_browser_automation_job", return_value=fake_browser_artifacts) as emit_browser:
                    result = cli.main(
                        [
                            "run-fab-batch",
                            "--listing-file",
                            str(listing_file),
                            "--output-dir",
                            str(output_dir),
                            "--game-scope",
                            "shared",
                        ]
                    )

            self.assertEqual(result, 0)
            summary = json.loads((output_dir / "fab_batch_summary.json").read_text(encoding="utf-8"))
            item = summary["items"][0]
            self.assertEqual(item["skip_reason"], "library-or-purchase-required")
            self.assertEqual(item["fallback_game_scope"], "shared")
            self.assertIn("fallback_browser_job_spec", item)
            self.assertIn("run-browser-job", item["next_action"])
            self.assertIn("--retries 2", item["next_action"])
            emit_browser.assert_called_once()

    def test_run_fab_batch_emits_uevault_fallback_for_unreal_only_skip(self) -> None:
        fake_downloader = unittest.mock.Mock()
        fake_downloader.inspect_listing.return_value = {
            "listing_id": "ue-only-123",
            "route": "unreal-engine-only",
            "download_access": "unreal-engine-only",
            "format_codes": ["unreal-engine"],
            "title": "UE Roman Arena Kit",
            "catalog_item_id": "catalog-ue-only",
            "asset_formats": [],
            "owned": True,
            "is_free": True,
        }

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            listing_file = root / "fab_listings.txt"
            listing_file.write_text("https://www.fab.com/listings/ue-only-123\n", encoding="utf-8")
            output_dir = root / "fab_batch"
            fake_uevault = unittest.mock.Mock()
            fake_uevault.to_dict.return_value = {
                "job_spec_path": str(output_dir / "fallback_jobs" / "RA_PACK_FAB_UEONLY12" / "uevaultmanager" / "uevaultmanager_job.json"),
                "script_path": str(output_dir / "fallback_jobs" / "RA_PACK_FAB_UEONLY12" / "uevaultmanager" / "run_uevaultmanager.ps1"),
            }

            with patch("assetboy.providers.fab_hybrid.FabHybridDownloader", return_value=fake_downloader):
                with patch.object(cli, "emit_uevaultmanager_job", return_value=fake_uevault) as emit_uevault:
                    with patch.object(cli, "has_unreal_editor_installation", return_value=False):
                        with patch.object(cli, "emit_epic_dummy_project_job") as emit_dummy:
                            result = cli.main(
                                [
                                    "run-fab-batch",
                                    "--listing-file",
                                    str(listing_file),
                                    "--output-dir",
                                    str(output_dir),
                                    "--game-scope",
                                    "shared",
                                ]
                            )

            self.assertEqual(result, 0)
            summary = json.loads((output_dir / "fab_batch_summary.json").read_text(encoding="utf-8"))
            item = summary["items"][0]
            self.assertEqual(item["skip_reason"], "unreal-engine-only")
            self.assertEqual(item["fallback_game_scope"], "shared")
            self.assertIn("fallback_uevault_job_spec", item)
            self.assertIn("fallback_uevault_script", item)
            emit_uevault.assert_called_once()
            emit_dummy.assert_not_called()

    def test_run_fab_batch_emits_browser_fallback_when_direct_download_fails(self) -> None:
        fake_downloader = unittest.mock.Mock()
        fake_downloader.inspect_listing.return_value = {
            "listing_id": "direct-fail-123",
            "route": "direct",
            "download_access": "batch-direct",
            "format_codes": ["glb"],
            "title": "Direct Fail Pack",
            "catalog_item_id": "catalog-direct-fail",
            "asset_formats": [],
            "owned": True,
            "is_free": True,
        }
        fake_downloader.download_listing_asset.side_effect = RuntimeError("403 forbidden")

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            listing_file = root / "fab_listings.txt"
            listing_file.write_text("https://www.fab.com/listings/direct-fail-123\n", encoding="utf-8")
            output_dir = root / "fab_batch"

            def _emit_browser(**kwargs):
                spec_path = output_dir / "fallback_jobs" / kwargs["pack_id"] / "browser_claim" / "browser_job.json"
                spec_path.parent.mkdir(parents=True, exist_ok=True)
                spec_path.write_text("{}", encoding="utf-8")
                return unittest.mock.Mock(job_spec_path=spec_path)

            with patch("assetboy.providers.fab_hybrid.FabHybridDownloader", return_value=fake_downloader):
                with patch.object(cli, "emit_browser_automation_job", side_effect=_emit_browser):
                    result = cli.main(
                        [
                            "run-fab-batch",
                            "--listing-file",
                            str(listing_file),
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            self.assertEqual(result, 0)
            summary = json.loads((output_dir / "fab_batch_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["skipped"], 1)
            self.assertEqual(summary["failed"], 0)
            item = summary["items"][0]
            self.assertEqual(item["status"], "skipped")
            self.assertEqual(item["skip_reason"], "download-failed")
            self.assertIn("download_error", item)
            self.assertIn("fallback_browser_job_spec", item)

            fallback_actions = json.loads((output_dir / "fab_batch_fallback_actions.json").read_text(encoding="utf-8"))
            self.assertEqual(fallback_actions["total_actions"], 1)
            self.assertTrue(any("run-browser-job" in command for command in fallback_actions["actions"][0]["commands"]))

    def test_run_fab_batch_uses_collision_safe_fallback_pack_ids(self) -> None:
        fake_downloader = unittest.mock.Mock()
        fake_downloader.inspect_listing.side_effect = [
            {
                "listing_id": "manual-123",
                "route": "direct",
                "download_access": "library-or-purchase-required",
                "format_codes": ["fbx", "glb"],
                "title": "Manual Roman Kit A",
                "catalog_item_id": "catalog-manual-a",
                "asset_formats": [],
                "owned": False,
                "is_free": False,
            },
            {
                "listing_id": "manual-124",
                "route": "direct",
                "download_access": "library-or-purchase-required",
                "format_codes": ["fbx", "glb"],
                "title": "Manual Roman Kit B",
                "catalog_item_id": "catalog-manual-b",
                "asset_formats": [],
                "owned": False,
                "is_free": False,
            },
        ]

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            listing_file = root / "fab_listings.txt"
            listing_file.write_text(
                "\n".join(
                    [
                        "https://www.fab.com/listings/manual-123",
                        "https://www.fab.com/listings/manual-124",
                    ]
                ),
                encoding="utf-8",
            )
            output_dir = root / "fab_batch"

            def _emit_browser(**kwargs):
                spec_path = output_dir / "fallback_jobs" / kwargs["pack_id"] / "browser_claim" / "browser_job.json"
                spec_path.parent.mkdir(parents=True, exist_ok=True)
                spec_path.write_text("{}", encoding="utf-8")
                return unittest.mock.Mock(job_spec_path=spec_path)

            with patch("assetboy.providers.fab_hybrid.FabHybridDownloader", return_value=fake_downloader):
                with patch.object(cli, "emit_browser_automation_job", side_effect=_emit_browser):
                    result = cli.main(
                        [
                            "run-fab-batch",
                            "--listing-file",
                            str(listing_file),
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            self.assertEqual(result, 0)
            summary = json.loads((output_dir / "fab_batch_summary.json").read_text(encoding="utf-8"))
            pack_ids = [str(item.get("fallback_pack_id", "")) for item in summary["items"]]
            self.assertEqual(len(pack_ids), 2)
            self.assertEqual(len(set(pack_ids)), 2)
            self.assertTrue(all(pack_id.startswith("RA_PACK_FAB_") for pack_id in pack_ids))

            fallback_actions = json.loads((output_dir / "fab_batch_fallback_actions.json").read_text(encoding="utf-8"))
            self.assertEqual(fallback_actions["total_actions"], 2)
            self.assertTrue(all(action["ready"] for action in fallback_actions["actions"]))

    def test_run_fab_fallback_actions_executes_browser_jobs_and_writes_report(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_spec_path = root / "fallback_jobs" / "pack" / "browser_job.json"
            job_spec_path.parent.mkdir(parents=True, exist_ok=True)
            job_spec_path.write_text("{}", encoding="utf-8")
            actions_path = root / "fab_batch_fallback_actions.json"
            actions_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-04-04T00:00:00Z",
                        "listing_file": str(root / "listings.txt"),
                        "total_actions": 1,
                        "actions": [
                            {
                                "listing_ref": "https://www.fab.com/listings/manual-123",
                                "listing_id": "manual-123",
                                "skip_reason": "library-or-purchase-required",
                                "fallback_pack_id": "RA_PACK_FAB_MANUAL123",
                                "fallback_game_scope": "shared",
                                "ready": True,
                                "required_files": [
                                    {
                                        "kind": "browser_job_spec",
                                        "path": str(job_spec_path),
                                        "exists": True,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            fake_result = unittest.mock.Mock(
                execution_mode="playwright_structured",
                attempts=1,
                last_url="https://www.fab.com/listings/manual-123",
                artifacts_dir=root / "playwright_artifacts",
                browser_profile_dir=Path(".private/custom_profile"),
                error="",
            )
            stdout = io.StringIO()
            with patch("assetboy.execution.playwright_runner.run_browser_job", return_value=fake_result) as run_browser_job:
                with redirect_stdout(stdout):
                    result = cli.main(
                        [
                            "run-fab-fallback-actions",
                            "--actions-file",
                            str(actions_path),
                            "--execute",
                            "--retries",
                            "2",
                        ]
                    )

            self.assertEqual(result, 0)
            run_browser_job.assert_called_once()
            self.assertEqual(run_browser_job.call_args.kwargs["job_spec_path"], job_spec_path)
            self.assertTrue(run_browser_job.call_args.kwargs["execute"])
            self.assertFalse(run_browser_job.call_args.kwargs["dry_run"])
            self.assertEqual(run_browser_job.call_args.kwargs["retries"], 2)

            report = json.loads((actions_path.parent / "fab_batch_fallback_execution.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["executed_actions"], 1)
            self.assertEqual(report["summary"]["failed_actions"], 0)
            self.assertEqual(report["summary"]["pending_manual_actions"], 0)
            self.assertIn("fab_fallback_executed=1", stdout.getvalue())

    def test_run_fab_fallback_actions_returns_nonzero_when_browser_job_is_interactive_required(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_spec_path = root / "fallback_jobs" / "pack" / "browser_job.json"
            job_spec_path.parent.mkdir(parents=True, exist_ok=True)
            job_spec_path.write_text("{}", encoding="utf-8")
            actions_path = root / "fab_batch_fallback_actions.json"
            actions_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-04-04T00:00:00Z",
                        "listing_file": str(root / "listings.txt"),
                        "total_actions": 1,
                        "actions": [
                            {
                                "listing_ref": "https://www.fab.com/listings/manual-123",
                                "listing_id": "manual-123",
                                "skip_reason": "download-failed",
                                "fallback_pack_id": "RA_PACK_FAB_MANUAL123",
                                "fallback_game_scope": "shared",
                                "ready": True,
                                "required_files": [
                                    {
                                        "kind": "browser_job_spec",
                                        "path": str(job_spec_path),
                                        "exists": True,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            fake_result = unittest.mock.Mock(
                execution_mode="interactive_required",
                attempts=2,
                last_url="https://www.fab.com/login",
                artifacts_dir=root / "playwright_artifacts",
                browser_profile_dir=Path(".private/custom_profile"),
                error="login required",
            )
            stdout = io.StringIO()
            with patch("assetboy.execution.playwright_runner.run_browser_job", return_value=fake_result):
                with redirect_stdout(stdout):
                    result = cli.main(
                        [
                            "run-fab-fallback-actions",
                            "--actions-file",
                            str(actions_path),
                            "--execute",
                        ]
                    )

            self.assertEqual(result, 1)
            report = json.loads((actions_path.parent / "fab_batch_fallback_execution.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["failed_actions"], 1)
            self.assertEqual(report["summary"]["executed_actions"], 0)
            self.assertIn("fab_fallback_failed=1", stdout.getvalue())

    def test_run_fab_fallback_actions_marks_repair_required_as_pending_manual(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_spec_path = root / "fallback_jobs" / "pack" / "browser_job.json"
            job_spec_path.parent.mkdir(parents=True, exist_ok=True)
            job_spec_path.write_text("{}", encoding="utf-8")
            actions_path = root / "fab_batch_fallback_actions.json"
            actions_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-04-04T00:00:00Z",
                        "listing_file": str(root / "listings.txt"),
                        "total_actions": 1,
                        "actions": [
                            {
                                "listing_ref": "https://www.fab.com/listings/manual-123",
                                "listing_id": "manual-123",
                                "skip_reason": "auth-refresh-required",
                                "fallback_pack_id": "RA_PACK_FAB_MANUAL123",
                                "fallback_game_scope": "shared",
                                "ready": True,
                                "required_files": [
                                    {
                                        "kind": "browser_job_spec",
                                        "path": str(job_spec_path),
                                        "exists": True,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            fake_result = unittest.mock.Mock(
                execution_mode="repair_required",
                attempts=0,
                last_url="",
                artifacts_dir=None,
                browser_profile_dir=Path(".private/custom_profile"),
                error="Fab auth needs repair.",
                repair_reason="auth_state_stale",
                repair_command="python scripts/cli.py asset-factory fab-auth --reuse-profile",
                provider_runbook_id="fab",
            )

            result = None
            with patch("assetboy.execution.playwright_runner.run_browser_job", return_value=fake_result):
                result = cli.main(
                    [
                        "run-fab-fallback-actions",
                        "--actions-file",
                        str(actions_path),
                        "--execute",
                        "--require-complete",
                    ]
                )

            self.assertEqual(result, 1)
            report = json.loads((actions_path.parent / "fab_batch_fallback_execution.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["repair_required_actions"], 1)
            self.assertEqual(report["summary"]["pending_manual_actions"], 1)
            self.assertEqual(report["results"][0]["status"], "pending_manual")
            self.assertEqual(report["results"][0]["steps"][0]["status"], "repair_required")
            self.assertEqual(
                report["results"][0]["steps"][0]["repair_command"],
                "python scripts/cli.py asset-factory fab-auth --reuse-profile",
            )

    def test_run_fab_fallback_actions_runs_pwsh_scripts_when_enabled(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            script_path = root / "fallback_jobs" / "pack" / "uevault" / "run_uevaultmanager.ps1"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("Write-Host 'ok'\n", encoding="utf-8")
            actions_path = root / "fab_batch_fallback_actions.json"
            actions_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-04-04T00:00:00Z",
                        "listing_file": str(root / "listings.txt"),
                        "total_actions": 1,
                        "actions": [
                            {
                                "listing_ref": "https://www.fab.com/listings/ue-only-123",
                                "listing_id": "ue-only-123",
                                "skip_reason": "unreal-engine-only",
                                "fallback_pack_id": "RA_PACK_FAB_UEONLY",
                                "fallback_game_scope": "shared",
                                "ready": True,
                                "required_files": [
                                    {
                                        "kind": "uevault_script",
                                        "path": str(script_path),
                                        "exists": True,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            fake_completed = unittest.mock.Mock(returncode=0, stdout="ok", stderr="")
            with patch.object(cli.subprocess, "run", return_value=fake_completed) as subprocess_run:
                result = cli.main(
                    [
                        "run-fab-fallback-actions",
                        "--actions-file",
                        str(actions_path),
                        "--execute",
                        "--run-pwsh",
                    ]
                )

            self.assertEqual(result, 0)
            subprocess_run.assert_called_once()
            self.assertEqual(subprocess_run.call_args.args[0][0], "pwsh")
            report = json.loads((actions_path.parent / "fab_batch_fallback_execution.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["executed_actions"], 1)
            self.assertEqual(report["summary"]["failed_actions"], 0)

    def test_run_fab_fallback_actions_prepare_pack_hydrates_and_packets_browser_source(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            state_root = root / "state"
            source_dir = root / "downloads" / "RA_PACK_FAB_AUTOPREP"
            artifacts_dir = root / "playwright_artifacts"
            job_spec_path = root / "fallback_jobs" / "RA_PACK_FAB_AUTOPREP" / "browser_claim" / "browser_job.json"
            job_spec_path.parent.mkdir(parents=True, exist_ok=True)
            payload_target = library_root / "publish" / "flax_intake" / "shared" / "RA_PACK_FAB_AUTOPREP" / "payload"
            job_spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "fab",
                        "runtime": "playwright_mcp",
                        "pack_id": "RA_PACK_FAB_AUTOPREP",
                        "game_scope": "shared",
                        "source_url": "https://www.fab.com/listings/manual-123",
                        "search_terms": ["Roman Arch Pack"],
                        "login_required": True,
                        "destination": str(source_dir),
                        "notes": ["Auto-emitted for fallback testing."],
                    }
                ),
                encoding="utf-8",
            )
            (job_spec_path.parent / "payload_target.txt").write_text(str(payload_target) + "\n", encoding="utf-8")
            (job_spec_path.parent / "provenance_template.json").write_text(
                json.dumps(
                    {
                        "template_version": "assetboy.provenance.v2",
                        "pack_id": "RA_PACK_FAB_AUTOPREP",
                        "game_scope": "shared",
                        "lane": "manual_browser",
                        "source_adapter": "fab",
                        "payload_target_path": str(payload_target),
                        "required_fields": [],
                        "values": {
                            "license": "Fab Standard License",
                            "license_snapshot": "Captured from owned Fab listing.",
                            "author_or_vendor": "Arena Vendor",
                            "entitlement_note": "Claimed through owned Fab library.",
                        },
                        "notes": ["Auto-emitted for fallback testing."],
                    }
                ),
                encoding="utf-8",
            )
            actions_path = root / "fab_batch_fallback_actions.json"
            actions_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-04-04T00:00:00Z",
                        "listing_file": str(root / "listings.txt"),
                        "total_actions": 1,
                        "actions": [
                            {
                                "listing_ref": "https://www.fab.com/listings/manual-123",
                                "listing_id": "manual-123",
                                "skip_reason": "library-or-purchase-required",
                                "fallback_pack_id": "RA_PACK_FAB_AUTOPREP",
                                "fallback_game_scope": "shared",
                                "ready": True,
                                "required_files": [
                                    {
                                        "kind": "browser_job_spec",
                                        "path": str(job_spec_path),
                                        "exists": True,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def _fake_run_browser_job(**_kwargs):
                source_dir.mkdir(parents=True, exist_ok=True)
                payload_file = source_dir / "arch.glb"
                payload_file.write_bytes(b"mesh")
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                (artifacts_dir / "execution_log.json").write_text(
                    json.dumps([{"action": "download", "download_path": str(payload_file)}]),
                    encoding="utf-8",
                )
                return unittest.mock.Mock(
                    execution_mode="playwright_structured",
                    attempts=1,
                    last_url="https://www.fab.com/listings/manual-123",
                    artifacts_dir=artifacts_dir,
                    browser_profile_dir=Path(".private/custom_profile"),
                    error="",
                )

            with ExitStack() as stack:
                stack.enter_context(patch.object(cli, "asset_library_root", return_value=library_root))
                stack.enter_context(patch("assetboy.workflows.pack_pipeline.asset_library_root", return_value=library_root))
                stack.enter_context(patch("assetboy.workflows.pack_pipeline.state_root", return_value=state_root))
                stack.enter_context(patch("assetboy.workflows.flax_wrapper.asset_library_root", return_value=library_root))
                stack.enter_context(patch("assetboy.workflows.flax_wrapper.state_root", return_value=state_root))
                stack.enter_context(patch("assetboy.execution.playwright_runner.run_browser_job", side_effect=_fake_run_browser_job))
                result = cli.main(
                    [
                        "run-fab-fallback-actions",
                        "--actions-file",
                        str(actions_path),
                        "--execute",
                        "--prepare-pack",
                        "--auto-intake",
                        "--cleanup-mode",
                        "skip",
                    ]
                )

            self.assertEqual(result, 0)
            provenance = json.loads((source_dir / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["lane"], "manual_browser")
            self.assertEqual(provenance["source_adapter"], "fab")
            self.assertEqual(provenance["license"], "Fab Standard License")
            self.assertEqual(provenance["author_or_vendor"], "Arena Vendor")
            self.assertEqual(provenance["downloaded_filename"], "arch.glb")
            self.assertEqual(provenance["payload_target_path"], str(payload_target.resolve()))

            hydration = json.loads((source_dir / "provenance_hydration_report.json").read_text(encoding="utf-8"))
            self.assertEqual(hydration["status"], "completed")
            self.assertEqual(hydration["payload_file_count"], 1)

            report = json.loads((actions_path.parent / "fab_batch_fallback_execution.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["executed_actions"], 1)
            self.assertEqual(report["summary"]["auto_intake_passed"], 1)
            self.assertEqual(report["summary"]["pending_manual_actions"], 0)
            step = report["results"][0]["steps"][0]
            self.assertEqual(step["status"], "executed")
            self.assertEqual(step["prepare_pack"]["current_state"], "packeted")
            self.assertTrue(step["auto_intake"]["pass"])
            packet_path = library_root / "publish" / "flax_intake" / "shared" / "RA_PACK_FAB_AUTOPREP" / "packet.json"
            self.assertTrue(packet_path.exists())
            self.assertTrue(
                (library_root / "publish" / "flax_intake" / "shared" / "RA_PACK_FAB_AUTOPREP" / "handoff_receipt.json").exists()
            )

    def test_run_fab_fallback_actions_prepare_pack_marks_incomplete_provenance_pending_manual(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            state_root = root / "state"
            source_dir = root / "downloads" / "RA_PACK_FAB_PENDING"
            artifacts_dir = root / "playwright_artifacts"
            job_spec_path = root / "fallback_jobs" / "RA_PACK_FAB_PENDING" / "browser_claim" / "browser_job.json"
            job_spec_path.parent.mkdir(parents=True, exist_ok=True)
            payload_target = library_root / "publish" / "flax_intake" / "shared" / "RA_PACK_FAB_PENDING" / "payload"
            job_spec_path.write_text(
                json.dumps(
                    {
                        "source_adapter": "fab",
                        "runtime": "playwright_mcp",
                        "pack_id": "RA_PACK_FAB_PENDING",
                        "game_scope": "shared",
                        "source_url": "https://www.fab.com/listings/manual-124",
                        "search_terms": ["Roman Prop Pack"],
                        "login_required": True,
                        "destination": str(source_dir),
                        "notes": [],
                    }
                ),
                encoding="utf-8",
            )
            (job_spec_path.parent / "payload_target.txt").write_text(str(payload_target) + "\n", encoding="utf-8")
            (job_spec_path.parent / "provenance_template.json").write_text(
                json.dumps(
                    {
                        "template_version": "assetboy.provenance.v2",
                        "pack_id": "RA_PACK_FAB_PENDING",
                        "game_scope": "shared",
                        "lane": "manual_browser",
                        "source_adapter": "fab",
                        "payload_target_path": str(payload_target),
                        "required_fields": [],
                        "values": {},
                        "notes": [],
                    }
                ),
                encoding="utf-8",
            )
            actions_path = root / "fab_batch_fallback_actions.json"
            actions_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-04-04T00:00:00Z",
                        "listing_file": str(root / "listings.txt"),
                        "total_actions": 1,
                        "actions": [
                            {
                                "listing_ref": "https://www.fab.com/listings/manual-124",
                                "listing_id": "manual-124",
                                "skip_reason": "library-or-purchase-required",
                                "fallback_pack_id": "RA_PACK_FAB_PENDING",
                                "fallback_game_scope": "shared",
                                "ready": True,
                                "required_files": [
                                    {
                                        "kind": "browser_job_spec",
                                        "path": str(job_spec_path),
                                        "exists": True,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def _fake_run_browser_job(**_kwargs):
                source_dir.mkdir(parents=True, exist_ok=True)
                payload_file = source_dir / "prop.glb"
                payload_file.write_bytes(b"mesh")
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                (artifacts_dir / "execution_log.json").write_text(
                    json.dumps([{"action": "download", "download_path": str(payload_file)}]),
                    encoding="utf-8",
                )
                return unittest.mock.Mock(
                    execution_mode="playwright_structured",
                    attempts=1,
                    last_url="https://www.fab.com/listings/manual-124",
                    artifacts_dir=artifacts_dir,
                    browser_profile_dir=Path(".private/custom_profile"),
                    error="",
                )

            with ExitStack() as stack:
                stack.enter_context(patch.object(cli, "asset_library_root", return_value=library_root))
                stack.enter_context(patch("assetboy.workflows.pack_pipeline.asset_library_root", return_value=library_root))
                stack.enter_context(patch("assetboy.workflows.pack_pipeline.state_root", return_value=state_root))
                stack.enter_context(patch("assetboy.workflows.flax_wrapper.asset_library_root", return_value=library_root))
                stack.enter_context(patch("assetboy.workflows.flax_wrapper.state_root", return_value=state_root))
                stack.enter_context(patch("assetboy.execution.playwright_runner.run_browser_job", side_effect=_fake_run_browser_job))
                result = cli.main(
                    [
                        "run-fab-fallback-actions",
                        "--actions-file",
                        str(actions_path),
                        "--execute",
                        "--prepare-pack",
                        "--cleanup-mode",
                        "skip",
                        "--require-complete",
                    ]
                )

            self.assertEqual(result, 1)
            provenance = json.loads((source_dir / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["lane"], "manual_browser")
            self.assertEqual(provenance["source_adapter"], "fab")
            self.assertEqual(provenance["downloaded_filename"], "prop.glb")

            report = json.loads((actions_path.parent / "fab_batch_fallback_execution.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["executed_actions"], 0)
            self.assertEqual(report["summary"]["pending_manual_actions"], 1)
            self.assertEqual(report["summary"]["failed_actions"], 0)
            step = report["results"][0]["steps"][0]
            self.assertEqual(step["status"], "pending_manual")
            self.assertNotIn("prepare_pack", step)
            self.assertIn("provenance.license is missing.", step["hydration"]["validation_errors"])

    def test_fab_fallback_end_to_end_promotes_shared_pack_into_readiness(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            library_root = root / "library"
            state_root = root / "state"
            manual_drop_root = root / "manual_drop"
            imported_root = root / "imported"
            listing_file = root / "fab_listings.txt"
            listing_file.write_text("https://www.fab.com/listings/manual-123\n", encoding="utf-8")
            output_dir = root / "fab_batch"

            fake_downloader = unittest.mock.Mock()
            fake_downloader.inspect_listing.return_value = {
                "listing_id": "manual-123",
                "route": "direct",
                "download_access": "library-or-purchase-required",
                "title": "Roman Arch Pack",
                "catalog_item_id": "catalog-arch",
                "asset_formats": [],
            }

            def _publish_payload_dir(*, game_scope: str, pack_id: str) -> Path:
                return library_root / "publish" / "flax_intake" / game_scope / pack_id / "payload"

            with ExitStack() as stack:
                stack.enter_context(patch("assetboy.providers.fab_hybrid.FabHybridDownloader", return_value=fake_downloader))
                stack.enter_context(patch.object(cli, "_resolve_fab_pack_id", return_value="SHARED_HIST_ARCH_ROMAN_CORE_01"))
                stack.enter_context(patch("assetboy.providers.browser_automation.manual_drop_dir", return_value=manual_drop_root))
                stack.enter_context(patch("assetboy.providers.browser_automation.publish_payload_dir", side_effect=_publish_payload_dir))
                stack.enter_context(patch.object(cli, "asset_library_root", return_value=library_root))
                stack.enter_context(patch.object(cli, "state_root", return_value=state_root))
                stack.enter_context(patch.object(cli, "imported_packs_dir", return_value=imported_root))
                stack.enter_context(patch("assetboy.library.paths.asset_library_root", return_value=library_root))
                stack.enter_context(patch("assetboy.workflows.pack_pipeline.asset_library_root", return_value=library_root))
                stack.enter_context(patch("assetboy.workflows.pack_pipeline.state_root", return_value=state_root))
                stack.enter_context(patch("assetboy.workflows.flax_wrapper.asset_library_root", return_value=library_root))
                stack.enter_context(patch("assetboy.workflows.flax_wrapper.state_root", return_value=state_root))

                batch_result = cli.main(
                    [
                        "run-fab-batch",
                        "--listing-file",
                        str(listing_file),
                        "--output-dir",
                        str(output_dir),
                        "--game-scope",
                        "shared",
                    ]
                )
                self.assertEqual(batch_result, 0)

                actions_path = output_dir / "fab_batch_fallback_actions.json"
                actions_payload = json.loads(actions_path.read_text(encoding="utf-8"))
                browser_job_path = Path(actions_payload["actions"][0]["required_files"][0]["path"])
                template_path = browser_job_path.parent / "provenance_template.json"
                template = json.loads(template_path.read_text(encoding="utf-8"))
                template["values"]["license"] = "Fab Standard License"
                template["values"]["license_snapshot"] = "Captured from owned Fab listing."
                template["values"]["author_or_vendor"] = "Arena Vendor"
                template["values"]["entitlement_note"] = "Claimed through owned Fab library."
                template_path.write_text(json.dumps(template), encoding="utf-8")

                def _fake_run_browser_job(*, job_spec_path: Path, **_kwargs):
                    job_payload = json.loads(Path(job_spec_path).read_text(encoding="utf-8"))
                    source_dir = Path(job_payload["destination"])
                    source_dir.mkdir(parents=True, exist_ok=True)
                    payload_file = source_dir / "arch.glb"
                    payload_file.write_bytes(b"mesh")
                    artifacts_dir = root / "playwright_artifacts"
                    artifacts_dir.mkdir(parents=True, exist_ok=True)
                    (artifacts_dir / "execution_log.json").write_text(
                        json.dumps([{"action": "download", "download_path": str(payload_file)}]),
                        encoding="utf-8",
                    )
                    return unittest.mock.Mock(
                        execution_mode="playwright_structured",
                        attempts=1,
                        last_url="https://www.fab.com/listings/manual-123",
                        artifacts_dir=artifacts_dir,
                        browser_profile_dir=Path(".private/custom_profile"),
                        error="",
                    )

                stack.enter_context(patch("assetboy.execution.playwright_runner.run_browser_job", side_effect=_fake_run_browser_job))
                fallback_result = cli.main(
                    [
                        "run-fab-fallback-actions",
                        "--actions-file",
                        str(actions_path),
                        "--execute",
                        "--prepare-pack",
                        "--auto-intake",
                        "--cleanup-mode",
                        "skip",
                    ]
                )
                self.assertEqual(fallback_result, 0)

                fake_plan = SimpleNamespace(
                    game_scope="roman_arena",
                    gate_report=SimpleNamespace(pass_state=False),
                    tasks=[],
                )
                stdout = io.StringIO()
                with patch.object(cli, "_resolve_gate_catalog_paths", return_value=(Path("gate.json"), Path("catalog.json"))):
                    with patch.object(cli, "plan_roman_blockers", return_value=fake_plan):
                        with redirect_stdout(stdout):
                            readiness_code_before_import = cli._run_print_pack_readiness(
                                None,
                                None,
                                as_json=True,
                                groups=["shared_priority"],
                            )

                self.assertEqual(readiness_code_before_import, 0)
                readiness_before_import = json.loads(stdout.getvalue())
                row_before_import = {
                    row["pack_id"]: row for row in readiness_before_import["rows"]
                }["SHARED_HIST_ARCH_ROMAN_CORE_01"]
                self.assertEqual(row_before_import["state"], "ready_reviewed")
                self.assertFalse(row_before_import["imported"])
                self.assertFalse(row_before_import["gate_pass"])
                self.assertTrue(row_before_import["intake_validated"])
                self.assertEqual(row_before_import["handoff_source"], "handoff_receipt")
                self.assertTrue(str(row_before_import["handoff_receipt_path"]).endswith("handoff_receipt.json"))

                imported_pack_dir = imported_root / "SHARED_HIST_ARCH_ROMAN_CORE_01"
                imported_pack_dir.mkdir(parents=True, exist_ok=True)
                (imported_pack_dir / "imported.txt").write_text("imported\n", encoding="utf-8")

                stdout = io.StringIO()
                with patch.object(cli, "_resolve_gate_catalog_paths", return_value=(Path("gate.json"), Path("catalog.json"))):
                    with patch.object(cli, "plan_roman_blockers", return_value=fake_plan):
                        with redirect_stdout(stdout):
                            readiness_code = cli._run_print_pack_readiness(
                                None,
                                None,
                                as_json=True,
                                groups=["shared_priority"],
                            )

            self.assertEqual(readiness_code, 0)
            readiness_payload = json.loads(stdout.getvalue())
            row_by_pack = {row["pack_id"]: row for row in readiness_payload["rows"]}
            self.assertIn("SHARED_HIST_ARCH_ROMAN_CORE_01", row_by_pack)
            readiness_row = row_by_pack["SHARED_HIST_ARCH_ROMAN_CORE_01"]
            self.assertEqual(readiness_row["state"], "gate_pass")
            self.assertTrue(readiness_row["ready_reviewed"])
            self.assertTrue(readiness_row["imported"])
            self.assertTrue(readiness_row["gate_pass"])
            self.assertTrue(readiness_row["intake_validated"])
            self.assertEqual(readiness_row["intake_status"], "validated_pending_mcp")
            self.assertEqual(readiness_row["handoff_source"], "handoff_receipt")
            self.assertTrue(str(readiness_row["handoff_receipt_path"]).endswith("handoff_receipt.json"))
            self.assertEqual(readiness_row["source_pack_id"], "SHARED_HIST_ARCH_ROMAN_CORE_01")

    def test_legacy_dummy_project_alias_is_supported(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "emit-epic-dummy-project-job",
                "--pack-id",
                "RA_PACK_ENV_ARCH_UE_SLICE_01",
                "--source-url",
                "https://www.fab.com/listings/example",
            ]
        )
        self.assertIn(args.command, {"emit-epic-dummy-project", "emit-epic-dummy-project-job"})
