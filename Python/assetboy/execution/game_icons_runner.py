"""
game_icons_runner.py — Download the full game-icons.net SVG icon set.

game-icons.net provides 3,000+ SVG game icons under CC BY 3.0 license.
Attribution required: "Icons by game-icons.net"
The full set is available as a single ZIP from their GitHub release page.

Usage (via CLI):
    python -m assetboy.cli run-game-icons --dry-run
    python -m assetboy.cli run-game-icons --filter combat
"""
from __future__ import annotations

import urllib.request
import io
import zipfile
import json
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from assetboy.library.paths import manual_drop_dir


# ---------------------------------------------------------------------------
# Source — GitHub release ZIP
# Full SVG set as a single download, no auth required.
# Check https://github.com/game-icons/icons/releases for latest tag.
# ---------------------------------------------------------------------------
GAME_ICONS_GITHUB_ZIP = (
    "https://github.com/game-icons/icons/archive/refs/heads/master.zip"
)
GAME_ICONS_LICENSE = "CC BY 3.0"
GAME_ICONS_ATTRIBUTION = "Icons by game-icons.net (CC BY 3.0)"
GAME_ICONS_AUTHOR_URL = "https://game-icons.net"

# ---------------------------------------------------------------------------
# Category filter map — subdirectory names inside the ZIP that match themes
# game-icons.net organizes icons by artist name; these are common theme groupings
# to select subsets for a game scope.
# ---------------------------------------------------------------------------
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "combat":    ["sword", "axe", "shield", "bow", "arrow", "spear", "mace", "dagger", "crossbow", "war", "battle"],
    "magic":     ["magic", "crystal", "potion", "wand", "spell", "scroll", "rune"],
    "character": ["player", "hero", "warrior", "knight", "wizard", "archer", "rogue", "thief"],
    "ui":        ["heart", "star", "coin", "gem", "key", "lock", "map", "compass", "timer", "clock", "skull"],
    "nature":    ["tree", "leaf", "flower", "cloud", "sun", "moon", "rain", "fire", "water", "stone", "rock"],
    "scifi":     ["laser", "robot", "alien", "rocket", "planet", "satellite", "cyber", "nano"],
    "horror":    ["skull", "ghost", "spider", "zombie", "blood", "bone", "grave", "poison"],
    "medieval":  ["castle", "tower", "gate", "banner", "crown", "throne", "catapult", "siege"],
    "transport": ["car", "truck", "ship", "boat", "airplane", "horse", "cart", "wheel"],
    "food":      ["bread", "apple", "fish", "meat", "cheese", "vegetable", "fruit", "mushroom"],
}


@dataclass
class GameIconsRunResult:
    output_dir: Path
    total_icons: int
    filtered_icons: int
    category_filter: str | None
    provenance_path: Path
    dry_run: bool
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "output_dir": str(self.output_dir),
            "total_icons": self.total_icons,
            "filtered_icons": self.filtered_icons,
            "category_filter": self.category_filter,
            "provenance_path": str(self.provenance_path),
            "dry_run": self.dry_run,
            "errors": self.errors,
        }


def run_game_icons(
    *,
    output_dir: str | Path | None = None,
    category_filter: str | None = None,
    game_scope: str = "shared",
    dry_run: bool = False,
    source_url: str = GAME_ICONS_GITHUB_ZIP,
) -> GameIconsRunResult:
    """
    Download and extract the game-icons.net SVG icon set.

    Parameters
    ----------
    output_dir      : Where to save icons. Defaults to manual_drop/game_icons/<scope>/
    category_filter : Optional theme filter — see CATEGORY_KEYWORDS keys.
                      e.g. 'combat', 'magic', 'ui', 'scifi'
                      If None, extracts all 3,000+ icons.
    game_scope      : 'shared' or specific game scope.
    dry_run         : Print plan without downloading.
    source_url      : Override default GitHub ZIP URL.
    """
    out = (
        Path(output_dir)
        if output_dir is not None
        else manual_drop_dir() / "game_icons" / (category_filter or "full") / game_scope
    )

    mode = "DRY RUN" if dry_run else "LIVE"
    kw = CATEGORY_KEYWORDS.get(category_filter or "", [])
    print(f"[GameIcons | {mode}] scope={game_scope} filter={category_filter or 'ALL'}")
    print(f"  Source: {source_url}")
    print(f"  Output: {out}")
    if category_filter:
        print(f"  Keywords: {', '.join(kw)}")

    if dry_run:
        return GameIconsRunResult(
            output_dir=out,
            total_icons=0,
            filtered_icons=0,
            category_filter=category_filter,
            provenance_path=out / "provenance.json",
            dry_run=True,
        )

    out.mkdir(parents=True, exist_ok=True)

    print("  Downloading icon set ZIP (may be 30–80 MB)...")
    raw = _download_bytes(source_url)

    total = 0
    kept = 0
    errors: list[str] = []

    kw_lower = [k.lower() for k in kw]

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        svg_members = [m for m in zf.infolist() if m.filename.lower().endswith(".svg")]
        total = len(svg_members)
        print(f"  Found {total} SVG icons in archive.")

        for member in svg_members:
            fname = Path(member.filename).name.lower()
            if category_filter and kw_lower:
                if not any(kw in fname for kw in kw_lower):
                    continue
            dest = out / Path(member.filename).name
            try:
                with zf.open(member) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                kept += 1
            except Exception as exc:
                errors.append(f"{member.filename}: {exc}")

    print(f"  Extracted {kept}/{total} icons{' (filtered)' if category_filter else ''}.")
    if errors:
        print(f"  Errors: {len(errors)}")

    provenance_path = _write_provenance(
        out,
        game_scope=game_scope,
        source_url=source_url,
        category_filter=category_filter,
        total_icons=total,
        kept_icons=kept,
    )

    return GameIconsRunResult(
        output_dir=out,
        total_icons=total,
        filtered_icons=kept,
        category_filter=category_filter,
        provenance_path=provenance_path,
        dry_run=False,
        errors=errors,
    )


def list_categories() -> list[str]:
    """List available category filter names."""
    return sorted(CATEGORY_KEYWORDS.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _download_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AssetBoy/1.0 (asset pipeline; game-icons CC-BY download)"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _write_provenance(
    out_dir: Path,
    *,
    game_scope: str,
    source_url: str,
    category_filter: str | None,
    total_icons: int,
    kept_icons: int,
) -> Path:
    provenance = {
        "schema_version": "assetboy.provenance.v1",
        "pack_id": f"SHARED_GAMEICONS_{(category_filter or 'FULL').upper()}_01",
        "game_scope": game_scope,
        "source_url": source_url,
        "license": GAME_ICONS_LICENSE,
        "license_notes": (
            "game-icons.net icons are CC BY 3.0. "
            "Attribution required: 'Icons by game-icons.net' — include in game credits. "
            "Commercial use allowed."
        ),
        "attribution": GAME_ICONS_ATTRIBUTION,
        "author_url": GAME_ICONS_AUTHOR_URL,
        "category_filter": category_filter,
        "total_icons_in_set": total_icons,
        "icons_extracted": kept_icons,
        "download_date": date.today().isoformat(),
        "source_adapter": "game_icons_github",
        "lane": "direct_url",
    }
    path = out_dir / "provenance.json"
    path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"  Provenance written: {path}")
    return path
