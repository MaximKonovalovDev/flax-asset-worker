"""Allow ``python -m assetboy.cli`` to invoke the Typer root."""

from assetboy.cli.app import app

if __name__ == "__main__":
    app()
