"""Epic Games / Fab vault sub-app for assetboy CLI.

Wraps ``providers/epic_vault.py``. Local Epic Launcher inventory + online
catalog state. No browser drive (use FAW's online routes for that).

Commands:
    epic status     -- show SQLite schema version + cached vault item count
    epic inventory  -- list local Fab/Marketplace cached vault items
    epic catalog    -- query online Epic catalog API (slower; needs auth)
"""

from __future__ import annotations

import json
import sqlite3
import sys
from typing import Annotated

import typer

app = typer.Typer(
    name="epic",
    help="Epic Launcher vault + online catalog.",
    add_completion=False,
    no_args_is_help=True,
)


# --------------------------------------------------------------------------- #
# epic status
# --------------------------------------------------------------------------- #

@app.command("status")
def status_cmd(
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Show Epic Launcher local SQLite schema version + row count. No network."""
    from assetboy.providers.epic_vault import default_local_fab_library_db_path

    try:
        db_path = default_local_fab_library_db_path()
    except Exception as exc:
        msg = f"path_resolve_failed: {exc}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"epic_status_error={msg}")
        raise typer.Exit(code=1)

    if not db_path.exists():
        msg = f"vault_db_not_found: {db_path}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"epic_status_error={msg}")
        raise typer.Exit(code=1)

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            count = conn.execute(
                "SELECT COUNT(*) FROM local_listing"
            ).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        msg = f"schema_drift: {exc}"
        if json_out:
            json.dump({"error": msg, "db_path": str(db_path)}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"epic_status_error={msg}")
        raise typer.Exit(code=1)

    payload = {
        "db_path": str(db_path),
        "schema_version": user_version,
        "vault_item_count": count,
    }
    if json_out:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for k, v in payload.items():
            print(f"epic_status_{k}={v}")


# --------------------------------------------------------------------------- #
# epic inventory
# --------------------------------------------------------------------------- #

@app.command("inventory")
def inventory_cmd(
    limit: Annotated[
        int, typer.Option("--limit", help="Max rows to display."),
    ] = 50,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Build + display local Epic vault inventory report."""
    from assetboy.providers.epic_vault import build_local_epic_library_report

    try:
        report = build_local_epic_library_report()
    except Exception as exc:
        msg = str(exc)
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"epic_inventory_error={msg}")
        raise typer.Exit(code=1)

    if json_out:
        json.dump(report, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    # Plain-text summary
    listings = report.get("listings") or report.get("items") or []
    print(f"epic_inventory_count={len(listings)}")
    for idx, item in enumerate(listings[:limit], start=1):
        uid = item.get("listing_uid") or item.get("uid") or item.get("id", "")
        title = item.get("title", "")
        kind = item.get("kind") or item.get("listing_type", "")
        print(
            f"epic_inventory_entry={idx}  "
            f"uid={uid}  kind={kind}  title={title!r}"
        )


# --------------------------------------------------------------------------- #
# epic catalog
# --------------------------------------------------------------------------- #

@app.command("catalog")
def catalog_cmd(
    limit: Annotated[
        int, typer.Option("--limit", help="Max rows to fetch."),
    ] = 25,
    timeout: Annotated[
        float, typer.Option("--timeout", help="HTTP timeout in seconds."),
    ] = 30.0,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Query online Epic catalog. May require valid auth in environment."""
    from assetboy.providers.epic_vault import build_online_epic_library_map

    try:
        report = build_online_epic_library_map(limit=limit, timeout=timeout)
    except Exception as exc:
        msg = str(exc)
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"epic_catalog_error={msg}")
        raise typer.Exit(code=1)

    if json_out:
        json.dump(report, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    items = report.get("items") or report.get("listings") or []
    print(f"epic_catalog_count={len(items)}")
    for idx, item in enumerate(items[:limit], start=1):
        uid = item.get("uid") or item.get("id", "")
        title = item.get("title") or item.get("name", "")
        print(f"epic_catalog_entry={idx}  uid={uid}  title={title!r}")


if __name__ == "__main__":
    app()
