"""
packet_writer.py — AI-side packet manifest generator.

Writes packet.json and provenance.json into publish/flax_intake/<game>/<pack_id>/
so the AI can close the loop without a human review step.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assetboy.library.asset_metadata import (
    build_asset_metadata,
    load_generator_registry,
    write_asset_metadata,
)
from assetboy.provenance.schema import canonicalize_provenance_payload, validate_provenance_payload
from assetboy.providers.lanes import canonical_lane_value, require_source_adapter

SUPPORTED_EXTENSIONS = {
    ".fbx", ".obj", ".dae", ".gltf", ".glb",
    ".png", ".jpg", ".jpeg", ".tga", ".hdr",
    ".wav", ".ogg", ".mp3",
    ".ttf", ".otf", ".woff", ".woff2",
}

_OPEN_LICENSE_TOKENS = (
    "cc0",
    "public domain",
    "public-domain",
    "ofl",
    "mit",
    "bsd",
    "apache",
    "creative commons 0",
    "cc by",
    "cc-by",
)


@dataclass
class PayloadFile:
    published_relative_path: str
    relative_pack_path: str
    bytes: int
    sha256: str


@dataclass
class PacketManifest:
    pack_id: str
    game_scope: str
    packet_status: str
    lane: str
    payload_path: str
    payload_files: list[dict[str, Any]]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ProvenanceRecord:
    pack_id: str
    game_scope: str
    source_url: str
    license: str
    author: str
    author_or_vendor: str
    license_snapshot: str
    acquired_at: str
    downloaded_filename: str
    download_date: str = field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())
    lane: str = "unknown"
    source_adapter: str = "direct_url_queue"
    payload_target_path: str = ""
    entitlement_note: str = ""
    notes: str = ""


def _sha256(path: Path) -> str:
    """Compute hex SHA-256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _requires_entitlement_note(license_name: str) -> bool:
    normalized = str(license_name).strip().lower()
    return normalized and not any(token in normalized for token in _OPEN_LICENSE_TOKENS)


def build_payload_manifest(payload_dir: Path, *, verify_hashes: bool = True) -> list[dict[str, Any]]:
    """Walk payload_dir and build the payload_files list for packet.json.

    Skips unsupported extensions (same filter as the PowerShell intake script).
    """
    payload_dir = Path(payload_dir).resolve()
    if not payload_dir.is_dir():
        raise FileNotFoundError(f"Payload directory not found: {payload_dir}")

    entries: list[dict[str, Any]] = []
    for fpath in sorted(payload_dir.rglob("*")):
        if not fpath.is_file():
            continue
        ext = fpath.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue
        rel = fpath.relative_to(payload_dir).as_posix()
        published_rel = (Path("payload") / Path(rel)).as_posix()
        size = fpath.stat().st_size
        sha = _sha256(fpath) if verify_hashes else ""
        entries.append(
            {
                "published_relative_path": published_rel,
                "relative_pack_path": rel,
                "bytes": size,
                "sha256": sha,
            }
        )
    return entries


def write_packet(
    pack_id: str,
    game_scope: str,
    payload_dir: Path,
    source_url: str,
    license: str,  # noqa: A002
    author: str,
    *,
    lane: str = "unknown",
    source_adapter: str = "direct_url_queue",
    license_snapshot: str = "",
    entitlement_note: str = "",
    acquired_at: str = "",
    notes: str = "",
    conversion_report: dict[str, Any] | None = None,
    library_root: Path | None = None,
    verify_hashes: bool = True,
    dry_run: bool = False,
) -> Path:
    """Write packet.json and provenance.json for a pack.

    Places them in:
      <library_root>/publish/flax_intake/<game_scope>/<pack_id>/

    Returns the path to packet.json.
    """
    if library_root is None:
        from assetboy.library.paths import asset_library_root
        library_root = asset_library_root()

    pack_dir = Path(library_root) / "publish" / "flax_intake" / game_scope / pack_id
    payload_target_path = pack_dir / "payload"
    payload_path = Path(payload_dir).resolve()
    lane_value = canonical_lane_value(lane)
    source_adapter_record = require_source_adapter(source_adapter)
    source_adapter_value = source_adapter_record.adapter_id
    entitlement_value = str(entitlement_note or notes).strip()

    if not payload_path.is_dir():
        raise FileNotFoundError(f"payload_dir does not exist: {payload_path}")
    if source_adapter_record.lane.value != lane_value:
        raise ValueError(
            f"source_adapter '{source_adapter_value}' maps to lane '{source_adapter_record.lane.value}', not lane '{lane_value}'."
        )
    if _requires_entitlement_note(license) and not entitlement_value:
        raise ValueError("provenance.entitlement_note is required for non-open or store-gated licenses.")

    payload_files = build_payload_manifest(payload_path, verify_hashes=verify_hashes)
    if not payload_files:
        raise ValueError(
            f"No supported files found in payload_dir: {payload_path}. "
            f"Supported extensions: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    manifest = PacketManifest(
        pack_id=pack_id,
        game_scope=game_scope,
        packet_status="ai_reviewed",
        lane=lane_value,
        payload_path="payload",
        payload_files=payload_files,
    )
    provenance = ProvenanceRecord(
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        license=license,
        author=author,
        author_or_vendor=author,
        license_snapshot=license_snapshot or notes or license,
        acquired_at=acquired_at or datetime.now(timezone.utc).isoformat(),
        downloaded_filename=payload_files[0]["relative_pack_path"] if payload_files else "",
        lane=lane_value,
        source_adapter=source_adapter_value,
        payload_target_path=str(payload_target_path),
        entitlement_note=entitlement_value,
        notes=notes,
    )
    _, provenance_errors, provenance_warnings = validate_provenance_payload(
        asdict(provenance),
        expected_lane=lane_value,
        expected_payload_target_path=payload_target_path,
    )
    if provenance_errors:
        raise ValueError("Invalid provenance for packet write: " + "; ".join(provenance_errors))
    if provenance_warnings:
        print("[WARN] provenance warnings: " + " | ".join(provenance_warnings))

    if dry_run:
        print(f"[dry-run] Would write packet.json + provenance.json to {pack_dir}")
        return pack_dir / "packet.json"

    pack_dir.mkdir(parents=True, exist_ok=True)
    packet_path = pack_dir / "packet.json"
    provenance_path = pack_dir / "provenance.json"

    packet_path.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
    canonical_provenance = canonicalize_provenance_payload(asdict(provenance), keep_extra=True)
    canonical_provenance["pack_id"] = pack_id
    canonical_provenance["game_scope"] = game_scope
    provenance_path.write_text(json.dumps(canonical_provenance, indent=2), encoding="utf-8")
    metadata = build_asset_metadata(
        pack_id=pack_id,
        game_scope=game_scope,
        payload_files=payload_files,
        provenance=canonical_provenance,
        conversion_report=conversion_report,
        generator_registry=load_generator_registry(),
        source_folder=str(payload_path),
    )
    metadata_path = write_asset_metadata(pack_dir, metadata)

    print(f"[OK] Wrote {packet_path}")
    print(f"[OK] Wrote {provenance_path}")
    print(f"[OK] Wrote {metadata_path}")
    print(f"[OK] payload_files: {len(payload_files)} supported asset(s)")
    return packet_path
