"""archive_org_runner.py — Batch-fetch CC/PD media from the Internet Archive.

Internet Archive (archive.org) hosts ~50M+ items: books, audio, video, software,
images. Most legacy uploads are CC0 / Public Domain; modern uploads vary.
No API key, no auth, no documented rate limit (be polite: <50 req/sec).

Endpoints used:
    GET /advancedsearch.php?q=<query>&fl[]=identifier&fl[]=title&fl[]=licenseurl
                            &fl[]=mediatype&rows=<N>&output=json
        -> {response: {docs: [{identifier, title, licenseurl, mediatype}, ...]}}
    GET /metadata/<identifier>
        -> {metadata: {...}, files: [{name, format, size, source, ...}], ...}
    GET /download/<identifier>/<filename>  (binary)

CLI driver: `assetboy gen archive-org fetch --query "subject:roman" --count 5`

This runner filters to items with CC/PD-compatible licenseurl values and
optional mediatype (image/audio/movies/texts). Restrictive licenses are
skipped.

Use cases in FAW:
  - Historical photography / public-domain art (reference plates).
  - Public-domain audio (game ambiences, sfx).
  - Old games / software (reference / nostalgia mood).
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

ARCHIVE_BASE = "https://archive.org"
USER_AGENT = "flax-asset-worker/1.10 (CC/PD collector; +https://github.com/flax-game-studio)"

# License URL tokens we accept. archive.org standard licenses live at
# https://creativecommons.org/licenses/... and https://creativecommons.org/publicdomain/...
_ACCEPTED_LICENSE_TOKENS = (
    "creativecommons.org/licenses/by/",     # CC-BY
    "creativecommons.org/licenses/by-sa/",  # CC-BY-SA
    "creativecommons.org/publicdomain/",    # CC0 + PD mark
    "creativecommons.org/license/publicdomain",
)

# File formats we'll download per mediatype (filter out giant derived/source files).
# This keeps us picking sensible preview-quality files, not 4GB raw scans.
_FORMAT_ALLOWLIST = {
    "image": {"JPEG", "JPG", "PNG", "GIF", "TIFF Tile"},
    "audio": {"VBR MP3", "MP3", "Ogg Vorbis", "Flac"},
    "movies": {"MPEG4", "h.264", "Matroska"},
    "texts": {"Text PDF", "Image Container PDF"},
}


@dataclass
class ArchiveOrgResult:
    """Outcome of one batch query."""

    pack_id: str
    query: str
    output_dir: Path
    items_matched: int = 0
    items_accepted_license: int = 0
    items_downloaded: int = 0
    items_skipped_restricted: int = 0
    items_failed: int = 0
    downloaded_paths: list[Path] = field(default_factory=list)
    manifest_path: Path | None = None
    dry_run: bool = False
    ok: bool = True
    error: str | None = None


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def _get_json(url: str, *, timeout: float = 20.0) -> dict:
    """v1.12.s69: retries HTTP 429/503/502/504 via with_429_retry."""
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

def is_license_accepted(licenseurl: str) -> bool:
    """True if licenseurl matches our CC-BY / CC-BY-SA / CC0 / PD allowlist."""
    if not licenseurl:
        return False
    norm = licenseurl.strip().lower()
    return any(tok in norm for tok in _ACCEPTED_LICENSE_TOKENS)


def search_archive_items(
    query: str,
    *,
    mediatype: str | None = None,
    rows: int = 20,
    timeout: float = 20.0,
) -> list[dict]:
    """Run advancedsearch; return docs list with {identifier, title, licenseurl, mediatype}."""
    q = query
    if mediatype:
        q = f"({query}) AND mediatype:{mediatype}"
    params = [
        ("q", q),
        ("fl[]", "identifier"),
        ("fl[]", "title"),
        ("fl[]", "licenseurl"),
        ("fl[]", "mediatype"),
        ("rows", str(rows)),
        ("output", "json"),
    ]
    url = f"{ARCHIVE_BASE}/advancedsearch.php?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    docs = payload.get("response", {}).get("docs", [])
    return list(docs)


def fetch_archive_metadata(identifier: str, *, timeout: float = 20.0) -> dict:
    """Fetch /metadata/<id>; returns full record including files list."""
    url = f"{ARCHIVE_BASE}/metadata/{urllib.parse.quote(identifier, safe='')}"
    return _get_json(url, timeout=timeout)


def pick_download_file(metadata: dict, mediatype: str) -> dict | None:
    """From a metadata record's files list, pick one suitable preview file.

    Returns the file dict (containing 'name' and 'format') or None.
    """
    files = metadata.get("files", []) or []
    allow = _FORMAT_ALLOWLIST.get(mediatype, set())
    # Prefer allowlisted formats first; fall back to first file with a name.
    for f in files:
        if not isinstance(f, dict):
            continue
        fmt = str(f.get("format", ""))
        name = str(f.get("name", ""))
        if name and (not allow or fmt in allow):
            return f
    # Fall back: first named file.
    for f in files:
        if isinstance(f, dict) and f.get("name"):
            return f
    return None


def run_archive_org_batch(
    *,
    query: str,
    mediatype: str | None = None,
    pack_id: str | None = None,
    count: int = 4,
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.3,
    dry_run: bool = False,
) -> ArchiveOrgResult:
    """Search archive.org for `query`, download CC/PD-licensed items' preview files.

    Args:
        query: lucene-ish query (e.g. 'subject:roman' or 'creator:nasa').
        mediatype: 'image' | 'audio' | 'movies' | 'texts' (None = no filter).
        pack_id: pack id for output dir; default from query slug.
        count: max items to download.
        output_dir: override; default <manual_drop>/archive_org/<pack_id>/.
        polite_sleep_s: sleep between per-item metadata + download calls.
        dry_run: when True, hit search + metadata but skip binary downloads.
    """
    resolved_pack_id = pack_id or f"ARCHIVE_{query.replace(' ', '_').replace(':', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "archive_org" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = ArchiveOrgResult(
        pack_id=resolved_pack_id,
        query=query,
        output_dir=out_dir,
        dry_run=dry_run,
    )

    try:
        docs = search_archive_items(
            query, mediatype=mediatype, rows=max(count * 4, 20),
        )
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.items_matched = len(docs)
    if not docs:
        result.error = "no_matches"
        return result

    manifest_entries: list[dict] = []
    for doc in docs:
        if result.items_downloaded >= count:
            break
        identifier = str(doc.get("identifier", ""))
        if not identifier:
            continue
        licenseurl = str(doc.get("licenseurl", "") or "")
        item_mediatype = str(doc.get("mediatype", "") or "")

        if not is_license_accepted(licenseurl):
            result.items_skipped_restricted += 1
            continue
        result.items_accepted_license += 1

        try:
            meta = fetch_archive_metadata(identifier)
        except (urllib.error.URLError, ValueError, TimeoutError):
            result.items_failed += 1
            continue

        file_info = pick_download_file(meta, item_mediatype or (mediatype or "image"))
        if not file_info:
            result.items_failed += 1
            continue

        filename = str(file_info.get("name", ""))
        if not filename:
            result.items_failed += 1
            continue

        download_url = f"{ARCHIVE_BASE}/download/{urllib.parse.quote(identifier, safe='')}/{urllib.parse.quote(filename, safe='')}"
        # Local filename: prefix with identifier to disambiguate.
        local_name = f"{identifier}__{filename}"
        # Sanitize path separators / suspect chars in identifier+filename.
        local_name = local_name.replace("/", "_").replace("\\", "_")
        dest = out_dir / local_name

        entry = {
            "identifier": identifier,
            "title": str(doc.get("title", "")),
            "mediatype": item_mediatype,
            "license_url": licenseurl,
            "license_accepted": True,
            "source_url": download_url,
            "item_url": f"{ARCHIVE_BASE}/details/{identifier}",
            "filename": filename,
            "format": str(file_info.get("format", "")),
            "size_bytes_api": file_info.get("size"),
            "local_path": str(dest),
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.items_downloaded += 1
            result.downloaded_paths.append(dest)
            continue

        try:
            byte_count = _download_binary(download_url, dest)
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
        "source": "archive_org",
        "pack_id": resolved_pack_id,
        "query": query,
        "mediatype_filter": mediatype,
        "items_matched": result.items_matched,
        "items_accepted_license": result.items_accepted_license,
        "items_downloaded": result.items_downloaded,
        "items_skipped_restricted": result.items_skipped_restricted,
        "items_failed": result.items_failed,
        "license_policy": "CC-BY | CC-BY-SA | CC0 | Public Domain only",
        "license_policy_url": "https://archive.org/about/terms.php",
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "archive_org_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    if result.items_downloaded == 0 and result.items_matched > 0:
        if not result.error:
            result.error = "no_accepted_license_in_first_slice"

    return result


__all__ = [
    "ARCHIVE_BASE",
    "ArchiveOrgResult",
    "is_license_accepted",
    "search_archive_items",
    "fetch_archive_metadata",
    "pick_download_file",
    "run_archive_org_batch",
]
