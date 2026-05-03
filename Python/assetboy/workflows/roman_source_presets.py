from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from typing import Any

from assetboy.library.files import read_json, write_json, write_text
from assetboy.library.paths import generated_output_root
from assetboy.providers.browser_automation import BrowserRuntime, emit_browser_automation_job
from assetboy.providers.direct_url import DirectUrlQueueRequest, write_queue_rows
from assetboy.workflows.roman_launchers import emit_roman_launcher_manifest
from assetboy.workflows.roman_first_playable import roman_first_playable_pack_ids


_DIRECT_DOWNLOAD_SUFFIXES = {
    ".zip",
    ".7z",
    ".rar",
    ".fbx",
    ".blend",
    ".obj",
    ".glb",
    ".gltf",
    ".png",
    ".jpg",
    ".jpeg",
    ".wav",
    ".mp3",
    ".unitypackage",
}

_PACK_MIXAMO_PRESETS: dict[str, tuple[str, ...]] = {
    "RA_PACK_ANM_COMBAT_SLICE_01": (
        "walk run sprint idle",
        "hit react stumble death",
        "javelin throw attack",
        "sling throw attack",
        "sword shield slash",
        "trap react knockback",
    ),
}

_HELPER_PACK_PRESETS: dict[str, dict[str, Any]] = {
    "makehuman": {
        "pack_id": "RA_PACK_CHR_MAKEHUMAN_BASELINE_01",
        "source_adapter": "makehuman_direct",
        "search_terms": (),
    },
    "mixamo_baseline": {
        "pack_id": "RA_PACK_ANM_MIXAMO_BASELINE_01",
        "source_adapter": "mixamo_animations",
        "search_terms": (
            "walk run sprint idle",
            "sword attack combat idle hit react",
        ),
    },
}


@dataclass(frozen=True)
class RomanSourcePresetArtifacts:
    output_dir: Path
    manifest_path: Path
    summary_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "manifest_path": str(self.manifest_path),
            "summary_path": str(self.summary_path),
        }


def _slugify(text: str) -> str:
    cleaned = "".join(character.lower() if character.isalnum() else "_" for character in str(text or ""))
    parts = [part for part in cleaned.split("_") if part]
    return "_".join(parts) or "source"


def _is_direct_download_url(url: str) -> bool:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix in _DIRECT_DOWNLOAD_SUFFIXES


def _entry_notes(entry: dict[str, Any], *, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    notes: list[str] = []
    launcher_name = str(entry.get("name", "")).strip()
    checklist_path = str(entry.get("checklist_path", "")).strip()
    launcher_path = str(entry.get("path", "")).strip()
    if launcher_name:
        notes.append(f"Imported from Roman launcher {launcher_name}.")
    if checklist_path:
        notes.append(f"Checklist: {checklist_path}")
    if launcher_path:
        notes.append(f"Original launcher path: {launcher_path}")
    notes.extend(item for item in extra if item)
    return tuple(notes)


def _emit_direct_url_queue(
    *,
    root_dir: Path,
    pack_id: str,
    game_scope: str,
    source_adapter: str,
    source_urls: list[str],
    notes: tuple[str, ...],
) -> Path:
    requests = [
        DirectUrlQueueRequest(
            pack_id=pack_id,
            game_scope=game_scope,
            url=url,
            source_adapter=source_adapter,
            source_page_url=url,
            notes=" ".join(notes),
        )
        for url in source_urls
    ]
    rows = [request.to_row(sequence=index) for index, request in enumerate(requests)]
    return write_queue_rows(rows, path=root_dir / "direct_url_queue.csv")


def _emit_browser_jobs(
    *,
    root_dir: Path,
    pack_id: str,
    game_scope: str,
    source_adapter: str,
    source_urls: list[str],
    search_terms: tuple[str, ...],
    login_required: bool,
    notes: tuple[str, ...],
) -> list[Path]:
    job_dirs: list[Path] = []
    for index, url in enumerate(source_urls, start=1):
        host = _slugify(urlparse(url).netloc)
        artifacts = emit_browser_automation_job(
            source_adapter=source_adapter,
            runtime=BrowserRuntime.PLAYWRIGHT_MCP,
            pack_id=pack_id,
            game_scope=game_scope,
            source_url=url,
            search_terms=search_terms,
            login_required=login_required,
            output_dir=root_dir / "browser_jobs" / f"{index:02d}_{host}",
            notes=notes,
        )
        job_dirs.append(artifacts.output_dir)
    return job_dirs


def _emit_pack_preset(root_dir: Path, pack_preset: dict[str, Any]) -> dict[str, Any]:
    pack_id = str(pack_preset.get("pack_id", "")).strip()
    game_scope = str(pack_preset.get("game_scope", "roman_arena")).strip() or "roman_arena"
    group = str(pack_preset.get("group", "")).strip()
    pack_dir = root_dir / "packs" / pack_id
    source_manifest = pack_preset.get("source_manifest") or {}
    source_urls = [str(url).strip() for url in source_manifest.get("source_urls", []) if str(url).strip()]
    result: dict[str, Any] = {
        "pack_id": pack_id,
        "group": group,
        "status": "reference_only",
        "direct_url_queue": "",
        "browser_job_dirs": [],
        "notes": [],
    }

    if source_urls:
        direct_urls = [url for url in source_urls if _is_direct_download_url(url)]
        browser_urls = [url for url in source_urls if not _is_direct_download_url(url)]
        source_notes = _entry_notes(
            source_manifest,
            extra=(f"Imported Roman pack group: {group or 'unknown'}.",),
        )
        if direct_urls:
            queue_path = _emit_direct_url_queue(
                root_dir=pack_dir,
                pack_id=pack_id,
                game_scope=game_scope,
                source_adapter="roman_launcher_import",
                source_urls=direct_urls,
                notes=source_notes,
            )
            result["direct_url_queue"] = str(queue_path)
        if browser_urls:
            browser_job_dirs = _emit_browser_jobs(
                root_dir=pack_dir,
                pack_id=pack_id,
                game_scope=game_scope,
                source_adapter="roman_manual_source",
                source_urls=browser_urls,
                search_terms=(group.replace("_", " ") or pack_id,),
                login_required=False,
                notes=source_notes,
            )
            result["browser_job_dirs"] = [str(path) for path in browser_job_dirs]
        result["status"] = "emitted"
        result["notes"] = list(source_notes)
        return result

    mixamo_search_terms = _PACK_MIXAMO_PRESETS.get(pack_id)
    if mixamo_search_terms:
        mixamo_notes = _entry_notes(
            pack_preset.get("asset_launcher") or {},
            extra=("Mapped to first-class Mixamo animation preset.",),
        )
        browser_job_dirs = _emit_browser_jobs(
            root_dir=pack_dir,
            pack_id=pack_id,
            game_scope=game_scope,
            source_adapter="mixamo_animations",
            source_urls=["https://www.mixamo.com/"],
            search_terms=mixamo_search_terms,
            login_required=True,
            notes=mixamo_notes,
        )
        result["status"] = "emitted"
        result["browser_job_dirs"] = [str(path) for path in browser_job_dirs]
        result["notes"] = list(mixamo_notes)
        return result

    result["notes"] = ["No source URLs were imported for this pack preset."]
    return result


def _emit_global_helper(root_dir: Path, helper_entry: dict[str, Any]) -> dict[str, Any]:
    group = str(helper_entry.get("group", "")).strip()
    game_scope = str(helper_entry.get("game_scope", "roman_arena")).strip() or "roman_arena"
    source_urls = [str(url).strip() for url in helper_entry.get("source_urls", []) if str(url).strip()]
    helper_dir = root_dir / "helpers" / _slugify(group or helper_entry.get("name", "helper"))
    result: dict[str, Any] = {
        "name": str(helper_entry.get("name", "")).strip(),
        "group": group,
        "status": "reference_only",
        "pack_id": "",
        "direct_url_queue": "",
        "browser_job_dirs": [],
        "notes": [],
    }

    preset = _HELPER_PACK_PRESETS.get(group)
    if not preset or not source_urls:
        result["notes"] = ["Global helper kept as reference only."]
        return result

    pack_id = str(preset["pack_id"])
    source_adapter = str(preset["source_adapter"])
    helper_notes = _entry_notes(helper_entry, extra=("Derived from Roman global helper launcher.",))
    direct_urls = [url for url in source_urls if _is_direct_download_url(url)]
    browser_urls = [url for url in source_urls if not _is_direct_download_url(url)]

    if direct_urls:
        queue_path = _emit_direct_url_queue(
            root_dir=helper_dir,
            pack_id=pack_id,
            game_scope=game_scope,
            source_adapter=source_adapter,
            source_urls=direct_urls,
            notes=helper_notes,
        )
        result["direct_url_queue"] = str(queue_path)

    if browser_urls:
        browser_job_dirs = _emit_browser_jobs(
            root_dir=helper_dir,
            pack_id=pack_id,
            game_scope=game_scope,
            source_adapter=source_adapter,
            source_urls=browser_urls,
            search_terms=tuple(str(item) for item in preset.get("search_terms", ()) if str(item).strip()),
            login_required=source_adapter.startswith("mixamo"),
            notes=helper_notes,
        )
        result["browser_job_dirs"] = [str(path) for path in browser_job_dirs]

    result["status"] = "emitted"
    result["pack_id"] = pack_id
    result["notes"] = list(helper_notes)
    return result


def _build_summary(
    *,
    game_scope: str,
    pack_results: list[dict[str, Any]],
    helper_results: list[dict[str, Any]],
) -> str:
    emitted_pack_count = sum(1 for item in pack_results if item.get("status") == "emitted")
    emitted_helper_count = sum(1 for item in helper_results if item.get("status") == "emitted")
    lines = [
        "# Roman Source Presets",
        "",
        f"- Game scope: `{game_scope}`",
        f"- Pack presets emitted: `{emitted_pack_count}` of `{len(pack_results)}`",
        f"- Global helper presets emitted: `{emitted_helper_count}` of `{len(helper_results)}`",
        "",
        "## Pack Presets",
    ]
    for item in pack_results:
        lines.append(f"- `{item['pack_id']}` -> `{item['status']}`")
        if item.get("direct_url_queue"):
            lines.append(f"- direct_url queue: `{item['direct_url_queue']}`")
        for job_dir in item.get("browser_job_dirs", []):
            lines.append(f"- browser job: `{job_dir}`")
    lines.extend(["", "## Global Helpers"])
    if not helper_results:
        lines.append("- None")
    else:
        for item in helper_results:
            label = item.get("pack_id") or item.get("name") or "helper"
            lines.append(f"- `{label}` -> `{item['status']}`")
            if item.get("direct_url_queue"):
                lines.append(f"- direct_url queue: `{item['direct_url_queue']}`")
            for job_dir in item.get("browser_job_dirs", []):
                lines.append(f"- browser job: `{job_dir}`")
    return "\n".join(lines) + "\n"


def emit_roman_source_presets(
    *,
    game_scope: str = "roman_arena",
    output_dir: str | Path | None = None,
    launcher_manifest_path: str | Path | None = None,
) -> RomanSourcePresetArtifacts:
    manifest_path = Path(launcher_manifest_path) if launcher_manifest_path is not None else None
    if manifest_path is None:
        manifest_path = emit_roman_launcher_manifest(game_scope=game_scope).manifest_path
    launcher_manifest = read_json(manifest_path)

    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "roman_source_presets" / game_scope
    )

    allowed_pack_ids = set(roman_first_playable_pack_ids())
    pack_results = [
        _emit_pack_preset(root_dir, pack_preset)
        for pack_preset in launcher_manifest.get("pack_presets", [])
        if str(pack_preset.get("pack_id", "")).strip() in allowed_pack_ids
    ]
    helper_results = [
        _emit_global_helper(root_dir, helper_entry)
        for helper_entry in launcher_manifest.get("global_helpers", [])
    ]

    manifest_payload = {
        "schema_version": "assetboy.roman_source_presets.v1",
        "game_scope": game_scope,
        "launcher_manifest_path": str(Path(manifest_path).resolve()),
        "pack_results": pack_results,
        "helper_results": helper_results,
    }
    output_manifest_path = write_json(root_dir / "roman_source_presets.json", manifest_payload)
    summary_path = write_text(
        root_dir / "README.md",
        _build_summary(
            game_scope=game_scope,
            pack_results=pack_results,
            helper_results=helper_results,
        ),
    )
    return RomanSourcePresetArtifacts(
        output_dir=root_dir,
        manifest_path=output_manifest_path,
        summary_path=summary_path,
    )
