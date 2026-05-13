"""pixabay_runner.py — Batch-fetch free CC0-equivalent media from Pixabay.

Pixabay (pixabay.com) offers a free API. All content is under the
**Pixabay Content License** — equivalent to CC0 (free for personal +
commercial use, no attribution required, no derivative restrictions).

Auth: requires API key. Free signup at https://pixabay.com/api/docs/.
We read from `PIXABAY_API_KEY` env var.

API endpoints (pixabay.com/api):
    GET /?key=<key>&q=<term>&image_type=<photo|illustration|vector|all>
        &per_page=<n>&page=<n>&safesearch=true
        -> {hits: [{id, pageURL, type, tags, previewURL, webformatURL,
                    largeImageURL, fullHDURL?, imageURL?, user, ...}]}
    GET /videos/?key=<key>&q=<term>&per_page=<n>
        -> {hits: [{id, pageURL, tags, duration, videos: {
                     large: {url, width, height, size},
                     medium: {url, ...}, small: {...}, tiny: {...}}}]}

CLI driver:
    assetboy gen pixabay photos --query "stone wall" --count 4
    assetboy gen pixabay videos --query "fire" --count 2

Pixabay is the Pexels twin: complementary search coverage + CC0
licensing (Pexels License requires no attribution either, but Pixabay
is explicitly CC0-compatible per their TOS).
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

PIXABAY_API = "https://pixabay.com/api"
USER_AGENT = "flax-asset-worker/1.10 (Pixabay-licensed collector; +https://github.com/flax-game-studio)"
PIXABAY_API_KEY_ENV = "PIXABAY_API_KEY"

_VALID_IMAGE_TYPES = {"all", "photo", "illustration", "vector"}
_VALID_PHOTO_VARIANTS = {"largeImageURL", "fullHDURL", "imageURL", "webformatURL", "previewURL"}
_VALID_VIDEO_VARIANTS = {"large", "medium", "small", "tiny"}


@dataclass
class PixabayResult:
    """Outcome of one batch query (photos OR videos)."""

    pack_id: str
    query: str
    output_dir: Path
    kind: str = "photos"  # 'photos' | 'videos'
    items_matched: int = 0
    items_downloaded: int = 0
    items_failed: int = 0
    downloaded_paths: list[Path] = field(default_factory=list)
    manifest_path: Path | None = None
    dry_run: bool = False
    ok: bool = True
    error: str | None = None


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def get_api_key() -> str | None:
    """Read PIXABAY_API_KEY from env. Returns None if unset/empty."""
    key = os.environ.get(PIXABAY_API_KEY_ENV, "").strip()
    return key or None


def _get_json(url: str, *, timeout: float = 20.0) -> dict:
    """v1.12.s68: retries HTTP 429/503/502/504 via with_429_retry."""
    from assetboy.execution._http_retry import with_429_retry

    def _do_call() -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

_VALID_ORIENTATIONS = {"all", "horizontal", "vertical"}


def search_pixabay_photos(
    query: str,
    *,
    api_key: str,
    image_type: str = "photo",
    per_page: int = 20,
    page: int = 1,
    safesearch: bool = True,
    orientation: str | None = None,
    timeout: float = 20.0,
) -> list[dict]:
    """Hit /api?image_type=...; return hits list.

    v1.24.s165: orientation = 'horizontal' | 'vertical' | 'all' (Pixabay native).
    """
    if image_type not in _VALID_IMAGE_TYPES:
        raise ValueError(f"invalid image_type {image_type!r}; valid: {sorted(_VALID_IMAGE_TYPES)}")
    if orientation and orientation not in _VALID_ORIENTATIONS:
        raise ValueError(
            f"invalid orientation {orientation!r}; valid: {sorted(_VALID_ORIENTATIONS)}"
        )
    params = {
        "key": api_key,
        "q": query,
        "image_type": image_type,
        "per_page": str(max(3, min(per_page, 200))),  # Pixabay min 3, max 200
        "page": str(page),
        "safesearch": "true" if safesearch else "false",
    }
    if orientation:
        params["orientation"] = orientation
    url = f"{PIXABAY_API}/?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    return list(payload.get("hits", []))


def search_pixabay_videos(
    query: str,
    *,
    api_key: str,
    per_page: int = 20,
    page: int = 1,
    safesearch: bool = True,
    timeout: float = 20.0,
) -> list[dict]:
    """Hit /api/videos/; return hits list."""
    params = {
        "key": api_key,
        "q": query,
        "per_page": str(max(3, min(per_page, 200))),
        "page": str(page),
        "safesearch": "true" if safesearch else "false",
    }
    url = f"{PIXABAY_API}/videos/?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    return list(payload.get("hits", []))


def pick_video_quality(hit: dict, variant: str = "medium") -> dict | None:
    """From a video hit, return the {url,width,height,size} for the chosen variant.

    Falls back through medium -> small -> tiny -> large if requested variant missing.
    """
    videos = hit.get("videos", {}) or {}
    fallback_order = [variant, "medium", "small", "tiny", "large"]
    seen = set()
    for v in fallback_order:
        if v in seen:
            continue
        seen.add(v)
        info = videos.get(v) or {}
        if info and info.get("url"):
            return dict(info)
    return None


def run_pixabay_photo_batch(
    *,
    query: str,
    api_key: str | None = None,
    pack_id: str | None = None,
    count: int = 6,
    image_type: str = "photo",
    variant: str = "largeImageURL",
    orientation: str | None = None,
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.1,
    dry_run: bool = False,
) -> PixabayResult:
    """Search Pixabay images and download `count` files.

    Args:
        image_type: 'photo' | 'illustration' | 'vector' | 'all'.
        variant: which URL key to download. 'largeImageURL' is full-res;
                 'webformatURL' is 640px-bounded; 'previewURL' is 150px thumb.
                 Pixabay also returns 'fullHDURL' + 'imageURL' for some
                 image_types (vectors).
    """
    if variant not in _VALID_PHOTO_VARIANTS:
        result = PixabayResult(
            pack_id=pack_id or "INVALID", query=query,
            output_dir=Path(output_dir) if output_dir else Path("."),
            kind="photos",
            ok=False,
            error=f"invalid_variant: {variant!r} not in {sorted(_VALID_PHOTO_VARIANTS)}",
        )
        return result

    resolved_pack_id = pack_id or f"PIXABAY_PHOTOS_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "pixabay" / "photos" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = PixabayResult(
        pack_id=resolved_pack_id, query=query, output_dir=out_dir,
        kind="photos", dry_run=dry_run,
    )

    key = api_key or get_api_key()
    if not key:
        result.ok = False
        result.error = f"missing_api_key (set ${PIXABAY_API_KEY_ENV})"
        return result

    try:
        hits = search_pixabay_photos(
            query, api_key=key, image_type=image_type,
            per_page=min(count * 2, 200),
            orientation=orientation,
        )
    except urllib.error.HTTPError as exc:
        result.ok = False
        result.error = f"search_failed: HTTP {exc.code}"
        return result
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.items_matched = len(hits)
    if not hits:
        result.error = "no_matches"
        return result

    manifest_entries: list[dict] = []
    for hit in hits:
        if result.items_downloaded >= count:
            break
        if not isinstance(hit, dict):
            continue
        # Try requested variant, fall back through descending sizes.
        image_url = None
        chosen_variant = None
        for v in (variant, "fullHDURL", "largeImageURL", "imageURL",
                  "webformatURL", "previewURL"):
            if hit.get(v):
                image_url = str(hit[v])
                chosen_variant = v
                break
        if not image_url:
            result.items_failed += 1
            continue

        hit_id = hit.get("id", "")
        # Derive suffix from URL.
        url_path = urllib.parse.urlparse(image_url).path
        suffix = Path(url_path).suffix or ".jpg"
        dest = out_dir / f"pixabay_photo_{hit_id}{suffix}"

        entry = {
            "id": hit_id,
            "type": str(hit.get("type", "")),
            "tags": str(hit.get("tags", "")),
            "user": str(hit.get("user", "")),
            "page_url": str(hit.get("pageURL", "")),
            "variant": chosen_variant,
            "source_url": image_url,
            "width": hit.get("imageWidth", 0),
            "height": hit.get("imageHeight", 0),
            "license": "Pixabay Content License (CC0-equivalent)",
            "license_url": "https://pixabay.com/service/license-summary/",
            "local_path": str(dest),
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.items_downloaded += 1
            result.downloaded_paths.append(dest)
            continue

        try:
            byte_count = _download_binary(image_url, dest)
            entry["downloaded"] = True
            entry["bytes"] = byte_count
            result.items_downloaded += 1
            result.downloaded_paths.append(dest)
            manifest_entries.append(entry)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            entry["downloaded"] = False
            entry["error"] = str(exc)
            manifest_entries.append(entry)
            result.items_failed += 1

        if polite_sleep_s > 0:
            from assetboy.execution._http_retry import get_polite_sleep_s
            time.sleep(get_polite_sleep_s(polite_sleep_s))

    manifest = {
        "source": "pixabay",
        "kind": "photos",
        "pack_id": resolved_pack_id,
        "query": query,
        "image_type": image_type,
        "variant_requested": variant,
        "items_matched": result.items_matched,
        "items_downloaded": result.items_downloaded,
        "items_failed": result.items_failed,
        "license": "Pixabay Content License (CC0-equivalent)",
        "license_url": "https://pixabay.com/service/license-summary/",
        "attribution_required": False,
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "pixabay_photos_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    return result


def run_pixabay_video_batch(
    *,
    query: str,
    api_key: str | None = None,
    pack_id: str | None = None,
    count: int = 3,
    variant: str = "medium",
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.2,
    dry_run: bool = False,
) -> PixabayResult:
    """Search Pixabay videos and download `count` videos.

    Args:
        variant: 'large' (1920x1080) | 'medium' (1280x720, default) |
                 'small' (960x540) | 'tiny' (640x360). Falls back if missing.
    """
    if variant not in _VALID_VIDEO_VARIANTS:
        result = PixabayResult(
            pack_id=pack_id or "INVALID", query=query,
            output_dir=Path(output_dir) if output_dir else Path("."),
            kind="videos",
            ok=False,
            error=f"invalid_variant: {variant!r} not in {sorted(_VALID_VIDEO_VARIANTS)}",
        )
        return result

    resolved_pack_id = pack_id or f"PIXABAY_VIDEOS_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "pixabay" / "videos" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = PixabayResult(
        pack_id=resolved_pack_id, query=query, output_dir=out_dir,
        kind="videos", dry_run=dry_run,
    )

    key = api_key or get_api_key()
    if not key:
        result.ok = False
        result.error = f"missing_api_key (set ${PIXABAY_API_KEY_ENV})"
        return result

    try:
        hits = search_pixabay_videos(query, api_key=key, per_page=min(count * 2, 200))
    except urllib.error.HTTPError as exc:
        result.ok = False
        result.error = f"search_failed: HTTP {exc.code}"
        return result
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.items_matched = len(hits)
    if not hits:
        result.error = "no_matches"
        return result

    manifest_entries: list[dict] = []
    for hit in hits:
        if result.items_downloaded >= count:
            break
        if not isinstance(hit, dict):
            continue
        vinfo = pick_video_quality(hit, variant=variant)
        if not vinfo or not vinfo.get("url"):
            result.items_failed += 1
            continue

        hit_id = hit.get("id", "")
        suffix = ".mp4"
        dest = out_dir / f"pixabay_video_{hit_id}{suffix}"

        entry = {
            "id": hit_id,
            "tags": str(hit.get("tags", "")),
            "user": str(hit.get("user", "")),
            "page_url": str(hit.get("pageURL", "")),
            "duration_s": hit.get("duration", 0),
            "variant": variant,
            "width": vinfo.get("width", 0),
            "height": vinfo.get("height", 0),
            "size_bytes_api": vinfo.get("size", 0),
            "source_url": vinfo["url"],
            "license": "Pixabay Content License (CC0-equivalent)",
            "license_url": "https://pixabay.com/service/license-summary/",
            "local_path": str(dest),
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.items_downloaded += 1
            result.downloaded_paths.append(dest)
            continue

        try:
            byte_count = _download_binary(vinfo["url"], dest)
            entry["downloaded"] = True
            entry["bytes"] = byte_count
            result.items_downloaded += 1
            result.downloaded_paths.append(dest)
            manifest_entries.append(entry)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            entry["downloaded"] = False
            entry["error"] = str(exc)
            manifest_entries.append(entry)
            result.items_failed += 1

        if polite_sleep_s > 0:
            from assetboy.execution._http_retry import get_polite_sleep_s
            time.sleep(get_polite_sleep_s(polite_sleep_s))

    manifest = {
        "source": "pixabay",
        "kind": "videos",
        "pack_id": resolved_pack_id,
        "query": query,
        "variant": variant,
        "items_matched": result.items_matched,
        "items_downloaded": result.items_downloaded,
        "items_failed": result.items_failed,
        "license": "Pixabay Content License (CC0-equivalent)",
        "license_url": "https://pixabay.com/service/license-summary/",
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "pixabay_videos_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    return result


__all__ = [
    "PIXABAY_API",
    "PIXABAY_API_KEY_ENV",
    "PixabayResult",
    "get_api_key",
    "search_pixabay_photos",
    "search_pixabay_videos",
    "pick_video_quality",
    "run_pixabay_photo_batch",
    "run_pixabay_video_batch",
]
