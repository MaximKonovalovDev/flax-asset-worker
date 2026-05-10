from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from assetboy.providers.legendary_bridge import (
    build_legendary_status_report,
    ensure_epic_remember_me_token,
    import_legendary_auth,
    list_legendary_ue_assets,
)


class LegendaryBridgeTests(unittest.TestCase):
    def test_build_legendary_status_report_reads_status_json(self) -> None:
        fake_result = unittest.mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "account": "angryowl91",
                    "games_available": 12,
                    "games_installed": 2,
                    "config_directory": "C:/Users/me/.config/legendary",
                }
            ),
            stderr="",
        )
        with patch("assetboy.providers.legendary_bridge.detect_legendary_executable", return_value=Path("C:/Tools/legendary.exe")):
            with patch("assetboy.providers.legendary_bridge.run_legendary_command", return_value=fake_result):
                report = build_legendary_status_report()

        self.assertEqual(report["status"]["account"], "angryowl91")
        self.assertEqual(report["status"]["games_available"], 12)

    def test_import_legendary_auth_reports_failure_cleanly(self) -> None:
        fake_result = unittest.mock.Mock(
            returncode=1,
            stdout="",
            stderr="No EGS login session found",
        )
        with patch("assetboy.providers.legendary_bridge.detect_legendary_executable", return_value=Path("C:/Tools/legendary.exe")):
            with patch("assetboy.providers.legendary_bridge.run_legendary_command", return_value=fake_result):
                report = import_legendary_auth()

        self.assertEqual(report["exit_code"], 1)
        self.assertEqual(report["error"], "legendary auth import failed")

    def test_list_legendary_ue_assets_parses_records(self) -> None:
        fake_result = unittest.mock.Mock(
            returncode=0,
            stdout=json.dumps(
                [
                    {"app_name": "GameAnimationSample", "app_title": "Game Animation Sample"},
                    {"app_name": "CitySampleBuildings", "app_title": "City Sample Buildings"},
                ]
            ),
            stderr="",
        )
        with patch("assetboy.providers.legendary_bridge.detect_legendary_executable", return_value=Path("C:/Tools/legendary.exe")):
            with patch("assetboy.providers.legendary_bridge.run_legendary_command", return_value=fake_result):
                report = list_legendary_ue_assets()

        self.assertEqual(report["summary"]["total_records"], 2)
        self.assertEqual(report["summary"]["has_titles"], 2)

    def test_ensure_epic_remember_me_token_mirrors_windows_editor_token(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            primary = root / "Windows" / "GameUserSettings.ini"
            alternate = root / "WindowsEditor" / "GameUserSettings.ini"
            primary.parent.mkdir(parents=True, exist_ok=True)
            alternate.parent.mkdir(parents=True, exist_ok=True)
            primary.write_text("[Launcher]\nCreatedProjectPaths=C:/Projects\n", encoding="utf-8")
            alternate.write_text("[Launcher]\nFoo=Bar\n\n[RememberMe]\nEnable=True\nData=abc123\n", encoding="utf-8")

            with patch("assetboy.providers.legendary_bridge.default_epic_launcher_config_path", return_value=primary):
                with patch("assetboy.providers.legendary_bridge.default_epic_launcher_windows_editor_config_path", return_value=alternate):
                    report = ensure_epic_remember_me_token()

            self.assertTrue(report["mirrored_to_primary"])
            contents = primary.read_text(encoding="utf-8")
            self.assertIn("[RememberMe]", contents)
            self.assertIn("Data=abc123", contents)
