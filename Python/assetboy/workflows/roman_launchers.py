from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, manual_drop_dir, project_root


_BATCH_VAR_PATTERN = re.compile(r'set\s+"(?P<name>[^=]+)=(?P<value>[^"]*)"', re.IGNORECASE)
_SOURCE_URL_LIST_PATTERN = re.compile(r'-SourceUrlList\s+"(?P<value>[^"]*)"', re.IGNORECASE)
_START_URL_PATTERN = re.compile(r'^\s*start\s+""\s+"(?P<url>https?://[^"]+)"', re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class RomanLauncherManifestArtifacts:
    output_dir: Path
    manifest_path: Path
    summary_path: Path
    source_manifests_dir: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "manifest_path": str(self.manifest_path),
            "summary_path": str(self.summary_path),
            "source_manifests_dir": str(self.source_manifests_dir),
        }


def _extract_batch_var(text: str, name: str) -> str:
    target = name.lower()
    for match in _BATCH_VAR_PATTERN.finditer(text):
        if match.group("name").strip().lower() == target:
            return match.group("value").strip()
    return ""


def _resolve_repo_path(repo_root: Path, value: str) -> str:
    if not value:
        return ""
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate.resolve())
    return str((repo_root / candidate).resolve())


def _extract_source_urls(text: str) -> list[str]:
    source_urls: list[str] = []
    source_list_match = _SOURCE_URL_LIST_PATTERN.search(text)
    if source_list_match:
        for item in source_list_match.group("value").split("|"):
            normalized = item.strip()
            if normalized:
                source_urls.append(normalized)
    for match in _START_URL_PATTERN.finditer(text):
        normalized = match.group("url").strip()
        if normalized and normalized not in source_urls:
            source_urls.append(normalized)
    return source_urls


def _launcher_group(path: Path) -> str:
    stem = path.stem
    if stem.startswith("ROMAN_"):
        stem = stem[len("ROMAN_") :]
    stem = stem.replace("_ASSETS", "").replace("_DOWNLOADS", "")
    return stem.lower()


def _launcher_mode(text: str, source_urls: list[str]) -> str:
    if _extract_batch_var(text, "HELPER_PS"):
        return "manual_source_helper"
    if source_urls and all(url.lower().endswith(".zip") for url in source_urls):
        return "direct_url_open"
    if source_urls:
        return "browser_open"
    if _extract_batch_var(text, "UI_PS"):
        return "asset_ui"
    return "unknown"


def _recommended_script_path(repo_root: Path, legacy_script_path: str) -> str:
    if not legacy_script_path:
        return ""
    legacy_name = Path(legacy_script_path).name.lower()
    if legacy_name in {"flaxmcp-asset-frontdoor-ui.ps1", "flaxmcp-asset-ui.ps1"}:
        for candidate in (
            repo_root / "scripts" / "flaxmcp-asset-frontdoor-ui.ps1",
            repo_root / "scripts" / "archive" / "flaxmcp-asset-frontdoor-ui.ps1",
            repo_root / "scripts" / "archive" / "flaxmcp-asset-ui.ps1",
        ):
            if candidate.exists():
                return str(candidate.resolve())
    if legacy_name == "flaxmcp-roman-manual-source-helper.ps1":
        for candidate in (
            repo_root / "scripts" / "experimental" / "flaxmcp-roman-manual-source-helper.ps1",
            repo_root / "scripts" / "archive" / "flaxmcp-roman-manual-source-helper.ps1",
        ):
            if candidate.exists():
                return str(candidate.resolve())
    return ""


def _build_launcher_entry(path: Path, repo_root: Path, game_scope: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    pack_id = _extract_batch_var(text, "PACK_ID")
    launcher_game_scope = _extract_batch_var(text, "GAME_SCOPE") or game_scope
    queue_file = _extract_batch_var(text, "QUEUE_FILE")
    ui_script = _extract_batch_var(text, "UI_PS")
    helper_script = _extract_batch_var(text, "HELPER_PS")
    checklist_path = _extract_batch_var(text, "CHECKLIST")
    source_urls = _extract_source_urls(text)
    legacy_script = ui_script or helper_script
    legacy_script_path = _resolve_repo_path(repo_root, legacy_script)
    recommended_script_path = _recommended_script_path(repo_root, legacy_script)
    library_root = repo_root / "artifacts" / "library" / "FlaxAssetLibrary"
    drop_root = manual_drop_dir(repo_root)
    assetboy_drop_target = str((drop_root / pack_id).resolve()) if pack_id else str(drop_root.resolve())

    entry = {
        "name": path.name,
        "path": str(path.resolve()),
        "group": _launcher_group(path),
        "mode": _launcher_mode(text, source_urls),
        "pack_id": pack_id,
        "game_scope": launcher_game_scope,
        "queue_file": _resolve_repo_path(repo_root, queue_file),
        "checklist_path": _resolve_repo_path(repo_root, checklist_path),
        "source_urls": source_urls,
        "legacy_script_path": legacy_script_path,
        "legacy_script_exists": bool(legacy_script_path and Path(legacy_script_path).exists()),
        "recommended_script_path": recommended_script_path,
        "recommended_script_exists": bool(recommended_script_path and Path(recommended_script_path).exists()),
        "legacy_library_root": str(library_root.resolve()),
        "assetboy_drop_target": assetboy_drop_target,
    }
    if pack_id:
        entry["assetboy_drop_root"] = str(drop_root.resolve())
    return entry


def _build_summary(
    *,
    game_scope: str,
    launcher_dir: Path,
    pack_presets: list[dict[str, Any]],
    global_helpers: list[dict[str, Any]],
) -> str:
    stale_count = 0
    for preset in pack_presets:
        for entry in (preset.get("asset_launcher", {}), preset.get("source_manifest", {})):
            if entry.get("legacy_script_path") and not entry.get("legacy_script_exists", False):
                stale_count += 1
    for entry in global_helpers:
        if entry.get("legacy_script_path") and not entry.get("legacy_script_exists", False):
            stale_count += 1

    lines = [
        "# Roman Launcher Import",
        "",
        f"- Game scope: `{game_scope}`",
        f"- Launcher directory: `{launcher_dir}`",
        f"- Pack presets imported: `{len(pack_presets)}`",
        f"- Global helpers imported: `{len(global_helpers)}`",
        f"- Stale script references detected: `{stale_count}`",
        "",
        "## Pack Presets",
    ]
    for preset in pack_presets:
        asset_name = preset.get("asset_launcher", {}).get("name", "none")
        source_name = preset.get("source_manifest", {}).get("name", "none")
        lines.append(
            f"- `{preset['pack_id']}` via `{asset_name}` "
            f"and `{source_name}`"
        )
        source_urls = preset.get("source_manifest", {}).get("source_urls", [])
        if source_urls:
            lines.append(
                f"- Source URLs for `{preset['pack_id']}`: `{len(source_urls)}`"
            )
    lines.extend(["", "## Global Helpers"])
    if not global_helpers:
        lines.append("- None")
    else:
        for helper in global_helpers:
            lines.append(f"- `{helper['name']}` -> `{helper['mode']}`")
    return "\n".join(lines) + "\n"


def emit_roman_launcher_manifest(
    *,
    game_scope: str = "roman_arena",
    output_dir: str | Path | None = None,
    repo_root: str | Path | None = None,
) -> RomanLauncherManifestArtifacts:
    resolved_repo_root = Path(repo_root) if repo_root is not None else project_root()
    resolved_repo_root = resolved_repo_root.resolve()
    launcher_dir = resolved_repo_root / "launchers" / game_scope
    if not launcher_dir.exists():
        raise FileNotFoundError(f"Roman launcher directory not found: {launcher_dir}")

    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "roman_launchers" / game_scope
    )
    source_manifests_dir = root_dir / "source_manifests"

    asset_entries: dict[str, dict[str, Any]] = {}
    source_entries: dict[str, dict[str, Any]] = {}
    global_helpers: list[dict[str, Any]] = []
    stale_script_references: list[dict[str, str]] = []

    for path in sorted(launcher_dir.glob("*.bat")):
        entry = _build_launcher_entry(path, resolved_repo_root, game_scope)
        if entry["legacy_script_path"] and not entry["legacy_script_exists"]:
            stale_script_references.append(
                {
                    "launcher": entry["name"],
                    "legacy_script_path": entry["legacy_script_path"],
                    "recommended_script_path": entry["recommended_script_path"],
                }
            )

        if path.name.endswith("_ASSETS.bat") and entry["pack_id"]:
            asset_entries[entry["pack_id"]] = entry
            continue

        if path.name.endswith("_DOWNLOADS.bat") and entry["pack_id"]:
            source_entries[entry["pack_id"]] = entry
            continue

        global_helpers.append(entry)

    pack_presets: list[dict[str, Any]] = []
    for pack_id in sorted(set(asset_entries) | set(source_entries)):
        asset_entry = asset_entries.get(pack_id)
        source_entry = source_entries.get(pack_id)
        manifest = {
            "schema_version": "assetboy.roman_source_manifest.v1",
            "game_scope": game_scope,
            "pack_id": pack_id,
            "group": (asset_entry or source_entry or {}).get("group", ""),
            "asset_launcher": asset_entry or {},
            "source_manifest": source_entry or {},
            "assetboy_drop_target": str((manual_drop_dir(resolved_repo_root) / pack_id).resolve()),
        }
        write_json(source_manifests_dir / f"{pack_id}.json", manifest)
        pack_presets.append(manifest)

    manifest_payload = {
        "schema_version": "assetboy.roman_launcher_manifest.v1",
        "game_scope": game_scope,
        "repo_root": str(resolved_repo_root),
        "launcher_dir": str(launcher_dir.resolve()),
        "source_manifests_dir": str(source_manifests_dir.resolve()),
        "pack_presets": pack_presets,
        "global_helpers": global_helpers,
        "stale_script_references": stale_script_references,
    }
    manifest_path = write_json(root_dir / "roman_launcher_manifest.json", manifest_payload)
    summary_path = write_text(
        root_dir / "README.md",
        _build_summary(
            game_scope=game_scope,
            launcher_dir=launcher_dir.resolve(),
            pack_presets=pack_presets,
            global_helpers=global_helpers,
        ),
    )
    return RomanLauncherManifestArtifacts(
        output_dir=root_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
        source_manifests_dir=source_manifests_dir,
    )
