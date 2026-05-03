from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from assetboy.library.paths import assetboy_root


MESH_EXTENSIONS = {".fbx", ".obj", ".dae", ".gltf", ".glb"}
CANONICAL_MESH_EXTENSIONS = {".gltf", ".glb"}
THUMBNAIL_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

SIM_READY_HINT_TOKENS: dict[str, tuple[str, ...]] = {
    "articulation_candidates": ("door", "hinge", "wheel", "lever", "turret", "joint"),
    "socket_candidates": ("weapon", "sword", "shield", "rifle", "pistol", "tool", "backpack"),
    "collision_profile_hints": ("crate", "barrel", "pillar", "rock", "wall", "floor", "vehicle"),
}


def generator_registry_path() -> Path:
    return assetboy_root() / "profiles" / "generator_registry.json"


def load_generator_registry() -> dict[str, Any]:
    path = generator_registry_path()
    if not path.exists():
        return {"schema_version": "missing", "providers": []}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def lookup_generator_provider(source_adapter: str, registry: dict[str, Any]) -> dict[str, Any]:
    adapter = str(source_adapter or "").strip()
    providers = registry.get("providers", [])
    if not adapter or not isinstance(providers, list):
        return {}
    for provider in providers:
        if str(provider.get("adapter_id", "")).strip().lower() == adapter.lower():
            return dict(provider)
    return {}


def infer_source_format_summary(payload_files: list[dict[str, Any]]) -> dict[str, Any]:
    extension_counts: Counter[str] = Counter()
    total_bytes = 0
    for item in payload_files:
        relative_path = str(item.get("relative_pack_path", "")).strip()
        extension = Path(relative_path).suffix.lower()
        if extension:
            extension_counts[extension] += 1
        total_bytes += int(item.get("bytes", 0) or 0)

    mesh_extensions = {
        extension: count
        for extension, count in sorted(extension_counts.items())
        if extension in MESH_EXTENSIONS
    }
    canonical_mesh_count = sum(
        count for extension, count in mesh_extensions.items() if extension in CANONICAL_MESH_EXTENSIONS
    )
    noncanonical_mesh_count = sum(mesh_extensions.values()) - canonical_mesh_count

    return {
        "total_files": sum(extension_counts.values()),
        "total_bytes": total_bytes,
        "extensions": dict(sorted(extension_counts.items())),
        "mesh_extensions": mesh_extensions,
        "canonical_mesh_count": canonical_mesh_count,
        "noncanonical_mesh_count": noncanonical_mesh_count,
    }


def infer_sim_ready_hints(payload_files: list[dict[str, Any]]) -> dict[str, Any]:
    relative_paths = [str(item.get("relative_pack_path", "")).strip() for item in payload_files]
    lower_names = [Path(path).stem.lower() for path in relative_paths if path]

    hint_hits: dict[str, list[str]] = {}
    for hint_name, tokens in SIM_READY_HINT_TOKENS.items():
        hits = sorted({token for token in tokens if any(token in name for name in lower_names)})
        hint_hits[hint_name] = hits

    has_mesh = any(Path(path).suffix.lower() in MESH_EXTENSIONS for path in relative_paths)
    score = 0.25 if has_mesh else 0.0
    if hint_hits["collision_profile_hints"]:
        score += 0.25
    if hint_hits["socket_candidates"]:
        score += 0.25
    if hint_hits["articulation_candidates"]:
        score += 0.25

    return {
        "sim_ready_score": round(min(score, 1.0), 3),
        "has_mesh_payload": has_mesh,
        "hints": hint_hits,
        "recommended_next_steps": [
            "Run collision proxy generation for mesh payload.",
            "Review socket candidates for gameplay attachment points.",
            "Tag articulated parts before runtime rigging."
        ] if has_mesh else [],
    }


def infer_thumbnails(payload_files: list[dict[str, Any]], *, limit: int = 6) -> list[str]:
    thumbnails = []
    for item in payload_files:
        relative_path = str(item.get("relative_pack_path", "")).strip()
        if Path(relative_path).suffix.lower() in THUMBNAIL_EXTENSIONS:
            thumbnails.append(relative_path.replace("\\", "/"))
        if len(thumbnails) >= limit:
            break
    return thumbnails


def build_asset_metadata(
    *,
    pack_id: str,
    game_scope: str,
    payload_files: list[dict[str, Any]],
    provenance: dict[str, Any],
    conversion_report: dict[str, Any] | None = None,
    generator_registry: dict[str, Any] | None = None,
    source_folder: str = "",
) -> dict[str, Any]:
    source_adapter = str(provenance.get("source_adapter", "")).strip()
    lane = str(provenance.get("lane", "")).strip()
    registry = generator_registry or {"schema_version": "missing", "providers": []}
    provider_entry = lookup_generator_provider(source_adapter, registry)
    source_format = infer_source_format_summary(payload_files)
    sim_ready = infer_sim_ready_hints(payload_files)

    metadata = {
        "schema_version": "assetboy.asset_metadata.v1",
        "pack_id": pack_id,
        "game_scope": game_scope,
        "lane": lane,
        "source_adapter": source_adapter,
        "source_folder": source_folder,
        "provenance": {
            "source_url": str(provenance.get("source_url", "")).strip(),
            "download_url": str(provenance.get("download_url", "")).strip(),
            "source_page_url": str(provenance.get("source_page_url", "")).strip(),
            "license_url": str(provenance.get("license_url", "")).strip(),
            "author_or_vendor": str(provenance.get("author_or_vendor", "")).strip(),
            "notes": str(provenance.get("notes", "")).strip(),
        },
        "source_format": source_format,
        "canonicalization": conversion_report or {
            "status": "not_requested",
            "message": "No explicit canonicalization report was provided.",
        },
        "sim_ready": sim_ready,
        "thumbnails": infer_thumbnails(payload_files),
        "generator": {
            "registry_schema_version": str(registry.get("schema_version", "missing")).strip(),
            "provider": provider_entry,
            "model_name": str(provenance.get("model_name", "")).strip(),
            "profile_id": str(provenance.get("profile_id", "")).strip(),
            "prompt": str(provenance.get("prompt", "")).strip(),
            "negative_prompt": str(provenance.get("negative_prompt", "")).strip(),
            "seed": str(provenance.get("seed", "")).strip(),
            "notebook_or_session": str(provenance.get("notebook_or_session", "")).strip(),
        },
    }
    return metadata


def write_asset_metadata(pack_dir: Path, metadata: dict[str, Any]) -> Path:
    pack_dir.mkdir(parents=True, exist_ok=True)
    output_path = pack_dir / "asset_metadata.json"
    output_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return output_path
