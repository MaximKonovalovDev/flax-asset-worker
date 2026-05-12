"""Local FAW asset-library sub-app.

Wraps the C# FAW HTTP server on :8790 (Source/Routes/LibraryRoutes.cs).
The C# side owns the JSON-on-disk library (artifacts/library/...);
this CLI just speaks HTTP to it.

Commands:
    library search    -- name/category substring match across installed assets
    library install   -- call a provider, download, validate, copy to Content/
    library ready     -- list all installed assets (full library dump)
    library audit     -- health-check the C# server (calls /api/v1/health)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

try:
    import requests
except ImportError as _exc:  # pragma: no cover
    requests = None  # type: ignore[assignment]

DEFAULT_BASE = "http://localhost:8790"

app = typer.Typer(
    name="library",
    help="Local FAW asset library: search / install / ready / audit.",
    add_completion=False,
    no_args_is_help=True,
)


# --------------------------------------------------------------------------- #
# Shared HTTP helper
# --------------------------------------------------------------------------- #

def _faw_post(
    path: str,
    payload: dict,
    *,
    base: str,
    timeout: float = 30.0,
) -> dict:
    """POST JSON to FAW. Returns parsed JSON; raises on non-2xx."""
    if requests is None:
        raise RuntimeError("requests library not installed (pip install requests)")
    r = requests.post(f"{base}{path}", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json() if r.content else {}


def _faw_get(path: str, *, base: str, timeout: float = 10.0) -> dict:
    if requests is None:
        raise RuntimeError("requests library not installed")
    r = requests.get(f"{base}{path}", timeout=timeout)
    r.raise_for_status()
    return r.json() if r.content else {}


def _emit_json(data, *, json_out: bool) -> None:
    if json_out:
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write("\n")


# --------------------------------------------------------------------------- #
# library search
# --------------------------------------------------------------------------- #

@app.command("search")
def search_cmd(
    query: Annotated[
        str,
        typer.Argument(help="Substring match across name + category."),
    ],
    category: Annotated[
        str,
        typer.Option(
            "--category",
            help="Optional category filter (texture/model/audio/animation/etc).",
        ),
    ] = "",
    base: Annotated[
        str,
        typer.Option("--server", help="FAW server base URL."),
    ] = DEFAULT_BASE,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of plain lines."),
    ] = False,
) -> None:
    """Search installed library assets by name/category substring."""
    payload = {"query": query}
    if category:
        payload["category"] = category
    try:
        data = _faw_post("/api/v1/library/search", payload, base=base)
    except Exception as exc:
        if json_out:
            json.dump({"error": str(exc)}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"library_search_error={exc}")
        raise typer.Exit(code=1)

    results = data.get("results") or data.get("assets") or []
    if json_out:
        _emit_json(data, json_out=True)
        return
    print(f"library_search_count={len(results)}")
    for idx, entry in enumerate(results, start=1):
        print(
            f"library_search_entry={idx}  "
            f"id={entry.get('id', '')}  "
            f"name={entry.get('name', '')!r}  "
            f"provider={entry.get('provider', '')}  "
            f"category={entry.get('category', '')}"
        )


# --------------------------------------------------------------------------- #
# library install
# --------------------------------------------------------------------------- #

@app.command("install")
def install_cmd(
    asset_id: Annotated[
        str,
        typer.Argument(help="Provider's native asset ID (e.g. 'brick_wall_01')."),
    ],
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            "-p",
            help="Provider id (polyhaven/kenney/fab/mixamo/freesound/epic).",
        ),
    ] = "polyhaven",
    category: Annotated[
        str,
        typer.Option(
            "--category",
            "-c",
            help="Asset category (texture/model/audio/animation/hdr/etc).",
        ),
    ] = "texture",
    name: Annotated[
        str,
        typer.Option(
            "--name",
            "-n",
            help="Display name for library entry. Defaults to asset_id.",
        ),
    ] = "",
    base: Annotated[
        str,
        typer.Option("--server", help="FAW server base URL."),
    ] = DEFAULT_BASE,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Install an asset: provider -> download -> validate -> copy to Content/."""
    payload = {
        "asset_id": asset_id,
        "provider": provider,
        "category": category,
        "name": name or asset_id,
    }
    try:
        data = _faw_post("/api/v1/library/install", payload, base=base, timeout=300.0)
    except Exception as exc:
        if json_out:
            json.dump({"error": str(exc), "asset_id": asset_id}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"library_install_error={exc}")
            print(f"library_install_asset_id={asset_id}")
        raise typer.Exit(code=1)

    if json_out:
        _emit_json(data, json_out=True)
        return
    for k, v in (data or {}).items():
        print(f"library_install_{k}={v}")


# --------------------------------------------------------------------------- #
# library ready
# --------------------------------------------------------------------------- #

@app.command("ready")
def ready_cmd(
    base: Annotated[
        str,
        typer.Option("--server", help="FAW server base URL."),
    ] = DEFAULT_BASE,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Dump the full installed library."""
    try:
        data = _faw_post("/api/v1/library/ready", {}, base=base)
    except Exception as exc:
        if json_out:
            json.dump({"error": str(exc)}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"library_ready_error={exc}")
        raise typer.Exit(code=1)

    assets = data if isinstance(data, list) else data.get("assets") or []
    if json_out:
        _emit_json(data, json_out=True)
        return
    print(f"library_ready_count={len(assets)}")
    for asset in assets:
        print(
            f"library_ready_entry  "
            f"id={asset.get('id', '')}  "
            f"name={asset.get('name', '')!r}  "
            f"provider={asset.get('provider', '')}  "
            f"path={asset.get('local_path', '')}"
        )


# --------------------------------------------------------------------------- #
# library audit
# --------------------------------------------------------------------------- #

@app.command("audit")
def audit_cmd(
    base: Annotated[
        str,
        typer.Option("--server", help="FAW server base URL."),
    ] = DEFAULT_BASE,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Health-check the FAW server (calls /api/v1/health)."""
    try:
        data = _faw_get("/api/v1/health", base=base, timeout=5.0)
    except Exception as exc:
        if json_out:
            json.dump({"ok": False, "error": str(exc)}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"library_audit_ok=false")
            print(f"library_audit_error={exc}")
        raise typer.Exit(code=1)

    if json_out:
        _emit_json({"ok": True, "response": data}, json_out=True)
        return
    print(f"library_audit_ok=true")
    for k, v in (data or {}).items():
        print(f"library_audit_{k}={v}")


# --------------------------------------------------------------------------- #
# library asset  (v1.6.s2)
# --------------------------------------------------------------------------- #

@app.command("asset")
def asset_cmd(
    asset_id: Annotated[
        str,
        typer.Argument(help="Asset ID to look up in the library."),
    ],
    base: Annotated[
        str,
        typer.Option("--server", help="FAW server base URL."),
    ] = DEFAULT_BASE,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Fetch a single asset's metadata by id (Path B v1.6.s2).

    Calls GET /api/v1/library/asset/{asset_id}. Returns 404-equivalent
    (`ok=false, error=asset_not_found`) when the id isn't installed.
    """
    try:
        # The HTTP server returns 404 on not-found; requests treats 404 as
        # an error, but we want to surface the JSON body anyway.
        if requests is None:
            raise RuntimeError("requests not installed")
        r = requests.get(
            f"{base}/api/v1/library/asset/{asset_id}",
            timeout=10.0,
        )
        # Accept both 200 (found) and 404 (not found); both return JSON
        if r.status_code not in (200, 404):
            r.raise_for_status()
        data = r.json() if r.content else {}
    except Exception as exc:
        if json_out:
            json.dump({"ok": False, "error": str(exc), "asset_id": asset_id},
                      sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"library_asset_ok=false")
            print(f"library_asset_error={exc}")
        raise typer.Exit(code=1)

    if json_out:
        _emit_json(data, json_out=True)
        if not data.get("success", False):
            raise typer.Exit(code=1)
        return

    if data.get("success"):
        asset = data.get("asset") or {}
        print(f"library_asset_ok=true")
        for k, v in asset.items():
            print(f"library_asset_{k}={v}")
    else:
        print(f"library_asset_ok=false")
        print(f"library_asset_error={data.get('error', 'unknown')}")
        print(f"library_asset_id={asset_id}")
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# library export  (v1.9.s22)
# --------------------------------------------------------------------------- #

@app.command("export")
def export_cmd(
    out_path: Annotated[
        Path,
        typer.Argument(
            help="Path to write the manifest (JSON or YAML by extension).",
        ),
    ],
    base: Annotated[
        str,
        typer.Option("--server", help="FAW server base URL."),
    ] = DEFAULT_BASE,
    format: Annotated[
        str,
        typer.Option(
            "--format",
            help="Output format: json | yaml (default: inferred from out_path extension).",
        ),
    ] = "",
    include_checksums: Annotated[
        bool,
        typer.Option(
            "--include-checksums",
            help="Include sha256 per asset for verification (default: false).",
        ),
    ] = False,
) -> None:
    """Export installed library as a portable manifest (Path B v1.9.s22).

    Walks /api/v1/library/ready and dumps in the same shape `bulk-install`
    accepts. Round-trip: export from one machine, bulk-install on another.

    With --include-checksums, each entry gets its sha256 (the C# server
    already records it per asset). Useful for verifying the receiving
    machine ended up with byte-identical files.
    """
    try:
        data = _faw_post("/api/v1/library/ready", {}, base=base)
    except Exception as exc:
        print(f"library_export_error={exc}")
        raise typer.Exit(code=1)

    raw_assets = data.get("ready_assets") or data.get("assets") or []
    if not isinstance(raw_assets, list):
        print(f"library_export_error=unexpected_response_shape (got {type(raw_assets).__name__})")
        raise typer.Exit(code=1)

    # Build the manifest entries (subset of fields that bulk-install consumes)
    manifest: list[dict] = []
    for asset in raw_assets:
        if not isinstance(asset, dict):
            continue
        entry = {
            "asset_id": asset.get("id", ""),
            "provider": asset.get("provider", ""),
            "category": asset.get("category", ""),
            "name": asset.get("name", asset.get("id", "")),
        }
        if include_checksums and asset.get("sha256"):
            entry["sha256"] = asset["sha256"]
        manifest.append(entry)

    # Decide format: explicit --format wins, else infer from extension
    fmt = format.strip().lower()
    if not fmt:
        suffix = out_path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            fmt = "yaml"
        else:
            fmt = "json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "yaml":
        try:
            import yaml
        except ImportError:
            print(f"library_export_error=pyyaml_not_installed (use --format json or pip install pyyaml)")
            raise typer.Exit(code=1)
        out_path.write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    elif fmt == "json":
        out_path.write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )
    else:
        print(f"library_export_error=unknown_format: {fmt!r} (use json or yaml)")
        raise typer.Exit(code=1)

    print(f"library_export_count={len(manifest)}")
    print(f"library_export_format={fmt}")
    print(f"library_export_path={out_path}")
    print(f"library_export_bytes={out_path.stat().st_size}")
    print(f"library_export_include_checksums={'true' if include_checksums else 'false'}")


# --------------------------------------------------------------------------- #
# library bulk-install  (v1.8.s16)
# --------------------------------------------------------------------------- #

@app.command("bulk-install")
def bulk_install_cmd(
    manifest: Annotated[
        Path,
        typer.Argument(help="Path to YAML or JSON manifest with assets to install."),
    ],
    base: Annotated[
        str,
        typer.Option("--server", help="FAW server base URL."),
    ] = DEFAULT_BASE,
    stop_on_error: Annotated[
        bool,
        typer.Option(
            "--stop-on-error",
            help="Abort batch on first failure (default: continue + report all).",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON summary."),
    ] = False,
) -> None:
    """Install many assets from a manifest in one batch (Path B v1.8.s16).

    Manifest schema (YAML or JSON):
      - asset_id: brick_wall_01
        provider: polyhaven
        category: texture
        name: Brick Wall 01           # optional; defaults to asset_id
      - asset_id: ...

    Per-asset isolation: one failure doesn't abort the batch unless
    --stop-on-error is set. Each asset gets its own success/fail entry.

    Exit code:
      0 if all assets installed
      1 if any failure (or stop_on_error triggered)
    """
    if not manifest.exists():
        msg = f"manifest_not_found: {manifest}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"library_bulk_install_error={msg}")
        raise typer.Exit(code=1)

    # Load YAML or JSON
    text = manifest.read_text(encoding="utf-8")
    items = None
    try:
        # Try JSON first (cheap)
        items = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
            items = yaml.safe_load(text)
        except Exception as exc:
            msg = f"manifest_parse_failed: {exc}"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"library_bulk_install_error={msg}")
            raise typer.Exit(code=1)

    if not isinstance(items, list):
        msg = f"manifest_must_be_a_list (got {type(items).__name__})"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"library_bulk_install_error={msg}")
        raise typer.Exit(code=1)

    results: list[dict] = []
    succeeded = 0
    failed = 0

    for idx, entry in enumerate(items):
        if not isinstance(entry, dict):
            results.append({
                "index": idx,
                "ok": False,
                "error": f"entry_not_a_dict (got {type(entry).__name__})",
            })
            failed += 1
            if stop_on_error:
                break
            continue

        asset_id = str(entry.get("asset_id", "")).strip()
        provider = str(entry.get("provider", "")).strip()
        category = str(entry.get("category", "")).strip() or "unknown"
        name = str(entry.get("name", "")).strip() or asset_id

        if not asset_id or not provider:
            results.append({
                "index": idx,
                "asset_id": asset_id,
                "provider": provider,
                "ok": False,
                "error": "missing_required_fields (asset_id + provider both required)",
            })
            failed += 1
            if stop_on_error:
                break
            continue

        payload = {
            "asset_id": asset_id,
            "provider": provider,
            "category": category,
            "name": name,
        }
        try:
            data = _faw_post("/api/v1/library/install", payload, base=base, timeout=300.0)
            entry_ok = bool(data.get("success", False))
            results.append({
                "index": idx,
                "asset_id": asset_id,
                "provider": provider,
                "ok": entry_ok,
                "response": data,
            })
            if entry_ok:
                succeeded += 1
                if not json_out:
                    print(f"  [OK ] {idx:3d}  {provider}/{asset_id}")
            else:
                failed += 1
                err = data.get("error", "install_failed")
                if not json_out:
                    print(f"  [RED] {idx:3d}  {provider}/{asset_id}  error={err}")
                if stop_on_error:
                    break
        except Exception as exc:
            results.append({
                "index": idx,
                "asset_id": asset_id,
                "provider": provider,
                "ok": False,
                "error": str(exc),
            })
            failed += 1
            if not json_out:
                print(f"  [RED] {idx:3d}  {provider}/{asset_id}  http_error={exc}")
            if stop_on_error:
                break

    if json_out:
        json.dump({
            "total": len(items),
            "attempted": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "stop_on_error": stop_on_error,
            "results": results,
        }, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        print()
        print(f"library_bulk_install_total={len(items)}")
        print(f"library_bulk_install_attempted={len(results)}")
        print(f"library_bulk_install_succeeded={succeeded}")
        print(f"library_bulk_install_failed={failed}")

    if failed > 0:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# library readiness  (v1.7.s13)
# --------------------------------------------------------------------------- #

@app.command("readiness")
def readiness_cmd(
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Per-provider probe timeout in seconds."),
    ] = 15.0,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Show per-provider readiness (Path B v1.7.s13).

    Wraps `providers.provider_readiness.build_provider_readiness_report`
    so operators can see at a glance what's set up vs missing across:
      - Fab / Mixamo / Unity / Epic (manual_browser lane auth)
      - PolyHaven / Kenney / AmbientCG / FreeSound (direct_url; usually OK)
      - ComfyUI / sd.cpp / Stable Audio (generator lane runtime)
      - generator_profiles (Colab JSON registry)

    Status per provider: ready_now / partial / setup_required.
    """
    from assetboy.providers.provider_readiness import build_provider_readiness_report

    try:
        report = build_provider_readiness_report(timeout_seconds=timeout)
    except Exception as exc:
        msg = f"readiness_failed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"library_readiness_error={msg}")
        raise typer.Exit(code=1)

    if json_out:
        json.dump(report, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    summary = report.get("summary") or {}
    providers = report.get("providers") or []
    print(f"library_readiness_total={summary.get('total', 0)}")
    print(f"library_readiness_ready_now={summary.get('ready_now', 0)}")
    print(f"library_readiness_partial={summary.get('partial', 0)}")
    print(f"library_readiness_setup_required={summary.get('setup_required', 0)}")
    for idx, prov in enumerate(providers, start=1):
        pid = prov.get("provider_id", "?")
        status = prov.get("status", "?")
        lane = prov.get("lane", "?")
        next_action = prov.get("next_action", "")
        # Truncate next_action to keep one-line readable
        if isinstance(next_action, str) and len(next_action) > 80:
            next_action = next_action[:77] + "..."
        print(
            f"library_readiness_provider={idx:2d}  "
            f"id={pid:30}  status={status:15}  lane={lane}  "
            f"next={next_action}"
        )


# --------------------------------------------------------------------------- #
# library r1a-status  (v1.12.s75)
# --------------------------------------------------------------------------- #

@app.command("r1a-status")
def r1a_status_cmd(
    check_live: Annotated[
        bool,
        typer.Option(
            "--check-live",
            help=(
                "v1.13.s80: probe each provider's API with a minimal search."
                " Adds ~1-3s wall time. Sets live_ok per provider in output."
            ),
        ),
    ] = False,
    bars: Annotated[
        bool,
        typer.Option(
            "--bars",
            help=(
                "v1.13.s90: render a 40-char ASCII bar per provider showing"
                " proportional downloaded-bytes on disk. Plain-text only."
            ),
        ),
    ] = False,
    html_out: Annotated[
        Path,
        typer.Option(
            "--html",
            help=(
                "v1.13.s97: write a standalone HTML report to this path"
                " (with CSS bars + status badges). No JSON or plain output"
                " when --html is set; stdout shows only the written path."
            ),
        ),
    ] = Path(""),
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Combined readiness + on-disk-stats check for the R1A provider catalog.

    Pulls together:
      - gen list-providers (env-key state per provider)
      - pack manifest-stats (on-disk counts per source)
      - (v1.13.s80) live API probe per provider when --check-live is set

    Examples:
      assetboy library r1a-status
      assetboy library r1a-status --check-live
      assetboy library r1a-status --json
    """
    import os
    from assetboy.execution.comfyui_runner import manual_drop_dir

    # --- list-providers part ---
    # (Replicated from gen.py:list_providers_cmd; keep in sync if catalog changes.)
    providers_catalog = [
        ("met-museum", None, "CC0", "image:photograph"),
        ("wikimedia", None, "CC0/CC-BY/SA/PD", "image:any"),
        ("archive-org", None, "CC/PD per item", "image|audio|video|texts"),
        ("scryfall", None, "CC-BY-SA-4.0", "image:fantasy_art"),
        ("iconify", None, "MIT/Apache/CC0/OFL", "image:icon_svg"),
        ("pexels", "PEXELS_API_KEY", "Pexels License", "image:photo + VIDEO"),
        ("pixabay", "PIXABAY_API_KEY", "CC0-equivalent", "image:any + VIDEO"),
        ("unsplash", "UNSPLASH_ACCESS_KEY", "Unsplash License", "image:photo"),
        ("rawg", "RAWG_API_KEY", "REFERENCE-ONLY", "image:game_screenshot"),
        ("jamendo", "JAMENDO_CLIENT_ID", "CC-BY/SA", "audio:music_track"),
        # v1.13.s86 — iNaturalist
        ("inaturalist", None, "CC0/CC-BY/CC-BY-SA", "image:nature_reference"),
    ]
    providers_state: list[dict] = []
    for pid, env_var, lic, asset_class in providers_catalog:
        if env_var is None:
            env_set = None
        else:
            env_set = bool(os.environ.get(env_var, "").strip())
        providers_state.append({
            "id": pid,
            "env_var": env_var,
            "env_set": env_set,
            "license": lic,
            "asset_class": asset_class,
            # Source key in manifests; some runners use the hyphenated cli name,
            # others use the underscored runner name. Align here.
            "manifest_source": {
                "met-museum": "met_museum",
                "wikimedia": "wikimedia_commons",
                "archive-org": "archive_org",
                "scryfall": "scryfall",
                "iconify": "iconify",
                "pexels": "pexels",
                "pixabay": "pixabay",
                "unsplash": "unsplash",
                "rawg": "rawg.io",
                "jamendo": "jamendo",
                "inaturalist": "inaturalist",
            }.get(pid, pid),
        })

    # --- manifest-stats part ---
    scan_root = manual_drop_dir()
    on_disk_by_source: dict[str, dict] = {}
    manifests_scanned = 0
    if scan_root.exists():
        for mf in sorted(scan_root.rglob("*_manifest.json")):
            try:
                doc = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                continue
            manifests_scanned += 1
            src = str(doc.get("source", "unknown"))
            bucket = on_disk_by_source.setdefault(src, {
                "manifests": 0, "downloaded": 0, "bytes": 0,
            })
            bucket["manifests"] += 1
            for k in ("objects_downloaded", "files_downloaded",
                      "items_downloaded", "cards_downloaded",
                      "icons_downloaded", "tracks_downloaded",
                      "photos_downloaded", "games_downloaded"):
                v = doc.get(k)
                if isinstance(v, int):
                    bucket["downloaded"] += v
            for entry in (doc.get("entries") or []):
                if isinstance(entry, dict):
                    b = entry.get("bytes")
                    if isinstance(b, int):
                        bucket["bytes"] += b

    # --- merge: annotate each provider with its on-disk row ---
    for prov in providers_state:
        src_key = prov["manifest_source"]
        disk = on_disk_by_source.get(src_key, {})
        prov["manifests_on_disk"] = disk.get("manifests", 0)
        prov["downloaded_on_disk"] = disk.get("downloaded", 0)
        prov["bytes_on_disk"] = disk.get("bytes", 0)
        # v1.13.s80 default: live_ok=None (not probed). Filled below if check_live.
        prov["live_ok"] = None
        prov["live_error"] = None

    # v1.13.s80 — live probes (concurrent via ThreadPoolExecutor).
    if check_live:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _probe(prov: dict) -> tuple[str, bool, str | None]:
            pid = prov["id"]
            try:
                if prov["env_var"] is not None and not prov["env_set"]:
                    return pid, False, "missing_env_key"
                if pid == "met-museum":
                    from assetboy.execution.met_museum_runner import search_met_object_ids
                    ids = search_met_object_ids("vermeer", has_images=True)
                    return pid, len(ids) > 0, None if ids else "no_results"
                if pid == "wikimedia":
                    from assetboy.execution.wikimedia_runner import search_wikimedia_files
                    files = search_wikimedia_files("stone wall", limit=2)
                    return pid, len(files) > 0, None if files else "no_results"
                if pid == "archive-org":
                    from assetboy.execution.archive_org_runner import search_archive_items
                    items = search_archive_items("subject:roman", rows=2)
                    return pid, len(items) > 0, None if items else "no_results"
                if pid == "scryfall":
                    from assetboy.execution.scryfall_runner import search_scryfall_cards
                    cards = search_scryfall_cards("type:dragon")
                    return pid, len(cards) > 0, None if cards else "no_results"
                if pid == "iconify":
                    from assetboy.execution.iconify_runner import search_iconify_icons
                    icons = search_iconify_icons("sword", limit=2)
                    return pid, len(icons) > 0, None if icons else "no_results"
                if pid == "pexels":
                    from assetboy.execution.pexels_runner import search_pexels_photos, get_api_key
                    photos = search_pexels_photos("fire", api_key=get_api_key(), per_page=2)
                    return pid, len(photos) > 0, None if photos else "no_results"
                if pid == "pixabay":
                    from assetboy.execution.pixabay_runner import search_pixabay_photos, get_api_key
                    hits = search_pixabay_photos("stone wall", api_key=get_api_key(), per_page=3)
                    return pid, len(hits) > 0, None if hits else "no_results"
                if pid == "unsplash":
                    from assetboy.execution.unsplash_runner import search_unsplash_photos, get_access_key
                    photos = search_unsplash_photos("mountain", access_key=get_access_key(), per_page=2)
                    return pid, len(photos) > 0, None if photos else "no_results"
                if pid == "rawg":
                    from assetboy.execution.rawg_runner import search_rawg_games, get_api_key
                    games = search_rawg_games("roguelike", api_key=get_api_key(), page_size=2)
                    return pid, len(games) > 0, None if games else "no_results"
                if pid == "jamendo":
                    from assetboy.execution.jamendo_runner import search_jamendo_tracks, get_client_id
                    tracks = search_jamendo_tracks("ambient", client_id=get_client_id(), limit=2)
                    return pid, True, None if tracks else "no_results_but_call_succeeded"
                if pid == "inaturalist":
                    from assetboy.execution.inaturalist_runner import search_inaturalist_observations
                    obs = search_inaturalist_observations("oak tree", per_page=2)
                    return pid, len(obs) > 0, None if obs else "no_results"
                return pid, False, "unknown_provider"
            except Exception as exc:
                return pid, False, f"probe_failed: {exc}"

        with ThreadPoolExecutor(max_workers=len(providers_state)) as pool:
            futs = {pool.submit(_probe, p): p for p in providers_state}
            for fut in as_completed(futs):
                pid_done, ok_done, err_done = fut.result()
                for p in providers_state:
                    if p["id"] == pid_done:
                        p["live_ok"] = ok_done
                        p["live_error"] = err_done
                        break

    no_key_count = sum(1 for p in providers_state if p["env_var"] is None)
    key_set = sum(1 for p in providers_state if p["env_set"] is True)
    key_unset = sum(1 for p in providers_state if p["env_set"] is False)
    total_downloaded = sum(p["downloaded_on_disk"] for p in providers_state)
    total_bytes = sum(p["bytes_on_disk"] for p in providers_state)
    live_ok_count = sum(1 for p in providers_state if p["live_ok"] is True)
    live_failed_count = sum(1 for p in providers_state if p["live_ok"] is False)

    summary = {
        "manual_drop_root": str(scan_root),
        "manifests_scanned": manifests_scanned,
        "providers_total": len(providers_state),
        "providers_no_key": no_key_count,
        "providers_key_set": key_set,
        "providers_key_unset": key_unset,
        "total_downloaded_on_disk": total_downloaded,
        "total_bytes_on_disk": total_bytes,
        "checked_live": check_live,
        "live_ok_count": live_ok_count,
        "live_failed_count": live_failed_count,
        "providers": providers_state,
    }

    # v1.13.s97 — HTML report (preempts both JSON and plain).
    # Note: Typer default Path("") str()-renders as ".", so check
    # for non-empty original string explicitly.
    html_out_str = str(html_out)
    if html_out_str and html_out_str != ".":
        html_path = Path(html_out)
        try:
            html_path.parent.mkdir(parents=True, exist_ok=True)
            max_bytes = max((p["bytes_on_disk"] for p in providers_state), default=0)
            rows_html: list[str] = []
            for p in providers_state:
                if p["env_var"] is None:
                    env_badge = "<span class='b-grey'>no key</span>"
                elif p["env_set"]:
                    env_badge = "<span class='b-green'>SET</span>"
                else:
                    env_badge = "<span class='b-red'>unset</span>"
                pct = (
                    100.0 * p["bytes_on_disk"] / max_bytes
                    if max_bytes > 0 else 0.0
                )
                rows_html.append(
                    "<tr>"
                    f"<td>{p['id']}</td>"
                    f"<td>{env_badge}</td>"
                    f"<td class='num'>{p['manifests_on_disk']}</td>"
                    f"<td class='num'>{p['downloaded_on_disk']}</td>"
                    f"<td class='num'>{p['bytes_on_disk']}</td>"
                    f"<td><div class='bar' style='width:{pct:.1f}%'></div></td>"
                    f"<td>{p['license']}</td>"
                    "</tr>"
                )
            html = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<title>FAW R1A Status</title>"
                "<style>"
                "body{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;}"
                "h1{margin-bottom:.2em}"
                ".summary{color:#666;margin-bottom:1em}"
                "table{border-collapse:collapse;width:100%}"
                "th,td{padding:.4em .6em;border-bottom:1px solid #eee;text-align:left}"
                "td.num{text-align:right;font-variant-numeric:tabular-nums}"
                ".bar{background:#4a90e2;height:14px;border-radius:2px}"
                ".b-green{background:#2e7d32;color:#fff;padding:2px 8px;border-radius:3px;font-size:.8em}"
                ".b-red{background:#c62828;color:#fff;padding:2px 8px;border-radius:3px;font-size:.8em}"
                ".b-grey{background:#9e9e9e;color:#fff;padding:2px 8px;border-radius:3px;font-size:.8em}"
                "</style></head><body>"
                "<h1>FAW R1A Provider Status</h1>"
                "<p class='summary'>"
                f"Total providers: {len(providers_state)} "
                f"(no-key: {no_key_count}; keyed: {key_set + key_unset}; "
                f"keys set: {key_set}/{key_set + key_unset}) "
                f"&middot; manifests on disk: {manifests_scanned} "
                f"&middot; total bytes: {total_bytes:,}"
                "</p>"
                "<table>"
                "<thead><tr>"
                "<th>Provider</th><th>Env</th><th>Manifests</th><th>Downloaded</th>"
                "<th>Bytes</th><th>Bytes proportion</th><th>License</th>"
                "</tr></thead><tbody>"
                + "".join(rows_html)
                + "</tbody></table>"
                f"<p class='summary'>Manual drop root: <code>{scan_root}</code></p>"
                "</body></html>"
            )
            html_path.write_text(html, encoding="utf-8")
        except Exception as exc:
            msg = f"html_write_failed: {exc}"
            print(f"library_r1a_status_error={msg}")
            raise typer.Exit(code=1)
        print(f"library_r1a_status_html_path={html_path}")
        return

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    print(f"library_r1a_status_manual_drop_root={scan_root}")
    print(f"library_r1a_status_manifests_scanned={manifests_scanned}")
    print(f"library_r1a_status_providers_total={len(providers_state)}")
    print(f"library_r1a_status_providers_no_key={no_key_count}")
    print(f"library_r1a_status_providers_key_set={key_set}/{key_set + key_unset}")
    print(f"library_r1a_status_total_downloaded_on_disk={total_downloaded}")
    print(f"library_r1a_status_total_bytes_on_disk={total_bytes}")
    print()
    print("Per-provider:")
    for p in providers_state:
        env = "(no key)" if p["env_var"] is None else (
            "SET   " if p["env_set"] else "unset ")
        print(
            f"  {p['id']:13s}  env={env}  "
            f"manifests={p['manifests_on_disk']:2d}  "
            f"downloaded={p['downloaded_on_disk']:4d}  "
            f"bytes={p['bytes_on_disk']:>12d}  "
            f"{p['license']}"
        )

    # v1.13.s90 — ASCII bars: proportional downloaded-bytes per provider.
    if bars:
        max_bytes = max((p["bytes_on_disk"] for p in providers_state), default=0)
        BAR_WIDTH = 40
        print()
        print("Bytes-on-disk proportion (40-char bars):")
        if max_bytes == 0:
            print("  (no downloads recorded yet; bars are all empty)")
        for p in providers_state:
            b = p["bytes_on_disk"]
            if max_bytes > 0:
                fill = int(round(BAR_WIDTH * b / max_bytes))
            else:
                fill = 0
            bar = "#" * fill + "-" * (BAR_WIDTH - fill)
            print(f"  {p['id']:13s} [{bar}] {b:>12d} B")


# --------------------------------------------------------------------------- #
# library install-r1a-pack  (v1.14.s103)
# --------------------------------------------------------------------------- #

@app.command("install-r1a-pack")
def install_r1a_pack_cmd(
    manifest_path: Annotated[
        Path,
        typer.Argument(help="Path to an R1A manifest JSON (e.g. met_museum_manifest.json)."),
    ],
    library_root: Annotated[
        Path,
        typer.Option(
            "--library-root",
            help="Library destination root (default: ./Library/).",
        ),
    ] = Path("Library"),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be installed; copy nothing."),
    ] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Install R1A manifest entries into the Library/ directory (Path B v1.14.s103).

    Reads an R1A `*_manifest.json` (written by any R1A runner) and copies
    each entry's local_path into:
      <library-root>/<source>/<pack_id>/<filename>

    Registers each installed file as a row in Library/asset_library.json with
    keys: name, category, source, license, attribution, file_path, original_url.

    Examples:
      assetboy library install-r1a-pack <manual_drop>/met_museum/MY_PACK/met_museum_manifest.json
      assetboy library install-r1a-pack mf.json --library-root C:/proj/Library --dry-run
    """
    import shutil

    if not manifest_path.exists():
        msg = f"manifest_not_found: {manifest_path}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"library_install_r1a_pack_error={msg}")
        raise typer.Exit(code=1)

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        msg = f"manifest_unparseable: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"library_install_r1a_pack_error={msg}")
        raise typer.Exit(code=1)

    source = str(manifest.get("source", "unknown"))
    pack_id = str(manifest.get("pack_id", "unknown"))
    entries = manifest.get("entries") or []
    license_str = str(manifest.get("license", "")
                      or manifest.get("license_policy", "")
                      or manifest.get("use_policy_notice", ""))

    dest_dir = library_root / source / pack_id
    asset_lib_file = library_root / "asset_library.json"

    installed: list[dict] = []
    skipped: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        local = entry.get("local_path")
        if not local:
            skipped.append({"reason": "no_local_path", "entry_id": str(entry.get("identifier") or entry.get("id") or entry.get("object_id") or "")})
            continue
        src_file = Path(local)
        if not src_file.exists():
            skipped.append({"reason": "source_file_missing", "path": local})
            continue
        # Skip entries explicitly marked not downloaded.
        if entry.get("downloaded") is False and not dry_run:
            skipped.append({"reason": "not_downloaded", "path": local})
            continue

        dest_file = dest_dir / src_file.name
        record = {
            "name": entry.get("title") or entry.get("name") or src_file.stem,
            "category": str(manifest.get("kind", source)),
            "source": source,
            "license": license_str,
            "attribution": str(entry.get("attribution_text") or entry.get("attribution") or ""),
            "file_path": str(dest_file),
            "original_url": str(entry.get("source_url") or entry.get("url") or ""),
            "pack_id": pack_id,
        }

        if dry_run:
            installed.append({**record, "dry_run": True})
            continue

        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src_file, dest_file)
            installed.append(record)
        except Exception as exc:
            skipped.append({"reason": f"copy_failed: {exc}", "path": local})

    # Register installed assets in asset_library.json (additive).
    if not dry_run and installed:
        existing: list[dict] = []
        if asset_lib_file.exists():
            try:
                existing = json.loads(asset_lib_file.read_text(encoding="utf-8")) or []
            except Exception:
                existing = []
        if not isinstance(existing, list):
            existing = []
        existing.extend(installed)
        asset_lib_file.parent.mkdir(parents=True, exist_ok=True)
        asset_lib_file.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    summary = {
        "ok": True,
        "manifest_path": str(manifest_path),
        "source": source,
        "pack_id": pack_id,
        "library_root": str(library_root),
        "dest_dir": str(dest_dir),
        "asset_library_file": str(asset_lib_file),
        "entries_total": len(entries),
        "installed": len(installed),
        "skipped": len(skipped),
        "skipped_details": skipped,
        "dry_run": dry_run,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"library_install_r1a_pack_source={source}")
        print(f"library_install_r1a_pack_pack_id={pack_id}")
        print(f"library_install_r1a_pack_dest_dir={dest_dir}")
        print(f"library_install_r1a_pack_entries_total={len(entries)}")
        print(f"library_install_r1a_pack_installed={len(installed)}")
        print(f"library_install_r1a_pack_skipped={len(skipped)}")
        print(f"library_install_r1a_pack_dry_run={dry_run}")
        if skipped:
            print("Skipped:")
            for s in skipped:
                print(f"  - {s.get('reason', '?')}: {s.get('path', s.get('entry_id', '?'))}")


if __name__ == "__main__":
    app()
