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


if __name__ == "__main__":
    app()
