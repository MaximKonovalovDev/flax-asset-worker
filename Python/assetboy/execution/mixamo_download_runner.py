"""
mixamo_download_runner.py — Mixamo animation downloader using saved auth state.

Two modes:
  1. Browser-automation mode (default): uses nodriver with saved browser
     profile to navigate mixamo.com, search clips, click Download, and
     capture the response via CDP network interception.
  2. Direct-API fallback: uses requests with cookies extracted from the
     saved auth state (works when Mixamo's API accepts cookie auth).

The browser-automation mode is preferred because it survives Mixamo UI
changes and works with any saved Adobe session.

Usage:
    python -m assetboy.execution.mixamo_download_runner single ^
        --clip "Sword And Shield Slash" --output-dir <dir>

    python -m assetboy.execution.mixamo_download_runner batch ^
        --list <download-list.json> --output-dir <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="[mixamo] %(levelname)-5s %(message)s",
)
logger = logging.getLogger("mixamo_dl")


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "AGENTS.md").exists() or (parent / ".git").exists():
            return parent
    return here.parents[3]  # fallback: up from assetboy/execution/


REPO_ROOT = _find_repo_root()
DEFAULT_AUTH_STATE_PATH = REPO_ROOT / ".private" / "mixamo_auth_state.json"
DEFAULT_BROWSER_PROFILE = REPO_ROOT / ".private" / "fab_browser_profile"

MIXAMO_BASE = "https://www.mixamo.com"

# How long to wait for a page element before failing.
_TIMEOUT_S = 20.0
# How long to wait for a download to complete.
_DOWNLOAD_TIMEOUT_S = 60.0
# Poll interval during download wait.
_POLL_S = 0.5


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class DownloadResult:
    clip_name: str
    filename: str
    output_path: Path
    size_bytes: int
    ok: bool
    error: str = ""


# ---------------------------------------------------------------------------
# Auth loading
# ---------------------------------------------------------------------------

def _load_auth_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        logger.error("Auth state not found at %s", path)
        logger.error("Run scripts/mixamo-setup-auth.ps1 first.")
        sys.exit(1)
    state = json.loads(path.read_text(encoding="utf-8"))
    if not state.get("authenticated"):
        logger.error("Auth state exists but is NOT authenticated.")
        logger.error("Run scripts/mixamo-setup-auth.ps1 again.")
        sys.exit(1)
    return state


# ---------------------------------------------------------------------------
# Browser-automation mode
# ---------------------------------------------------------------------------

class MixamoBrowserDownloader:
    """Download Mixamo clips via nodriver browser automation.

    Opens the saved browser profile (same one used during auth setup)
    which already has valid Adobe/Mixamo session cookies.  Navigates to
    mixamo.com, searches for each clip, clicks Download, and captures
    the FBX via CDP network-response interception.
    """

    def __init__(self, *, auth_state_path: Path, output_dir: Path, browser_profile_dir: Optional[Path] = None):
        self.auth_state_path = auth_state_path
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir = (browser_profile_dir or DEFAULT_BROWSER_PROFILE).resolve()
        self._pending_downloads: Dict[str, asyncio.Future] = {}
        self._browser = None
        self._page = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def download_clip(
        self,
        clip_name: str,
        *,
        character: str = "X Bot",
    ) -> DownloadResult:
        """Download one Mixamo clip.  Starts browser if not already running."""
        if self._browser is None:
            await self._start_browser()

        filename = self._sanitize(clip_name)
        out_path = self.output_dir / filename
        logger.info("Downloading %s -> %s", clip_name, out_path.name)

        try:
            # Build the Mixamo search URL with hash-router query parameter.
            search_url = f"{MIXAMO_BASE}/#/?query={clip_name.replace(' ', '%20')}"
            logger.debug("Navigating to %s", search_url)
            await self._page.get(search_url)
            await asyncio.sleep(4)

            # Set up download future before clicking.
            dl_future: asyncio.Future[bytes] = asyncio.Future()
            self._pending_downloads[out_path.name] = dl_future

            # Try to click the download button.
            clicked = await self._click_download_button()
            if not clicked:
                logger.warning("Could not find download button for %s", clip_name)
                # Fallback: inject JS to trigger download via Mixamo API.
                await self._fallback_download(clip_name, character, out_path, dl_future)

            # Wait for the download response.
            try:
                data = await asyncio.wait_for(dl_future, timeout=_DOWNLOAD_TIMEOUT_S)
            except asyncio.TimeoutError:
                logger.warning("Download timed out for %s; trying fallback", clip_name)
                await self._fallback_download(clip_name, character, out_path, None)
                if not out_path.exists():
                    return DownloadResult(
                        clip_name=clip_name, filename=filename,
                        output_path=out_path, size_bytes=0, ok=False,
                        error="download_timeout_and_fallback_failed",
                    )
                data = out_path.read_bytes()

            out_path.write_bytes(data)
            size = out_path.stat().st_size
            logger.info("  Downloaded %s (%d bytes)", out_path.name, size)
            return DownloadResult(
                clip_name=clip_name, filename=filename,
                output_path=out_path, size_bytes=size, ok=True,
            )

        except Exception as exc:
            logger.error("  Failed %s: %s", clip_name, exc)
            return DownloadResult(
                clip_name=clip_name, filename=filename,
                output_path=out_path, size_bytes=0, ok=False,
                error=str(exc),
            )
        finally:
            self._pending_downloads.pop(out_path.name, None)

    async def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.stop()
            except Exception:
                pass
            self._browser = None
            self._page = None

    # ------------------------------------------------------------------ #
    # Browser setup
    # ------------------------------------------------------------------ #

    async def _start_browser(self) -> None:
        import nodriver as uc

        profile_dir = self.browser_profile_dir
        profile_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Starting browser with profile %s", profile_dir)

        self._browser = await uc.start(
            headless=False,
            user_data_dir=str(profile_dir),
        )

        # Intercept network responses to capture downloads.
        import nodriver.cdp.network as cdp_network
        import base64

        async def _on_response(event: cdp_network.ResponseReceived) -> None:
            url = event.response.url.lower()
            # Mixamo FBX download responses contain "download" and end with
            # .fbx or have content-type application/octet-stream.
            if "mixamo.com" in url and event.response.status == 200:
                if (
                    ".fbx" in url
                    or "download" in url
                    or "application/octet-stream" in str(event.response.headers)
                ):
                    try:
                        raw = await self._page.send(
                            cdp_network.get_response_body(event.request_id)
                        )
                        if not raw:
                            return
                        body_str, base64_encoded = raw
                        data = (
                            base64.b64decode(body_str)
                            if base64_encoded
                            else body_str.encode("utf-8")
                        )
                        if data and len(data) > 100:
                            await self._on_download_data(data, url)
                    except Exception:
                        pass

        self._browser.on(cdp_network.ResponseReceived, _on_response)

        # Navigate to Mixamo to establish session.
        self._page = await self._browser.get(MIXAMO_BASE)
        await asyncio.sleep(3)

        # Verify we're on Mixamo (not a login redirect).
        page_url = (await self._page.evaluate("window.location.href", return_by_value=True)) or ""
        if "login" in page_url.lower() or "adobe" in page_url.lower():
            logger.warning(
                "Browser shows login page instead of Mixamo. "
                "The saved session may be expired. "
                "Run scripts/mixamo-setup-auth.ps1 to refresh auth."
            )

    async def _on_download_data(self, data: bytes, url: str) -> None:
        """Route captured download bytes to the pending future for the clip."""
        if not self._pending_downloads:
            return
        # Give to the most recently added future (likely the current clip).
        name = list(self._pending_downloads.keys())[-1]
        future = self._pending_downloads[name]
        if not future.done():
            future.set_result(data)

    # ------------------------------------------------------------------ #
    # UI interaction
    # ------------------------------------------------------------------ #

    async def _click_download_button(self) -> bool:
        """Try to find and click the Mixamo Download button.

        Mixamo's UI is a React SPA.  The download button is typically:
          button[class*="download"], a[class*="download"], or the last
          button in the animation-detail toolbar.
        """
        js_click = """
        (() => {
            // Strategy 1: button with "Download" text
            const buttons = Array.from(document.querySelectorAll('button'));
            const dlBtn = buttons.find(b =>
                b.innerText.toLowerCase().includes('download')
            );
            if (dlBtn) { dlBtn.click(); return true; }

            // Strategy 2: anchor with download attributes or text
            const anchors = Array.from(document.querySelectorAll('a'));
            const dlA = anchors.find(a =>
                a.innerText.toLowerCase().includes('download')
                || a.getAttribute('download') !== null
                || a.href?.toLowerCase().includes('download')
            );
            if (dlA) { dlA.click(); return true; }

            // Strategy 3: any element with data-testid or aria-label "download"
            const byAttr = document.querySelector(
                '[data-testid*="download"], [aria-label*="download"], '
                + '[class*="Download"], [class*="download"]'
            );
            if (byAttr) { byAttr.click(); return true; }

            return false;
        })()
        """
        try:
            result = await self._page.evaluate(js_click, return_by_value=True)
            return bool(result)
        except Exception:
            return False

    async def _fallback_download(
        self,
        clip_name: str,
        character: str,
        out_path: Path,
        future: Optional[asyncio.Future],
    ) -> None:
        """Fallback: use Python requests with cookies from auth state."""
        logger.info("  Using request-based fallback for %s", clip_name)
        import requests as req

        state = _load_auth_state(self.auth_state_path)
        cookies = {
            c["name"]: c["value"]
            for c in state.get("cookies", [])
            if c.get("name")
        }
        session = req.Session()
        for k, v in cookies.items():
            session.cookies.set(k, v, domain=".mixamo.com")

        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Origin": MIXAMO_BASE,
            "Referer": f"{MIXAMO_BASE}/",
        })

        # Step 1: search for the animation.
        search_resp = session.get(
            f"{MIXAMO_BASE}/api/v1/animation/search",
            params={"query": clip_name},
            timeout=15,
        )
        if search_resp.status_code != 200:
            logger.warning("  Search API returned %d", search_resp.status_code)
            # Try to construct a download URL via the Adobe/Mixamo download
            # gateway.  This is a best-effort — the URL structure may change.
            logger.warning("  Search failed; cannot download %s via fallback", clip_name)
            return

        try:
            search_data = search_resp.json()
        except json.JSONDecodeError:
            logger.warning("  Search response not JSON")
            search_data = {}

        animations = (
            search_data.get("results")
            or search_data.get("animations")
            or search_data.get("data")
            or []
        )
        if not animations:
            logger.warning("  No animations found for %s", clip_name)
            return

        anim = animations[0]
        anim_id = anim.get("id") or anim.get("animationId") or ""
        if not anim_id:
            logger.warning("  No animation ID in search result for %s", clip_name)
            return

        char_id = character.replace(" ", "_").lower()  # best guess

        # Step 2: request download.
        dl_resp = session.get(
            f"{MIXAMO_BASE}/api/v1/animation/download",
            params={
                "animation_id": anim_id,
                "character_id": char_id,
                "format": "fbx",
                "skin": "true",
            },
            stream=True,
            timeout=120,
        )
        if dl_resp.status_code != 200:
            logger.warning("  Download API returned %d for %s", dl_resp.status_code, clip_name)
            return

        out_path.write_bytes(dl_resp.content)
        if future and not future.done():
            future.set_result(dl_resp.content)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _sanitize(clip_name: str) -> str:
        """Match MixamoCache.ClipNameToFilename in C#."""
        s = clip_name.strip().replace(" ", "_")
        s = re.sub(r"[^a-zA-Z0-9_.]", "", s)
        return s + ".fbx"


# ---------------------------------------------------------------------------
# Direct-API fallback mode (no browser)
# ---------------------------------------------------------------------------

def _download_clip_direct(
    clip_name: str,
    character: str,
    output_dir: Path,
    auth_state_path: Path,
) -> DownloadResult:
    """Download a single clip using Python requests + saved cookies.

    This is the no-browser mode, suitable for CI/headless use after auth
    state is fresh.
    """
    import requests as req

    filename = MixamoBrowserDownloader._sanitize(clip_name)
    out_path = Path(output_dir).resolve() / filename
    logger.info("Direct-download %s -> %s", clip_name, out_path.name)

    try:
        state = _load_auth_state(auth_state_path)
        cookies = {
            c["name"]: c["value"]
            for c in state.get("cookies", [])
            if c.get("name")
        }
        session = req.Session()
        for k, v in cookies.items():
            session.cookies.set(k, v, domain=".mixamo.com")

        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Origin": MIXAMO_BASE,
            "Referer": f"{MIXAMO_BASE}/",
        })

        # Search for animation.
        logger.debug("  Searching Mixamo API: %s", clip_name)
        search_resp = session.get(
            f"{MIXAMO_BASE}/api/v1/animation/search",
            params={"query": clip_name},
            timeout=20,
        )
        if search_resp.status_code != 200:
            return DownloadResult(
                clip_name=clip_name, filename=filename,
                output_path=out_path, size_bytes=0, ok=False,
                error=f"search_api_{search_resp.status_code}",
            )

        search_data = search_resp.json()
        animations = (
            search_data.get("results")
            or search_data.get("animations")
            or search_data.get("data")
            or []
        )
        if not animations:
            return DownloadResult(
                clip_name=clip_name, filename=filename,
                output_path=out_path, size_bytes=0, ok=False,
                error="no_animations_found",
            )

        anim = animations[0]
        anim_id = anim.get("id") or anim.get("animationId") or ""
        if not anim_id:
            return DownloadResult(
                clip_name=clip_name, filename=filename,
                output_path=out_path, size_bytes=0, ok=False,
                error="no_animation_id",
            )

        char_id = character.replace(" ", "_").lower()

        # Download.
        logger.debug("  Downloading animation %s from character %s", anim_id, char_id)
        dl_resp = session.get(
            f"{MIXAMO_BASE}/api/v1/animation/download",
            params={
                "animation_id": anim_id,
                "character_id": char_id,
                "format": "fbx",
                "skin": "true",
            },
            stream=True,
            timeout=300,
        )
        if dl_resp.status_code != 200:
            return DownloadResult(
                clip_name=clip_name, filename=filename,
                output_path=out_path, size_bytes=0, ok=False,
                error=f"download_api_{dl_resp.status_code}",
            )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(dl_resp.content)
        size = out_path.stat().st_size
        logger.info("  Downloaded %s (%d bytes)", out_path.name, size)
        return DownloadResult(
            clip_name=clip_name, filename=filename,
            output_path=out_path, size_bytes=size, ok=True,
        )

    except Exception as exc:
        logger.error("  Direct download failed: %s", exc)
        return DownloadResult(
            clip_name=clip_name, filename=filename,
            output_path=out_path, size_bytes=0, ok=False,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Download Mixamo animations using saved auth state.",
    )
    p.add_argument(
        "--auth", default=str(DEFAULT_AUTH_STATE_PATH),
        help="Path to mixamo_auth_state.json (default: repo-root/.private/)",
    )
    p.add_argument(
        "--mode", choices=["browser", "direct"], default="direct",
        help=(
            "'browser'=nodriver with saved profile (visible); "
            "'direct'=requests with cookies from auth state (default,"
            " headless)"
        ),
    )
    p.add_argument(
        "--character", default="X Bot",
        help="Mixamo character name for animation preview (default: X Bot)",
    )
    p.add_argument(
        "--browser-profile-dir", default=str(DEFAULT_BROWSER_PROFILE),
        help="Path to browser profile directory (default: repo-root/.private/fab_browser_profile)",
    )

    sub = p.add_subparsers(dest="command", required=True)

    # Single download
    dl = sub.add_parser("single", help="Download one clip")
    dl.add_argument("--clip", required=True, help="Mixamo clip name")
    dl.add_argument("--output-dir", required=True, help="Output directory")

    # Batch download from JSON list
    batch = sub.add_parser("batch", help="Download from JSON download-list")
    batch.add_argument(
        "--list", required=True,
        help="Path to download-list.json (list of clip names)",
    )
    batch.add_argument("--output-dir", required=True, help="Output directory")

    # Search only
    s = sub.add_parser("search", help="Search Mixamo for a clip")
    s.add_argument("--query", required=True, help="Search query")

    return p


def _main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    auth_path = Path(args.auth)
    output_dir = Path(args.output_dir) if hasattr(args, "output_dir") else None
    character = args.character

    if args.command == "search":
        # Quick search via API to verify auth works.
        state = _load_auth_state(auth_path)
        import requests as req
        cookies = {c["name"]: c["value"] for c in state.get("cookies", []) if c.get("name")}
        session = req.Session()
        for k, v in cookies.items():
            session.cookies.set(k, v, domain=".mixamo.com")
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Origin": MIXAMO_BASE,
            "Referer": f"{MIXAMO_BASE}/",
        })
        resp = session.get(
            f"{MIXAMO_BASE}/api/v1/animation/search",
            params={"query": args.query},
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results") or data.get("animations") or data.get("data") or []
            print(f"Search results for '{args.query}': {len(results)} found")
            for r in results[:10]:
                name = r.get("name") or r.get("displayName") or r.get("id", "?")
                print(f"  - {name}")
        else:
            print(f"Search API returned HTTP {resp.status_code}")
            print("Auth may be expired. Run scripts/mixamo-setup-auth.ps1")
        return

    # Single or batch download
    clips: List[Dict[str, str]] = []

    if args.command == "single":
        clips = [{"clip": args.clip, "character": character}]
    elif args.command == "batch":
        list_path = Path(getattr(args, "list", ""))
        if not list_path.exists():
            print(f"ERROR: download-list not found: {list_path}")
            sys.exit(1)
        raw = json.loads(list_path.read_text(encoding="utf-8"))
        # Support both array-of-strings and array-of-objects.
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str):
                    clips.append({"clip": item, "character": character})
                elif isinstance(item, dict):
                    clips.append({
                        "clip": item.get("clip") or item.get("name") or "",
                        "character": item.get("character") or character,
                    })
        elif isinstance(raw, dict):
            for item in raw.get("clips", []):
                if isinstance(item, str):
                    clips.append({"clip": item, "character": character})
                elif isinstance(item, dict):
                    clips.append({
                        "clip": item.get("clip") or item.get("name") or "",
                        "character": item.get("character") or character,
                    })

    if not clips:
        print("ERROR: No clips to download.")
        sys.exit(1)

    results: List[DownloadResult] = []
    out_dir = output_dir or Path()

    if args.mode == "browser":
        async def _run_browser():
            dl = MixamoBrowserDownloader(
                auth_state_path=auth_path,
                output_dir=out_dir,
                browser_profile_dir=Path(args.browser_profile_dir),
            )
            for entry in clips:
                result = await dl.download_clip(
                    entry["clip"],
                    character=entry["character"],
                )
                results.append(result)
            await dl.close()

        asyncio.run(_run_browser())
    else:
        for entry in clips:
            result = _download_clip_direct(
                entry["clip"],
                entry["character"],
                out_dir,
                auth_path,
            )
            results.append(result)

    # Summary
    ok_count = sum(1 for r in results if r.ok)
    fail_count = sum(1 for r in results if not r.ok)
    total_bytes = sum(r.size_bytes for r in results if r.ok)

    print()
    print("=" * 60)
    print(f"Mixamo download complete: {ok_count} OK, {fail_count} failed")
    print(f"Total bytes: {total_bytes:,}")
    print(f"Output: {out_dir}")
    for r in results:
        status = "OK" if r.ok else "FAIL"
        print(f"  [{status}] {r.clip_name} -> {r.filename} ({r.size_bytes} bytes)"
              + (f"  error={r.error}" if not r.ok else ""))
    print("=" * 60)

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    _main()
