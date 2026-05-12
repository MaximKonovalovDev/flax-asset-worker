"""met_museum_runner.py — Batch-fetch CC0 reference images from The Met's Open Access API.

The Metropolitan Museum of Art's Open Access program publishes ~500K+ artworks
as CC0 (public domain). API requires no key, no auth, no rate limit headers
documented (be polite: <80 req/sec per their docs).

Endpoints used:
    GET /public/collection/v1/search?q=<term>&hasImages=true  -> {total, objectIDs[]}
    GET /public/collection/v1/objects/{id}                    -> object metadata
        Key fields: isPublicDomain (bool), primaryImage (URL), primaryImageSmall,
        title, artistDisplayName, objectDate, medium, classification.

CLI driver: `assetboy gen met-museum --query "ancient roman" --count 8`

This runner returns reference images (not 3D models) suitable for:
    - Texture inspiration / mood boards
    - ComfyUI img2img source plates
    - Recipe pack `reference_image_urls` lists for downstream prompt-gen

License gate: we ONLY download objects where isPublicDomain=true. Anything
non-CC0 is skipped with a clear note (Met has some non-OA holdings too).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from assetboy.execution.comfyui_runner import generated_output_root, manual_drop_dir

MET_API_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"
USER_AGENT = "flax-asset-worker/1.10 (CC0 collector; +https://github.com/flax-game-studio)"


@dataclass
class MetMuseumResult:
    """One object's outcome. ok=True when image was saved or skipped-non-PD."""

    pack_id: str
    query: str
    output_dir: Path
    objects_matched: int = 0
    objects_public_domain: int = 0
    objects_downloaded: int = 0
    objects_skipped_non_pd: int = 0
    objects_failed: int = 0
    downloaded_paths: list[Path] = field(default_factory=list)
    manifest_path: Path | None = None
    dry_run: bool = False
    ok: bool = True
    error: str | None = None


# --------------------------------------------------------------------------- #
# Low-level HTTP helpers (stdlib only; no requests dep)
# --------------------------------------------------------------------------- #

def _get_json(url: str, *, timeout: float = 15.0) -> dict:
    """GET a URL, parse JSON. v1.12.s69: retries HTTP 429/503/502/504."""
    from assetboy.execution._http_retry import with_429_retry

    def _do_call() -> dict:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return json.loads(raw)

    return with_429_retry(_do_call, max_retries=3, base_delay_s=1.0, cap_delay_s=30.0)


def _download_binary(url: str, dest: Path, *, timeout: float = 30.0) -> int:
    """GET a URL, write bytes to `dest`. Returns byte count."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def search_met_object_ids(
    query: str,
    *,
    has_images: bool = True,
    department_id: int | None = None,
    timeout: float = 15.0,
) -> list[int]:
    """Hit /search and return the objectIDs list.

    Returns [] when API gives `{total: 0, objectIDs: null}` (common for narrow queries).
    """
    params = {"q": query}
    if has_images:
        params["hasImages"] = "true"
    if department_id is not None:
        params["departmentId"] = str(department_id)
    url = f"{MET_API_BASE}/search?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, timeout=timeout)
    ids = payload.get("objectIDs")
    if not ids:
        return []
    return list(ids)


def fetch_met_object(object_id: int, *, timeout: float = 15.0) -> dict:
    """Hit /objects/{id} and return the full metadata dict."""
    url = f"{MET_API_BASE}/objects/{object_id}"
    return _get_json(url, timeout=timeout)


def list_met_departments(*, timeout: float = 15.0) -> list[dict]:
    """v1.23.s158 — list Met departments via /departments.

    Returns: list of {departmentId, displayName} dicts (Met's native shape).
    """
    url = f"{MET_API_BASE}/departments"
    payload = _get_json(url, timeout=timeout)
    return list(payload.get("departments", []))


def run_met_museum_batch(
    *,
    query: str,
    pack_id: str | None = None,
    count: int = 6,
    department_id: int | None = None,
    output_dir: str | Path | None = None,
    use_small_image: bool = False,
    polite_sleep_s: float = 0.2,
    dry_run: bool = False,
) -> MetMuseumResult:
    """Search The Met for `query`, download up to `count` public-domain primary images.

    Args:
        query: free-text search term (matches title, artist, medium, etc).
        pack_id: pack identifier for output path; defaults to derived slug.
        count: maximum number of OBJECTS to fetch (after PD filter).
        department_id: optional Met department filter (e.g. 13 = Greek/Roman Art).
        output_dir: override output directory; default <manual_drop>/met_museum/<pack_id>/.
        use_small_image: if True, fetch primaryImageSmall (faster); else primaryImage.
        polite_sleep_s: sleep between per-object API calls (default 200ms).
        dry_run: when True, plan only — no HTTP fetches of images, but search IS hit.

    Returns:
        MetMuseumResult with download counts + per-asset paths + manifest path.
    """
    resolved_pack_id = pack_id or f"MET_{query.replace(' ', '_').upper()}"
    out_dir = (
        Path(output_dir) if output_dir
        else manual_drop_dir() / "met_museum" / resolved_pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = MetMuseumResult(
        pack_id=resolved_pack_id,
        query=query,
        output_dir=out_dir,
        dry_run=dry_run,
    )

    # Step 1: search.
    try:
        object_ids = search_met_object_ids(
            query, has_images=True, department_id=department_id
        )
    except (urllib.error.URLError, ValueError, TimeoutError) as exc:
        result.ok = False
        result.error = f"search_failed: {exc}"
        return result

    result.objects_matched = len(object_ids)

    if not object_ids:
        # Empty result is "ok" — we just have nothing to download.
        result.error = "no_matches"
        result.ok = True
        return result

    # Step 2: walk objects until we have `count` PD images (or exhaust list).
    manifest_entries: list[dict] = []
    for obj_id in object_ids:
        if result.objects_downloaded >= count:
            break
        try:
            obj = fetch_met_object(obj_id)
        except (urllib.error.URLError, ValueError, TimeoutError):
            result.objects_failed += 1
            continue

        is_pd = bool(obj.get("isPublicDomain"))
        if not is_pd:
            result.objects_skipped_non_pd += 1
            continue
        result.objects_public_domain += 1

        image_url = (
            obj.get("primaryImageSmall") if use_small_image else obj.get("primaryImage")
        )
        if not image_url:
            # PD object but no usable image URL.
            result.objects_failed += 1
            continue

        # Construct destination filename from URL last segment.
        url_path = urllib.parse.urlparse(image_url).path
        filename = Path(url_path).name or f"met_{obj_id}.jpg"
        dest = out_dir / f"met_{obj_id}_{filename}"

        entry = {
            "object_id": obj_id,
            "title": obj.get("title", ""),
            "artist": obj.get("artistDisplayName", ""),
            "date": obj.get("objectDate", ""),
            "medium": obj.get("medium", ""),
            "classification": obj.get("classification", ""),
            "department": obj.get("department", ""),
            "is_public_domain": True,
            "license": "CC0",
            "source_url": image_url,
            "object_page": obj.get("objectURL", ""),
            "local_path": str(dest),
        }

        if dry_run:
            entry["downloaded"] = False
            manifest_entries.append(entry)
            result.objects_downloaded += 1  # counted as "would download"
            result.downloaded_paths.append(dest)
            continue

        try:
            byte_count = _download_binary(image_url, dest)
            entry["downloaded"] = True
            entry["bytes"] = byte_count
            result.objects_downloaded += 1
            result.downloaded_paths.append(dest)
            manifest_entries.append(entry)
        except (urllib.error.URLError, ValueError, TimeoutError) as exc:
            entry["downloaded"] = False
            entry["error"] = str(exc)
            manifest_entries.append(entry)
            result.objects_failed += 1

        if polite_sleep_s > 0:
            from assetboy.execution._http_retry import get_polite_sleep_s
            time.sleep(get_polite_sleep_s(polite_sleep_s))

    # Step 3: write manifest.
    manifest = {
        "source": "met_museum",
        "pack_id": resolved_pack_id,
        "query": query,
        "department_id": department_id,
        "objects_matched": result.objects_matched,
        "objects_downloaded": result.objects_downloaded,
        "objects_skipped_non_pd": result.objects_skipped_non_pd,
        "objects_failed": result.objects_failed,
        "license": "CC0 (Met Open Access)",
        "license_url": "https://www.metmuseum.org/about-the-met/policies-and-documents/image-resources",
        "dry_run": dry_run,
        "entries": manifest_entries,
    }
    manifest_path = out_dir / "met_museum_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    result.manifest_path = manifest_path

    if result.objects_downloaded == 0 and result.objects_matched > 0:
        result.ok = True  # search worked, just nothing PD in first slice
        if not result.error:
            result.error = "no_public_domain_images_in_first_slice"

    return result


__all__ = [
    "MET_API_BASE",
    "MetMuseumResult",
    "search_met_object_ids",
    "fetch_met_object",
    "list_met_departments",
    "run_met_museum_batch",
]
