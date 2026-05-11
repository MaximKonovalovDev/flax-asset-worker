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


if __name__ == "__main__":
    app()
