"""
vehicle_runner.py — Download CC0 vehicle asset packs for all game scopes.

Sources:
  1. Kenney.nl Vehicle Kit — cars, trucks, emergency vehicles (CC0)
  2. Kenney.nl Racing Kit — race cars, tracks (CC0)
  3. Kenney.nl City Kit — commercial vehicles, buses (CC0)
  4. Kenney.nl Space Kit — spacecraft vehicles (CC0)
  5. NASA 3D — public domain rovers, spacecraft (Public Domain)

All CC0 — no attribution required, commercial use OK.
This runner fits Lane 1 (direct_url) — pure urllib, no Playwright needed.

Usage (via CLI):
    python -m assetboy.cli run-vehicle-batch --use-presets --dry-run
    python -m assetboy.cli run-vehicle-batch --use-presets --tags-filter horse
"""
from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from assetboy.library.paths import manual_drop_dir
from assetboy.execution.kenney_runner import resolve_kenney_download_url


# ---------------------------------------------------------------------------
# Vehicle preset packs — Kenney direct ZIP downloads, all CC0
# Format: (pack_id, zip_url, description, tags)
# ---------------------------------------------------------------------------
VEHICLE_PRESETS: list[tuple[str, str, str, list[str]]] = [
    # ── Ground Vehicles ──────────────────────────────────────────────────────
    (
        "SHARED_VEH_KENNEY_VEHICLE_KIT",
        "https://kenney.nl/assets/car-kit",
        "Kenney Car Kit — cars, trucks, SUVs, and road vehicles. CC0.",
        ["vehicle", "car", "truck", "modern", "all"],
    ),
    (
        "SHARED_VEH_KENNEY_RACING_KIT",
        "https://kenney.nl/assets/racing-kit",
        "Kenney Racing Kit — race cars, barriers, track elements. CC0.",
        ["vehicle", "car", "racing", "all"],
    ),
    (
        "SHARED_VEH_KENNEY_CITY_VEHICLES",
        "https://kenney.nl/assets/city-kit-roads",
        "Kenney City Roads Kit — roads, buses, trams, road props. CC0.",
        ["vehicle", "city", "bus", "modern", "all"],
    ),
    (
        "SHARED_VEH_KENNEY_HOLIDAY_TRAIN",
        "https://kenney.nl/assets/holiday-kit",
        "Kenney Holiday Kit — includes train and cart vehicles. CC0.",
        ["vehicle", "train", "cart", "holiday", "all"],
    ),
    # ── Fantasy / Historical ─────────────────────────────────────────────────
    (
        "SHARED_VEH_KENNEY_PIRATE_SHIPS",
        "https://kenney.nl/assets/pirate-kit",
        "Kenney Pirate Kit — ships, boats, cannon carts. CC0.",
        ["vehicle", "ship", "boat", "pirate", "fantasy", "roman", "all"],
    ),
    # ── Sci-Fi / Space ───────────────────────────────────────────────────────
    (
        "SHARED_VEH_KENNEY_SPACE_SHIPS",
        "https://kenney.nl/assets/space-kit",
        "Kenney Space Kit — spacecraft, rockets, modules. CC0.",
        ["vehicle", "spacecraft", "scifi", "space", "all"],
    ),
    (
        "SHARED_VEH_KENNEY_SCIFI_VEHICLES",
        "https://kenney.nl/assets/modular-space-kit",
        "Kenney Modular Space Kit — ships, modules, and sci-fi vehicle-friendly parts. CC0.",
        ["vehicle", "tank", "scifi", "hover", "all"],
    ),
]

# Direct download zip URL registry — populate from pack page download buttons
VEHICLE_DIRECT_ZIPS: dict[str, str] = {
    # Pattern: https://kenney.nl/content/3-assets/<idx>-<slug>/<slug>.zip
    # Example: "SHARED_VEH_KENNEY_VEHICLE_KIT": "https://kenney.nl/.../kenney_vehicleKit.zip"
    # Operator: visit pack page → Download → copy .zip URL → add here
}


@dataclass
class VehicleRunResult:
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
    return [(pid, url, desc) for pid, url, desc, _ in VEHICLE_PRESETS]


def run_vehicle_batch(
    *,
    pack_id: str,
    source_url: str,
    output_dir: str | Path | None = None,
    game_scope: str = "shared",
    dry_run: bool = False,
) -> VehicleRunResult:
    """
    Download and extract a vehicle asset pack from a direct ZIP URL.

    Parameters
    ----------
    pack_id      : AssetBoy pack ID (e.g. SHARED_VEH_KENNEY_VEHICLE_KIT)
    source_url   : Direct .zip URL or pack page URL
    output_dir   : Where to extract. Defaults to manual_drop/vehicles/<pack_id>/
    game_scope   : 'shared' or specific game scope
    dry_run      : If True, print plan without downloading.
    """
    out = (
        Path(output_dir)
        if output_dir is not None
        else manual_drop_dir() / "vehicles" / game_scope / pack_id
    )

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[VehicleRunner | {mode}] Pack: {pack_id}")
    print(f"  URL: {source_url}")
    print(f"  Output: {out}")

    if dry_run:
        print("  [dry-run] Skipping download.")
        return VehicleRunResult(
            pack_id=pack_id,
            source_url=source_url,
            output_dir=out,
            files_extracted=[],
            provenance_path=out / "provenance.json",
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

    provenance_path = _write_provenance(out, pack_id=pack_id, source_url=source_url,
                                         game_scope=game_scope)
    return VehicleRunResult(
        pack_id=pack_id,
        source_url=source_url,
        output_dir=out,
        files_extracted=extracted,
        provenance_path=provenance_path,
        dry_run=False,
    )


def run_vehicle_presets(
    *,
    game_scope: str = "shared",
    dry_run: bool = False,
    tags_filter: list[str] | None = None,
) -> list[VehicleRunResult]:
    """Run all built-in vehicle presets, optionally filtered by tags."""
    results = []
    for pack_id, url, desc, tags in VEHICLE_PRESETS:
        if tags_filter and not any(t in tags for t in tags_filter):
            continue
        print(f"\n--- {desc} ---")
        results.append(run_vehicle_batch(
            pack_id=pack_id,
            source_url=url,
            game_scope=game_scope,
            dry_run=dry_run,
        ))
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_zip_url(pack_id: str, page_url: str) -> str:
    known = VEHICLE_DIRECT_ZIPS.get(pack_id)
    if known and known.endswith(".zip"):
        return known
    return resolve_kenney_download_url(page_url, pack_id=pack_id)


def _download_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AssetBoy/1.0 (asset pipeline; CC0 download)"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read()


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
            "Kenney.nl vehicle packs are released under CC0 1.0 Universal. "
            "No attribution required. Commercial use OK. Public domain."
        ),
        "author": "Kenney (Kenney Vleugels)",
        "author_url": "https://kenney.nl",
        "download_date": date.today().isoformat(),
        "source_adapter": "vehicle_direct_url",
        "lane": "direct_url",
    }
    path = out_dir / "provenance.json"
    path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"  Provenance written: {path}")
    return path
