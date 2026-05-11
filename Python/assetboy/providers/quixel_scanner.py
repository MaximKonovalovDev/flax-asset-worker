"""Quixel / Megascans local library scanner.

Extracted from ``providers/library_map.py`` 2026-05-10 (Path B s3).
The old `library_map.py` re-exports these names for backward compat so
existing importers (`epic_vault.py`, `cli.py`) keep working.

Surface:
    build_local_quixel_library_map(*, extra_roots, timeout_seconds) -> dict
        Top-level entry. Combines Bridge API probe + filesystem rglob scan.

    render_local_quixel_library_map_markdown(report) -> str
        Markdown formatter for the report dict.

    scan_quixel_library_root(root, *, sample_limit) -> dict
        Single-root scan; counts category JSON files.

Internal helpers (prefixed _) are exported for tests + advanced callers
but treated as private by convention. Public surface = the 2 functions
above.

No side effects at import time. All functions are read-only against the
local filesystem and the optional Bridge API at http://127.0.0.1:28241.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import requests


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Path helpers (shared with library_map; duplicated to keep this module
# standalone without a circular import)
# --------------------------------------------------------------------------- #

def _append_path(paths: list[Path], seen: set[str], candidate: str | Path | None) -> None:
    if candidate is None:
        return
    resolved = Path(candidate).expanduser()
    key = str(resolved).lower()
    if key in seen:
        return
    seen.add(key)
    paths.append(resolved)


# --------------------------------------------------------------------------- #
# Discovery — Bridge settings, env vars, default install paths
# --------------------------------------------------------------------------- #

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


# --------------------------------------------------------------------------- #
# Bridge API probe (optional — Bridge running locally exposes this)
# --------------------------------------------------------------------------- #

def _probe_quixel_bridge_api(
    *,
    api_base: str = _QUIXEL_API_BASE,
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
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
        folder_response = requests.get(
            f"{api_base}/GetMegascansFolder/", timeout=timeout_seconds
        )
        folder_response.raise_for_status()
        folder_payload = folder_response.json() if folder_response.content else {}
        report["reachable"] = True
        report["megascans_folder"] = str(folder_payload.get("folder", "")).strip()
    except Exception as exc:
        report["error"] = str(exc)
        return report

    try:
        zip_response = requests.get(
            f"{api_base}/GetZipFolderPaths/", timeout=timeout_seconds
        )
        zip_response.raise_for_status()
        zip_payload = zip_response.json() if zip_response.content else {}
        folders = zip_payload.get("folders") or []
        report["zip_folders"] = [str(item).strip() for item in folders if str(item).strip()]
    except Exception:
        report["zip_folders"] = []

    try:
        assets_response = requests.get(
            f"{api_base}/GetAllAssets/", timeout=max(timeout_seconds, 5.0)
        )
        assets_response.raise_for_status()
        assets_payload = assets_response.json() if assets_response.content else {}
        assets = assets_payload.get("assets") or []
        category_counts: Counter[str] = Counter()
        for asset in assets:
            folder = str((asset or {}).get("folder", "")).strip()
            category = _quixel_category_from_parts(Path(folder).parts)
            category_counts[category] += 1
        report["asset_count"] = len(assets)
        report["category_counts"] = dict(
            sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
        )
    except Exception:
        report["asset_count"] = 0
        report["category_counts"] = {}

    return report


# --------------------------------------------------------------------------- #
# Filesystem scan
# --------------------------------------------------------------------------- #

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


def scan_quixel_library_root(
    root: str | Path,
    *,
    sample_limit: int = 24,
) -> dict[str, Any]:
    """Walk a single Quixel library root and return counts + samples."""
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
        "category_counts": dict(
            sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
        ),
        "sample_assets": sample_assets,
    }


# --------------------------------------------------------------------------- #
# Top-level entry
# --------------------------------------------------------------------------- #

def build_local_quixel_library_map(
    *,
    extra_roots: tuple[str | Path, ...] = (),
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    """Combine Bridge API probe + filesystem scan into one report.

    Args:
        extra_roots: additional directories to scan beyond the auto-detected
            install paths (Documents/Megascans Library/, Bridge settings, env
            vars, Bridge API folder).
        timeout_seconds: HTTP timeout for Bridge API probe (default 2s).

    Returns:
        Dict with keys:
            api               -> result of _probe_quixel_bridge_api
            detected_roots    -> list[str] paths that exist
            scanned_roots     -> list[dict] per-root scan_quixel_library_root
            summary           -> {detected_root_count, total_assets,
                                  category_counts, bridge_api_reachable}
    """
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
            "category_counts": dict(
                sorted(combined_categories.items(), key=lambda item: (-item[1], item[0]))
            ),
            "bridge_api_reachable": bool(api_report.get("reachable")),
        },
    }


def render_local_quixel_library_map_markdown(report: dict[str, Any]) -> str:
    """Render a build_local_quixel_library_map result as markdown."""
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
        lines.append(
            f"- API zip folders: `{', '.join(str(item) for item in api['zip_folders'])}`"
        )
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
            lines.append(
                f"- Categories: `{', '.join(f'{name}:{count}' for name, count in counts.items())}`"
            )
        samples = item.get("sample_assets") or []
        if samples:
            lines.append("- Samples:")
            for sample in samples[:8]:
                lines.append(
                    f"  - `{sample.get('category', 'unknown')}` | `{sample.get('name', '')}`"
                )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


__all__ = [
    "build_local_quixel_library_map",
    "render_local_quixel_library_map_markdown",
    "scan_quixel_library_root",
]
