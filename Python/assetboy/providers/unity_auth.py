from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

from playwright.sync_api import Error, TimeoutError, sync_playwright

from assetboy.library.paths import assetboy_root
from assetboy.providers.auth_freshness import (
    DEFAULT_AUTH_STATE_STALE_AFTER_HOURS,
    describe_auth_state_freshness,
)

_UNITY_AUTH_PROBE_URL = "https://assetstore.unity.com/packages/3d/characters/humanoids/humans/human-character-dummy-178395"


def _resolve_repo_path(value: str | Path, *, current_file: str | Path = __file__) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (assetboy_root(current_file) / candidate).resolve()


class UnityAuthSession:
    """
    Save a reusable Unity Asset Store browser session.

    Unity uses its own Chromium profile folder. This keeps Fab/Mixamo stable
    while avoiding Unity's Chrome-profile-specific login failures.
    """

    def __init__(
        self,
        auth_state_path: str = ".private/unity_auth_state.json",
        browser_profile_dir: str = ".private/unity_browser_profile",
    ) -> None:
        self.auth_state_path = _resolve_repo_path(auth_state_path)
        self.auth_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir = _resolve_repo_path(browser_profile_dir)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self.auth_lock_path = self.auth_state_path.with_suffix(".lock")

    @contextmanager
    def auth_lock(self) -> Iterable[None]:
        try:
            fd = os.open(str(self.auth_lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(
                f"Unity auth is already running. Close the existing auth window or remove {self.auth_lock_path}."
            ) from exc

        try:
            os.write(fd, str(os.getpid()).encode("utf-8"))
            os.close(fd)
            yield
        finally:
            try:
                self.auth_lock_path.unlink(missing_ok=True)
            except Exception:
                pass

    def profile_has_browser_state(self) -> bool:
        cookie_db = self.browser_profile_dir / "Default" / "Network" / "Cookies"
        local_state = self.browser_profile_dir / "Local State"
        return cookie_db.exists() or local_state.exists()

    @staticmethod
    def _playwright_launch_kwargs(*, headless: bool) -> Dict[str, Any]:
        # Prefer the operator's installed Chrome over Playwright's bundled Chromium.
        # Unity login has proven sensitive to automation/browser differences.
        return {
            "headless": headless,
            "channel": "chrome",
            "args": ["--disable-blink-features=AutomationControlled"],
        }

    @staticmethod
    def _apply_stealth_overrides(context: Any) -> None:
        context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = window.chrome || { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            """
        )

    def _launch_persistent_context(self, playwright: Any, *, headless: bool) -> Any:
        launch_kwargs = self._playwright_launch_kwargs(headless=headless)
        try:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.browser_profile_dir),
                **launch_kwargs,
            )
        except Error:
            fallback_kwargs = dict(launch_kwargs)
            fallback_kwargs.pop("channel", None)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.browser_profile_dir),
                **fallback_kwargs,
            )
        self._apply_stealth_overrides(context)
        return context

    @staticmethod
    def _page_probe(page: Any) -> Dict[str, Any]:
        fallback_url = str(page.url or "")
        fallback_title = str(page.title() or "")
        try:
            probe = page.evaluate(
                """
                (() => {
                    const host = window.location.hostname.toLowerCase();
                    const title = (document.title || "").trim();
                    const texts = Array.from(document.querySelectorAll("a,button,[role='button'],label"))
                        .map((el) => ((el.innerText || el.textContent || "").trim().toLowerCase()))
                        .filter(Boolean)
                        .slice(0, 300);
                    const combined = texts.join(" | ");
                    const loginPromptVisible =
                        combined.includes("sign in") ||
                        combined.includes("continue with google") ||
                        combined.includes("create an account") ||
                        combined.includes("use another account") ||
                        Boolean(document.querySelector("input[type='email']"));
                    const onAssetStore = host.includes("assetstore.unity.com");
                    const onUnityLogin = host.includes("login.unity.com") || host.includes("id.unity.com");
                    return {
                        authenticated: Boolean(onAssetStore && !loginPromptVisible && !onUnityLogin),
                        page_url: window.location.href,
                        page_title: title,
                        login_prompt_visible: loginPromptVisible
                    };
                })()
                """
            )
        except Exception:
            probe = {
                "authenticated": False,
                "page_url": fallback_url,
                "page_title": fallback_title,
                "login_prompt_visible": True,
            }
        if not isinstance(probe, dict):
            probe = {}
        return {
            "authenticated": bool(probe.get("authenticated", False)),
            "page_url": str(probe.get("page_url") or fallback_url),
            "page_title": str(probe.get("page_title") or fallback_title),
            "login_prompt_visible": bool(probe.get("login_prompt_visible", True)),
        }

    @staticmethod
    def _csrf_token(page: Any) -> str:
        try:
            cookie_string = str(page.evaluate("() => document.cookie") or "")
        except Exception:
            return ""
        match = re.search(r"(?:^|; )_csrf=([^;]+)", cookie_string)
        return match.group(1) if match else ""

    @classmethod
    def _graphql_headers(cls, page: Any, *, operations: str, referer: str | None = None) -> Dict[str, str]:
        csrf_token = cls._csrf_token(page)
        if not csrf_token:
            return {}
        return {
            "x-csrf-token": csrf_token,
            "x-requested-with": "XMLHttpRequest",
            "x-source": "storefront",
            "referer": referer or str(page.url or "https://assetstore.unity.com/"),
            "operations": operations,
            "content-type": "application/json;charset=UTF-8",
            "accept": "application/json, text/plain, */*",
        }

    @classmethod
    def _graphql_batch(cls, context: Any, page: Any, *, operations: str, payload: list[dict[str, Any]]) -> Any:
        headers = cls._graphql_headers(page, operations=operations)
        if not headers:
            return None
        response = context.request.post(
            "https://assetstore.unity.com/api/graphql/batch",
            headers=headers,
            data=payload,
        )
        if response.status != 200:
            return None
        try:
            return response.json()
        except Exception:
            return None

    @classmethod
    def _api_probe(cls, context: Any, page: Any) -> Dict[str, Any]:
        query = """
        query CurrentUser($id: ID!) {
          user(id: $id) {
            id
            name
            email
            myAssets
          }
        }
        """
        fallback = {
            "checked": False,
            "authenticated": False,
            "current_user_id": "",
            "current_user_name": "",
            "current_user_email": "",
            "current_user_my_assets": None,
        }
        payload = cls._graphql_batch(
            context,
            page,
            operations="CurrentUser",
            payload=[
                {
                    "query": query,
                    "variables": {"id": "0"},
                    "operationName": "CurrentUser",
                }
            ],
        )

        if not isinstance(payload, list) or not payload:
            return fallback
        first = payload[0] if isinstance(payload[0], dict) else {}
        data = first.get("data", {}) if isinstance(first, dict) else {}
        user = data.get("user", {}) if isinstance(data, dict) else {}
        user_id = str(user.get("id", "")).strip()
        user_name = str(user.get("name", "")).strip()
        user_email = str(user.get("email", "")).strip()
        user_assets = user.get("myAssets")
        authenticated = bool(user_id and user_id != "0")
        return {
            "checked": True,
            "authenticated": authenticated,
            "current_user_id": user_id,
            "current_user_name": user_name,
            "current_user_email": user_email,
            "current_user_my_assets": user_assets,
        }

    @classmethod
    def claim_probe(cls, context: Any, page: Any, product_id: str) -> Dict[str, Any]:
        fallback = {
            "checked": False,
            "authenticated": False,
            "current_user_id": "",
            "current_user_name": "",
            "current_user_email": "",
            "product_id": str(product_id or ""),
            "product_name": "",
            "user_entitled": False,
            "order_request_id": "",
        }
        normalized_product_id = str(product_id or "").strip()
        if not normalized_product_id:
            return fallback

        current_user_query = """
        query CurrentUser($id: ID!) {
          user(id: $id) {
            id
            name
            email
            myAssets
          }
        }
        """
        add_to_cart_query = """
        query AddToCartButton($id: ID!) {
          product(id: $id) {
            id
            itemId
            userEntitlement {
              id
              orderId
              grantTime
            }
            orderRequestId
            name
          }
        }
        """

        payload = cls._graphql_batch(
            context,
            page,
            operations="CurrentUser,AddToCartButton",
            payload=[
                {
                    "query": current_user_query,
                    "variables": {"id": "0"},
                    "operationName": "CurrentUser",
                },
                {
                    "query": add_to_cart_query,
                    "variables": {"id": normalized_product_id, "request": {}},
                    "operationName": "AddToCartButton",
                },
            ],
        )
        if not isinstance(payload, list) or len(payload) < 2:
            return fallback

        current_user_data = payload[0].get("data", {}) if isinstance(payload[0], dict) else {}
        current_user = current_user_data.get("user", {}) if isinstance(current_user_data, dict) else {}
        product_data = payload[1].get("data", {}) if isinstance(payload[1], dict) else {}
        product = product_data.get("product", {}) if isinstance(product_data, dict) else {}
        user_id = str(current_user.get("id", "")).strip()
        entitlement = product.get("userEntitlement")
        order_request_id = str(product.get("orderRequestId", "") or "").strip()
        return {
            "checked": True,
            "authenticated": bool(user_id and user_id != "0"),
            "current_user_id": user_id,
            "current_user_name": str(current_user.get("name", "") or "").strip(),
            "current_user_email": str(current_user.get("email", "") or "").strip(),
            "product_id": normalized_product_id,
            "product_name": str(product.get("name", "") or "").strip(),
            "user_entitled": bool(entitlement),
            "order_request_id": order_request_id,
        }

    @staticmethod
    def _iter_storage_items(state: Dict[str, Any]) -> Iterable[tuple[str, str]]:
        for origin in state.get("origins", []) or []:
            for bucket_name in ("localStorage", "sessionStorage"):
                for item in origin.get(bucket_name, []) or []:
                    name = str(item.get("name", "")).strip()
                    value = str(item.get("value", "")).strip()
                    if name or value:
                        yield name, value

    @classmethod
    def _state_looks_authenticated(cls, state: Dict[str, Any]) -> bool:
        if "api_authenticated" in state:
            if bool(state.get("api_authenticated", False)):
                return True

        page_url = str(state.get("page_url", "")).strip()
        host = urlparse(page_url).netloc.lower()
        if "assetstore.unity.com" in host and not bool(state.get("login_prompt_visible", True)):
            return True

        auth_cookie_domains = {"unity.com", ".unity.com", "id.unity.com", "assetstore.unity.com"}
        strong_cookie_names = {
            "__secure-next-auth.session-token",
            "ls",
            "activeorgid",
        }
        has_unity_cookie = False
        has_strong_cookie = False
        for cookie in state.get("cookies", []) or []:
            domain = str(cookie.get("domain", "")).strip().lower()
            name = str(cookie.get("name", "")).strip().lower()
            value = str(cookie.get("value", "")).strip()
            if domain in auth_cookie_domains and value:
                has_unity_cookie = True
            if domain in auth_cookie_domains and name in strong_cookie_names and value:
                has_strong_cookie = True

        storage_markers = {"access_token", "id_token", "auth_token", "unity_session", "nextauth.message"}
        has_storage_marker = False
        has_asset_store_marker = False
        for name, value in cls._iter_storage_items(state):
            lower_name = name.lower()
            lower_value = value.lower()
            if lower_name in storage_markers and value:
                has_storage_marker = True
            if lower_name.startswith("myassets-") and value:
                has_asset_store_marker = True
            if "user_logged_in" in lower_value and "yes" in lower_value:
                has_asset_store_marker = True

        if "assetstore.unity.com" in host and (has_strong_cookie or has_asset_store_marker):
            return True

        return has_unity_cookie and (has_storage_marker or has_asset_store_marker) and not bool(
            state.get("login_prompt_visible", True)
        )

    def _save_context_state(self, context: Any, page: Any) -> Dict[str, Any]:
        state = context.storage_state()
        if not isinstance(state, dict):
            state = {"cookies": [], "origins": []}
        probe = self._page_probe(page)
        api_probe = self._api_probe(context, page)
        state["page_url"] = str(probe.get("page_url", ""))
        state["page_title"] = str(probe.get("page_title", ""))
        state["api_checked"] = bool(api_probe.get("checked", False))
        state["api_authenticated"] = bool(api_probe.get("authenticated", False))
        state["current_user_id"] = str(api_probe.get("current_user_id", ""))
        state["current_user_name"] = str(api_probe.get("current_user_name", ""))
        state["current_user_email"] = str(api_probe.get("current_user_email", ""))
        state["current_user_my_assets"] = api_probe.get("current_user_my_assets")
        state["login_prompt_visible"] = bool(probe.get("login_prompt_visible", True))
        state["authenticated"] = self._state_looks_authenticated(state) or bool(probe.get("authenticated", False))
        if state["authenticated"]:
            state["login_prompt_visible"] = False
        state["saved_at"] = datetime.now(timezone.utc).isoformat()
        self.auth_state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state

    def refresh_auth_from_profile(self, *, timeout_seconds: float = 12.0) -> Dict[str, Any]:
        timeout_ms = int(timeout_seconds * 1000)
        with sync_playwright() as playwright:
            context = self._launch_persistent_context(playwright, headless=True)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(_UNITY_AUTH_PROBE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(3500)
                return self._save_context_state(context, page)
            finally:
                context.close()

    def acquire_session_interactive(self, *, timeout_seconds: float = 20.0) -> Dict[str, Any]:
        timeout_ms = int(timeout_seconds * 1000)
        with sync_playwright() as playwright:
            context = self._launch_persistent_context(playwright, headless=False)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(_UNITY_AUTH_PROBE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2000)

                print("\n" + "=" * 80)
                print("ACTION REQUIRED: One Unity Asset Store window has opened using the shared browser profile.")
                print("1. Sign in to Unity if asked.")
                print("2. If Unity redirects to Google, finish the Google login flow.")
                print("3. Wait until the Unity Asset Store listing is back on screen.")
                print("4. Return here and press ENTER once.")
                print("=" * 80 + "\n")
                input("Press [ENTER] here when Unity Asset Store is ready: ")

                page.wait_for_timeout(2500)
                return self._save_context_state(context, page)
            finally:
                context.close()

    def load_auth_state(self) -> Optional[Dict[str, Any]]:
        if self.auth_state_path.exists():
            return json.loads(self.auth_state_path.read_text(encoding="utf-8"))
        return None

    def auth_status(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "auth_state_path": str(self.auth_state_path),
            "auth_state_exists": self.auth_state_path.exists(),
            "browser_profile_dir": str(self.browser_profile_dir),
            "browser_profile_has_state": self.profile_has_browser_state(),
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
            "repair_command": "python scripts/cli.py asset-factory unity-auth --reuse-profile",
            "bootstrap_command": "python scripts/cli.py asset-factory unity-auth --allow-browser",
            "repair_recommended": False,
            "repair_reason": "",
        }
        auth_state = self.load_auth_state()
        payload.update(
            describe_auth_state_freshness(
                auth_state_path=self.auth_state_path,
                auth_state=auth_state,
                stale_after_hours=DEFAULT_AUTH_STATE_STALE_AFTER_HOURS,
            )
        )
        if not auth_state:
            if payload["browser_profile_has_state"]:
                payload["repair_recommended"] = True
                payload["repair_reason"] = "profile_state_present_without_auth_snapshot"
            return payload

        payload["api_checked"] = bool(auth_state.get("api_checked", False))
        payload["api_authenticated"] = bool(auth_state.get("api_authenticated", False))
        payload["current_user_id"] = str(auth_state.get("current_user_id", ""))
        payload["current_user_name"] = str(auth_state.get("current_user_name", ""))
        payload["current_user_email"] = str(auth_state.get("current_user_email", ""))
        payload["authenticated"] = self._state_looks_authenticated(auth_state)
        payload["page_url"] = str(auth_state.get("page_url", ""))
        payload["page_title"] = str(auth_state.get("page_title", ""))
        payload["login_prompt_visible"] = bool(auth_state.get("login_prompt_visible", True)) and not payload["authenticated"]
        if bool(payload.get("auth_state_stale")):
            payload["authenticated"] = False
            payload["login_prompt_visible"] = True
            payload["repair_recommended"] = True
            payload["repair_reason"] = "auth_state_stale"
        elif not payload["authenticated"]:
            payload["repair_recommended"] = True
            payload["repair_reason"] = "auth_state_not_authenticated"
        return payload
