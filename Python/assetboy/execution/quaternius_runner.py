"""quaternius_runner.py - Download free CC0 low-poly packs from quaternius.com.

Path B v1.7.s15 (2026-05-11) - revived from DEAD (s2.6d). The original
2025-vintage runner was deleted because its data was overspecific and
the pipeline didn't need it; this rewrite is leaner and aligned with
the s11 acquisition_router contract.

Quaternius packs are CC0 (Creative Commons 0 / public domain) and ship
as direct .zip URLs from quaternius.com/packs/. No login required, no
attribution required. Fits the direct_url lane.

Surface:
  QUATERNIUS_BASE             - "https://quaternius.com/packs/"
  QuaternioRunResult dataclass
  run_quaternius_batch(*, pack_id, source_url, output_dir=None,
                       game_scope="shared", dry_run=False) -> QuaternioRunResult
  resolve_quaternius_zip_url(source_url, pack_id) -> str

Used by:
  - assetboy.cli pack from-recipe ... (via acquisition_router)
  - acquisition_router._drive_quaternius (separate slice / next iter)
"""

from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from assetboy.library.paths import manual_drop_dir


QUATERNIUS_BASE = "https://quaternius.com/packs/"

# Tunable subset of known Quaternius packs. Each entry is a (pack_id,
# slug, description) tuple. Slugs map to https://quaternius.com/packs/<slug>.zip
# Operator can override with explicit URLs at recipe time.
QUATERNIUS_PRESETS: list[tuple[str, str, str]] = [
    (
        "SHARED_QUAT_NATURE_KIT_01",
        "nature-kit",
        "Quaternius Nature Kit - trees, rocks, plants. CC0.",
    ),
    (
        "SHARED_QUAT_SURVIVAL_KIT_01",
        "survival-kit",
        "Quaternius Survival Kit - tents, fire, props. CC0.",
    ),
    (
        "SHARED_QUAT_CITY_KIT_01",
        "city-kit",
        "Quaternius City Kit - buildings, vehicles, props. CC0.",
    ),
    (
        "SHARED_QUAT_ULTIMATE_PLATFORMER_01",
        "ultimate-platformer-pack",
        "Quaternius Ultimate Platformer Pack - tiles, props. CC0.",
    ),
    (
        "SHARED_QUAT_RPG_CHARACTERS_01",
        "rpg-character-pack",
        "Quaternius RPG Character Pack - humanoid models. CC0.",
    ),
]


@dataclass
class QuaternioRunResult:
    """Outcome of one Quaternius pack download + extract."""
    pack_id: str
    source_url: str
    output_dir: Path
    files_extracted: list[str]
    provenance_path: Path
    dry_run: bool
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "source_url": self.source_url,
            "output_dir": str(self.output_dir),
            "files_extracted": self.files_extracted,
            "provenance_path": str(self.provenance_path),
            "dry_run": self.dry_run,
            "error": self.error,
        }


def list_presets() -> list[tuple[str, str, str]]:
    """Return (pack_id, slug, description) for all built-in Quaternius presets."""
    return list(QUATERNIUS_PRESETS)


def resolve_quaternius_zip_url(source_url: str, pack_id: str = "") -> str:
    """Normalize a Quaternius source spec to a direct .zip URL.

    Accepts:
      - Full direct URLs ending in .zip: returned as-is
      - Slug-only ("nature-kit"): expanded to QUATERNIUS_BASE + slug + ".zip"
      - quaternius.com/packs/<slug> page URLs: appends .zip
    """
    s = (source_url or "").strip().rstrip("/")
    if not s:
        if not pack_id:
            raise ValueError("quaternius source_url and pack_id are both empty")
        # Fall back to pack_id-derived slug (drop "SHARED_QUAT_" prefix +
        # "_NN" suffix, lower-snake-case -> dash-case)
        slug = pack_id.lower()
        for prefix in ("shared_quat_", "quaternius_"):
            if slug.startswith(prefix):
                slug = slug[len(prefix):]
                break
        slug = slug.rstrip("_0123456789").rstrip("_").replace("_", "-")
        return f"{QUATERNIUS_BASE}{slug}.zip"

    if s.endswith(".zip"):
        return s
    # quaternius.com/packs/<slug> -> append .zip
    if "quaternius.com" in s:
        return f"{s}.zip"
    # Bare slug
    if "/" not in s:
        return f"{QUATERNIUS_BASE}{s}.zip"
    # Unknown shape - return verbatim (let HTTP fail loudly)
    return s


def run_quaternius_batch(
    *,
    pack_id: str,
    source_url: str = "",
    output_dir: str | Path | None = None,
    game_scope: str = "shared",
    dry_run: bool = False,
    timeout_seconds: float = 60.0,
) -> QuaternioRunResult:
    """Download and extract one Quaternius CC0 ZIP pack.

    Args:
        pack_id:        AssetBoy pack ID (e.g. SHARED_QUAT_NATURE_KIT_01)
        source_url:     Direct .zip URL OR slug OR quaternius.com page URL.
                        If empty, derived from pack_id (best-effort).
        output_dir:     Where to extract. Defaults to manual_drop/quaternius/<pack_id>/
        game_scope:     'shared' or specific game scope (used in provenance)
        dry_run:        If True, emit plan + provenance only; no network.
        timeout_seconds: HTTP timeout for the ZIP fetch.

    Returns QuaternioRunResult with .error set on failure (never raises
    for network errors; caller can decide how to handle).
    """
    pack_id = str(pack_id or "").strip()
    if not pack_id:
        raise ValueError("run_quaternius_batch: pack_id is required")

    try:
        zip_url = resolve_quaternius_zip_url(source_url, pack_id=pack_id)
    except ValueError as exc:
        return QuaternioRunResult(
            pack_id=pack_id,
            source_url=source_url,
            output_dir=Path("."),
            files_extracted=[],
            provenance_path=Path("."),
            dry_run=dry_run,
            error=f"resolve_zip_url_failed: {exc}",
        )

    out = (
        Path(output_dir)
        if output_dir is not None
        else manual_drop_dir() / "quaternius" / pack_id
    )

    if dry_run:
        # Emit plan + provenance without downloading
        out.mkdir(parents=True, exist_ok=True)
        provenance_path = _write_provenance(
            out, pack_id=pack_id, source_url=zip_url,
            game_scope=game_scope, dry_run=True,
        )
        return QuaternioRunResult(
            pack_id=pack_id,
            source_url=zip_url,
            output_dir=out,
            files_extracted=[],
            provenance_path=provenance_path,
            dry_run=True,
        )

    out.mkdir(parents=True, exist_ok=True)
    try:
        raw = _download_bytes(zip_url, timeout=timeout_seconds)
    except Exception as exc:
        return QuaternioRunResult(
            pack_id=pack_id,
            source_url=zip_url,
            output_dir=out,
            files_extracted=[],
            provenance_path=out / "provenance.json",
            dry_run=False,
            error=f"download_failed: {exc}",
        )

    extracted: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for member in zf.infolist():
                # Defensive: skip ZipSlip vectors (any member path with
                # ".." or absolute prefix). Quaternius packs are usually
                # clean but third-party ZIPs shouldn't be trusted blindly.
                if ".." in Path(member.filename).parts or member.filename.startswith(("/", "\\")):
                    continue
                zf.extract(member, out)
                extracted.append(member.filename)
    except zipfile.BadZipFile as exc:
        return QuaternioRunResult(
            pack_id=pack_id,
            source_url=zip_url,
            output_dir=out,
            files_extracted=[],
            provenance_path=out / "provenance.json",
            dry_run=False,
            error=f"zip_invalid: {exc}",
        )

    provenance_path = _write_provenance(
        out, pack_id=pack_id, source_url=zip_url,
        game_scope=game_scope, dry_run=False,
        file_count=len(extracted),
    )

    return QuaternioRunResult(
        pack_id=pack_id,
        source_url=zip_url,
        output_dir=out,
        files_extracted=extracted,
        provenance_path=provenance_path,
        dry_run=False,
    )


def _download_bytes(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(
        url, headers={"User-Agent": "assetboy-quaternius/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _write_provenance(
    out_dir: Path,
    *,
    pack_id: str,
    source_url: str,
    game_scope: str,
    dry_run: bool,
    file_count: int = 0,
) -> Path:
    """Write provenance.json so pack_pipeline can read the source lane."""
    provenance = {
        "pack_id": pack_id,
        "source_url": source_url,
        "source_adapter": "quaternius",
        "lane": "direct_url",
        "game_scope": game_scope,
        "license": {
            "kind": "cc0",
            "commercial_ok": True,
            "attribution_required": False,
            "notes": "Quaternius - Creative Commons Zero (public domain). https://quaternius.com",
        },
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "file_count": file_count,
    }
    provenance_path = out_dir / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    return provenance_path


__all__ = [
    "QUATERNIUS_BASE",
    "QUATERNIUS_PRESETS",
    "QuaternioRunResult",
    "list_presets",
    "resolve_quaternius_zip_url",
    "run_quaternius_batch",
]
