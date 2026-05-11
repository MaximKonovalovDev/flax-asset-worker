"""Unity Asset Store sub-app for assetboy CLI.

Wraps the existing ``providers/unity_hub.py`` + ``providers/unity_runner.py``
surfaces. No logic duplication.

Commands:
    unity status         -- inspect Unity Hub + DPAPI token state (no network)
    unity list-installs  -- list detected Unity Editor installations
    unity owned          -- enumerate Unity Asset Store owned packages (auth)
    unity download       -- download a single owned package by product_id
"""

from __future__ import annotations

import json
import sys
from typing import Annotated

import typer

app = typer.Typer(
    name="unity",
    help="Unity Asset Store auth + owned-package enumeration + download.",
    add_completion=False,
    no_args_is_help=True,
)


def _emit(payload: dict, *, json_out: bool, prefix: str) -> None:
    if json_out:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for k, v in payload.items():
            if isinstance(v, bool):
                v = "true" if v else "false"
            print(f"{prefix}_{k}={v}")


# --------------------------------------------------------------------------- #
# unity status
# --------------------------------------------------------------------------- #

@app.command("status")
def status_cmd(
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Inspect Unity Hub + DPAPI token state. No network calls.

    Reports whether Local State + encryptedTokens.json exist, whether the
    DPAPI master key can be unwrapped, and whether the resulting access
    token is non-empty.
    """
    from assetboy.providers.unity_hub import (
        DEFAULT_UNITY_HUB_LOCAL_STATE_PATH,
        DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH,
        build_unity_hub_status,
    )

    payload = {
        "local_state_path": str(DEFAULT_UNITY_HUB_LOCAL_STATE_PATH),
        "local_state_exists": DEFAULT_UNITY_HUB_LOCAL_STATE_PATH.exists(),
        "tokens_path": str(DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH),
        "tokens_exist": DEFAULT_UNITY_HUB_ENCRYPTED_TOKENS_PATH.exists(),
    }
    try:
        status = build_unity_hub_status()
        if isinstance(status, dict):
            payload.update(
                {
                    "decrypt_ok": bool(status.get("decrypt_ok", False)),
                    "access_token_present": bool(
                        status.get("access_token_present", False)
                    ),
                }
            )
    except Exception as exc:
        payload["error"] = str(exc)

    _emit(payload, json_out=json_out, prefix="unity_status")
    if not payload.get("access_token_present", False):
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# unity list-installs
# --------------------------------------------------------------------------- #

@app.command("list-installs")
def list_installs_cmd(
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """List detected Unity Editor installations on this machine."""
    from assetboy.providers.unity_runner import list_unity_installations

    try:
        installs = list_unity_installations() or []
    except Exception as exc:
        if json_out:
            json.dump({"error": str(exc)}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"unity_list_error={exc}")
        raise typer.Exit(code=1)

    if json_out:
        # UnityInstallation is a dataclass; convert to plain dicts
        payload = []
        for inst in installs:
            d = {}
            for k in ("version", "path", "executable", "platform"):
                if hasattr(inst, k):
                    d[k] = str(getattr(inst, k))
            payload.append(d)
        json.dump({"installs": payload, "count": len(payload)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"unity_install_count={len(installs)}")
        for idx, inst in enumerate(installs, start=1):
            version = getattr(inst, "version", "?")
            path = getattr(inst, "path", getattr(inst, "executable", "?"))
            print(f"unity_install_entry={idx}  version={version}  path={path}")


# --------------------------------------------------------------------------- #
# unity owned
# --------------------------------------------------------------------------- #

@app.command("owned")
def owned_cmd(
    limit: Annotated[
        int, typer.Option("--limit", help="Max records to fetch."),
    ] = 25,
    timeout: Annotated[
        float, typer.Option("--timeout", help="HTTP timeout in seconds."),
    ] = 20.0,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Enumerate Unity Asset Store owned packages via authenticated API."""
    from assetboy.providers.unity_hub import (
        list_unity_owned_assets,
        load_unity_hub_tokens,
    )

    try:
        tokens = load_unity_hub_tokens()
    except Exception as exc:
        if json_out:
            json.dump({"error": f"token_load_failed: {exc}"}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"unity_owned_error=token_load_failed: {exc}")
        raise typer.Exit(code=1)

    if not tokens or not tokens.get("accessToken"):
        msg = "no_access_token (open Unity Hub + sign in to refresh)"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"unity_owned_error={msg}")
        raise typer.Exit(code=1)

    try:
        payload = list_unity_owned_assets(rows=limit, tokens=tokens, timeout=timeout)
    except Exception as exc:
        if json_out:
            json.dump({"error": str(exc)}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"unity_owned_error={exc}")
        raise typer.Exit(code=1)

    results = payload.get("results") or []
    if json_out:
        json.dump(
            {"results": results[:limit], "count": len(results)},
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        print(f"unity_owned_count={len(results)}")
        for idx, entry in enumerate(results[:limit], start=1):
            pid = entry.get("packageId") or entry.get("id", "")
            name = entry.get("name") or entry.get("title", "")
            print(f"unity_owned_entry={idx}  product_id={pid}  name={name!r}")


# --------------------------------------------------------------------------- #
# unity download
# --------------------------------------------------------------------------- #

@app.command("download")
def download_cmd(
    product_id: Annotated[
        str, typer.Argument(help="Unity Asset Store product ID (numeric)."),
    ],
    timeout: Annotated[
        float, typer.Option("--timeout", help="Download timeout in seconds."),
    ] = 300.0,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Download a single owned Unity package by product_id."""
    from assetboy.providers.unity_hub import (
        download_unity_owned_package,
        load_unity_hub_tokens,
    )

    try:
        tokens = load_unity_hub_tokens()
    except Exception as exc:
        if json_out:
            json.dump({"error": f"token_load_failed: {exc}"}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"unity_download_error=token_load_failed: {exc}")
        raise typer.Exit(code=1)

    if not tokens or not tokens.get("accessToken"):
        msg = "no_access_token"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"unity_download_error={msg}")
        raise typer.Exit(code=1)

    try:
        result = download_unity_owned_package(
            product_id=product_id, tokens=tokens, timeout=timeout
        )
    except Exception as exc:
        if json_out:
            json.dump({"error": str(exc), "product_id": product_id}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"unity_download_error={exc}")
            print(f"unity_download_product_id={product_id}")
        raise typer.Exit(code=1)

    payload = {
        "product_id": product_id,
        "status": "ok",
        "result": str(result) if not isinstance(result, dict) else "ok",
    }
    if isinstance(result, dict):
        for k in ("path", "name", "size_bytes"):
            if k in result:
                payload[k] = str(result[k])
    _emit(payload, json_out=json_out, prefix="unity_download")


if __name__ == "__main__":
    app()
