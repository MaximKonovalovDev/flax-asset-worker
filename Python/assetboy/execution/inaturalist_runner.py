"""inaturalist_runner.py — Batch-fetch CC-licensed nature observation photos.

iNaturalist (inaturalist.org) is a citizen-science platform with ~200M+
observations of plants, animals, fungi, etc. Observation photos are
user-uploaded under various Creative Commons licenses (CC0, CC-BY,
CC-BY-NC, CC-BY-SA, all rights reserved).

No API key, no auth. Rate limit: ~60 req/min sustained (be polite).

For commercial game use we filter to CC0 / CC-BY / CC-BY-SA only.
Adding `--allow-restrictive` accepts CC-NC variants.

API endpoint (api.inaturalist.org/v1):
    GET /observations?q=<term>&photos=true&photo_license=<csv>&per_page=<n>
        Returns: {results: [{id, taxon: {name, preferred_common_name},
                              observed_on, place_guess, observation_photos:
                              [{photo: {url, attribution, license_code,
                                        original_dimensions: {height, width}}}]}]}

CLI driver: `assetboy gen inaturalist fetch --query "oak tree" --count 4`

Use cases in FAW:
  - Wildlife reference plates (animals, plants, fungi for survival games)
  - Texture references (bark, fur, leaves)
  - ComfyUI img2img seeds for nature-themed work
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

INATURALIST_API = "https://api.inaturalist.org/v1"
USER_AGENT = "flax-asset-worker/1.13 (CC nature collector; +https://github.com/flax-game-studio)"

# iNaturalist license_code values we accept.
# Format ref: https://www.inaturalist.org/pages/help#cc
_ACCEPTED_LICENSES_DEFAULT = frozenset({"cc0", "cc-by", "cc-by-sa"})
_ACCEPTED_LICENSES_PERMISSIVE = _ACCEPTED_LICENSES_DEFAULT | frozenset({
    "cc-by-nc", "cc-by-nc-sa", "cc-by-nd", "cc-by-nc-nd"
})


@dataclass
class INaturalistResult:
    pack_id: str
    query: str
    output_dir: Path
    observations_matched: int = 0
    observations_with_photo: int = 0
    photos_downloaded: int = 0
    photos_skipped_restricted: int = 0
    photos_failed: int = 0
    downloaded_paths: list[Path] = field(default_factory=list)
    manifest_path: Path | None = None
    dry_run: bool = False
    ok: bool = True
    error: str | None = None


# --------------------------------------------------------------------------- #
# HTTP helpers
# --------------------------------------------------------------------------- #

def _get_json(url: str, *, timeout: float = 20.0) -> dict:
    """v1.13.s84: retries 429/503/502/504 via with_429_retry."""
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

def is_license_accepted(license_code: str, *, allow_restrictive: bool = False) -> bool:
    """True if license_code is in the accepted CC set."""
    if not license_code:
        return False
    norm = license_code.strip().lower()
    if allow_restrictive:
        return norm in _ACCEPTED_LICENSES_PERMISSIVE
    return norm in _ACCEPTED_LICENSES_DEFAULT


def search_inaturalist_observations(
    query: str,
    *,
    per_page: int = 10,
    page: int = 1,
    allow_restrictive: bool = False,
    timeout: float = 20.0,
) -> list[dict]:
    """Hit /observations; return list of observation dicts."""
    licenses = ",".join(sorted(
        _ACCEPTED_LICENSES_PERMISSIVE if allow_restrictive else _ACCEPTED_LICENSES_DEFAULT
    ))
    params = {
        "q": query,
        "photos": "true",
        "photo_license": licenses,
        "per_page": str(max(1, min(per_page, 200))),
        "page": str(page),
    }
    url = f"{INATURALIST_API}/observations?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    return list(payload.get("results", []))


def run_inaturalist_batch(
    *,
    query: str,
    pack_id: str | None = None,
    count: int = 6,
    allow_restrictive: bool = False,
    output_dir: str | Path | None = None,
    polite_sleep_s: float = 0.3,
    dry_run: bool = False,
) -> INaturalistResult:
    """Search iNaturalist observations and download CC-licensed photos.

    Args:
        query: free-text (matches taxon name, common name, description).
        pack_id: pack id for output dir.
        count: max photos to download (one per observation; first photo only).
        allow_restrictive: when True, accept CC-NC variants (personal use only).
        output_dir: override.
        polite_sleep_s: delay between downloads (~60 req/min target).
        dry_run: when True, hit search but skip binary photo downloads.
    """
    resolved_pack_id = pack_id or f"INAT_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "inaturalist" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = INaturalistResult(
        pack_id=resolved_pack_id, query=query, output_dir=out_dir,
        dry_run=dry_run,
    )

    try:
        observations = search_inaturalist_observations(
            query,
            per_page=min(count * 2, 200),
            allow_restrictive=allow_restrictive,
        )
    except urllib.error.HTTPError as exc:
        result.ok = False
        result.error = f"search_failed: HTTP {exc.code}"
        return result
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.observations_matched = len(observations)
    if not observations:
        result.error = "no_matches"
        return result

    manifest_entries: list[dict] = []
    for obs in observations:
        if result.photos_downloaded >= count:
            break
        if not isinstance(obs, dict):
            continue
        photos = obs.get("observation_photos") or []
        if not photos:
            continue
        # First photo only; iNaturalist returns photos sorted by position.
        first = photos[0]
        if not isinstance(first, dict):
            continue
        photo = first.get("photo", {}) or {}
        license_code = str(photo.get("license_code", "") or "")
        if not is_license_accepted(license_code, allow_restrictive=allow_restrictive):
            result.photos_skipped_restricted += 1
            continue
        photo_url = str(photo.get("url", "") or "")
        if not photo_url:
            result.photos_failed += 1
            continue

        result.observations_with_photo += 1

        # iNaturalist URLs end in /<id>/square.jpeg by default; ask for medium.
        # Their convention: replace 'square' with 'medium' or 'original'.
        if "/square." in photo_url:
            photo_url = photo_url.replace("/square.", "/medium.")

        obs_id = obs.get("id", "")
        taxon = obs.get("taxon", {}) or {}
        taxon_name = str(taxon.get("name", "") or "")
        common_name = str(taxon.get("preferred_common_name", "") or "")
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in taxon_name.replace(" ", "_")
        )[:60] or f"obs_{obs_id}"
        url_path = urllib.parse.urlparse(photo_url).path
        suffix = Path(url_path).suffix or ".jpg"
        dest = out_dir / f"inat_{obs_id}_{safe_name}{suffix}"

        entry = {
            "observation_id": obs_id,
            "taxon_name": taxon_name,
            "common_name": common_name,
            "observed_on": str(obs.get("observed_on", "") or ""),
            "place": str(obs.get("place_guess", "") or ""),
            "license_code": license_code,
            "attribution": str(photo.get("attribution", "") or ""),
            "width": (photo.get("original_dimensions") or {}).get("width", 0),
            "height": (photo.get("original_dimensions") or {}).get("height", 0),
            "source_url": photo_url,
            "observation_url": f"https://www.inaturalist.org/observations/{obs_id}",
            "license": f"CC ({license_code.upper()}) — see attribution",
            "local_path": str(dest),
            "attribution_required": license_code.lower() != "cc0",
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.photos_downloaded += 1
            result.downloaded_paths.append(dest)
            continue

        try:
            byte_count = _download_binary(photo_url, dest)
            entry["downloaded"] = True
            entry["bytes"] = byte_count
            result.photos_downloaded += 1
            result.downloaded_paths.append(dest)
            manifest_entries.append(entry)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            entry["downloaded"] = False
            entry["error"] = str(exc)
            manifest_entries.append(entry)
            result.photos_failed += 1

        if polite_sleep_s > 0:
            time.sleep(polite_sleep_s)

    manifest = {
        "source": "inaturalist",
        "pack_id": resolved_pack_id,
        "query": query,
        "allow_restrictive": allow_restrictive,
        "observations_matched": result.observations_matched,
        "observations_with_photo": result.observations_with_photo,
        "photos_downloaded": result.photos_downloaded,
        "photos_skipped_restricted": result.photos_skipped_restricted,
        "photos_failed": result.photos_failed,
        "license_policy": (
            "CC0 | CC-BY | CC-BY-SA only (commercial-safe) UNLESS "
            "--allow-restrictive (then also CC-NC variants for personal use)"
        ),
        "license_policy_url": "https://www.inaturalist.org/pages/help#cc",
        "attribution_note": (
            "CC-BY/SA photos require attribution. Use per-entry "
            "'attribution' field when crediting."
        ),
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "inaturalist_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    return result


__all__ = [
    "INATURALIST_API",
    "INaturalistResult",
    "is_license_accepted",
    "search_inaturalist_observations",
    "run_inaturalist_batch",
]
