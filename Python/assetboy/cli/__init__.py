"""Typer-based CLI for assetboy (Path B s5+).

Replaces the 8500-line ``cli.py`` god-object incrementally:
  s5  -- fab + library + import sub-apps
  s6  -- unity + epic + gen sub-apps
  s10 -- delete old cli.py; this becomes the only entry point

Entry point:
    python -m assetboy.cli <subapp> <command> [args]
or equivalently:
    python -m assetboy <subapp> <command>   (if __main__.py is wired up)

Sub-apps in this slice:
    fab        -- Fab.com auth + library + download
    library    -- local FAW asset library search/install/ready
    import     -- direct file import to Flax via :8790 server

Each sub-app is a single self-contained file (cli/fab.py, cli/library.py,
cli/import_cmd.py). They wrap the existing provider/runner functions --
no logic re-implementation, just thin Typer-friendly facades.
"""

from assetboy.cli.app import app

__all__ = ["app"]
