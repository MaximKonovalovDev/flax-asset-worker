"""
mixamo_auth.py — Browser-based Mixamo authentication via nodriver.

Provides MixamoAuthSession which opens a Chrome window using a saved
profile, lets the user log into Adobe/Mixamo, then captures session
cookies and saves them for headless automated downloads.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logging.basicConfig(
    level=logging.INFO,
    format="[mixamo_auth] %(levelname)-5s %(message)s",
)
logger = logging.getLogger("mixamo_auth")

MIXAMO_BASE = "https://www.mixamo.com"


class MixamoAuthSession:
    """Manages an interactive browser-based Mixamo authentication session.

    Opens a visible Chrome window (nodriver) using a persisted browser
    profile.  The user logs into Adobe/Mixamo in the window, then presses
    ENTER in the terminal.  Cookies + page state are saved to a JSON file
    for reuse by the headless download runner.
    """

    def __init__(
        self,
        auth_state_path: str | Path,
        browser_profile_dir: str | Path,
    ):
        self.auth_state_path = Path(auth_state_path).resolve()
        self.browser_profile_dir = Path(browser_profile_dir).resolve()
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)

    async def acquire_session_interactive(
        self,
        timeout_seconds: float = 20.0,
    ) -> Dict[str, Any]:
        """Open Chrome, let user log into Mixamo, capture session state.

        Parameters
        ----------
        timeout_seconds : float
            How long to wait for the user to press ENTER after logging in.

        Returns
        -------
        dict
            Auth state with keys: authenticated, page_url, page_title,
            cookies, saved_at.  The caller should check ``state.get('authenticated')``.
        """
        import nodriver as uc

        logger.info("Starting browser with profile %s", self.browser_profile_dir)
        browser = await uc.start(
            headless=False,
            user_data_dir=str(self.browser_profile_dir),
        )
        try:
            page = await browser.get(MIXAMO_BASE)
            await asyncio.sleep(3)

            print()
            print("=" * 80)
            print("ACTION REQUIRED: A Chrome window has opened to Mixamo.")
            print("1. Log into Adobe / Mixamo in the browser window.")
            print("2. Wait until the Mixamo homepage is fully loaded.")
            print("3. Return to this terminal and press ENTER once.")
            print("4. Wait for the confirmation before closing anything.")
            print("=" * 80)
            print()

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: input("Press [ENTER] here when logged in: "),
            )
            await asyncio.sleep(2)

            cookies = await browser.cookies.get_all()
            cookies_dict = [
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path,
                    "httpOnly": c.http_only,
                    "secure": c.secure,
                }
                for c in cookies
            ]

            page_url = ""
            page_title = ""
            try:
                page_url = await page.evaluate(
                    "window.location.href", return_by_value=True
                )
                page_title = await page.evaluate(
                    "document.title", return_by_value=True
                )
            except Exception:
                pass

            state = {
                "authenticated": True,
                "page_url": str(page_url or ""),
                "page_title": str(page_title or ""),
                "cookies": cookies_dict,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }

            self.auth_state_path.parent.mkdir(parents=True, exist_ok=True)
            self.auth_state_path.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
            logger.info("Auth state saved to %s", self.auth_state_path)
            return state

        finally:
            try:
                browser.stop()
            except Exception:
                pass
