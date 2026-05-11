"""Typer root for assetboy CLI.

Composes the per-domain sub-apps into a single ``app`` so the user types:

    python -m assetboy.cli fab auth
    python -m assetboy.cli library search "stone wall"
    python -m assetboy.cli import C:/downloads/oak.fbx

Sub-app additions in future slices land here as one line + one import.
"""

from __future__ import annotations

import typer

from assetboy.cli import epic as _epic
from assetboy.cli import fab as _fab
from assetboy.cli import gen as _gen
from assetboy.cli import import_cmd as _import_cmd
from assetboy.cli import library as _library
from assetboy.cli import pack as _pack
from assetboy.cli import unity as _unity

app = typer.Typer(
    name="assetboy",
    help=(
        "AssetBoy CLI (Path B Typer rewrite). 7 sub-apps shipped: "
        "fab, library, import, unity, epic, gen, pack."
    ),
    add_completion=False,
    rich_markup_mode="rich",
    no_args_is_help=True,
)

app.add_typer(_fab.app, name="fab", help="Fab.com auth + library + download.")
app.add_typer(
    _library.app,
    name="library",
    help="Local FAW asset library: search, install, ready, audit.",
)
# `import` is a Python keyword; expose under that name in Typer but the module
# file is `import_cmd.py` to avoid the import-shadowing trap.
app.add_typer(
    _import_cmd.app,
    name="import",
    help="Import a file (or watch a folder) into Flax content via FAW :8790.",
)
app.add_typer(
    _unity.app,
    name="unity",
    help="Unity Asset Store auth + owned-package enumeration + download.",
)
app.add_typer(
    _epic.app,
    name="epic",
    help="Epic Launcher vault + online catalog.",
)
app.add_typer(
    _gen.app,
    name="gen",
    help="AI generation via local ComfyUI or stable-diffusion.cpp.",
)
app.add_typer(
    _pack.app,
    name="pack",
    help="YAML-recipe-driven pack pipeline runs (Path B s8 recipes).",
)


@app.callback()
def _root() -> None:
    """AssetBoy -- modular asset pipeline for Flax Engine."""


if __name__ == "__main__":
    app()
