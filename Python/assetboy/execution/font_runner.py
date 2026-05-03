"""
font_runner.py — Download CC0/OFL game fonts for all game scopes.

Sources: Google Fonts GitHub (OFL-1.1) and Font Library (CC0/OFL).
All fonts are free for commercial use. No ingame attribution required for OFL.
This runner fits Lane 1 (direct_url) — pure urllib, no Playwright needed.

Usage (via CLI):
    python -m assetboy.cli run-font-batch --use-presets --dry-run
    python -m assetboy.cli run-font-batch --use-presets --tags-filter medieval
    python -m assetboy.cli run-font-batch --pack-id MY_FONT --url <ttf_url>
"""
from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import unquote

from assetboy.library.paths import manual_drop_dir


# ---------------------------------------------------------------------------
# Font preset packs — all OFL-1.1, commercial use OK, direct TTF download
# Format: (pack_id, url, description, tags)
# ---------------------------------------------------------------------------
FONT_PRESETS: list[tuple[str, str, str, list[str]]] = [
    # ── Medieval / Fantasy ───────────────────────────────────────────────────
    (
        "SHARED_FONT_UNCIAL_ONE",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/uncialantiqua/UncialAntiqua-Regular.ttf",
        "Uncial Antiqua — medieval/fantasy display font. OFL. Replaces the removed Uncial One preset source.",
        ["medieval", "fantasy", "display"],
    ),
    (
        "SHARED_FONT_CINZEL",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/cinzel/Cinzel%5Bwght%5D.ttf",
        "Cinzel — Roman/classical serif display font. OFL.",
        ["roman", "classical", "serif", "display"],
    ),
    (
        "SHARED_FONT_CINZEL_DECO",
        "https://github.com/google/fonts/raw/main/ofl/cinzeldecorative/CinzelDecorative-Regular.ttf",
        "Cinzel Decorative — ornate Roman display font. OFL.",
        ["roman", "classical", "display", "ornate"],
    ),
    (
        "SHARED_FONT_MEDIEVAL_SHARP",
        "https://github.com/google/fonts/raw/main/ofl/medievalsharp/MedievalSharp.ttf",
        "MedievalSharp — gothic/horror title font. OFL.",
        ["medieval", "gothic", "horror", "display"],
    ),
    (
        "SHARED_FONT_ALMENDRA",
        "https://github.com/google/fonts/raw/main/ofl/almendradisplay/AlmendraDisplay-Regular.ttf",
        "Almendra Display — fantasy/elf elegant display. OFL.",
        ["fantasy", "elegant", "display"],
    ),
    # ── Sci-Fi / Futuristic ──────────────────────────────────────────────────
    (
        "SHARED_FONT_ORBITRON",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/orbitron/Orbitron%5Bwght%5D.ttf",
        "Orbitron — sci-fi futuristic display font. OFL.",
        ["scifi", "futuristic", "display"],
    ),
    (
        "SHARED_FONT_EXO2",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/exo2/Exo2%5Bwght%5D.ttf",
        "Exo 2 — clean sci-fi UI body font. OFL.",
        ["scifi", "ui", "body"],
    ),
    (
        "SHARED_FONT_RAJDHANI",
        "https://github.com/google/fonts/raw/main/ofl/rajdhani/Rajdhani-Regular.ttf",
        "Rajdhani — compact bold HUD indicator font. OFL.",
        ["hud", "ui", "bold", "compact", "scifi"],
    ),
    # ── Pixel / Retro ────────────────────────────────────────────────────────
    (
        "SHARED_FONT_PRESS_START",
        "https://github.com/google/fonts/raw/main/ofl/pressstart2p/PressStart2P-Regular.ttf",
        "Press Start 2P — pixel/8-bit retro UI font. OFL.",
        ["pixel", "retro", "ui"],
    ),
    # ── Horror / Action ──────────────────────────────────────────────────────
    (
        "SHARED_FONT_PIRATA",
        "https://github.com/google/fonts/raw/main/ofl/pirataone/PirataOne-Regular.ttf",
        "Pirata One — pirate/skull style display. OFL.",
        ["pirate", "horror", "display"],
    ),
    (
        "SHARED_FONT_CREEPSTER",
        "https://github.com/google/fonts/raw/main/ofl/creepster/Creepster-Regular.ttf",
        "Creepster — horror/halloween display. OFL.",
        ["horror", "halloween", "display"],
    ),
    (
        "SHARED_FONT_BANGERS",
        "https://github.com/google/fonts/raw/main/ofl/bangers/Bangers-Regular.ttf",
        "Bangers — comic action title font. OFL.",
        ["comic", "action", "display"],
    ),
    # ── UI / HUD / Body ──────────────────────────────────────────────────────
    (
        "SHARED_FONT_INTER",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf",
        "Inter — clean modern UI/HUD body font. OFL.",
        ["ui", "hud", "body", "modern"],
    ),
    (
        "SHARED_FONT_ROBOTO",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/Roboto%5Bwdth,wght%5D.ttf",
        "Roboto — standard HUD readable body font. OFL.",
        ["ui", "hud", "body"],
    ),
    (
        "SHARED_FONT_CABIN",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/cabin/Cabin%5Bwdth,wght%5D.ttf",
        "Cabin — neutral UI sans-serif body. OFL.",
        ["ui", "body", "neutral"],
    ),
]


@dataclass
class FontRunResult:
    pack_id: str
    source_url: str
    output_dir: Path
    files_downloaded: list[str]
    provenance_path: Path
    dry_run: bool

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "source_url": self.source_url,
            "output_dir": str(self.output_dir),
            "files_downloaded": self.files_downloaded,
            "provenance_path": str(self.provenance_path),
            "dry_run": self.dry_run,
        }


def list_presets() -> list[tuple[str, str, str]]:
    """Return (pack_id, url, description) for all built-in presets."""
    return [(pid, url, desc) for pid, url, desc, _ in FONT_PRESETS]


def run_font_batch(
    *,
    pack_id: str,
    source_url: str,
    output_dir: str | Path | None = None,
    game_scope: str = "shared",
    dry_run: bool = False,
) -> FontRunResult:
    """
    Download a single font file or ZIP from a direct URL.

    Parameters
    ----------
    pack_id      : AssetBoy pack ID (e.g. SHARED_FONT_CINZEL)
    source_url   : Direct .ttf, .otf, or .zip URL
    output_dir   : Where to save. Defaults to manual_drop/fonts/<game_scope>/<pack_id>/
    game_scope   : 'shared' or specific game scope
    dry_run      : If True, print plan without downloading.
    """
    out = (
        Path(output_dir)
        if output_dir is not None
        else manual_drop_dir() / "fonts" / game_scope / pack_id
    )

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[FontRunner | {mode}] Pack: {pack_id}")
    print(f"  URL: {source_url}")
    print(f"  Output: {out}")

    if dry_run:
        print("  [dry-run] Skipping download.")
        return FontRunResult(
            pack_id=pack_id,
            source_url=source_url,
            output_dir=out,
            files_downloaded=[],
            provenance_path=out / "provenance.json",
            dry_run=True,
        )

    out.mkdir(parents=True, exist_ok=True)
    raw = _download_bytes(source_url)
    downloaded: list[str] = []

    if source_url.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for member in zf.infolist():
                if member.filename.lower().endswith((".ttf", ".otf", ".woff", ".woff2")):
                    dest = out / Path(member.filename).name
                    dest.write_bytes(zf.read(member))
                    downloaded.append(dest.name)
    else:
        fname = unquote(source_url.split("/")[-1])
        (out / fname).write_bytes(raw)
        downloaded.append(fname)

    print(f"  Downloaded {len(downloaded)} file(s).")
    provenance_path = _write_provenance(out, pack_id=pack_id, source_url=source_url,
                                         game_scope=game_scope, files=downloaded)
    return FontRunResult(
        pack_id=pack_id,
        source_url=source_url,
        output_dir=out,
        files_downloaded=downloaded,
        provenance_path=provenance_path,
        dry_run=False,
    )


def run_font_presets(
    *,
    game_scope: str = "shared",
    dry_run: bool = False,
    tags_filter: list[str] | None = None,
) -> list[FontRunResult]:
    """Run all built-in font presets, optionally filtered by tags."""
    results = []
    for pack_id, url, desc, tags in FONT_PRESETS:
        if tags_filter and not any(t in tags for t in tags_filter):
            continue
        print(f"\n--- {desc} ---")
        results.append(run_font_batch(
            pack_id=pack_id,
            source_url=url,
            game_scope=game_scope,
            dry_run=dry_run,
        ))
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _download_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AssetBoy/1.0 (asset pipeline; OFL/CC0 fonts)"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _write_provenance(
    out_dir: Path,
    *,
    pack_id: str,
    source_url: str,
    game_scope: str,
    files: list[str],
) -> Path:
    provenance = {
        "schema_version": "assetboy.provenance.v1",
        "pack_id": pack_id,
        "game_scope": game_scope,
        "source_url": source_url,
        "license": "OFL-1.1",
        "license_notes": (
            "SIL Open Font License 1.1. Free for commercial use. "
            "No ingame attribution required. Embedding in software is allowed."
        ),
        "author": "Google Fonts / various contributors",
        "author_url": "https://fonts.google.com",
        "files": files,
        "download_date": date.today().isoformat(),
        "source_adapter": "font_direct_url",
        "lane": "direct_url",
    }
    path = out_dir / "provenance.json"
    path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"  Provenance written: {path}")
    return path
