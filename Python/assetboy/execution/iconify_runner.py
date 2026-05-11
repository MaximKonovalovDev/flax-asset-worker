"""iconify_runner.py — Batch-fetch open-licensed icons from Iconify.

Iconify (iconify.design) is a unified icon API aggregating 150+ open-source
icon sets (Material, Tabler, Lucide, Phosphor, Game-Icons, etc.). Most are
MIT, Apache-2.0, SIL OFL 1.1, or CC0. No API key, no auth required.

API endpoints (api.iconify.design):
    GET /search?query=<term>&limit=<n>
        -> {icons: ["prefix:name", ...], total: <n>, collections: {...}}
    GET /<prefix>/<name>.svg?width=<px>&color=<hex>
        -> SVG bytes
    GET /collections
        -> {<prefix>: {name, license: {title, spdx, url}, ...}}

CLI driver: `assetboy gen iconify fetch --query "sword" --count 20`

Use cases in FAW:
  - UI iconography for game HUDs (action icons, inventory icons).
  - Vector mood boards for ComfyUI ControlNet (canny edges).
  - Reference glyph libraries for stylized typography.

License gate: Iconify aggregates open-source sets. We accept these SPDX:
    MIT, Apache-2.0, ISC, CC0-1.0, CC-BY-4.0, CC-BY-SA-4.0, SIL OFL-1.1,
    GPL-2.0, GPL-3.0, LGPL-2.1, MPL-2.0
Some sets are commercial/restricted; we record the license per icon and
skip ones flagged 'proprietary' or unknown.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from assetboy.execution.comfyui_runner import manual_drop_dir

ICONIFY_API = "https://api.iconify.design"
USER_AGENT = "flax-asset-worker/1.10 (open-icon collector; +https://github.com/flax-game-studio)"

# SPDX identifiers we accept. Substring match (case-insensitive) on
# collection metadata's license.spdx field.
_ACCEPTED_LICENSE_SPDX = {
    "mit", "apache-2.0", "isc", "bsd-2-clause", "bsd-3-clause",
    "cc0-1.0", "cc-by-4.0", "cc-by-sa-4.0", "ofl-1.1",
    "gpl-2.0", "gpl-3.0", "lgpl-2.1", "mpl-2.0",
    "unlicense",
}


@dataclass
class IconifyResult:
    """Outcome of one batch query."""

    pack_id: str
    query: str
    output_dir: Path
    icons_matched: int = 0
    icons_accepted_license: int = 0
    icons_downloaded: int = 0
    icons_skipped_restricted: int = 0
    icons_failed: int = 0
    downloaded_paths: list[Path] = field(default_factory=list)
    manifest_path: Path | None = None
    dry_run: bool = False
    ok: bool = True
    error: str | None = None


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def _get_json(url: str, *, timeout: float = 15.0) -> dict:
    """v1.12.s69: retries HTTP 429/503/502/504 via with_429_retry."""
    from assetboy.execution._http_retry import with_429_retry

    def _do_call() -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    return with_429_retry(_do_call, max_retries=3, base_delay_s=1.0, cap_delay_s=30.0)


def _get_text(url: str, *, timeout: float = 15.0) -> str:
    """v1.12.s69: retries HTTP 429/503/502/504 (SVG fetch endpoint)."""
    from assetboy.execution._http_retry import with_429_retry

    def _do_call() -> str:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")

    return with_429_retry(_do_call, max_retries=3, base_delay_s=1.0, cap_delay_s=30.0)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def is_license_accepted(spdx: str) -> bool:
    """True if SPDX identifier is in our open-license allowlist."""
    if not spdx:
        return False
    norm = spdx.strip().lower()
    return norm in _ACCEPTED_LICENSE_SPDX


def search_iconify_icons(
    query: str,
    *,
    limit: int = 32,
    timeout: float = 15.0,
) -> list[str]:
    """Run /search; return list of icon identifiers like 'mdi:sword'."""
    params = {"query": query, "limit": str(min(max(limit, 1), 64))}
    url = f"{ICONIFY_API}/search?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    return list(payload.get("icons", []))


def fetch_iconify_collections(*, timeout: float = 15.0) -> dict:
    """Fetch /collections; returns {<prefix>: {name, license: {...}, ...}}."""
    return _get_json(f"{ICONIFY_API}/collections", timeout=timeout)


def fetch_icon_svg(
    icon_id: str,
    *,
    width: int = 64,
    color: str | None = None,
    timeout: float = 15.0,
) -> str:
    """Fetch a single icon's SVG markup.

    Args:
        icon_id: 'prefix:name' (e.g. 'mdi:sword', 'game-icons:dragon').
        width: render width in pixels (height auto-scales).
        color: optional hex color override (e.g. '#FF6600'); None = original.
    """
    if ":" not in icon_id:
        raise ValueError(f"icon_id must be 'prefix:name' (got {icon_id!r})")
    prefix, name = icon_id.split(":", 1)
    params: dict[str, str] = {"width": str(width)}
    if color:
        params["color"] = color
    url = f"{ICONIFY_API}/{urllib.parse.quote(prefix)}/{urllib.parse.quote(name)}.svg"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return _get_text(url, timeout=timeout)


def run_iconify_batch(
    *,
    query: str,
    pack_id: str | None = None,
    count: int = 16,
    width: int = 64,
    color: str | None = None,
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.05,
    skip_collections_check: bool = False,
    dry_run: bool = False,
) -> IconifyResult:
    """Search Iconify and download open-licensed icons as SVG.

    Args:
        query: free-text search.
        pack_id: pack id for output dir.
        count: max icons to download.
        width: render width in px.
        color: optional hex color override (e.g. '#FFAA00').
        output_dir: override.
        polite_sleep_s: delay between icon fetches (default 50ms; SVGs are tiny).
        skip_collections_check: when True, skip the /collections call and download
                                ALL search hits regardless of license metadata.
                                Use with caution (testing only).
        dry_run: when True, hit search (and collections) but skip SVG fetches.
    """
    resolved_pack_id = pack_id or f"ICONIFY_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "iconify" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = IconifyResult(
        pack_id=resolved_pack_id,
        query=query,
        output_dir=out_dir,
        dry_run=dry_run,
    )

    # Step 1: search (oversample to absorb license filter losses).
    try:
        icons = search_iconify_icons(query, limit=min(count * 2, 64))
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.icons_matched = len(icons)
    if not icons:
        result.error = "no_matches"
        return result

    # Step 2: fetch collections metadata for license lookup.
    collections: dict[str, dict] = {}
    if not skip_collections_check:
        try:
            collections = fetch_iconify_collections()
        except (urllib.error.URLError, ValueError, TimeoutError):
            # Soft failure: we'll just accept all icons without license check
            # but record the warning.
            collections = {}
            result.error = "collections_fetch_failed_proceeding_without_license_filter"

    manifest_entries: list[dict] = []
    for icon_id in icons:
        if result.icons_downloaded >= count:
            break
        if ":" not in icon_id:
            result.icons_failed += 1
            continue
        prefix = icon_id.split(":", 1)[0]
        coll = collections.get(prefix, {}) if collections else {}
        coll_license = coll.get("license", {}) or {}
        spdx = str(coll_license.get("spdx", "")).strip()
        license_title = str(coll_license.get("title", "")).strip()
        license_url = str(coll_license.get("url", "")).strip()
        collection_name = str(coll.get("name", "")).strip() or prefix

        # Apply license filter (only if collections metadata loaded).
        if collections and spdx and not is_license_accepted(spdx):
            result.icons_skipped_restricted += 1
            continue
        if collections and not spdx and not skip_collections_check:
            # No SPDX info and we're enforcing — skip to be safe.
            result.icons_skipped_restricted += 1
            continue
        result.icons_accepted_license += 1

        safe_id = icon_id.replace(":", "__").replace("/", "_")
        dest = out_dir / f"{safe_id}.svg"

        entry = {
            "icon_id": icon_id,
            "prefix": prefix,
            "collection": collection_name,
            "license_spdx": spdx,
            "license_title": license_title,
            "license_url": license_url,
            "width": width,
            "color": color,
            "source_url": f"{ICONIFY_API}/{prefix}/{icon_id.split(':', 1)[1]}.svg",
            "local_path": str(dest),
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.icons_downloaded += 1
            result.downloaded_paths.append(dest)
            continue

        try:
            svg = fetch_icon_svg(icon_id, width=width, color=color)
            dest.write_text(svg, encoding="utf-8")
            entry["downloaded"] = True
            entry["bytes"] = len(svg.encode("utf-8"))
            result.icons_downloaded += 1
            result.downloaded_paths.append(dest)
            manifest_entries.append(entry)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            entry["downloaded"] = False
            entry["error"] = str(exc)
            manifest_entries.append(entry)
            result.icons_failed += 1

        if polite_sleep_s > 0:
            time.sleep(polite_sleep_s)

    manifest = {
        "source": "iconify",
        "pack_id": resolved_pack_id,
        "query": query,
        "width_px": width,
        "color_override": color,
        "icons_matched": result.icons_matched,
        "icons_accepted_license": result.icons_accepted_license,
        "icons_downloaded": result.icons_downloaded,
        "icons_skipped_restricted": result.icons_skipped_restricted,
        "icons_failed": result.icons_failed,
        "license_policy": (
            "Open-source SPDX only: MIT/Apache-2.0/ISC/BSD/CC0/CC-BY/CC-BY-SA/"
            "OFL/GPL/LGPL/MPL/Unlicense"
        ),
        "license_policy_url": "https://iconify.design/docs/licenses/",
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "iconify_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    return result


__all__ = [
    "ICONIFY_API",
    "IconifyResult",
    "is_license_accepted",
    "search_iconify_icons",
    "fetch_iconify_collections",
    "fetch_icon_svg",
    "run_iconify_batch",
]
