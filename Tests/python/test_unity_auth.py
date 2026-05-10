from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from assetboy.library.paths import assetboy_root
from assetboy.providers.unity_auth import UnityAuthSession


class UnityAuthSessionTests(unittest.TestCase):
    def test_relative_paths_anchor_to_assetboy_repo(self) -> None:
        session = UnityAuthSession()
        expected_root = assetboy_root()
        self.assertEqual(session.auth_state_path, expected_root / ".private" / "unity_auth_state.json")
        self.assertEqual(session.browser_profile_dir, expected_root / ".private" / "unity_browser_profile")

    def test_playwright_launch_kwargs_prefer_real_chrome(self) -> None:
        session = UnityAuthSession()

        launch_kwargs = session._playwright_launch_kwargs(headless=True)

        self.assertTrue(launch_kwargs["headless"])
        self.assertEqual(launch_kwargs["channel"], "chrome")
        self.assertIn("--disable-blink-features=AutomationControlled", launch_kwargs["args"])

    def test_apply_stealth_overrides_registers_init_script(self) -> None:
        session = UnityAuthSession()

        class _FakeContext:
            def __init__(self) -> None:
                self.script = ""

            def add_init_script(self, script: str) -> None:
                self.script = script

        fake_context = _FakeContext()
        session._apply_stealth_overrides(fake_context)

        self.assertIn("navigator, 'webdriver'", fake_context.script)
        self.assertIn("window.chrome", fake_context.script)

    def test_auth_status_reports_authenticated_saved_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            auth_state_path = Path(temp_dir) / "unity_auth_state.json"
            profile_dir = Path(temp_dir) / "unity_browser_profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / "Local State").write_text("{}", encoding="utf-8")
            auth_state_path.write_text(
                json.dumps(
                    {
                        "cookies": [{"domain": "assetstore.unity.com", "value": "cookie"}],
                        "origins": [
                            {
                                "origin": "https://assetstore.unity.com",
                                "localStorage": [{"name": "access_token", "value": "token"}],
                                "sessionStorage": [],
                            }
                        ],
                        "page_url": "https://assetstore.unity.com/packages/foo",
                        "page_title": "Unity Asset Store",
                        "login_prompt_visible": False,
                    }
                ),
                encoding="utf-8",
            )

            session = UnityAuthSession(
                auth_state_path=str(auth_state_path),
                browser_profile_dir=str(profile_dir),
            )
            status = session.auth_status()

        self.assertTrue(status["auth_state_exists"])
        self.assertTrue(status["browser_profile_has_state"])
        self.assertTrue(status["authenticated"])
        self.assertFalse(status["auth_state_stale"])
        self.assertEqual(status["repair_command"], "python scripts/cli.py asset-factory unity-auth --reuse-profile")

    def test_auth_status_accepts_saved_unity_session_even_if_login_prompt_probe_is_noisy(self) -> None:
        with TemporaryDirectory() as temp_dir:
            auth_state_path = Path(temp_dir) / "unity_auth_state.json"
            profile_dir = Path(temp_dir) / "unity_browser_profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / "Local State").write_text("{}", encoding="utf-8")
            auth_state_path.write_text(
                json.dumps(
                    {
                        "cookies": [
                            {
                                "name": "__Secure-next-auth.session-token",
                                "domain": "assetstore.unity.com",
                                "value": "token",
                            },
                            {
                                "name": "activeOrgId",
                                "domain": "assetstore.unity.com",
                                "value": "12345",
                            },
                        ],
                        "origins": [
                            {
                                "origin": "https://assetstore.unity.com",
                                "localStorage": [
                                    {"name": "myAssets-12345", "value": "[\"178395\"]"},
                                    {"name": "nextauth.message", "value": "{\"event\":\"session\"}"},
                                ],
                                "sessionStorage": [],
                            }
                        ],
                        "page_url": "https://assetstore.unity.com/",
                        "page_title": "The Best Assets for Game Making | Unity Asset Store",
                        "login_prompt_visible": True,
                    }
                ),
                encoding="utf-8",
            )

            session = UnityAuthSession(
                auth_state_path=str(auth_state_path),
                browser_profile_dir=str(profile_dir),
            )
            status = session.auth_status()

        self.assertTrue(status["authenticated"])
        self.assertFalse(status["login_prompt_visible"])

    def test_auth_status_falls_back_to_browser_evidence_when_api_probe_is_anonymous(self) -> None:
        with TemporaryDirectory() as temp_dir:
            auth_state_path = Path(temp_dir) / "unity_auth_state.json"
            profile_dir = Path(temp_dir) / "unity_browser_profile"
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / "Local State").write_text("{}", encoding="utf-8")
            auth_state_path.write_text(
                json.dumps(
                    {
                        "cookies": [
                            {
                                "name": "activeOrgId",
                                "domain": "assetstore.unity.com",
                                "value": "12345",
                            }
                        ],
                        "origins": [
                            {
                                "origin": "https://assetstore.unity.com",
                                "localStorage": [
                                    {"name": "myAssets-12345", "value": "[\"178395\"]"},
                                ],
                                "sessionStorage": [],
                            }
                        ],
                        "page_url": "https://assetstore.unity.com/",
                        "page_title": "Unity Asset Store",
                        "login_prompt_visible": False,
                        "api_checked": True,
                        "api_authenticated": False,
                        "current_user_id": "0",
                    }
                ),
                encoding="utf-8",
            )

            session = UnityAuthSession(
                auth_state_path=str(auth_state_path),
                browser_profile_dir=str(profile_dir),
            )
            status = session.auth_status()

        self.assertTrue(status["authenticated"])
        self.assertTrue(status["api_checked"])
        self.assertFalse(status["api_authenticated"])
        self.assertEqual(status["current_user_id"], "0")
        self.assertFalse(status["login_prompt_visible"])

    def test_auth_status_marks_stale_saved_state_for_repair(self) -> None:
        with TemporaryDirectory() as temp_dir:
            auth_state_path = Path(temp_dir) / "unity_auth_state.json"
            auth_state_path.write_text(
                json.dumps(
                    {
                        "authenticated": True,
                        "saved_at": "2026-01-01T00:00:00+00:00",
                        "cookies": [{"domain": "assetstore.unity.com", "value": "cookie"}],
                        "origins": [],
                        "page_url": "https://assetstore.unity.com/packages/foo",
                        "page_title": "Unity Asset Store",
                        "login_prompt_visible": False,
                    }
                ),
                encoding="utf-8",
            )

            session = UnityAuthSession(auth_state_path=str(auth_state_path))
            status = session.auth_status()

        self.assertFalse(status["authenticated"])
        self.assertTrue(status["auth_state_stale"])
        self.assertTrue(status["repair_recommended"])
        self.assertEqual(status["repair_reason"], "auth_state_stale")
