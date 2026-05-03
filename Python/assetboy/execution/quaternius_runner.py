"""
quaternius_runner.py — Download free CC0 low-poly packs from quaternius.com.

Quaternius pack pages are public, but the live download targets often resolve through
Google Drive folders or Itch click-through buttons instead of a stable static archive URL.
Treat this runner as a pack-page registry plus dry-run planner until a specific archive URL
is pinned for a pack.

Usage (via CLI):
    python -m assetboy.cli run-quaternius-batch --use-presets --dry-run
    python -m assetboy.cli run-quaternius-batch --pack-id MY_PACK --url https://quaternius.com/packs/...
"""
from __future__ import annotations

import urllib.request
import io
import zipfile
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from assetboy.library.paths import manual_drop_dir


# ---------------------------------------------------------------------------
# Roman + reusable preset pack list
# Each entry: (pack_id, url, description, tags)
# URLs point to the current public pack pages
# ---------------------------------------------------------------------------
QUATERNIUS_PRESETS: list[tuple[str, str, str, list[str]]] = [
    (
        "SHARED_QUAT_ULTIMATE_CHARACTERS_01",
        "https://quaternius.com/packs/universalbasecharacters.html",
        "Universal Base Characters — lowpoly humanoid base characters CC0.",
        ["character", "humanoid", "lowpoly", "cc0"],
    ),
    (
        "SHARED_QUAT_ULTIMATE_ANIMATED_01",
        "https://quaternius.com/packs/ultimatedanimatedcharacter.html",
        "Ultimate Animated Character — rigged and animated lowpoly CC0.",
        ["character", "animated", "rigged", "cc0"],
    ),
    (
        "SHARED_QUAT_ULTIMATE_WEAPONS_01",
        "https://quaternius.com/packs/medievalweapons.html",
        "Medieval Weapons — swords, axes, shields, and melee props. CC0.",
        ["weapon", "prop", "lowpoly", "cc0"],
    ),
    (
        "SHARED_QUAT_MODULAR_DUNGEON_01",
        "https://quaternius.com/packs/ultimatemodularruins.html",
        "Ultimate Modular Ruins — stone arches, pillars, floors, and ruins-friendly pieces. CC0.",
        ["environment", "modular", "stone", "roman_crossover", "cc0"],
    ),
    (
        "SHARED_QUAT_NATURE_01",
        "https://quaternius.com/packs/ultimatenature.html",
        "Ultimate Nature — rocks, trees, ruins-compatible vegetation, CC0",
        ["environment", "nature", "rocks", "cc0"],
    ),
]

# Direct archive map — populated only when a stable downloadable archive URL is pinned
# Key: pack_id from QUATERNIUS_PRESETS
# Value: direct zip URL (filled in only after the page click-through target is pinned)
QUATERNIUS_DIRECT_ZIPS: dict[str, str] = {}

_QUATERNIUS_TARGET_RE = re.compile(r"""window\.open\('([^']+)'\)""", re.IGNORECASE)


@dataclass
class QuaterniusRunResult:
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
    return [(pid, url, desc) for pid, url, desc, _ in QUATERNIUS_PRESETS]


def run_quaternius_batch(
    *,
    pack_id: str,
    source_url: str,
    output_dir: str | Path | None = None,
    game_scope: str = "shared",
    dry_run: bool = False,
) -> QuaterniusRunResult:
    """
    Download and extract a Quaternius zip pack.

    Parameters
    ----------
    pack_id      : AssetBoy pack ID (e.g. SHARED_QUAT_ULTIMATE_WEAPONS_01)
    source_url   : Direct .zip URL or pack page URL
    output_dir   : Where to extract. Defaults to manual_drop/quaternius/<pack_id>/
    game_scope   : 'shared' for reusable packs, or 'roman_arena' etc.
    dry_run      : If True, print what would happen without downloading.
    """
    out = (
        Path(output_dir)
        if output_dir is not None
        else manual_drop_dir() / "quaternius" / pack_id
    )

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[Quaternius | {mode}] Pack: {pack_id}")
    print(f"  URL: {source_url}")
    print(f"  Output: {out}")

    if dry_run:
        print("  [dry-run] Skipping download.")
        provenance_path = out / "provenance.json"
        return QuaterniusRunResult(
            pack_id=pack_id,
            source_url=source_url,
            output_dir=out,
            files_extracted=[],
            provenance_path=provenance_path,
            dry_run=True,
        )

    out.mkdir(parents=True, exist_ok=True)

    # Detect if URL is a direct zip or a page link
    if source_url.endswith(".zip"):
        zip_url = source_url
    else:
        # Try to resolve zip from known pack map
        zip_url = _resolve_zip_url(pack_id, source_url)

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

    return QuaterniusRunResult(
        pack_id=pack_id,
        source_url=source_url,
        output_dir=out,
        files_extracted=extracted,
        provenance_path=provenance_path,
        dry_run=False,
    )


def run_quaternius_presets(
    *,
    game_scope: str = "shared",
    dry_run: bool = False,
) -> list[QuaterniusRunResult]:
    """Run all built-in Roman/shared Quaternius presets."""
    results = []
    for pack_id, url, desc, _ in QUATERNIUS_PRESETS:
        print(f"\n--- {desc} ---")
        result = run_quaternius_batch(
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

def _resolve_zip_url(pack_id: str, page_url: str) -> str:
    """
    Try to get direct zip URL from pack_id registry, fallback to page_url.
    In practice today: Quaternius pack pages often expose Google Drive folders or Itch
    downloads via page-click buttons, not stable static archive URLs. Only treat a pack as
    direct-download-ready once a specific archive URL is pinned in QUATERNIUS_DIRECT_ZIPS.
    """
    known = QUATERNIUS_DIRECT_ZIPS.get(pack_id)
    if known and known.endswith(".zip"):
        return known

    target_hint = ""
    try:
        html = _download_bytes(page_url).decode("utf-8", errors="replace")
        targets = [match.group(1) for match in _QUATERNIUS_TARGET_RE.finditer(html)]
        manual_targets = [target for target in targets if "drive.google.com" in target or "itch.io" in target]
        if manual_targets:
            target_hint = f"\n  Current page exposes manual targets: {', '.join(manual_targets[:2])}"
    except Exception:
        target_hint = ""

    raise ValueError(
        f"No direct archive URL is pinned for '{pack_id}'.\n"
        f"  Visit: {page_url}\n"
        f"  Quaternius is currently a page-click/manual source for this pack; use browser review or pin a real archive URL via --url.\n"
        f"  Then add it to QUATERNIUS_DIRECT_ZIPS in quaternius_runner.py for future runs."
        f"{target_hint}"
    )


def _download_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "AssetBoy/1.0 (asset pipeline; CC0 download)"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
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
        "license_notes": "Quaternius packs are released under CC0. No attribution required. Commercial use OK.",
        "author": "Quaternius (Maxim Zhukov)",
        "author_url": "https://quaternius.com",
        "download_date": date.today().isoformat(),
        "source_adapter": "quaternius_direct",
        "lane": "direct_url",
    }
    path = out_dir / "provenance.json"
    path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"  Provenance written: {path}")
    return path
