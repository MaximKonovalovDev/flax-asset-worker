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
    awaiting_manual: bool = False  # True when method=manual_browser + files not yet dropped


class AcquisitionError(Exception):
    """Raised when an acquisition attempt fails in a way the caller should
    surface to the operator (e.g. unsupported method, dead provider)."""


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

    # Shouldn't reach (method check above is exhaustive) but defensive:
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

    if provider == "polyhaven":
        return _drive_polyhaven(pack, pack_id=pack_id, out_dir=out_dir)
    if provider == "kenney":
        return _drive_kenney(pack, pack_id=pack_id, out_dir=out_dir)
    if provider == "ambientcg":
        return _drive_ambientcg(pack, pack_id=pack_id, out_dir=out_dir)
    if provider == "freesound":
        return _drive_freesound(pack, pack_id=pack_id, out_dir=out_dir)

    return AcquisitionResult(
        ok=False,
        method="direct_url",
        provider=provider,
        error=(
            f"unsupported_provider: {provider!r}. "
            "direct_url lane currently supports: polyhaven, kenney, ambientcg, freesound. "
            "For others, set acquisition_method: manual_browser or generator."
        ),
    )


def _drive_polyhaven(pack: dict[str, Any], *, pack_id: str, out_dir: Path) -> AcquisitionResult:
    """Drive polyhaven_runner with the pack's asset list.

    polyhaven_runner expects a single ``search`` query (string), not a list,
    so we iterate the pack's assets and call once per asset_id.
    """
    try:
        from assetboy.execution.polyhaven_runner import run_polyhaven_batch
    except ImportError as exc:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="polyhaven",
            error=f"import_failed: {exc}",
        )
    assets = pack.get("assets") or []
    asset_ids = [a.get("asset_id") if isinstance(a, dict) else str(a) for a in assets]
    asset_ids = [a for a in asset_ids if a]
    if not asset_ids:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="polyhaven",
            error="no_assets_in_pack",
        )
    # Categorize: HDRIs go to "hdris", textures to "textures", models to "models".
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
    try:
        from assetboy.execution.kenney_runner import run_kenney_batch
    except ImportError as exc:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="kenney",
            error=f"import_failed: {exc}",
        )
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
                # Kenney recipes that ship without explicit URLs are blocked;
                # the operator must provide a source_url per asset.
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
    try:
        from assetboy.execution.ambientcg_runner import run_ambientcg_pack
    except ImportError as exc:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="ambientcg",
            error=f"import_failed: {exc}",
        )
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
    # Map int resolutions to AmbientCG's "1K"/"2K"/"4K" labels.
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
    try:
        from assetboy.execution.freesound_runner import run_freesound_batch
    except ImportError as exc:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="freesound",
            error=f"import_failed: {exc}",
        )
    search_terms = pack.get("search_terms") or []
    if not search_terms:
        return AcquisitionResult(
            ok=False, method="direct_url", provider="freesound",
            error="no_search_terms_in_pack",
        )
    try:
        # freesound_runner emits a spec file; execute=False keeps it plan-only
        # (s2.6b retired the execute=True browser-driving path).
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
    # Resolve drop_dir tolerantly so dry_run works without workspace.json.
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

    # Check if operator has already dropped files
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

    # No files yet -- emit/refresh marker + return awaiting
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
        ok=False,  # not ready yet; caller skips pack_pipeline for this pack
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
        try:
            from assetboy.execution.comfyui_runner import is_comfyui_running
        except ImportError as exc:
            return AcquisitionResult(
                ok=False, method="generator", provider="comfyui",
                error=f"import_failed: {exc}",
            )
        if not is_comfyui_running():
            return AcquisitionResult(
                ok=False, method="generator", provider="comfyui",
                error="comfyui_not_running (start ComfyUI on :8188 then re-run)",
            )
        return AcquisitionResult(
            ok=False, method="generator", provider="comfyui",
            error="comfyui_workflow_routing_TBD_in_s11.1 "
                  "(server is up; full workflow integration deferred)",
        )

    if provider in ("stable_audio_open_small", "local_image", "sd.cpp"):
        return AcquisitionResult(
            ok=False, method="generator", provider=provider,
            error=f"generator_provider_TBD_in_s11.1: {provider}",
        )

    return AcquisitionResult(
        ok=False, method="generator", provider=provider,
        error=f"unsupported_generator_provider: {provider}",
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
            # No workspace.json -- return a synthetic placeholder path.
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
