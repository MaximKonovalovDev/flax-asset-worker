import os
import json
import logging
import asyncio
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Iterable
from pathlib import Path
from curl_cffi import requests

import nodriver as uc
import nodriver.cdp.network as network
import nodriver.cdp.fetch as fetch

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
    if getattr(network.Cookie.from_json, "__name__", "") == "_assetboy_cookie_from_json":
        return

    def _assetboy_cookie_from_json(cls, json: Dict[str, Any]) -> network.Cookie:
        payload = dict(json)
        payload.setdefault("sameParty", False)
        return _ORIGINAL_COOKIE_FROM_JSON(payload)

    network.Cookie.from_json = classmethod(_assetboy_cookie_from_json)


_patch_nodriver_cookie_parser()


def _resolve_repo_path(value: str | Path, *, current_file: str | Path = __file__) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (assetboy_root(current_file) / candidate).resolve()


def _fab_library_format_codes(item: dict[str, Any]) -> list[str]:
    listing = item.get("listing") or {}
    asset_formats = listing.get("assetFormats") or []
    codes: list[str] = []
    for format_entry in asset_formats:
        format_meta = format_entry.get("assetFormatType") or {}
        code = str(format_meta.get("code", "")).strip()
        if code:
            codes.append(code)
    return codes


def _fab_library_route(format_codes: list[str]) -> str:
    non_unreal_codes = [code for code in format_codes if code != "unreal-engine"]
    if non_unreal_codes:
        return "neutral_or_mixed"
    if "unreal-engine" in format_codes:
        return "unreal_only"
    return "unknown"


def _fab_library_keywords(title: str) -> list[str]:
    tokens = (
        "roman",
        "arena",
        "gladiator",
        "colosseum",
        "sword",
        "shield",
        "spear",
        "weapon",
        "combat",
        "animation",
        "enemy",
        "character",
    )
    title_lower = title.lower()
    return [token for token in tokens if token in title_lower]


def fetch_fab_library_page(
    session: requests.Session,
    *,
    url: str | None = None,
    cursor: str | None = None,
    sort_by: str = "-createdAt",
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    if url:
        response = session.get(url, timeout=timeout_seconds)
    else:
        params: dict[str, str] = {"sort_by": sort_by}
        if cursor:
            params["cursor"] = cursor
        response = session.get(
            "https://www.fab.com/i/library/search",
            params=params,
            timeout=timeout_seconds,
        )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Fab library search returned an unexpected payload.")
    return payload


def build_online_fab_library_map(
    *,
    auth_state_path: str | Path | None = None,
    browser_profile_dir: str | Path | None = None,
    timeout_seconds: float = 30.0,
    max_pages: int = 200,
) -> dict[str, Any]:
    downloader = FabHybridDownloader(
        auth_state_path=str(auth_state_path) if auth_state_path is not None else ".private/fab_auth_state.json",
        browser_profile_dir=str(browser_profile_dir) if browser_profile_dir is not None else ".private/fab_browser_profile",
        debug=False,
    )
    auth_state = downloader.load_auth_state()
    if not auth_state:
        return {
            "account_display_name": "",
            "records": [],
            "roman_candidates": [],
            "summary": {
                "total_records": 0,
                "downloadable_records": 0,
                "unreal_only_records": 0,
                "neutral_or_mixed_records": 0,
                "page_count": 0,
                "roman_candidate_count": 0,
                "format_counts": {},
                "listing_type_counts": {},
                "publisher_counts": {},
            },
            "error": "No Fab auth state found.",
        }

    session = downloader.create_cffi_session(auth_state)
    if not downloader.is_authenticated(session):
        return {
            "account_display_name": "",
            "records": [],
            "roman_candidates": [],
            "summary": {
                "total_records": 0,
                "downloadable_records": 0,
                "unreal_only_records": 0,
                "neutral_or_mixed_records": 0,
                "page_count": 0,
                "roman_candidate_count": 0,
                "format_counts": {},
                "listing_type_counts": {},
                "publisher_counts": {},
            },
            "error": "Saved Fab auth is not authenticated.",
        }

    user_response = session.get("https://www.fab.com/i/users/me", timeout=timeout_seconds)
    user_response.raise_for_status()
    user_payload = user_response.json() if user_response.content else {}
    account_display_name = str(user_payload.get("displayName", "")).strip()

    records: list[dict[str, Any]] = []
    roman_candidates: list[dict[str, Any]] = []
    seen_listing_uids: set[str] = set()
    format_counts: Counter[str] = Counter()
    listing_type_counts: Counter[str] = Counter()
    publisher_counts: Counter[str] = Counter()

    next_url: str | None = None
    page_count = 0
    for _ in range(max_pages):
        payload = fetch_fab_library_page(
            session,
            url=next_url,
            timeout_seconds=timeout_seconds,
        )
        page_count += 1
        results = payload.get("results") or []
        if not isinstance(results, list):
            raise RuntimeError("Fab library search results were not a list.")

        for item in results:
            if not isinstance(item, dict):
                continue
            listing = item.get("listing") or {}
            listing_uid = str(listing.get("uid") or item.get("uid") or "").strip()
            if not listing_uid or listing_uid in seen_listing_uids:
                continue
            seen_listing_uids.add(listing_uid)

            title = str(listing.get("title", "")).strip()
            format_codes = _fab_library_format_codes(item)
            route = _fab_library_route(format_codes)
            publisher = listing.get("publisher") if isinstance(listing.get("publisher"), dict) else {}
            publisher_name = str(publisher.get("sellerName", "")).strip()
            listing_type = str(listing.get("listingType", "")).strip()
            license_paths = [
                str(license_item.get("path", "")).strip()
                for license_item in ((item.get("entitlement") or {}).get("licenses") or [])
                if str(license_item.get("path", "")).strip()
            ]
            keywords = _fab_library_keywords(title)

            mapped = {
                "uid": str(item.get("uid", "")).strip(),
                "listing_uid": listing_uid,
                "title": title,
                "publisher_name": publisher_name,
                "listing_type": listing_type,
                "created_at": str(item.get("createdAt", "")).strip(),
                "can_request_download_url": bool(item.get("canRequestDownloadUrl")),
                "route": route,
                "format_codes": format_codes,
                "license_paths": license_paths,
                "keywords": keywords,
                "listing_url": f"https://www.fab.com/listings/{listing_uid}",
            }
            records.append(mapped)
            if keywords:
                roman_candidates.append(mapped)

            for code in format_codes:
                format_counts[code] += 1
            if listing_type:
                listing_type_counts[listing_type] += 1
            if publisher_name:
                publisher_counts[publisher_name] += 1

        raw_next_url = payload.get("next")
        next_url = raw_next_url.strip() if isinstance(raw_next_url, str) and raw_next_url.strip() else None
        if not next_url or not results:
            break

    downloadable_records = sum(1 for item in records if item["can_request_download_url"])
    unreal_only_records = sum(1 for item in records if item["route"] == "unreal_only")
    neutral_or_mixed_records = sum(1 for item in records if item["route"] == "neutral_or_mixed")
    roman_candidates.sort(key=lambda item: (len(item["keywords"]), item["title"].lower()), reverse=True)

    return {
        "account_display_name": account_display_name,
        "records": records,
        "roman_candidates": roman_candidates,
        "summary": {
            "total_records": len(records),
            "downloadable_records": downloadable_records,
            "unreal_only_records": unreal_only_records,
            "neutral_or_mixed_records": neutral_or_mixed_records,
            "page_count": page_count,
            "roman_candidate_count": len(roman_candidates),
            "format_counts": dict(sorted(format_counts.items(), key=lambda item: (-item[1], item[0]))),
            "listing_type_counts": dict(sorted(listing_type_counts.items(), key=lambda item: (-item[1], item[0]))),
            "publisher_counts": dict(sorted(publisher_counts.items(), key=lambda item: (-item[1], item[0]))),
        },
    }


def render_online_fab_library_map_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# Online Fab Library Map",
        "",
        f"- Account: `{report.get('account_display_name', '') or 'unknown'}`",
        f"- Total owned listings: `{summary.get('total_records', 0)}`",
        f"- Downloadable listings: `{summary.get('downloadable_records', 0)}`",
        f"- Neutral or mixed-format listings: `{summary.get('neutral_or_mixed_records', 0)}`",
        f"- Unreal-only listings: `{summary.get('unreal_only_records', 0)}`",
        f"- Pages fetched: `{summary.get('page_count', 0)}`",
        f"- Roman or arena keyword matches: `{summary.get('roman_candidate_count', 0)}`",
        "",
    ]

    error = str(report.get("error", "")).strip()
    if error:
        lines.extend([f"- Error: `{error}`", ""])
        return "\n".join(lines).strip() + "\n"

    format_counts = summary.get("format_counts") or {}
    if format_counts:
        lines.extend(["## Format Mix", ""])
        for code, count in list(format_counts.items())[:15]:
            lines.append(f"- `{code}`: `{count}`")
        lines.append("")

    listing_type_counts = summary.get("listing_type_counts") or {}
    if listing_type_counts:
        lines.extend(["## Listing Types", ""])
        for code, count in list(listing_type_counts.items())[:15]:
            lines.append(f"- `{code}`: `{count}`")
        lines.append("")

    roman_candidates = report.get("roman_candidates") or []
    if roman_candidates:
        lines.extend(["## Roman Candidates", ""])
        for item in roman_candidates[:20]:
            lines.append(
                f"- {item['title']} | route=`{item['route']}` | formats=`{', '.join(item['format_codes']) or 'none'}` | seller=`{item['publisher_name'] or 'unknown'}`"
            )
        lines.append("")

    records = report.get("records") or []
    if records:
        lines.extend(["## First 25 Records", ""])
        for item in records[:25]:
            lines.append(
                f"- {item['title']} | type=`{item['listing_type'] or 'unknown'}` | route=`{item['route']}` | formats=`{', '.join(item['format_codes']) or 'none'}`"
            )
        lines.append("")

    return "\n".join(lines).strip() + "\n"

class FabHybridDownloader:
    """
    Hybrid Downloader using nodriver to bypass Cloudflare Turnstile.
    1. Uses nodriver to extract the auth state (bypassing Cloudflare JS challenges/login issues).
    2. Uses curl_cffi (impersonate="chrome120") to make the raw API calls and download the payload.
    """
    def __init__(
        self,
        auth_state_path: str = '.private/fab_auth_state.json',
        browser_profile_dir: str = '.private/fab_browser_profile',
        debug: bool = True,
    ):
        self.auth_state_path = _resolve_repo_path(auth_state_path)
        self.auth_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir = _resolve_repo_path(browser_profile_dir)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self.auth_lock_path = self.auth_state_path.with_suffix(".lock")
        self.logger = logging.getLogger("FabHybridDownloader")
        if debug:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

    @contextmanager
    def auth_lock(self) -> Iterable[None]:
        try:
            fd = os.open(str(self.auth_lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RuntimeError(
                f"Fab auth is already running. Close the existing auth window or remove {self.auth_lock_path}."
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
    def _iter_storage_values(auth_state: Dict[str, Any]) -> Iterable[tuple[str, str]]:
        for origin in auth_state.get("origins", []):
            for bucket_name in ("localStorage", "sessionStorage"):
                for item in origin.get(bucket_name, []) or []:
                    name = str(item.get("name", ""))
                    value = str(item.get("value", ""))
                    if name or value:
                        yield name, value

    @classmethod
    def _extract_access_token(cls, auth_state: Dict[str, Any]) -> Optional[str]:
        def scan(value: Any) -> Optional[str]:
            if isinstance(value, dict):
                for key in ("access_token", "accessToken"):
                    token = value.get(key)
                    if isinstance(token, str) and token:
                        return token
                for nested in value.values():
                    token = scan(nested)
                    if token:
                        return token
                return None
            if isinstance(value, list):
                for nested in value:
                    token = scan(nested)
                    if token:
                        return token
                return None
            if isinstance(value, str):
                text = value.strip()
                if text.startswith("eg1~"):
                    return text
                if text.startswith("{") or text.startswith("["):
                    try:
                        return scan(json.loads(text))
                    except Exception:
                        return None
            return None

        for _, raw_value in cls._iter_storage_values(auth_state):
            token = scan(raw_value)
            if token:
                return token
        return None

    @staticmethod
    def _format_codes(asset_formats: list[dict[str, Any]]) -> list[str]:
        codes: list[str] = []
        for format_entry in asset_formats or []:
            format_meta = format_entry.get("assetFormatType") or {}
            code = str(format_meta.get("code", "")).strip()
            if code:
                codes.append(code)
        return codes

    @classmethod
    def _classify_asset_formats(cls, asset_formats: list[dict[str, Any]]) -> str:
        codes = cls._format_codes(asset_formats)
        if any(code != "unreal-engine" for code in codes):
            return "direct"
        if "unreal-engine" in codes:
            return "unreal-engine-only"
        return "unknown"

    @staticmethod
    def _extract_first_url(payload: Any) -> Optional[str]:
        if isinstance(payload, dict):
            for value in payload.values():
                url = FabHybridDownloader._extract_first_url(value)
                if url:
                    return url
            return None
        if isinstance(payload, list):
            for value in payload:
                url = FabHybridDownloader._extract_first_url(value)
                if url:
                    return url
            return None
        if isinstance(payload, str) and payload.startswith("http"):
            return payload
        return None

    @staticmethod
    def _pick_download_file(asset_formats: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        # Prefer engine-ready interchange formats before DCC-native project files.
        format_priority = {
            "fbx": 0,
            "gltf": 1,
            "glb": 1,
            "obj": 2,
            "blender": 3,
            "maya": 4,
            "usdz": 5,
            "usd": 5,
            "additional-files": 10,
        }
        candidates: list[tuple[tuple[int, int], str, dict[str, Any]]] = []
        for format_entry in asset_formats or []:
            format_meta = format_entry.get("assetFormatType") or {}
            format_code = str(format_meta.get("code", "")).strip()
            if not format_code or format_code == "unreal-engine":
                continue
            for file_entry in format_entry.get("files") or []:
                uid = str(file_entry.get("uid", "")).strip()
                if not uid:
                    continue
                size = int(file_entry.get("fileSize") or 0)
                candidates.append(((format_priority.get(format_code, 20), -size), format_code, file_entry))
        if not candidates:
            raise RuntimeError("No directly downloadable non-Unreal asset files found for this listing.")
        candidates.sort(key=lambda item: item[0])
        _, chosen_format, chosen_file = candidates[0]
        return chosen_format, chosen_file

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

    @staticmethod
    def _build_auth_state(
        *,
        cookies_dict: list[dict[str, Any]],
        local_storage_json: str,
        session_storage_json: str,
    ) -> Dict[str, Any]:
        return {
            "cookies": cookies_dict,
            "origins": [
                {
                    "origin": "https://www.fab.com",
                    "localStorage": FabHybridDownloader._storage_json_to_items(local_storage_json),
                    "sessionStorage": FabHybridDownloader._storage_json_to_items(session_storage_json),
                }
            ],
        }

    async def _save_browser_state(
        self,
        browser: Any,
        page: Optional[Any],
        *,
        timeout_seconds: float = 12.0,
    ) -> Dict[str, Any]:
        cookies_response = await self._await_with_timeout(
            "Fab cookie capture",
            browser.cookies.get_all(),
            timeout_seconds=timeout_seconds,
            default=[],
        )
        cookies_dict = [
            {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path,
                "expires": c.expires,
                "httpOnly": c.http_only,
                "secure": c.secure,
                "sameSite": getattr(c.same_site, 'value', str(c.same_site)) if c.same_site else "None"
            }
            for c in cookies_response
        ]

        local_storage_json = "{}"
        session_storage_json = "{}"
        if page is not None:
            local_storage_json = await self._await_with_timeout(
                "Fab localStorage capture",
                page.evaluate(
                    "JSON.stringify(Object.fromEntries(Object.keys(window.localStorage).map(k => [k, window.localStorage.getItem(k)])))",
                    return_by_value=True,
                ),
                timeout_seconds=timeout_seconds,
                default="{}",
            )
            session_storage_json = await self._await_with_timeout(
                "Fab sessionStorage capture",
                page.evaluate(
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
        )
        state["saved_at"] = datetime.now(timezone.utc).isoformat()
        with open(self.auth_state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        return state

    def profile_has_browser_state(self) -> bool:
        cookie_db = self.browser_profile_dir / "Default" / "Network" / "Cookies"
        local_state = self.browser_profile_dir / "Local State"
        return cookie_db.exists() or local_state.exists()

    async def _start_browser(self, *, allow_ephemeral_fallback: bool = True) -> Any:
        try:
            return await uc.start(headless=False, user_data_dir=str(self.browser_profile_dir))
        except Exception as e:
            if not allow_ephemeral_fallback:
                raise RuntimeError(
                    f"Could not open the saved Fab browser profile at {self.browser_profile_dir}: {e}"
                ) from e
            self.logger.warning(f"Persistent profile launch failed, falling back to ephemeral profile: {e}")
            return await uc.start(headless=False)

    async def _open_fab_page(self, browser: Any, *, timeout_seconds: float = 15.0) -> Optional[Any]:
        page = None
        try:
            self.logger.info("Loading Fab.com...")
            task = asyncio.create_task(browser.get("https://www.fab.com/"))
            page = await asyncio.wait_for(task, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            self.logger.info("Fab page load timed out; using the existing browser tab.")
            if browser.tabs:
                page = browser.tabs[0]
        return page

    async def refresh_auth_from_profile(self, *, timeout_seconds: float = 12.0) -> Dict[str, Any]:
        """
        Re-open the saved Fab browser profile and extract a fresh auth file.
        Useful when the site login already exists but auth_state.json is missing.
        """
        browser = await self._start_browser(allow_ephemeral_fallback=False)
        page = None
        try:
            page = await self._open_fab_page(browser, timeout_seconds=timeout_seconds)
            await asyncio.sleep(2)
            return await self._save_browser_state(browser, page, timeout_seconds=timeout_seconds)
        finally:
            try:
                browser.stop()
            except Exception:
                pass

    async def acquire_session_interactive(self, *, timeout_seconds: float = 12.0) -> Dict[str, Any]:
        """
        Launches headed nodriver to let the user log in to Fab.com.
        Saves the cookies and localStorage state.
        """
        self.logger.info("Acquiring session interactively via nodriver...")
        # Never fall back to an ephemeral browser for auth. If the shared
        # profile is unavailable, fail loudly instead of spawning a second
        # window that is both unsigned-in and easy to mistake for the real one.
        browser = await self._start_browser(allow_ephemeral_fallback=False)
        page = None
        try:
            page = await self._open_fab_page(browser, timeout_seconds=timeout_seconds)

            print("\n" + "=" * 80)
            print("ACTION REQUIRED: A Chromium window has opened.")
            print("1. Log into your Epic Games / Fab account.")
            print("2. Wait until your Fab profile picture is visible.")
            print("3. Return to this terminal and press ENTER once.")
            print("4. Wait for the confirmation line before closing anything.")
            print("=" * 80 + "\n")

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, input, "Press [ENTER] here when done: ")
            await asyncio.sleep(2)

            self.logger.info("Saving Fab auth state...")
            state = await self._save_browser_state(browser, page, timeout_seconds=timeout_seconds)
            self.logger.info("Fab auth state saved.")
            return state
        finally:
            try:
                browser.stop()
            except Exception:
                pass

    def load_auth_state(self) -> Optional[Dict[str, Any]]:
        if self.auth_state_path.exists():
            with open(self.auth_state_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def auth_status(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "auth_state_path": str(self.auth_state_path),
            "auth_state_exists": self.auth_state_path.exists(),
            "browser_profile_dir": str(self.browser_profile_dir),
            "browser_profile_has_state": self.profile_has_browser_state(),
            "authenticated": False,
            "error": "",
            "repair_command": "python scripts/cli.py asset-factory fab-auth --reuse-profile",
            "bootstrap_command": "python scripts/cli.py asset-factory fab-auth --allow-browser",
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

        try:
            session = self.create_cffi_session(auth_state)
            payload["authenticated"] = self.is_authenticated(session)
        except Exception as exc:
            payload["error"] = str(exc)
        if payload["error"]:
            payload["repair_recommended"] = True
            payload["repair_reason"] = "auth_probe_failed"
        elif bool(payload.get("auth_state_stale")):
            payload["authenticated"] = False
            payload["repair_recommended"] = True
            payload["repair_reason"] = "auth_state_stale"
        elif not payload["authenticated"]:
            payload["repair_recommended"] = True
            payload["repair_reason"] = "auth_state_not_authenticated"
        return payload

    @staticmethod
    def _cookie_header_value(auth_state: Dict[str, Any], name: str) -> str:
        for cookie in auth_state.get("cookies", []):
            if cookie.get("name") == name:
                return str(cookie.get("value", ""))
        return ""

    def create_cffi_session(self, auth_state: Dict[str, Any]) -> requests.Session:
        """
        Builds a curl_cffi session injected with the saved cookies and localStorage tokens.
        """
        session = requests.Session(impersonate="chrome120")
        
        if 'cookies' in auth_state:
            for c in auth_state['cookies']:
                session.cookies.set(c['name'], c['value'], domain=c['domain'], path=c['path'])

        session.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.fab.com",
            "Referer": "https://www.fab.com/",
            "X-Requested-With": "XMLHttpRequest",
        })
        csrf_token = self._cookie_header_value(auth_state, "fab_csrftoken")
        if csrf_token:
            session.headers["X-CSRFToken"] = csrf_token

        bearer_token = self._extract_access_token(auth_state)
        if bearer_token:
            session.headers['Authorization'] = f"Bearer {bearer_token}"

        return session

    def is_authenticated(self, session: requests.Session) -> bool:
        response = session.get("https://www.fab.com/i/users/me/wallet")
        return response.status_code == 200

    def ensure_listing_in_library(self, session: requests.Session, listing_id: str) -> None:
        listing_url = f"https://www.fab.com/listings/{listing_id}"
        ownership_url = f"https://www.fab.com/i/listings/{listing_id}/ownership"
        ownership = session.get(ownership_url, headers={"Referer": listing_url})
        if ownership.status_code == 401:
            raise RuntimeError("Saved Fab auth is missing an authenticated bearer token. Run `fab-auth` again.")
        offer_id = self.get_free_offer_id(session, listing_id)
        if ownership.status_code == 200 and not offer_id:
            return
        add_url = f"https://www.fab.com/i/listings/{listing_id}/add-to-library"
        added = session.post(
            add_url,
            headers={"Referer": listing_url},
            json={"offerId": offer_id} if offer_id else None,
        )
        if added.status_code == 400 and "offerId" in added.text and not offer_id:
            offer_id = self.get_free_offer_id(session, listing_id)
            if not offer_id:
                raise RuntimeError("Fab listing requires offerId to add to library, but no free offerId was found.")
            added = session.post(add_url, headers={"Referer": listing_url}, json={"offerId": offer_id})
        if added.status_code not in (200, 201, 204, 409):
            raise RuntimeError(f"Failed to add listing to library: HTTP {added.status_code}")

    def get_free_offer_id(self, session: requests.Session, listing_id: str) -> Optional[str]:
        payload = self.get_prices_info(session, listing_id)
        offers = payload.get("offers") or []
        for offer in offers:
            price = offer.get("price")
            discounted_price = offer.get("discountedPrice")
            if price == 0 or discounted_price == 0:
                offer_id = str(offer.get("offerId", "")).strip()
                if offer_id:
                    return offer_id
        return None

    def get_prices_info(self, session: requests.Session, listing_id: str) -> dict[str, Any]:
        listing_url = f"https://www.fab.com/listings/{listing_id}"
        response = session.get(
            f"https://www.fab.com/i/listings/{listing_id}/prices-infos",
            headers={"Referer": listing_url},
        )
        if response.status_code != 200:
            return {}
        payload = response.json()
        if not isinstance(payload, dict):
            return {}
        return payload

    def get_ownership_status(self, session: requests.Session, listing_id: str) -> dict[str, Any]:
        listing_url = f"https://www.fab.com/listings/{listing_id}"
        response = session.get(
            f"https://www.fab.com/i/listings/{listing_id}/ownership",
            headers={"Referer": listing_url},
        )
        if response.status_code == 401:
            raise RuntimeError("Saved Fab auth is missing an authenticated bearer token. Run `fab-auth` again.")
        owned = response.status_code == 200
        return {
            "owned": owned,
            "status_code": response.status_code,
        }

    def get_asset_formats(self, session: requests.Session, listing_id: str) -> list[dict[str, Any]]:
        listing_url = f"https://www.fab.com/listings/{listing_id}"
        response = session.get(
            f"https://www.fab.com/i/listings/{listing_id}/asset-formats",
            headers={"Referer": listing_url},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Failed to fetch asset formats: HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Fab asset-formats response had unexpected shape.")
        return payload

    def get_listing_details(self, session: requests.Session, listing_id: str) -> dict[str, Any]:
        listing_url = f"https://www.fab.com/listings/{listing_id}"
        response = session.get(
            f"https://www.fab.com/i/listings/{listing_id}",
            headers={"Referer": listing_url},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Failed to fetch listing details: HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Fab listing details response had unexpected shape.")
        return payload

    def inspect_listing(self, listing_id: str) -> dict[str, Any]:
        auth_state = self.load_auth_state()
        if not auth_state:
            raise RuntimeError("No Fab auth state found. Run `fab-auth` first.")

        session = self.create_cffi_session(auth_state)
        if not self.is_authenticated(session):
            raise RuntimeError("Saved Fab auth is not authenticated. Run `fab-auth` again and sign in in that window.")

        normalized_listing_id = self._normalize_listing_id(listing_id)
        listing_details = self.get_listing_details(session, normalized_listing_id)
        asset_formats = self.get_asset_formats(session, normalized_listing_id)
        prices_info = self.get_prices_info(session, normalized_listing_id)
        free_offer_id = self.get_free_offer_id(session, normalized_listing_id)
        ownership = self.get_ownership_status(session, normalized_listing_id)
        route = self._classify_asset_formats(asset_formats)
        if route == "direct":
            download_access = "batch-direct" if ownership["owned"] or free_offer_id else "library-or-purchase-required"
        elif route == "unreal-engine-only":
            download_access = "unreal-engine-only"
        else:
            download_access = "unknown"
        return {
            "listing_id": normalized_listing_id,
            "route": route,
            "download_access": download_access,
            "format_codes": self._format_codes(asset_formats),
            "title": str(listing_details.get("title", "")).strip(),
            "catalog_item_id": str(listing_details.get("catalogItemId", "")).strip(),
            "seller_name": str((listing_details.get("seller") or {}).get("displayName", "")).strip(),
            "owned": bool(ownership["owned"]),
            "free_offer_id": free_offer_id or "",
            "is_free": bool(free_offer_id),
            "price_tier_count": len(prices_info.get("offers") or []),
            "asset_formats": asset_formats,
        }

    def get_signed_download_url(
        self,
        session: requests.Session,
        listing_id: str,
        format_code: str,
        file_uid: str,
    ) -> str:
        listing_url = f"https://www.fab.com/listings/{listing_id}"
        url = (
            f"https://www.fab.com/i/listings/{listing_id}/asset-formats/"
            f"{format_code}/files/{file_uid}/download-info?"
        )
        response = session.get(url, headers={"Referer": listing_url})
        if response.status_code != 200:
            raise RuntimeError(f"Failed to fetch download info: HTTP {response.status_code}")
        try:
            payload = response.json()
        except Exception as e:
            raise RuntimeError(f"Fab download-info response was not JSON: {e}") from e
        download_url = self._extract_first_url(payload)
        if not download_url:
            raise RuntimeError("Fab download-info response did not include a signed download URL.")
        return download_url

    def download_ziplink_with_cffi(
        self,
        url: str,
        output_path: str,
        session: Optional[requests.Session] = None,
    ):
        self.logger.info(f"Downloading payload to {output_path} via curl_cffi...")
        active_session = session
        if active_session is None:
            auth_state = self.load_auth_state()
            if not auth_state:
                raise RuntimeError("No auth state found. Please run acquire_session_interactive() first.")
            active_session = self.create_cffi_session(auth_state)

        response = active_session.get(url, stream=True)
        if response.status_code != 200:
            raise RuntimeError(f"Download failed with status code {response.status_code}")
            
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                
        self.logger.info(f"Successfully downloaded {os.path.getsize(output_path)} bytes.")

    def download_listing_asset(self, listing_id: str, output_path: str) -> dict[str, Any]:
        auth_state = self.load_auth_state()
        if not auth_state:
            raise RuntimeError("No Fab auth state found. Run `fab-auth` first.")

        session = self.create_cffi_session(auth_state)
        if not self.is_authenticated(session):
            raise RuntimeError("Saved Fab auth is not authenticated. Run `fab-auth` again and sign in in that window.")

        normalized_listing_id = self._normalize_listing_id(listing_id)
        self.ensure_listing_in_library(session, normalized_listing_id)
        asset_formats = self.get_asset_formats(session, normalized_listing_id)
        route = self._classify_asset_formats(asset_formats)
        if route != "direct":
            raise RuntimeError(f"Listing route is `{route}` and cannot be downloaded as a direct Fab file.")
        format_code, file_entry = self._pick_download_file(asset_formats)
        file_uid = str(file_entry.get("uid", "")).strip()
        if not file_uid:
            raise RuntimeError("Chosen Fab asset file did not expose a uid.")
        signed_url = self.get_signed_download_url(session, normalized_listing_id, format_code, file_uid)
        self.download_ziplink_with_cffi(signed_url, output_path, session=session)
        return {
            "listing_id": normalized_listing_id,
            "format_code": format_code,
            "file_name": file_entry.get("name", ""),
            "file_uid": file_uid,
            "output_path": output_path,
        }

    @staticmethod
    def _normalize_listing_id(listing_ref: str) -> str:
        text = str(listing_ref or "").strip()
        marker = "/listings/"
        if marker in text:
            text = text.split(marker, 1)[1]
        return text.split("?", 1)[0].split("#", 1)[0].strip("/")

    async def get_download_url(self, listing_id: str) -> str:
        """
        Uses nodriver (in visible mode to bypass headless pipe bugs) along with the saved nodriver 
        auth state to navigate to the Fab listing page, click the download button, 
        and intercept the S3/CDN direct download URL.
        """
        normalized_listing_id = self._normalize_listing_id(listing_id)
        if not normalized_listing_id:
            raise RuntimeError("Invalid listing id. Pass a Fab listing id or URL containing /listings/<id>.")

        self.logger.info(f"Intercepting S3 download URL for listing {normalized_listing_id} using nodriver...")
        
        loop = asyncio.get_running_loop()
        download_url_future = loop.create_future()

        auth_state = self.load_auth_state()
        browser = await self._start_browser()
        page = None
        try:
            if auth_state:
                for c in auth_state.get('cookies', []):
                    try:
                        await browser.cookies.set(
                            name=c['name'],
                            value=c['value'],
                            domain=c['domain'],
                            path=c.get('path', '/')
                        )
                    except Exception:
                        pass

            async def fetch_paused(event: fetch.RequestPaused):
                try:
                    url = event.request.url or ""
                    url_lc = url.lower()
                    has_download_shape = (
                        "amazonaws.com" in url_lc
                        or "cloudfront.net" in url_lc
                        or "download" in url_lc
                        or "epicgames.com" in url_lc
                        or "epicgamescdn.com" in url_lc
                    )
                    has_signed_marker = (
                        "?x-amz-algorithm" in url_lc
                        or "&x-amz-signature=" in url_lc
                        or "policy=" in url_lc
                        or "f_token=" in url_lc
                    )
                    if has_download_shape and event.request.method == "GET" and (has_signed_marker or "download" in url_lc):
                        if not download_url_future.done():
                            download_url_future.set_result(url)
                        try:
                            await browser.connection.send(fetch.fail_request(
                                request_id=event.request_id,
                                error_reason=network.ErrorReason.ABORTED
                            ))
                        except Exception:
                            pass
                        return
                    await browser.connection.send(fetch.continue_request(request_id=event.request_id))
                except Exception:
                    try:
                        await browser.connection.send(fetch.continue_request(request_id=event.request_id))
                    except Exception:
                        pass

            browser.connection.add_handler(fetch.RequestPaused, fetch_paused)
            await browser.connection.send(fetch.enable(patterns=[
                fetch.RequestPattern(url_pattern="*amazonaws.com*"),
                fetch.RequestPattern(url_pattern="*cloudfront.net*"),
                fetch.RequestPattern(url_pattern="*epicgames.com*"),
                fetch.RequestPattern(url_pattern="*epicgamescdn.com*"),
                fetch.RequestPattern(url_pattern="*download*"),
            ]))

            try:
                task = asyncio.create_task(browser.get(f"https://www.fab.com/listings/{normalized_listing_id}"))
                page = await asyncio.wait_for(task, timeout=10)
            except asyncio.TimeoutError:
                self.logger.warning("SPA load timeout hit. Continuing.")
                if browser.tabs:
                    page = browser.tabs[0]

            if not page:
                raise RuntimeError("No active tab found.")

            self.logger.info("Clicking download...")
            try:
                btn = await page.find("Download", timeout=15)
                await btn.click()
                self.logger.info("Clicked first Download button.")
                
                # Wait for modal
                await asyncio.sleep(2)
                
                # Use JS to click the modal button as a fallback since select_all can be tricky
                await page.evaluate('''() => {
                    let btns = Array.from(document.querySelectorAll('button, a, div[role="button"]'));
                    let assetDownloadBtns = btns.filter(b => b.innerText && b.innerText.includes('Download') && b.innerText.includes('asset'));
                    if (assetDownloadBtns.length > 0) {
                        assetDownloadBtns[assetDownloadBtns.length - 1].click();
                        return;
                    }
                    let downloadBtns = btns.filter(b => b.innerText && b.innerText.includes('Download'));
                    if (downloadBtns.length > 0) {
                        downloadBtns[downloadBtns.length - 1].click();
                    }
                }''')
            except Exception as e:
                self.logger.warning(f"Failed to click download: {e}")

            try:
                s3_url = await asyncio.wait_for(download_url_future, timeout=25.0)
                self.logger.info("Intercepted S3 download URL successfully!")
                await self._save_browser_state(browser, page)
                return str(s3_url)
            except asyncio.TimeoutError:
                raise RuntimeError("Timed out waiting to intercept the download URL.")
        finally:
            try:
                if page is not None:
                    await self._save_browser_state(browser, page)
                browser.stop()
            except Exception:
                pass
