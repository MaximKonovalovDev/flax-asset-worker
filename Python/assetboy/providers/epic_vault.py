from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import requests
from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, manual_drop_dir, publish_payload_dir
from assetboy.provenance.templates import build_provenance_template
from assetboy.providers.lanes import ProviderLane
from assetboy.providers.extractor_bridge import ExtractorArtifacts, ExtractorTool, emit_extractor_job


class EpicVaultMethod(str, Enum):
    UEVAULTMANAGER = "uevaultmanager"
    DUMMY_PROJECT = "dummy_project"


SAFE_UEVAULT_CONFIG_TEXT = "\n".join(
    [
        "[UEVaultManager]",
        "max_memory = 2048",
        "max_workers = 8",
        "locale = en-US",
        "preferred_cdn = epicgames-download1.akamaized.net",
        "disable_https = false",
        "disable_update_check = False",
        "disable_update_notice = False",
        "start_in_edit_mode = False",
        "create_output_backup = False",
        "create_log_backup = False",
        "verbose_mode = False",
        "engine_version_for_obsolete_assets = 4.26",
        "",
    ]
)


@dataclass(frozen=True)
class EpicVaultJob:
    method: EpicVaultMethod
    pack_id: str
    game_scope: str
    source_url: str
    vault_item: str
    engine_association: str
    source_adapter: str
    download_target: Path
    staging_target: Path
    project_dir: Path
    project_name: str
    uproject_path: Path
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method.value,
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "source_url": self.source_url,
            "vault_item": self.vault_item,
            "engine_association": self.engine_association,
            "source_adapter": self.source_adapter,
            "download_target": str(self.download_target),
            "staging_target": str(self.staging_target),
            "project_dir": str(self.project_dir),
            "project_name": self.project_name,
            "uproject_path": str(self.uproject_path),
            "notes": list(self.notes),
            "preferred_extractors": ["fmodel", "umodel"],
        }


@dataclass(frozen=True)
class EpicVaultArtifacts:
    output_dir: Path
    job_spec_path: Path
    review_checklist_path: Path
    provenance_template_path: Path
    payload_target_path_file: Path
    script_path: Path
    command_template_path: Path
    uproject_path: Path
    download_target_path: Path
    staging_target_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "job_spec_path": str(self.job_spec_path),
            "review_checklist_path": str(self.review_checklist_path),
            "provenance_template_path": str(self.provenance_template_path),
            "payload_target_path_file": str(self.payload_target_path_file),
            "script_path": str(self.script_path),
            "command_template_path": str(self.command_template_path),
            "uproject_path": str(self.uproject_path),
            "download_target_path": str(self.download_target_path),
            "staging_target_path": str(self.staging_target_path),
        }


def _append_unreal_editor_candidate(candidates: list[Path], seen: set[str], candidate: Path) -> None:
    resolved = candidate.resolve()
    if not resolved.exists():
        return
    key = str(resolved).lower()
    if key in seen:
        return
    seen.add(key)
    candidates.append(resolved)


def _append_unreal_engine_root(candidates: list[Path], seen: set[str], root: Path) -> None:
    if root.suffix.lower() == ".exe":
        _append_unreal_editor_candidate(candidates, seen, root)
        return
    binary_root = root / "Engine" / "Binaries" / "Win64"
    _append_unreal_editor_candidate(candidates, seen, binary_root / "UnrealEditor.exe")
    _append_unreal_editor_candidate(candidates, seen, binary_root / "UE4Editor.exe")


def detect_unreal_editor_installations() -> tuple[Path, ...]:
    candidates: list[Path] = []
    seen: set[str] = set()

    program_files = os.environ.get("ProgramFiles")
    if program_files:
        epic_root = Path(program_files) / "Epic Games"
        if epic_root.exists():
            for engine_root in epic_root.glob("UE_*"):
                _append_unreal_engine_root(candidates, seen, engine_root)

    if os.name == "nt":
        try:
            import winreg  # type: ignore
        except ImportError:
            winreg = None  # type: ignore[assignment]
        if winreg is not None:
            registry_locations = (
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EpicGames\Unreal Engine", True),
                (winreg.HKEY_CURRENT_USER, r"Software\Epic Games\Unreal Engine\Builds", False),
            )
            for hive, key_path, enumerate_subkeys in registry_locations:
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        if enumerate_subkeys:
                            index = 0
                            while True:
                                try:
                                    subkey_name = winreg.EnumKey(key, index)
                                except OSError:
                                    break
                                index += 1
                                try:
                                    with winreg.OpenKey(key, subkey_name) as subkey:
                                        install_dir, _ = winreg.QueryValueEx(subkey, "InstalledDirectory")
                                except OSError:
                                    continue
                                _append_unreal_engine_root(candidates, seen, Path(str(install_dir)))
                        else:
                            index = 0
                            while True:
                                try:
                                    _, install_dir, _ = winreg.EnumValue(key, index)
                                except OSError:
                                    break
                                index += 1
                                _append_unreal_engine_root(candidates, seen, Path(str(install_dir)))
                except OSError:
                    continue

    return tuple(candidates)


def has_unreal_editor_installation() -> bool:
    return bool(detect_unreal_editor_installations())


def default_uevaultmanager_safe_config_path() -> Path:
    return generated_output_root() / "uevaultmanager.safe.ini"


def write_uevaultmanager_safe_config(path: str | Path | None = None) -> Path:
    resolved = Path(path) if path is not None else default_uevaultmanager_safe_config_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(SAFE_UEVAULT_CONFIG_TEXT, encoding="utf-8", newline="\n")
    return resolved


def resolve_uevaultmanager_executable() -> str:
    if candidate := shutil.which("UEVaultManager"):
        return candidate

    python312_scripts = Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python312" / "Scripts" / "UEVaultManager.exe"
    if python312_scripts.exists():
        return str(python312_scripts)

    raise FileNotFoundError("UEVaultManager executable not found on PATH or in the standard Python Scripts location.")


def run_uevaultmanager_command(
    command_args: list[str],
    *,
    config_path: str | Path | None = None,
    timeout_seconds: float = 120.0,
    disable_nodriver: bool = True,
) -> subprocess.CompletedProcess[str]:
    executable = resolve_uevaultmanager_executable()
    safe_config_path = write_uevaultmanager_safe_config(config_path)
    env = os.environ.copy()
    if disable_nodriver:
        env["UEVM_DISABLE_NODRIVER"] = "1"

    full_command = [executable, "-c", str(safe_config_path), *command_args]
    return subprocess.run(
        full_command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        env=env,
        check=False,
    )


def parse_uevault_owned_asset_count(payload_path: str | Path) -> tuple[int, int]:
    data = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        items = list(data.values())
    elif isinstance(data, list):
        items = list(data)
    else:
        items = []

    owned_count = 0
    for item in items:
        if isinstance(item, dict) and bool(item.get("Owned")):
            owned_count += 1
    return owned_count, len(items)


def default_local_fab_library_db_path() -> Path:
    return Path(r"C:\ProgramData\Epic\EpicGamesLauncher\VaultCache\FabLibrary\listings_v1.db")


def default_epic_launcher_saved_data_dir() -> Path:
    return Path.home() / "AppData" / "Local" / "EpicGamesLauncher" / "Saved" / "Data"


def default_epic_launcher_webcache_dir() -> Path:
    return Path.home() / "AppData" / "Local" / "EpicGamesLauncher" / "Saved" / "webcache_4430"


def default_uevault_user_data_path() -> Path:
    return Path.home() / ".config" / "UEVaultManager" / "json" / "user_data.json"


def discover_epic_launcher_cache_data_paths() -> tuple[Path, ...]:
    data_dir = default_epic_launcher_saved_data_dir()
    if not data_dir.exists():
        return ()
    return tuple(sorted(data_dir.glob("OC_*.dat")))


def _extract_printable_ascii_strings(data: bytes, *, min_length: int = 8, max_length: int = 160) -> list[str]:
    pattern = re.compile(rb"[ -~]{%d,%d}" % (min_length, max_length))
    strings = [match.group(0).decode("utf-8", "ignore").strip() for match in pattern.finditer(data)]
    return [item for item in strings if item]


def _looks_like_hex_id(value: str) -> bool:
    compact = value.replace("-", "").strip().lower()
    return len(compact) >= 16 and all(character in "0123456789abcdef" for character in compact)


def _split_cache_family_and_version(token: str) -> tuple[str, str | None]:
    match = re.fullmatch(r"([A-Za-z][A-Za-z0-9]+)_(\d+\.\d+)", token)
    if match:
        return match.group(1), match.group(2)
    return token, None


def _classify_launcher_cache_family(family: str) -> str:
    family_lower = family.lower()
    if any(item in family_lower for item in ("anim", "lyra", "parry", "combat", "inventory")):
        return "character_animation"
    if any(item in family_lower for item in ("city", "cave", "dungeon", "lighthouse", "temple", "dream", "kite")):
        return "environment"
    if "contentexamples" in family_lower or "sample" in family_lower:
        return "sample_project"
    return "mixed"


def _launcher_cache_notes(family: str, classification: str) -> str:
    if classification == "character_animation":
        return f"Likely useful for skeletal meshes, animations, and combat template content from {family}."
    if classification == "environment":
        return f"Likely useful for static meshes, materials, and environment set dressing from {family}."
    if classification == "sample_project":
        return f"Sample-project family detected for {family}; likely broad content, but needs manual extraction triage."
    return f"Launcher cache candidate detected for {family}; needs manual verification before claiming ownership."


def build_local_epic_launcher_cache_candidates(data_paths: tuple[str | Path, ...] | None = None) -> list[dict[str, object]]:
    resolved_paths = tuple(Path(item) for item in data_paths) if data_paths is not None else discover_epic_launcher_cache_data_paths()
    if not resolved_paths:
        return []

    candidate_hits: dict[str, dict[str, object]] = {}
    for data_path in resolved_paths:
        if not data_path.exists():
            continue
        for token in _extract_printable_ascii_strings(data_path.read_bytes()):
            if _looks_like_hex_id(token):
                continue
            token_lower = token.lower()
            if token_lower.startswith(("http", "fabplugin_", "quixelbridge_")):
                continue
            if sum(character.isalpha() for character in token) < 4:
                continue
            if not any(
                keyword in token_lower
                for keyword in (
                    "sample",
                    "pack",
                    "kit",
                    "inventory",
                    "roman",
                    "combat",
                    "animation",
                    "anim",
                    "lighthouse",
                    "city",
                    "cave",
                    "village",
                    "forest",
                    "temple",
                    "weapon",
                    "castle",
                    "dungeon",
                    "parry",
                    "supergrid",
                    "lyra",
                    "dream",
                    "psychokinesis",
                    "contentexamples",
                )
            ):
                continue

            family, version = _split_cache_family_and_version(token)
            if re.search(r"[0-9a-f]{8,}v\d+$", family.lower()):
                continue
            family_lower = family.lower()
            entry = candidate_hits.setdefault(
                family_lower,
                {
                    "family": family,
                    "raw_hits": set(),
                    "versions": set(),
                    "source_files": set(),
                },
            )
            entry["raw_hits"].add(token)
            if version:
                entry["versions"].add(version)
            entry["source_files"].add(str(data_path))

    candidates: list[dict[str, object]] = []
    for entry in sorted(candidate_hits.values(), key=lambda item: str(item["family"]).lower()):
        family = str(entry["family"])
        classification = _classify_launcher_cache_family(family)
        versions = sorted(str(item) for item in entry["versions"])
        raw_hits = sorted(str(item) for item in entry["raw_hits"])
        source_files = sorted(str(item) for item in entry["source_files"])
        candidates.append(
            {
                "family": family,
                "display_name": family if not versions else f"{family} ({', '.join(versions)})",
                "versions": versions,
                "raw_hits": raw_hits,
                "source_files": source_files,
                "classification": classification,
                "confidence": "launcher_cache_candidate",
                "notes": _launcher_cache_notes(family, classification),
            }
        )
    return candidates


def render_local_epic_launcher_cache_markdown(entries: list[dict[str, object]]) -> str:
    lines = [
        "# Local Epic Launcher Cache Candidates",
        "",
        f"- Candidate families: `{len(entries)}`",
        "",
    ]
    for entry in entries:
        display_name = str(entry.get("display_name") or entry.get("family") or "Untitled launcher candidate")
        family = str(entry.get("family") or display_name)
        lines.extend(
            [
                f"## {display_name}",
                "",
                f"- Family: `{family}`",
                f"- Classification: `{entry.get('classification', 'mixed')}`",
                f"- Confidence: `{entry.get('confidence', 'launcher_cache_candidate')}`",
                f"- Notes: {entry.get('notes', 'Needs manual review.')}",
            ]
        )
        versions = entry.get("versions") or []
        if versions:
            lines.append(f"- Versions: `{', '.join(str(item) for item in versions)}`")
        raw_hits = entry.get("raw_hits") or []
        if raw_hits:
            lines.append(f"- Raw hits: `{', '.join(str(item) for item in raw_hits[:8])}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def detect_local_extractor_tools() -> dict[str, str]:
    candidates = {
        "fmodel": (
            "FModel.exe",
            r"C:\SHARE\Tools\FModel\FModel.exe",
        ),
        "umodel": (
            "umodel.exe",
            "UEViewer.exe",
            r"C:\SHARE\Tools\UModel\umodel.exe",
            r"C:\SHARE\Tools\UEViewer\umodel.exe",
            r"C:\SHARE\Tools\UEViewer\UEViewer.exe",
        ),
    }
    detected: dict[str, str] = {}
    for key, locations in candidates.items():
        for location in locations:
            candidate_path = Path(location)
            if candidate_path.is_absolute():
                if candidate_path.exists():
                    detected[key] = str(candidate_path)
                    break
                continue
            if resolved := shutil.which(location):
                detected[key] = resolved
                break
    return detected


def build_local_epic_extraction_readiness() -> dict[str, object]:
    editors = [str(path) for path in detect_unreal_editor_installations()]
    extractors = detect_local_extractor_tools()
    return {
        "unreal_editor_paths": editors,
        "extractor_tools": extractors,
        "can_extract_now": bool(editors or extractors),
        "recommended_path": (
            "Use FModel/Umodel if installed; otherwise use a compatible Unreal editor export path."
            if (editors or extractors)
            else "Install FModel/Umodel or point AssetBoy at a compatible Unreal editor before attempting bulk extraction."
        ),
    }


def load_uevault_user_data(path: str | Path | None = None) -> dict[str, Any]:
    resolved = Path(path) if path is not None else default_uevault_user_data_path()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _epic_launcher_headers(access_token: str) -> dict[str, str]:
    return {
        "User-Agent": "UELauncher/11.0.1-14907503+++Portal+Release-Live Windows/10.0.19041.1.256.64bit",
        "Authorization": f"bearer {access_token}",
    }


def fetch_online_epic_library_records(
    user_data: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 30.0,
) -> list[dict[str, Any]]:
    session_data = user_data or load_uevault_user_data()
    access_token = str(session_data.get("access_token", "")).strip()
    if not access_token:
        return []

    headers = _epic_launcher_headers(access_token)
    url = "https://library-service.live.use1a.on.epicgames.com/library/api/public/items"
    records: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(100):
        params = {"includeMetadata": "true"}
        if cursor:
            params["cursor"] = cursor
        response = requests.get(url, params=params, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        page_records = list(payload.get("records", []))
        records.extend(page_records)
        cursor = payload.get("responseMetadata", {}).get("nextCursor") or payload.get("nextCursor")
        if not cursor or not page_records:
            break
    return records


def fetch_catalog_item_info(
    *,
    access_token: str,
    namespace: str,
    catalog_item_id: str,
    country_code: str = "IL",
    language_code: str = "en",
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    headers = _epic_launcher_headers(access_token)
    url = f"https://catalog-public-service-prod06.ol.epicgames.com/catalog/api/shared/namespace/{namespace}/bulk/items"
    response = requests.get(
        url,
        params={
            "id": catalog_item_id,
            "includeDLCDetails": "true",
            "includeMainGameDetails": "true",
            "country": country_code,
            "locale": language_code,
        },
        headers=headers,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    return dict(payload.get(catalog_item_id, {}) or {})


def _online_library_entry_kind(entry: dict[str, Any]) -> str:
    sandbox = str(entry.get("sandbox_name", "")).strip()
    category_paths = [str(item.get("path", "")).strip() for item in entry.get("categories", []) if isinstance(item, dict)]
    title = str(entry.get("title", "")).strip().lower()
    if sandbox == "UE Marketplace":
        if any(path.startswith("engines") for path in category_paths):
            return "engine"
        if "sample" in title or "examples" in title:
            return "marketplace_sample"
        return "marketplace_asset"
    return "game_or_app"


def build_online_epic_library_map(
    user_data: dict[str, Any] | None = None,
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    session_data = user_data or load_uevault_user_data()
    access_token = str(session_data.get("access_token", "")).strip()
    display_name = str(session_data.get("displayName", "")).strip()
    if not access_token:
        return {
            "account_display_name": display_name,
            "records": [],
            "summary": {
                "total_records": 0,
                "ue_marketplace_records": 0,
                "engine_records": 0,
                "marketplace_asset_records": 0,
                "marketplace_sample_records": 0,
                "game_or_app_records": 0,
            },
        }

    raw_records = fetch_online_epic_library_records(session_data, timeout_seconds=timeout_seconds)
    mapped_records: list[dict[str, Any]] = []
    for record in raw_records:
        namespace = str(record.get("namespace", "")).strip()
        catalog_item_id = str(record.get("catalogItemId", "")).strip()
        catalog_info: dict[str, Any] = {}
        if namespace and catalog_item_id:
            try:
                catalog_info = fetch_catalog_item_info(
                    access_token=access_token,
                    namespace=namespace,
                    catalog_item_id=catalog_item_id,
                    country_code="IL",
                    language_code="en",
                    timeout_seconds=timeout_seconds,
                )
            except Exception:
                catalog_info = {}
        categories = list(catalog_info.get("categories", []) or [])
        developer = str(catalog_info.get("developer", "")).strip()
        seller = catalog_info.get("seller", {}) if isinstance(catalog_info.get("seller", {}), dict) else {}
        mapped = {
            "title": str(catalog_info.get("title", "")).strip() or str(record.get("appName", "")).strip(),
            "namespace": namespace,
            "catalog_item_id": catalog_item_id,
            "app_name": str(record.get("appName", "")).strip(),
            "sandbox_name": str(record.get("sandboxName", "")).strip(),
            "record_type": str(record.get("recordType", "")).strip(),
            "acquisition_date": str(record.get("acquisitionDate", "")).strip(),
            "developer": developer,
            "seller_name": str(seller.get("name", "")).strip(),
            "categories": categories,
            "custom_attribute_keys": sorted(list((catalog_info.get("customAttributes") or {}).keys()))[:24],
        }
        mapped["kind"] = _online_library_entry_kind(mapped)
        mapped_records.append(mapped)

    summary = {
        "total_records": len(mapped_records),
        "ue_marketplace_records": sum(1 for item in mapped_records if item["sandbox_name"] == "UE Marketplace"),
        "engine_records": sum(1 for item in mapped_records if item["kind"] == "engine"),
        "marketplace_asset_records": sum(1 for item in mapped_records if item["kind"] == "marketplace_asset"),
        "marketplace_sample_records": sum(1 for item in mapped_records if item["kind"] == "marketplace_sample"),
        "game_or_app_records": sum(1 for item in mapped_records if item["kind"] == "game_or_app"),
    }
    return {
        "account_display_name": display_name,
        "records": mapped_records,
        "summary": summary,
    }


def render_online_epic_library_map_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    records = list(report.get("records", []))
    lines = [
        "# Epic/Fab Library Map",
        "",
        f"- Account: `{report.get('account_display_name', '')}`",
        f"- Total records: `{summary.get('total_records', 0)}`",
        f"- UE Marketplace records: `{summary.get('ue_marketplace_records', 0)}`",
        f"- Engine records: `{summary.get('engine_records', 0)}`",
        f"- Marketplace asset records: `{summary.get('marketplace_asset_records', 0)}`",
        f"- Marketplace sample records: `{summary.get('marketplace_sample_records', 0)}`",
        f"- Game/app records: `{summary.get('game_or_app_records', 0)}`",
        "",
    ]
    for section_name, matcher in (
        ("Marketplace Assets", lambda item: item.get("kind") == "marketplace_asset"),
        ("Marketplace Samples", lambda item: item.get("kind") == "marketplace_sample"),
        ("Engines", lambda item: item.get("kind") == "engine"),
        ("Games And Apps", lambda item: item.get("kind") == "game_or_app"),
    ):
        section_records = [item for item in records if matcher(item)]
        if not section_records:
            continue
        lines.extend([f"## {section_name}", ""])
        for entry in sorted(section_records, key=lambda item: str(item.get("title", "")).lower()):
            category_paths = [str(item.get("path", "")).strip() for item in entry.get("categories", []) if isinstance(item, dict)]
            lines.append(f"- `{entry.get('title', '')}`")
            lines.append(f"  sandbox=`{entry.get('sandbox_name', '')}` app=`{entry.get('app_name', '')}`")
            if entry.get("developer") or entry.get("seller_name"):
                lines.append(f"  developer=`{entry.get('developer', '')}` seller=`{entry.get('seller_name', '')}`")
            if category_paths:
                lines.append(f"  categories=`{', '.join(category_paths[:6])}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_local_epic_library_report(
    db_path: str | Path | None = None,
    data_paths: tuple[str | Path, ...] | None = None,
) -> dict[str, object]:
    confirmed_entries = build_local_epic_vault_inventory(db_path)
    launcher_candidates = build_local_epic_launcher_cache_candidates(data_paths)
    readiness = build_local_epic_extraction_readiness()
    return {
        "confirmed_cached_entries": confirmed_entries,
        "launcher_cache_candidates": launcher_candidates,
        "extraction_readiness": readiness,
    }


def render_local_epic_library_report_markdown(report: dict[str, object]) -> str:
    confirmed_entries = list(report.get("confirmed_cached_entries", []))
    launcher_candidates = list(report.get("launcher_cache_candidates", []))
    readiness = dict(report.get("extraction_readiness", {}))
    lines = [
        "# Local Epic/Fab Library Deep Dive",
        "",
        f"- Confirmed cached owned entries: `{len(confirmed_entries)}`",
        f"- Launcher cache candidate families: `{len(launcher_candidates)}`",
        f"- Can extract now: `{bool(readiness.get('can_extract_now'))}`",
        f"- Recommended path: {readiness.get('recommended_path', '')}",
        "",
    ]
    editors = readiness.get("unreal_editor_paths") or []
    if editors:
        lines.append(f"- Unreal editors: `{', '.join(str(item) for item in editors)}`")
    extractors = readiness.get("extractor_tools") or {}
    if extractors:
        tool_text = ", ".join(f"{name}={path}" for name, path in sorted(dict(extractors).items()))
        lines.append(f"- Extractor tools: `{tool_text}`")
    lines.append("")
    lines.append(render_local_epic_vault_inventory_markdown(confirmed_entries).strip())
    lines.append("")
    lines.append(render_local_epic_launcher_cache_markdown(launcher_candidates).strip())
    return "\n".join(lines).strip() + "\n"


def _classify_cached_unreal_listing(stats: dict[str, int]) -> str:
    static_meshes = stats["static_mesh_candidates"]
    skeletal_meshes = stats["skeletal_mesh_candidates"]
    animations = stats["animation_candidates"]
    blueprints = stats["blueprint_candidates"]

    if static_meshes >= 10 and skeletal_meshes == 0 and animations == 0:
        return "environment_art_heavy"
    if skeletal_meshes > 0 or animations >= 5:
        return "character_animation_mix"
    if blueprints > (static_meshes + skeletal_meshes + animations):
        return "logic_template_heavy"
    return "mixed_content"


def _extractability_notes(stats: dict[str, int]) -> str:
    if stats["skeletal_mesh_candidates"] > 0 or stats["animation_candidates"] > 0:
        return "Good candidate for skeletal mesh + animation extraction."
    if stats["static_mesh_candidates"] > 0:
        return "Good candidate for static mesh + texture extraction."
    if stats["texture_candidates"] > 0 or stats["sound_candidates"] > 0:
        return "Mostly textures/audio; limited 3D extraction value."
    return "Mostly logic or map content; low direct 3D extraction value."


def scan_cached_unreal_content(content_root: str | Path) -> dict[str, int]:
    root = Path(content_root)
    stats = {
        "uasset_files": 0,
        "umap_files": 0,
        "static_mesh_candidates": 0,
        "skeletal_mesh_candidates": 0,
        "animation_candidates": 0,
        "texture_candidates": 0,
        "sound_candidates": 0,
        "blueprint_candidates": 0,
        "material_candidates": 0,
    }
    if not root.exists():
        return stats

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        suffix = file_path.suffix.lower()
        rel = str(file_path.relative_to(root)).replace("\\", "/")
        name = file_path.stem
        rel_lower = rel.lower()
        name_upper = name.upper()

        if suffix == ".uasset":
            stats["uasset_files"] += 1
        elif suffix == ".umap":
            stats["umap_files"] += 1

        if "/meshes/" in rel_lower and name_upper.startswith("SM_"):
            stats["static_mesh_candidates"] += 1
        elif name_upper.startswith("SM_"):
            stats["static_mesh_candidates"] += 1

        if "/mesh/" in rel_lower and "sk_" in name_upper.lower():
            stats["skeletal_mesh_candidates"] += 1
        elif "/meshes/" in rel_lower and (name_upper.startswith("SK_") or name_upper.startswith("SKM_")):
            stats["skeletal_mesh_candidates"] += 1
        elif name_upper.startswith("SK_") or name_upper.startswith("SKM_"):
            stats["skeletal_mesh_candidates"] += 1

        if "/animations/" in rel_lower or "/anims/" in rel_lower:
            stats["animation_candidates"] += 1
        elif any(token in rel_lower for token in ("/animnotify", "/animmodifier", "/montage")):
            stats["animation_candidates"] += 1
        elif any(token in name_upper for token in ("IDLE", "RUN", "WALK", "JUMP", "SPRINT", "TURN_")):
            stats["animation_candidates"] += 1

        if "/textures/" in rel_lower or name_upper.startswith("T_"):
            stats["texture_candidates"] += 1
        if "/sound/" in rel_lower or "/audio/" in rel_lower:
            stats["sound_candidates"] += 1
        if "/blueprint" in rel_lower or name_upper.startswith(("BP_", "BPI_", "AC_")):
            stats["blueprint_candidates"] += 1
        if "/materials/" in rel_lower or name_upper.startswith(("M_", "MI_", "MF_", "ML_")):
            stats["material_candidates"] += 1

    return stats


def build_local_epic_vault_inventory(db_path: str | Path | None = None) -> list[dict[str, object]]:
    resolved_db_path = Path(db_path) if db_path is not None else default_local_fab_library_db_path()
    if not resolved_db_path.exists():
        return []

    conn = sqlite3.connect(resolved_db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                l.uid,
                l.title,
                l.thumbnail,
                d.format,
                d.path,
                d.cache_size
            FROM local_listing l
            INNER JOIN listing_acquisition a ON a.listing_uid = l.uid
            LEFT JOIN download_meta d ON d.listing_uid = l.uid
            ORDER BY l.title COLLATE NOCASE
            """
        ).fetchall()
    finally:
        conn.close()

    inventory: list[dict[str, object]] = []
    for row in rows:
        cache_path = Path(str(row["path"])) if row["path"] else None
        content_root = cache_path / "data" / "Content" if cache_path is not None else None
        stats = scan_cached_unreal_content(content_root) if content_root is not None else scan_cached_unreal_content(Path())
        inventory.append(
            {
                "listing_uid": row["uid"],
                "title": row["title"],
                "thumbnail": row["thumbnail"],
                "format": row["format"] or "",
                "cache_path": str(cache_path) if cache_path is not None else "",
                "content_root": str(content_root) if content_root is not None else "",
                "cache_size_bytes": int(row["cache_size"] or 0),
                "content_present": bool(content_root and content_root.exists()),
                "stats": stats,
                "classification": _classify_cached_unreal_listing(stats),
                "extractability_notes": _extractability_notes(stats),
            }
        )
    return inventory


def render_local_epic_vault_inventory_markdown(entries: list[dict[str, object]]) -> str:
    lines = [
        "# Local Epic/Fab Vault Inventory",
        "",
        f"- Cached owned entries: `{len(entries)}`",
        "",
    ]
    for entry in entries:
        stats = dict(entry.get("stats", {}))
        lines.extend(
            [
                f"## {entry.get('title', 'Untitled cached entry')}",
                "",
                f"- Listing uid: `{entry.get('listing_uid', '')}`",
                f"- Format: `{entry.get('format', '')}`",
                f"- Cache path: `{entry.get('cache_path', '')}`",
                f"- Classification: `{entry.get('classification', 'mixed_content')}`",
                f"- Extractability: {entry.get('extractability_notes', 'Needs manual review.')}",
                f"- Static mesh candidates: `{stats.get('static_mesh_candidates', 0)}`",
                f"- Skeletal mesh candidates: `{stats.get('skeletal_mesh_candidates', 0)}`",
                f"- Animation candidates: `{stats.get('animation_candidates', 0)}`",
                f"- Texture candidates: `{stats.get('texture_candidates', 0)}`",
                f"- Sound candidates: `{stats.get('sound_candidates', 0)}`",
                f"- Blueprint candidates: `{stats.get('blueprint_candidates', 0)}`",
                f"- Map files: `{stats.get('umap_files', 0)}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _inventory_entry_to_pack_id(entry: dict[str, object], index: int) -> str:
    title = str(entry.get("title", "")).strip() or f"epic_cached_{index}"
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", title.upper()).strip("_")
    normalized = "_".join(part for part in normalized.split("_") if part)
    trimmed = "_".join(normalized.split("_")[:6]) or f"EPIC_CACHED_{index:02d}"
    return f"SHARED_EPIC_{trimmed}_{index:02d}"


def _inventory_entry_asset_kind(entry: dict[str, object]) -> str:
    classification = str(entry.get("classification", "")).strip().lower()
    if classification == "environment_art_heavy":
        return "architecture"
    if classification == "character_animation_mix":
        return "character"
    return "prop"


def emit_epic_cache_extractor_wave(
    entries: list[dict[str, object]],
    *,
    game_scope: str = "arena_shared",
    tool: ExtractorTool | str = ExtractorTool.FMODEL,
    output_dir: str | Path | None = None,
) -> list[dict[str, object]]:
    emitted: list[dict[str, object]] = []
    root_dir = Path(output_dir) if output_dir is not None else generated_output_root() / "epic_extractors"
    for index, entry in enumerate(entries, start=1):
        stats = dict(entry.get("stats", {}))
        if int(stats.get("static_mesh_candidates", 0)) <= 0 and int(stats.get("skeletal_mesh_candidates", 0)) <= 0:
            continue
        title = str(entry.get("title", "")).strip()
        pack_id = _inventory_entry_to_pack_id(entry, index)
        artifacts = emit_extractor_job(
            tool=tool,
            pack_id=pack_id,
            game_scope=game_scope,
            source_package_name=title or pack_id,
            source_url=f"epic-cache://{entry.get('listing_uid', pack_id)}",
            license_note="Owned Epic/Fab cached Unreal content",
            input_path_hint=str(entry.get("cache_path", "")),
            asset_kind=_inventory_entry_asset_kind(entry),
            output_dir=root_dir / pack_id,
        )
        emitted.append(
            {
                "pack_id": pack_id,
                "title": title,
                "cache_path": str(entry.get("cache_path", "")),
                "artifacts": artifacts.to_dict(),
            }
        )
    return emitted


def _dummy_project_payload(engine_association: str) -> dict[str, object]:
    return {
        "FileVersion": 3,
        "EngineAssociation": engine_association,
        "Category": "",
        "Description": "Dummy project to acquire Fab/Marketplace assets for AssetBoy extraction.",
    }


def _build_uevaultmanager_script(job: EpicVaultJob) -> str:
    source_listing_hint = ""
    marker = "/listings/"
    if marker in job.source_url:
        source_listing_hint = job.source_url.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
    return "\n".join(
        [
            "param(",
            '  [string]$VaultTool = "UEVaultManager",',
            f'  [string]$VaultItem = "{job.vault_item}",',
            f'  [string]$SourceListingHint = "{source_listing_hint}",',
            f'  [string]$OutputDir = "{job.download_target}",',
            '  [string]$ConfigFile = "$PSScriptRoot\\uevaultmanager.safe.ini",',
            '  [string]$ListOutput = "$PSScriptRoot\\uevault_owned_assets.json",',
            "  [switch]$ImportFromLauncher = $false,",
            "  [switch]$InteractiveAuth = $false,",
            "  [switch]$EnableNoDriver = $false,",
            "  [switch]$SkipInstall = $false,",
            "  [switch]$FullInstall = $false",
            ")",
            "",
            '$ErrorActionPreference = "Stop"',
            "$script:LastUevmExitCode = 0",
            "",
            "function Write-UevmConfig {",
            "  param([string]$Path)",
            "  $base = @(",
            "    '[UEVaultManager]'",
            "    'start_in_edit_mode = False'",
            "    'disable_update_check = False'",
            "    'create_output_backup = False'",
            "    'create_log_backup = False'",
            "    'verbose_mode = False'",
            "  )",
            "  [System.IO.File]::WriteAllText($Path, ($base -join \"`n\") + \"`n\", (New-Object System.Text.UTF8Encoding($false)))",
            "}",
            "",
            "function Invoke-Uevm {",
            "  param([string[]]$CmdArgs)",
            "  Write-UevmConfig -Path $ConfigFile",
            "  $printableArgs = ($CmdArgs | ForEach-Object {",
            "    if ($_ -match '\\s') { '\"' + $_ + '\"' } else { $_ }",
            "  }) -join ' '",
            '  Write-Host "UEVM>" $VaultTool "-y -c" "`"$ConfigFile`"" $printableArgs',
            "  & $VaultTool -y -c $ConfigFile @CmdArgs",
            "  $script:LastUevmExitCode = $LASTEXITCODE",
            "}",
            "",
            "if (-not (Get-Command $VaultTool -ErrorAction SilentlyContinue)) {",
            '  throw "UEVaultManager executable not found. Set -VaultTool to full path if needed."',
            "}",
            'if (!(Test-Path $OutputDir)) { New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null }',
            "Write-UevmConfig -Path $ConfigFile",
            "",
            "$eglConfig = Join-Path $env:LOCALAPPDATA 'EpicGamesLauncher\\Saved\\Config\\Windows\\GameUserSettings.ini'",
            "$rememberMeReady = $false",
            "if (Test-Path $eglConfig) {",
            "  $eglRaw = Get-Content -Path $eglConfig -Raw",
            "  if ($eglRaw -match '(?m)^\\[RememberMe\\]' -and $eglRaw -match '(?m)^Data=.+') {",
            "    $rememberMeReady = $true",
            "  }",
            "}",
            "",
            'Write-Host "AssetBoy UEVaultManager bridge"',
            'Write-Host "Safe config file:" $ConfigFile',
            'Write-Host "Output target:" $OutputDir',
            'Write-Host "Owned-assets list file:" $ListOutput',
            "if (-not $EnableNoDriver) {",
            '  $env:UEVM_DISABLE_NODRIVER = "1"',
            '  Write-Host "NoDriver disabled: true (avoids extra Chrome windows)"',
            "} else {",
            '  Remove-Item Env:UEVM_DISABLE_NODRIVER -ErrorAction SilentlyContinue',
            '  Write-Host "NoDriver disabled: false (may spawn Chrome windows)"',
            "}",
            "",
            "Invoke-Uevm -CmdArgs @('status', '--json')",
            "$statusExit = $script:LastUevmExitCode",
            "if ($statusExit -ne 0) {",
            '  Write-Host "[WARN] UEVaultManager status check failed. Auth may still work, but verify with manual status command below."',
            "}",
            "",
            "if ($ImportFromLauncher) {",
            "  if (-not $rememberMeReady) {",
            '    Write-Host "[WARN] Epic Launcher RememberMe token not found. Import is likely to fail."',
            '    Write-Host "       Open Epic Launcher -> sign in with Remember Me checked -> close launcher fully -> retry."',
            "  }",
            "  Invoke-Uevm -CmdArgs @('auth', '--import')",
            "  $importExit = $script:LastUevmExitCode",
            "  if ($importExit -ne 0) {",
            '    Write-Host "[WARN] UEVaultManager auth import failed. Use dummy-project fallback if needed."',
            "  }",
            "}",
            "",
            "if ($InteractiveAuth) {",
            "  Invoke-Uevm -CmdArgs @('auth', '--disable-webview')",
            "  $authExit = $script:LastUevmExitCode",
            "  if ($authExit -ne 0) {",
            '    Write-Host "[WARN] Non-webview auth failed; retrying default interactive auth."',
            "    Invoke-Uevm -CmdArgs @('auth')",
            "    $authExit = $script:LastUevmExitCode",
            "  }",
            "  if ($authExit -ne 0) {",
            '    Write-Host "[WARN] Interactive auth still failed. Use dummy-project fallback if needed."',
            "  }",
            "}",
            "",
            "if (Test-Path $ListOutput) {",
            "  try {",
            "    Remove-Item -Path $ListOutput -Force -ErrorAction Stop",
            "  } catch {",
            '    Write-Host "[WARN] Could not clear previous list output file. UEVaultManager may fail when merging stale JSON."',
            "  }",
            "}",
            "Invoke-Uevm -CmdArgs @('list', '--json', '-o', $ListOutput)",
            "$listExit = $script:LastUevmExitCode",
            "if ($listExit -ne 0) {",
            '  Write-Host "[WARN] Unable to list vault assets. This is often a UEVaultManager list/output merge bug, not an auth failure."',
            '  Write-Host "       Retry with a fresh -ListOutput path and inspect status output for Epic account name."',
            "}",
            "$ownedAssetCount = $null",
            "if (($listExit -eq 0) -and (Test-Path $ListOutput)) {",
            "  try {",
            "    $listJson = Get-Content -Path $ListOutput -Raw | ConvertFrom-Json",
            "    if ($null -ne $listJson) {",
            "      $listItems = @($listJson.PSObject.Properties | ForEach-Object { $_.Value })",
            "      $ownedAssetCount = @($listItems | Where-Object { $_.Owned -eq $true }).Count",
            "      if ($ownedAssetCount -eq 0) {",
            '        Write-Host "[WARN] Owned asset list contained zero owned entries."',
            '        Write-Host "       UEVaultManager marketplace metadata is likely stale or missing current Fab coverage."',
            '        Write-Host "       Install by title/app name will usually fail until the asset exists in the owned metadata cache."',
            "      }",
            "    }",
            "  } catch {",
            '    Write-Host "[WARN] Could not parse the owned-assets list output. Proceeding with install attempt anyway."',
            "  }",
            "}",
            "",
            "$resolvedVaultItem = $VaultItem",
            "if (-not $resolvedVaultItem) {",
            "  $resolvedVaultItem = $SourceListingHint",
            "}",
            "",
            "if (-not $SkipInstall -and $resolvedVaultItem) {",
            "  $installArgs = @('install', $resolvedVaultItem, '-dp', $OutputDir)",
            "  if (-not $FullInstall) {",
            "    $installArgs += '--download-only'",
            "  }",
            "  Invoke-Uevm -CmdArgs $installArgs",
            "  $installExit = $script:LastUevmExitCode",
            "  if ($installExit -ne 0) {",
            '    Write-Host "[WARN] Install/download failed. Fab ownership may exist, but UEVaultManager may still lack matching marketplace metadata for this asset."',
            '    Write-Host "       If the owned-assets list reported zero owned entries or the asset is missing from cache, use dummy-project fallback."',
            "  }",
            "} elseif (-not $SkipInstall) {",
            '  Write-Host "[WARN] No vault item hint was provided. Pass -VaultItem or include /listings/<id> in source URL."',
            "}",
            "",
            'Write-Host ""',
            'Write-Host "Next commands (adjust to your UEVaultManager version):"',
            'Write-Host "  $VaultTool -c `"$ConfigFile`" --help"',
            'Write-Host "  $VaultTool -c `"$ConfigFile`" install --help"',
            'if ($resolvedVaultItem) { Write-Host "  Target vault item hint: $resolvedVaultItem" }',
            'Write-Host "  $VaultTool -c `"$ConfigFile`" list --json -o `"$ListOutput`""',
            'Write-Host "  $VaultTool -c `"$ConfigFile`" install `"$resolvedVaultItem`" -dp `"$OutputDir`" --download-only"',
            f'Write-Host "Stage extracted open formats into: {job.staging_target}"',
            'Write-Host "If vault auth remains unstable, run epic dummy-project fallback for this same pack."',
        ]
    ) + "\n"


def _build_dummy_project_script(job: EpicVaultJob) -> str:
    payload_json = json.dumps(_dummy_project_payload(job.engine_association), indent=2)
    return "\n".join(
        [
            "param(",
            f'  [string]$ProjectDir = "{job.project_dir}",',
            f'  [string]$ProjectName = "{job.project_name}",',
            f'  [string]$EngineAssociation = "{job.engine_association}",',
            "  [switch]$PatchLauncherConfig = $true",
            ")",
            "",
            '$ErrorActionPreference = "Stop"',
            "",
            '$uprojectPath = Join-Path $ProjectDir ($ProjectName + ".uproject")',
            '$contentPath = Join-Path $ProjectDir "Content"',
            "",
            'if (!(Test-Path $ProjectDir)) { New-Item -ItemType Directory -Path $ProjectDir -Force | Out-Null }',
            'if (!(Test-Path $contentPath)) { New-Item -ItemType Directory -Path $contentPath -Force | Out-Null }',
            "",
            '$payload = @\'',
            payload_json,
            '\'@',
            'Set-Content -Path $uprojectPath -Value $payload -Encoding UTF8',
            "",
            'Write-Host "Dummy project ready:" $uprojectPath',
            'Write-Host "Fully restart Epic Games Launcher, then Add to Project -> select this dummy project."',
            "",
            "if ($PatchLauncherConfig) {",
            '  $configPath = Join-Path $env:LOCALAPPDATA "EpicGamesLauncher\\Saved\\Config\\Windows\\GameUserSettings.ini"',
            "  if (Test-Path $configPath) {",
            "    $ini = Get-Content -Path $configPath -Raw",
            "    if ($ini -notmatch '(?m)^\\[Launcher\\]') {",
            '      $ini += "`r`n[Launcher]`r`n"',
            "    }",
            "    if ($ini -notmatch [regex]::Escape(\"CreatedProjectPaths=$ProjectDir\")) {",
            '      $ini += "`r`nCreatedProjectPaths=$ProjectDir`r`n"',
            '      Set-Content -Path $configPath -Value $ini -Encoding UTF8',
            '      Write-Host "Patched GameUserSettings.ini with CreatedProjectPaths."',
            "    }",
            "  }",
            "}",
            "",
            f'Write-Host "Downloaded raw assets will land under: {job.download_target}"',
            f'Write-Host "After extraction/cleanup stage outputs into: {job.staging_target}"',
        ]
    ) + "\n"


def _build_uevaultmanager_command_template(job: EpicVaultJob, script_path: Path) -> str:
    return "\n".join(
        [
            "# Recommended safe path: use the AssetBoy no-browser wrapper commands first.",
            "python -m assetboy.cli uevault-repair-config",
            "python -m assetboy.cli uevault-status",
            "python -m assetboy.cli uevault-import-auth",
            'python -m assetboy.cli uevault-list-owned --output ".\\uevault_owned_assets.json"',
            f'python -m assetboy.cli uevault-install-owned --vault-item "{job.vault_item or "listing_id_or_app_name"}" --download-dir "{job.download_target}"',
            "",
            "# Then use the hardened PowerShell wrapper if you want the generated per-pack workflow files.",
            f'pwsh -ExecutionPolicy Bypass -File "{script_path}"',
            f'pwsh -ExecutionPolicy Bypass -File "{script_path}" -ImportFromLauncher',
            f'pwsh -ExecutionPolicy Bypass -File "{script_path}" -SkipInstall',
            "",
            "# Browser-launching fallback (last resort only, may open extra windows if you ask for it):",
            f'pwsh -ExecutionPolicy Bypass -File "{script_path}" -InteractiveAuth',
            f'pwsh -ExecutionPolicy Bypass -File "{script_path}" -EnableNoDriver -InteractiveAuth',
            "",
            "# Direct raw CLI (if you need manual control):",
            "UEVaultManager --help",
            'UEVaultManager -c ".\\uevaultmanager.safe.ini" status --offline --json',
            'UEVaultManager -c ".\\uevaultmanager.safe.ini" auth --import',
            'UEVaultManager -c ".\\uevaultmanager.safe.ini" list --json -o ".\\uevault_owned_assets.json"',
            f'UEVaultManager -c ".\\uevaultmanager.safe.ini" install "{job.vault_item or "listing_id_or_app_name"}" -dp "{job.download_target}" --download-only',
            "# If the owned-assets list shows zero owned entries or install says metadata are unavailable, stop here and run the dummy-project fallback for the same pack.",
            "",
            "# Then extract owned Unreal assets into open formats:",
            f'python -m assetboy.cli emit-extractor-job --tool fmodel --pack-id {job.pack_id} --game-scope {job.game_scope} --source-package-name "{job.vault_item or job.pack_id}" --source-url "{job.source_url}" --license-note "Owned Fab/Marketplace vault item" --input-path-hint "{job.download_target}"',
        ]
    ) + "\n"


def _build_dummy_project_command_template(job: EpicVaultJob, script_path: Path) -> str:
    return "\n".join(
        [
            f'pwsh -ExecutionPolicy Bypass -File "{script_path}"',
            "",
            "# Epic Launcher flow:",
            "1) Fully close Launcher (including tray icon) and reopen.",
            "2) Library -> Fab/Vault -> Add to Project.",
            "3) Select dummy project and choose closest compatible version.",
            "",
            "# Then extract open formats for Flax pipeline:",
            f'python -m assetboy.cli emit-extractor-job --tool fmodel --pack-id {job.pack_id} --game-scope {job.game_scope} --source-package-name "{job.project_name}" --source-url "{job.source_url}" --license-note "Owned Fab/Marketplace vault item via dummy project" --input-path-hint "{job.download_target}"',
        ]
    ) + "\n"


def emit_uevaultmanager_job(
    *,
    pack_id: str,
    game_scope: str,
    source_url: str,
    vault_item: str = "",
    engine_association: str = "5.3",
    output_dir: str | Path | None = None,
    notes: tuple[str, ...] = (),
) -> EpicVaultArtifacts:
    source_adapter = "uevaultmanager"
    download_target = manual_drop_dir() / pack_id / "epic_raw"
    staging_target = manual_drop_dir() / pack_id
    project_dir = manual_drop_dir() / pack_id / "_dummy_project"
    project_name = "DummyProject"
    uproject_path = project_dir / f"{project_name}.uproject"
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "epic_vault" / source_adapter / pack_id
    )
    job = EpicVaultJob(
        method=EpicVaultMethod.UEVAULTMANAGER,
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        vault_item=vault_item,
        engine_association=engine_association,
        source_adapter=source_adapter,
        download_target=download_target,
        staging_target=staging_target,
        project_dir=project_dir,
        project_name=project_name,
        uproject_path=uproject_path,
        notes=notes,
    )
    provenance = build_provenance_template(
        pack_id=pack_id,
        game_scope=game_scope,
        lane=ProviderLane.MANUAL_BROWSER,
        source_adapter=source_adapter,
        payload_target_path=str(payload_target),
        notes=notes,
    )
    provenance["values"]["source_page_url"] = source_url
    provenance["values"]["download_notes"] = "Owned Fab/Marketplace vault item downloaded through UEVaultManager."

    checklist = "\n".join(
        [
            "# Fab Vault (UEVaultManager) Checklist",
            "",
            f"- Pack: `{pack_id}`",
            f"- Game scope: `{game_scope}`",
            f"- Source URL: `{source_url}`",
            f"- Download target: `{download_target}`",
            f"- Staging target: `{staging_target}`",
            f"- Payload target: `{payload_target}`",
            "",
            "## Steps",
            "- Run the generated UEVaultManager wrapper script first (it repairs known config issues and checks RememberMe state).",
            "- Import Epic Launcher session only after RememberMe token is present in Epic Launcher config.",
            "- Download owned Fab/Marketplace vault item into the raw target folder.",
            "- Run FModel or Umodel extractor bridge on downloaded content.",
            "- Keep models, animations, textures, audio only; skip plugins/editor tools/code by default.",
            "- Run Blender cleanup and then publish reviewed payload.",
        ]
    ) + "\n"

    job_spec_path = write_json(root_dir / "epic_vault_job.json", job.to_dict())
    provenance_template_path = write_json(root_dir / "provenance_template.json", provenance)
    review_checklist_path = write_text(root_dir / "review_checklist.md", checklist)
    payload_target_path_file = write_text(root_dir / "payload_target.txt", str(payload_target) + "\n")
    script_path = write_text(root_dir / "run_uevaultmanager.ps1", _build_uevaultmanager_script(job))
    command_template_path = write_text(root_dir / "commands.txt", _build_uevaultmanager_command_template(job, script_path))
    write_text(uproject_path, json.dumps(_dummy_project_payload(engine_association), indent=2) + "\n")

    return EpicVaultArtifacts(
        output_dir=root_dir,
        job_spec_path=job_spec_path,
        review_checklist_path=review_checklist_path,
        provenance_template_path=provenance_template_path,
        payload_target_path_file=payload_target_path_file,
        script_path=script_path,
        command_template_path=command_template_path,
        uproject_path=uproject_path,
        download_target_path=download_target,
        staging_target_path=staging_target,
    )


def emit_epic_dummy_project_job(
    *,
    pack_id: str,
    game_scope: str,
    source_url: str,
    engine_association: str = "5.3",
    project_name: str = "DummyProject",
    project_dir: str | Path | None = None,
    output_dir: str | Path | None = None,
    notes: tuple[str, ...] = (),
) -> EpicVaultArtifacts:
    source_adapter = "epic_dummy_project"
    resolved_project_dir = Path(project_dir) if project_dir is not None else manual_drop_dir() / pack_id / "_dummy_project"
    download_target = resolved_project_dir / "Content"
    staging_target = manual_drop_dir() / pack_id
    uproject_path = resolved_project_dir / f"{project_name}.uproject"
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "epic_vault" / source_adapter / pack_id
    )
    job = EpicVaultJob(
        method=EpicVaultMethod.DUMMY_PROJECT,
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        vault_item=project_name,
        engine_association=engine_association,
        source_adapter=source_adapter,
        download_target=download_target,
        staging_target=staging_target,
        project_dir=resolved_project_dir,
        project_name=project_name,
        uproject_path=uproject_path,
        notes=notes,
    )
    provenance = build_provenance_template(
        pack_id=pack_id,
        game_scope=game_scope,
        lane=ProviderLane.MANUAL_BROWSER,
        source_adapter=source_adapter,
        payload_target_path=str(payload_target),
        notes=notes,
    )
    provenance["values"]["source_page_url"] = source_url
    provenance["values"]["download_notes"] = "Owned Fab/Marketplace vault item acquired through Epic Launcher dummy-project flow."

    checklist = "\n".join(
        [
            "# Fab Vault (Dummy Project) Checklist",
            "",
            f"- Pack: `{pack_id}`",
            f"- Game scope: `{game_scope}`",
            f"- Source URL: `{source_url}`",
            f"- Dummy project path: `{resolved_project_dir}`",
            f"- Download target: `{download_target}`",
            f"- Staging target: `{staging_target}`",
            f"- Payload target: `{payload_target}`",
            "",
            "## Steps",
            "- Create and save the dummy .uproject file (script generated here).",
            "- Fully restart Epic Launcher before Add to Project.",
            "- Use Show all projects if the dummy project does not show immediately.",
            "- If version mismatch appears, choose closest compatible version in dropdown.",
            "- If Launcher still cannot find the project, patch GameUserSettings.ini CreatedProjectPaths.",
            "- Extract open formats (FModel/Umodel), then run Blender cleanup and publish reviewed payload.",
        ]
    ) + "\n"

    write_text(uproject_path, json.dumps(_dummy_project_payload(engine_association), indent=2) + "\n")
    job_spec_path = write_json(root_dir / "epic_vault_job.json", job.to_dict())
    provenance_template_path = write_json(root_dir / "provenance_template.json", provenance)
    review_checklist_path = write_text(root_dir / "review_checklist.md", checklist)
    payload_target_path_file = write_text(root_dir / "payload_target.txt", str(payload_target) + "\n")
    script_path = write_text(root_dir / "prepare_dummy_project.ps1", _build_dummy_project_script(job))
    command_template_path = write_text(root_dir / "commands.txt", _build_dummy_project_command_template(job, script_path))

    return EpicVaultArtifacts(
        output_dir=root_dir,
        job_spec_path=job_spec_path,
        review_checklist_path=review_checklist_path,
        provenance_template_path=provenance_template_path,
        payload_target_path_file=payload_target_path_file,
        script_path=script_path,
        command_template_path=command_template_path,
        uproject_path=uproject_path,
        download_target_path=download_target,
        staging_target_path=staging_target,
    )
