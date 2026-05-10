from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from assetboy.providers.mixamo_auth import MixamoAuthSession


class _FakeTab:
    def __init__(
        self,
        *,
        url: str,
        title: str,
        probe_result: dict | None = None,
        raise_on_evaluate: bool = False,
    ) -> None:
        self.target = SimpleNamespace(url=url, title=title)
        self._probe_result = probe_result
        self._raise_on_evaluate = raise_on_evaluate

    def __await__(self):
        async def _noop():
            return self

        return _noop().__await__()

    def evaluate(self, _script: str, return_by_value: bool = True):
        async def _run():
            if self._raise_on_evaluate:
                raise RuntimeError("stale page")
            return self._probe_result

        return _run()


class MixamoAuthSessionTests(unittest.TestCase):
    def test_build_auth_state_preserves_mixamo_probe_fields(self) -> None:
        state = MixamoAuthSession._build_auth_state(
            cookies_dict=[{"name": "mixamo_cookie", "value": "abc"}],
            local_storage_json='{"foo":"bar"}',
            session_storage_json='{"baz":"qux"}',
            authenticated=True,
            page_url="https://www.mixamo.com/#/?query=roman",
            page_title="Mixamo",
            login_prompt_visible=False,
        )

        self.assertTrue(state["authenticated"])
        self.assertEqual(state["page_url"], "https://www.mixamo.com/#/?query=roman")
        self.assertEqual(state["page_title"], "Mixamo")
        self.assertFalse(state["login_prompt_visible"])
        self.assertEqual(state["origins"][0]["origin"], "https://www.mixamo.com")
        self.assertEqual(state["origins"][0]["localStorage"][0]["name"], "foo")

    def test_auth_lock_blocks_concurrent_runs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            session = MixamoAuthSession(
                auth_state_path=str(root / "mixamo_auth_state.json"),
                browser_profile_dir=str(root / "fab_browser_profile"),
                debug=False,
            )

            with session.auth_lock():
                with self.assertRaises(RuntimeError):
                    with session.auth_lock():
                        pass

    def test_auth_status_reports_saved_state(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth_state_path = root / "mixamo_auth_state.json"
            profile_cookie_db = root / "fab_browser_profile" / "Default" / "Network" / "Cookies"
            profile_cookie_db.parent.mkdir(parents=True, exist_ok=True)
            profile_cookie_db.write_text("cookie-db", encoding="utf-8")
            auth_state_path.write_text(
                json.dumps(
                    {
                        "authenticated": True,
                        "page_url": "https://www.mixamo.com/",
                        "page_title": "Mixamo",
                        "login_prompt_visible": False,
                        "cookies": [],
                        "origins": [],
                    }
                ),
                encoding="utf-8",
            )

            session = MixamoAuthSession(
                auth_state_path=str(auth_state_path),
                browser_profile_dir=str(root / "fab_browser_profile"),
                debug=False,
            )
            status = session.auth_status()

            self.assertTrue(status["auth_state_exists"])
            self.assertTrue(status["browser_profile_has_state"])
            self.assertTrue(status["authenticated"])
            self.assertFalse(status["login_prompt_visible"])
            self.assertEqual(status["page_title"], "Mixamo")
            self.assertFalse(status["auth_state_stale"])
            self.assertEqual(status["repair_command"], "python scripts/cli.py asset-factory mixamo-auth --reuse-profile")

    def test_probe_page_prefers_live_mixamo_tab_and_fills_fallback_metadata(self) -> None:
        session = MixamoAuthSession(debug=False)
        stale_page = _FakeTab(url="", title="", raise_on_evaluate=True)
        mixamo_page = _FakeTab(
            url="https://www.mixamo.com/#/?query=roman",
            title="Mixamo",
            probe_result={
                "authenticated": True,
                "page_url": "",
                "page_title": "",
                "login_prompt_visible": False,
            },
        )
        browser = SimpleNamespace(tabs=[stale_page, mixamo_page])

        probe, selected_page = asyncio.run(session._probe_page(browser, stale_page, timeout_seconds=0.1))

        self.assertIs(selected_page, mixamo_page)
        self.assertTrue(probe["authenticated"])
        self.assertFalse(probe["login_prompt_visible"])
        self.assertEqual(probe["page_url"], "https://www.mixamo.com/#/?query=roman")
        self.assertEqual(probe["page_title"], "Mixamo")

    def test_auth_status_infers_authenticated_from_saved_mixamo_access_token(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth_state_path = root / "mixamo_auth_state.json"
            profile_cookie_db = root / "fab_browser_profile" / "Default" / "Network" / "Cookies"
            profile_cookie_db.parent.mkdir(parents=True, exist_ok=True)
            profile_cookie_db.write_text("cookie-db", encoding="utf-8")
            auth_state_path.write_text(
                json.dumps(
                    {
                        "authenticated": False,
                        "page_url": "https://www.mixamo.com/#/",
                        "page_title": "Mixamo",
                        "login_prompt_visible": True,
                        "cookies": [],
                        "origins": [
                            {
                                "origin": "https://www.mixamo.com",
                                "localStorage": [{"name": "access_token", "value": "token123"}],
                                "sessionStorage": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            session = MixamoAuthSession(
                auth_state_path=str(auth_state_path),
                browser_profile_dir=str(root / "fab_browser_profile"),
                debug=False,
            )
            status = session.auth_status()

            self.assertTrue(status["authenticated"])
            self.assertFalse(status["login_prompt_visible"])

    def test_auth_status_marks_stale_saved_state_for_repair(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth_state_path = root / "mixamo_auth_state.json"
            auth_state_path.write_text(
                json.dumps(
                    {
                        "authenticated": True,
                        "saved_at": "2026-01-01T00:00:00+00:00",
                        "page_url": "https://www.mixamo.com/#/",
                        "page_title": "Mixamo",
                        "login_prompt_visible": False,
                        "cookies": [],
                        "origins": [],
                    }
                ),
                encoding="utf-8",
            )

            session = MixamoAuthSession(
                auth_state_path=str(auth_state_path),
                browser_profile_dir=str(root / "fab_browser_profile"),
                debug=False,
            )
            status = session.auth_status()

            self.assertFalse(status["authenticated"])
            self.assertTrue(status["auth_state_stale"])
            self.assertTrue(status["repair_recommended"])
            self.assertEqual(status["repair_reason"], "auth_state_stale")

    def test_interactive_auth_uses_shared_profile_without_ephemeral_fallback(self) -> None:
        session = MixamoAuthSession(debug=False)

        async def _run() -> None:
            async def _noop():
                return None

            fake_browser = SimpleNamespace(
                stop=lambda: None,
                connection=SimpleNamespace(disconnect=lambda: _noop()),
            )
            with patch.object(session, "_start_browser", return_value=fake_browser) as start_browser:
                with patch.object(session, "_open_mixamo_page", return_value=None):
                    with patch.object(session, "_save_browser_state", return_value={"authenticated": True}):
                        with patch("builtins.input", return_value=""):
                            with patch("asyncio.sleep", return_value=None):
                                await session.acquire_session_interactive(timeout_seconds=0.1)
            start_browser.assert_called_once_with(allow_ephemeral_fallback=False)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
