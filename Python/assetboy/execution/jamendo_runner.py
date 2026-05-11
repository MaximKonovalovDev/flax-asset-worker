"""jamendo_runner.py — Batch-fetch CC-licensed music tracks from Jamendo.

Jamendo (jamendo.com) hosts ~500K tracks under various Creative Commons
licenses (CC-BY, CC-BY-SA, CC-BY-ND, CC-BY-NC, CC-BY-NC-SA, CC-BY-NC-ND).
For commercial game use, we filter to commercial-allowed CC variants only
(CC-BY, CC-BY-SA, CC0 if available).

Auth: requires client_id only (no full OAuth dance for read access).
Free signup at https://developer.jamendo.com/. Read from `JAMENDO_CLIENT_ID`
env var.

API endpoints (api.jamendo.com/v3.0):
    GET /tracks?client_id=<id>&format=json&limit=<n>&search=<term>
        &include=licenses+musicinfo&audiodlformat=mp32
        -> {results: [{id, name, artist_name, album_name, duration,
                       audiodownload, license_ccurl, musicinfo: {tags: {...}},
                       ...}]}

CLI driver: `assetboy gen jamendo tracks --query "ambient cinematic" --count 4`

This is FAW's first true MUSIC provider (Freesound is sfx-focused).
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

JAMENDO_API = "https://api.jamendo.com/v3.0"
USER_AGENT = "flax-asset-worker/1.10 (Jamendo CC collector; +https://github.com/flax-game-studio)"
JAMENDO_CLIENT_ID_ENV = "JAMENDO_CLIENT_ID"

# Jamendo's license_ccurl points at creativecommons.org/licenses/<variant>/x.x/
# We accept CC variants that allow COMMERCIAL use (no -NC) AND DERIVATIVE
# works (no -ND) by default. Operator can broaden with --allow-restrictive.
_COMMERCIAL_OK_TOKENS = (
    "creativecommons.org/licenses/by/",       # CC-BY
    "creativecommons.org/licenses/by-sa/",    # CC-BY-SA
    "creativecommons.org/publicdomain/",      # CC0 / PD
)
_DERIVATIVE_OK_TOKENS = _COMMERCIAL_OK_TOKENS  # same set (NC and ND both rejected)


@dataclass
class JamendoResult:
    """Outcome of one batch query."""

    pack_id: str
    query: str
    output_dir: Path
    tracks_matched: int = 0
    tracks_accepted_license: int = 0
    tracks_downloaded: int = 0
    tracks_skipped_restricted: int = 0
    tracks_failed: int = 0
    downloaded_paths: list[Path] = field(default_factory=list)
    manifest_path: Path | None = None
    dry_run: bool = False
    ok: bool = True
    error: str | None = None


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def get_client_id() -> str | None:
    key = os.environ.get(JAMENDO_CLIENT_ID_ENV, "").strip()
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

def is_license_accepted(
    license_ccurl: str,
    *,
    require_commercial: bool = True,
    require_derivative: bool = True,
) -> bool:
    """True if the CC license URL meets the commercial+derivative gates.

    Args:
        license_ccurl: e.g. 'https://creativecommons.org/licenses/by/4.0/'.
        require_commercial: reject -nc variants.
        require_derivative: reject -nd variants.
    """
    if not license_ccurl:
        return False
    norm = license_ccurl.strip().lower()
    if require_commercial and "-nc" in norm:
        return False
    if require_derivative and "-nd" in norm:
        return False
    return any(tok in norm for tok in _COMMERCIAL_OK_TOKENS) or (
        not require_commercial and "creativecommons.org" in norm
    )


def search_jamendo_tracks(
    query: str,
    *,
    client_id: str,
    limit: int = 10,
    timeout: float = 20.0,
) -> list[dict]:
    """Hit /tracks?search=...; return results list."""
    params = {
        "client_id": client_id,
        "format": "json",
        "limit": str(max(1, min(limit, 200))),
        "search": query,
        "include": "licenses+musicinfo",
        "audiodlformat": "mp32",
    }
    url = f"{JAMENDO_API}/tracks?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    return list(payload.get("results", []))


def run_jamendo_tracks_batch(
    *,
    query: str,
    client_id: str | None = None,
    pack_id: str | None = None,
    count: int = 4,
    allow_restrictive: bool = False,
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.5,
    dry_run: bool = False,
) -> JamendoResult:
    """Search Jamendo and download commercial-OK CC tracks.

    Args:
        query: free-text (matches track name, artist, tags).
        client_id: JAMENDO_CLIENT_ID (falls back to env var).
        count: max tracks to download.
        allow_restrictive: when True, accept CC-NC / CC-ND variants too
            (for personal/educational projects). Default False = commercial-safe.
    """
    resolved_pack_id = pack_id or f"JAMENDO_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "jamendo" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = JamendoResult(
        pack_id=resolved_pack_id, query=query, output_dir=out_dir,
        dry_run=dry_run,
    )

    cid = client_id or get_client_id()
    if not cid:
        result.ok = False
        result.error = f"missing_client_id (set ${JAMENDO_CLIENT_ID_ENV})"
        return result

    try:
        tracks = search_jamendo_tracks(query, client_id=cid, limit=min(count * 3, 200))
    except urllib.error.HTTPError as exc:
        result.ok = False
        result.error = f"search_failed: HTTP {exc.code}"
        return result
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.tracks_matched = len(tracks)
    if not tracks:
        result.error = "no_matches"
        return result

    require_commercial = not allow_restrictive
    require_derivative = not allow_restrictive

    manifest_entries: list[dict] = []
    for track in tracks:
        if result.tracks_downloaded >= count:
            break
        if not isinstance(track, dict):
            continue
        license_url = str(track.get("license_ccurl", "") or "")
        if not is_license_accepted(
            license_url,
            require_commercial=require_commercial,
            require_derivative=require_derivative,
        ):
            result.tracks_skipped_restricted += 1
            continue
        result.tracks_accepted_license += 1

        audio_url = str(track.get("audiodownload", "") or "")
        if not audio_url:
            result.tracks_failed += 1
            continue

        track_id = track.get("id", "")
        artist = str(track.get("artist_name", "") or "")
        name = str(track.get("name", "") or "")
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
        safe_name = safe_name.replace(" ", "_")[:60] or f"track_{track_id}"
        dest = out_dir / f"jamendo_{track_id}_{safe_name}.mp3"

        musicinfo = track.get("musicinfo", {}) or {}
        tags_info = musicinfo.get("tags", {}) or {}

        entry = {
            "track_id": track_id,
            "name": name,
            "artist": artist,
            "album": str(track.get("album_name", "") or ""),
            "duration_s": track.get("duration", 0),
            "license_url": license_url,
            "license_accepted": True,
            "tags": {
                "genres": tags_info.get("genres", []) or [],
                "vartags": tags_info.get("vartags", []) or [],
                "instruments": tags_info.get("instruments", []) or [],
            },
            "track_page": str(track.get("shareurl", "") or ""),
            "source_url": audio_url,
            "local_path": str(dest),
            "attribution_required": "by-sa" in license_url.lower() or "by/" in license_url.lower(),
            "attribution_text": f"{artist} - {name} (CC license: {license_url})",
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.tracks_downloaded += 1
            result.downloaded_paths.append(dest)
            continue

        try:
            byte_count = _download_binary(audio_url, dest)
            entry["downloaded"] = True
            entry["bytes"] = byte_count
            result.tracks_downloaded += 1
            result.downloaded_paths.append(dest)
            manifest_entries.append(entry)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            entry["downloaded"] = False
            entry["error"] = str(exc)
            manifest_entries.append(entry)
            result.tracks_failed += 1

        if polite_sleep_s > 0:
            time.sleep(polite_sleep_s)

    manifest = {
        "source": "jamendo",
        "pack_id": resolved_pack_id,
        "query": query,
        "allow_restrictive": allow_restrictive,
        "tracks_matched": result.tracks_matched,
        "tracks_accepted_license": result.tracks_accepted_license,
        "tracks_downloaded": result.tracks_downloaded,
        "tracks_skipped_restricted": result.tracks_skipped_restricted,
        "tracks_failed": result.tracks_failed,
        "license_policy": (
            "CC-BY | CC-BY-SA only (commercial+derivative OK) "
            "UNLESS --allow-restrictive (also accept CC-NC / CC-ND variants)"
        ),
        "license_policy_url": "https://developer.jamendo.com/v3.0/tracks",
        "attribution_note": (
            "CC-BY and CC-BY-SA tracks REQUIRE attribution. "
            "Use the per-entry 'attribution_text' field when crediting in-game."
        ),
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "jamendo_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    return result


__all__ = [
    "JAMENDO_API",
    "JAMENDO_CLIENT_ID_ENV",
    "JamendoResult",
    "get_client_id",
    "is_license_accepted",
    "search_jamendo_tracks",
    "run_jamendo_tracks_batch",
]
