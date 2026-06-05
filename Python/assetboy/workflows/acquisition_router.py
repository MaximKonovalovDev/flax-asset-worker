"""Pre-pack acquisition router (Path B s11, 2026-05-11).

Maps a recipe pack to a ``source_dir`` BEFORE ``pack_pipeline`` runs.

Recipe schema (per ``recipes/<game>/<recipe>.yaml``):

    packs:
      - id: <PACK_ID>
        acquisition_method: direct_url | manual_browser | generator
        provider: polyhaven | kenney | ambientcg | freesound | fab | unity | epic | mixamo | stable_audio_open_small | comfyui
        assets: [...]               # for direct_url
        search_terms: [...]         # for freesound / search-based providers
        prompts: [...]              # for generator method

The router has THREE lanes:

1. **direct_url** — call the provider's downloader runner (polyhaven_runner,
   kenney_runner, ambientcg_runner, freesound_runner). Real network I/O.
   Returns the staging dir the runner wrote files into.

2. **manual_browser** — emit a wait-marker file at the expected source_dir.
   Operator drops files there (manually or via @playwright/mcp), then re-runs
   ``pack from-recipe --resume`` and the next pass succeeds.

3. **generator** — route to comfyui_runner / local_image_runner / stable
   audio. Returns the generated-output dir. Currently dry-run only (the
   real generation hooks land in s11.1).

Returns a Path to the source_dir, or raises if the method/provider is
unknown or the operator hasn't completed the manual step yet.

Used by ``cli/pack.py:from_recipe_cmd`` between recipe-parse and
``execute_prepare_pack_dispatched`` invocation.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assetboy.library.paths import asset_library_root, manual_drop_dir


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #

@dataclass
class AcquisitionResult:
    """Outcome of a single pack acquisition attempt."""

    ok: bool
    source_dir: Path | None = None
    method: str = ""
    provider: str = ""
    notes: str = ""
    error: str = ""
    awaiting_manual: bool = False


class AcquisitionError(Exception):
    """Raised when an acquisition attempt fails in a way the caller should
    surface to the operator (e.g. unsupported method, dead provider)."""


# --------------------------------------------------------------------------- #
# Shared error wrappers (Phase 3M: extracted from per-driver duplication)
# --------------------------------------------------------------------------- #

def _import_runner(module_name: str) -> tuple[Any, AcquisitionResult | None]:
    """Import a runner module. Returns (module, None) or (None, error)."""
    try:
        return importlib.import_module(f"assetboy.execution.{module_name}"), None
    except ImportError as exc:
        return None, AcquisitionResult(ok=False, error=f"import_failed: {exc}")


def _run_batch(fn, **kwargs) -> tuple[Any, AcquisitionResult | None]:
    """Call a runner function. Returns (result, None) or (None, error)."""
    try:
        return fn(**kwargs), None
    except Exception as exc:
        return None, AcquisitionResult(ok=False, error=f"runner_crashed: {exc}")


# --------------------------------------------------------------------------- #
# Generic driver dispatch (Phase 3M: consolidated 11 simple _drive_* functions)
# --------------------------------------------------------------------------- #

_DRIVERS: dict[str, tuple[str, str, int, dict[str, Any]]] = {
    # (module_name, fn_name, default_count, extra_kwargs)
    "met_museum":       ("met_museum_runner",  "run_met_museum_batch",  4, {}),
    "met-museum":       ("met_museum_runner",  "run_met_museum_batch",  4, {}),
    "wikimedia":        ("wikimedia_runner",   "run_wikimedia_batch",   6, {}),
    "wikimedia_commons":("wikimedia_runner",   "run_wikimedia_batch",   6, {}),
    "archive_org":      ("archive_org_runner", "run_archive_org_batch", 4, {}),
    "archive-org":      ("archive_org_runner", "run_archive_org_batch", 4, {}),
    "archiveorg":       ("archive_org_runner", "run_archive_org_batch", 4, {}),
    "scryfall":         ("scryfall_runner",    "run_scryfall_batch",    6, {}),
    "iconify":          ("iconify_runner",     "run_iconify_batch",    16, {}),
    "pexels":           ("pexels_runner",      "run_pexels_photo_batch", 4, {}),
    "pexels_photos":    ("pexels_runner",      "run_pexels_photo_batch", 4, {}),
    "pexels_videos":    ("pexels_runner",      "run_pexels_video_batch", 2, {}),
    "pixabay":          ("pixabay_runner",     "run_pixabay_photo_batch", 4, {}),
    "pixabay_photos":   ("pixabay_runner",     "run_pixabay_photo_batch", 4, {}),
    "pixabay_videos":   ("pixabay_runner",     "run_pixabay_video_batch", 2, {}),
    "unsplash":         ("unsplash_runner",    "run_unsplash_photo_batch", 4, {}),
    "rawg":             ("rawg_runner",        "run_rawg_games_batch",    4, {}),
    "jamendo":          ("jamendo_runner",     "run_jamendo_tracks_batch", 3, {}),
    "inaturalist":      ("inaturalist_runner", "run_inaturalist_batch",   4, {}),
    "inat":             ("inaturalist_runner", "run_inaturalist_batch",   4, {}),
}


def _drive_generic(
    pack: dict[str, Any], *, pack_id: str, out_dir: Path, provider: str,
) -> AcquisitionResult:
    """Generic driver for simple providers that follow the
    query/count/output_dir pattern.

    Each entry in ``_DRIVERS`` maps provider → (module_name, fn_name, default_count, {}).
    Per-provider extra kwargs that depend on the pack dict are built inline here.
    """
    entry = _DRIVERS.get(provider)
    if entry is None:
        return AcquisitionResult(
            ok=False, method="direct_url", provider=provider,
            error=f"unsupported_provider: {provider!r}",
        )
    module_name, fn_name, default_count, _extra = entry

    mod, err = _import_runner(module_name)
    if err:
        return AcquisitionResult(
            ok=False, method="direct_url", provider=provider,
            error=err.error,
        )

    fn = getattr(mod, fn_name)
    query = _pack_search_query(pack)
    count = _pack_count(pack, default=default_count)

    # Build per-provider kwargs (the small variations between providers)
    kwargs: dict[str, Any] = {
        "query": query,
        "pack_id": pack_id,
        "count": count,
        "output_dir": out_dir,
    }

    if provider in ("pexels", "pexels_photos", "pexels_videos"):
        kwargs["max_height"] = int(pack.get("pexels_max_height", 1080) or 1080)
        if "video" in fn_name:
            pass  # pexels_video_batch takes same query/count/output_dir
        else:
            kwargs["variant"] = str(pack.get("pexels_variant", "large"))
    elif provider in ("pixabay", "pixabay_photos", "pixabay_videos"):
        if "video" in fn_name:
            kwargs["variant"] = str(pack.get("pixabay_variant", "medium"))
        else:
            kwargs["image_type"] = str(pack.get("pixabay_image_type", "photo"))
            kwargs["variant"] = str(pack.get("pixabay_variant", "largeImageURL"))
    elif provider == "unsplash":
        orientation = pack.get("unsplash_orientation")
        kwargs["variant"] = str(pack.get("unsplash_variant", "regular"))
        if orientation:
            kwargs["orientation"] = str(orientation).lower()
    elif provider == "rawg":
        kwargs["genres"] = pack.get("rawg_genres")
        kwargs["max_screenshots_per_game"] = int(pack.get("rawg_max_screenshots", 3) or 3)
        kwargs["include_screenshots"] = bool(pack.get("rawg_include_screenshots", True))
    elif provider == "jamendo":
        kwargs["allow_restrictive"] = bool(pack.get("jamendo_allow_restrictive", False))
    elif provider == "inaturalist" or provider == "inat":
        kwargs["allow_restrictive"] = bool(pack.get("inaturalist_allow_restrictive", False))
    elif provider in ("met_museum", "met-museum"):
        department = pack.get("met_department_id")
        if department is not None:
            kwargs["department_id"] = int(department)
    elif provider in ("archive_org", "archive-org", "archiveorg"):
        mediatype = pack.get("archive_mediatype") or pack.get("mediatype")
        if mediatype:
            kwargs["mediatype"] = str(mediatype).lower()
    elif provider == "scryfall":
        kwargs["variant"] = str(pack.get("scryfall_variant", "art_crop")).strip().lower()
    elif provider == "iconify":
        kwargs["width"] = int(pack.get("iconify_width", 64) or 64)
        color = pack.get("iconify_color")
        if color:
            kwargs["color"] = str(color)

    result, err = _run_batch(fn, **kwargs)
    if err:
        return AcquisitionResult(
            ok=False, method="direct_url", provider=provider,
            error=err.error,
        )

    # Build a descriptive notes string from the result
    notes = _build_notes(provider, fn_name, result)
    return AcquisitionResult(
        ok=result.ok, method="direct_url", provider=provider,
        source_dir=out_dir, notes=notes,
        error=result.error if not result.ok else None,
    )


def _build_notes(provider: str, fn_name: str, result) -> str:
    """Extract a human-readable notes string from a runner result."""
    m = getattr(result, "items_matched", None)
    d = getattr(result, "items_downloaded", None)
    if provider == "pexels":
        kind = "video" if "video" in fn_name else "photo"
        return f"pexels_{kind}: matched={m} downloaded={d}"
    if provider == "pixabay":
        kind = "video" if "video" in fn_name else "photo"
        return f"pixabay_{kind}: matched={m} downloaded={d}"
    if provider == "unsplash":
        return (
            f"unsplash: matched={getattr(result, 'photos_matched', m)} "
            f"downloaded={getattr(result, 'photos_downloaded', d)} "
            f"pings={getattr(result, 'download_pings', 0)}"
        )
    if provider == "rawg":
        return (
            f"rawg: matched={getattr(result, 'games_matched', m)} "
            f"covers={getattr(result, 'games_downloaded', d)} "
            f"screenshots={getattr(result, 'screenshots_downloaded', 0)} (REFERENCE-ONLY)"
        )
    if provider == "jamendo":
        return (
            f"jamendo: matched={getattr(result, 'tracks_matched', m)} "
            f"downloaded={getattr(result, 'tracks_downloaded', d)} "
            f"skipped_restricted={getattr(result, 'tracks_skipped_restricted', 0)}"
        )
    if provider in ("inaturalist", "inat"):
        return (
            f"inaturalist: matched={getattr(result, 'observations_matched', m)} "
            f"downloaded={getattr(result, 'photos_downloaded', d)} "
            f"skipped_restricted={getattr(result, 'photos_skipped_restricted', 0)}"
        )
    if provider in ("met_museum", "met-museum"):
        return (
            f"met_museum: matched={getattr(result, 'objects_matched', m)} "
            f"downloaded={getattr(result, 'objects_downloaded', d)} "
            f"skipped_non_pd={getattr(result, 'objects_skipped_non_pd', 0)}"
        )
    if provider in ("wikimedia", "wikimedia_commons"):
        return (
            f"wikimedia: matched={getattr(result, 'files_matched', m)} "
            f"downloaded={getattr(result, 'files_downloaded', d)} "
            f"skipped_restricted={getattr(result, 'files_skipped_restricted', 0)}"
        )
    if provider in ("archive_org", "archive-org", "archiveorg"):
        return (
            f"archive_org: matched={getattr(result, 'items_matched', m)} "
            f"downloaded={getattr(result, 'items_downloaded', d)} "
            f"skipped_restricted={getattr(result, 'items_skipped_restricted', 0)}"
        )
    if provider == "scryfall":
        return (
            f"scryfall: matched={getattr(result, 'cards_matched', m)} "
            f"downloaded={getattr(result, 'cards_downloaded', d)} "
            f"variant={getattr(result, 'variant', '')}"
        )
    if provider == "iconify":
        return (
            f"iconify: matched={getattr(result, 'icons_matched', m)} "
            f"downloaded={getattr(result, 'icons_downloaded', d)} "
            f"skipped_restricted={getattr(result, 'icons_skipped_restricted', 0)}"
        )
    return f"{provider}: matched={m} downloaded={d}"


# --------------------------------------------------------------------------- #
# Method dispatch
# --------------------------------------------------------------------------- #

SUPPORTED_METHODS = {"direct_url", "manual_browser", "generator"}


def acquire_source_dir(
    pack: dict[str, Any],
    recipe: dict[str, Any],
    *,
    dry_run: bool = False,
) -> AcquisitionResult:
    """Map a recipe pack to a source_dir before pack_pipeline runs.

    Args:
        pack:    the pack dict from recipe["packs"]
        recipe:  the full recipe doc (for game_scope / output_folder context)
        dry_run: if True, emit plan only; no network/filesystem writes

    Returns:
        AcquisitionResult with .ok + .source_dir (or .error / .awaiting_manual)
    """
    pack_id = str(pack.get("id", "?"))
    method = str(pack.get("acquisition_method", "")).strip().lower()
    provider = str(pack.get("provider", "")).strip().lower()

    if method not in SUPPORTED_METHODS:
        return AcquisitionResult(
            ok=False,
            method=method,
            provider=provider,
            error=f"unknown_method: {method!r} (expected one of: {sorted(SUPPORTED_METHODS)})",
        )

    if method == "direct_url":
        return _acquire_direct_url(pack, recipe, pack_id=pack_id, provider=provider, dry_run=dry_run)

    if method == "manual_browser":
        return _acquire_manual_browser(pack, recipe, pack_id=pack_id, provider=provider, dry_run=dry_run)

    if method == "generator":
        return _acquire_generator(pack, recipe, pack_id=pack_id, provider=provider, dry_run=dry_run)

    return AcquisitionResult(ok=False, method=method, provider=provider, error="unreachable")


# --------------------------------------------------------------------------- #
# direct_url lane
# --------------------------------------------------------------------------- #

def _acquire_direct_url(
    pack: dict[str, Any],
    recipe: dict[str, Any],
    *,
    pack_id: str,
    provider: str,
    dry_run: bool,
) -> AcquisitionResult:
    """Drive a downloader runner for CC0/direct providers.

    Today wires four real C# / Python providers: polyhaven, kenney,
    ambientcg, freesound. For any other provider id, returns a clean
    "unsupported_provider" error so the recipe author can adjust the
    method or wait for an adapter to ship.
    """
    # Phase 3M: simple providers (met_museum, wikimedia, archive_org,
    # scryfall, iconify, pexels, pixabay, unsplash, rawg, jamendo,
    # inaturalist) are handled by _drive_generic. The remaining 5
    # complex providers (polyhaven, kenney, ambientcg, freesound,
    # quaternius) have custom iteration/param logic and stay explicit.
    game_scope = str((recipe.get("recipe") or {}).get("game", "unknown"))
    try:
        out_dir = _resolve_source_staging_dir(pack_id, game_scope, lane="direct_url", dry_run=dry_run)
    except FileNotFoundError as exc:
        return AcquisitionResult(
            ok=False, method="direct_url", provider=provider,
            error=f"workspace_not_configured: {exc}",
        )

    if dry_run:
        return AcquisitionResult(
            ok=True,
            method="direct_url",
            provider=provider,
            source_dir=out_dir,
            notes=f"dry_run: would invoke {provider} runner -> {out_dir}",
        )

    if provider in _DRIVERS:
        return _drive_generic(pack, pack_id=pack_id, out_dir=out_dir, provider=provider)

    if provider == "polyhaven":
        return _drive_polyhaven(pack, pack_id=pack_id, out_dir=out_dir)
    if provider == "kenney":
        return _drive_kenney(pack, pack_id=pack_id, out_dir=out_dir)
    if provider == "ambientcg":
        return _drive_ambientcg(pack, pack_id=pack_id, out_dir=out_dir)
    if provider == "freesound":
        return _drive_freesound(pack, pack_id=pack_id, out_dir=out_dir)
    if provider == "quaternius":
        return _drive_quaternius(pack, pack_id=pack_id, out_dir=out_dir)

    return AcquisitionResult(
        ok=False,
        method="direct_url",
        provider=provider,
        error=(
            f"unsupported_provider: {provider!r}. "
            "direct_url lane supports: polyhaven, kenney, ambientcg, freesound, "
            "quaternius, met_museum, wikimedia, archive_org, scryfall, iconify, "
            "pexels[_photos|_videos], pixabay[_photos|_videos], unsplash, "
            "rawg, jamendo, inaturalist. For others, set acquisition_method: "
            "manual_browser or generator."
        ),
    )


# --------------------------------------------------------------------------- #
# Complex direct_url provider drivers
# (kept explicit because of custom iteration / param logic)
# --------------------------------------------------------------------------- #

def _pack_search_query(pack: dict[str, Any]) -> str:
    """Extract search query string from a pack.

    Priority: search_terms[0] -> assets[0].asset_id (or asset[0] str) -> pack id.
    """
    terms = pack.get("search_terms") or []
    if terms and isinstance(terms, list):
        first = terms[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
        if isinstance(first, dict) and first.get("term"):
            return str(first["term"]).strip()
    assets = pack.get("assets") or []
    if assets:
        a0 = assets[0]
        if isinstance(a0, dict):
            v = a0.get("asset_id") or a0.get("query") or a0.get("name")
            if v:
                return str(v).strip()
        elif isinstance(a0, str):
            return a0.strip()
    return str(pack.get("id", "untitled")).replace("_", " ")


def _pack_count(pack: dict[str, Any], default: int = 4) -> int:
    """Determine target count for a pack.

    Priority: pack['count'] -> len(pack['assets']) -> default.
    """
    c = pack.get("count")
    if isinstance(c, int) and c > 0:
        return c
    assets = pack.get("assets") or []
    if assets:
        return len(assets)
    return default


def _drive_polyhaven(pack: dict[str, Any], *, pack_id: str, out_dir: Path) -> AcquisitionResult:
    """Drive polyhaven_runner with the pack's asset list.

    polyhaven_runner expects a single ``search`` query (string), not a list,
    so we iterate the pack's assets and call once per asset_id.
    """
    mod, err = _import_runner("polyhaven_runner")
    if err:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="polyhaven", error=err.error,
        )
    run_polyhaven_batch = getattr(mod, "run_polyhaven_batch")

    assets = pack.get("assets") or []
    asset_ids = [a.get("asset_id") if isinstance(a, dict) else str(a) for a in assets]
    asset_ids = [a for a in asset_ids if a]
    if not asset_ids:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="polyhaven",
            error="no_assets_in_pack",
        )
    explicit_category = str(pack.get("polyhaven_category", "")).strip().lower()
    if explicit_category in ("textures", "models", "hdris"):
        category = explicit_category
    else:
        category = "textures"
        asset_kind = str(pack.get("asset_kind", "")).lower()
        if asset_kind in ("skybox", "hdr", "hdri"):
            category = "hdris"
        elif asset_kind in ("model", "prop_static", "foliage"):
            category = "models"
    try:
        for asset_id in asset_ids:
            run_polyhaven_batch(
                category=category,
                search=str(asset_id),
                pack_id=pack_id,
                count=1,
                output_dir=out_dir,
            )
    except Exception as exc:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="polyhaven",
            error=f"runner_failed: {exc}",
        )
    return AcquisitionResult(
        ok=True, method="direct_url", provider="polyhaven",
        source_dir=out_dir,
        notes=f"polyhaven downloaded {len(asset_ids)} asset(s) ({category}) -> {out_dir}",
    )


def _drive_kenney(pack: dict[str, Any], *, pack_id: str, out_dir: Path) -> AcquisitionResult:
    """Drive kenney_runner. Each Kenney asset is a ZIP URL; the runner takes
    one ``source_url`` per call. Iterate the pack's assets."""
    mod, err = _import_runner("kenney_runner")
    if err:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="kenney", error=err.error,
        )
    run_kenney_batch = getattr(mod, "run_kenney_batch")

    assets = pack.get("assets") or []
    if not assets:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="kenney",
            error="no_assets_in_pack",
        )
    downloaded = 0
    try:
        for asset in assets:
            if isinstance(asset, dict):
                url = asset.get("source_url") or asset.get("zip_url")
                aid = asset.get("asset_id", "unknown")
            else:
                url = None
                aid = str(asset)
            if not url:
                return AcquisitionResult(
                    ok=False, method="direct_url", provider="kenney",
                    error=f"kenney_asset_missing_source_url: {aid} "
                          "(add source_url field to each asset in recipe)",
                )
            run_kenney_batch(pack_id=pack_id, source_url=url, output_dir=out_dir)
            downloaded += 1
    except Exception as exc:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="kenney",
            error=f"runner_failed: {exc}",
        )
    return AcquisitionResult(
        ok=True, method="direct_url", provider="kenney",
        source_dir=out_dir,
        notes=f"kenney downloaded {downloaded} ZIP(s) -> {out_dir}",
    )


def _drive_ambientcg(pack: dict[str, Any], *, pack_id: str, out_dir: Path) -> AcquisitionResult:
    """Drive ambientcg_runner. Takes the full asset_id list in one call."""
    mod, err = _import_runner("ambientcg_runner")
    if err:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="ambientcg", error=err.error,
        )
    run_ambientcg_pack = getattr(mod, "run_ambientcg_pack")

    assets = pack.get("assets") or []
    asset_ids = [a.get("asset_id") if isinstance(a, dict) else str(a) for a in assets]
    asset_ids = [a for a in asset_ids if a]
    if not asset_ids:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="ambientcg",
            error="no_assets_in_pack",
        )
    description = pack.get("description") or pack_id
    resolution = str(
        (pack.get("flax_import") or {}).get("resolution_default", 2048)
    )
    if resolution in ("1024", "1k", "1K"):
        resolution = "1K"
    elif resolution in ("2048", "2k", "2K"):
        resolution = "2K"
    elif resolution in ("4096", "4k", "4K"):
        resolution = "4K"
    else:
        resolution = "2K"
    try:
        run_ambientcg_pack(
            pack_id=pack_id,
            description=str(description),
            asset_ids=asset_ids,
            resolution=resolution,
            output_dir=out_dir,
        )
    except Exception as exc:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="ambientcg",
            error=f"runner_failed: {exc}",
        )
    return AcquisitionResult(
        ok=True, method="direct_url", provider="ambientcg",
        source_dir=out_dir,
        notes=f"ambientcg downloaded {len(asset_ids)} asset(s) @ {resolution} -> {out_dir}",
    )


def _drive_freesound(pack: dict[str, Any], *, pack_id: str, out_dir: Path) -> AcquisitionResult:
    """Drive freesound_runner with search terms."""
    mod, err = _import_runner("freesound_runner")
    if err:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="freesound", error=err.error,
        )
    run_freesound_batch = getattr(mod, "run_freesound_batch")

    search_terms = pack.get("search_terms") or []
    if not search_terms:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="freesound",
            error="no_search_terms_in_pack",
        )
    try:
        for term in search_terms:
            run_freesound_batch(
                search=term, count=3, pack_id=pack_id,
                output_dir=out_dir, execute=False, dry_run=False,
            )
    except Exception as exc:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="freesound",
            error=f"runner_failed: {exc}",
        )
    return AcquisitionResult(
        ok=True, method="direct_url", provider="freesound",
        source_dir=out_dir,
        notes=f"freesound spec emitted for {len(search_terms)} search term(s) -> {out_dir}",
    )


def _drive_quaternius(pack: dict[str, Any], *, pack_id: str, out_dir: Path) -> AcquisitionResult:
    """Drive quaternius_runner (Path B v1.7.s15).

    Each pack's assets[] entry can specify either:
      - {asset_id: "...", source_url: "https://..."}  - explicit zip URL
      - {asset_id: "nature-kit"}                       - slug (resolved to QUATERNIUS_BASE + .zip)
    Pack with no assets[] but matching a known preset (by pack_id) auto-resolves.
    """
    mod, err = _import_runner("quaternius_runner")
    if err:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="quaternius", error=err.error,
        )
    QUATERNIUS_PRESETS = getattr(mod, "QUATERNIUS_PRESETS", [])
    run_quaternius_batch = getattr(mod, "run_quaternius_batch")

    assets = pack.get("assets") or []
    downloaded = 0
    last_error: str | None = None

    if not assets:
        preset_match = next(
            (p for p in QUATERNIUS_PRESETS if p[0] == pack_id),
            None,
        )
        if preset_match:
            assets = [{"asset_id": preset_match[1]}]
        else:
            return AcquisitionResult(
                ok=False, method="direct_url", provider="quaternius",
                error=(
                    f"no_assets_in_pack: provide assets[] with asset_id "
                    f"(slug or URL) OR use a known preset pack_id "
                    f"(known: {[p[0] for p in QUATERNIUS_PRESETS]})"
                ),
            )

    try:
        for asset in assets:
            if isinstance(asset, dict):
                source_url = asset.get("source_url", "") or asset.get("asset_id", "")
            else:
                source_url = str(asset)
            result = run_quaternius_batch(
                pack_id=pack_id,
                source_url=source_url,
                output_dir=out_dir,
            )
            if result.error:
                last_error = result.error
                continue
            downloaded += 1
    except Exception as exc:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="quaternius",
            error=f"runner_crashed: {exc}",
        )

    if downloaded == 0:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="quaternius",
            error=f"all_assets_failed: last_error={last_error}",
        )

    return AcquisitionResult(
        ok=True, method="direct_url", provider="quaternius",
        source_dir=out_dir,
        notes=(
            f"quaternius downloaded {downloaded}/{len(assets)} asset(s) -> {out_dir}"
            + (f"; last_warning={last_error}" if last_error else "")
        ),
    )


# --------------------------------------------------------------------------- #
# manual_browser lane
# --------------------------------------------------------------------------- #

def _acquire_manual_browser(
    pack: dict[str, Any],
    recipe: dict[str, Any],
    *,
    pack_id: str,
    provider: str,
    dry_run: bool,
) -> AcquisitionResult:
    """Emit a wait-marker file describing what the operator must drop.

    Returns ``awaiting_manual=True`` (ok=False) if the marker is fresh
    (operator hasn't dropped files yet). Returns ``ok=True`` if the
    marker exists AND the drop folder has files.
    """
    game_scope = str((recipe.get("recipe") or {}).get("game", "unknown"))
    try:
        drop_dir = manual_drop_dir() / game_scope / pack_id
    except FileNotFoundError:
        if dry_run:
            import tempfile
            drop_dir = (
                Path(tempfile.gettempdir())
                / "assetboy_dry_run"
                / "manual_drop"
                / game_scope
                / pack_id
            )
        else:
            return AcquisitionResult(
                ok=False, method="manual_browser", provider=provider,
                error="workspace_not_configured (set ASSETBOY_FLAX_REPO_ROOT or create assetboy.workspace.json)",
            )
    marker_path = drop_dir / ".manual_browser_wait.json"

    if dry_run:
        return AcquisitionResult(
            ok=True, method="manual_browser", provider=provider,
            source_dir=drop_dir,
            notes=f"dry_run: would emit wait-marker at {marker_path}",
        )

    drop_dir.mkdir(parents=True, exist_ok=True)

    existing_files = [
        p for p in drop_dir.iterdir()
        if p.is_file() and not p.name.startswith(".")
    ]
    if existing_files:
        return AcquisitionResult(
            ok=True, method="manual_browser", provider=provider,
            source_dir=drop_dir,
            notes=f"manual drop complete: {len(existing_files)} file(s) in {drop_dir}",
        )

    marker_payload = {
        "pack_id": pack_id,
        "provider": provider,
        "method": "manual_browser",
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_url": pack.get("source_url", ""),
        "assets": pack.get("assets", []),
        "search_terms": pack.get("search_terms", []),
        "license_kind": (pack.get("license") or {}).get("kind", ""),
        "operator_instructions": [
            f"1. Open {pack.get('source_url') or '<provider site>'} in your browser.",
            f"2. Sign in to {provider} if needed.",
            f"3. Download the asset(s) listed in 'assets' / 'search_terms' above.",
            f"4. Drop the files into: {drop_dir}",
            f"5. Re-run: python -m assetboy.cli pack from-recipe <recipe> --resume",
        ],
    }
    marker_path.write_text(json.dumps(marker_payload, indent=2), encoding="utf-8")

    return AcquisitionResult(
        ok=False,
        method="manual_browser", provider=provider,
        source_dir=drop_dir,
        awaiting_manual=True,
        notes=f"wait_marker_emitted -> drop files into {drop_dir} then re-run with --resume",
    )


# --------------------------------------------------------------------------- #
# generator lane
# --------------------------------------------------------------------------- #

def _acquire_generator(
    pack: dict[str, Any],
    recipe: dict[str, Any],
    *,
    pack_id: str,
    provider: str,
    dry_run: bool,
) -> AcquisitionResult:
    """Route to comfyui_runner / local_image_runner / stable audio.

    s11 ships dry-run + ComfyUI workflow path. local_image (sd.cpp) +
    Stable Audio Open Small are stubbed for s11.1.
    """
    game_scope = str((recipe.get("recipe") or {}).get("game", "unknown"))
    try:
        out_dir = _resolve_source_staging_dir(pack_id, game_scope, lane="generator", dry_run=dry_run)
    except FileNotFoundError as exc:
        return AcquisitionResult(
            ok=False, method="generator", provider=provider,
            error=f"workspace_not_configured: {exc}",
        )

    if dry_run:
        return AcquisitionResult(
            ok=True, method="generator", provider=provider,
            source_dir=out_dir,
            notes=f"dry_run: would route generation to {provider} -> {out_dir}",
        )

    if provider == "comfyui":
        return _drive_comfyui(pack, pack_id=pack_id, out_dir=out_dir)

    if provider in ("local_image", "sd.cpp"):
        return _drive_local_image(pack, pack_id=pack_id, out_dir=out_dir)

    if provider in ("stable_audio_open_small", "stable_audio"):
        return _drive_stable_audio(pack, pack_id=pack_id, out_dir=out_dir)

    return AcquisitionResult(
        ok=False, method="generator", provider=provider,
        error=f"unsupported_generator_provider: {provider}",
    )


# --------------------------------------------------------------------------- #
# Generator drivers
# --------------------------------------------------------------------------- #

def _drive_comfyui(pack: dict[str, Any], *, pack_id: str, out_dir: Path) -> AcquisitionResult:
    """Drive comfyui_runner.run_comfyui_batch with the pack's prompts."""
    mod, err = _import_runner("comfyui_runner")
    if err:
        return AcquisitionResult(
            ok=False, method="generator", provider="comfyui", error=err.error,
        )
    is_comfyui_running = getattr(mod, "is_comfyui_running")
    run_comfyui_batch = getattr(mod, "run_comfyui_batch")

    if not is_comfyui_running():
        return AcquisitionResult(
            ok=False, method="generator", provider="comfyui",
            error="comfyui_not_running (start ComfyUI on :8188 then re-run)",
        )

    prompts = pack.get("prompts") or []
    if not prompts:
        return AcquisitionResult(
            ok=False, method="generator", provider="comfyui",
            error="no_prompts_in_pack (add prompts: [...] to the recipe pack)",
        )

    asset_kind = str(pack.get("asset_kind", "")).lower()
    asset_type_map = {
        "surface_pbr": "texture",
        "texture": "texture",
        "skybox": "texture",
        "hdr": "texture",
        "model": "model",
        "prop_static": "model",
        "foliage": "model",
        "character_static": "model",
        "character_animated": "model",
    }
    asset_type = asset_type_map.get(asset_kind, "texture")

    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    errors = []
    for prompt_entry in prompts:
        if isinstance(prompt_entry, str):
            prompt_text = prompt_entry
            width, height, steps, cfg = 1024, 1024, 25, 7.0
            input_image = None
        elif isinstance(prompt_entry, dict):
            prompt_text = str(prompt_entry.get("text") or prompt_entry.get("prompt") or "")
            width = int(prompt_entry.get("width", 1024))
            height = int(prompt_entry.get("height", 1024))
            steps = int(prompt_entry.get("steps", 25))
            cfg = float(prompt_entry.get("cfg", 7.0))
            input_image = prompt_entry.get("input_image")
        else:
            continue
        if not prompt_text:
            errors.append("empty_prompt_text")
            continue

        batch_results, call_err = _run_batch(
            run_comfyui_batch,
            prompt=prompt_text, pack_id=pack_id, asset_type=asset_type,
            width=width, height=height, steps=steps, cfg=cfg,
            input_image=input_image, output_dir=out_dir,
        )
        if call_err:
            errors.append(f"{prompt_text[:40]}: {call_err.error}")
        elif batch_results:
            results.extend(batch_results)

    if not results:
        return AcquisitionResult(
            ok=False, method="generator", provider="comfyui",
            error=f"all_prompts_failed: {'; '.join(errors)[:200]}",
        )

    return AcquisitionResult(
        ok=True, method="generator", provider="comfyui",
        source_dir=out_dir,
        notes=(
            f"comfyui generated {len(results)} output(s) "
            f"from {len(prompts)} prompt(s) -> {out_dir}"
            + (f"; warnings: {len(errors)}" if errors else "")
        ),
    )


def _drive_local_image(pack: dict[str, Any], *, pack_id: str, out_dir: Path) -> AcquisitionResult:
    """Drive local_image_runner.run_local_image_batch (sd.cpp CUDA wrapper)."""
    mod, err = _import_runner("local_image_runner")
    if err:
        return AcquisitionResult(
            ok=False, method="generator", provider="local_image", error=err.error,
        )
    run_local_image_batch = getattr(mod, "run_local_image_batch")

    prompts = pack.get("prompts") or []
    if not prompts:
        return AcquisitionResult(
            ok=False, method="generator", provider="local_image",
            error="no_prompts_in_pack",
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    errors = []
    for prompt_entry in prompts:
        if isinstance(prompt_entry, str):
            prompt_text = prompt_entry
            count, width, height, steps, cfg = 6, 512, 512, 20, 7.0
            model_path = None
        elif isinstance(prompt_entry, dict):
            prompt_text = str(prompt_entry.get("text") or prompt_entry.get("prompt") or "")
            count = int(prompt_entry.get("count", 6))
            width = int(prompt_entry.get("width", 512))
            height = int(prompt_entry.get("height", 512))
            steps = int(prompt_entry.get("steps", 20))
            cfg = float(prompt_entry.get("cfg", 7.0))
            model_path = prompt_entry.get("model_path")
        else:
            continue
        if not prompt_text:
            errors.append("empty_prompt_text")
            continue

        batch_result, call_err = _run_batch(
            run_local_image_batch,
            pack_id=pack_id, prompt=prompt_text, count=count,
            width=width, height=height, steps=steps, cfg=cfg,
            model_path=model_path, output_dir=out_dir,
        )
        if call_err:
            errors.append(f"{prompt_text[:40]}: {call_err.error}")
        elif batch_result:
            results.append(batch_result)

    if not results:
        return AcquisitionResult(
            ok=False, method="generator", provider="local_image",
            error=f"all_prompts_failed: {'; '.join(errors)[:200]}",
        )

    return AcquisitionResult(
        ok=True, method="generator", provider="local_image",
        source_dir=out_dir,
        notes=(
            f"local_image generated {len(results)} batch(es) "
            f"from {len(prompts)} prompt(s) -> {out_dir}"
            + (f"; warnings: {len(errors)}" if errors else "")
        ),
    )


def _drive_stable_audio(pack: dict[str, Any], *, pack_id: str, out_dir: Path) -> AcquisitionResult:
    """Drive stable_audio_runner.run_stable_audio_batch."""
    mod, err = _import_runner("stable_audio_runner")
    if err:
        return AcquisitionResult(
            ok=False, method="generator", provider="stable_audio_open_small", error=err.error,
        )
    is_stable_audio_available = getattr(mod, "is_stable_audio_available")
    run_stable_audio_batch = getattr(mod, "run_stable_audio_batch")

    prompts = pack.get("prompts") or []
    if not prompts:
        return AcquisitionResult(
            ok=False, method="generator", provider="stable_audio_open_small",
            error="no_prompts_in_pack",
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    available = is_stable_audio_available()

    results = []
    errors = []
    for prompt_entry in prompts:
        if isinstance(prompt_entry, str):
            prompt_text = prompt_entry
            duration_s = 11
        elif isinstance(prompt_entry, dict):
            prompt_text = str(prompt_entry.get("text") or prompt_entry.get("prompt") or "")
            duration_s = int(prompt_entry.get("duration_s", 11))
        else:
            continue
        if not prompt_text:
            errors.append("empty_prompt_text")
            continue

        batch_result, call_err = _run_batch(
            run_stable_audio_batch,
            pack_id=pack_id, prompt=prompt_text, duration_s=duration_s,
            output_dir=out_dir, dry_run=not available,
        )
        if call_err:
            errors.append(f"{prompt_text[:30]}: {call_err.error}")
        elif batch_result:
            results.append(batch_result)
            if batch_result.error:
                errors.append(f"{prompt_text[:30]}: {batch_result.error}")

    if not results:
        return AcquisitionResult(
            ok=False, method="generator", provider="stable_audio_open_small",
            error=f"all_prompts_failed: {'; '.join(errors)[:200]}",
        )

    succeeded_real = sum(1 for r in results if not r.error and not r.dry_run)
    spec_only = sum(1 for r in results if r.dry_run or r.error)

    if available and succeeded_real > 0:
        return AcquisitionResult(
            ok=True, method="generator", provider="stable_audio_open_small",
            source_dir=out_dir,
            notes=f"stable_audio generated {succeeded_real} clip(s) -> {out_dir}",
        )

    return AcquisitionResult(
        ok=False, method="generator", provider="stable_audio_open_small",
        source_dir=out_dir,
        awaiting_manual=True,
        notes=(
            f"stable_audio job specs emitted ({spec_only}); operator must "
            f"invoke STABLE_AUDIO_RUNNER_BIN against them (see "
            f"assetboy/data/stable_audio_*.json under {out_dir}). "
            f"Or set STABLE_AUDIO_MODEL_DIR + STABLE_AUDIO_RUNNER_BIN env "
            "vars and re-run."
        ),
    )


# --------------------------------------------------------------------------- #
# Path helpers
# --------------------------------------------------------------------------- #

def _resolve_source_staging_dir(
    pack_id: str, game_scope: str, *, lane: str, dry_run: bool = False
) -> Path:
    """Where downloaded/generated bytes land before pack_pipeline picks them up.

    Layout: <asset_library_root>/inbox/<lane>/<game_scope>/<pack_id>/
    Mirrors the existing ``manual_drop_dir`` shape for consistency.

    In dry_run mode (no workspace.json present), returns a synthetic path
    under a system-temp dir so the router can still answer "where would the
    bytes land" without requiring the operator's Flax workspace to be set up.
    """
    if dry_run:
        try:
            return asset_library_root() / "inbox" / lane / game_scope / pack_id
        except FileNotFoundError:
            import tempfile
            return (
                Path(tempfile.gettempdir())
                / "assetboy_dry_run"
                / lane
                / game_scope
                / pack_id
            )
    root = asset_library_root()
    return root / "inbox" / lane / game_scope / pack_id


__all__ = [
    "AcquisitionResult",
    "AcquisitionError",
    "SUPPORTED_METHODS",
    "acquire_source_dir",
]
