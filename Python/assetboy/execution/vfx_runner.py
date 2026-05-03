"""
vfx_runner.py — Download CC0 VFX / particle assets for all game scopes.

Sources:
  1. Kenney.nl — particle packs, explosion sprite sheets, magic VFX (CC0)
  2. OpenGameArt.org — free CC0/CC-BY VFX (listed as manual-drop targets only)

All Kenney packs are CC0 — no attribution required, commercial use OK.
This runner fits Lane 1 (direct_url) — pure urllib, no Playwright needed.

Usage (via CLI):
    python -m assetboy.cli run-vfx-batch --use-presets --dry-run
    python -m assetboy.cli run-vfx-batch --use-presets --tags-filter combat
    python -m assetboy.cli run-vfx-batch --show-oga    (list manual-drop OGA targets)
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
# VFX preset packs — Kenney.nl direct ZIP downloads, all CC0
# Format: (pack_id, zip_url, description, tags)
# ---------------------------------------------------------------------------
VFX_PRESETS: list[tuple[str, str, str, list[str]]] = [
    (
        "SHARED_VFX_KENNEY_PARTICLES",
        "https://kenney.nl/assets/particle-pack",
        "Kenney Particle Pack — smoke, fire, sparks, explosion sprites. CC0.",
        ["particles", "smoke", "fire", "explosion", "spark", "all"],
    ),
    (
        "SHARED_VFX_KENNEY_SMOKE_PARTICLES",
        "https://kenney.nl/assets/smoke-particles",
        "Kenney Smoke Particles — smoke, explosion, and dust effect sprites. CC0.",
        ["particles", "smoke", "explosion", "dust", "combat", "all"],
    ),
    (
        "SHARED_VFX_KENNEY_SPLAT_PACK",
        "https://kenney.nl/assets/splat-pack",
        "Kenney Splat Pack — impact splats, bursts, and stylized hit overlays. CC0.",
        ["particles", "impact", "combat", "stylized", "all"],
    ),
    (
        "SHARED_VFX_KENNEY_1BIT",
        "https://kenney.nl/assets/1-bit-pack",
        "Kenney 1-Bit Pack — stylized retro particles, sprites, and effect support. CC0.",
        ["pixel", "retro", "stylized", "all"],
    ),
]

# OpenGameArt packs require a browser to download — listed as manual-drop targets.
# Use playwright_runner or manual download for these.
OGA_MANUAL_DROP_TARGETS: list[dict] = [
    {
        "pack_id": "OGA_VFX_EXPLOSION_ANIMATED",
        "url": "https://opengameart.org/content/explosion-animated",
        "description": "Animated explosion sprite sheet. CC0.",
        "tags": ["explosion", "combat", "animation"],
        "license": "CC0",
        "manual_drop_path": "vfx/oga/explosion_animated/",
    },
    {
        "pack_id": "OGA_VFX_MAGIC_CIRCLE",
        "url": "https://opengameart.org/content/magic-circle",
        "description": "Magic circle VFX sprites. CC0.",
        "tags": ["magic", "fantasy", "vfx"],
        "license": "CC0",
        "manual_drop_path": "vfx/oga/magic_circle/",
    },
    {
        "pack_id": "OGA_VFX_FIRE_SPRITES",
        "url": "https://opengameart.org/content/fire-animation-sprite-sheet",
        "description": "Fire animation sprite sheet. CC0.",
        "tags": ["fire", "environment", "particles"],
        "license": "CC0",
        "manual_drop_path": "vfx/oga/fire_sprites/",
    },
]


@dataclass
class VfxRunResult:
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
    return [(pid, url, desc) for pid, url, desc, _ in VFX_PRESETS]


def print_oga_manual_targets() -> None:
    """Print OpenGameArt manual-drop targets for operator reference."""
    print("\n[VfxRunner] OpenGameArt manual-drop targets (browser required):")
    for t in OGA_MANUAL_DROP_TARGETS:
        print(f"  {t['pack_id']}  ({t['license']})")
        print(f"    Browse : {t['url']}")
        print(f"    Drop to: manual_drop/{t['manual_drop_path']}")


def run_vfx_batch(
    *,
    pack_id: str,
    source_url: str,
    output_dir: str | Path | None = None,
    game_scope: str = "shared",
    dry_run: bool = False,
) -> VfxRunResult:
    """
    Download and extract a VFX pack from a direct ZIP or file URL.

    Parameters
    ----------
    pack_id      : AssetBoy pack ID (e.g. SHARED_VFX_KENNEY_PARTICLES)
    source_url   : Direct .zip URL
    output_dir   : Where to extract. Defaults to manual_drop/vfx/<game_scope>/<pack_id>/
    game_scope   : 'shared' or specific game scope
    dry_run      : If True, print plan without downloading.
    """
    out = (
        Path(output_dir)
        if output_dir is not None
        else manual_drop_dir() / "vfx" / game_scope / pack_id
    )

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[VfxRunner | {mode}] Pack: {pack_id}")
    print(f"  URL: {source_url}")
    print(f"  Output: {out}")

    if dry_run:
        print("  [dry-run] Skipping download.")
        return VfxRunResult(
            pack_id=pack_id,
            source_url=source_url,
            output_dir=out,
            files_extracted=[],
            provenance_path=out / "provenance.json",
            dry_run=True,
        )

    out.mkdir(parents=True, exist_ok=True)
    resolved_source_url = resolve_kenney_download_url(source_url, pack_id=pack_id)
    raw = _download_bytes(resolved_source_url)
    extracted: list[str] = []

    if resolved_source_url.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for member in zf.infolist():
                zf.extract(member, out)
                extracted.append(member.filename)
    else:
        fname = resolved_source_url.split("/")[-1]
        (out / fname).write_bytes(raw)
        extracted.append(fname)

    print(f"  Extracted {len(extracted)} files.")
    provenance_path = _write_provenance(out, pack_id=pack_id, source_url=resolved_source_url,
                                         game_scope=game_scope)
    return VfxRunResult(
        pack_id=pack_id,
        source_url=resolved_source_url,
        output_dir=out,
        files_extracted=extracted,
        provenance_path=provenance_path,
        dry_run=False,
    )


def run_vfx_presets(
    *,
    game_scope: str = "shared",
    dry_run: bool = False,
    tags_filter: list[str] | None = None,
) -> list[VfxRunResult]:
    """Run all built-in VFX presets, optionally filtered by tags."""
    results = []
    for pack_id, url, desc, tags in VFX_PRESETS:
        if tags_filter and not any(t in tags for t in tags_filter):
            continue
        print(f"\n--- {desc} ---")
        results.append(run_vfx_batch(
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
        headers={"User-Agent": "AssetBoy/1.0 (asset pipeline; CC0 download)"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
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
            "Kenney.nl VFX packs are released under CC0 1.0 Universal. "
            "No attribution required. Commercial use OK. Public domain."
        ),
        "author": "Kenney (Kenney Vleugels)",
        "author_url": "https://kenney.nl",
        "download_date": date.today().isoformat(),
        "source_adapter": "kenney_vfx_direct",
        "lane": "direct_url",
    }
    path = out_dir / "provenance.json"
    path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"  Provenance written: {path}")
    return path
