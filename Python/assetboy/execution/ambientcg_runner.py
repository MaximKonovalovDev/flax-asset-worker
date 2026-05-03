"""
ambientcg_runner.py — Download CC0 PBR materials from ambientcg.com.

AmbientCG provides 3,500+ CC0 PBR texture sets.
All assets are CC0 — public domain, no attribution required, commercial OK.

NOTE: The AmbientCG REST API v2 (/api/v2/full_json) returns HTTP 500 as of 2026.
This runner uses direct download URLs instead:
  https://ambientcg.com/get?file=<AssetId>_<Resolution>-JPG.zip

Asset IDs are curated in AMBIENTCG_PRESETS below.
To add new assets: find the asset ID on ambientcg.com, add to the pack list.

Usage (via CLI):
    python -m assetboy.cli run-ambientcg-batch --use-presets --dry-run
    python -m assetboy.cli run-ambientcg-batch --use-presets
    python -m assetboy.cli run-ambientcg-batch --pack-id SHARED_MAT_STONE_WALL_CORE --dry-run
"""
from __future__ import annotations

import io
import json
import urllib.request
import urllib.parse
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from assetboy.library.paths import manual_drop_dir


# ---------------------------------------------------------------------------
# AmbientCG direct download base
# Pattern: https://ambientcg.com/get?file=<AssetId>_<Resolution>-JPG.zip
# ---------------------------------------------------------------------------
AMBIENTCG_DOWNLOAD_BASE = "https://ambientcg.com/get"
AMBIENTCG_ASSET_PAGE_BASE = "https://ambientcg.com/view?id="

DEFAULT_RESOLUTION = "2K"


# ---------------------------------------------------------------------------
# Preset packs — curated asset ID lists for the Roman Arena shared baseline.
#
# Format: (pack_id, description, resolution, asset_ids, tags)
#
# asset_ids: list of AmbientCG asset IDs (e.g. "Rock023", "Concrete010")
# Find IDs on ambientcg.com — the URL is ambientcg.com/view?id=<AssetId>
# ---------------------------------------------------------------------------
AMBIENTCG_PRESETS: list[tuple[str, str, str, list[str], list[str]]] = [
    (
        "SHARED_MAT_STONE_WALL_CORE",
        "Stone wall PBR materials — Roman arena walls, pillars, ruins",
        "2K",
        [
            "Rock023",       # rough stone wall
            "Rock027",       # mossy stone
            "Concrete010",   # worn concrete / stone
            "Rock029",       # stone blocks
            "SurfaceImperfections002",  # aging / damage overlays
        ],
        ["stone", "wall", "pbr", "cc0", "roman"],
    ),
    (
        "SHARED_MAT_MARBLE_FLOOR_CORE",
        "Marble floor PBR — Roman arena floor tiles",
        "2K",
        [
            "Marble006",
            "Marble007",
            "Marble009",
            "Tiles049",  # square floor tile
        ],
        ["marble", "floor", "tile", "pbr", "cc0", "roman"],
    ),
    (
        "SHARED_MAT_SANDY_GROUND_CORE",
        "Sand and ground PBR — arena sand floor, outdoor terrain",
        "2K",
        [
            "Ground026",   # dry sand
            "Ground054",   # sandy dirt
            "Ground030",   # coarse sand
            "Ground068",   # beach sand with pebbles
        ],
        ["sand", "ground", "terrain", "pbr", "cc0", "roman"],
    ),
    (
        "SHARED_MAT_COBBLESTONE_CORE",
        "Cobblestone PBR — Roman street, courtyard floor",
        "2K",
        [
            "PavingStones070",
            "PavingStones092",
            "PavingStones111",
            "PavingStones126",
        ],
        ["cobblestone", "paving", "ground", "pbr", "cc0"],
    ),
    (
        "SHARED_MAT_WOOD_PLANK_CORE",
        "Wood plank PBR — doors, furniture, shields",
        "2K",
        [
            "WoodFloor041",
            "WoodFloor054",
            "Wood049",      # worn plank
            "WoodFloor063",
        ],
        ["wood", "plank", "pbr", "cc0"],
    ),
    (
        "SHARED_MAT_METAL_CORE",
        "Metal PBR — weapons, armour, chains",
        "2K",
        [
            "Metal006",
            "Metal032",     # worn scratched iron
            "Metal033",     # chainmail-ish
            "MetalPlates006",
        ],
        ["metal", "iron", "armour", "pbr", "cc0"],
    ),
    (
        "SHARED_MAT_FABRIC_CORE",
        "Fabric PBR — banners, tunics, cloth props",
        "2K",
        [
            "Fabric047",
            "Fabric069",
            "Fabric083",
        ],
        ["fabric", "cloth", "pbr", "cc0"],
    ),
    (
        "SHARED_MAT_BRICK_CORE",
        "Brick wall PBR — arena outer walls, tunnels",
        "2K",
        [
            "Bricks076",
            "Bricks097",
            "Bricks059",
            "Bricks075",
        ],
        ["brick", "wall", "pbr", "cc0"],
    ),
    (
        "SHARED_MAT_DIRT_TERRAIN_CORE",
        "Dirt and soil PBR — terrain, under-arena passages",
        "2K",
        [
            "Ground037",   # cracked earth
            "Ground048",
            "SoilBeachSand001",
            "Ground052",
        ],
        ["dirt", "soil", "terrain", "pbr", "cc0"],
    ),
    (
        "SHARED_MAT_ROCK_CLIFF_CORE",
        "Rock and cliff PBR — surrounding terrain, boulders",
        "2K",
        [
            "Rock035",
            "Rock022",
            "Rock026",
            "Rock048",
        ],
        ["rock", "cliff", "terrain", "pbr", "cc0"],
    ),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AmbientCGAssetResult:
    asset_id: str
    download_url: str
    output_dir: Path
    files_extracted: list[str]
    success: bool
    error: str | None = None


@dataclass
class AmbientCGRunResult:
    pack_id: str
    description: str
    output_dir: Path
    assets: list[AmbientCGAssetResult]
    provenance_path: Path
    dry_run: bool
    errors: list[str] = field(default_factory=list)

    @property
    def downloaded(self) -> list[str]:
        return [a.asset_id for a in self.assets if a.success]

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "description": self.description,
            "output_dir": str(self.output_dir),
            "downloaded": self.downloaded,
            "errors": self.errors,
            "provenance_path": str(self.provenance_path),
            "dry_run": self.dry_run,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_presets() -> list[tuple[str, str, str]]:
    """Return (pack_id, description, asset_count) for all built-in presets."""
    return [
        (pid, desc, f"{len(ids)} assets @ {res}")
        for pid, desc, res, ids, _ in AMBIENTCG_PRESETS
    ]


def make_download_url(asset_id: str, resolution: str = DEFAULT_RESOLUTION) -> str:
    """Build the direct download URL for an AmbientCG asset."""
    filename = f"{asset_id}_{resolution}-JPG.zip"
    return f"{AMBIENTCG_DOWNLOAD_BASE}?file={filename}"


def run_ambientcg_pack(
    *,
    pack_id: str,
    description: str,
    asset_ids: list[str],
    resolution: str = DEFAULT_RESOLUTION,
    output_dir: str | Path | None = None,
    game_scope: str = "shared",
    dry_run: bool = False,
) -> AmbientCGRunResult:
    """
    Download and extract a set of AmbientCG assets by ID.

    Parameters
    ----------
    pack_id      : AssetBoy pack ID (e.g. SHARED_MAT_STONE_WALL_CORE)
    description  : Human-readable description for provenance
    asset_ids    : List of AmbientCG asset IDs to download
    resolution   : 1K / 2K / 4K / 8K (default 2K)
    output_dir   : Where to extract. Defaults to manual_drop/ambientcg/<pack_id>/
    game_scope   : 'shared' or specific game scope
    dry_run      : If True, print plan without downloading.
    """
    out = (
        Path(output_dir)
        if output_dir is not None
        else manual_drop_dir() / "ambientcg" / pack_id
    )

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"\n[AmbientCG | {mode}] {pack_id}")
    print(f"  {description}")
    print(f"  Assets ({len(asset_ids)}): {', '.join(asset_ids)}")
    print(f"  Resolution: {resolution}  Output: {out}")

    if dry_run:
        for aid in asset_ids:
            url = make_download_url(aid, resolution)
            print(f"  [dry] Would download: {url}")
        return AmbientCGRunResult(
            pack_id=pack_id,
            description=description,
            output_dir=out,
            assets=[],
            provenance_path=out / "provenance.json",
            dry_run=True,
        )

    out.mkdir(parents=True, exist_ok=True)
    asset_results: list[AmbientCGAssetResult] = []

    for asset_id in asset_ids:
        download_url = make_download_url(asset_id, resolution)
        asset_dir = out / asset_id
        asset_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Downloading {asset_id} @ {resolution} ...")

        try:
            zip_bytes = _download_bytes(download_url)
            extracted: list[str] = []
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                zf.extractall(asset_dir)
                extracted = [m.filename for m in zf.infolist()]
            print(f"    ✓ {len(extracted)} files → {asset_dir}")
            asset_results.append(AmbientCGAssetResult(
                asset_id=asset_id,
                download_url=download_url,
                output_dir=asset_dir,
                files_extracted=extracted,
                success=True,
            ))
        except Exception as exc:
            msg = str(exc)
            print(f"    ✗ {asset_id}: {msg}")
            asset_results.append(AmbientCGAssetResult(
                asset_id=asset_id,
                download_url=download_url,
                output_dir=asset_dir,
                files_extracted=[],
                success=False,
                error=msg,
            ))

    errors = [f"{a.asset_id}: {a.error}" for a in asset_results if not a.success]
    downloaded = [a.asset_id for a in asset_results if a.success]

    provenance_path = _write_provenance(
        out,
        pack_id=pack_id,
        description=description,
        resolution=resolution,
        game_scope=game_scope,
        asset_ids=asset_ids,
        downloaded=downloaded,
    )

    print(f"  Done: {len(downloaded)}/{len(asset_ids)} downloaded. {len(errors)} errors.")
    return AmbientCGRunResult(
        pack_id=pack_id,
        description=description,
        output_dir=out,
        assets=asset_results,
        provenance_path=provenance_path,
        dry_run=False,
        errors=errors,
    )


def run_ambientcg_presets(
    *,
    game_scope: str = "shared",
    resolution: str = DEFAULT_RESOLUTION,
    dry_run: bool = False,
    tags_filter: list[str] | None = None,
) -> list[AmbientCGRunResult]:
    """Run all built-in AmbientCG presets, optionally filtered by tags."""
    results = []
    for pack_id, desc, res, asset_ids, tags in AMBIENTCG_PRESETS:
        if tags_filter and not any(t in tags for t in tags_filter):
            continue
        result = run_ambientcg_pack(
            pack_id=pack_id,
            description=desc,
            asset_ids=asset_ids,
            resolution=resolution or res,
            game_scope=game_scope,
            dry_run=dry_run,
        )
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _download_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AssetBoy/1.0 (asset pipeline; CC0 download)"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _write_provenance(
    out_dir: Path,
    *,
    pack_id: str,
    description: str,
    resolution: str,
    game_scope: str,
    asset_ids: list[str],
    downloaded: list[str],
) -> Path:
    provenance = {
        "schema_version": "assetboy.provenance.v1",
        "pack_id": pack_id,
        "game_scope": game_scope,
        "description": description,
        "source_url": AMBIENTCG_ASSET_PAGE_BASE + asset_ids[0] if asset_ids else "https://ambientcg.com",
        "license": "CC0",
        "license_notes": (
            "AmbientCG assets are CC0 1.0 Universal (Public Domain). "
            "No attribution required. Commercial use OK. No restrictions."
        ),
        "author": "AmbientCG community",
        "author_url": "https://ambientcg.com",
        "resolution": resolution,
        "asset_ids_requested": asset_ids,
        "asset_ids_downloaded": downloaded,
        "asset_count": len(downloaded),
        "download_date": date.today().isoformat(),
        "source_adapter": "ambientcg_direct",
        "lane": "direct_url",
        "note": "Uses direct download URL pattern: ambientcg.com/get?file=<AssetId>_<Res>-JPG.zip",
    }
    path = out_dir / "provenance.json"
    path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"  Provenance written: {path}")
    return path
