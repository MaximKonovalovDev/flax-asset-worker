import unittest
from pathlib import Path

from assetboy.cli_legacy import build_parser


class CliParserCommandsTests(unittest.TestCase):
    def test_parser_exposes_documented_runner_commands(self) -> None:
        parser = build_parser()
        subparsers_action = next(
            action for action in parser._actions if getattr(action, "choices", None)
        )
        choices = subparsers_action.choices
        expected = {
            "init-library-layout",
            "smoke-lanes",
            "run-kenney-batch",
            "run-game-icons",
            "run-font-batch",
            "run-vfx-batch",
            "run-animationgpt",
            "run-museum-batch",
            "run-vehicle-batch",
            "run-skybox-batch",
            "run-terrain-batch",
            "run-dialogue-batch",
            "write-packet",
            "run-bulk",
            "run-cleanup",
            "prepare-pack",
            "pack-status",
            "register-packet",
            "get-job-status",
            "uevault-repair-config",
            "uevault-status",
            "uevault-import-auth",
            "uevault-list-owned",
            "uevault-install-owned",
            "legendary-status",
            "legendary-import-auth",
            "legendary-list-ue",
            "legendary-install-owned",
            "seed-shared-browser-profile",
            "unity-auth",
            "unity-auth-status",
            "inventory-epic-vault-cache",
            "inventory-epic-launcher-cache",
            "emit-epic-cache-extractor-wave",
            "map-epic-library",
            "map-fab-library",
            "map-quixel-library",
            "map-all-libraries",
            "emit-fab-dummy-project-wave",
            "emit-arena-owned-wave",
            "emit-arena-extraction-wave",
            "emit-useful-harvest-wave",
            "print-pack-readiness",
            "sync-shared-priority",
            "list-pack-families",
            "emit-pack-family-plan",
            "print-batchability",
            "run-fab-fallback-actions",
            "emit-unity-download-wave",
            "run-unity-claim-wave",
            "unity-hub-status",
            "map-unity-owned-library",
            "unity-download-owned",
            "download-unity-owned-lightweights",
            "download-unity-owned-wave",
            "emit-unity-project-ingest-wave",
        }
        self.assertTrue(expected.issubset(set(choices)))

    def test_init_library_layout_parser_accepts_dry_run(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["init-library-layout", "--dry-run"])
        self.assertEqual(args.command, "init-library-layout")
        self.assertTrue(args.dry_run)

    def test_run_tts_batch_parser_accepts_provider_and_scope(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-tts-batch",
                "--text",
                "For Rome!",
                "--voice",
                "hero",
                "--provider",
                "elevenlabs",
                "--game-scope",
                "roman_arena",
                "--line-id",
                "DIA_HERO_TEST",
                "--dry-run",
            ]
        )
        self.assertEqual(args.command, "run-tts-batch")
        self.assertEqual(args.voice, "hero")
        self.assertEqual(args.provider, "elevenlabs")
        self.assertEqual(args.game_scope, "roman_arena")
        self.assertEqual(args.line_id, "DIA_HERO_TEST")
        self.assertTrue(args.dry_run)

    def test_run_dialogue_batch_parser_accepts_provider(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["run-dialogue-batch", "--provider", "edge_tts", "--text", "Welcome", "--voice", "announcer"]
        )
        self.assertEqual(args.command, "run-dialogue-batch")
        self.assertEqual(args.provider, "edge_tts")
        self.assertEqual(args.text, "Welcome")
        self.assertEqual(args.voice, "announcer")

    def test_smoke_lanes_parser_accepts_output_dir_and_json(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["smoke-lanes", "--output-dir", "state/generated/lane_smoke", "--json"]
        )
        self.assertEqual(args.command, "smoke-lanes")
        self.assertEqual(args.output_dir, Path("state/generated/lane_smoke"))
        self.assertTrue(args.as_json)

    def test_fab_auth_parser_accepts_explicit_browser_guard(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["fab-auth", "--allow-browser"])
        self.assertEqual(args.command, "fab-auth")
        self.assertTrue(args.allow_browser)

    def test_mixamo_auth_parser_accepts_explicit_browser_guard(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["mixamo-auth", "--allow-browser"])
        self.assertEqual(args.command, "mixamo-auth")
        self.assertTrue(args.allow_browser)

    def test_unity_auth_parser_accepts_explicit_browser_guard(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["unity-auth", "--allow-browser"])
        self.assertEqual(args.command, "unity-auth")
        self.assertTrue(args.allow_browser)

    def test_seed_shared_browser_profile_parser_accepts_custom_source(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "seed-shared-browser-profile",
                "--source-root",
                "C:/Users/me/AppData/Local/Google/Chrome/User Data",
                "--source-profile",
                "Profile 7",
                "--target-dir",
                "state/generated/browser_profile",
                "--force",
            ]
        )
        self.assertEqual(args.command, "seed-shared-browser-profile")
        self.assertEqual(args.source_profile, "Profile 7")
        self.assertEqual(args.target_dir, Path("state/generated/browser_profile"))
        self.assertTrue(args.force)

    def test_uevault_list_owned_parser_accepts_force_refresh(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["uevault-list-owned", "--output", "state/generated/owned.json", "--force-refresh"])
        self.assertEqual(args.command, "uevault-list-owned")
        self.assertEqual(args.output, Path("state/generated/owned.json"))
        self.assertTrue(args.force_refresh)

    def test_uevault_install_owned_parser_accepts_download_dir(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["uevault-install-owned", "--vault-item", "Roman Arena Kit", "--download-dir", "state/generated/epic_raw"]
        )
        self.assertEqual(args.command, "uevault-install-owned")
        self.assertEqual(args.vault_item, "Roman Arena Kit")
        self.assertEqual(args.download_dir, Path("state/generated/epic_raw"))

    def test_legendary_list_ue_parser_accepts_output_dir(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["legendary-list-ue", "--output-dir", "state/generated/legendary_ue"])
        self.assertEqual(args.command, "legendary-list-ue")
        self.assertEqual(args.output_dir, Path("state/generated/legendary_ue"))

    def test_legendary_install_owned_parser_accepts_base_path(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["legendary-install-owned", "--app-name", "Game Animation Sample", "--base-path", "state/generated/legendary_downloads"]
        )
        self.assertEqual(args.command, "legendary-install-owned")
        self.assertEqual(args.app_name, "Game Animation Sample")
        self.assertEqual(args.base_path, Path("state/generated/legendary_downloads"))

    def test_inventory_epic_vault_cache_parser_accepts_output_dir(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["inventory-epic-vault-cache", "--output-dir", "state/generated/epic_inventory"])
        self.assertEqual(args.command, "inventory-epic-vault-cache")
        self.assertEqual(args.output_dir, Path("state/generated/epic_inventory"))

    def test_inventory_epic_vault_cache_parser_accepts_launcher_cache_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["inventory-epic-vault-cache", "--include-launcher-cache"])
        self.assertEqual(args.command, "inventory-epic-vault-cache")
        self.assertTrue(args.include_launcher_cache)

    def test_inventory_epic_launcher_cache_parser_accepts_data_dir(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["inventory-epic-launcher-cache", "--data-dir", "C:/Users/me/AppData/Local/EpicGamesLauncher/Saved/Data"]
        )
        self.assertEqual(args.command, "inventory-epic-launcher-cache")
        self.assertEqual(args.data_dir, Path("C:/Users/me/AppData/Local/EpicGamesLauncher/Saved/Data"))

    def test_emit_epic_cache_extractor_wave_parser_accepts_output_dir(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["emit-epic-cache-extractor-wave", "--output-dir", "state/generated/epic_extractors"])
        self.assertEqual(args.command, "emit-epic-cache-extractor-wave")
        self.assertEqual(args.output_dir, Path("state/generated/epic_extractors"))

    def test_map_epic_library_parser_accepts_timeout(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["map-epic-library", "--timeout", "45", "--output-dir", "state/generated/epic_map"])
        self.assertEqual(args.command, "map-epic-library")
        self.assertEqual(args.timeout, 45.0)
        self.assertEqual(args.output_dir, Path("state/generated/epic_map"))

    def test_map_fab_library_parser_accepts_timeout(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["map-fab-library", "--timeout", "45", "--output-dir", "state/generated/fab_map"])
        self.assertEqual(args.command, "map-fab-library")
        self.assertEqual(args.timeout, 45.0)
        self.assertEqual(args.output_dir, Path("state/generated/fab_map"))

    def test_map_quixel_library_parser_accepts_extra_roots(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "map-quixel-library",
                "--timeout",
                "3",
                "--root",
                "D:/Megascans",
                "--root",
                "E:/Bridge/Megascans Library",
            ]
        )
        self.assertEqual(args.command, "map-quixel-library")
        self.assertEqual(args.timeout, 3.0)
        self.assertEqual(args.quixel_roots, ["D:/Megascans", "E:/Bridge/Megascans Library"])

    def test_map_all_libraries_parser_accepts_paths(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "map-all-libraries",
                "--db-path",
                "C:/ProgramData/Epic/EpicGamesLauncher/VaultCache/FabLibrary/listings_v1.db",
                "--data-dir",
                "C:/Users/me/AppData/Local/EpicGamesLauncher/Saved/Data",
                "--quixel-root",
                "D:/Megascans",
                "--timeout",
                "60",
            ]
        )
        self.assertEqual(args.command, "map-all-libraries")
        self.assertEqual(
            args.db_path,
            Path("C:/ProgramData/Epic/EpicGamesLauncher/VaultCache/FabLibrary/listings_v1.db"),
        )
        self.assertEqual(args.data_dir, Path("C:/Users/me/AppData/Local/EpicGamesLauncher/Saved/Data"))
        self.assertEqual(args.quixel_roots, ["D:/Megascans"])
        self.assertEqual(args.timeout, 60.0)

    def test_emit_fab_dummy_project_wave_parser_accepts_limits(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "emit-fab-dummy-project-wave",
                "--game-scope",
                "arena_shared",
                "--engine-association",
                "5.7",
                "--max-jobs",
                "5",
                "--output-dir",
                "state/generated/fab_dummy_project_wave",
            ]
        )
        self.assertEqual(args.command, "emit-fab-dummy-project-wave")
        self.assertEqual(args.game_scope, "arena_shared")
        self.assertEqual(args.engine_association, "5.7")
        self.assertEqual(args.max_jobs, 5)
        self.assertEqual(args.output_dir, Path("state/generated/fab_dummy_project_wave"))

    def test_emit_arena_owned_wave_parser_accepts_output_dir(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "emit-arena-owned-wave",
                "--output-dir",
                "state/generated/arena_owned_wave",
            ]
        )
        self.assertEqual(args.command, "emit-arena-owned-wave")
        self.assertEqual(args.output_dir, Path("state/generated/arena_owned_wave"))

    def test_emit_arena_extraction_wave_parser_accepts_scope(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "emit-arena-extraction-wave",
                "--output-dir",
                "state/generated/arena_extraction_wave",
                "--game-scope",
                "arena_shared",
            ]
        )
        self.assertEqual(args.command, "emit-arena-extraction-wave")
        self.assertEqual(args.output_dir, Path("state/generated/arena_extraction_wave"))
        self.assertEqual(args.game_scope, "arena_shared")

    def test_emit_useful_harvest_wave_parser_accepts_output_dir(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "emit-useful-harvest-wave",
                "--output-dir",
                "state/generated/useful_harvest_wave",
            ]
        )
        self.assertEqual(args.command, "emit-useful-harvest-wave")
        self.assertEqual(args.output_dir, Path("state/generated/useful_harvest_wave"))

    def test_print_pack_readiness_parser_accepts_json_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "print-pack-readiness",
                "--gate",
                "artifacts/quality/asset-gates/roman_arena_fps_gate_2026-03-15.json",
                "--catalog",
                "FlaxMCP/generated/asset_catalogs/roman_arena.json",
                "--json",
            ]
        )
        self.assertEqual(args.command, "print-pack-readiness")
        self.assertEqual(args.gate, Path("artifacts/quality/asset-gates/roman_arena_fps_gate_2026-03-15.json"))
        self.assertEqual(args.catalog, Path("FlaxMCP/generated/asset_catalogs/roman_arena.json"))
        self.assertIsNone(args.states)
        self.assertIsNone(args.groups)
        self.assertFalse(args.import_pending_only)
        self.assertTrue(args.as_json)

    def test_print_pack_readiness_parser_accepts_state_and_import_pending_filters(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "print-pack-readiness",
                "--state",
                "ready_reviewed",
                "--state",
                "imported",
                "--group",
                "roman_arena",
                "--group",
                "shared_priority",
                "--import-pending-only",
                "--json",
            ]
        )
        self.assertEqual(args.command, "print-pack-readiness")
        self.assertEqual(args.states, ["ready_reviewed", "imported"])
        self.assertEqual(args.groups, ["roman_arena", "shared_priority"])
        self.assertTrue(args.import_pending_only)
        self.assertTrue(args.as_json)

    def test_sync_shared_priority_parser_accepts_filters(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "sync-shared-priority",
                "--target-scope",
                "shared",
                "--pack-id",
                "SHARED_HIST_ARCH_ROMAN_CORE_01",
                "--pack-id",
                "SHARED_CHR_HUMAN_RIG_BASE_01",
                "--dry-run",
                "--json",
            ]
        )
        self.assertEqual(args.command, "sync-shared-priority")
        self.assertEqual(args.target_scope, "shared")
        self.assertEqual(
            args.pack_ids,
            ["SHARED_HIST_ARCH_ROMAN_CORE_01", "SHARED_CHR_HUMAN_RIG_BASE_01"],
        )
        self.assertTrue(args.dry_run)
        self.assertTrue(args.as_json)

    def test_emit_useful_donor_export_wave_parser_accepts_project_path(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "emit-useful-donor-export-wave",
                "--output-dir",
                "state/generated/useful_donor_export_wave",
                "--game-scope",
                "arena_shared",
                "--project-path",
                "C:/Users/me/My project (1)",
            ]
        )
        self.assertEqual(args.command, "emit-useful-donor-export-wave")
        self.assertEqual(args.output_dir, Path("state/generated/useful_donor_export_wave"))
        self.assertEqual(args.game_scope, "arena_shared")
        self.assertEqual(args.project_path, Path("C:/Users/me/My project (1)"))

    def test_emit_unity_download_wave_parser_accepts_paths(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "emit-unity-download-wave",
                "--source-file",
                "docs/reference/UNITY_FULL_DOWNLOAD_URLS_2026-03-26.md",
                "--project-root",
                "C:/Users/me/Documents/Unity AssetBoy",
                "--output-dir",
                "state/generated/unity_download_wave",
            ]
        )
        self.assertEqual(args.command, "emit-unity-download-wave")
        self.assertEqual(args.source_file, Path("docs/reference/UNITY_FULL_DOWNLOAD_URLS_2026-03-26.md"))
        self.assertEqual(args.project_root, Path("C:/Users/me/Documents/Unity AssetBoy"))
        self.assertEqual(args.output_dir, Path("state/generated/unity_download_wave"))

    def test_run_unity_claim_wave_parser_accepts_filters(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-unity-claim-wave",
                "--wave-json",
                "state/generated/unity_download_wave/unity_download_wave.json",
                "--best-first",
                "--exportable-only",
                "--category",
                "animation",
                "--category",
                "character",
                "--limit",
                "5",
                "--headless",
                "--browser-profile-dir",
                ".private/unity_profile",
                "--timeout-ms",
                "22000",
                "--retries",
                "3",
                "--hydrate-provenance",
                "--prepare-pack",
                "--auto-intake",
                "--cleanup-mode",
                "skip",
                "--asset-kind",
                "character",
                "--animated",
                "--packet-status",
                "reviewed_real",
                "--overwrite-packet",
                "--no-verify-hashes",
                "--continue-on-error",
                "--require-complete",
                "--emit-project-ingest-wave",
                "--project-path",
                "C:/Users/me/Documents/Unity AssetBoy/ProjectA",
                "--game-scope",
                "shared",
                "--output-dir",
                "state/generated/unity_claim_wave",
                "--json",
            ]
        )
        self.assertEqual(args.command, "run-unity-claim-wave")
        self.assertEqual(args.wave_json, Path("state/generated/unity_download_wave/unity_download_wave.json"))
        self.assertTrue(args.best_first)
        self.assertTrue(args.exportable_only)
        self.assertEqual(args.categories, ["animation", "character"])
        self.assertEqual(args.limit, 5)
        self.assertTrue(args.headless)
        self.assertEqual(args.browser_profile_dir, Path(".private/unity_profile"))
        self.assertEqual(args.timeout_ms, 22000)
        self.assertEqual(args.retries, 3)
        self.assertTrue(args.hydrate_provenance)
        self.assertTrue(args.prepare_pack)
        self.assertTrue(args.auto_intake)
        self.assertEqual(args.cleanup_mode, "skip")
        self.assertEqual(args.asset_kind, "character")
        self.assertTrue(args.animated)
        self.assertEqual(args.packet_status, "reviewed_real")
        self.assertTrue(args.overwrite_packet)
        self.assertFalse(args.verify_hashes)
        self.assertTrue(args.continue_on_error)
        self.assertTrue(args.require_complete)
        self.assertTrue(args.emit_project_ingest_wave)
        self.assertEqual(args.project_path, Path("C:/Users/me/Documents/Unity AssetBoy/ProjectA"))
        self.assertEqual(args.game_scope, "shared")
        self.assertEqual(args.output_dir, Path("state/generated/unity_claim_wave"))
        self.assertTrue(args.as_json)

    def test_unity_hub_status_parser_accepts_output_dir(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["unity-hub-status", "--output-dir", "state/generated/unity_hub_status"])
        self.assertEqual(args.command, "unity-hub-status")
        self.assertEqual(args.output_dir, Path("state/generated/unity_hub_status"))

    def test_map_unity_owned_library_parser_accepts_page_options(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "map-unity-owned-library",
                "--page-size",
                "150",
                "--max-pages",
                "3",
                "--output-dir",
                "state/generated/unity_owned_map",
            ]
        )
        self.assertEqual(args.command, "map-unity-owned-library")
        self.assertEqual(args.page_size, 150)
        self.assertEqual(args.max_pages, 3)
        self.assertEqual(args.output_dir, Path("state/generated/unity_owned_map"))

    def test_unity_download_owned_parser_accepts_product_id(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "unity-download-owned",
                "--product-id",
                "165785",
                "--timeout",
                "45",
                "--output-dir",
                "state/generated/unity_owned_downloads",
            ]
        )
        self.assertEqual(args.command, "unity-download-owned")
        self.assertEqual(args.product_id, "165785")
        self.assertEqual(args.timeout, 45.0)
        self.assertEqual(args.output_dir, Path("state/generated/unity_owned_downloads"))

    def test_download_unity_owned_lightweights_parser_accepts_size_controls(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "download-unity-owned-lightweights",
                "--max-mb",
                "120",
                "--limit",
                "8",
                "--include-hidden",
                "--include-unknown-size",
                "--page-size",
                "150",
                "--max-pages",
                "3",
                "--timeout",
                "45",
                "--output-dir",
                "state/generated/unity_owned_lightweights",
            ]
        )
        self.assertEqual(args.command, "download-unity-owned-lightweights")
        self.assertEqual(args.max_mb, 120.0)
        self.assertEqual(args.limit, 8)
        self.assertTrue(args.include_hidden)
        self.assertTrue(args.include_unknown_size)
        self.assertEqual(args.page_size, 150)
        self.assertEqual(args.max_pages, 3)
        self.assertEqual(args.timeout, 45.0)
        self.assertEqual(args.output_dir, Path("state/generated/unity_owned_lightweights"))

    def test_download_unity_owned_wave_parser_accepts_filters(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "download-unity-owned-wave",
                "--wave-json",
                "state/generated/unity_download_wave/unity_download_wave.json",
                "--best-first",
                "--exportable-only",
                "--asset-donor-only",
                "--category",
                "animation",
                "--pack-id",
                "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                "--limit",
                "2",
                "--timeout",
                "45",
                "--output-dir",
                "state/generated/unity_owned_download_wave",
            ]
        )
        self.assertEqual(args.command, "download-unity-owned-wave")
        self.assertEqual(args.wave_json, Path("state/generated/unity_download_wave/unity_download_wave.json"))
        self.assertTrue(args.best_first)
        self.assertTrue(args.exportable_only)
        self.assertTrue(args.asset_donor_only)
        self.assertEqual(args.categories, ["animation"])
        self.assertEqual(args.pack_ids, ["SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785"])
        self.assertEqual(args.limit, 2)
        self.assertEqual(args.timeout, 45.0)
        self.assertEqual(args.output_dir, Path("state/generated/unity_owned_download_wave"))

    def test_emit_unity_project_ingest_wave_parser_accepts_filters(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "emit-unity-project-ingest-wave",
                "--wave-json",
                "state/generated/unity_download_wave/unity_download_wave.json",
                "--project-path",
                "C:/Users/me/My project (1)",
                "--best-first",
                "--category",
                "animation",
                "--pack-id",
                "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                "--limit",
                "3",
                "--output-dir",
                "state/generated/unity_project_ingest_wave",
            ]
        )
        self.assertEqual(args.command, "emit-unity-project-ingest-wave")
        self.assertEqual(args.wave_json, Path("state/generated/unity_download_wave/unity_download_wave.json"))
        self.assertEqual(args.project_path, Path("C:/Users/me/My project (1)"))
        self.assertTrue(args.best_first)
        self.assertEqual(args.categories, ["animation"])
        self.assertEqual(args.pack_ids, ["SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785"])
        self.assertEqual(args.limit, 3)
        self.assertEqual(args.output_dir, Path("state/generated/unity_project_ingest_wave"))

    def test_print_batchability_parser_accepts_json(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["print-batchability", "--json"])
        self.assertEqual(args.command, "print-batchability")
        self.assertTrue(args.as_json)

    def test_run_bulk_parser_accepts_continue_on_error(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-bulk",
                "--profile",
                "kenney_presets",
                "--continue-on-error",
            ]
        )
        self.assertEqual(args.command, "run-bulk")
        self.assertTrue(args.continue_on_error)

    def test_run_browser_job_parser_accepts_execution_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-browser-job",
                "--job-spec",
                "state/generated/browser_job.json",
                "--execute",
                "--headless",
                "--browser-profile-dir",
                ".private/custom_profile",
                "--timeout-ms",
                "9000",
                "--retries",
                "3",
                "--hydrate-provenance",
                "--prepare-pack",
                "--auto-intake",
                "--cleanup-mode",
                "skip",
                "--asset-kind",
                "character",
                "--animated",
                "--packet-status",
                "reviewed_real",
                "--overwrite-packet",
                "--no-verify-hashes",
            ]
        )
        self.assertEqual(args.command, "run-browser-job")
        self.assertTrue(args.execute)
        self.assertTrue(args.headless)
        self.assertEqual(args.browser_profile_dir, Path(".private/custom_profile"))
        self.assertEqual(args.timeout_ms, 9000)
        self.assertEqual(args.retries, 3)
        self.assertTrue(args.hydrate_provenance)
        self.assertTrue(args.prepare_pack)
        self.assertTrue(args.auto_intake)
        self.assertEqual(args.cleanup_mode, "skip")
        self.assertEqual(args.asset_kind, "character")
        self.assertTrue(args.animated)
        self.assertEqual(args.packet_status, "reviewed_real")
        self.assertTrue(args.overwrite_packet)
        self.assertFalse(args.verify_hashes)

    def test_run_fab_fallback_actions_parser_accepts_execution_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-fab-fallback-actions",
                "--actions-file",
                "state/generated/fab_batch/fab_batch_fallback_actions.json",
                "--execute",
                "--headless",
                "--browser-profile-dir",
                ".private/custom_profile",
                "--timeout-ms",
                "9100",
                "--retries",
                "4",
                "--run-pwsh",
                "--hydrate-provenance",
                "--prepare-pack",
                "--auto-intake",
                "--cleanup-mode",
                "skip",
                "--asset-kind",
                "character",
                "--animated",
                "--packet-status",
                "reviewed_real",
                "--overwrite-packet",
                "--no-verify-hashes",
                "--pwsh-timeout-sec",
                "120",
                "--continue-on-error",
                "--require-complete",
                "--json",
            ]
        )
        self.assertEqual(args.command, "run-fab-fallback-actions")
        self.assertEqual(args.actions_file, Path("state/generated/fab_batch/fab_batch_fallback_actions.json"))
        self.assertTrue(args.execute)
        self.assertTrue(args.headless)
        self.assertEqual(args.browser_profile_dir, Path(".private/custom_profile"))
        self.assertEqual(args.timeout_ms, 9100)
        self.assertEqual(args.retries, 4)
        self.assertTrue(args.run_pwsh)
        self.assertTrue(args.hydrate_provenance)
        self.assertTrue(args.prepare_pack)
        self.assertTrue(args.auto_intake)
        self.assertEqual(args.cleanup_mode, "skip")
        self.assertEqual(args.asset_kind, "character")
        self.assertTrue(args.animated)
        self.assertEqual(args.packet_status, "reviewed_real")
        self.assertTrue(args.overwrite_packet)
        self.assertFalse(args.verify_hashes)
        self.assertEqual(args.pwsh_timeout_sec, 120.0)
        self.assertTrue(args.continue_on_error)
        self.assertTrue(args.require_complete)
        self.assertTrue(args.as_json)

    def test_run_colab_batch_parser_accepts_drive_folder(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-colab-batch",
                "--batch-file",
                "state/generated/hunyuan/prompt_batch.json",
                "--drive-folder",
                "AssetBoy/colab/hunyuan3d2.production/RA_PACK_WPN_COMBAT_SLICE_01",
            ]
        )
        self.assertEqual(args.command, "run-colab-batch")
        self.assertEqual(args.batch_file, Path("state/generated/hunyuan/prompt_batch.json"))
        self.assertEqual(
            args.drive_folder,
            "AssetBoy/colab/hunyuan3d2.production/RA_PACK_WPN_COMBAT_SLICE_01",
        )

    def test_run_hunyuan_batch_parser_accepts_drive_folder(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-hunyuan-batch",
                "--pack-id",
                "RA_PACK_WPN_COMBAT_SLICE_01",
                "--drive-folder",
                "AssetBoy/colab/hunyuan3d2.production/RA_PACK_WPN_COMBAT_SLICE_01",
            ]
        )
        self.assertEqual(args.command, "run-hunyuan-batch")
        self.assertEqual(
            args.drive_folder,
            "AssetBoy/colab/hunyuan3d2.production/RA_PACK_WPN_COMBAT_SLICE_01",
        )

    def test_run_mixamo_batch_parser_accepts_execution_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-mixamo-batch",
                "--pack-id",
                "RA_PACK_CHR_CORE_SLICE_01",
                "--search",
                "male fighter humanoid base",
                "--execute",
                "--headless",
                "--browser-profile-dir",
                ".private/custom_profile",
                "--timeout-ms",
                "7000",
                "--output-dir",
                "state/generated/mixamo",
            ]
        )
        self.assertEqual(args.command, "run-mixamo-batch")
        self.assertTrue(args.execute)
        self.assertTrue(args.headless)
        self.assertEqual(args.browser_profile_dir, Path(".private/custom_profile"))
        self.assertEqual(args.timeout_ms, 7000)
        self.assertEqual(args.output_dir, Path("state/generated/mixamo"))

    def test_run_freesound_batch_parser_accepts_execution_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-freesound-batch",
                "--pack-id",
                "RA_PACK_AUD_SFX_SLICE_01",
                "--search",
                "sword clash metal impact",
                "--execute",
                "--headless",
                "--browser-profile-dir",
                ".private/custom_profile",
                "--timeout-ms",
                "5000",
                "--output-dir",
                "state/generated/freesound",
            ]
        )
        self.assertEqual(args.command, "run-freesound-batch")
        self.assertTrue(args.execute)
        self.assertTrue(args.headless)
        self.assertEqual(args.browser_profile_dir, Path(".private/custom_profile"))
        self.assertEqual(args.timeout_ms, 5000)
        self.assertEqual(args.output_dir, Path("state/generated/freesound"))

    def test_run_music_batch_parser_accepts_execution_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-music-batch",
                "--source",
                "mixkit",
                "--search",
                "epic battle",
                "--execute",
                "--headless",
                "--browser-profile-dir",
                ".private/custom_profile",
                "--timeout-ms",
                "6000",
                "--output-dir",
                "state/generated/music",
            ]
        )
        self.assertEqual(args.command, "run-music-batch")
        self.assertTrue(args.execute)
        self.assertTrue(args.headless)
        self.assertEqual(args.browser_profile_dir, Path(".private/custom_profile"))
        self.assertEqual(args.timeout_ms, 6000)
        self.assertEqual(args.output_dir, Path("state/generated/music"))

    def test_run_roman_cleanup_wave_parser_accepts_filters(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-roman-cleanup-wave",
                "--pack-id",
                "RA_PACK_CHR_CORE_SLICE_01",
                "--pack-id",
                "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
                "--input-root",
                "state/generated/raw",
                "--output-dir",
                "state/generated/roman_cleanup",
                "--dry-run",
            ]
        )
        self.assertEqual(args.command, "run-roman-cleanup-wave")
        self.assertEqual(
            args.pack_ids,
            ["RA_PACK_CHR_CORE_SLICE_01", "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01"],
        )
        self.assertEqual(args.input_root, Path("state/generated/raw"))
        self.assertEqual(args.output_dir, Path("state/generated/roman_cleanup"))
        self.assertTrue(args.dry_run)
