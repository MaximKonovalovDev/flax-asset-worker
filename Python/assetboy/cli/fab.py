"""Fab.com sub-app for assetboy CLI.

Wraps the existing ``providers/fab_hybrid.py`` surface. No logic duplication --
this module is a thin Typer-friendly facade. Original handlers live in
``cli.py`` (s5 leaves the old cli.py in parallel; s10 will delete it).

Commands:
    fab auth          -- establish Fab session (browser or reuse profile)
    fab auth-status   -- inspect saved session state on disk
    fab download      -- download one asset from a known listing
    fab library       -- list/sample owned Fab listings via /i/library/search
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated

import typer

app = typer.Typer(
    name="fab",
    help="Fab.com auth + library + download.",
    add_completion=False,
    no_args_is_help=True,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_downloader(debug: bool = False):
    """Construct a FabHybridDownloader. Lazy import for fast --help."""
    from assetboy.providers.fab_hybrid import FabHybridDownloader

    return FabHybridDownloader(debug=debug)


def _emit(payload: dict, *, json_out: bool) -> None:
    """Print a result either as JSON (for tooling) or `key=value` (legacy)."""
    if json_out:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for k, v in payload.items():
            if isinstance(v, bool):
                v = "true" if v else "false"
            print(f"fab_{k}={v}")


# --------------------------------------------------------------------------- #
# fab auth
# --------------------------------------------------------------------------- #

@app.command("auth")
def auth_cmd(
    reuse_profile: Annotated[
        bool,
        typer.Option(
            "--reuse-profile",
            help="Reuse the shared Chrome profile (safe path; no visible window).",
        ),
    ] = False,
    allow_browser: Annotated[
        bool,
        typer.Option(
            "--allow-browser",
            help="Open a visible Fab login window. Required for first-time auth.",
        ),
    ] = False,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="Seconds to wait for browser session."),
    ] = 240.0,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of key=value."),
    ] = False,
) -> None:
    """Establish a Fab.com session and persist auth state to disk.

    Default refuses to do anything dangerous: use --reuse-profile for the
    safe path or --allow-browser to open a real browser window.
    """
    if not reuse_profile and not allow_browser:
        _emit(
            {"auth_error": "Browser launch blocked by default. Use --reuse-profile or --allow-browser."},
            json_out=json_out,
        )
        raise typer.Exit(code=1)

    downloader = _make_downloader()
    try:
        with downloader.auth_lock():
            if reuse_profile:
                state = asyncio.run(
                    downloader.refresh_auth_from_profile(timeout_seconds=timeout)
                )
            else:
                state = asyncio.run(
                    downloader.acquire_session_interactive(timeout_seconds=timeout)
                )
    except Exception as exc:
        _emit({"auth_error": str(exc)}, json_out=json_out)
        raise typer.Exit(code=1)

    session = downloader.create_cffi_session(state)
    if downloader.is_authenticated(session):
        _emit(
            {
                "auth_status": "authenticated",
                "auth_saved": str(downloader.auth_state_path),
            },
            json_out=json_out,
        )
        return

    _emit(
        {
            "auth_error": "Saved session still unauthenticated. Finish login + rerun fab auth.",
            "auth_saved": str(downloader.auth_state_path),
        },
        json_out=json_out,
    )
    raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# fab auth-status
# --------------------------------------------------------------------------- #

@app.command("auth-status")
def auth_status_cmd(
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of key=value."),
    ] = False,
) -> None:
    """Inspect persisted Fab session state. No network calls."""
    downloader = _make_downloader()
    status = downloader.auth_status()
    payload = {
        "auth_state_path": str(status["auth_state_path"]),
        "auth_state_exists": bool(status["auth_state_exists"]),
        "browser_profile_dir": str(status["browser_profile_dir"]),
        "browser_profile_has_state": bool(status["browser_profile_has_state"]),
        "authenticated": bool(status["authenticated"]),
    }
    _emit(payload, json_out=json_out)
    if not status["authenticated"]:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# fab download
# --------------------------------------------------------------------------- #

@app.command("download")
def download_cmd(
    listing_uid: Annotated[
        str,
        typer.Argument(help="Fab listing UID (the long hex/dash identifier)."),
    ],
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="HTTP timeout in seconds."),
    ] = 30.0,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Download a single Fab asset by listing UID.

    Requires `fab auth` to have run successfully first.
    """
    downloader = _make_downloader()
    auth_state = downloader.load_auth_state()
    if not auth_state:
        _emit(
            {"download_error": "no_auth_state_run_fab_auth"},
            json_out=json_out,
        )
        raise typer.Exit(code=1)

    session = downloader.create_cffi_session(auth_state)
    if not downloader.is_authenticated(session):
        _emit(
            {"download_error": "auth_expired_run_fab_auth_again"},
            json_out=json_out,
        )
        raise typer.Exit(code=1)

    try:
        result = downloader.download_listing(
            session=session, listing_uid=listing_uid, timeout_seconds=timeout
        )
    except Exception as exc:
        _emit({"download_error": str(exc)}, json_out=json_out)
        raise typer.Exit(code=1)

    _emit(
        {
            "listing_uid": listing_uid,
            "download_status": "ok",
            "download_path": str(result),
        },
        json_out=json_out,
    )


# --------------------------------------------------------------------------- #
# fab library
# --------------------------------------------------------------------------- #

@app.command("library")
def library_cmd(
    limit: Annotated[
        int,
        typer.Option("--limit", help="Max records to fetch from page 1."),
    ] = 25,
    timeout: Annotated[
        float,
        typer.Option("--timeout", help="HTTP timeout in seconds."),
    ] = 15.0,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """List owned Fab listings (page 1, cursor-paginated upstream)."""
    from assetboy.providers.fab_hybrid import fetch_fab_library_page

    downloader = _make_downloader()
    auth_state = downloader.load_auth_state()
    if not auth_state:
        _emit(
            {"library_error": "no_auth_state_run_fab_auth"},
            json_out=json_out,
        )
        raise typer.Exit(code=1)

    session = downloader.create_cffi_session(auth_state)
    try:
        payload = fetch_fab_library_page(session, timeout_seconds=timeout)
    except Exception as exc:
        _emit({"library_error": str(exc)}, json_out=json_out)
        raise typer.Exit(code=1)

    results = (payload.get("results") or [])[:limit]
    if json_out:
        json.dump(
            {"results": results, "count": len(results), "next": payload.get("next")},
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        print(f"fab_library_count={len(results)}")
        for idx, entry in enumerate(results, start=1):
            listing = (entry or {}).get("listing") or {}
            uid = listing.get("uid", "")
            title = listing.get("title", "")
            print(f"fab_library_entry={idx}  uid={uid}  title={title!r}")
        if payload.get("next"):
            print(f"fab_library_next_cursor={payload['next']}")


if __name__ == "__main__":
    app()
