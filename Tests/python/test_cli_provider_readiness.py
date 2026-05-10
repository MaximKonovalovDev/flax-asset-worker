from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from assetboy import cli
from assetboy.providers import provider_readiness


class ProviderReadinessReportTests(unittest.TestCase):
    def test_build_provider_readiness_report_summarizes_core_surfaces(self) -> None:
        fake_fab = SimpleNamespace(
            auth_status=lambda: {
                "auth_state_path": "C:/fab/auth_state.json",
                "auth_state_exists": True,
                "browser_profile_dir": "C:/fab/profile",
                "browser_profile_has_state": True,
                "authenticated": False,
                "error": "",
            }
        )
        fake_mixamo = SimpleNamespace(
            auth_status=lambda: {
                "auth_state_path": "C:/mixamo/auth_state.json",
                "auth_state_exists": True,
                "browser_profile_dir": "C:/mixamo/profile",
                "browser_profile_has_state": True,
                "authenticated": True,
                "page_url": "https://www.mixamo.com/",
                "page_title": "Mixamo",
                "login_prompt_visible": False,
                "error": "",
            }
        )
        fake_unity = SimpleNamespace(
            auth_status=lambda: {
                "auth_state_path": "C:/unity/auth_state.json",
                "auth_state_exists": False,
                "browser_profile_dir": "C:/unity/profile",
                "browser_profile_has_state": False,
                "authenticated": False,
                "api_checked": False,
                "api_authenticated": False,
                "current_user_id": "",
                "current_user_name": "",
                "current_user_email": "",
                "page_url": "",
                "page_title": "",
                "login_prompt_visible": True,
                "error": "",
            }
        )
        unity_install = SimpleNamespace(
            to_dict=lambda: {
                "version": "2022.3.15f1",
                "root_dir": "C:/Program Files/Unity/Hub/Editor/2022.3.15f1",
                "editor_path": "C:/Program Files/Unity/Hub/Editor/2022.3.15f1/Editor/Unity.exe",
                "detection_source": "directory_scan",
                "usable": True,
            }
        )
        unreal_install = SimpleNamespace(
            to_dict=lambda: {
                "version": "5.4",
                "root_dir": "C:/Program Files/Epic Games/UE_5.4",
                "editor_cmd_path": "",
                "editor_gui_path": "",
                "detection_source": "directory_scan",
                "usable": False,
            }
        )

        fake_profile = SimpleNamespace(
            profile_id="hunyuan3d2.production",
            display_name="Hunyuan 3D",
            adapter_id="hunyuan3d2",
            model_name="Hunyuan3D-2",
            lane="generator",
            asset_kind="weapon_mesh",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            fab_db = tmp_path / "listings_v1.db"
            fab_db.write_text("stub", encoding="utf-8")
            launcher_dir = tmp_path / "Saved" / "Data"
            launcher_dir.mkdir(parents=True)

            with patch.object(provider_readiness, "FabHybridDownloader", return_value=fake_fab):
                with patch.object(provider_readiness, "MixamoAuthSession", return_value=fake_mixamo):
                    with patch.object(provider_readiness, "UnityAuthSession", return_value=fake_unity):
                        with patch.object(provider_readiness, "list_unity_installations", return_value=(unity_install,)):
                            with patch.object(provider_readiness, "list_unreal_installations", return_value=(unreal_install,)):
                                with patch.object(provider_readiness, "profile_ids", return_value=("hunyuan3d2.production",)):
                                    with patch.object(provider_readiness, "load_colab_profile", return_value=fake_profile):
                                        with patch.object(
                                            provider_readiness,
                                            "build_local_epic_extraction_readiness",
                                            return_value={
                                                "unreal_editor_paths": ["C:/Program Files/Epic Games/UE_5.4"],
                                                "extractor_tools": ["fmodel"],
                                                "can_extract_now": True,
                                                "recommended_path": "Epic extraction is ready.",
                                            },
                                        ):
                                            with patch.object(provider_readiness, "default_local_fab_library_db_path", return_value=fab_db):
                                                with patch.object(provider_readiness, "default_epic_launcher_saved_data_dir", return_value=launcher_dir):
                                                    with patch.object(
                                                        provider_readiness,
                                                        "build_legendary_status_report",
                                                        return_value={
                                                            "legendary_path": "",
                                                            "session": {
                                                                "remember_me_present": False,
                                                                "remember_me_data_present": False,
                                                            },
                                                            "error": "legendary executable not found",
                                                        },
                                                    ):
                                                        report = provider_readiness.build_provider_readiness_report(timeout_seconds=3.0)

        self.assertEqual(report["summary"]["total"], 9)
        self.assertEqual(report["summary"]["ready_now"], 5)
        self.assertEqual(report["summary"]["partial"], 2)
        self.assertEqual(report["summary"]["setup_required"], 2)

        rows = {row["provider_id"]: row for row in report["providers"]}
        self.assertEqual(rows["fab"]["status"], "partial")
        self.assertEqual(rows["mixamo"]["status"], "ready_now")
        self.assertEqual(rows["unity_asset_store"]["status"], "partial")
        self.assertEqual(rows["unity_export_bridge"]["status"], "ready_now")
        self.assertEqual(rows["unreal_export_bridge"]["status"], "setup_required")
        self.assertEqual(rows["epic_extraction"]["status"], "ready_now")
        self.assertEqual(rows["legendary"]["status"], "setup_required")
        self.assertEqual(rows["generator_profiles"]["status"], "ready_now")
        self.assertEqual(rows["direct_url_lane"]["autonomy_mode"], "autonomous_ready")
        self.assertEqual(rows["mixamo"]["autonomy_mode"], "auth_bootstrapped")
        self.assertEqual(rows["unity_export_bridge"]["autonomy_mode"], "local_tooling_ready")
        self.assertEqual(rows["fab"]["autonomy_mode"], "operator_action_required")
        self.assertEqual(rows["unreal_export_bridge"]["autonomy_mode"], "local_tooling_required")
        self.assertIn("browser_auth_required", rows["fab"]["blocking_reasons"])
        self.assertIn("unreal_editor_missing", rows["unreal_export_bridge"]["blocking_reasons"])
        self.assertTrue(rows["fab"]["operator_action_required"])
        self.assertTrue(rows["unreal_export_bridge"]["local_tooling_required"])
        self.assertIn("reuse-profile", rows["fab"]["next_action"])
        self.assertIn("detected", rows["unreal_export_bridge"]["next_action"].lower())
        self.assertIn("fab", report["available_runbook_ids"])
        self.assertIn("unity_asset_store", report["available_runbook_ids"])
        self.assertIn("fab", report["autonomy"]["auth_blocker_provider_ids"])
        self.assertIn("unity_asset_store", report["autonomy"]["auth_blocker_provider_ids"])
        self.assertIn("unreal_export_bridge", report["autonomy"]["tooling_blocker_provider_ids"])
        self.assertIn("legendary", report["autonomy"]["tooling_blocker_provider_ids"])
        self.assertEqual(report["autonomy"]["recommended_provider_ids"][0], "direct_url_lane")
        self.assertIn("generator_profiles", report["autonomy"]["recommended_provider_ids"])
        self.assertIn("fab", report["autonomy"]["highest_leverage_unblock_provider_ids"])

        lane_rows = {row["lane"]: row for row in report["lanes"]}
        self.assertEqual(lane_rows["direct_url"]["status"], "ready_now")
        self.assertEqual(lane_rows["manual_browser"]["ready_now"], 3)
        self.assertEqual(lane_rows["manual_browser"]["partial"], 2)
        self.assertEqual(lane_rows["manual_browser"]["setup_required"], 2)
        self.assertEqual(lane_rows["generator"]["status"], "ready_now")
        self.assertTrue(any("legendary" in action.lower() for action in report["recommended_actions"]))

    def test_build_provider_readiness_report_marks_stale_browser_auth_partial(self) -> None:
        fake_fab = SimpleNamespace(
            auth_status=lambda: {
                "auth_state_path": "C:/fab/auth_state.json",
                "auth_state_exists": True,
                "browser_profile_dir": "C:/fab/profile",
                "browser_profile_has_state": True,
                "authenticated": True,
                "auth_state_stale": True,
                "repair_recommended": True,
                "repair_command": "python scripts/cli.py asset-factory fab-auth --reuse-profile",
                "error": "",
            }
        )

        with patch.object(provider_readiness, "FabHybridDownloader", return_value=fake_fab):
            row = provider_readiness._annotate_row(provider_readiness._fab_row())

        self.assertEqual(row["status"], "partial")
        self.assertIn("browser_auth_refresh_recommended", row["blocking_reasons"])
        self.assertTrue(row["operator_action_required"])
        self.assertIn("reuse-profile", row["next_action"])

    def test_build_provider_readiness_report_auth_repair_moves_fab_to_ready_now(self) -> None:
        fake_mixamo = SimpleNamespace(
            auth_status=lambda: {
                "auth_state_path": "C:/mixamo/auth_state.json",
                "auth_state_exists": False,
                "browser_profile_dir": "C:/mixamo/profile",
                "browser_profile_has_state": False,
                "authenticated": False,
                "page_url": "",
                "page_title": "",
                "login_prompt_visible": True,
                "error": "",
            }
        )
        fake_unity = SimpleNamespace(
            auth_status=lambda: {
                "auth_state_path": "C:/unity/auth_state.json",
                "auth_state_exists": False,
                "browser_profile_dir": "C:/unity/profile",
                "browser_profile_has_state": False,
                "authenticated": False,
                "api_checked": False,
                "api_authenticated": False,
                "current_user_id": "",
                "current_user_name": "",
                "current_user_email": "",
                "page_url": "",
                "page_title": "",
                "login_prompt_visible": True,
                "error": "",
            }
        )
        unity_install = SimpleNamespace(
            to_dict=lambda: {
                "version": "2022.3.15f1",
                "root_dir": "C:/Program Files/Unity/Hub/Editor/2022.3.15f1",
                "editor_path": "C:/Program Files/Unity/Hub/Editor/2022.3.15f1/Editor/Unity.exe",
                "detection_source": "directory_scan",
                "usable": True,
            }
        )

        def build_report(fake_fab: SimpleNamespace) -> dict[str, object]:
            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                fab_db = tmp_path / "listings_v1.db"
                fab_db.write_text("stub", encoding="utf-8")
                launcher_dir = tmp_path / "Saved" / "Data"
                launcher_dir.mkdir(parents=True)

                with patch.object(provider_readiness, "FabHybridDownloader", return_value=fake_fab):
                    with patch.object(provider_readiness, "MixamoAuthSession", return_value=fake_mixamo):
                        with patch.object(provider_readiness, "UnityAuthSession", return_value=fake_unity):
                            with patch.object(provider_readiness, "list_unity_installations", return_value=(unity_install,)):
                                with patch.object(provider_readiness, "list_unreal_installations", return_value=()):
                                    with patch.object(provider_readiness, "profile_ids", return_value=()):
                                        with patch.object(
                                            provider_readiness,
                                            "build_local_epic_extraction_readiness",
                                            return_value={
                                                "unreal_editor_paths": [],
                                                "extractor_tools": ["fmodel"],
                                                "can_extract_now": True,
                                                "recommended_path": "Epic extraction is ready.",
                                            },
                                        ):
                                            with patch.object(provider_readiness, "default_local_fab_library_db_path", return_value=fab_db):
                                                with patch.object(provider_readiness, "default_epic_launcher_saved_data_dir", return_value=launcher_dir):
                                                    with patch.object(
                                                        provider_readiness,
                                                        "build_legendary_status_report",
                                                        return_value={
                                                            "legendary_path": "C:/tools/legendary.exe",
                                                            "session": {
                                                                "remember_me_present": True,
                                                                "remember_me_data_present": True,
                                                            },
                                                            "status": {"account": "demo"},
                                                            "error": "",
                                                        },
                                                    ):
                                                        return provider_readiness.build_provider_readiness_report(timeout_seconds=3.0)

        baseline_report = build_report(
            SimpleNamespace(
                auth_status=lambda: {
                    "auth_state_path": "C:/fab/auth_state.json",
                    "auth_state_exists": False,
                    "browser_profile_dir": "C:/fab/profile",
                    "browser_profile_has_state": False,
                    "authenticated": False,
                    "error": "",
                }
            )
        )
        repaired_report = build_report(
            SimpleNamespace(
                auth_status=lambda: {
                    "auth_state_path": "C:/fab/auth_state.json",
                    "auth_state_exists": True,
                    "browser_profile_dir": "C:/fab/profile",
                    "browser_profile_has_state": True,
                    "authenticated": True,
                    "saved_at": "2026-04-05T12:00:00Z",
                    "saved_at_source": "state_file",
                    "auth_state_stale": False,
                    "error": "",
                }
            )
        )

        baseline_rows = {row["provider_id"]: row for row in baseline_report["providers"]}
        repaired_rows = {row["provider_id"]: row for row in repaired_report["providers"]}

        self.assertEqual(baseline_rows["fab"]["status"], "setup_required")
        self.assertEqual(repaired_rows["fab"]["status"], "ready_now")
        self.assertIn("fab", baseline_report["autonomy"]["auth_blocker_provider_ids"])
        self.assertNotIn("fab", repaired_report["autonomy"]["auth_blocker_provider_ids"])
        self.assertIn("fab", repaired_report["autonomy"]["auth_bootstrapped_provider_ids"])


class CliProviderReadinessTests(unittest.TestCase):
    def test_parser_accepts_provider_readiness_flags(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["print-provider-readiness", "--timeout", "9", "--json"])
        self.assertEqual(args.command, "print-provider-readiness")
        self.assertEqual(args.timeout, 9.0)
        self.assertTrue(args.as_json)

    def test_run_print_provider_readiness_outputs_json(self) -> None:
        fake_report = {
            "summary": {"total": 1, "ready_now": 1, "partial": 0, "setup_required": 0},
            "autonomy": {
                "recommended_provider_ids": ["direct_url_lane"],
                "highest_leverage_unblock_provider_ids": [],
                "auth_blocker_provider_ids": [],
                "tooling_blocker_provider_ids": [],
            },
            "lanes": [],
            "providers": [
                {
                    "provider_id": "direct_url_lane",
                    "display_name": "Direct URL Lane",
                    "lane": "direct_url",
                    "status": "ready_now",
                    "autonomy_mode": "autonomous_ready",
                    "blocking_reasons": [],
                    "operator_action_required": False,
                    "local_tooling_required": False,
                    "next_action": "Queue direct sources immediately.",
                    "details": {"adapter_count": 12},
                    "runbook_id": "direct_url_lane",
                }
            ],
            "available_runbook_ids": ["direct_url_lane"],
            "recommended_actions": [],
        }

        with patch.object(cli, "build_provider_readiness_report", return_value=fake_report):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cli._run_print_provider_readiness(as_json=True, timeout_seconds=4.0)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["ready_now"], 1)
        self.assertEqual(payload["providers"][0]["provider_id"], "direct_url_lane")

    def test_parser_accepts_provider_autonomy_delta_flags(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["print-provider-autonomy-deltas", "--timeout", "6", "--json"])
        self.assertEqual(args.command, "print-provider-autonomy-deltas")
        self.assertEqual(args.timeout, 6.0)
        self.assertTrue(args.as_json)

    def test_run_print_provider_autonomy_deltas_outputs_json(self) -> None:
        fake_report = {
            "summary": {
                "all_clear": False,
                "auth_blocker_count": 1,
                "tooling_blocker_count": 1,
            },
            "auth_blocker_provider_ids": ["fab"],
            "tooling_blocker_provider_ids": ["unreal_export_bridge"],
            "auth_blockers": [
                {
                    "provider_id": "fab",
                    "display_name": "Fab",
                    "lane": "manual_browser",
                    "status": "setup_required",
                    "autonomy_mode": "operator_action_required",
                    "blocking_reasons": ["browser_auth_required"],
                    "next_action": "Run fab-auth.",
                }
            ],
            "tooling_blockers": [
                {
                    "provider_id": "unreal_export_bridge",
                    "display_name": "Unreal Export Bridge",
                    "lane": "manual_browser",
                    "status": "setup_required",
                    "autonomy_mode": "local_tooling_required",
                    "blocking_reasons": ["unreal_editor_missing"],
                    "next_action": "Repair Unreal editor.",
                }
            ],
        }

        with patch.object(cli, "build_provider_autonomy_delta_report", return_value=fake_report):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cli._run_print_provider_autonomy_deltas(as_json=True, timeout_seconds=4.0)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["auth_blocker_count"], 1)
        self.assertEqual(payload["auth_blocker_provider_ids"], ["fab"])

    def test_parser_accepts_provider_runbook_json_flag(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(["print-provider-runbook", "--provider", "fab", "--json"])
        self.assertEqual(args.command, "print-provider-runbook")
        self.assertEqual(args.provider, "fab")
        self.assertTrue(args.as_json)

    def test_run_print_provider_runbook_outputs_json(self) -> None:
        fake_payload = {
            "provider_id": "fab",
            "display_name": "Fab",
            "provider_family": "manual_browser",
            "setup_steps": ["login"],
            "progression_steps": ["download"],
            "review_checklist": ["capture provenance"],
            "rendered_text": "provider_id=fab",
        }

        with patch.object(cli, "build_provider_runbook_payload", return_value=fake_payload):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cli._run_print_provider_runbook("fab", as_json=True)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["provider_id"], "fab")
        self.assertEqual(payload["provider_family"], "manual_browser")
