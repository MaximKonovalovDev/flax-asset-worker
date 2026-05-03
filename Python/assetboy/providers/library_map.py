from __future__ import annotations

import json
import os
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, manual_drop_dir, publish_payload_dir
from assetboy.provenance.templates import build_provenance_template
from assetboy.cleanup.blender_mcp import build_cleanup_plan
from assetboy.providers.epic_vault import (
    build_local_epic_library_report,
    build_online_epic_library_map,
    default_epic_launcher_saved_data_dir,
    default_local_fab_library_db_path,
    emit_epic_cache_extractor_wave,
    emit_epic_dummy_project_job,
)
from assetboy.providers.extractor_bridge import ExtractorTool, emit_extractor_job
from assetboy.providers.fab_hybrid import build_online_fab_library_map
from assetboy.providers.unity_hub import build_unity_owned_library_map
from assetboy.providers.unity_runner import emit_unity_export_runner
from assetboy.providers.lanes import ProviderLane


_QUIXEL_API_BASE = "http://127.0.0.1:28241"
_QUIXEL_CATEGORY_NAMES = (
    "3d",
    "3dplant",
    "atlas",
    "brush",
    "decal",
    "displacement",
    "imperfection",
    "surface",
)
_QUIXEL_SKIP_PARTS = {
    ".bridge",
    ".quixel",
    "cache",
    "caches",
    "support",
    "thumbnails",
    "thumbs",
    "previews",
    "preview",
    "logs",
    "temp",
    "tmp",
    "zip",
    "zips",
}
_QUIXEL_SKIP_FILES = {
    "settings.json",
    "library.json",
    "categories.json",
    "manifest.json",
}
_DUMMY_DO_FIRST_KEYWORDS = (
    "roman",
    "arena",
    "gladiator",
    "combat",
    "animation",
    "anim",
    "parry",
    "character",
    "enemy",
    "spear",
    "shield",
    "sword",
    "weapon",
    "city",
    "building",
    "cave",
    "sample",
    "lyra",
)
_DUMMY_TOP_PRIORITY_PHRASES = (
    "game animation sample",
    "animation starter pack",
    "slay animation sample",
    "combat magic animations",
    "mega spear animation pack",
    "free fantasy weapon sample pack",
    "dark ruins megascans sample",
    "city sample buildings",
)
_DUMMY_SKIP_KEYWORDS = (
    "plugin",
    "manager",
    "system",
    "tools",
    "generator",
)
_DUMMY_DEMOTE_KEYWORDS = (
    "finger",
    "interaction",
    "blueprint",
    "designers",
    "poses",
)
_USEFUL_FAB_KEYWORDS = (
    "roman",
    "gladiator",
    "arena",
    "animation",
    "retargeted",
    "survival character",
    "warrior",
    "human melee",
    "character",
    "enemy",
    "gladius",
    "pugio",
    "shield",
    "spear",
    "villa",
    "courtyard",
    "ruins",
    "environment",
    "ambience",
    "music",
    "sound",
    "audio",
    "hud",
    "ui",
)
_USEFUL_UNITY_KEYWORDS = (
    "animation",
    "character",
    "melee",
    "motions",
    "dummy",
    "environment",
    "ruins",
    "courtyard",
    "sound",
    "audio",
    "ui",
)
_USEFUL_EPIC_FAMILIES = (
    "gameanimationsample",
    "animstarterpack",
    "lyra",
    "parryattack",
    "gasp",
    "citysamplebuildings",
    "electricdreamssample",
    "romancave",
    "contentexamples",
)
_USEFUL_DONOR_GAME_SCOPE = "arena_shared"
_USEFUL_DONOR_DEFAULT_PROJECT_PATH = Path(r"C:\Users\me\My project (1)")
_USEFUL_FAB_DONOR_SPECS: tuple[dict[str, Any], ...] = (
    {
        "listing_uid": "11d20d01-b764-4936-8163-cb20d05c369e",
        "pack_id": "SHARED_FAB_CHR_SURVIVAL_CHARACTER_FREE_11D20D01",
        "asset_kind": "character",
        "animated": True,
        "license_note": "Owned/downloaded Fab neutral asset. Export reviewed neutral files only.",
    },
    {
        "listing_uid": "e0dbddd5-54b9-4c56-9005-87c5f04785b0",
        "pack_id": "SHARED_FAB_CHR_WARRIOR_E0DBDDD5",
        "asset_kind": "character",
        "animated": True,
        "license_note": "Owned/downloaded Fab neutral asset. Export reviewed neutral files only.",
    },
    {
        "listing_uid": "ae6ea187-cf7d-4cad-8940-eca1916afe0c",
        "pack_id": "SHARED_FAB_WPN_ANCIENT_ROMAN_SWORD_GLADIUS_AE6EA187",
        "asset_kind": "weapon",
        "animated": False,
        "license_note": "Owned/downloaded Fab neutral asset. Export reviewed neutral files only.",
    },
    {
        "listing_uid": "332e2b59-9870-46fe-9537-81f697e036da",
        "pack_id": "SHARED_FAB_WPN_EMERALD_MAGIC_SPEAR_332E2B59",
        "asset_kind": "weapon",
        "animated": False,
        "license_note": "Owned/downloaded Fab neutral asset. Export reviewed neutral files only.",
    },
)
_USEFUL_FAB_BLOCKED_SPECS: tuple[dict[str, Any], ...] = (
    {
        "listing_uid": "259f8545-f820-47b3-8fc1-e8ec5458214d",
        "pack_id": "SHARED_FAB_ANM_GAME_ANIMATION_SAMPLE_RETARGETED_259F8545",
        "reason": "Downloaded Fab retargeted animation archives are truncated and must be re-downloaded before extraction.",
    },
)
_USEFUL_UNITY_DONOR_SPECS: tuple[dict[str, Any], ...] = (
    {
        "product_id": "178395",
        "pack_id": "SHARED_UNITY_CHR_HUMAN_CHARACTER_DUMMY_178395",
        "asset_kind": "character",
        "source_url": "https://assetstore.unity.com/packages/3d/characters/humanoids/humans/human-character-dummy-178395",
        "license_note": "Owned Unity Asset Store package. Import into throwaway Unity project and export reviewed neutral files only.",
    },
    {
        "product_id": "154271",
        "pack_id": "SHARED_UNITY_ANM_HUMAN_BASIC_MOTIONS_FREE_154271",
        "asset_kind": "animation",
        "source_url": "https://assetstore.unity.com/packages/3d/animations/human-basic-motions-free-154271",
        "license_note": "Owned Unity Asset Store package. Import into throwaway Unity project and export reviewed neutral files only.",
    },
    {
        "product_id": "165785",
        "pack_id": "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785",
        "asset_kind": "animation",
        "source_url": "https://assetstore.unity.com/packages/3d/animations/human-melee-animations-free-165785",
        "license_note": "Owned Unity Asset Store package. Import into throwaway Unity project and export reviewed neutral files only.",
    },
)


def _append_path(paths: list[Path], seen: set[str], candidate: str | Path | None) -> None:
    if candidate is None:
        return
    resolved = Path(candidate).expanduser()
    key = str(resolved).lower()
    if key in seen:
        return
    seen.add(key)
    paths.append(resolved)


def _iter_quixel_settings_candidates() -> tuple[Path, ...]:
    home = Path.home()
    roaming = home / "AppData" / "Roaming"
    local = home / "AppData" / "Local"
    return (
        roaming / "Bridge" / "settings.json",
        roaming / "Bridge" / "settings" / "settings.json",
        roaming / "Bridge-Bifrost" / "settings.json",
        roaming / "Bridge-Bifrost" / "settings" / "settings.json",
        local / "Bridge" / "settings.json",
        local / "Bridge" / "settings" / "settings.json",
    )


def _extract_paths_from_settings(value: Any) -> list[str]:
    discovered: list[str] = []

    def walk(node: Any, key_hint: str = "") -> None:
        if isinstance(node, dict):
            for key, nested in node.items():
                walk(nested, str(key))
            return
        if isinstance(node, list):
            for nested in node:
                walk(nested, key_hint)
            return
        if not isinstance(node, str):
            return

        text = node.strip()
        if not text:
            return

        lowered_hint = key_hint.lower()
        looks_like_path = (":\\" in text) or text.startswith("\\\\") or text.startswith("/")
        relevant_hint = any(
            token in lowered_hint
            for token in ("path", "folder", "library", "download", "megascans", "quixel")
        )
        relevant_text = any(token in text.lower() for token in ("megascans", "quixel", "bridge"))
        if looks_like_path and (relevant_hint or relevant_text):
            discovered.append(text)

    walk(value)
    return discovered


def _discover_quixel_roots_from_settings() -> tuple[Path, ...]:
    roots: list[Path] = []
    seen: set[str] = set()
    for settings_path in _iter_quixel_settings_candidates():
        if not settings_path.exists():
            continue
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for candidate in _extract_paths_from_settings(payload):
            _append_path(roots, seen, candidate)
    return tuple(roots)


def _default_quixel_path_candidates() -> tuple[Path, ...]:
    home = Path.home()
    documents = home / "Documents"
    public_documents = Path(r"C:\Users\Public\Documents")
    env_candidates = tuple(
        Path(value)
        for value in (
            os.environ.get("MEGASCANS_LIBRARY"),
            os.environ.get("MEGASCANS_ASSETS"),
            os.environ.get("QUIXEL_LIBRARY_ROOT"),
            os.environ.get("QUIXEL_BRIDGE_LIBRARY"),
        )
        if value
    )
    return (
        *env_candidates,
        documents / "Megascans Library",
        documents / "Megascans Assets",
        documents / "Quixel" / "Megascans Library",
        documents / "Bridge" / "Megascans Library",
        public_documents / "Megascans Library",
        home / "AppData" / "Roaming" / "Bridge",
        home / "AppData" / "Roaming" / "Bridge-Bifrost",
        home / "AppData" / "Local" / "Bridge",
        home / "AppData" / "Local" / "Megascans",
    )


def _probe_quixel_bridge_api(*, api_base: str = _QUIXEL_API_BASE, timeout_seconds: float = 2.0) -> dict[str, Any]:
    report: dict[str, Any] = {
        "api_base": api_base,
        "reachable": False,
        "megascans_folder": "",
        "zip_folders": [],
        "asset_count": 0,
        "category_counts": {},
        "error": "",
    }

    try:
        folder_response = requests.get(f"{api_base}/GetMegascansFolder/", timeout=timeout_seconds)
        folder_response.raise_for_status()
        folder_payload = folder_response.json() if folder_response.content else {}
        report["reachable"] = True
        report["megascans_folder"] = str(folder_payload.get("folder", "")).strip()
    except Exception as exc:
        report["error"] = str(exc)
        return report

    try:
        zip_response = requests.get(f"{api_base}/GetZipFolderPaths/", timeout=timeout_seconds)
        zip_response.raise_for_status()
        zip_payload = zip_response.json() if zip_response.content else {}
        folders = zip_payload.get("folders") or []
        report["zip_folders"] = [str(item).strip() for item in folders if str(item).strip()]
    except Exception:
        report["zip_folders"] = []

    try:
        assets_response = requests.get(f"{api_base}/GetAllAssets/", timeout=max(timeout_seconds, 5.0))
        assets_response.raise_for_status()
        assets_payload = assets_response.json() if assets_response.content else {}
        assets = assets_payload.get("assets") or []
        category_counts: Counter[str] = Counter()
        for asset in assets:
            folder = str((asset or {}).get("folder", "")).strip()
            category = _quixel_category_from_parts(Path(folder).parts)
            category_counts[category] += 1
        report["asset_count"] = len(assets)
        report["category_counts"] = dict(sorted(category_counts.items(), key=lambda item: (-item[1], item[0])))
    except Exception:
        report["asset_count"] = 0
        report["category_counts"] = {}

    return report


def _quixel_category_from_parts(parts: tuple[str, ...] | list[str]) -> str:
    lowered = [part.lower() for part in parts]
    for candidate in _QUIXEL_CATEGORY_NAMES:
        if candidate in lowered:
            return candidate
    if lowered:
        return lowered[0]
    return "unknown"


def _looks_like_quixel_asset_json(path: Path, *, root: Path | None = None) -> bool:
    if path.name.lower() in _QUIXEL_SKIP_FILES:
        return False
    try:
        relevant_parts = path.relative_to(root).parts if root is not None else path.parts
    except Exception:
        relevant_parts = path.parts
    lowered_parts = {part.lower() for part in relevant_parts}
    if lowered_parts & _QUIXEL_SKIP_PARTS:
        return False
    return path.suffix.lower() == ".json"


def scan_quixel_library_root(root: str | Path, *, sample_limit: int = 24) -> dict[str, Any]:
    resolved = Path(root)
    category_counts: Counter[str] = Counter()
    sample_assets: list[dict[str, str]] = []
    asset_count = 0
    json_count = 0

    if not resolved.exists():
        return {
            "root": str(resolved),
            "exists": False,
            "asset_count": 0,
            "json_file_count": 0,
            "category_counts": {},
            "sample_assets": [],
        }

    for json_path in resolved.rglob("*.json"):
        if not _looks_like_quixel_asset_json(json_path, root=resolved):
            continue
        json_count += 1
        relative_parts = json_path.relative_to(resolved).parts
        category = _quixel_category_from_parts(relative_parts)
        category_counts[category] += 1
        asset_count += 1
        if len(sample_assets) < sample_limit:
            sample_assets.append(
                {
                    "name": json_path.stem,
                    "category": category,
                    "json_path": str(json_path),
                }
            )

    return {
        "root": str(resolved),
        "exists": True,
        "asset_count": asset_count,
        "json_file_count": json_count,
        "category_counts": dict(sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))),
        "sample_assets": sample_assets,
    }


def build_local_quixel_library_map(
    *,
    extra_roots: tuple[str | Path, ...] = (),
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    api_report = _probe_quixel_bridge_api(timeout_seconds=timeout_seconds)
    roots: list[Path] = []
    seen: set[str] = set()

    for candidate in _default_quixel_path_candidates():
        _append_path(roots, seen, candidate)
    for candidate in _discover_quixel_roots_from_settings():
        _append_path(roots, seen, candidate)
    for candidate in extra_roots:
        _append_path(roots, seen, candidate)

    if api_report.get("megascans_folder"):
        _append_path(roots, seen, str(api_report["megascans_folder"]))
    for candidate in api_report.get("zip_folders", []):
        _append_path(roots, seen, candidate)

    existing_roots = [path for path in roots if path.exists()]
    scanned_roots = [scan_quixel_library_root(path) for path in existing_roots]
    combined_categories: Counter[str] = Counter()
    for item in scanned_roots:
        for category, count in dict(item.get("category_counts", {})).items():
            combined_categories[category] += int(count)

    total_assets = sum(int(item.get("asset_count", 0)) for item in scanned_roots)
    total_assets = max(total_assets, int(api_report.get("asset_count", 0)))
    return {
        "api": api_report,
        "detected_roots": [str(path) for path in existing_roots],
        "scanned_roots": scanned_roots,
        "summary": {
            "detected_root_count": len(existing_roots),
            "total_assets": total_assets,
            "category_counts": dict(sorted(combined_categories.items(), key=lambda item: (-item[1], item[0]))),
            "bridge_api_reachable": bool(api_report.get("reachable")),
        },
    }


def render_local_quixel_library_map_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    api = dict(report.get("api", {}))
    lines = [
        "# Local Quixel / Megascans Map",
        "",
        f"- Bridge API reachable: `{bool(summary.get('bridge_api_reachable'))}`",
        f"- Detected roots: `{summary.get('detected_root_count', 0)}`",
        f"- Total assets: `{summary.get('total_assets', 0)}`",
        "",
    ]
    if api.get("megascans_folder"):
        lines.append(f"- API Megascans folder: `{api.get('megascans_folder', '')}`")
    if api.get("error"):
        lines.append(f"- API note: `{api['error']}`")
    if api.get("zip_folders"):
        lines.append(f"- API zip folders: `{', '.join(str(item) for item in api['zip_folders'])}`")
    lines.append("")

    category_counts = summary.get("category_counts") or {}
    if category_counts:
        lines.extend(["## Category Counts", ""])
        for category, count in category_counts.items():
            lines.append(f"- `{category}`: `{count}`")
        lines.append("")

    for item in report.get("scanned_roots", []) or []:
        lines.extend(
            [
                f"## {item.get('root', '')}",
                "",
                f"- Assets: `{item.get('asset_count', 0)}`",
                f"- Metadata JSON files: `{item.get('json_file_count', 0)}`",
            ]
        )
        counts = item.get("category_counts") or {}
        if counts:
            lines.append(f"- Categories: `{', '.join(f'{name}:{count}' for name, count in counts.items())}`")
        samples = item.get("sample_assets") or []
        if samples:
            lines.append("- Samples:")
            for sample in samples[:8]:
                lines.append(f"  - `{sample.get('category', 'unknown')}` | `{sample.get('name', '')}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def detect_optional_library_tools() -> dict[str, str]:
    home = Path.home()
    candidates = {
        "UEVaultManager": (
            "UEVaultManager",
            home / "AppData" / "Local" / "Programs" / "Python" / "Python312" / "Scripts" / "UEVaultManager.exe",
        ),
        "FModel": (
            "FModel.exe",
            Path(r"C:\SHARE\Tools\FModel\FModel.exe"),
        ),
        "Legendary": ("legendary", "legendary.exe"),
        "Rare": ("rare", "rare.exe"),
        "EpicAssetManager": ("epic-asset-manager", "EpicAssetManager.exe"),
    }
    detected: dict[str, str] = {}
    for label, values in candidates.items():
        for value in values:
            if isinstance(value, Path):
                if value.exists():
                    detected[label] = str(value)
                    break
                continue
            if resolved := shutil.which(value):
                detected[label] = resolved
                break
    return detected


def _normalize_lookup_token(value: str) -> str:
    lowered = value.lower()
    return "".join(character for character in lowered if character.isalnum())


def _dummy_family_prefix(title: str, listing_type: str, keywords: list[str]) -> str:
    lowered = title.lower()
    keyword_set = set(keywords)
    if listing_type == "animation" or "animation" in keyword_set or "anim" in keyword_set:
        return "SHARED_EPIC_ANM"
    if any(token in lowered for token in ("character", "enemy", "npc", "fighter")):
        return "SHARED_EPIC_CHR"
    if any(token in lowered for token in ("sword", "shield", "spear", "weapon")):
        return "SHARED_EPIC_WPN"
    if any(token in lowered for token in ("arena", "city", "building", "cave", "ruin", "environment")):
        return "SHARED_EPIC_ENV"
    return "SHARED_EPIC_MISC"


def _dummy_pack_id(title: str, listing_uid: str, listing_type: str, keywords: list[str]) -> str:
    prefix = _dummy_family_prefix(title, listing_type, keywords)
    token = _normalize_lookup_token(title)[:28].upper() or "ITEM"
    uid_fragment = _normalize_lookup_token(listing_uid)[:8].upper() or "UNKNOWN"
    return f"{prefix}_{token}_{uid_fragment}"


def rank_fab_dummy_project_candidates(
    fab_report: dict[str, Any],
    local_report: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    local_title_tokens = {
        _normalize_lookup_token(str(entry.get("title", "")))
        for entry in local_report.get("confirmed_cached_entries", []) or []
        if str(entry.get("title", "")).strip()
    }
    launcher_title_tokens = {
        _normalize_lookup_token(str(entry.get("family", "")))
        for entry in local_report.get("launcher_cache_candidates", []) or []
        if str(entry.get("family", "")).strip()
    }

    do_first: list[dict[str, Any]] = []
    do_later: list[dict[str, Any]] = []
    skip: list[dict[str, Any]] = []

    for entry in fab_report.get("records", []) or []:
        if entry.get("route") != "unreal_only":
            continue

        title = str(entry.get("title", "")).strip()
        if not title:
            continue
        title_token = _normalize_lookup_token(title)
        keywords = [str(item).strip().lower() for item in entry.get("keywords", []) or [] if str(item).strip()]
        listing_type = str(entry.get("listing_type", "")).strip()
        score = 0
        reasons: list[str] = []
        title_lower = title.lower()

        if listing_type in {"animation", "3d-model", "tutorials-examples"}:
            score += 8 if listing_type != "animation" else 10
            reasons.append(f"type:{listing_type}")
        elif listing_type == "game-template":
            score += 2
            reasons.append("type:template")
        elif listing_type in {"tool-and-plugin", "game-system"}:
            score -= 5
            reasons.append(f"type:{listing_type}")

        for keyword in keywords:
            if keyword in _DUMMY_DO_FIRST_KEYWORDS:
                score += 4
        if any(token in title_lower for token in _DUMMY_DO_FIRST_KEYWORDS):
            score += 3
        if any(phrase in title_lower for phrase in _DUMMY_TOP_PRIORITY_PHRASES):
            score += 6
            reasons.append("top_priority_phrase")

        if any(token in title_lower for token in _DUMMY_SKIP_KEYWORDS):
            score -= 6
            reasons.append("plugin_or_system")
        if any(token in title_lower for token in _DUMMY_DEMOTE_KEYWORDS):
            score -= 5
            reasons.append("demote_non_core_animation")

        if title_token in local_title_tokens:
            score -= 10
            reasons.append("already_cached")
        if any(token and token in title_token for token in launcher_title_tokens):
            score -= 1
            reasons.append("launcher_hint_seen")

        candidate = {
            "title": title,
            "listing_uid": str(entry.get("listing_uid", "")).strip(),
            "listing_url": str(entry.get("listing_url", "")).strip(),
            "listing_type": listing_type,
            "publisher_name": str(entry.get("publisher_name", "")).strip(),
            "keywords": keywords,
            "score": score,
            "reasons": reasons,
            "pack_id": _dummy_pack_id(title, str(entry.get("listing_uid", "")), listing_type, keywords),
        }

        if "already_cached" in reasons:
            skip.append(candidate | {"bucket": "skip", "why": "already_cached_locally"})
        elif score >= 8:
            do_first.append(candidate | {"bucket": "do_first"})
        elif score >= 1:
            do_later.append(candidate | {"bucket": "do_later"})
        else:
            skip.append(candidate | {"bucket": "skip", "why": "low_value_or_plugin_heavy"})

    sort_key = lambda item: (-int(item.get("score", 0)), str(item.get("title", "")).lower())
    return {
        "do_first": sorted(do_first, key=sort_key),
        "do_later": sorted(do_later, key=sort_key),
        "skip": sorted(skip, key=sort_key),
    }


def render_fab_dummy_project_wave_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Fab Dummy-Project Wave",
        "",
        f"- Do first: `{len(report.get('do_first', []))}`",
        f"- Do later: `{len(report.get('do_later', []))}`",
        f"- Skip: `{len(report.get('skip', []))}`",
        f"- Emitted jobs: `{len(report.get('emitted_jobs', []))}`",
        "",
    ]
    for section_name in ("do_first", "do_later", "skip"):
        entries = list(report.get(section_name, []) or [])
        if not entries:
            continue
        lines.extend([f"## {section_name.replace('_', ' ').title()}", ""])
        for entry in entries[:20]:
            lines.append(
                f"- {entry.get('title', '')} | score=`{entry.get('score', 0)}` | type=`{entry.get('listing_type', '')}` | reasons=`{', '.join(entry.get('reasons', [])) or '-'}`"
            )
        lines.append("")
    emitted = list(report.get("emitted_jobs", []) or [])
    if emitted:
        lines.extend(["## Emitted Jobs", ""])
        for entry in emitted:
            lines.append(f"- `{entry.get('pack_id', '')}` -> `{entry.get('job_output_dir', '')}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def emit_fab_dummy_project_wave(
    *,
    fab_report: dict[str, Any] | None = None,
    local_report: dict[str, Any] | None = None,
    game_scope: str = "arena_shared",
    engine_association: str = "5.3",
    max_jobs: int = 8,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved_output_dir = Path(output_dir) if output_dir is not None else generated_output_root() / "fab_dummy_project_wave"
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    live_fab_report = fab_report or build_online_fab_library_map()
    live_local_report = local_report or build_local_epic_library_report(default_local_fab_library_db_path(), tuple(sorted(default_epic_launcher_saved_data_dir().glob("OC_*.dat"))))
    ranking = rank_fab_dummy_project_candidates(live_fab_report, live_local_report)
    emitted_jobs: list[dict[str, str]] = []

    for candidate in list(ranking.get("do_first", []))[:max_jobs]:
        title = str(candidate.get("title", "")).strip() or "Dummy Project"
        project_name = "".join(character if character.isalnum() else "_" for character in title)[:48].strip("_") or "DummyProject"
        artifacts = emit_epic_dummy_project_job(
            pack_id=str(candidate["pack_id"]),
            game_scope=game_scope,
            source_url=str(candidate.get("listing_url", "")),
            engine_association=engine_association,
            project_name=project_name,
            output_dir=resolved_output_dir / str(candidate["pack_id"]),
            notes=(f"Fab owned Unreal-only listing: {title}",),
        )
        emitted_jobs.append(
            {
                "pack_id": str(candidate["pack_id"]),
                "title": title,
                "job_output_dir": str(artifacts.output_dir),
                "uproject_path": str(artifacts.uproject_path),
                "command_template_path": str(artifacts.command_template_path),
                "listing_url": str(candidate.get("listing_url", "")),
            }
        )

    report = {
        "game_scope": game_scope,
        "engine_association": engine_association,
        "max_jobs": max_jobs,
        "do_first": ranking["do_first"],
        "do_later": ranking["do_later"],
        "skip": ranking["skip"],
        "emitted_jobs": emitted_jobs,
    }
    write_json(resolved_output_dir / "fab_dummy_project_wave.json", report)
    write_text(resolved_output_dir / "fab_dummy_project_wave.md", render_fab_dummy_project_wave_markdown(report))
    return report


def _find_first_record(records: list[dict[str, Any]], *needles: str) -> dict[str, Any] | None:
    for record in records:
        title = str(record.get("title", "")).lower()
        if all(needle.lower() in title for needle in needles):
            return record
    return None


def _choose_arena_direct_candidates(fab_records: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    neutral_records = [item for item in fab_records if item.get("route") == "neutral_or_mixed"]

    arena_shell = (
        _find_first_record(neutral_records, "roman", "arena")
        or _find_first_record(neutral_records, "roman", "modular")
        or _find_first_record(neutral_records, "sandstone", "modular")
        or _find_first_record(neutral_records, "roman", "villa")
    )
    animation_primary = (
        _find_first_record(neutral_records, "game animation sample", "retargeted")
        or _find_first_record(neutral_records, "animation", "retargeted")
        or _find_first_record(neutral_records, "animations only")
    )
    combat_sfx = (
        _find_first_record(neutral_records, "combat", "sfx")
        or _find_first_record(neutral_records, "battle", "sfx")
        or _find_first_record(neutral_records, "combat", "sound")
    )
    arena_music = (
        _find_first_record(neutral_records, "arena", "music")
        or _find_first_record(neutral_records, "battle", "music")
        or _find_first_record(neutral_records, "combat", "music")
        or _find_first_record(neutral_records, "ambience")
    )
    ui_hud = (
        _find_first_record(neutral_records, "hud")
        or _find_first_record(neutral_records, "user interface")
        or _find_first_record(neutral_records, "interface")
    )

    return {
        "character_primary": (
            _find_first_record(neutral_records, "gladiator", "character")
            or _find_first_record(neutral_records, "survival", "character")
            or _find_first_record(neutral_records, "warrior")
        ),
        "enemy_variant": (
            _find_first_record(neutral_records, "warrior")
            or _find_first_record(neutral_records, "fighter")
            or _find_first_record(neutral_records, "gladiator")
        ),
        "animation_primary": animation_primary,
        "weapon_gladius": _find_first_record(neutral_records, "roman", "gladius"),
        "weapon_dagger": _find_first_record(neutral_records, "roman", "pugio"),
        "weapon_shield": (
            _find_first_record(neutral_records, "roman republican shield")
            or _find_first_record(neutral_records, "gladiator shield")
            or _find_first_record(neutral_records, "roman", "shield")
        ),
        "weapon_spear": _find_first_record(neutral_records, "spear"),
        "arena_shell": arena_shell,
        "combat_sfx": combat_sfx,
        "arena_music": arena_music,
        "ui_hud": ui_hud,
    }


def _pick_dummy_wave_titles(dummy_wave: dict[str, Any], wanted_titles: tuple[str, ...]) -> list[dict[str, Any]]:
    do_first = list(dummy_wave.get("do_first", []) or [])
    selected: list[dict[str, Any]] = []
    wanted_lower = [title.lower() for title in wanted_titles]
    for wanted in wanted_lower:
        for entry in do_first:
            if str(entry.get("title", "")).lower() == wanted:
                selected.append(entry)
                break
    return selected


def build_arena_owned_wave(
    combined_report: dict[str, Any],
    dummy_wave_report: dict[str, Any],
) -> dict[str, Any]:
    fab_records = list((combined_report.get("fab_online") or {}).get("records", []) or [])
    local_report = dict(combined_report.get("epic_local", {}))
    direct_candidates = _choose_arena_direct_candidates(fab_records)
    local_cached = list(local_report.get("confirmed_cached_entries", []) or [])

    local_lookup = {
        _normalize_lookup_token(str(entry.get("title", ""))): entry
        for entry in local_cached
        if str(entry.get("title", "")).strip()
    }

    animation_titles = (
        "Game Animation Sample",
        "Animation Starter Pack",
        "Slay Animation Sample",
        "Mega Spear Animation Pack",
        "Combat Magic Animations",
        "Free Animation Library",
        "FREE Dramatic Death – Animation Performances for NPCs & Cinematics",
    )
    dummy_animation_jobs = _pick_dummy_wave_titles(dummy_wave_report, animation_titles)
    environment_titles = (
        "Dark Ruins Megascans Sample",
        "City Sample Buildings",
    )
    dummy_environment_jobs = _pick_dummy_wave_titles(dummy_wave_report, environment_titles)

    cached_animation_sources = [
        entry
        for key, entry in local_lookup.items()
        if any(token in key for token in ("gasp", "parryattacksystem"))
    ]
    cached_environment_sources = [
        entry
        for key, entry in local_lookup.items()
        if "abandonedlighthouseisland" in key
    ]

    actions = {
        "idle_walk_run_sprint": ["Game Animation Sample", "Animation Starter Pack", "GASP: Basic Template for FPS with Spatial Inventory"],
        "jump_land_strafe": ["Game Animation Sample", "Animation Starter Pack", "GASP: Basic Template for FPS with Spatial Inventory"],
        "light_heavy_attacks": ["Slay Animation Sample", "Parry Attack System", "Combat Magic Animations"],
        "block_parry_hit_react": ["Parry Attack System", "Slay Animation Sample"],
        "death": ["FREE Dramatic Death – Animation Performances for NPCs & Cinematics", "Parry Attack System"],
        "spear_actions": ["Mega Spear Animation Pack"],
    }
    action_sources = {source for sources in actions.values() for source in sources}

    character_primary = direct_candidates["character_primary"]
    enemy_variant = direct_candidates["enemy_variant"]
    character_compatibility = (
        "same_or_compatible_rig"
        if character_primary and enemy_variant
        else "needs_manual_rig_compatibility_check"
    )

    return {
        "summary": {
            "direct_candidate_count": sum(1 for item in direct_candidates.values() if item),
            "dummy_animation_job_count": len(dummy_animation_jobs),
            "dummy_environment_job_count": len(dummy_environment_jobs),
            "cached_animation_source_count": len(cached_animation_sources),
            "cached_environment_source_count": len(cached_environment_sources),
            "action_source_count": len(action_sources),
        },
        "roman_targets": {
            "RA_PACK_CHR_CORE_SLICE_01": {
                "primary_direct_candidate": character_primary,
                "secondary_direct_candidate": enemy_variant,
                "compatibility_goal": character_compatibility,
                "notes": "Use a direct neutral-format humanoid first, then retarget to the shared combat stack.",
            },
            "RA_PACK_CHR_DUELIST_SLICE_01": {
                "primary_direct_candidate": enemy_variant,
                "secondary_direct_candidate": character_primary,
                "compatibility_goal": character_compatibility,
                "notes": "Use the second compatible humanoid as the first enemy/variant route.",
            },
            "RA_PACK_ANM_COMBAT_SLICE_01": {
                "primary_direct_candidate": direct_candidates["animation_primary"],
                "dummy_project_jobs": dummy_animation_jobs,
                "cached_sources": cached_animation_sources,
                "action_coverage_plan": actions,
                "notes": "Prefer neutral FBX animation sets first, then fill coverage with Unreal-only sample extraction jobs.",
            },
            "RA_PACK_WPN_COMBAT_SLICE_01": {
                "direct_candidates": [
                    candidate
                    for key, candidate in direct_candidates.items()
                    if key.startswith("weapon_") and candidate
                ],
                "notes": "Sword and shield should come from direct neutral Roman assets first; spear can fall back to the Unreal sample wave if needed.",
            },
            "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01": {
                "direct_candidate": direct_candidates["arena_shell"],
                "dummy_project_jobs": dummy_environment_jobs,
                "cached_sources": cached_environment_sources,
                "notes": "Use owned Roman direct environment kits first, then supplement with cached Unreal environment packs for shell dressing and extract patterns.",
            },
            "RA_PACK_AUD_SFX_SLICE_01": {
                "primary_direct_candidate": direct_candidates["combat_sfx"],
                "cached_sources": cached_animation_sources,
                "notes": "GASP and Parry cache are the best Unreal-side sound extraction candidates already on disk.",
            },
            "RA_PACK_AUD_MUSIC_SLICE_01": {
                "primary_direct_candidate": direct_candidates["arena_music"],
                "notes": "If the owned library does not provide a strong arena loop, keep the existing reviewed bootstrap ambience/music pack and upgrade later.",
            },
            "RA_PACK_UI_COMBAT_SLICE_01": {
                "primary_direct_candidate": direct_candidates["ui_hud"],
                "notes": "Optional only. Use owned UI/HUD art if it exists; otherwise keep the current bootstrap packet.",
            },
        },
    }


def render_arena_owned_wave_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# Arena Owned Wave",
        "",
        f"- Direct neutral candidates: `{summary.get('direct_candidate_count', 0)}`",
        f"- Dummy animation jobs: `{summary.get('dummy_animation_job_count', 0)}`",
        f"- Dummy environment jobs: `{summary.get('dummy_environment_job_count', 0)}`",
        f"- Cached animation sources: `{summary.get('cached_animation_source_count', 0)}`",
        f"- Cached environment sources: `{summary.get('cached_environment_source_count', 0)}`",
        f"- Action source families: `{summary.get('action_source_count', 0)}`",
        "",
    ]
    roman_targets = dict(report.get("roman_targets", {}))
    for pack_id, target in roman_targets.items():
        lines.extend([f"## {pack_id}", ""])
        primary = target.get("primary_direct_candidate")
        if isinstance(primary, dict):
            lines.append(f"- Primary direct candidate: {primary.get('title', '')} | `{primary.get('listing_url', '')}`")
        secondary = target.get("secondary_direct_candidate")
        if isinstance(secondary, dict):
            lines.append(f"- Secondary direct candidate: {secondary.get('title', '')} | `{secondary.get('listing_url', '')}`")
        direct = target.get("direct_candidate")
        if isinstance(direct, dict):
            lines.append(f"- Direct candidate: {direct.get('title', '')} | `{direct.get('listing_url', '')}`")
        direct_candidates = target.get("direct_candidates") or []
        for item in direct_candidates:
            lines.append(f"- Direct candidate: {item.get('title', '')} | `{item.get('listing_url', '')}`")
        compatibility_goal = str(target.get("compatibility_goal", "")).strip()
        if compatibility_goal:
            lines.append(f"- Compatibility goal: `{compatibility_goal}`")
        dummy_jobs = target.get("dummy_project_jobs") or []
        for item in dummy_jobs:
            lines.append(f"- Dummy-project candidate: {item.get('title', '')} | `{item.get('listing_url', '')}`")
        dummy_candidate = target.get("dummy_project_candidate")
        if isinstance(dummy_candidate, dict):
            lines.append(f"- Dummy-project candidate: {dummy_candidate.get('title', '')} | `{dummy_candidate.get('listing_url', '')}`")
        cached_sources = target.get("cached_sources") or []
        for item in cached_sources:
            lines.append(f"- Cached source: {item.get('title', '')}")
        notes = str(target.get("notes", "")).strip()
        if notes:
            lines.append(f"- Notes: {notes}")
        action_plan = target.get("action_coverage_plan") or {}
        for action, sources in action_plan.items():
            lines.append(f"- {action}: `{', '.join(str(item) for item in sources)}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def emit_arena_owned_wave(
    *,
    combined_report: dict[str, Any] | None = None,
    dummy_wave_report: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved_output_dir = Path(output_dir) if output_dir is not None else generated_output_root() / "arena_owned_wave"
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    live_combined = combined_report or build_combined_library_map()
    live_dummy_wave = dummy_wave_report or emit_fab_dummy_project_wave(
        output_dir=resolved_output_dir / "fab_dummy_project_wave",
    )
    report = build_arena_owned_wave(live_combined, live_dummy_wave)
    write_json(resolved_output_dir / "arena_owned_wave.json", report)
    write_text(resolved_output_dir / "arena_owned_wave.md", render_arena_owned_wave_markdown(report))
    return report


def _arena_dummy_asset_kind(entry: dict[str, Any]) -> str:
    pack_id = str(entry.get("pack_id", "")).upper()
    listing_type = str(entry.get("listing_type", "")).strip().lower()
    if "_ENV_" in pack_id:
        return "architecture"
    if "_ANM_" in pack_id or listing_type == "animation":
        return "character"
    return "prop"


def _dedupe_cached_sources(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for entry in group:
            title = str(entry.get("title", "")).strip()
            if not title:
                continue
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(entry)
    return deduped


def build_arena_extraction_wave(
    arena_report: dict[str, Any],
    dummy_wave_report: dict[str, Any],
    *,
    game_scope: str = "arena_shared",
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved_output_dir = Path(output_dir) if output_dir is not None else generated_output_root() / "arena_extraction_wave"
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    roman_targets = dict(arena_report.get("roman_targets", {}))
    cached_entries = _dedupe_cached_sources(
        list((roman_targets.get("RA_PACK_ANM_COMBAT_SLICE_01") or {}).get("cached_sources", []) or []),
        list((roman_targets.get("RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01") or {}).get("cached_sources", []) or []),
        list((roman_targets.get("RA_PACK_AUD_SFX_SLICE_01") or {}).get("cached_sources", []) or []),
    )
    cached_extractors = emit_epic_cache_extractor_wave(
        cached_entries,
        game_scope=game_scope,
        tool=ExtractorTool.FMODEL,
        output_dir=resolved_output_dir / "epic_cache_extractors",
    )

    dummy_emitted_jobs = list(dummy_wave_report.get("emitted_jobs", []) or [])
    dummy_extractors: list[dict[str, Any]] = []
    for entry in dummy_emitted_jobs:
        pack_id = str(entry.get("pack_id", "")).strip()
        title = str(entry.get("title", "")).strip()
        listing_url = str(entry.get("listing_url", "")).strip()
        if not pack_id or not title or not listing_url:
            continue
        artifacts = emit_extractor_job(
            tool=ExtractorTool.FMODEL,
            pack_id=pack_id,
            game_scope=game_scope,
            source_package_name=title,
            source_url=listing_url,
            license_note="Owned Fab Unreal-only asset via dummy project",
            input_path_hint=str(manual_drop_dir() / pack_id / "epic_raw"),
            asset_kind=_arena_dummy_asset_kind(entry),
            output_dir=resolved_output_dir / "dummy_project_extractors" / pack_id,
        )
        dummy_extractors.append(
            {
                "pack_id": pack_id,
                "title": title,
                "listing_url": listing_url,
                "dummy_project_job_output_dir": str(entry.get("job_output_dir", "")),
                "dummy_project_command_template_path": str(entry.get("command_template_path", "")),
                "artifacts": artifacts.to_dict(),
            }
        )

    report = {
        "summary": {
            "cached_extractors": len(cached_extractors),
            "dummy_project_extractors": len(dummy_extractors),
            "total_extractors": len(cached_extractors) + len(dummy_extractors),
        },
        "local_cached_extractors": cached_extractors,
        "dummy_project_extractors": dummy_extractors,
        "recommended_order": [
            "Run local cached extractors first: GASP, Parry Attack System, Abandoned Lighthouse Island.",
            "Then use the dummy-project jobs to Add to Project for the owned Unreal-only animation and environment packs.",
            "After each Add to Project, run the paired extractor job under dummy_project_extractors.",
            "Review exported meshes, animations, textures, and sounds before packet publish.",
        ],
    }
    write_json(resolved_output_dir / "arena_extraction_wave.json", report)
    write_text(resolved_output_dir / "arena_extraction_wave.md", render_arena_extraction_wave_markdown(report))
    return report


def render_arena_extraction_wave_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# Arena Extraction Wave",
        "",
        f"- Cached extractors: `{summary.get('cached_extractors', 0)}`",
        f"- Dummy-project extractors: `{summary.get('dummy_project_extractors', 0)}`",
        f"- Total extractors: `{summary.get('total_extractors', 0)}`",
        "",
        "## Local Cached Extractors",
        "",
    ]
    for entry in report.get("local_cached_extractors", []) or []:
        artifacts = dict(entry.get("artifacts", {}))
        lines.append(f"- {entry.get('title', '')} -> `{artifacts.get('output_dir', '')}`")
    lines.extend(["", "## Dummy-Project Extractors", ""])
    for entry in report.get("dummy_project_extractors", []) or []:
        artifacts = dict(entry.get("artifacts", {}))
        lines.append(f"- {entry.get('title', '')} -> `{artifacts.get('output_dir', '')}`")
        lines.append(f"  Dummy project job: `{entry.get('dummy_project_job_output_dir', '')}`")
    lines.extend(["", "## Recommended Order", ""])
    for step in report.get("recommended_order", []) or []:
        lines.append(f"- {step}")
    return "\n".join(lines).strip() + "\n"


def emit_arena_extraction_wave(
    *,
    arena_report: dict[str, Any] | None = None,
    dummy_wave_report: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    game_scope: str = "arena_shared",
) -> dict[str, Any]:
    resolved_output_dir = Path(output_dir) if output_dir is not None else generated_output_root() / "arena_extraction_wave"
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    live_arena = arena_report or emit_arena_owned_wave(output_dir=resolved_output_dir / "arena_owned_wave")
    live_dummy = dummy_wave_report or json.loads(
        (resolved_output_dir / "arena_owned_wave" / "fab_dummy_project_wave" / "fab_dummy_project_wave.json").read_text(encoding="utf-8")
    )
    return build_arena_extraction_wave(
        live_arena,
        live_dummy,
        game_scope=game_scope,
        output_dir=resolved_output_dir,
    )


def _score_useful_fab_record(entry: dict[str, Any]) -> int:
    title = str(entry.get("title", "")).lower()
    route = str(entry.get("route", "")).strip()
    format_codes = [str(item).lower() for item in entry.get("format_codes", []) or [] if str(item).strip()]
    score = 0
    if route == "neutral_or_mixed":
        score += 8
    elif route == "unreal_only":
        score += 2
    for keyword in _USEFUL_FAB_KEYWORDS:
        if keyword in title:
            score += 3
    if "fbx" in format_codes:
        score += 4
    if any(code in format_codes for code in ("glb", "gltf", "obj", "wav")):
        score += 2
    if "unreal-engine" in format_codes:
        score -= 2
    return score


def _choose_useful_fab_records(fab_report: dict[str, Any], *, limit: int = 16) -> list[dict[str, Any]]:
    chosen: dict[str, dict[str, Any]] = {}
    for entry in fab_report.get("roman_candidates", []) or []:
        listing_uid = str(entry.get("listing_uid", "")).strip()
        if listing_uid:
            chosen[listing_uid] = entry

    for entry in fab_report.get("records", []) or []:
        title = str(entry.get("title", "")).strip()
        listing_uid = str(entry.get("listing_uid", "")).strip()
        if not title or not listing_uid:
            continue
        if _score_useful_fab_record(entry) <= 0:
            continue
        chosen.setdefault(listing_uid, entry)

    ranked = sorted(
        chosen.values(),
        key=lambda item: (-_score_useful_fab_record(item), str(item.get("title", "")).lower()),
    )
    return ranked[:limit]


def _choose_useful_epic_launcher_candidates(local_report: dict[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for entry in local_report.get("launcher_cache_candidates", []) or []:
        family = _normalize_lookup_token(str(entry.get("family", "")))
        display_name = str(entry.get("display_name", "")).strip()
        if not display_name:
            continue
        if any(token in family for token in _USEFUL_EPIC_FAMILIES):
            candidates.append(entry)
    candidates.sort(key=lambda item: str(item.get("display_name", "")).lower())
    return candidates[:limit]


def _discover_downloaded_unity_owned_packages(*, limit: int = 12) -> list[dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
    seen_asset_ids: set[str] = set()
    for report_path in sorted(generated_output_root().glob("unity_owned_download_wave*/unity_owned_download_wave.json")):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for entry in payload.get("items", []) or []:
            if str(entry.get("status", "")).strip() != "downloaded":
                continue
            pack_id = str(entry.get("pack_id", "")).strip()
            if not pack_id or pack_id in discovered:
                continue
            asset_id = str(entry.get("asset_id", "")).strip()
            if asset_id and asset_id in seen_asset_ids:
                continue
            discovered[pack_id] = {
                "name": str(entry.get("name", "")).strip(),
                "pack_id": pack_id,
                "asset_id": asset_id,
                "output_path": str(entry.get("output_path", "")).strip(),
                "download_report_json": str(entry.get("download_report_json", "")).strip(),
            }
            if asset_id:
                seen_asset_ids.add(asset_id)
            if len(discovered) >= limit:
                break
        if len(discovered) >= limit:
            break

    if len(discovered) < limit:
        for report_path in sorted(generated_output_root().glob("unity_owned_download*/unity_owned_download_*.json")):
            try:
                payload = json.loads(report_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            pack_id = str(payload.get("pack_id", "")).strip()
            if not pack_id:
                product_id = str(payload.get("product_id", "")).strip()
                if not product_id:
                    continue
                pack_id = f"SHARED_UNITY_OWNED_{product_id}"
            if pack_id in discovered:
                continue
            product_id = str(payload.get("product_id", "")).strip()
            if product_id and product_id in seen_asset_ids:
                continue
            output_path = str(payload.get("output_path", "")).strip()
            if not output_path:
                continue
            discovered[pack_id] = {
                "name": str(payload.get("display_name", "")).strip(),
                "pack_id": pack_id,
                "asset_id": product_id,
                "output_path": output_path,
                "download_report_json": str(report_path),
            }
            if product_id:
                seen_asset_ids.add(product_id)
            if len(discovered) >= limit:
                break
    return list(discovered.values())


def _load_generated_report_fallback(
    base_name: str,
    *,
    preferred_dirs: tuple[str, ...] = (),
) -> dict[str, Any] | None:
    candidates: list[Path] = []
    seen: set[str] = set()

    for directory_name in preferred_dirs:
        candidate = generated_output_root() / directory_name / base_name
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            candidates.append(candidate)

    generated_root = generated_output_root()
    if generated_root.exists():
        for directory in sorted(
            generated_root.iterdir(),
            key=lambda path: path.stat().st_mtime if path.exists() else 0.0,
            reverse=True,
        ):
            if not directory.is_dir():
                continue
            candidate = directory / base_name
            key = str(candidate).lower()
            if key in seen or not candidate.exists():
                continue
            seen.add(key)
            candidates.append(candidate)

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _choose_useful_unity_owned_items(unity_report: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for entry in unity_report.get("items", []) or []:
        title = str(entry.get("display_name", "")).strip()
        lowered = title.lower()
        if not title:
            continue
        if any(keyword in lowered for keyword in _USEFUL_UNITY_KEYWORDS):
            candidates.append(entry)
    candidates.sort(key=lambda item: str(item.get("display_name", "")).lower())
    return candidates[:limit]


def build_useful_harvest_wave(
    *,
    combined_report: dict[str, Any],
    unity_owned_report: dict[str, Any],
    fab_dummy_wave_report: dict[str, Any],
    unity_downloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fab_useful = _choose_useful_fab_records(dict(combined_report.get("fab_online", {})))
    epic_cached = _top_local_extract_candidates(dict(combined_report.get("epic_local", {})), limit=6)
    epic_launcher = _choose_useful_epic_launcher_candidates(dict(combined_report.get("epic_local", {})))
    unity_useful = _choose_useful_unity_owned_items(unity_owned_report)
    unity_downloaded = unity_downloads if unity_downloads is not None else _discover_downloaded_unity_owned_packages()
    fab_dummy_next = list((fab_dummy_wave_report.get("do_first") or [])[:8])

    return {
        "summary": {
            "fab_useful_now": len(fab_useful),
            "epic_cached_now": len(epic_cached),
            "unity_owned_useful": len(unity_useful),
            "unity_downloaded_ready": len(unity_downloaded),
            "epic_launcher_next": len(epic_launcher),
            "fab_unreal_next": len(fab_dummy_next),
        },
        "extract_now": {
            "fab_neutral_owned": fab_useful,
            "epic_cached": epic_cached,
            "unity_downloaded": unity_downloaded,
            "unity_owned": unity_useful,
        },
        "queue_next": {
            "epic_launcher_candidates": epic_launcher,
            "fab_unreal_dummy_project": fab_dummy_next,
        },
        "recommended_order": [
            "Use direct neutral Fab assets first for Roman weapons, character variants, animation donors, and environment shell pieces.",
            "Pull from the cached Unreal packs next, especially GASP and Parry Attack System for animation/audio and Abandoned Lighthouse for environment extraction patterns.",
            "Use the already-downloaded Unity packages next, starting with Human Melee Animations FREE.",
            "Queue the strongest launcher-cache and Unreal-only Fab families after that with dummy-project or extractor waves.",
        ],
    }


def render_useful_harvest_wave_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# Useful Harvest Wave",
        "",
        f"- Fab useful now: `{summary.get('fab_useful_now', 0)}`",
        f"- Epic cached now: `{summary.get('epic_cached_now', 0)}`",
        f"- Unity owned useful: `{summary.get('unity_owned_useful', 0)}`",
        f"- Unity downloaded ready: `{summary.get('unity_downloaded_ready', 0)}`",
        f"- Epic launcher next: `{summary.get('epic_launcher_next', 0)}`",
        f"- Fab Unreal-only next: `{summary.get('fab_unreal_next', 0)}`",
        "",
        "## Extract Now",
        "",
    ]

    for entry in report.get("extract_now", {}).get("fab_neutral_owned", []) or []:
        formats = ", ".join(str(item) for item in entry.get("format_codes", []) or []) or "-"
        lines.append(f"- Fab: {entry.get('title', '')} | route=`{entry.get('route', '')}` | formats=`{formats}`")
    for entry in report.get("extract_now", {}).get("epic_cached", []) or []:
        stats = dict(entry.get("stats", {}))
        lines.append(
            f"- Epic cache: {entry.get('title', '')} | skeletal=`{stats.get('skeletal_mesh_candidates', 0)}` anims=`{stats.get('animation_candidates', 0)}` static=`{stats.get('static_mesh_candidates', 0)}` sounds=`{stats.get('sound_candidates', 0)}`"
        )
    for entry in report.get("extract_now", {}).get("unity_downloaded", []) or []:
        lines.append(f"- Unity downloaded: {entry.get('name', '')} | `{entry.get('output_path', '')}`")
    for entry in report.get("extract_now", {}).get("unity_owned", []) or []:
        lines.append(f"- Unity owned: {entry.get('display_name', '')} | package_id=`{entry.get('package_id', '')}`")

    lines.extend(["", "## Queue Next", ""])
    for entry in report.get("queue_next", {}).get("epic_launcher_candidates", []) or []:
        lines.append(f"- Epic launcher candidate: {entry.get('display_name', '')} | class=`{entry.get('classification', '')}`")
    for entry in report.get("queue_next", {}).get("fab_unreal_dummy_project", []) or []:
        lines.append(f"- Fab Unreal-only: {entry.get('title', '')} | score=`{entry.get('score', 0)}`")

    lines.extend(["", "## Recommended Order", ""])
    for step in report.get("recommended_order", []) or []:
        lines.append(f"- {step}")
    lines.append("")
    return "\n".join(lines)


def emit_useful_harvest_wave(
    *,
    combined_report: dict[str, Any] | None = None,
    unity_owned_report: dict[str, Any] | None = None,
    fab_dummy_wave_report: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    resolved_output_dir = Path(output_dir) if output_dir is not None else generated_output_root() / "useful_harvest_wave"
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    if combined_report is not None:
        live_combined = combined_report
    else:
        try:
            live_combined = build_combined_library_map()
        except Exception:
            cached_combined = _load_generated_report_fallback(
                "combined_library_map.json",
                preferred_dirs=("combined_library_map_live",),
            )
            if cached_combined is None:
                raise
            live_combined = cached_combined

    if unity_owned_report is not None:
        live_unity = unity_owned_report
    else:
        try:
            live_unity = build_unity_owned_library_map()
        except Exception:
            cached_unity = _load_generated_report_fallback(
                "unity_owned_library_map.json",
                preferred_dirs=(
                    "unity_owned_library_map_live_v3",
                    "unity_owned_library_map_live_v2",
                    "unity_owned_library_map_live",
                ),
            )
            if cached_unity is None:
                raise
            live_unity = cached_unity

    if fab_dummy_wave_report is not None:
        live_dummy_wave = fab_dummy_wave_report
    else:
        live_dummy_wave = emit_fab_dummy_project_wave(
            fab_report=dict(live_combined.get("fab_online", {})),
            local_report=dict(live_combined.get("epic_local", {})),
            output_dir=resolved_output_dir / "fab_dummy_project_wave",
        )

    report = build_useful_harvest_wave(
        combined_report=live_combined,
        unity_owned_report=live_unity,
        fab_dummy_wave_report=live_dummy_wave,
    )
    write_json(resolved_output_dir / "useful_harvest_wave.json", report)
    write_text(resolved_output_dir / "useful_harvest_wave.md", render_useful_harvest_wave_markdown(report))
    return report


def _fab_download_roots() -> tuple[Path, ...]:
    generated_root = generated_output_root()
    candidates: list[Path] = []
    seen: set[str] = set()
    for path in sorted(generated_root.glob("useful_fab_harvest*/downloads")):
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(path)
    return tuple(candidates)


def _find_fab_download_file(listing_uid: str) -> Path | None:
    preferred_suffixes = (".fbx", ".glb", ".gltf", ".obj", ".zip")
    for root in _fab_download_roots():
        listing_dir = root / listing_uid
        if not listing_dir.exists():
            continue
        files = [item for item in listing_dir.iterdir() if item.is_file()]
        if not files:
            continue
        files.sort(key=lambda item: (preferred_suffixes.index(item.suffix.lower()) if item.suffix.lower() in preferred_suffixes else len(preferred_suffixes), item.name.lower()))
        return files[0]
    return None


def _find_fab_download_files(listing_uid: str) -> list[Path]:
    discovered: list[Path] = []
    for root in _fab_download_roots():
        listing_dir = root / listing_uid
        if not listing_dir.exists():
            continue
        discovered.extend(item for item in listing_dir.iterdir() if item.is_file())
    return sorted(discovered, key=lambda item: item.name.lower())


def _collect_fab_record_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for entry in report.get("extract_now", {}).get("fab_neutral_owned", []) or []:
        listing_uid = str(entry.get("listing_uid", "")).strip()
        if listing_uid:
            records[listing_uid] = dict(entry)
    return records


def _discover_unity_download_report_payloads() -> dict[str, dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
    for report_path in sorted(generated_output_root().glob("unity_owned_download_wave*/downloads/*/unity_owned_download_*.json")):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        product_id = str(payload.get("product_id", "")).strip()
        if product_id:
            payload["download_report_json"] = str(report_path)
            discovered[product_id] = payload
    for report_path in sorted(generated_output_root().glob("unity_owned_download*/unity_owned_download_*.json")):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        product_id = str(payload.get("product_id", "")).strip()
        if not product_id or product_id in discovered:
            continue
        payload["download_report_json"] = str(report_path)
        discovered[product_id] = payload
    return discovered


def _looks_like_valid_zip(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path, "r") as handle:
            return handle.testzip() is None
    except Exception:
        return False


def _file_size_bytes(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


def _emit_direct_donor_cleanup_job(
    *,
    pack_id: str,
    title: str,
    game_scope: str,
    source_url: str,
    source_path: Path,
    asset_kind: str,
    animated: bool,
    license_note: str,
    source_adapter: str,
    author_or_vendor: str = "",
    output_dir: Path,
) -> dict[str, Any]:
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
    cleanup_plan = build_cleanup_plan(
        pack_id=pack_id,
        asset_kind=asset_kind,
        source_lane=ProviderLane.DIRECT_URL.value,
        animated=animated,
    )
    provenance = build_provenance_template(
        pack_id=pack_id,
        game_scope=game_scope,
        lane=ProviderLane.DIRECT_URL,
        source_adapter=source_adapter,
        payload_target_path=str(payload_target),
        notes=(
            "Prepared from a directly harvested donor file.",
            "Run Blender cleanup before copying accepted exports into the payload target.",
        ),
    )
    provenance_values = dict(provenance.get("values", {}))
    provenance_values.update(
        {
            "source_url": source_url,
            "license": license_note,
            "license_snapshot": license_note,
            "author_or_vendor": author_or_vendor,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
            "downloaded_filename": source_path.name,
            "download_url": source_url,
            "download_notes": "Harvested into useful_fab_harvest_live; direct donor file staged for Blender cleanup.",
            "entitlement_note": "Use only under the owned/licensed Fab entitlement for this account.",
        }
    )
    provenance["values"] = provenance_values

    manifest = {
        "pack_id": pack_id,
        "title": title,
        "game_scope": game_scope,
        "source_url": source_url,
        "source_path": str(source_path),
        "source_filename": source_path.name,
        "source_size_bytes": _file_size_bytes(source_path),
        "asset_kind": asset_kind,
        "animated": animated,
    }
    blender_handoff = {
        "pack_id": pack_id,
        "title": title,
        "source_path": str(source_path),
        "cleanup_plan_path": str(output_dir / "cleanup_plan.json"),
        "payload_target_path": str(payload_target),
        "preferred_cleanup_exports": list(cleanup_plan.export_decision.export_targets),
        "next_step": "Import the direct donor file into Blender, normalize it, then copy accepted exports into the payload target.",
    }
    checklist_lines = [
        f"# {title}",
        "",
        f"- Pack: `{pack_id}`",
        f"- Source file: `{source_path}`",
        f"- Asset kind: `{asset_kind}`",
        f"- Animated: `{animated}`",
        f"- Payload target: `{payload_target}`",
        "",
        "## Cleanup",
        "",
        "- Import the harvested donor file into Blender.",
        "- Normalize scale, pivot, material slots, and ASCII-safe names.",
        "- Export only the reviewed open-format outputs listed in the cleanup plan.",
    ]

    write_json(output_dir / "cleanup_plan.json", cleanup_plan.to_dict())
    write_json(output_dir / "source_manifest.json", manifest)
    write_json(output_dir / "provenance_template.json", provenance)
    write_json(output_dir / "blender_handoff.json", blender_handoff)
    write_text(output_dir / "payload_target.txt", str(payload_target) + "\n")
    write_text(output_dir / "review_checklist.md", "\n".join(checklist_lines) + "\n")

    return {
        "pack_id": pack_id,
        "title": title,
        "asset_kind": asset_kind,
        "animated": animated,
        "source_path": str(source_path),
        "payload_target_path": str(payload_target),
        "cleanup_plan_path": str(output_dir / "cleanup_plan.json"),
        "provenance_template_path": str(output_dir / "provenance_template.json"),
        "output_dir": str(output_dir),
    }


def _render_useful_donor_export_wave_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# Useful Donor Export Wave",
        "",
        f"- Direct cleanup jobs: `{summary.get('direct_cleanup_jobs', 0)}`",
        f"- Unity export jobs: `{summary.get('unity_export_jobs', 0)}`",
        f"- Blocked sources: `{summary.get('blocked_sources', 0)}`",
        f"- Total ready jobs: `{summary.get('total_ready_jobs', 0)}`",
        "",
        "## Direct Cleanup Jobs",
        "",
    ]
    for entry in report.get("direct_cleanup_jobs", []) or []:
        lines.append(
            f"- `{entry.get('pack_id', '')}` | {entry.get('title', '')} | source=`{entry.get('source_path', '')}` | cleanup=`{entry.get('cleanup_plan_path', '')}`"
        )
    lines.extend(["", "## Unity Export Jobs", ""])
    for entry in report.get("unity_export_jobs", []) or []:
        lines.append(
            f"- `{entry.get('pack_id', '')}` | {entry.get('title', '')} | unitypackage=`{entry.get('unitypackage_path', '')}` | runner=`{entry.get('runner_job_path', '')}`"
        )
    lines.extend(["", "## Blocked Sources", ""])
    for entry in report.get("blocked_sources", []) or []:
        lines.append(
            f"- `{entry.get('pack_id', '')}` | {entry.get('title', '')} | reason=`{entry.get('reason', '')}`"
        )
        for path in entry.get("source_paths", []) or []:
            lines.append(f"  source=`{path}`")
    lines.extend(["", "## Recommended Order", ""])
    for step in report.get("recommended_order", []) or []:
        lines.append(f"- {step}")
    lines.append("")
    return "\n".join(lines)


def emit_useful_donor_export_wave(
    *,
    useful_harvest_report: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    game_scope: str = _USEFUL_DONOR_GAME_SCOPE,
    project_path: str | Path = _USEFUL_DONOR_DEFAULT_PROJECT_PATH,
) -> dict[str, Any]:
    resolved_output_dir = Path(output_dir) if output_dir is not None else generated_output_root() / "useful_donor_export_wave"
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    if useful_harvest_report is not None:
        harvest_report = useful_harvest_report
    else:
        harvest_report = _load_generated_report_fallback(
            "useful_harvest_wave.json",
            preferred_dirs=("useful_harvest_wave_live",),
        )
        if harvest_report is None:
            harvest_report = emit_useful_harvest_wave(output_dir=generated_output_root() / "useful_harvest_wave")

    fab_records = _collect_fab_record_map(harvest_report)
    unity_download_reports = _discover_unity_download_report_payloads()
    direct_jobs: list[dict[str, Any]] = []
    unity_jobs: list[dict[str, Any]] = []
    blocked_sources: list[dict[str, Any]] = []

    for spec in _USEFUL_FAB_DONOR_SPECS:
        listing_uid = str(spec["listing_uid"])
        record = fab_records.get(listing_uid, {})
        source_path = _find_fab_download_file(listing_uid)
        if source_path is None:
            continue
        job = _emit_direct_donor_cleanup_job(
            pack_id=str(spec["pack_id"]),
            title=str(record.get("title", source_path.stem)),
            game_scope=game_scope,
            source_url=str(record.get("listing_url", f"https://www.fab.com/listings/{listing_uid}")),
            source_path=source_path,
            asset_kind=str(spec["asset_kind"]),
            animated=bool(spec["animated"]),
            license_note=str(spec["license_note"]),
            source_adapter="fab_direct_download",
            author_or_vendor=str(record.get("publisher_name", "")),
            output_dir=resolved_output_dir / "direct_cleanup_jobs" / str(spec["pack_id"]),
        )
        direct_jobs.append(job)

    for spec in _USEFUL_FAB_BLOCKED_SPECS:
        listing_uid = str(spec["listing_uid"])
        record = fab_records.get(listing_uid, {})
        source_paths = _find_fab_download_files(listing_uid)
        if not source_paths:
            continue
        invalid_paths = [str(path) for path in source_paths if path.suffix.lower() == ".zip" and not _looks_like_valid_zip(path)]
        if not invalid_paths:
            continue
        blocked_sources.append(
            {
                "pack_id": str(spec["pack_id"]),
                "title": str(record.get("title", spec["pack_id"])),
                "reason": str(spec["reason"]),
                "source_paths": invalid_paths,
                "listing_url": str(record.get("listing_url", f"https://www.fab.com/listings/{listing_uid}")),
            }
        )

    for spec in _USEFUL_UNITY_DONOR_SPECS:
        product_id = str(spec["product_id"])
        payload = unity_download_reports.get(product_id)
        if not payload:
            continue
        unitypackage_path = Path(str(payload.get("output_path", "")).strip())
        if not unitypackage_path.exists():
            continue
        slug = str(payload.get("slug", "")).strip()
        source_url = str(spec["source_url"]).strip()
        if not source_url and slug:
            source_url = f"https://assetstore.unity.com/packages/{slug}"
        artifacts = emit_unity_export_runner(
            pack_id=str(spec["pack_id"]),
            game_scope=game_scope,
            source_url=source_url,
            license_note=str(spec["license_note"]),
            project_path=project_path,
            package_root="Assets",
            unitypackage_paths=(str(unitypackage_path),),
            source_package_name=str(payload.get("display_name", "")),
            asset_kind=str(spec["asset_kind"]),
            output_dir=resolved_output_dir / "unity_export_runners" / str(spec["pack_id"]),
            notes=(
                f"Unity Asset Store product_id={product_id}",
                "Use the throwaway Unity project only for import/export, not for gameplay code.",
            ),
        )
        unity_jobs.append(
            {
                "pack_id": str(spec["pack_id"]),
                "title": str(payload.get("display_name", spec["pack_id"])),
                "product_id": product_id,
                "unitypackage_path": str(unitypackage_path),
                "runner_job_path": str(artifacts.runner_job_path),
                "powershell_path": str(artifacts.powershell_path),
                "blender_handoff_path": str(artifacts.blender_handoff_path),
                "output_dir": str(artifacts.output_dir),
                "payload_target_path": str(artifacts.payload_target_path),
            }
        )

    report = {
        "summary": {
            "direct_cleanup_jobs": len(direct_jobs),
            "unity_export_jobs": len(unity_jobs),
            "blocked_sources": len(blocked_sources),
            "total_ready_jobs": len(direct_jobs) + len(unity_jobs),
        },
        "direct_cleanup_jobs": direct_jobs,
        "unity_export_jobs": unity_jobs,
        "blocked_sources": blocked_sources,
        "recommended_order": [
            "Run Blender cleanup on the direct Fab donor files first so the character and weapon donors become reviewed neutral exports quickly.",
            "Import the downloaded Unity packages into the throwaway Unity project next, then run the generated export runners.",
            "Re-download the blocked Fab retargeted animation pack before treating it as a usable source.",
        ],
    }
    write_json(resolved_output_dir / "useful_donor_export_wave.json", report)
    write_text(resolved_output_dir / "useful_donor_export_wave.md", _render_useful_donor_export_wave_markdown(report))
    return report


def _top_local_extract_candidates(report: dict[str, Any], *, limit: int = 8) -> list[dict[str, Any]]:
    entries = list(report.get("confirmed_cached_entries", []))

    def score(entry: dict[str, Any]) -> int:
        stats = dict(entry.get("stats", {}))
        return (
            int(stats.get("skeletal_mesh_candidates", 0)) * 10
            + int(stats.get("animation_candidates", 0)) * 2
            + int(stats.get("static_mesh_candidates", 0))
            + int(stats.get("texture_candidates", 0))
            + int(stats.get("sound_candidates", 0))
        )

    ranked = sorted(entries, key=score, reverse=True)
    return ranked[:limit]


def build_combined_library_map(
    *,
    db_path: str | Path | None = None,
    launcher_data_dir: str | Path | None = None,
    quixel_roots: tuple[str | Path, ...] = (),
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    resolved_data_dir = Path(launcher_data_dir) if launcher_data_dir is not None else default_epic_launcher_saved_data_dir()
    data_paths = tuple(sorted(resolved_data_dir.glob("OC_*.dat"))) if resolved_data_dir.exists() else ()
    local_epic_report = build_local_epic_library_report(db_path or default_local_fab_library_db_path(), data_paths)
    epic_online_report = build_online_epic_library_map(timeout_seconds=timeout_seconds)
    fab_online_report = build_online_fab_library_map(timeout_seconds=timeout_seconds)
    quixel_report = build_local_quixel_library_map(extra_roots=quixel_roots, timeout_seconds=min(timeout_seconds, 5.0))
    tools = detect_optional_library_tools()

    local_confirmed_entries = list(local_epic_report.get("confirmed_cached_entries", []))
    launcher_candidates = list(local_epic_report.get("launcher_cache_candidates", []))
    local_extract_targets = _top_local_extract_candidates(local_epic_report)
    fab_summary = dict(fab_online_report.get("summary", {}))
    epic_summary = dict(epic_online_report.get("summary", {}))
    quixel_summary = dict(quixel_report.get("summary", {}))

    return {
        "summary": {
            "fab_owned_total": fab_summary.get("total_records", 0),
            "fab_neutral_or_mixed": fab_summary.get("neutral_or_mixed_records", 0),
            "fab_unreal_only": fab_summary.get("unreal_only_records", 0),
            "fab_roman_candidates": fab_summary.get("roman_candidate_count", 0),
            "epic_online_total": epic_summary.get("total_records", 0),
            "epic_marketplace_assets": epic_summary.get("marketplace_asset_records", 0),
            "epic_engines": epic_summary.get("engine_records", 0),
            "epic_local_cached": len(local_confirmed_entries),
            "epic_launcher_candidates": len(launcher_candidates),
            "quixel_detected_roots": quixel_summary.get("detected_root_count", 0),
            "quixel_total_assets": quixel_summary.get("total_assets", 0),
            "detected_tool_count": len(tools),
        },
        "source_of_truth": {
            "fab_owned_assets": "fab_online_api",
            "epic_launcher_entitlements": "epic_online_api",
            "downloaded_unreal_payloads": "local_fablibrary_db_and_vaultcache",
            "megascans_assets": "quixel_bridge_api_or_local_megascans_roots",
            "uevaultmanager": "fallback_only",
        },
        "tools": tools,
        "high_value": {
            "fab_roman_candidates": list((fab_online_report.get("roman_candidates") or [])[:12]),
            "local_extract_candidates": local_extract_targets,
        },
        "fab_online": fab_online_report,
        "epic_online": epic_online_report,
        "epic_local": local_epic_report,
        "quixel_local": quixel_report,
    }


def render_combined_library_map_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# AssetBoy Combined Library Map",
        "",
        f"- Fab owned listings: `{summary.get('fab_owned_total', 0)}`",
        f"- Fab neutral or mixed-format listings: `{summary.get('fab_neutral_or_mixed', 0)}`",
        f"- Fab Unreal-only listings: `{summary.get('fab_unreal_only', 0)}`",
        f"- Fab Roman candidates: `{summary.get('fab_roman_candidates', 0)}`",
        f"- Epic online records: `{summary.get('epic_online_total', 0)}`",
        f"- Epic marketplace assets: `{summary.get('epic_marketplace_assets', 0)}`",
        f"- Local cached Unreal packs: `{summary.get('epic_local_cached', 0)}`",
        f"- Launcher cache candidate families: `{summary.get('epic_launcher_candidates', 0)}`",
        f"- Quixel detected roots: `{summary.get('quixel_detected_roots', 0)}`",
        f"- Quixel total assets: `{summary.get('quixel_total_assets', 0)}`",
        "",
        "## Source Of Truth",
        "",
    ]
    for label, source in dict(report.get("source_of_truth", {})).items():
        lines.append(f"- `{label}` -> `{source}`")
    lines.append("")

    tools = dict(report.get("tools", {}))
    if tools:
        lines.extend(["## Detected Tools", ""])
        for label, path in sorted(tools.items()):
            lines.append(f"- `{label}`: `{path}`")
        lines.append("")

    high_value = dict(report.get("high_value", {}))
    fab_candidates = list(high_value.get("fab_roman_candidates", []))
    if fab_candidates:
        lines.extend(["## Fab Roman Candidates", ""])
        for item in fab_candidates[:12]:
            formats = ", ".join(item.get("format_codes", [])) or "none"
            lines.append(f"- {item.get('title', '')} | route=`{item.get('route', '')}` | formats=`{formats}`")
        lines.append("")

    local_candidates = list(high_value.get("local_extract_candidates", []))
    if local_candidates:
        lines.extend(["## Local Extraction Candidates", ""])
        for item in local_candidates:
            stats = dict(item.get("stats", {}))
            lines.append(
                f"- {item.get('title', '')} | static=`{stats.get('static_mesh_candidates', 0)}` "
                f"skeletal=`{stats.get('skeletal_mesh_candidates', 0)}` anims=`{stats.get('animation_candidates', 0)}` "
                f"textures=`{stats.get('texture_candidates', 0)}` sounds=`{stats.get('sound_candidates', 0)}`"
            )
        lines.append("")

    return "\n".join(lines).strip() + "\n"
