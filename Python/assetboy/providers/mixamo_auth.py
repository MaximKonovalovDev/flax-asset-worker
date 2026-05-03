from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse

import nodriver as uc
import nodriver.cdp.network as network

from assetboy.library.paths import assetboy_root
from assetboy.providers.auth_freshness import (
    DEFAULT_AUTH_STATE_STALE_AFTER_HOURS,
    describe_auth_state_freshness,
)


_ORIGINAL_COOKIE_FROM_JSON = network.Cookie.from_json


def _patch_nodriver_cookie_parser() -> None:
    """
    nodriver's generated Cookie parser expects `sameParty` on every cookie,
    but Chromium omits it on some cookies. Make that field optional.
    """
    if getattr(network.Cookie.from_json, "__name__", "") == "_assetboy_mixamo_cookie_from_json":
        return

    def _assetboy_mixamo_cookie_from_json(cls, json_payload: Dict[str, Any]) -> network.Cookie:
        payload = dict(json_payload)
        payload.setdefault("sameParty", False)
        return _ORIGINAL_COOKIE_FROM_JSON(payload)

    network.Cookie.from_json = classmethod(_assetboy_mixamo_cookie_from_json)


_patch_nodriver_cookie_parser()


def _resolve_repo_path(value: str | Path, *, current_file: str | Path = __file__) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (assetboy_root(current_file) / candidate).resolve()


class MixamoAuthSession:
    """
    Save a reusable Mixamo browser session.

    By default this reuses the same Chromium profile folder as Fab so one
    browser profile carries both marketplace logins.
    """

    def __init__(
        self,
        auth_state_path: str = ".private/mixamo_auth_state.json",
        browser_profile_dir: str = ".private/fab_browser_profile",
        debug: bool = True,
    ) -> None:
        self.auth_state_path = _resolve_repo_path(auth_state_path)
        self.auth_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir = _resolve_repo_path(browser_profile_dir)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self.auth_lock_path = self.auth_state_path.with_suffix(".lock")
        self.logger = logging.getLogger("MixamoAuthSession")
        self.logger.setLevel(logging.DEBUG if debug else logging.INFO)

    @contextmanager
    def auth_lock(self) -> Iterable[None]:
        try:
            fd = os.open(str(self.auth_lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(
                f"Mixamo auth is already running. Close the existing auth window or remove {self.auth_lock_path}."
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

    @staticmethod
    def _storage_json_to_items(storage_json: str) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        try:
            parsed = json.loads(storage_json or "{}")
            if isinstance(parsed, dict):
                for key, value in parsed.items():
                    items.append({"name": str(key), "value": str(value)})
        except Exception:
            pass
        return items

    @staticmethod
    def _origin_for_url(page_url: str) -> str:
        parsed = urlparse(page_url or "https://www.mixamo.com/")
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return "https://www.mixamo.com"

    @staticmethod
    def _page_url(page: Optional[Any]) -> str:
        if page is None:
            return ""
        return str(getattr(getattr(page, "target", None), "url", "") or "")

    @staticmethod
    def _page_title(page: Optional[Any]) -> str:
        if page is None:
            return ""
        return str(getattr(getattr(page, "target", None), "title", "") or "")

    @classmethod
    def _location_rank(cls, page_url: str, page_title: str) -> int:
        host = urlparse(page_url or "").netloc.lower()
        title = (page_title or "").lower()
        if "mixamo.com" in host or "mixamo" in title:
            return 0
        if "adobe.com" in host:
            return 1
        if "google.com" in host:
            return 2
        return 9

    @classmethod
    def _probe_rank(cls, probe: Dict[str, Any]) -> tuple[int, int, int]:
        return (
            0 if bool(probe.get("authenticated")) else 1,
            cls._location_rank(str(probe.get("page_url", "")), str(probe.get("page_title", ""))),
            1 if bool(probe.get("login_prompt_visible", True)) else 0,
        )

    def _candidate_pages(self, browser: Any, page: Optional[Any]) -> list[Any]:
        candidates: list[Any] = []
        seen: set[int] = set()
        for candidate in [page, *(getattr(browser, "tabs", []) or [])]:
            if candidate is None:
                continue
            marker = id(candidate)
            if marker in seen:
                continue
            seen.add(marker)
            candidates.append(candidate)
        return candidates

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
        page_url = str(state.get("page_url", "")).strip()
        page_title = str(state.get("page_title", "")).strip()
        on_mixamo = cls._location_rank(page_url, page_title) == 0
        if not on_mixamo:
            return False
        if bool(state.get("authenticated", False)):
            return True

        auth_storage_keys = {"access_token", "auth_token", "ims_access_token"}
        for name, value in cls._iter_storage_items(state):
            if name.lower() in auth_storage_keys and value:
                return True

        auth_cookie_names = {"ims_sid", "aux_sid", "idg_token"}
        for cookie in state.get("cookies", []) or []:
            name = str(cookie.get("name", "")).strip().lower()
            domain = str(cookie.get("domain", "")).strip().lower()
            value = str(cookie.get("value", "")).strip()
            if name in auth_cookie_names and value and ("adobe.com" in domain or "mixamo.com" in domain):
                return True

        return False

    @staticmethod
    def _build_auth_state(
        *,
        cookies_dict: list[dict[str, Any]],
        local_storage_json: str,
        session_storage_json: str,
        authenticated: bool,
        page_url: str,
        page_title: str,
        login_prompt_visible: bool,
    ) -> Dict[str, Any]:
        origin = MixamoAuthSession._origin_for_url(page_url)
        return {
            "authenticated": authenticated,
            "page_url": page_url,
            "page_title": page_title,
            "login_prompt_visible": login_prompt_visible,
            "cookies": cookies_dict,
            "origins": [
                {
                    "origin": origin,
                    "localStorage": MixamoAuthSession._storage_json_to_items(local_storage_json),
                    "sessionStorage": MixamoAuthSession._storage_json_to_items(session_storage_json),
                }
            ],
        }

    async def _await_with_timeout(
        self,
        label: str,
        awaitable: Any,
        *,
        timeout_seconds: float,
        default: Any,
    ) -> Any:
        try:
            return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            self.logger.warning(f"{label} timed out after {timeout_seconds:.0f}s; continuing with fallback.")
            return default
        except Exception as exc:
            self.logger.warning(f"{label} failed: {exc}")
            return default

    def profile_has_browser_state(self) -> bool:
        cookie_db = self.browser_profile_dir / "Default" / "Network" / "Cookies"
        local_state = self.browser_profile_dir / "Local State"
        return cookie_db.exists() or local_state.exists()

    async def _start_browser(self, *, allow_ephemeral_fallback: bool = True) -> Any:
        try:
            return await uc.start(headless=False, user_data_dir=str(self.browser_profile_dir))
        except Exception as exc:
            if not allow_ephemeral_fallback:
                raise RuntimeError(
                    f"Could not open the saved browser profile at {self.browser_profile_dir}: {exc}"
                ) from exc
            self.logger.warning(f"Persistent profile launch failed, falling back to ephemeral profile: {exc}")
            return await uc.start(headless=False)

    async def _open_mixamo_page(self, browser: Any, *, timeout_seconds: float = 20.0) -> Optional[Any]:
        page = None
        try:
            self.logger.info("Loading Mixamo...")
            task = asyncio.create_task(browser.get("https://www.mixamo.com/"))
            page = await asyncio.wait_for(task, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            self.logger.info("Mixamo page load timed out; using the existing browser tab.")
            if browser.tabs:
                page = browser.tabs[0]
        return page

    async def _probe_single_page(self, page: Optional[Any], *, timeout_seconds: float = 12.0) -> Dict[str, Any]:
        if page is None:
            return {
                "authenticated": False,
                "page_url": "",
                "page_title": "",
                "login_prompt_visible": True,
            }

        fallback_url = self._page_url(page)
        fallback_title = self._page_title(page)
        try:
            await page
        except Exception:
            pass

        probe = await self._await_with_timeout(
            "Mixamo auth probe",
            page.evaluate(
                """
                (() => {
                    const loginTerms = ["log in", "login", "sign in", "join now", "create account"];
                    const visibleTexts = Array.from(document.querySelectorAll("a,button,[role='button']"))
                        .map((el) => ((el.innerText || el.textContent || "").trim().toLowerCase()))
                        .filter(Boolean)
                        .slice(0, 250);
                    const combined = visibleTexts.join(" | ");
                    const loginPromptVisible = loginTerms.some((term) => combined.includes(term));
                    const url = window.location.href;
                    const title = document.title || "";
                    const onMixamo = window.location.hostname.toLowerCase().includes("mixamo.com");
                    return {
                        authenticated: Boolean(onMixamo && !loginPromptVisible),
                        page_url: url,
                        page_title: title,
                        login_prompt_visible: loginPromptVisible
                    };
                })()
                """,
                return_by_value=True,
            ),
            timeout_seconds=timeout_seconds,
            default={
                "authenticated": False,
                "page_url": fallback_url,
                "page_title": fallback_title,
                "login_prompt_visible": True,
            },
        )
        if isinstance(probe, dict):
            normalized = dict(probe)
            normalized["page_url"] = str(normalized.get("page_url") or fallback_url)
            normalized["page_title"] = str(normalized.get("page_title") or fallback_title)
            normalized["authenticated"] = bool(normalized.get("authenticated", False))
            normalized["login_prompt_visible"] = bool(normalized.get("login_prompt_visible", True))
            return normalized
        return {
            "authenticated": False,
            "page_url": fallback_url,
            "page_title": fallback_title,
            "login_prompt_visible": True,
        }

    async def _probe_page(
        self,
        browser: Any,
        page: Optional[Any],
        *,
        timeout_seconds: float = 12.0,
    ) -> tuple[Dict[str, Any], Optional[Any]]:
        best_page = page
        best_probe = {
            "authenticated": False,
            "page_url": self._page_url(page),
            "page_title": self._page_title(page),
            "login_prompt_visible": True,
        }

        for candidate in self._candidate_pages(browser, page):
            probe = await self._probe_single_page(candidate, timeout_seconds=timeout_seconds)
            if self._probe_rank(probe) < self._probe_rank(best_probe):
                best_probe = probe
                best_page = candidate
            if probe.get("authenticated"):
                break

        return best_probe, best_page

    async def _save_browser_state(
        self,
        browser: Any,
        page: Optional[Any],
        *,
        timeout_seconds: float = 12.0,
    ) -> Dict[str, Any]:
        probe, storage_page = await self._probe_page(browser, page, timeout_seconds=timeout_seconds)
        cookies_response = await self._await_with_timeout(
            "Mixamo cookie capture",
            browser.cookies.get_all(),
            timeout_seconds=timeout_seconds,
            default=[],
        )
        cookies_dict = [
            {
                "name": cookie.name,
                "value": cookie.value,
                "domain": cookie.domain,
                "path": cookie.path,
                "expires": cookie.expires,
                "httpOnly": cookie.http_only,
                "secure": cookie.secure,
                "sameSite": getattr(cookie.same_site, "value", str(cookie.same_site)) if cookie.same_site else "None",
            }
            for cookie in cookies_response
        ]

        local_storage_json = "{}"
        session_storage_json = "{}"
        if storage_page is not None:
            local_storage_json = await self._await_with_timeout(
                "Mixamo localStorage capture",
                storage_page.evaluate(
                    "JSON.stringify(Object.fromEntries(Object.keys(window.localStorage).map(k => [k, window.localStorage.getItem(k)])))",
                    return_by_value=True,
                ),
                timeout_seconds=timeout_seconds,
                default="{}",
            )
            session_storage_json = await self._await_with_timeout(
                "Mixamo sessionStorage capture",
                storage_page.evaluate(
                    "JSON.stringify(Object.fromEntries(Object.keys(window.sessionStorage).map(k => [k, window.sessionStorage.getItem(k)])))",
                    return_by_value=True,
                ),
                timeout_seconds=timeout_seconds,
                default="{}",
            )

        state = self._build_auth_state(
            cookies_dict=cookies_dict,
            local_storage_json=local_storage_json or "{}",
            session_storage_json=session_storage_json or "{}",
            authenticated=bool(probe.get("authenticated", False)),
            page_url=str(probe.get("page_url", "")),
            page_title=str(probe.get("page_title", "")),
            login_prompt_visible=bool(probe.get("login_prompt_visible", True)),
        )
        state["authenticated"] = self._state_looks_authenticated(state)
        if state["authenticated"]:
            state["login_prompt_visible"] = False
        state["saved_at"] = datetime.now(timezone.utc).isoformat()
        self.auth_state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state

    async def _shutdown_browser(self, browser: Any) -> None:
        connection = getattr(browser, "connection", None)
        disconnect = getattr(connection, "disconnect", None)
        if callable(disconnect):
            try:
                await self._await_with_timeout(
                    "Mixamo browser disconnect",
                    disconnect(),
                    timeout_seconds=3.0,
                    default=None,
                )
            except Exception:
                pass
        try:
            browser.stop()
        except Exception:
            pass
        await asyncio.sleep(0)

    async def refresh_auth_from_profile(self, *, timeout_seconds: float = 12.0) -> Dict[str, Any]:
        browser = await self._start_browser(allow_ephemeral_fallback=False)
        page = None
        try:
            page = await self._open_mixamo_page(browser, timeout_seconds=timeout_seconds)
            await asyncio.sleep(2)
            return await self._save_browser_state(browser, page, timeout_seconds=timeout_seconds)
        finally:
            await self._shutdown_browser(browser)

    async def acquire_session_interactive(self, *, timeout_seconds: float = 12.0) -> Dict[str, Any]:
        # Never fall back to an ephemeral browser for auth. If the shared
        # profile is unavailable, fail loudly instead of spawning a second
        # window that is not using the saved login state.
        browser = await self._start_browser(allow_ephemeral_fallback=False)
        page = None
        try:
            page = await self._open_mixamo_page(browser, timeout_seconds=timeout_seconds)

            print("\n" + "=" * 80)
            print("ACTION REQUIRED: One Mixamo window has opened using the same browser profile as Fab.")
            print("1. If Adobe asks you to sign in, finish the login.")
            print("2. Wait until Mixamo is fully open again.")
            print("3. Return to this terminal and press ENTER once.")
            print("4. Wait for the saved-session confirmation before closing anything.")
            print("=" * 80 + "\n")

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, input, "Press [ENTER] here when Mixamo is ready: ")
            await asyncio.sleep(2)

            self.logger.info("Saving Mixamo auth state...")
            state = await self._save_browser_state(browser, page, timeout_seconds=timeout_seconds)
            self.logger.info("Mixamo auth state saved.")
            return state
        finally:
            await self._shutdown_browser(browser)

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
            "page_url": "",
            "page_title": "",
            "login_prompt_visible": True,
            "error": "",
            "repair_command": "python scripts/cli.py asset-factory mixamo-auth --reuse-profile",
            "bootstrap_command": "python scripts/cli.py asset-factory mixamo-auth --allow-browser",
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
