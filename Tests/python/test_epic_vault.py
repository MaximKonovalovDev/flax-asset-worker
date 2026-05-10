from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

import os
from types import SimpleNamespace
from unittest.mock import patch

from assetboy.providers.epic_vault import (
    SAFE_UEVAULT_CONFIG_TEXT,
    build_local_epic_launcher_cache_candidates,
    build_local_epic_library_report,
    build_local_epic_vault_inventory,
    build_online_epic_library_map,
    detect_unreal_editor_installations,
    detect_local_extractor_tools,
    discover_epic_launcher_cache_data_paths,
    emit_epic_cache_extractor_wave,
    default_uevaultmanager_safe_config_path,
    default_local_fab_library_db_path,
    emit_epic_dummy_project_job,
    emit_uevaultmanager_job,
    fetch_online_epic_library_records,
    has_unreal_editor_installation,
    load_uevault_user_data,
    parse_uevault_owned_asset_count,
    render_local_epic_library_report_markdown,
    render_local_epic_launcher_cache_markdown,
    render_local_epic_vault_inventory_markdown,
    render_online_epic_library_map_markdown,
    run_uevaultmanager_command,
    scan_cached_unreal_content,
    write_uevaultmanager_safe_config,
)


class EpicVaultTests(unittest.TestCase):
    def test_detect_unreal_editor_installations_scans_program_files_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            program_files = Path(temp_dir) / "Program Files"
            editor_path = program_files / "Epic Games" / "UE_5.5" / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
            editor_path.parent.mkdir(parents=True, exist_ok=True)
            editor_path.write_text("", encoding="utf-8")

            with patch.dict(os.environ, {"ProgramFiles": str(program_files)}, clear=False):
                detected = detect_unreal_editor_installations()
                self.assertIn(editor_path.resolve(), detected)
                self.assertTrue(has_unreal_editor_installation())

    def test_detect_unreal_editor_installations_supports_ue4_editor_name(self) -> None:
        with TemporaryDirectory() as temp_dir:
            program_files = Path(temp_dir) / "Program Files"
            editor_path = program_files / "Epic Games" / "UE_4.27" / "Engine" / "Binaries" / "Win64" / "UE4Editor.exe"
            editor_path.parent.mkdir(parents=True, exist_ok=True)
            editor_path.write_text("", encoding="utf-8")

            with patch.dict(os.environ, {"ProgramFiles": str(program_files)}, clear=False):
                detected = detect_unreal_editor_installations()
                self.assertIn(editor_path.resolve(), detected)

    def test_emit_uevaultmanager_job_writes_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "uevault"
            artifacts = emit_uevaultmanager_job(
                pack_id="RA_PACK_ENV_ARCH_UE_SLICE_01",
                game_scope="roman_arena",
                source_url="https://www.fab.com/listings/example",
                vault_item="Roman Arena Kit",
                output_dir=output_dir,
            )
            self.assertTrue(artifacts.job_spec_path.exists())
            self.assertTrue(artifacts.review_checklist_path.exists())
            self.assertTrue(artifacts.provenance_template_path.exists())
            self.assertTrue(artifacts.script_path.exists())
            self.assertTrue(artifacts.command_template_path.exists())
            self.assertTrue(artifacts.uproject_path.exists())

            payload = json.loads(artifacts.job_spec_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["method"], "uevaultmanager")
            self.assertEqual(payload["source_adapter"], "uevaultmanager")

            script_text = artifacts.script_path.read_text(encoding="utf-8")
            self.assertIn("Write-UevmConfig", script_text)
            self.assertIn("RememberMe", script_text)
            self.assertIn("$ImportFromLauncher", script_text)
            self.assertIn("$InteractiveAuth", script_text)
            self.assertIn("UEVM_DISABLE_NODRIVER", script_text)
            self.assertIn("$EnableNoDriver", script_text)
            self.assertIn("$SkipInstall", script_text)
            self.assertIn("--download-only", script_text)
            self.assertIn("status', '--json'", script_text)
            self.assertIn("$script:LastUevmExitCode", script_text)
            self.assertIn("Remove-Item -Path $ListOutput -Force", script_text)
            self.assertIn("list/output merge bug", script_text)
            self.assertIn("list', '--json', '-o', $ListOutput", script_text)
            self.assertIn("Owned asset list contained zero owned entries", script_text)
            self.assertIn("Fab ownership may exist, but UEVaultManager may still lack matching marketplace metadata", script_text)

            commands_text = artifacts.command_template_path.read_text(encoding="utf-8")
            self.assertIn("python -m assetboy.cli uevault-repair-config", commands_text)
            self.assertIn("python -m assetboy.cli uevault-status", commands_text)
            self.assertIn("python -m assetboy.cli uevault-import-auth", commands_text)
            self.assertIn("python -m assetboy.cli uevault-list-owned", commands_text)
            self.assertIn("python -m assetboy.cli uevault-install-owned", commands_text)
            self.assertIn("run_uevaultmanager.ps1", commands_text)
            self.assertIn('UEVaultManager -c ".\\uevaultmanager.safe.ini" auth --import', commands_text)
            self.assertIn("Recommended safe path", commands_text)
            self.assertIn("Browser-launching fallback (last resort only", commands_text)
            self.assertIn("-InteractiveAuth", commands_text)
            self.assertIn("-EnableNoDriver -InteractiveAuth", commands_text)
            self.assertIn("-SkipInstall", commands_text)
            self.assertIn("install", commands_text)
            self.assertIn("If the owned-assets list shows zero owned entries", commands_text)

    def test_write_uevaultmanager_safe_config_rewrites_minimal_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "uevaultmanager.safe.ini"
            config_path.write_text("broken = true\n", encoding="utf-8")

            written = write_uevaultmanager_safe_config(config_path)

            self.assertEqual(written, config_path)
            self.assertEqual(config_path.read_text(encoding="utf-8"), SAFE_UEVAULT_CONFIG_TEXT)
            self.assertNotIn("ignored_assets_filename_log", SAFE_UEVAULT_CONFIG_TEXT)

    def test_parse_uevault_owned_asset_count_supports_dict_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            payload_path = Path(temp_dir) / "owned.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "one": {"Owned": True},
                        "two": {"Owned": False},
                        "three": {"Owned": True},
                    }
                ),
                encoding="utf-8",
            )

            owned_count, total_count = parse_uevault_owned_asset_count(payload_path)

            self.assertEqual(owned_count, 2)
            self.assertEqual(total_count, 3)

    def test_run_uevaultmanager_command_uses_safe_config_and_disables_nodriver(self) -> None:
        fake_result = SimpleNamespace(returncode=0, stdout="{}", stderr="")
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "uevaultmanager.safe.ini"
            with patch("assetboy.providers.epic_vault.resolve_uevaultmanager_executable", return_value="UEVaultManager.exe"):
                with patch("assetboy.providers.epic_vault.subprocess.run", return_value=fake_result) as subprocess_run:
                    result = run_uevaultmanager_command(["status", "--offline", "--json"], config_path=config_path)

            self.assertIs(result, fake_result)
            self.assertEqual(config_path.read_text(encoding="utf-8"), SAFE_UEVAULT_CONFIG_TEXT)
            called_args = subprocess_run.call_args.args[0]
            self.assertEqual(called_args[:3], ["UEVaultManager.exe", "-c", str(config_path)])
            env = subprocess_run.call_args.kwargs["env"]
            self.assertEqual(env["UEVM_DISABLE_NODRIVER"], "1")

    def test_scan_cached_unreal_content_classifies_meshes_and_textures(self) -> None:
        with TemporaryDirectory() as temp_dir:
            content_root = Path(temp_dir) / "Content"
            (content_root / "Demo" / "Meshes").mkdir(parents=True, exist_ok=True)
            (content_root / "Demo" / "Textures").mkdir(parents=True, exist_ok=True)
            (content_root / "Demo" / "Animations").mkdir(parents=True, exist_ok=True)
            (content_root / "Demo" / "Blueprints").mkdir(parents=True, exist_ok=True)
            (content_root / "Demo" / "Meshes" / "SM_Rock.uasset").write_text("", encoding="utf-8")
            (content_root / "Demo" / "Meshes" / "SK_Guy.uasset").write_text("", encoding="utf-8")
            (content_root / "Demo" / "Animations" / "Run_Fwd.uasset").write_text("", encoding="utf-8")
            (content_root / "Demo" / "Textures" / "T_Rock_D.uasset").write_text("", encoding="utf-8")
            (content_root / "Demo" / "Blueprints" / "BP_Test.uasset").write_text("", encoding="utf-8")
            (content_root / "Demo" / "Map.umap").write_text("", encoding="utf-8")

            stats = scan_cached_unreal_content(content_root)

            self.assertEqual(stats["static_mesh_candidates"], 1)
            self.assertEqual(stats["skeletal_mesh_candidates"], 1)
            self.assertGreaterEqual(stats["animation_candidates"], 1)
            self.assertEqual(stats["texture_candidates"], 1)
            self.assertEqual(stats["blueprint_candidates"], 1)
            self.assertEqual(stats["umap_files"], 1)

    def test_build_local_epic_vault_inventory_reads_sqlite_rows(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "listings_v1.db"
            cache_root = root / "VaultCache" / "Lighthouse"
            content_root = cache_root / "data" / "Content" / "Pack" / "Meshes"
            content_root.mkdir(parents=True, exist_ok=True)
            (content_root / "SM_Cliff.uasset").write_text("", encoding="utf-8")

            import sqlite3

            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE local_listing (
                    uid TEXT PRIMARY KEY,
                    user_uid TEXT,
                    category_uid TEXT,
                    entitlement_uid TEXT,
                    title TEXT,
                    description TEXT,
                    average_rating REAL,
                    review_count INTEGER,
                    is_ai_forbidden INTEGER,
                    is_ai_generated INTEGER,
                    listing_type TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    published_at TEXT,
                    published_at_unix INTEGER,
                    last_updated_at TEXT,
                    thumbnail TEXT,
                    media TEXT,
                    user_seller_name TEXT,
                    user_profile_image_url TEXT,
                    user_cover_image_url TEXT,
                    category_name TEXT,
                    category_path TEXT,
                    category_slug TEXT
                );
                CREATE TABLE listing_acquisition (listing_uid TEXT, user_uid TEXT);
                CREATE TABLE download_meta (
                    id INTEGER PRIMARY KEY,
                    listing_uid TEXT,
                    format TEXT,
                    quality TEXT,
                    path TEXT,
                    platform_included TEXT,
                    is_converted INTEGER,
                    downloaded_at INTEGER,
                    cache_size INTEGER
                );
                """
            )
            conn.execute(
                "INSERT INTO local_listing (uid, title, thumbnail) VALUES (?, ?, ?)",
                ("uid-1", "Lighthouse Pack", "thumb"),
            )
            conn.execute(
                "INSERT INTO listing_acquisition (listing_uid, user_uid) VALUES (?, ?)",
                ("uid-1", "user-1"),
            )
            conn.execute(
                "INSERT INTO download_meta (id, listing_uid, format, path, cache_size) VALUES (?, ?, ?, ?, ?)",
                (1, "uid-1", "unreal-engine", str(cache_root), 1234),
            )
            conn.commit()
            conn.close()

            entries = build_local_epic_vault_inventory(db_path)

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["title"], "Lighthouse Pack")
            self.assertEqual(entries[0]["stats"]["static_mesh_candidates"], 1)
            self.assertEqual(entries[0]["classification"], "mixed_content")

    def test_render_local_epic_vault_inventory_markdown_mentions_extractability(self) -> None:
        markdown = render_local_epic_vault_inventory_markdown(
            [
                {
                    "listing_uid": "uid-1",
                    "title": "Lighthouse Pack",
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
        )

        self.assertIn("Lighthouse Pack", markdown)
        self.assertIn("Good candidate for static mesh + texture extraction.", markdown)
        self.assertIn("Static mesh candidates: `12`", markdown)

    def test_build_local_epic_launcher_cache_candidates_groups_versions(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_path = Path(temp_dir) / "OC_sample.dat"
            data_path.write_bytes(
                b"ContentExamples_5.3\x00ContentExamples_5.4\x00AnimStarterPack\x00FabPlugin_5.7\x00"
            )

            entries = build_local_epic_launcher_cache_candidates((data_path,))

            families = {entry["family"]: entry for entry in entries}
            self.assertIn("ContentExamples", families)
            self.assertEqual(families["ContentExamples"]["versions"], ["5.3", "5.4"])
            self.assertIn("AnimStarterPack", families)
            self.assertNotIn("FabPlugin", families)

    def test_render_local_epic_launcher_cache_markdown_mentions_versions(self) -> None:
        markdown = render_local_epic_launcher_cache_markdown(
            [
                {
                    "family": "ContentExamples",
                    "display_name": "ContentExamples (5.3, 5.4)",
                    "versions": ["5.3", "5.4"],
                    "raw_hits": ["ContentExamples_5.3", "ContentExamples_5.4"],
                    "source_files": ["C:/Saved/Data/OC_x.dat"],
                    "classification": "sample_project",
                    "confidence": "launcher_cache_candidate",
                    "notes": "Sample-project family detected.",
                }
            ]
        )

        self.assertIn("ContentExamples (5.3, 5.4)", markdown)
        self.assertIn("Versions: `5.3, 5.4`", markdown)

    def test_detect_local_extractor_tools_uses_shutil_which(self) -> None:
        def _fake_which(name: str) -> str | None:
            if name == "FModel.exe":
                return r"C:\Tools\FModel\FModel.exe"
            return None

        with patch("assetboy.providers.epic_vault.shutil.which", side_effect=_fake_which):
            detected = detect_local_extractor_tools()

        self.assertEqual(detected["fmodel"], r"C:\Tools\FModel\FModel.exe")
        self.assertNotIn("umodel", detected)

    def test_detect_local_extractor_tools_supports_absolute_fallback_path(self) -> None:
        fallback_path = r"C:\SHARE\Tools\FModel\FModel.exe"

        def _fake_exists(path_obj: Path) -> bool:
            return str(path_obj) == fallback_path

        with patch("assetboy.providers.epic_vault.shutil.which", return_value=None):
            with patch("pathlib.Path.exists", autospec=True, side_effect=_fake_exists):
                detected = detect_local_extractor_tools()

        self.assertEqual(detected["fmodel"], fallback_path)

    def test_build_local_epic_library_report_combines_sections(self) -> None:
        with patch("assetboy.providers.epic_vault.build_local_epic_vault_inventory", return_value=[{"title": "Lighthouse"}]):
            with patch("assetboy.providers.epic_vault.build_local_epic_launcher_cache_candidates", return_value=[{"family": "Lyra"}]):
                with patch(
                    "assetboy.providers.epic_vault.build_local_epic_extraction_readiness",
                    return_value={"can_extract_now": True, "recommended_path": "Use FModel"},
                ):
                    report = build_local_epic_library_report()

        self.assertEqual(len(report["confirmed_cached_entries"]), 1)
        self.assertEqual(len(report["launcher_cache_candidates"]), 1)
        self.assertTrue(report["extraction_readiness"]["can_extract_now"])

    def test_render_local_epic_library_report_markdown_mentions_sections(self) -> None:
        markdown = render_local_epic_library_report_markdown(
            {
                "confirmed_cached_entries": [
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
                ],
                "launcher_cache_candidates": [
                    {
                        "family": "Lyra",
                        "display_name": "Lyra (5.4, 5.5)",
                        "versions": ["5.4", "5.5"],
                        "raw_hits": ["Lyra_5.4", "Lyra_5.5"],
                        "source_files": ["C:/Saved/Data/OC_x.dat"],
                        "classification": "character_animation",
                        "confidence": "launcher_cache_candidate",
                        "notes": "Likely useful for skeletal meshes.",
                    }
                ],
                "extraction_readiness": {
                    "can_extract_now": True,
                    "recommended_path": "Use FModel",
                    "unreal_editor_paths": [r"C:\Program Files\Epic Games\UE_4.27\Engine\Binaries\Win64\UnrealEditor.exe"],
                    "extractor_tools": {"fmodel": r"C:\Tools\FModel\FModel.exe"},
                },
            }
        )

        self.assertIn("Confirmed cached owned entries: `1`", markdown)
        self.assertIn("Launcher cache candidate families: `1`", markdown)
        self.assertIn("Lyra (5.4, 5.5)", markdown)

    def test_emit_epic_cache_extractor_wave_emits_for_meshy_entries_only(self) -> None:
        fake_artifacts = unittest.mock.Mock()
        fake_artifacts.to_dict.return_value = {"job_spec_path": "job.json"}
        entries = [
            {
                "title": "Lighthouse Pack",
                "listing_uid": "uid-1",
                "cache_path": "C:/VaultCache/Lighthouse",
                "classification": "environment_art_heavy",
                "stats": {"static_mesh_candidates": 12, "skeletal_mesh_candidates": 0},
            },
            {
                "title": "Logic Only",
                "listing_uid": "uid-2",
                "cache_path": "C:/VaultCache/Logic",
                "classification": "mixed_content",
                "stats": {"static_mesh_candidates": 0, "skeletal_mesh_candidates": 0},
            },
        ]
        with TemporaryDirectory() as temp_dir:
            with patch("assetboy.providers.epic_vault.emit_extractor_job", return_value=fake_artifacts) as emit_job:
                emitted = emit_epic_cache_extractor_wave(entries, output_dir=Path(temp_dir))

        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0]["title"], "Lighthouse Pack")
        emit_job.assert_called_once()

    def test_load_uevault_user_data_reads_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            user_path = Path(temp_dir) / "user_data.json"
            user_path.write_text(json.dumps({"displayName": "angryowl91"}), encoding="utf-8")

            payload = load_uevault_user_data(user_path)

            self.assertEqual(payload["displayName"], "angryowl91")

    def test_fetch_online_epic_library_records_paginates(self) -> None:
        responses = [
            {"records": [{"catalogItemId": "one"}], "responseMetadata": {"nextCursor": "abc"}},
            {"records": [{"catalogItemId": "two"}], "responseMetadata": {}},
        ]

        def _fake_get(*_args, **_kwargs):
            payload = responses.pop(0)
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: payload,
            )

        with patch("assetboy.providers.epic_vault.requests.get", side_effect=_fake_get):
            records = fetch_online_epic_library_records({"access_token": "token"})

        self.assertEqual([item["catalogItemId"] for item in records], ["one", "two"])

    def test_build_online_epic_library_map_merges_catalog_titles(self) -> None:
        fake_records = [
            {
                "namespace": "ns-1",
                "catalogItemId": "cat-1",
                "appName": "app-1",
                "sandboxName": "UE Marketplace",
                "recordType": "APPLICATION",
                "acquisitionDate": "2026-03-01T00:00:00Z",
            },
            {
                "namespace": "ns-2",
                "catalogItemId": "cat-2",
                "appName": "app-2",
                "sandboxName": "Live",
                "recordType": "APPLICATION",
                "acquisitionDate": "2026-03-02T00:00:00Z",
            },
        ]
        with patch("assetboy.providers.epic_vault.fetch_online_epic_library_records", return_value=fake_records):
            with patch(
                "assetboy.providers.epic_vault.fetch_catalog_item_info",
                side_effect=[
                    {"title": "Roman Cave", "developer": "Dev A", "categories": [{"path": "assets/environments"}]},
                    {"title": "Warface", "developer": "Dev B", "categories": [{"path": "games"}]},
                ],
            ):
                report = build_online_epic_library_map({"access_token": "token", "displayName": "angryowl91"})

        self.assertEqual(report["summary"]["total_records"], 2)
        self.assertEqual(report["summary"]["ue_marketplace_records"], 1)
        self.assertEqual(report["records"][0]["title"], "Roman Cave")
        self.assertEqual(report["records"][0]["kind"], "marketplace_asset")
        self.assertEqual(report["records"][1]["kind"], "game_or_app")

    def test_render_online_epic_library_map_markdown_mentions_counts(self) -> None:
        markdown = render_online_epic_library_map_markdown(
            {
                "account_display_name": "angryowl91",
                "summary": {
                    "total_records": 3,
                    "ue_marketplace_records": 2,
                    "engine_records": 1,
                    "marketplace_asset_records": 1,
                    "marketplace_sample_records": 0,
                    "game_or_app_records": 1,
                },
                "records": [
                    {"title": "Roman Cave", "kind": "marketplace_asset", "sandbox_name": "UE Marketplace", "app_name": "roman_cave", "developer": "Dev", "seller_name": "", "categories": [{"path": "assets/environments"}]},
                    {"title": "Unreal Engine", "kind": "engine", "sandbox_name": "UE Marketplace", "app_name": "UE_5_7", "developer": "Epic Games", "seller_name": "", "categories": [{"path": "engines"}]},
                    {"title": "Warface", "kind": "game_or_app", "sandbox_name": "Live", "app_name": "warface", "developer": "Dev", "seller_name": "", "categories": [{"path": "games"}]},
                ],
            }
        )

        self.assertIn("Total records: `3`", markdown)
        self.assertIn("Marketplace Assets", markdown)
        self.assertIn("Roman Cave", markdown)

    def test_emit_epic_dummy_project_job_writes_uproject(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "dummy"
            project_dir = root / "DummyProject"
            artifacts = emit_epic_dummy_project_job(
                pack_id="RA_PACK_ENV_ARCH_UE_SLICE_01",
                game_scope="roman_arena",
                source_url="https://www.fab.com/listings/example",
                engine_association="5.3",
                project_name="DummyProject",
                project_dir=project_dir,
                output_dir=output_dir,
            )
            self.assertTrue(artifacts.job_spec_path.exists())
            self.assertTrue(artifacts.script_path.exists())
            self.assertTrue(artifacts.command_template_path.exists())
            self.assertTrue(artifacts.uproject_path.exists())

            project_payload = json.loads(artifacts.uproject_path.read_text(encoding="utf-8"))
            self.assertEqual(project_payload["EngineAssociation"], "5.3")
            self.assertEqual(project_payload["FileVersion"], 3)
