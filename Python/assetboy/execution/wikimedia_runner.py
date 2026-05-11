"""wikimedia_runner.py — Batch-fetch CC-licensed images from Wikimedia Commons.

Wikimedia Commons hosts ~100M media files, most under CC-BY-SA, CC-BY, CC0, or
public domain. The API requires no key, no auth, no rate limit (be polite:
<200 req/sec per their User-Agent policy).

Endpoints used (MediaWiki Action API):
    GET /w/api.php?action=query&list=search&srsearch=<term>&srnamespace=6
        -> {query: {search: [{title, ...}]}}     # ns=6 = File: namespace
    GET /w/api.php?action=query&prop=imageinfo&titles=File:<name>
                  &iiprop=url|extmetadata|size
        -> {query: {pages: {<id>: {imageinfo: [{url, extmetadata: {License, ...}}]}}}}

CLI driver: `assetboy gen wikimedia fetch --query "stone wall" --count 8`

We filter to CC-BY / CC-BY-SA / CC0 / PD only; anything more restrictive
(fair use, "by permission", etc.) is skipped with a clear note.

Use case in FAW: reference plates for ComfyUI img2img, texture mood boards,
seed images for recipe packs.
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

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "flax-asset-worker/1.10 (CC0/CC-BY collector; +https://github.com/flax-game-studio)"

# License names we accept (from extmetadata.LicenseShortName.value).
# Wikimedia normalizes these; case-insensitive substring match.
_ACCEPTED_LICENSE_TOKENS = (
    "cc0", "public domain", "pd-", "pd ",
    "cc-by-sa", "cc by-sa", "cc-by ", "cc by ",
    "cc-by-2", "cc by-2", "cc-by-3", "cc by-3", "cc-by-4", "cc by-4",
)


@dataclass
class WikimediaResult:
    """Outcome of one batch query."""

    pack_id: str
    query: str
    output_dir: Path
    files_matched: int = 0
    files_accepted_license: int = 0
    files_downloaded: int = 0
    files_skipped_restricted: int = 0
    files_failed: int = 0
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


def _download_binary(url: str, dest: Path, *, timeout: float = 30.0) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def is_license_accepted(license_short_name: str) -> bool:
    """True if the license string matches one of our acceptable CC tokens.

    Args:
        license_short_name: e.g. "CC0", "CC BY-SA 4.0", "Public domain", "All rights reserved".
    """
    if not license_short_name:
        return False
    norm = license_short_name.strip().lower()
    return any(tok in norm for tok in _ACCEPTED_LICENSE_TOKENS)


def search_wikimedia_files(
    query: str,
    *,
    limit: int = 20,
    timeout: float = 15.0,
) -> list[str]:
    """Search File: namespace; return list of file titles (e.g. ['File:Foo.jpg', ...])."""
    params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": query,
        "srnamespace": "6",   # File: namespace
        "srlimit": str(limit),
    }
    url = f"{WIKIMEDIA_API}?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    results = payload.get("query", {}).get("search", [])
    return [str(r.get("title", "")) for r in results if r.get("title")]


def fetch_wikimedia_imageinfo(file_title: str, *, timeout: float = 15.0) -> dict:
    """Fetch imageinfo for a File:<name>; returns the first imageinfo dict or {}."""
    params = {
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "titles": file_title,
        "iiprop": "url|extmetadata|size|mime",
    }
    url = f"{WIKIMEDIA_API}?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    pages = payload.get("query", {}).get("pages", {})
    if not pages:
        return {}
    # pages is a dict keyed by page id (or "-1" for missing); take the first.
    page = next(iter(pages.values()))
    infos = page.get("imageinfo") or []
    if not infos:
        return {}
    return dict(infos[0])


def run_wikimedia_batch(
    *,
    query: str,
    pack_id: str | None = None,
    count: int = 6,
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.2,
    dry_run: bool = False,
) -> WikimediaResult:
    """Search Wikimedia Commons for `query`, download CC-licensed image files.

    Args:
        query: free-text search (matches file name, description, metadata).
        pack_id: pack id for output dir; default derived from query.
        count: max files to download AFTER license filter.
        output_dir: override; default <manual_drop>/wikimedia/<pack_id>/.
        polite_sleep_s: delay between per-file API calls (default 200ms).
        dry_run: when True, hit search + imageinfo but skip binary downloads.

    Returns:
        WikimediaResult.
    """
    resolved_pack_id = pack_id or f"WIKIMEDIA_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "wikimedia" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = WikimediaResult(
        pack_id=resolved_pack_id,
        query=query,
        output_dir=out_dir,
        dry_run=dry_run,
    )

    # Search; oversample 3x to absorb license-filter losses.
    try:
        titles = search_wikimedia_files(query, limit=max(count * 3, 20))
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.files_matched = len(titles)

    if not titles:
        result.error = "no_matches"
        return result

    manifest_entries: list[dict] = []
    for title in titles:
        if result.files_downloaded >= count:
            break
        try:
            info = fetch_wikimedia_imageinfo(title)
        except (urllib.error.URLError, ValueError, TimeoutError):
            result.files_failed += 1
            continue

        if not info or not info.get("url"):
            result.files_failed += 1
            continue

        extmeta = info.get("extmetadata", {}) or {}
        license_field = extmeta.get("LicenseShortName", {}) or {}
        license_short = str(license_field.get("value", "") or "")
        artist_field = extmeta.get("Artist", {}) or {}
        artist_html = str(artist_field.get("value", "") or "")

        if not is_license_accepted(license_short):
            result.files_skipped_restricted += 1
            continue
        result.files_accepted_license += 1

        image_url = info["url"]
        url_path = urllib.parse.urlparse(image_url).path
        filename = Path(url_path).name or f"wm_{title}.jpg"
        # Sanitize filename — wikimedia URL-encodes spaces etc.
        filename = urllib.parse.unquote(filename)
        dest = out_dir / filename

        entry = {
            "title": title,
            "license": license_short,
            "artist_html": artist_html,
            "source_url": image_url,
            "description_url": info.get("descriptionurl", ""),
            "mime": info.get("mime", ""),
            "width": info.get("width", 0),
            "height": info.get("height", 0),
            "size_bytes_api": info.get("size", 0),
            "local_path": str(dest),
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.files_downloaded += 1
            result.downloaded_paths.append(dest)
            continue

        try:
            byte_count = _download_binary(image_url, dest)
            entry["downloaded"] = True
            entry["bytes"] = byte_count
            result.files_downloaded += 1
            result.downloaded_paths.append(dest)
            manifest_entries.append(entry)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            entry["downloaded"] = False
            entry["error"] = str(exc)
            manifest_entries.append(entry)
            result.files_failed += 1

        if polite_sleep_s > 0:
            time.sleep(polite_sleep_s)

    manifest = {
        "source": "wikimedia_commons",
        "pack_id": resolved_pack_id,
        "query": query,
        "files_matched": result.files_matched,
        "files_accepted_license": result.files_accepted_license,
        "files_downloaded": result.files_downloaded,
        "files_skipped_restricted": result.files_skipped_restricted,
        "files_failed": result.files_failed,
        "license_policy": "CC0 | CC-BY | CC-BY-SA | Public Domain only",
        "license_policy_url": "https://commons.wikimedia.org/wiki/Commons:Licensing",
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "wikimedia_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    if result.files_downloaded == 0 and result.files_matched > 0:
        if not result.error:
            result.error = "no_accepted_license_in_first_slice"

    return result


__all__ = [
    "WIKIMEDIA_API",
    "WikimediaResult",
    "is_license_accepted",
    "search_wikimedia_files",
    "fetch_wikimedia_imageinfo",
    "run_wikimedia_batch",
]
