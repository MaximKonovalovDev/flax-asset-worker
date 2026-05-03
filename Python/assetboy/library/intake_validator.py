"""
intake_validator.py — Pure-Python port of AssetBoyOpsTool.cs/ExecuteValidatePacket.

Lets the AI validate a packet locally before calling the MCP tool,
and powers the `auto-intake` CLI command.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from assetboy.providers.lanes import canonical_lane_value, require_source_adapter

SUPPORTED_EXTENSIONS = {
    ".fbx", ".obj", ".gltf", ".glb",
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

_PROVENANCE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "source_url": ("source_url", "source_page_url", "download_url"),
    "license": ("license",),
    "license_snapshot": ("license_snapshot", "license_note", "license_notes", "download_notes", "review_notes"),
    "author_or_vendor": ("author_or_vendor", "author", "vendor"),
    "acquired_at": ("acquired_at", "acquired_at_utc", "download_date"),
    "lane": ("lane",),
    "source_adapter": ("source_adapter",),
    "payload_target_path": ("payload_target_path", "payload_target"),
    "downloaded_filename": ("downloaded_filename",),
    "prompt": ("prompt",),
    "model_name": ("model_name",),
    "profile_id": ("profile_id",),
    "notebook_or_session": ("notebook_or_session",),
    "entitlement_note": ("entitlement_note", "license_note", "license_notes", "download_notes", "notes"),
}

_COMMON_REQUIRED_PROVENANCE_FIELDS = (
    "source_url",
    "license",
    "license_snapshot",
    "author_or_vendor",
    "acquired_at",
    "lane",
    "source_adapter",
    "payload_target_path",
)
_DIRECT_URL_REQUIRED_PROVENANCE_FIELDS = _COMMON_REQUIRED_PROVENANCE_FIELDS + ("downloaded_filename",)
_MANUAL_BROWSER_REQUIRED_PROVENANCE_FIELDS = _COMMON_REQUIRED_PROVENANCE_FIELDS + ("downloaded_filename",)
_GENERATOR_REQUIRED_PROVENANCE_FIELDS = _COMMON_REQUIRED_PROVENANCE_FIELDS + (
    "prompt",
    "model_name",
    "profile_id",
    "notebook_or_session",
)


def _resolve_path_relative_to(base_dir: Path, candidate: str | None) -> Path | None:
    if candidate is None:
        return None

    text = str(candidate).strip()
    if not text:
        return None

    path = Path(text)
    if path.is_absolute():
        return path.resolve()
    return (base_dir / path).resolve()


def _canonical_provenance_value(provenance: dict[str, Any], field_id: str) -> str:
    for alias in _PROVENANCE_FIELD_ALIASES.get(field_id, (field_id,)):
        value = provenance.get(alias)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _required_provenance_fields(lane: str) -> tuple[str, ...]:
    if lane == "manual_browser":
        return _MANUAL_BROWSER_REQUIRED_PROVENANCE_FIELDS
    if lane == "generator":
        return _GENERATOR_REQUIRED_PROVENANCE_FIELDS
    return _DIRECT_URL_REQUIRED_PROVENANCE_FIELDS


def _requires_entitlement_note(license_name: str) -> bool:
    normalized = str(license_name).strip().lower()
    return normalized and not any(token in normalized for token in _OPEN_LICENSE_TOKENS)


@dataclass
class ValidationResult:
    pack_id: str
    game_scope: str
    packet_path: str
    pass_: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    payload_file_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "packet_path": self.packet_path,
            "pass": self.pass_,
            "errors": self.errors,
            "warnings": self.warnings,
            "payload_file_count": self.payload_file_count,
        }


def validate_packet(
    pack_id: str,
    game_scope: str,
    *,
    library_root: Path | None = None,
    packet_path: Path | None = None,
    provenance_required: bool = True,
) -> ValidationResult:
    """Validate an AI-generated (or human-reviewed) packet.

    Mirrors the logic in AssetBoyOpsTool.cs/ExecuteValidatePacket exactly so
    there are no surprises when the MCP tool runs.
    """
    if library_root is None:
        from assetboy.library.paths import asset_library_root
        library_root = asset_library_root()

    if packet_path is None:
        packet_path = (
            Path(library_root) / "publish" / "flax_intake" / game_scope / pack_id / "packet.json"
        )
    packet_path = Path(packet_path).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    # 1. packet.json must exist and be parseable
    if not packet_path.exists():
        return ValidationResult(
            pack_id=pack_id,
            game_scope=game_scope,
            packet_path=str(packet_path),
            pass_=False,
            errors=[f"packet.json not found: {packet_path}"],
        )

    try:
        packet: dict[str, Any] = json.loads(packet_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return ValidationResult(
            pack_id=pack_id,
            game_scope=game_scope,
            packet_path=str(packet_path),
            pass_=False,
            errors=[f"packet.json is not valid JSON: {exc}"],
        )

    raw_pack_id = packet.get("pack_id", "").strip()
    raw_game_scope = packet.get("game_scope", "").strip()
    raw_lane = str(packet.get("lane", "")).strip()

    if not raw_pack_id:
        errors.append("packet.pack_id is missing or empty.")
    elif raw_pack_id != pack_id:
        warnings.append(f"packet.pack_id '{raw_pack_id}' != expected '{pack_id}'.")

    if not raw_game_scope:
        errors.append("packet.game_scope is missing or empty.")
    elif raw_game_scope != game_scope:
        warnings.append(f"packet.game_scope '{raw_game_scope}' != expected '{game_scope}'.")

    packet_lane = ""
    if not raw_lane:
        errors.append("packet.lane is missing or empty.")
    else:
        try:
            packet_lane = canonical_lane_value(raw_lane)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            if packet_lane != raw_lane:
                warnings.append(f"packet.lane '{raw_lane}' normalized to canonical '{packet_lane}'.")

    # 2. packet_status
    status = packet.get("packet_status", "").strip()
    allowed_statuses = {"reviewed", "ai_reviewed"}
    if status and status not in allowed_statuses:
        warnings.append(f"packet_status '{status}' is not in {sorted(allowed_statuses)}.")

    # 3. payload dir
    packet_dir = packet_path.parent
    payload_rel = packet.get("payload_path", "payload")
    payload_dir = _resolve_path_relative_to(packet_dir, payload_rel) or (packet_dir / "payload").resolve()
    expected_payload_dir = (packet_dir / "payload").resolve()
    if str(payload_rel).strip() != "payload":
        errors.append("packet.payload_path must be the canonical relative path 'payload'.")
    elif payload_dir != expected_payload_dir:
        errors.append(f"packet.payload_path resolves to unexpected location: {payload_dir}")
    if not payload_dir.is_dir():
        errors.append(f"payload_path missing: {payload_dir}")

    # 4. provenance.json
    provenance_path = packet_dir / "provenance.json"
    if provenance_required and not provenance_path.exists():
        errors.append(f"provenance.json missing: {provenance_path}")
    elif provenance_path.exists():
        try:
            provenance: dict[str, Any] = json.loads(provenance_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            errors.append(f"provenance.json is not valid JSON: {exc}")
        else:
            raw_provenance_lane = _canonical_provenance_value(provenance, "lane")
            if not raw_provenance_lane:
                errors.append("provenance.lane is missing or empty.")
                provenance_lane = ""
            else:
                try:
                    provenance_lane = canonical_lane_value(raw_provenance_lane)
                except ValueError as exc:
                    errors.append(str(exc))
                    provenance_lane = ""
                else:
                    if provenance_lane != raw_provenance_lane:
                        warnings.append(
                            f"provenance.lane '{raw_provenance_lane}' normalized to canonical '{provenance_lane}'."
                        )
                    if packet_lane and provenance_lane != packet_lane:
                        errors.append(
                            f"provenance.lane '{provenance_lane}' does not match packet.lane '{packet_lane}'."
                        )

            for field_id in _required_provenance_fields(provenance_lane or packet_lane or "direct_url"):
                if not _canonical_provenance_value(provenance, field_id):
                    errors.append(f"provenance.{field_id} is missing.")

            raw_payload_target_path = _canonical_provenance_value(provenance, "payload_target_path")
            if not raw_payload_target_path:
                errors.append("provenance.payload_target_path is missing.")
            else:
                payload_target_path = _resolve_path_relative_to(packet_dir, raw_payload_target_path)
                if payload_target_path != expected_payload_dir:
                    errors.append(
                        f"provenance.payload_target_path '{payload_target_path}' != expected '{expected_payload_dir}'."
                    )

            raw_source_adapter = _canonical_provenance_value(provenance, "source_adapter")
            if raw_source_adapter:
                try:
                    adapter = require_source_adapter(raw_source_adapter)
                except ValueError as exc:
                    errors.append(str(exc))
                else:
                    adapter_lane = adapter.lane.value
                    if packet_lane and adapter_lane != packet_lane:
                        errors.append(
                            f"provenance.source_adapter '{raw_source_adapter}' maps to lane '{adapter_lane}', "
                            f"not packet.lane '{packet_lane}'."
                        )

            if _requires_entitlement_note(_canonical_provenance_value(provenance, "license")):
                if not _canonical_provenance_value(provenance, "entitlement_note"):
                    errors.append("provenance.entitlement_note is required for non-open or store-gated licenses.")

    # 5. payload_files list
    payload_files: list[dict[str, Any]] = packet.get("payload_files") or []
    file_count = 0
    missing_files: list[str] = []
    if not payload_files:
        warnings.append("packet.payload_files is empty — did auto-packet generation run?")
    else:
        for entry in payload_files:
            if not isinstance(entry, dict):
                continue
            published_relative = entry.get("published_relative_path")
            relative_pack = entry.get("relative_pack_path")

            full: Path | None = None
            if published_relative:
                full = _resolve_path_relative_to(packet_dir, str(published_relative))
            elif relative_pack and payload_dir.is_dir():
                full = _resolve_path_relative_to(payload_dir, str(relative_pack))

            if full is None:
                continue

            if full.exists():
                file_count += 1
            else:
                missing_files.append(str(full))

    if missing_files:
        errors.append(f"Missing payload files: {len(missing_files)}")
        warnings.extend(f"missing payload file: {path}" for path in missing_files)

    passed = len(errors) == 0
    return ValidationResult(
        pack_id=pack_id,
        game_scope=game_scope,
        packet_path=str(packet_path),
        pass_=passed,
        errors=errors,
        warnings=warnings,
        payload_file_count=file_count,
    )


def scan_publish_dir(
    game_scope: str | None = None,
    *,
    library_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Scan publish/flax_intake/ and return a summary of all packs found.

    Each entry: {pack_id, game_scope, packet_path, has_packet, has_provenance,
                 packet_status, payload_file_count_on_disk}.
    """
    if library_root is None:
        from assetboy.library.paths import asset_library_root
        library_root = asset_library_root()

    intake_root = Path(library_root) / "publish" / "flax_intake"
    results: list[dict[str, Any]] = []

    if not intake_root.is_dir():
        return results

    for game_dir in sorted(intake_root.iterdir()):
        if not game_dir.is_dir():
            continue
        if game_scope and game_dir.name != game_scope:
            continue
        for pack_dir in sorted(game_dir.iterdir()):
            if not pack_dir.is_dir():
                continue
            packet_path = pack_dir / "packet.json"
            provenance_path = pack_dir / "provenance.json"
            has_packet = packet_path.exists()
            has_provenance = provenance_path.exists()
            status = ""
            payload_count = 0
            if has_packet:
                try:
                    p = json.loads(packet_path.read_text(encoding="utf-8-sig"))
                    status = p.get("packet_status", "")
                    payload_dir = (pack_dir / p.get("payload_path", "payload")).resolve()
                    if payload_dir.is_dir():
                        payload_count = sum(
                            1 for f in payload_dir.rglob("*")
                            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
                        )
                except Exception:  # noqa: BLE001
                    pass

            results.append({
                "game_scope": game_dir.name,
                "pack_id": pack_dir.name,
                "packet_path": str(packet_path),
                "has_packet": has_packet,
                "has_provenance": has_provenance,
                "packet_status": status,
                "payload_file_count": payload_count,
            })

    return results
