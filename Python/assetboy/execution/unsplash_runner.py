"""unsplash_runner.py — Batch-fetch free stock photos from Unsplash.

Unsplash (unsplash.com) offers high-quality stock photography under the
Unsplash License (free for personal AND commercial use, no attribution
required but appreciated; cannot be used to compete with Unsplash itself).

Auth: read-access via `Authorization: Client-ID <access_key>` header.
This is the "demo" mode — no full OAuth dance required for public endpoints.
Free dev tier: 50 req/hour. Free signup at https://unsplash.com/developers.

Auth env var: `UNSPLASH_ACCESS_KEY`.

API endpoints (api.unsplash.com):
    GET /search/photos?query=<term>&per_page=<n>&page=<n>&orientation=<o>
        Header: Authorization: Client-ID <key>
        -> {total, total_pages, results: [{id, urls: {raw, full, regular,
                                                     small, thumb},
                                          user: {name, links: {html}},
                                          description, alt_description, ...}]}

Hotlink rule: per Unsplash API guidelines, downloads MUST trigger
the /photos/<id>/download endpoint for usage analytics. We hit that
endpoint after each successful image fetch (non-blocking; failures logged
but don't fail the slice).

CLI driver: `assetboy gen unsplash photos --query "stone wall" --count 4`
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from assetboy.execution.comfyui_runner import manual_drop_dir

UNSPLASH_API = "https://api.unsplash.com"
USER_AGENT = "flax-asset-worker/1.10 (Unsplash-licensed collector; +https://github.com/flax-game-studio)"
UNSPLASH_ACCESS_KEY_ENV = "UNSPLASH_ACCESS_KEY"

_VALID_VARIANTS = {"raw", "full", "regular", "small", "thumb"}
_VALID_ORIENTATIONS = {"landscape", "portrait", "squarish"}


@dataclass
class UnsplashResult:
    """Outcome of one batch query."""

    pack_id: str
    query: str
    output_dir: Path
    photos_matched: int = 0
    photos_downloaded: int = 0
    photos_failed: int = 0
    download_pings: int = 0  # successful /photos/{id}/download triggers
    downloaded_paths: list[Path] = field(default_factory=list)
    manifest_path: Path | None = None
    dry_run: bool = False
    ok: bool = True
    error: str | None = None


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def get_access_key() -> str | None:
    key = os.environ.get(UNSPLASH_ACCESS_KEY_ENV, "").strip()
    return key or None


def _authed_get_json(url: str, access_key: str, *, timeout: float = 20.0) -> dict:
    """v1.12.s68: retries HTTP 429/503/502/504 via with_429_retry."""
    from assetboy.execution._http_retry import with_429_retry

    def _do_call() -> dict:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Authorization": f"Client-ID {access_key}",
                "Accept-Version": "v1",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    return with_429_retry(_do_call, max_retries=3, base_delay_s=1.0, cap_delay_s=30.0)


def _download_binary(url: str, dest: Path, *, timeout: float = 60.0) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


def _trigger_download_endpoint(
    photo_id: str, access_key: str, *, timeout: float = 10.0,
) -> bool:
    """Hit /photos/<id>/download to register the download per Unsplash API guidelines.

    Returns True on success. Failure is non-blocking (logged in manifest).
    """
    try:
        url = f"{UNSPLASH_API}/photos/{urllib.parse.quote(photo_id, safe='')}/download"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Authorization": f"Client-ID {access_key}",
                "Accept-Version": "v1",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()  # discard
        return True
    except (urllib.error.URLError, ValueError, TimeoutError):
        return False


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def search_unsplash_photos(
    query: str,
    *,
    access_key: str,
    per_page: int = 10,
    page: int = 1,
    orientation: str | None = None,
    collections: str | None = None,
    timeout: float = 20.0,
) -> list[dict]:
    """Hit /search/photos; return results list.

    v1.19.s133: optional collections= filter (comma-separated collection IDs).
    """
    if orientation and orientation not in _VALID_ORIENTATIONS:
        raise ValueError(
            f"invalid orientation {orientation!r}; valid: {sorted(_VALID_ORIENTATIONS)}"
        )
    params = {
        "query": query,
        "per_page": str(max(1, min(per_page, 30))),  # Unsplash max 30
        "page": str(page),
    }
    if orientation:
        params["orientation"] = orientation
    if collections:
        params["collections"] = collections
    url = f"{UNSPLASH_API}/search/photos?{urllib.parse.urlencode(params)}"
    payload = _authed_get_json(url, access_key, timeout=timeout)
    return list(payload.get("results", []))


def run_unsplash_photo_batch(
    *,
    query: str,
    access_key: str | None = None,
    pack_id: str | None = None,
    count: int = 6,
    variant: str = "regular",
    orientation: str | None = None,
    collections: str | None = None,
    min_width: int = 0,
    min_height: int = 0,
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.2,
    dry_run: bool = False,
    skip_download_ping: bool = False,
) -> UnsplashResult:
    """Search Unsplash and download `count` photos at `variant` resolution.

    Args:
        query: free-text search.
        access_key: UNSPLASH_ACCESS_KEY (falls back to env var).
        count: max photos to download.
        variant: 'raw' (full original) | 'full' | 'regular' (1080w default)
                | 'small' | 'thumb'.
        orientation: optional 'landscape' | 'portrait' | 'squarish'.
        skip_download_ping: when True, skip the /photos/<id>/download ping
                            (use only for testing; production should ping
                            to honor Unsplash API guidelines).
    """
    if variant not in _VALID_VARIANTS:
        result = UnsplashResult(
            pack_id=pack_id or "INVALID", query=query,
            output_dir=Path(output_dir) if output_dir else Path("."),
            ok=False,
            error=f"invalid_variant: {variant!r} not in {sorted(_VALID_VARIANTS)}",
        )
        return result

    resolved_pack_id = pack_id or f"UNSPLASH_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "unsplash" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = UnsplashResult(
        pack_id=resolved_pack_id, query=query, output_dir=out_dir,
        dry_run=dry_run,
    )

    key = access_key or get_access_key()
    if not key:
        result.ok = False
        result.error = f"missing_access_key (set ${UNSPLASH_ACCESS_KEY_ENV})"
        return result

    try:
        photos = search_unsplash_photos(
            query, access_key=key, per_page=min(count, 30),
            orientation=orientation, collections=collections,
        )
    except urllib.error.HTTPError as exc:
        result.ok = False
        result.error = f"search_failed: HTTP {exc.code}"
        return result
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.photos_matched = len(photos)
    if not photos:
        result.error = "no_matches"
        return result

    manifest_entries: list[dict] = []
    for photo in photos:
        if result.photos_downloaded >= count:
            break
        if not isinstance(photo, dict):
            continue
        # v1.40.s228 — min_width / min_height post-filter (Unsplash reports
        # width / height at top level).
        if min_width > 0 or min_height > 0:
            pw = int(photo.get("width", 0) or 0)
            ph = int(photo.get("height", 0) or 0)
            if (min_width > 0 and pw < min_width) or \
               (min_height > 0 and ph < min_height):
                continue
        urls = photo.get("urls", {}) or {}
        image_url = urls.get(variant) or urls.get("regular") or urls.get("small")
        if not image_url:
            result.photos_failed += 1
            continue

        photo_id = str(photo.get("id", ""))
        user = photo.get("user", {}) or {}
        photographer = str(user.get("name", "") or "")
        photographer_html = ((user.get("links") or {}).get("html", "")
                             if isinstance(user.get("links"), dict) else "")

        suffix = ".jpg"
        dest = out_dir / f"unsplash_{photo_id}{suffix}"

        entry = {
            "id": photo_id,
            "photographer": photographer,
            "photographer_url": photographer_html,
            "description": str(photo.get("description", "") or ""),
            "alt_description": str(photo.get("alt_description", "") or ""),
            "page_url": ((photo.get("links") or {}).get("html", "")
                        if isinstance(photo.get("links"), dict) else ""),
            "variant": variant,
            "orientation": orientation,
            "width": photo.get("width", 0),
            "height": photo.get("height", 0),
            "source_url": image_url,
            "license": "Unsplash License (free personal+commercial; attribution appreciated)",
            "license_url": "https://unsplash.com/license",
            "attribution_required": False,
            "attribution_appreciated": True,
            "attribution_suggested": (
                f"Photo by {photographer} on Unsplash"
                if photographer else "Photo on Unsplash"
            ),
            "local_path": str(dest),
            "download_ping_triggered": False,
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.photos_downloaded += 1
            result.downloaded_paths.append(dest)
            continue

        try:
            byte_count = _download_binary(image_url, dest)
            entry["downloaded"] = True
            entry["bytes"] = byte_count
            result.photos_downloaded += 1
            result.downloaded_paths.append(dest)
            # Trigger Unsplash download-tracking endpoint (best-effort).
            if not skip_download_ping:
                if _trigger_download_endpoint(photo_id, key):
                    entry["download_ping_triggered"] = True
                    result.download_pings += 1
            manifest_entries.append(entry)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            entry["downloaded"] = False
            entry["error"] = str(exc)
            manifest_entries.append(entry)
            result.photos_failed += 1

        if polite_sleep_s > 0:
            from assetboy.execution._http_retry import get_polite_sleep_s
            time.sleep(get_polite_sleep_s(polite_sleep_s))

    manifest = {
        "source": "unsplash",
        "pack_id": resolved_pack_id,
        "query": query,
        "variant": variant,
        "orientation": orientation,
        "photos_matched": result.photos_matched,
        "photos_downloaded": result.photos_downloaded,
        "photos_failed": result.photos_failed,
        "download_pings": result.download_pings,
        "license": "Unsplash License",
        "license_url": "https://unsplash.com/license",
        "attribution_required": False,
        "attribution_appreciated": True,
        "guidelines_url": "https://help.unsplash.com/en/collections/1463188-unsplash-api",
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "unsplash_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    return result


__all__ = [
    "UNSPLASH_API",
    "UNSPLASH_ACCESS_KEY_ENV",
    "UnsplashResult",
    "get_access_key",
    "search_unsplash_photos",
    "run_unsplash_photo_batch",
]
