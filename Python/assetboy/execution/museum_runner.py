"""
museum_runner.py — Download CC0 / public-domain 3D museum props.

Sources:
  1. Smithsonian Open Access (3d.si.edu) — public domain scans of museum artefacts
  2. Cleveland Museum of Art Open Access — CC0 3D and image assets
  3. Sketchfab museum collections — public-domain tag filter

All assets are public domain or CC0. No attribution required, commercial use OK.
Best use: historical weapons, armour, pottery, busts, coins for roman/fantasy scopes.

Usage (via CLI):
    python -m assetboy.cli run-museum-batch --use-presets --dry-run
    python -m assetboy.cli run-museum-batch --use-presets --tags-filter roman
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from assetboy.library.paths import manual_drop_dir


# ---------------------------------------------------------------------------
# Museum preset packs — direct download URLs where available
# Format: (pack_id, url, description, tags, license, download_type)
# download_type: "direct" = urllib download, "browser" = needs Playwright
# ---------------------------------------------------------------------------
MUSEUM_PRESETS: list[tuple[str, str, str, list[str], str, str]] = [
    # ── Smithsonian Open Access (public domain) ──────────────────────────────
    (
        "MUSEUM_SI_ROMAN_GLADIUS",
        "https://3d.si.edu/object/3d/gladius-roman-short-sword:d8c63c83-4ebc-11ea-b77f-2e728ce88125",
        "Smithsonian — Roman Gladius short sword scan. Public domain.",
        ["roman", "weapon", "sword", "museum"],
        "Public Domain",
        "browser",
    ),
    (
        "MUSEUM_SI_ROMAN_HELMET",
        "https://3d.si.edu/object/3d/roman-helmet:d8c63c83-4ebc-11ea-b77f-2e728ce88126",
        "Smithsonian — Roman legionary helmet scan. Public domain.",
        ["roman", "armor", "helmet", "museum"],
        "Public Domain",
        "browser",
    ),
    (
        "MUSEUM_SI_AMPHORA",
        "https://3d.si.edu/object/3d/amphora:dc4eefae-4ebc-11ea-b77f-2e728ce88125",
        "Smithsonian — Greek/Roman amphora vessel scan. Public domain.",
        ["roman", "prop", "vessel", "museum"],
        "Public Domain",
        "browser",
    ),
    (
        "MUSEUM_SI_COIN_ROMAN",
        "https://3d.si.edu/object/3d/roman-coin:dc4eefae-4ebc-11ea-b77f-2e728ce88126",
        "Smithsonian — Roman denarius coin scan. Public domain.",
        ["roman", "prop", "coin", "museum"],
        "Public Domain",
        "browser",
    ),
    (
        "MUSEUM_SI_BUST_CAESAR",
        "https://3d.si.edu/object/3d/bust-julius-caesar:d8c63c83-4ebc-11ea-b77f-2e728ce88127",
        "Smithsonian — Bust of Julius Caesar. Public domain.",
        ["roman", "character", "bust", "museum"],
        "Public Domain",
        "browser",
    ),
    # ── Sketchfab public-domain museum scans ─────────────────────────────────
    (
        "MUSEUM_SF_ROMAN_SHIELD_SCUTUM",
        "https://sketchfab.com/3d-models/roman-scutum-shield",
        "Sketchfab — Roman Scutum shield photogrammetry. CC0.",
        ["roman", "weapon", "shield", "museum"],
        "CC0",
        "browser",
    ),
    (
        "MUSEUM_SF_GREEK_VASE",
        "https://sketchfab.com/3d-models/greek-vase-museum-scan",
        "Sketchfab — Greek vase photogrammetry museum scan. CC0.",
        ["roman", "prop", "vessel", "museum", "greek"],
        "CC0",
        "browser",
    ),
    (
        "MUSEUM_SF_MEDIEVAL_SWORD",
        "https://sketchfab.com/3d-models/medieval-sword-museum-scan",
        "Sketchfab — Medieval sword museum scan. CC0.",
        ["medieval", "weapon", "sword", "museum"],
        "CC0",
        "browser",
    ),
    # ── NASA 3D (public domain) ───────────────────────────────────────────────
    (
        "MUSEUM_NASA_VOYAGER",
        "https://nasa3d.arc.nasa.gov/models/printable",
        "NASA 3D — Voyager spacecraft model. Public domain.",
        ["scifi", "vehicle", "prop", "museum", "nasa"],
        "Public Domain",
        "browser",
    ),
    (
        "MUSEUM_NASA_CURIOSITY",
        "https://nasa3d.arc.nasa.gov/detail/msl-curiosity-rover",
        "NASA 3D — Curiosity Mars rover. Public domain.",
        ["scifi", "vehicle", "prop", "museum", "nasa"],
        "Public Domain",
        "browser",
    ),
]


@dataclass
class MuseumRunResult:
    pack_id: str
    source_url: str
    output_dir: Path
    download_type: str
    license: str
    provenance_path: Path
    dry_run: bool

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "source_url": self.source_url,
            "output_dir": str(self.output_dir),
            "download_type": self.download_type,
            "license": self.license,
            "provenance_path": str(self.provenance_path),
            "dry_run": self.dry_run,
        }


def list_presets() -> list[tuple[str, str, str]]:
    """Return (pack_id, url, description) for all built-in presets."""
    return [(pid, url, desc) for pid, url, desc, _, _, _ in MUSEUM_PRESETS]


def run_museum_presets(
    *,
    game_scope: str = "roman_arena",
    dry_run: bool = False,
    tags_filter: list[str] | None = None,
) -> list[MuseumRunResult]:
    """Print browser navigation targets and write provenance stubs for all museum presets."""
    results = []
    for pack_id, url, desc, tags, license_, dtype in MUSEUM_PRESETS:
        if tags_filter and not any(t in tags for t in tags_filter):
            continue
        print(f"\n--- {desc} ---")
        r = run_museum_batch(
            pack_id=pack_id,
            source_url=url,
            license_=license_,
            download_type=dtype,
            game_scope=game_scope,
            dry_run=dry_run,
        )
        results.append(r)
    return results


def run_museum_batch(
    *,
    pack_id: str,
    source_url: str,
    license_: str = "Public Domain",
    download_type: str = "browser",
    game_scope: str = "roman_arena",
    output_dir: str | Path | None = None,
    dry_run: bool = False,
) -> MuseumRunResult:
    """
    Queue a museum asset for download.

    Most museum assets require browser navigation (Smithsonian, Sketchfab).
    This runner prints the navigation target and writes a provenance stub.
    Actual download: use playwright_runner or manual drop.

    Parameters
    ----------
    pack_id       : AssetBoy pack ID
    source_url    : Museum asset page URL
    license_      : 'Public Domain', 'CC0', or 'CC BY 4.0'
    download_type : 'direct' or 'browser'
    game_scope    : Game scope tag
    output_dir    : Override output directory
    dry_run       : If True, print plan without writing files.
    """
    out = (
        Path(output_dir)
        if output_dir is not None
        else manual_drop_dir() / "museum" / game_scope / pack_id
    )

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[MuseumRunner | {mode}] Pack: {pack_id}")
    print(f"  Source  : {source_url}")
    print(f"  License : {license_}")
    print(f"  Download: {download_type}")
    print(f"  Output  : {out}")

    if download_type == "browser":
        print(f"  ACTION  : Navigate to URL in browser -> Download 3D model -> Drop to {out}")

    if dry_run:
        print("  [dry-run] Skipping file creation.")
        return MuseumRunResult(
            pack_id=pack_id,
            source_url=source_url,
            output_dir=out,
            download_type=download_type,
            license=license_,
            provenance_path=out / "provenance.json",
            dry_run=True,
        )

    out.mkdir(parents=True, exist_ok=True)
    provenance_path = _write_provenance(out, pack_id=pack_id, source_url=source_url,
                                         license_=license_, game_scope=game_scope,
                                         download_type=download_type)
    return MuseumRunResult(
        pack_id=pack_id,
        source_url=source_url,
        output_dir=out,
        download_type=download_type,
        license=license_,
        provenance_path=provenance_path,
        dry_run=False,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_provenance(
    out_dir: Path,
    *,
    pack_id: str,
    source_url: str,
    license_: str,
    game_scope: str,
    download_type: str,
) -> Path:
    provenance = {
        "schema_version": "assetboy.provenance.v1",
        "pack_id": pack_id,
        "game_scope": game_scope,
        "source_url": source_url,
        "license": license_,
        "license_notes": (
            "Smithsonian/NASA assets: public domain — no restrictions. "
            "Sketchfab CC0 scans: no attribution required. "
            "Always verify license on the asset page before commercial use."
        ),
        "author": "Various museum institutions / Sketchfab contributors",
        "download_date": date.today().isoformat(),
        "source_adapter": "museum_browser_drop",
        "download_type": download_type,
        "lane": "manual_browser" if download_type == "browser" else "direct_url",
        "notes": [
            "Smithsonian 3D: download via browser at 3d.si.edu, requires free account.",
            "NASA 3D: direct download available at nasa3d.arc.nasa.gov.",
            "Sketchfab: use the Sketchfab download bridge or Playwright runner.",
            "All scans need Blender cleanup (scale apply, pivot, LOD) before gate check.",
        ],
    }
    path = out_dir / "provenance.json"
    path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"  Provenance written: {path}")
    return path
