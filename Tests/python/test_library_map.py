from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from assetboy.providers.library_map import (
    build_arena_extraction_wave,
    build_arena_owned_wave,
    build_combined_library_map,
    build_local_quixel_library_map,
    build_useful_harvest_wave,
    emit_arena_extraction_wave,
    emit_arena_owned_wave,
    emit_fab_dummy_project_wave,
    emit_useful_donor_export_wave,
    emit_useful_harvest_wave,
    render_arena_extraction_wave_markdown,
    render_arena_owned_wave_markdown,
    rank_fab_dummy_project_candidates,
    render_combined_library_map_markdown,
    render_fab_dummy_project_wave_markdown,
    render_local_quixel_library_map_markdown,
    render_useful_harvest_wave_markdown,
    scan_quixel_library_root,
)


class LibraryMapTests(unittest.TestCase):
    def test_scan_quixel_library_root_counts_categories(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Megascans Library"
            surface = root / "surface" / "sandstone_tile"
            meshes = root / "3d" / "roman_column"
            surface.mkdir(parents=True, exist_ok=True)
            meshes.mkdir(parents=True, exist_ok=True)
            (surface / "sandstone_tile.json").write_text("{}", encoding="utf-8")
            (meshes / "roman_column.json").write_text("{}", encoding="utf-8")
            (root / "support" / "settings.json").parent.mkdir(parents=True, exist_ok=True)
            (root / "support" / "settings.json").write_text("{}", encoding="utf-8")

            report = scan_quixel_library_root(root)

        self.assertEqual(report["asset_count"], 2)
        self.assertEqual(report["category_counts"]["surface"], 1)
        self.assertEqual(report["category_counts"]["3d"], 1)

    def test_build_local_quixel_library_map_uses_extra_roots(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Megascans Library"
            asset_dir = root / "3d" / "rock_sandstone"
            asset_dir.mkdir(parents=True, exist_ok=True)
            (asset_dir / "rock_sandstone.json").write_text("{}", encoding="utf-8")

            # Path B s3 (2026-05-10) moved the Quixel scanner out of
            # library_map.py into providers/quixel_scanner.py. Patch the new
            # location. library_map still re-exports build_local_quixel_library_map
            # for back-compat, so the public surface is unchanged.
            with patch("assetboy.providers.quixel_scanner._probe_quixel_bridge_api", return_value={"reachable": False, "megascans_folder": "", "zip_folders": [], "asset_count": 0, "category_counts": {}, "error": "offline"}):
                report = build_local_quixel_library_map(extra_roots=(root,))

        self.assertEqual(report["summary"]["detected_root_count"], 1)
        self.assertEqual(report["summary"]["total_assets"], 1)

    def test_build_combined_library_map_merges_surface_counts(self) -> None:
        fake_fab = {
            "summary": {
                "total_records": 147,
                "neutral_or_mixed_records": 60,
                "unreal_only_records": 86,
                "roman_candidate_count": 32,
            },
            "roman_candidates": [{"title": "Ancient Roman Sword Gladius", "route": "neutral_or_mixed", "format_codes": ["fbx"]}],
            "records": [],
        }
        fake_epic_online = {
            "summary": {
                "total_records": 68,
                "marketplace_asset_records": 13,
                "engine_records": 38,
            },
            "records": [],
        }
        fake_epic_local = {
            "confirmed_cached_entries": [
                {
                    "title": "Parry Attack System",
                    "stats": {
                        "static_mesh_candidates": 0,
                        "skeletal_mesh_candidates": 4,
                        "animation_candidates": 66,
                        "texture_candidates": 10,
                        "sound_candidates": 21,
                    },
                }
            ],
            "launcher_cache_candidates": [{}] * 19,
            "extraction_readiness": {},
        }
        fake_quixel = {
            "summary": {"detected_root_count": 1, "total_assets": 250, "category_counts": {"3d": 100}, "bridge_api_reachable": False},
            "api": {"reachable": False},
            "detected_roots": ["D:/Megascans"],
            "scanned_roots": [],
        }

        with patch("assetboy.providers.library_map.build_online_fab_library_map", return_value=fake_fab):
            with patch("assetboy.providers.library_map.build_online_epic_library_map", return_value=fake_epic_online):
                with patch("assetboy.providers.library_map.build_local_epic_library_report", return_value=fake_epic_local):
                    with patch("assetboy.providers.library_map.build_local_quixel_library_map", return_value=fake_quixel):
                        with patch("assetboy.providers.library_map.detect_optional_library_tools", return_value={"FModel": "C:/SHARE/Tools/FModel/FModel.exe"}):
                            report = build_combined_library_map()

        self.assertEqual(report["summary"]["fab_owned_total"], 147)
        self.assertEqual(report["summary"]["epic_local_cached"], 1)
        self.assertEqual(report["summary"]["quixel_total_assets"], 250)

    def test_renderers_include_key_counts(self) -> None:
        quixel_markdown = render_local_quixel_library_map_markdown(
            {
                "api": {"reachable": False, "megascans_folder": "", "zip_folders": [], "asset_count": 0, "category_counts": {}, "error": "offline"},
                "detected_roots": ["D:/Megascans"],
                "scanned_roots": [],
                "summary": {"detected_root_count": 1, "total_assets": 42, "category_counts": {"3d": 20}, "bridge_api_reachable": False},
            }
        )
        combined_markdown = render_combined_library_map_markdown(
            {
                "summary": {
                    "fab_owned_total": 147,
                    "fab_neutral_or_mixed": 60,
                    "fab_unreal_only": 86,
                    "fab_roman_candidates": 32,
                    "epic_online_total": 68,
                    "epic_marketplace_assets": 13,
                    "epic_local_cached": 4,
                    "epic_launcher_candidates": 19,
                    "quixel_detected_roots": 1,
                    "quixel_total_assets": 42,
                },
                "source_of_truth": {"fab_owned_assets": "fab_online_api"},
                "tools": {"FModel": "C:/SHARE/Tools/FModel/FModel.exe"},
                "high_value": {
                    "fab_roman_candidates": [{"title": "Ancient Roman Sword Gladius", "route": "neutral_or_mixed", "format_codes": ["fbx"]}],
                    "local_extract_candidates": [{"title": "Parry Attack System", "stats": {"static_mesh_candidates": 0, "skeletal_mesh_candidates": 4, "animation_candidates": 66, "texture_candidates": 10, "sound_candidates": 21}}],
                },
            }
        )

        self.assertIn("Total assets: `42`", quixel_markdown)
        self.assertIn("Fab owned listings: `147`", combined_markdown)
        self.assertIn("Ancient Roman Sword Gladius", combined_markdown)

    def test_rank_fab_dummy_project_candidates_prefers_animation_and_skips_cached(self) -> None:
        fab_report = {
            "records": [
                {
                    "title": "Game Animation Sample",
                    "listing_uid": "abcd-1234",
                    "listing_url": "https://www.fab.com/listings/abcd-1234",
                    "listing_type": "tutorials-examples",
                    "publisher_name": "Epic Games",
                    "keywords": ["animation"],
                    "route": "unreal_only",
                },
                {
                    "title": "Basic Montage Sequence Manager",
                    "listing_uid": "efgh-5678",
                    "listing_url": "https://www.fab.com/listings/efgh-5678",
                    "listing_type": "tool-and-plugin",
                    "publisher_name": "RodrigoMello",
                    "keywords": [],
                    "route": "unreal_only",
                },
                {
                    "title": "Parry Attack System",
                    "listing_uid": "ijkl-9999",
                    "listing_url": "https://www.fab.com/listings/ijkl-9999",
                    "listing_type": "3d-model",
                    "publisher_name": "BP Systems",
                    "keywords": ["combat"],
                    "route": "unreal_only",
                },
            ]
        }
        local_report = {
            "confirmed_cached_entries": [{"title": "Parry Attack System"}],
            "launcher_cache_candidates": [],
        }

        ranking = rank_fab_dummy_project_candidates(fab_report, local_report)

        self.assertEqual(ranking["do_first"][0]["title"], "Game Animation Sample")
        self.assertEqual(ranking["skip"][0]["title"], "Parry Attack System")
        self.assertTrue(any(item["title"] == "Basic Montage Sequence Manager" for item in ranking["skip"]))

    def test_emit_fab_dummy_project_wave_writes_artifacts(self) -> None:
        fab_report = {
            "records": [
                {
                    "title": "Game Animation Sample",
                    "listing_uid": "abcd-1234",
                    "listing_url": "https://www.fab.com/listings/abcd-1234",
                    "listing_type": "tutorials-examples",
                    "publisher_name": "Epic Games",
                    "keywords": ["animation"],
                    "route": "unreal_only",
                }
            ]
        }
        local_report = {"confirmed_cached_entries": [], "launcher_cache_candidates": []}

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "dummy_wave"
            with patch("assetboy.providers.library_map.emit_epic_dummy_project_job") as emit_job:
                emit_job.return_value = type(
                    "Artifacts",
                    (),
                    {
                        "output_dir": output_dir / "job",
                        "uproject_path": output_dir / "job" / "Dummy.uproject",
                        "command_template_path": output_dir / "job" / "commands.txt",
                    },
                )()
                report = emit_fab_dummy_project_wave(
                    fab_report=fab_report,
                    local_report=local_report,
                    max_jobs=1,
                    output_dir=output_dir,
                )
                json_exists = (output_dir / "fab_dummy_project_wave.json").exists()
                md_exists = (output_dir / "fab_dummy_project_wave.md").exists()

        self.assertEqual(len(report["emitted_jobs"]), 1)
        self.assertTrue(json_exists)
        self.assertTrue(md_exists)

    def test_render_fab_dummy_project_wave_markdown_mentions_sections(self) -> None:
        markdown = render_fab_dummy_project_wave_markdown(
            {
                "do_first": [{"title": "Game Animation Sample", "score": 12, "listing_type": "tutorials-examples", "reasons": ["type:tutorials-examples"]}],
                "do_later": [],
                "skip": [],
                "emitted_jobs": [{"pack_id": "SHARED_EPIC_ANM_GAME_ANIMATION_SAMPLE_ABCD1234", "job_output_dir": "C:/Temp/job"}],
            }
        )
        self.assertIn("Do first: `1`", markdown)
        self.assertIn("Game Animation Sample", markdown)

    def test_build_useful_harvest_wave_prioritizes_fab_epic_and_unity_assets(self) -> None:
        combined_report = {
            "fab_online": {
                "roman_candidates": [
                    {
                        "title": "Ancient Roman Sword Gladius",
                        "listing_uid": "fab-roman-gladius",
                        "listing_url": "https://www.fab.com/listings/gladius",
                        "route": "neutral_or_mixed",
                        "format_codes": ["fbx"],
                    }
                ],
                "records": [
                    {
                        "title": "Human Melee Animations Retargeted",
                        "listing_uid": "fab-human-melee",
                        "listing_url": "https://www.fab.com/listings/human-melee",
                        "route": "neutral_or_mixed",
                        "format_codes": ["fbx"],
                    }
                ],
            },
            "epic_local": {
                "confirmed_cached_entries": [
                    {
                        "title": "GASP: Basic Template for FPS with Spatial Inventory",
                        "stats": {
                            "static_mesh_candidates": 13,
                            "skeletal_mesh_candidates": 8,
                            "animation_candidates": 1157,
                            "texture_candidates": 73,
                            "sound_candidates": 406,
                        },
                    }
                ],
                "launcher_cache_candidates": [
                    {
                        "display_name": "GameAnimationSample (5.4, 5.5, 5.6, 5.7)",
                        "family": "GameAnimationSample",
                        "classification": "character_animation",
                    }
                ],
            },
        }
        unity_owned_report = {
            "items": [
                {
                    "display_name": "Human Melee Animations FREE",
                    "package_id": "165785",
                }
            ]
        }
        dummy_wave_report = {
            "do_first": [
                {
                    "title": "Game Animation Sample",
                    "score": 12,
                    "listing_url": "https://www.fab.com/listings/game-animation",
                }
            ]
        }

        report = build_useful_harvest_wave(
            combined_report=combined_report,
            unity_owned_report=unity_owned_report,
            fab_dummy_wave_report=dummy_wave_report,
            unity_downloads=[
                {
                    "name": "Human Melee Animations FREE",
                    "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                    "output_path": "C:/downloads/HumanMelee.unitypackage",
                }
            ],
        )

        self.assertTrue(any(item["title"] == "Ancient Roman Sword Gladius" for item in report["extract_now"]["fab_neutral_owned"]))
        self.assertEqual(report["extract_now"]["epic_cached"][0]["title"], "GASP: Basic Template for FPS with Spatial Inventory")
        self.assertEqual(report["extract_now"]["unity_downloaded"][0]["name"], "Human Melee Animations FREE")
        self.assertEqual(report["queue_next"]["epic_launcher_candidates"][0]["family"], "GameAnimationSample")

    def test_emit_useful_harvest_wave_writes_artifacts(self) -> None:
        combined_report = {"fab_online": {"roman_candidates": [], "records": []}, "epic_local": {"confirmed_cached_entries": [], "launcher_cache_candidates": []}}
        unity_owned_report = {"items": []}
        dummy_wave_report = {"do_first": []}

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "useful_harvest_wave"
            report = emit_useful_harvest_wave(
                combined_report=combined_report,
                unity_owned_report=unity_owned_report,
                fab_dummy_wave_report=dummy_wave_report,
                output_dir=output_dir,
            )

            self.assertTrue((output_dir / "useful_harvest_wave.json").exists())
            self.assertTrue((output_dir / "useful_harvest_wave.md").exists())
            self.assertIn("summary", report)

    def test_emit_useful_donor_export_wave_writes_direct_and_unity_jobs(self) -> None:
        useful_harvest_report = {
            "extract_now": {
                "fab_neutral_owned": [
                    {
                        "listing_uid": "11d20d01-b764-4936-8163-cb20d05c369e",
                        "title": "Survival Character FREE",
                        "listing_url": "https://www.fab.com/listings/11d20d01-b764-4936-8163-cb20d05c369e",
                        "publisher_name": "Vendor A",
                    },
                    {
                        "listing_uid": "e0dbddd5-54b9-4c56-9005-87c5f04785b0",
                        "title": "Warrior",
                        "listing_url": "https://www.fab.com/listings/e0dbddd5-54b9-4c56-9005-87c5f04785b0",
                        "publisher_name": "Vendor B",
                    },
                    {
                        "listing_uid": "ae6ea187-cf7d-4cad-8940-eca1916afe0c",
                        "title": "Ancient Roman Sword Gladius",
                        "listing_url": "https://www.fab.com/listings/ae6ea187-cf7d-4cad-8940-eca1916afe0c",
                        "publisher_name": "Vendor C",
                    },
                    {
                        "listing_uid": "332e2b59-9870-46fe-9537-81f697e036da",
                        "title": "Emerald Magic Spear",
                        "listing_url": "https://www.fab.com/listings/332e2b59-9870-46fe-9537-81f697e036da",
                        "publisher_name": "Vendor D",
                    },
                    {
                        "listing_uid": "259f8545-f820-47b3-8fc1-e8ec5458214d",
                        "title": "Game Animation Sample Animations Retargeted to ue5 mannequin Animations only",
                        "listing_url": "https://www.fab.com/listings/259f8545-f820-47b3-8fc1-e8ec5458214d",
                        "publisher_name": "Vendor E",
                    },
                ]
            }
        }

        with TemporaryDirectory() as temp_dir:
            generated_root = Path(temp_dir) / "generated"
            useful_fab_root = generated_root / "useful_fab_harvest_live" / "downloads"
            useful_fab_root.mkdir(parents=True, exist_ok=True)
            (useful_fab_root / "11d20d01-b764-4936-8163-cb20d05c369e").mkdir(parents=True, exist_ok=True)
            (useful_fab_root / "11d20d01-b764-4936-8163-cb20d05c369e" / "survival_character_free.fbx").write_text("fbx", encoding="utf-8")
            (useful_fab_root / "e0dbddd5-54b9-4c56-9005-87c5f04785b0").mkdir(parents=True, exist_ok=True)
            (useful_fab_root / "e0dbddd5-54b9-4c56-9005-87c5f04785b0" / "warrior.fbx").write_text("fbx", encoding="utf-8")
            (useful_fab_root / "ae6ea187-cf7d-4cad-8940-eca1916afe0c").mkdir(parents=True, exist_ok=True)
            (useful_fab_root / "ae6ea187-cf7d-4cad-8940-eca1916afe0c" / "gladius.fbx").write_text("fbx", encoding="utf-8")
            (useful_fab_root / "332e2b59-9870-46fe-9537-81f697e036da").mkdir(parents=True, exist_ok=True)
            (useful_fab_root / "332e2b59-9870-46fe-9537-81f697e036da" / "emerald_magic_spear.fbx").write_text("fbx", encoding="utf-8")
            (useful_fab_root / "259f8545-f820-47b3-8fc1-e8ec5458214d").mkdir(parents=True, exist_ok=True)
            (useful_fab_root / "259f8545-f820-47b3-8fc1-e8ec5458214d" / "animations.zip").write_text("not-a-zip", encoding="utf-8")

            dummy_dir = generated_root / "unity_owned_download_human_dummy"
            dummy_dir.mkdir(parents=True, exist_ok=True)
            (dummy_dir / "human-character-dummy.unitypackage").write_text("pkg", encoding="utf-8")
            (dummy_dir / "unity_owned_download_178395.json").write_text(
                json.dumps(
                    {
                        "product_id": "178395",
                        "display_name": "Human Character Dummy",
                        "slug": "human-character-dummy-178395",
                        "output_path": str(dummy_dir / "human-character-dummy.unitypackage"),
                    }
                ),
                encoding="utf-8",
            )

            motions_dir = generated_root / "unity_owned_download_human_basic_motions"
            motions_dir.mkdir(parents=True, exist_ok=True)
            (motions_dir / "human-basic-motions.unitypackage").write_text("pkg", encoding="utf-8")
            (motions_dir / "unity_owned_download_154271.json").write_text(
                json.dumps(
                    {
                        "product_id": "154271",
                        "display_name": "Human Basic Motions FREE",
                        "slug": "human-basic-motions-free-154271",
                        "output_path": str(motions_dir / "human-basic-motions.unitypackage"),
                    }
                ),
                encoding="utf-8",
            )

            melee_dir = generated_root / "unity_owned_download_human_melee"
            melee_dir.mkdir(parents=True, exist_ok=True)
            (melee_dir / "human-melee.unitypackage").write_text("pkg", encoding="utf-8")
            (melee_dir / "unity_owned_download_165785.json").write_text(
                json.dumps(
                    {
                        "product_id": "165785",
                        "display_name": "Human Melee Animations FREE",
                        "slug": "human-melee-animations-free-165785",
                        "output_path": str(melee_dir / "human-melee.unitypackage"),
                    }
                ),
                encoding="utf-8",
            )

            with patch("assetboy.providers.library_map.generated_output_root", return_value=generated_root):
                with patch(
                    "assetboy.providers.library_map.publish_payload_dir",
                    side_effect=lambda game_scope, pack_id: Path(temp_dir) / "payload" / game_scope / pack_id / "payload",
                ):
                    with patch(
                        "assetboy.providers.library_map.emit_unity_export_runner",
                        side_effect=lambda **kwargs: SimpleNamespace(
                            runner_job_path=Path(kwargs["output_dir"]) / "unity_export_runner.json",
                            powershell_path=Path(kwargs["output_dir"]) / "run_unity_export.ps1",
                            blender_handoff_path=Path(kwargs["output_dir"]) / "blender_handoff.json",
                            output_dir=Path(kwargs["output_dir"]),
                            payload_target_path=Path(temp_dir) / "payload" / kwargs["pack_id"],
                        ),
                    ):
                        output_dir = generated_root / "useful_donor_export_wave"
                        report = emit_useful_donor_export_wave(
                            useful_harvest_report=useful_harvest_report,
                            output_dir=output_dir,
                            project_path=Path(temp_dir) / "UnityProject",
                        )

            self.assertEqual(report["summary"]["direct_cleanup_jobs"], 4)
            self.assertEqual(report["summary"]["unity_export_jobs"], 3)
            self.assertEqual(report["summary"]["blocked_sources"], 1)
            self.assertTrue((output_dir / "useful_donor_export_wave.json").exists())
            self.assertTrue((output_dir / "useful_donor_export_wave.md").exists())
            self.assertTrue(
                (
                    output_dir
                    / "direct_cleanup_jobs"
                    / "SHARED_FAB_CHR_SURVIVAL_CHARACTER_FREE_11D20D01"
                    / "cleanup_plan.json"
                ).exists()
            )

    def test_emit_useful_harvest_wave_falls_back_to_cached_reports(self) -> None:
        combined_report = {"fab_online": {"roman_candidates": [], "records": []}, "epic_local": {"confirmed_cached_entries": [], "launcher_cache_candidates": []}}
        unity_owned_report = {"items": []}

        with TemporaryDirectory() as temp_dir:
            generated_root = Path(temp_dir) / "generated"
            combined_dir = generated_root / "combined_library_map_live"
            unity_dir = generated_root / "unity_owned_library_map_live"
            combined_dir.mkdir(parents=True, exist_ok=True)
            unity_dir.mkdir(parents=True, exist_ok=True)
            (combined_dir / "combined_library_map.json").write_text(json.dumps(combined_report), encoding="utf-8")
            (unity_dir / "unity_owned_library_map.json").write_text(json.dumps(unity_owned_report), encoding="utf-8")

            with patch("assetboy.providers.library_map.generated_output_root", return_value=generated_root):
                with patch("assetboy.providers.library_map.build_combined_library_map", side_effect=RuntimeError("offline")):
                    with patch("assetboy.providers.library_map.build_unity_owned_library_map", side_effect=RuntimeError("offline")):
                        report = emit_useful_harvest_wave(
                            fab_dummy_wave_report={"do_first": []},
                            output_dir=generated_root / "useful_harvest_wave",
                        )

        self.assertEqual(report["summary"]["fab_useful_now"], 0)
        self.assertEqual(report["summary"]["unity_owned_useful"], 0)

    def test_build_useful_harvest_wave_detects_direct_unity_owned_download_reports(self) -> None:
        combined_report = {"fab_online": {"roman_candidates": [], "records": []}, "epic_local": {"confirmed_cached_entries": [], "launcher_cache_candidates": []}}
        unity_owned_report = {"items": []}
        dummy_wave_report = {"do_first": []}

        with TemporaryDirectory() as temp_dir:
            generated_root = Path(temp_dir) / "generated"
            report_dir = generated_root / "unity_owned_download_human_dummy"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "unity_owned_download_178395.json").write_text(
                json.dumps(
                    {
                        "product_id": "178395",
                        "display_name": "Human Character Dummy",
                        "output_path": "C:/downloads/HumanCharacterDummy.unitypackage",
                    }
                ),
                encoding="utf-8",
            )

            with patch("assetboy.providers.library_map.generated_output_root", return_value=generated_root):
                report = build_useful_harvest_wave(
                    combined_report=combined_report,
                    unity_owned_report=unity_owned_report,
                    fab_dummy_wave_report=dummy_wave_report,
                )

        self.assertEqual(report["summary"]["unity_downloaded_ready"], 1)
        self.assertEqual(report["extract_now"]["unity_downloaded"][0]["name"], "Human Character Dummy")

    def test_build_useful_harvest_wave_dedupes_wave_and_direct_unity_download_reports(self) -> None:
        combined_report = {"fab_online": {"roman_candidates": [], "records": []}, "epic_local": {"confirmed_cached_entries": [], "launcher_cache_candidates": []}}
        unity_owned_report = {"items": []}
        dummy_wave_report = {"do_first": []}

        with TemporaryDirectory() as temp_dir:
            generated_root = Path(temp_dir) / "generated"
            wave_dir = generated_root / "unity_owned_download_wave_live"
            direct_dir = generated_root / "unity_owned_download_human_melee"
            wave_dir.mkdir(parents=True, exist_ok=True)
            direct_dir.mkdir(parents=True, exist_ok=True)
            (wave_dir / "unity_owned_download_wave.json").write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "status": "downloaded",
                                "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
                                "asset_id": "165785",
                                "name": "Human Melee Animations FREE",
                                "output_path": "C:/downloads/HumanMelee.unitypackage",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (direct_dir / "unity_owned_download_165785.json").write_text(
                json.dumps(
                    {
                        "product_id": "165785",
                        "display_name": "Human Melee Animations FREE",
                        "output_path": "C:/downloads/HumanMeleeDuplicate.unitypackage",
                    }
                ),
                encoding="utf-8",
            )

            with patch("assetboy.providers.library_map.generated_output_root", return_value=generated_root):
                report = build_useful_harvest_wave(
                    combined_report=combined_report,
                    unity_owned_report=unity_owned_report,
                    fab_dummy_wave_report=dummy_wave_report,
                )

        self.assertEqual(report["summary"]["unity_downloaded_ready"], 1)
        self.assertEqual(report["extract_now"]["unity_downloaded"][0]["asset_id"], "165785")

    def test_render_useful_harvest_wave_markdown_mentions_sections(self) -> None:
        markdown = render_useful_harvest_wave_markdown(
            {
                "summary": {
                    "fab_useful_now": 1,
                    "epic_cached_now": 1,
                    "unity_owned_useful": 1,
                    "unity_downloaded_ready": 1,
                    "epic_launcher_next": 1,
                    "fab_unreal_next": 1,
                },
                "extract_now": {
                    "fab_neutral_owned": [{"title": "Ancient Roman Sword Gladius", "route": "neutral_or_mixed", "format_codes": ["fbx"]}],
                    "epic_cached": [{"title": "GASP: Basic Template for FPS with Spatial Inventory", "stats": {"skeletal_mesh_candidates": 8, "animation_candidates": 1157, "static_mesh_candidates": 13, "sound_candidates": 406}}],
                    "unity_downloaded": [{"name": "Human Melee Animations FREE", "output_path": "C:/downloads/HumanMelee.unitypackage"}],
                    "unity_owned": [{"display_name": "Human Melee Animations FREE", "package_id": "165785"}],
                },
                "queue_next": {
                    "epic_launcher_candidates": [{"display_name": "GameAnimationSample", "classification": "character_animation"}],
                    "fab_unreal_dummy_project": [{"title": "Game Animation Sample", "score": 12}],
                },
                "recommended_order": ["Use direct neutral Fab assets first."],
            }
        )

        self.assertIn("Useful Harvest Wave", markdown)
        self.assertIn("Ancient Roman Sword Gladius", markdown)
        self.assertIn("Human Melee Animations FREE", markdown)
        self.assertIn("Game Animation Sample", markdown)

    def test_build_arena_owned_wave_maps_character_animation_and_audio_targets(self) -> None:
        combined_report = {
            "fab_online": {
                "records": [
                    {
                        "title": "Survival Character FREE",
                        "route": "neutral_or_mixed",
                        "listing_url": "https://www.fab.com/listings/survival",
                    },
                    {
                        "title": "Warrior",
                        "route": "neutral_or_mixed",
                        "listing_url": "https://www.fab.com/listings/warrior",
                    },
                    {
                        "title": "Game Animation Sample Animations Retargeted to ue5 mannequin Animations only",
                        "route": "neutral_or_mixed",
                        "listing_url": "https://www.fab.com/listings/game-animation-retargeted",
                    },
                    {
                        "title": "Ancient Roman Sword Gladius",
                        "route": "neutral_or_mixed",
                        "listing_url": "https://www.fab.com/listings/gladius",
                    },
                    {
                        "title": "Roman Republican shield",
                        "route": "neutral_or_mixed",
                        "listing_url": "https://www.fab.com/listings/shield",
                    },
                    {
                        "title": "Roman furniture: Roman villa pack",
                        "route": "neutral_or_mixed",
                        "listing_url": "https://www.fab.com/listings/villa",
                    },
                    {
                        "title": "Arena Combat Music Loop",
                        "route": "neutral_or_mixed",
                        "listing_url": "https://www.fab.com/listings/music",
                    },
                ]
            },
            "epic_local": {
                "confirmed_cached_entries": [
                    {"title": "GASP: Basic Template for FPS with Spatial Inventory"},
                    {"title": "Parry Attack System"},
                    {"title": "Abandoned Lighthouse Island – Modular Environment Pack"},
                ]
            },
        }
        dummy_wave_report = {
            "do_first": [
                {"title": "Game Animation Sample", "listing_url": "https://www.fab.com/listings/game-animation"},
                {"title": "Animation Starter Pack", "listing_url": "https://www.fab.com/listings/animation-starter"},
                {"title": "Slay Animation Sample", "listing_url": "https://www.fab.com/listings/slay"},
                {"title": "Mega Spear Animation Pack", "listing_url": "https://www.fab.com/listings/spear"},
                {"title": "Dark Ruins Megascans Sample", "listing_url": "https://www.fab.com/listings/dark-ruins"},
                {"title": "FREE Dramatic Death – Animation Performances for NPCs & Cinematics", "listing_url": "https://www.fab.com/listings/death"},
            ]
        }

        report = build_arena_owned_wave(combined_report, dummy_wave_report)

        core = report["roman_targets"]["RA_PACK_CHR_CORE_SLICE_01"]
        anm = report["roman_targets"]["RA_PACK_ANM_COMBAT_SLICE_01"]
        env = report["roman_targets"]["RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01"]
        music = report["roman_targets"]["RA_PACK_AUD_MUSIC_SLICE_01"]

        self.assertEqual(core["primary_direct_candidate"]["title"], "Survival Character FREE")
        self.assertEqual(core["secondary_direct_candidate"]["title"], "Warrior")
        self.assertEqual(core["compatibility_goal"], "same_or_compatible_rig")
        self.assertEqual(anm["primary_direct_candidate"]["title"], "Game Animation Sample Animations Retargeted to ue5 mannequin Animations only")
        self.assertTrue(any(item["title"] == "Game Animation Sample" for item in anm["dummy_project_jobs"]))
        self.assertEqual(len(env["cached_sources"]), 1)
        self.assertEqual(music["primary_direct_candidate"]["title"], "Arena Combat Music Loop")

    def test_emit_arena_owned_wave_writes_artifacts(self) -> None:
        combined_report = {"fab_online": {"records": []}, "epic_local": {"confirmed_cached_entries": []}}
        dummy_wave_report = {"do_first": []}

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "arena_owned_wave"
            report = emit_arena_owned_wave(
                combined_report=combined_report,
                dummy_wave_report=dummy_wave_report,
                output_dir=output_dir,
            )

            self.assertTrue((output_dir / "arena_owned_wave.json").exists())
            self.assertTrue((output_dir / "arena_owned_wave.md").exists())
            self.assertIn("summary", report)

    def test_render_arena_owned_wave_markdown_mentions_character_and_actions(self) -> None:
        markdown = render_arena_owned_wave_markdown(
            {
                "summary": {
                    "direct_candidate_count": 3,
                    "dummy_animation_job_count": 2,
                    "dummy_environment_job_count": 1,
                    "cached_animation_source_count": 2,
                    "cached_environment_source_count": 1,
                    "action_source_count": 4,
                },
                "roman_targets": {
                    "RA_PACK_CHR_CORE_SLICE_01": {
                        "primary_direct_candidate": {
                            "title": "Survival Character FREE",
                            "listing_url": "https://www.fab.com/listings/survival",
                        },
                        "compatibility_goal": "same_or_compatible_rig",
                    },
                    "RA_PACK_ANM_COMBAT_SLICE_01": {
                        "action_coverage_plan": {
                            "idle_walk_run_sprint": ["Game Animation Sample", "Animation Starter Pack"],
                        }
                    },
                },
            }
        )

        self.assertIn("Arena Owned Wave", markdown)
        self.assertIn("Survival Character FREE", markdown)
        self.assertIn("same_or_compatible_rig", markdown)
        self.assertIn("idle_walk_run_sprint", markdown)

    def test_build_arena_extraction_wave_emits_cached_and_dummy_extractors(self) -> None:
        arena_report = {
            "roman_targets": {
                "RA_PACK_ANM_COMBAT_SLICE_01": {
                    "cached_sources": [
                        {
                            "title": "GASP: Basic Template for FPS with Spatial Inventory",
                            "cache_path": "C:/Vault/GASP",
                            "listing_uid": "gasp-uid",
                            "classification": "character_animation_mix",
                            "stats": {"skeletal_mesh_candidates": 8, "animation_candidates": 1157},
                        }
                    ]
                },
                "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01": {
                    "cached_sources": [
                        {
                            "title": "Abandoned Lighthouse Island – Modular Environment Pack",
                            "cache_path": "C:/Vault/Lighthouse",
                            "listing_uid": "lighthouse-uid",
                            "classification": "environment_art_heavy",
                            "stats": {"static_mesh_candidates": 101},
                        }
                    ]
                },
                "RA_PACK_AUD_SFX_SLICE_01": {
                    "cached_sources": [
                        {
                            "title": "Parry Attack System",
                            "cache_path": "C:/Vault/Parry",
                            "listing_uid": "parry-uid",
                            "classification": "character_animation_mix",
                            "stats": {"skeletal_mesh_candidates": 4, "animation_candidates": 66},
                        }
                    ]
                },
            }
        }
        dummy_wave_report = {
            "emitted_jobs": [
                {
                    "pack_id": "SHARED_EPIC_ANM_GAMEANIMATIONSAMPLE_880E319A",
                    "title": "Game Animation Sample",
                    "listing_url": "https://www.fab.com/listings/game-animation",
                    "listing_type": "tutorials-examples",
                    "job_output_dir": "C:/Temp/dummy_job",
                    "command_template_path": "C:/Temp/dummy_job/commands.txt",
                }
            ]
        }

        with TemporaryDirectory() as temp_dir:
            report = build_arena_extraction_wave(
                arena_report,
                dummy_wave_report,
                output_dir=Path(temp_dir) / "arena_extract",
            )

        self.assertEqual(report["summary"]["cached_extractors"], 3)
        self.assertEqual(report["summary"]["dummy_project_extractors"], 1)
        self.assertEqual(report["dummy_project_extractors"][0]["pack_id"], "SHARED_EPIC_ANM_GAMEANIMATIONSAMPLE_880E319A")

    def test_emit_arena_extraction_wave_writes_artifacts(self) -> None:
        arena_report = {"roman_targets": {}}
        dummy_wave_report = {"emitted_jobs": []}

        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "arena_extract"
            report = emit_arena_extraction_wave(
                arena_report=arena_report,
                dummy_wave_report=dummy_wave_report,
                output_dir=output_dir,
            )

            self.assertTrue((output_dir / "arena_extraction_wave.json").exists())
            self.assertTrue((output_dir / "arena_extraction_wave.md").exists())
            self.assertIn("summary", report)

    def test_render_arena_extraction_wave_markdown_mentions_sections(self) -> None:
        markdown = render_arena_extraction_wave_markdown(
            {
                "summary": {
                    "cached_extractors": 2,
                    "dummy_project_extractors": 3,
                    "total_extractors": 5,
                },
                "local_cached_extractors": [
                    {
                        "title": "GASP",
                        "artifacts": {"output_dir": "C:/Temp/gasp"},
                    }
                ],
                "dummy_project_extractors": [
                    {
                        "title": "Game Animation Sample",
                        "dummy_project_job_output_dir": "C:/Temp/dummy",
                        "artifacts": {"output_dir": "C:/Temp/extractor"},
                    }
                ],
                "recommended_order": ["Run local cached extractors first."],
            }
        )

        self.assertIn("Arena Extraction Wave", markdown)
        self.assertIn("GASP", markdown)
        self.assertIn("Game Animation Sample", markdown)
