"""Import sub-app: drop a file (or watch a folder) into Flax Content/.

This is the simplest possible bridge -- we hit the FAW C# server's
``/api/v1/library/install`` route with ``provider="local"`` semantics:

- ``import <file>`` POSTs `{asset_id, provider="local", local_path}` and
  the C# server copies into Content/ImportedAssets/.
- ``import --watch <folder>`` polls the folder for new files and imports
  each. Single-process, no background thread. Use Ctrl+C to stop.

Commands:
    import file <path>        -- one-shot import of a single file
    import watch <folder>     -- poll a folder forever
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Annotated

import typer

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None  # type: ignore[assignment]

DEFAULT_BASE = "http://localhost:8790"

# Extensions FAW currently handles natively.
SUPPORTED_EXT = {
    ".fbx", ".obj", ".glb", ".gltf",
    ".png", ".jpg", ".jpeg", ".tga", ".exr", ".hdr",
    ".wav", ".ogg", ".mp3",
}

app = typer.Typer(
    name="import",
    help="Import a file (or watch a folder) into Flax Content via FAW :8790.",
    add_completion=False,
    no_args_is_help=True,
)


def _post(path: str, payload: dict, *, base: str, timeout: float = 60.0) -> dict:
    if requests is None:
        raise RuntimeError("requests not installed")
    r = requests.post(f"{base}{path}", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json() if r.content else {}


def _import_one(file_path: Path, *, base: str, json_out: bool) -> int:
    """Import a single file. Returns shell exit code (0 ok, 1 fail)."""
    if not file_path.exists():
        msg = f"file_not_found: {file_path}"
        print(json.dumps({"error": msg}) if json_out else f"import_error={msg}")
        return 1
    if file_path.suffix.lower() not in SUPPORTED_EXT:
        msg = f"unsupported_ext: {file_path.suffix}"
        print(json.dumps({"error": msg}) if json_out else f"import_error={msg}")
        return 1

    payload = {
        "asset_id": file_path.stem,
        "provider": "local",
        "category": _guess_category(file_path.suffix),
        "name": file_path.stem,
        "local_path": str(file_path.resolve()),
    }
    try:
        data = _post("/api/v1/library/install", payload, base=base)
    except Exception as exc:
        msg = str(exc)
        print(
            json.dumps({"error": msg, "file": str(file_path)})
            if json_out
            else f"import_error={msg}"
        )
        return 1

    if json_out:
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for k, v in (data or {}).items():
            print(f"import_{k}={v}")
        print(f"import_source={file_path}")
    return 0


def _guess_category(suffix: str) -> str:
    s = suffix.lower()
    if s in {".fbx", ".obj", ".glb", ".gltf"}:
        return "model"
    if s in {".hdr", ".exr"}:
        return "hdr"
    if s in {".wav", ".ogg", ".mp3"}:
        return "audio"
    return "texture"


# --------------------------------------------------------------------------- #
# import file <path>
# --------------------------------------------------------------------------- #

@app.command("file")
def file_cmd(
    file_path: Annotated[
        Path,
        typer.Argument(
            help="Path to a single FBX/OBJ/GLB/PNG/WAV file to import.",
            exists=False,  # we check ourselves to give a clean error
        ),
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
    """Import a single file into Flax Content/."""
    rc = _import_one(file_path, base=base, json_out=json_out)
    if rc:
        raise typer.Exit(code=rc)


# --------------------------------------------------------------------------- #
# import watch <folder>
# --------------------------------------------------------------------------- #

@app.command("watch")
def watch_cmd(
    folder: Annotated[
        Path,
        typer.Argument(help="Folder to poll for new files."),
    ],
    interval: Annotated[
        float,
        typer.Option("--interval", help="Polling interval in seconds."),
    ] = 5.0,
    base: Annotated[
        str,
        typer.Option("--server", help="FAW server base URL."),
    ] = DEFAULT_BASE,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON output per imported file."),
    ] = False,
) -> None:
    """Poll a folder, import every new SUPPORTED_EXT file. Ctrl+C to stop.

    Crashes loud if the folder doesn't exist. Otherwise loops forever; each
    cycle scans + imports anything not seen yet (tracked by file mtime).
    """
    if not folder.exists():
        print(f"import_watch_error=folder_not_found: {folder}")
        raise typer.Exit(code=1)
    if not folder.is_dir():
        print(f"import_watch_error=not_a_directory: {folder}")
        raise typer.Exit(code=1)

    seen_mtimes: dict[Path, float] = {}
    print(f"import_watch_start  folder={folder}  interval={interval}s  server={base}")
    try:
        while True:
            for p in folder.iterdir():
                if not p.is_file():
                    continue
                if p.suffix.lower() not in SUPPORTED_EXT:
                    continue
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    continue
                if seen_mtimes.get(p) == mtime:
                    continue
                seen_mtimes[p] = mtime
                print(f"import_watch_seen={p.name}")
                _import_one(p, base=base, json_out=json_out)
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\nimport_watch_stop  imported_count={len(seen_mtimes)}")


if __name__ == "__main__":
    app()
