"""
kenney_runner.py — Download free CC0 asset packs from kenney.nl.

Kenney packs are direct .zip downloads with no login required.
All content is CC0 — fully public domain, no attribution required.
This runner fits Lane 1 (direct_url).

Usage (via CLI):
    python -m assetboy.cli run-kenney-batch --use-presets --dry-run
    python -m assetboy.cli run-kenney-batch --pack-id MY_PACK --url https://kenney.nl/...
"""
from __future__ import annotations

import urllib.request
import io
import zipfile
import json
import re
from dataclasses import dataclass
from datetime import date
from html import unescape
from pathlib import Path

from assetboy.library.paths import manual_drop_dir


# ---------------------------------------------------------------------------
# Kenney preset packs — confirmed CC0, all genres
# Format: (pack_id, zip_url, description, tags)
# Direct .zip URLs from kenney.nl CDN
# ---------------------------------------------------------------------------
KENNEY_PRESETS: list[tuple[str, str, str, list[str]]] = [
    # ── 3D Props & Environment ──────────────────────────────────────────────
    (
        "SHARED_KENNEY_MEDIEVAL_RTS_01",
        "https://kenney.nl/assets/medieval-rts",
        "Medieval RTS — towers, walls, units, terrain. CC0.",
        ["3d", "medieval", "rts", "architecture", "props", "cc0"],
    ),
    (
        "SHARED_KENNEY_FANTASY_TOWN_01",
        "https://kenney.nl/assets/fantasy-town-kit",
        "Fantasy Town Kit — modular buildings, roads, trees. CC0.",
        ["3d", "fantasy", "environment", "modular", "cc0"],
    ),
    (
        "SHARED_KENNEY_DUNGEON_01",
        "https://kenney.nl/assets/modular-dungeon-kit",
        "Modular Dungeon Kit — corridors, rooms, walls, and dungeon props. CC0.",
        ["3d", "dungeon", "environment", "horror", "cc0"],
    ),
    (
        "SHARED_KENNEY_SPACE_KIT_01",
        "https://kenney.nl/assets/space-kit",
        "Space Kit — planets, ships, asteroids. CC0.",
        ["3d", "scifi", "space", "environment", "cc0"],
    ),
    (
        "SHARED_KENNEY_SCIFI_CHARACTERS_01",
        "https://kenney.nl/assets/animated-characters-2",
        "Animated Characters 2 — current live animated humanoids with cyborg-friendly shared-character coverage. CC0.",
        ["3d", "character", "scifi", "npc", "cc0"],
    ),
    (
        "SHARED_KENNEY_PLATFORMER_3D_01",
        "https://kenney.nl/assets/platformer-kit",
        "Platformer Kit 3D — tiles, platforms, props. CC0.",
        ["3d", "platformer", "environment", "cc0"],
    ),
    (
        "SHARED_KENNEY_VEHICLE_KIT_01",
        "https://kenney.nl/assets/car-kit",
        "Car Kit — cars, trucks, and road vehicles. CC0.",
        ["3d", "vehicle", "props", "cc0"],
    ),
    (
        "SHARED_KENNEY_CITY_KIT_01",
        "https://kenney.nl/assets/city-kit-commercial",
        "City Kit — commercial buildings, roads, signs. CC0.",
        ["3d", "city", "architecture", "environment", "cc0"],
    ),
    (
        "SHARED_KENNEY_NATURE_KIT_01",
        "https://kenney.nl/assets/nature-kit",
        "Nature Kit — trees, rocks, terrain tiles. CC0.",
        ["3d", "nature", "environment", "terrain", "cc0"],
    ),
    (
        "SHARED_KENNEY_PIRATE_KIT_01",
        "https://kenney.nl/assets/pirate-kit",
        "Pirate Kit — ships, islands, treasure, cannons. CC0.",
        ["3d", "pirate", "props", "environment", "cc0"],
    ),
    (
        "SHARED_KENNEY_FOOD_KIT_01",
        "https://kenney.nl/assets/food-kit",
        "Food Kit — fruits, vegetables, bakery props. CC0.",
        ["3d", "prop", "food", "cc0"],
    ),
    (
        "SHARED_KENNEY_SHOOTING_GALLERY_01",
        "https://kenney.nl/assets/shooting-gallery",
        "Shooting Gallery — FPS props, targets, guns. CC0.",
        ["3d", "fps", "targets", "range", "cc0"],
    ),
    (
        "SHARED_KENNEY_SPORTS_KIT_01",
        "https://kenney.nl/assets/sports-pack",
        "Sports Pack — footballs, hoops, and sports equipment. CC0.",
        ["3d", "sports", "recreation", "cc0"],
    ),
    (
        "SHARED_KENNEY_HOLIDAY_01",
        "https://kenney.nl/assets/holiday-kit",
        "Holiday Kit — winter props, decorations. CC0.",
        ["3d", "holiday", "seasonal", "cc0"],
    ),
    # ── Characters ──────────────────────────────────────────────────────────
    (
        "SHARED_KENNEY_CHARACTERS_01",
        "https://kenney.nl/assets/mini-characters-1",
        "Mini Characters — low-poly humanoid base characters. CC0.",
        ["3d", "character", "humanoid", "cc0"],
    ),
    (
        "SHARED_KENNEY_RPG_CHARACTERS_01",
        "https://kenney.nl/assets/mini-dungeon",
        "Mini Dungeon — current live dungeon/RPG pack with roguelike-friendly character coverage. CC0.",
        ["3d", "character", "rpg", "dungeon", "humanoid", "cc0"],
    ),
    (
        "SHARED_KENNEY_ANIMAL_PACK_01",
        "https://kenney.nl/assets/animal-pack",
        "Animal Pack — reusable animal sprites and game-support content. CC0.",
        ["3d", "character", "animal", "cc0"],
    ),
    # ── UI & 2D ─────────────────────────────────────────────────────────────
    (
        "SHARED_KENNEY_UI_PACK_01",
        "https://kenney.nl/assets/ui-pack",
        "UI Pack — buttons, panels, sliders, HUD elements. CC0.",
        ["2d", "ui", "hud", "icons", "cc0"],
    ),
    (
        "SHARED_KENNEY_UI_SPACE_01",
        "https://kenney.nl/assets/ui-pack-sci-fi",
        "UI Pack - Sci-Fi — sci-fi HUD set. CC0.",
        ["2d", "ui", "hud", "scifi", "cc0"],
    ),
    (
        "SHARED_KENNEY_RPG_UI_01",
        "https://kenney.nl/assets/ui-pack-rpg-expansion",
        "UI Pack (RPG Expansion) — inventory, portraits, and dialog-friendly panels. CC0.",
        ["2d", "ui", "rpg", "cc0"],
    ),
    (
        "SHARED_KENNEY_GAME_ICONS_01",
        "https://kenney.nl/assets/game-icons",
        "Game Icons — 500+ pixel art item and skill icons. CC0.",
        ["2d", "icons", "pixel", "cc0"],
    ),
    # ── Textures ─────────────────────────────────────────────────────────────
    (
        "SHARED_KENNEY_PROTOTYPE_TEXTURES_01",
        "https://kenney.nl/assets/prototype-textures",
        "Prototype Textures — dev greybox tileable textures. CC0.",
        ["texture", "prototype", "greybox", "cc0"],
    ),
]


# ---------------------------------------------------------------------------
# Direct zip URL registry
# Kenney zip URL pattern: https://kenney.nl/assets/<slug> redirects to download
# Actual CDN: https://kenney.nl/assets/<slug>/kenney_<slug>.zip  (varies)
# Update these when confirmed from the download page.
# ---------------------------------------------------------------------------
KENNEY_DIRECT_ZIPS: dict[str, str] = {
    # Confirmed CDN patterns — update with real URLs as encountered
    # Example: "SHARED_KENNEY_MEDIEVAL_RTS_01": "https://kenney.nl/..../kenney_medievalRTS.zip"
    # Operator: visit the pack page, click Download, copy the .zip URL, add here.
}

_KENNEY_DONATE_ZIP_RE = re.compile(
    r"""id=['"]donate-text['"][^>]*href=['"]([^'"]+\.zip)['"]""",
    re.IGNORECASE,
)
_KENNEY_GENERIC_ZIP_RE = re.compile(
    r"""https://kenney\.nl/media/pages/assets/[^'"]+\.zip""",
    re.IGNORECASE,
)


@dataclass
class KenneyRunResult:
    pack_id: str
    source_url: str
    output_dir: Path
    files_extracted: list[str]
    provenance_path: Path
    dry_run: bool

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "source_url": self.source_url,
            "output_dir": str(self.output_dir),
            "files_extracted": self.files_extracted,
            "provenance_path": str(self.provenance_path),
            "dry_run": self.dry_run,
        }


def list_presets() -> list[tuple[str, str, str]]:
    """Return (pack_id, url, description) for all built-in presets."""
    return [(pid, url, desc) for pid, url, desc, _ in KENNEY_PRESETS]


def run_kenney_batch(
    *,
    pack_id: str,
    source_url: str,
    output_dir: str | Path | None = None,
    game_scope: str = "shared",
    dry_run: bool = False,
) -> KenneyRunResult:
    """
    Download and extract a Kenney.nl zip pack.

    Parameters
    ----------
    pack_id      : AssetBoy pack ID (e.g. SHARED_KENNEY_MEDIEVAL_RTS_01)
    source_url   : Direct .zip URL or pack page URL
    output_dir   : Where to extract. Defaults to manual_drop/kenney/<pack_id>/
    game_scope   : 'shared' or specific game scope
    dry_run      : If True, print plan without downloading.
    """
    out = (
        Path(output_dir)
        if output_dir is not None
        else manual_drop_dir() / "kenney" / pack_id
    )

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[Kenney | {mode}] Pack: {pack_id}")
    print(f"  URL: {source_url}")
    print(f"  Output: {out}")

    if dry_run:
        print("  [dry-run] Skipping download.")
        provenance_path = out / "provenance.json"
        return KenneyRunResult(
            pack_id=pack_id,
            source_url=source_url,
            output_dir=out,
            files_extracted=[],
            provenance_path=provenance_path,
            dry_run=True,
        )

    out.mkdir(parents=True, exist_ok=True)

    zip_url = resolve_kenney_download_url(source_url, pack_id=pack_id)

    print(f"  Downloading zip from: {zip_url}")
    raw = _download_bytes(zip_url)

    extracted: list[str] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for member in zf.infolist():
            zf.extract(member, out)
            extracted.append(member.filename)
    print(f"  Extracted {len(extracted)} files.")

    provenance_path = _write_provenance(
        out, pack_id=pack_id, source_url=source_url, game_scope=game_scope
    )

    return KenneyRunResult(
        pack_id=pack_id,
        source_url=source_url,
        output_dir=out,
        files_extracted=extracted,
        provenance_path=provenance_path,
        dry_run=False,
    )


def run_kenney_presets(
    *,
    game_scope: str = "shared",
    dry_run: bool = False,
    tags_filter: list[str] | None = None,
) -> list[KenneyRunResult]:
    """
    Run all built-in Kenney presets, optionally filtered by tags.

    Example:
        run_kenney_presets(tags_filter=["3d", "medieval"])
    """
    results = []
    for pack_id, url, desc, tags in KENNEY_PRESETS:
        if tags_filter and not any(t in tags for t in tags_filter):
            continue
        print(f"\n--- {desc} ---")
        result = run_kenney_batch(
            pack_id=pack_id,
            source_url=url,
            game_scope=game_scope,
            dry_run=dry_run,
        )
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_kenney_download_url(source_url: str, *, pack_id: str = "", html: str | None = None) -> str:
    if source_url.endswith(".zip"):
        return source_url

    known = KENNEY_DIRECT_ZIPS.get(pack_id)
    if known and known.endswith(".zip"):
        return known

    page_html = html
    if page_html is None:
        try:
            page_html = _download_text(source_url)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                f"Kenney pack page could not be resolved for '{pack_id or source_url}'. Visit: {source_url}"
            ) from exc

    extracted = _extract_zip_url_from_html(page_html)
    if extracted:
        return extracted

    raise ValueError(
        f"No direct .zip URL registered or detected for '{pack_id or source_url}'.\n"
        f"  Visit: {source_url}\n"
        f"  Click 'Download', copy the .zip link, pass via --url <zip_url>.\n"
        f"  Then add to KENNEY_DIRECT_ZIPS in kenney_runner.py for future runs."
    )

def _resolve_zip_url(pack_id: str, page_url: str) -> str:
    return resolve_kenney_download_url(page_url, pack_id=pack_id)


def _download_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AssetBoy/1.0 (asset pipeline; CC0 download)"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read()


def _download_text(url: str) -> str:
    return _download_bytes(url).decode("utf-8", errors="replace")


def _extract_zip_url_from_html(html: str) -> str:
    donate_match = _KENNEY_DONATE_ZIP_RE.search(html)
    if donate_match:
        return unescape(donate_match.group(1))

    generic_match = _KENNEY_GENERIC_ZIP_RE.search(html)
    if generic_match:
        return unescape(generic_match.group(0))

    return ""


def _write_provenance(
    out_dir: Path,
    *,
    pack_id: str,
    source_url: str,
    game_scope: str,
) -> Path:
    provenance = {
        "schema_version": "assetboy.provenance.v1",
        "pack_id": pack_id,
        "game_scope": game_scope,
        "source_url": source_url,
        "license": "CC0",
        "license_notes": (
            "Kenney.nl packs are released under CC0 1.0 Universal. "
            "No attribution required. Commercial use OK. Public domain."
        ),
        "author": "Kenney (Kenney Vleugels)",
        "author_url": "https://kenney.nl",
        "download_date": date.today().isoformat(),
        "source_adapter": "kenney_direct",
        "lane": "direct_url",
    }
    path = out_dir / "provenance.json"
    path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"  Provenance written: {path}")
    return path
