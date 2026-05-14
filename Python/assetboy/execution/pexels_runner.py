"""pexels_runner.py — Batch-fetch free stock photos + video from Pexels.

Pexels (pexels.com) offers a free API with generous rate limits (200/hour
default, 20k/month). All photos and videos are released under the
**Pexels License**: free for personal AND commercial use, no attribution
required (attribution appreciated).

Auth: requires an API key. Free signup at https://www.pexels.com/api/new/.
We read the key from `PEXELS_API_KEY` env var.

API endpoints (api.pexels.com):
    GET /v1/search?query=<term>&per_page=<n>&page=<n>
        Header: Authorization: <key>
        -> {photos: [{id, width, height, url, photographer, src: {original,
                                large, medium, small, tiny, portrait, landscape}}]}
    GET /videos/search?query=<term>&per_page=<n>
        -> {videos: [{id, width, height, duration, video_files: [
                       {id, quality, file_type, link, width, height}]}]}

CLI driver:
    assetboy gen pexels photos --query "stone wall" --count 4
    assetboy gen pexels videos --query "fire crackling" --count 2

This is FAW's FIRST video provider — opens recipe support for video
reference plates downstream.
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

PEXELS_API = "https://api.pexels.com"
USER_AGENT = "flax-asset-worker/1.10 (Pexels-licensed collector; +https://github.com/flax-game-studio)"
PEXELS_API_KEY_ENV = "PEXELS_API_KEY"


@dataclass
class PexelsResult:
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
    """Read PEXELS_API_KEY from env. Returns None if unset/empty."""
    key = os.environ.get(PEXELS_API_KEY_ENV, "").strip()
    return key or None


def _authed_get_json(url: str, api_key: str, *, timeout: float = 20.0) -> dict:
    """v1.12.s67: now retries on HTTP 429/503/502/504 via with_429_retry."""
    from assetboy.execution._http_retry import with_429_retry

    def _do_call() -> dict:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Authorization": api_key,
                "Accept": "application/json",
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


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

_VALID_PEXELS_ORIENTATIONS = {"landscape", "portrait", "square"}


def search_pexels_photos(
    query: str,
    *,
    api_key: str,
    per_page: int = 15,
    page: int = 1,
    orientation: str | None = None,
    timeout: float = 20.0,
) -> list[dict]:
    """Hit /v1/search; return list of photo records.

    v1.24.s166: orientation = 'landscape' | 'portrait' | 'square' (Pexels native).
    """
    if orientation and orientation not in _VALID_PEXELS_ORIENTATIONS:
        raise ValueError(
            f"invalid orientation {orientation!r}; valid: {sorted(_VALID_PEXELS_ORIENTATIONS)}"
        )
    params = {"query": query, "per_page": str(per_page), "page": str(page)}
    if orientation:
        params["orientation"] = orientation
    url = f"{PEXELS_API}/v1/search?{urllib.parse.urlencode(params)}"
    payload = _authed_get_json(url, api_key, timeout=timeout)
    return list(payload.get("photos", []))


def search_pexels_videos(
    query: str,
    *,
    api_key: str,
    per_page: int = 15,
    page: int = 1,
    timeout: float = 20.0,
) -> list[dict]:
    """Hit /videos/search; return list of video records."""
    params = {"query": query, "per_page": str(per_page), "page": str(page)}
    url = f"{PEXELS_API}/videos/search?{urllib.parse.urlencode(params)}"
    payload = _authed_get_json(url, api_key, timeout=timeout)
    return list(payload.get("videos", []))


def pick_video_file(video: dict, *, max_height: int = 1080) -> dict | None:
    """From a video record's video_files list, pick best quality <= max_height.

    Returns the file dict with {link, quality, file_type, width, height} or None.
    """
    files = video.get("video_files", []) or []
    # Filter to acceptable formats; pick highest height that's <= max_height.
    candidates: list[tuple[int, dict]] = []
    for f in files:
        if not isinstance(f, dict):
            continue
        if not f.get("link"):
            continue
        h = int(f.get("height", 0) or 0)
        if h <= max_height and h > 0:
            candidates.append((h, f))
    if not candidates:
        # Fall back to the smallest available.
        for f in files:
            if isinstance(f, dict) and f.get("link"):
                return f
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def run_pexels_photo_batch(
    *,
    query: str,
    api_key: str | None = None,
    pack_id: str | None = None,
    count: int = 6,
    variant: str = "large",
    orientation: str | None = None,
    min_width: int = 0,
    min_height: int = 0,
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.1,
    dry_run: bool = False,
) -> PexelsResult:
    """Search Pexels photos and download `count` images at `variant` size.

    Args:
        query: free-text search.
        api_key: PEXELS_API_KEY (falls back to env var if None).
        pack_id: pack id for output dir.
        count: max photos to download.
        variant: src key — 'original' | 'large2x' | 'large' | 'medium' | 'small'
                 | 'tiny' | 'portrait' | 'landscape'.
        output_dir: override.
        polite_sleep_s: delay between downloads.
        dry_run: skip binary downloads.
    """
    resolved_pack_id = pack_id or f"PEXELS_PHOTOS_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "pexels" / "photos" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = PexelsResult(
        pack_id=resolved_pack_id, query=query, output_dir=out_dir,
        kind="photos", dry_run=dry_run,
    )

    key = api_key or get_api_key()
    if not key:
        result.ok = False
        result.error = f"missing_api_key (set ${PEXELS_API_KEY_ENV})"
        return result

    try:
        photos = search_pexels_photos(
            query, api_key=key, per_page=min(count, 80),
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

    result.items_matched = len(photos)
    if not photos:
        result.error = "no_matches"
        return result

    manifest_entries: list[dict] = []
    for photo in photos:
        if result.items_downloaded >= count:
            break
        if not isinstance(photo, dict):
            continue
        # v1.40.s226 — min_width / min_height post-filter (Pexels returns w/h).
        if min_width > 0 or min_height > 0:
            ph_w = int(photo.get("width", 0) or 0)
            ph_h = int(photo.get("height", 0) or 0)
            if (min_width > 0 and ph_w < min_width) or \
               (min_height > 0 and ph_h < min_height):
                continue
        src = photo.get("src", {}) or {}
        image_url = src.get(variant) or src.get("large") or src.get("original")
        if not image_url:
            result.items_failed += 1
            continue

        photo_id = photo.get("id", "")
        suffix = ".jpg"  # Pexels src URLs end in .jpg typically
        dest = out_dir / f"pexels_photo_{photo_id}{suffix}"

        entry = {
            "id": photo_id,
            "photographer": photo.get("photographer", ""),
            "photographer_url": photo.get("photographer_url", ""),
            "url": photo.get("url", ""),
            "alt": photo.get("alt", ""),
            "variant": variant,
            "source_url": image_url,
            "width": photo.get("width", 0),
            "height": photo.get("height", 0),
            "license": "Pexels License (free for personal + commercial; attribution appreciated)",
            "license_url": "https://www.pexels.com/license/",
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
        "source": "pexels",
        "kind": "photos",
        "pack_id": resolved_pack_id,
        "query": query,
        "variant": variant,
        "items_matched": result.items_matched,
        "items_downloaded": result.items_downloaded,
        "items_failed": result.items_failed,
        "license": "Pexels License",
        "license_url": "https://www.pexels.com/license/",
        "attribution_required": False,
        "attribution_appreciated": True,
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "pexels_photos_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    return result


def run_pexels_video_batch(
    *,
    query: str,
    api_key: str | None = None,
    pack_id: str | None = None,
    count: int = 3,
    max_height: int = 1080,
    min_duration_s: float = 0.0,
    min_width: int = 0,
    min_height: int = 0,
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.2,
    dry_run: bool = False,
) -> PexelsResult:
    """Search Pexels videos and download `count` videos at <= max_height.

    Args:
        query: free-text search.
        api_key: PEXELS_API_KEY (falls back to env var).
        count: max videos to download.
        max_height: prefer the highest-quality file <= this many pixels.
        min_duration_s: v1.28.s183 - skip videos shorter than this duration
                        (Pexels reports duration in seconds). 0.0 = no filter.
    """
    resolved_pack_id = pack_id or f"PEXELS_VIDEOS_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "pexels" / "videos" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = PexelsResult(
        pack_id=resolved_pack_id, query=query, output_dir=out_dir,
        kind="videos", dry_run=dry_run,
    )

    key = api_key or get_api_key()
    if not key:
        result.ok = False
        result.error = f"missing_api_key (set ${PEXELS_API_KEY_ENV})"
        return result

    try:
        videos = search_pexels_videos(query, api_key=key, per_page=min(count * 2, 80))
    except urllib.error.HTTPError as exc:
        result.ok = False
        result.error = f"search_failed: HTTP {exc.code}"
        return result
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.items_matched = len(videos)
    if not videos:
        result.error = "no_matches"
        return result

    manifest_entries: list[dict] = []
    for video in videos:
        if result.items_downloaded >= count:
            break
        if not isinstance(video, dict):
            continue
        # v1.28.s183 — apply min_duration_s filter (Pexels duration is int seconds).
        if min_duration_s > 0:
            dur = video.get("duration", 0) or 0
            if dur < min_duration_s:
                continue
        file_info = pick_video_file(video, max_height=max_height)
        if not file_info:
            result.items_failed += 1
            continue
        # v1.42.s241 — min_width / min_height filter on picked file dims.
        if min_width > 0 or min_height > 0:
            fw = int(file_info.get("width", 0) or 0)
            fh = int(file_info.get("height", 0) or 0)
            if (min_width > 0 and fw < min_width) or \
               (min_height > 0 and fh < min_height):
                continue
        link = str(file_info.get("link", ""))
        if not link:
            result.items_failed += 1
            continue

        vid_id = video.get("id", "")
        suffix = ".mp4"
        ftype = str(file_info.get("file_type", "video/mp4"))
        if "webm" in ftype:
            suffix = ".webm"
        dest = out_dir / f"pexels_video_{vid_id}{suffix}"

        entry = {
            "id": vid_id,
            "user": (video.get("user") or {}).get("name", "")
                    if isinstance(video.get("user"), dict) else "",
            "url": video.get("url", ""),
            "duration_s": video.get("duration", 0),
            "width": file_info.get("width", 0),
            "height": file_info.get("height", 0),
            "quality": file_info.get("quality", ""),
            "file_type": ftype,
            "source_url": link,
            "license": "Pexels License",
            "license_url": "https://www.pexels.com/license/",
            "local_path": str(dest),
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.items_downloaded += 1
            result.downloaded_paths.append(dest)
            continue

        try:
            byte_count = _download_binary(link, dest)
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
        "source": "pexels",
        "kind": "videos",
        "pack_id": resolved_pack_id,
        "query": query,
        "max_height_px": max_height,
        "items_matched": result.items_matched,
        "items_downloaded": result.items_downloaded,
        "items_failed": result.items_failed,
        "license": "Pexels License",
        "license_url": "https://www.pexels.com/license/",
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "pexels_videos_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    return result


__all__ = [
    "PEXELS_API",
    "PEXELS_API_KEY_ENV",
    "PexelsResult",
    "get_api_key",
    "search_pexels_photos",
    "search_pexels_videos",
    "pick_video_file",
    "run_pexels_photo_batch",
    "run_pexels_video_batch",
]
