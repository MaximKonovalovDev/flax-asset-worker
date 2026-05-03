from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root
from assetboy.providers.browser_automation import BrowserRuntime, emit_browser_automation_job
from assetboy.providers.unity_runner import emit_unity_export_runner


def _split_markdown_row(line: str) -> list[str]:
    placeholder = "__ASSETBOY_ESCAPED_PIPE__"
    safe = line.replace(r"\|", placeholder)
    parts = [part.strip().replace(placeholder, "|") for part in safe.strip().strip("|").split("|")]
    return parts


def _extract_unity_asset_id(url: str) -> str:
    match = re.search(r"-([0-9]+)(?:[/?#]|$)", url.strip())
    if match:
        return match.group(1)
    return ""


def _normalize_token(value: str, *, limit: int = 28) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().upper())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return "ITEM"
    return cleaned[:limit].strip("_") or "ITEM"


def _classify_unity_asset(*, section: str, subsection: str, title: str, url: str) -> tuple[str, bool, str]:
    section_lower = section.lower()
    subsection_lower = subsection.lower()
    title_lower = title.lower()
    url_lower = url.lower()

    audio_markers = (
        "/audio/",
        "sound-fx",
        "music",
        "ambient",
        "ui sounds",
        "nature sounds",
    )
    character_markers = (
        "/3d/characters/",
        "character",
        "humanoid",
        "human",
        "warrior",
        "unity-chan",
        "uma",
    )
    animation_markers = (
        "/3d/animations/",
        "animation",
        "mecanim",
        "melee",
        "death",
        "attack",
        "spear",
    )
    environment_markers = (
        "/3d/environments/",
        "environment",
        "terrain",
        "forest",
        "island",
        "mountain",
        "ruins",
        "temple",
        "courtyard",
        "cabin",
        "archviz",
        "hdrp demo scene",
        "time ghost",
        "heretic",
    )
    tool_markers = (
        "/tools/",
        "/add-ons/",
        "toolkit",
        "serializer",
        "inspector",
        "pathfinding",
        "dialogue system",
        "save",
        "multiplayer session",
        "matchmaker",
        "player account",
        "leaderboards",
        "accessibility",
        "utility",
    )

    if any(marker in url_lower or marker in title_lower or marker in subsection_lower or marker in section_lower for marker in tool_markers):
        return "tooling", False, "prop"
    if any(marker in url_lower or marker in title_lower or marker in subsection_lower for marker in audio_markers):
        return "audio", True, "prop"
    if any(marker in url_lower or marker in title_lower or marker in subsection_lower for marker in animation_markers):
        return "animation", True, "character"
    if any(marker in url_lower or marker in title_lower or marker in subsection_lower for marker in character_markers):
        return "character", True, "character"
    if any(marker in url_lower or marker in title_lower or marker in subsection_lower for marker in environment_markers):
        return "environment", True, "architecture"
    if "/templates/" in url_lower or "/tutorial-projects/" in url_lower:
        likely_art = any(
            token in title_lower or token in subsection_lower
            for token in ("environment", "character", "animation", "courtyard", "time ghost", "heretic", "terrain")
        )
        if likely_art:
            return "environment", True, "architecture"
        return "template", False, "prop"
    if "/3d/" in url_lower:
        return "prop", True, "prop"
    return "misc", False, "prop"


def _pack_prefix(category: str) -> str:
    mapping = {
        "audio": "SHARED_UNITY_AUD",
        "animation": "SHARED_UNITY_ANM",
        "character": "SHARED_UNITY_CHR",
        "environment": "SHARED_UNITY_ENV",
        "prop": "SHARED_UNITY_PROP",
        "tooling": "SHARED_UNITY_TOOL",
        "template": "SHARED_UNITY_TEMPLATE",
        "misc": "SHARED_UNITY_MISC",
    }
    return mapping.get(category, "SHARED_UNITY_MISC")


def _project_name_from_pack_id(pack_id: str) -> str:
    token = _normalize_token(pack_id, limit=48).title().replace("_", "")
    return token or "AssetBoyUnityProject"


def parse_unity_download_sheet(source_path: str | Path) -> list[dict[str, Any]]:
    path = Path(source_path)
    section = ""
    subsection = ""
    raw_entries: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    index = 0

    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if stripped.startswith("## "):
            section = stripped[3:].strip()
            subsection = ""
            index += 1
            continue
        if stripped.startswith("### "):
            subsection = stripped[4:].strip()
            index += 1
            continue
        if not stripped.startswith("|"):
            index += 1
            continue

        table_lines: list[str] = []
        while index < len(lines) and lines[index].strip().startswith("|"):
            table_lines.append(lines[index].strip())
            index += 1
        if len(table_lines) < 2:
            continue

        header = _split_markdown_row(table_lines[0])
        if header[:3] != ["Name", "Type", "URL"]:
            continue

        for row in table_lines[2:]:
            columns = _split_markdown_row(row)
            if len(columns) < 3:
                continue
            name, entry_type, url = columns[:3]
            if entry_type != "Asset Store":
                continue
            raw_entries.append(
                {
                    "name": name,
                    "type": entry_type,
                    "url": url,
                    "section": section,
                    "subsection": subsection,
                }
            )

    deduped: dict[str, dict[str, Any]] = {}
    for entry in raw_entries:
        url = str(entry["url"]).strip()
        title = str(entry["name"]).strip()
        category, exportable, asset_kind = _classify_unity_asset(
            section=str(entry["section"]),
            subsection=str(entry["subsection"]),
            title=title,
            url=url,
        )
        asset_id = _extract_unity_asset_id(url)
        prefix = _pack_prefix(category)
        pack_id = f"{prefix}_{_normalize_token(title)}"
        if asset_id:
            pack_id = f"{pack_id}_{asset_id}"

        current = deduped.get(url)
        entry_payload = {
            "name": title,
            "type": "Asset Store",
            "url": url,
            "asset_id": asset_id,
            "category": category,
            "exportable": exportable,
            "asset_kind": asset_kind,
            "pack_id": pack_id,
            "best_first_wave": str(entry["section"]).strip().lower() == "best first wave",
            "sections": [str(entry["section"]).strip()] if str(entry["section"]).strip() else [],
            "subsections": [str(entry["subsection"]).strip()] if str(entry["subsection"]).strip() else [],
        }
        if current is None:
            deduped[url] = entry_payload
            continue
        if entry_payload["best_first_wave"]:
            current["best_first_wave"] = True
        for key in ("sections", "subsections"):
            existing = list(current.get(key, []))
            for value in entry_payload[key]:
                if value and value not in existing:
                    existing.append(value)
            current[key] = existing

    items = list(deduped.values())
    items.sort(
        key=lambda item: (
            not bool(item.get("best_first_wave")),
            str(item.get("category", "")),
            str(item.get("name", "")).lower(),
        )
    )
    return items


def render_unity_download_wave_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# Unity Download Wave",
        "",
        f"- Source file: `{report.get('source_file', '')}`",
        f"- Asset Store entries: `{summary.get('asset_store_entries', 0)}`",
        f"- Best first wave entries: `{summary.get('best_first_wave_entries', 0)}`",
        f"- Export runner candidates: `{summary.get('export_runner_candidates', 0)}`",
        f"- Browser jobs emitted: `{summary.get('browser_jobs_emitted', 0)}`",
        f"- Unity export runners emitted: `{summary.get('unity_export_runners_emitted', 0)}`",
        "",
        "## Category Counts",
        "",
    ]
    for category, count in (report.get("category_counts") or {}).items():
        lines.append(f"- `{category}`: `{count}`")
    lines.append("")

    for item in report.get("items", []) or []:
        marker = "best-first" if item.get("best_first_wave") else item.get("category", "")
        lines.append(
            f"- {item.get('name', '')} | `{marker}` | exportable=`{str(bool(item.get('exportable'))).lower()}` | `{item.get('url', '')}`"
        )
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def select_unity_download_wave_jobs(
    report: dict[str, Any],
    *,
    best_first_only: bool = False,
    exportable_only: bool = False,
    asset_donor_only: bool = False,
    categories: tuple[str, ...] = (),
    pack_ids: tuple[str, ...] = (),
    limit: int | None = None,
) -> list[dict[str, Any]]:
    browser_jobs = {
        str(job.get("pack_id", "")): dict(job)
        for job in (report.get("browser_jobs") or [])
        if isinstance(job, dict)
    }
    category_filter = {str(value).strip().lower() for value in categories if str(value).strip()}
    pack_filter = {str(value).strip() for value in pack_ids if str(value).strip()}
    donor_categories = {"animation", "character", "environment", "audio", "prop"}
    selected: list[dict[str, Any]] = []
    for item in report.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        pack_id = str(item.get("pack_id", "")).strip()
        if not pack_id:
            continue
        if best_first_only and not bool(item.get("best_first_wave")):
            continue
        if exportable_only and not bool(item.get("exportable")):
            continue
        if asset_donor_only:
            item_category = str(item.get("category", "")).strip().lower()
            if not bool(item.get("exportable")):
                continue
            if item_category not in donor_categories:
                continue
        if category_filter and str(item.get("category", "")).strip().lower() not in category_filter:
            continue
        if pack_filter and pack_id not in pack_filter:
            continue
        browser_job = browser_jobs.get(pack_id)
        if not browser_job:
            continue
        merged = dict(item)
        merged.update(browser_job)
        selected.append(merged)
        if limit is not None and limit > 0 and len(selected) >= limit:
            break
    return selected


def render_unity_claim_wave_markdown(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# Unity Claim Wave",
        "",
        f"- Wave json: `{report.get('wave_json', '')}`",
        f"- Total selected: `{summary.get('selected_jobs', 0)}`",
        f"- Processed: `{summary.get('processed_jobs', 0)}`",
        f"- Executed: `{summary.get('executed', 0)}`",
        f"- Pending manual: `{summary.get('pending_manual', 0)}`",
        f"- Claimed or already owned: `{summary.get('claimed_or_owned', 0)}`",
        f"- Interactive required: `{summary.get('interactive_required', 0)}`",
        f"- Failed: `{summary.get('failed', 0)}`",
        "",
    ]
    project_ingest_wave = report.get("project_ingest_wave")
    if isinstance(project_ingest_wave, dict) and project_ingest_wave:
        lines.extend(
            [
                "## Follow-up Ingest Wave",
                "",
                f"- Project path: `{project_ingest_wave.get('project_path', '')}`",
                f"- Ingest json: `{project_ingest_wave.get('json_path', '')}`",
                f"- Ingest markdown: `{project_ingest_wave.get('md_path', '')}`",
                f"- Selected jobs: `{project_ingest_wave.get('selected_jobs', 0)}`",
                "",
            ]
        )
    for item in report.get("results", []) or []:
        step = {}
        steps = item.get("steps", []) or []
        if isinstance(steps, list) and steps and isinstance(steps[0], dict):
            step = dict(steps[0])
        post_status = str(step.get("status", item.get("status", ""))).strip()
        prepare_state = str(step.get("prepare_pack", {}).get("current_state", "")).strip() if isinstance(step.get("prepare_pack"), dict) else ""
        lines.append(
            "- "
            + f"{item.get('name', '')} | `{item.get('pack_id', '')}` | "
            + f"mode=`{item.get('execution_mode', '')}` | status=`{item.get('status', '')}` | step=`{post_status}` | "
            + f"claimed=`{str(bool(item.get('claimed_or_owned'))).lower()}` | "
            + (f"prepare=`{prepare_state}` | " if prepare_state else "")
            + f"`{item.get('url', '')}`"
        )
    lines.append("")
    return "\n".join(lines)


def emit_unity_download_wave(
    *,
    source_file: str | Path,
    output_dir: str | Path | None = None,
    game_scope: str = "arena_shared",
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    resolved_source = Path(source_file)
    resolved_output_dir = Path(output_dir) if output_dir is not None else generated_output_root() / "unity_download_wave"
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    resolved_project_root = Path(project_root) if project_root is not None else Path.home() / "Documents" / "Unity AssetBoy"
    resolved_project_root.mkdir(parents=True, exist_ok=True)

    items = parse_unity_download_sheet(resolved_source)
    category_counts = Counter(str(item.get("category", "misc")) for item in items)
    browser_jobs: list[dict[str, str]] = []
    unity_export_jobs: list[dict[str, str]] = []

    for item in items:
        pack_id = str(item["pack_id"])
        item_dir = resolved_output_dir / "browser_jobs" / pack_id
        notes = (
            f"Approved from Unity download sheet: {resolved_source.name}",
            f"Sections: {', '.join(item.get('sections', [])) or '-'}",
            f"Subsections: {', '.join(item.get('subsections', [])) or '-'}",
        )
        browser_artifacts = emit_browser_automation_job(
            source_adapter="unity_asset_store",
            runtime=BrowserRuntime.PLAYWRIGHT_MCP,
            pack_id=pack_id,
            game_scope=game_scope,
            source_url=str(item["url"]),
            search_terms=(str(item["name"]),),
            login_required=True,
            output_dir=item_dir,
            notes=notes,
        )
        browser_jobs.append(
            {
                "pack_id": pack_id,
                "name": str(item["name"]),
                "job_output_dir": str(browser_artifacts.output_dir),
                "browser_job_spec": str(browser_artifacts.job_spec_path),
            }
        )
        if not bool(item.get("exportable")):
            continue

        export_dir = resolved_output_dir / "unity_export_runners" / pack_id
        unity_artifacts = emit_unity_export_runner(
            pack_id=pack_id,
            game_scope=game_scope,
            source_url=str(item["url"]),
            license_note="Unity Asset Store package from approved internal download sheet.",
            project_path=resolved_project_root / _project_name_from_pack_id(pack_id),
            package_root="Assets",
            source_package_name=str(item["name"]),
            asset_kind=str(item["asset_kind"]),
            output_dir=export_dir,
            notes=notes,
        )
        unity_export_jobs.append(
            {
                "pack_id": pack_id,
                "name": str(item["name"]),
                "runner_output_dir": str(unity_artifacts.output_dir),
                "runner_job_path": str(unity_artifacts.runner_job_path),
                "launch_command_path": str(unity_artifacts.launch_command_path),
            }
        )

    report = {
        "source_file": str(resolved_source),
        "output_dir": str(resolved_output_dir),
        "project_root": str(resolved_project_root),
        "summary": {
            "asset_store_entries": len(items),
            "best_first_wave_entries": sum(1 for item in items if item.get("best_first_wave")),
            "export_runner_candidates": sum(1 for item in items if item.get("exportable")),
            "browser_jobs_emitted": len(browser_jobs),
            "unity_export_runners_emitted": len(unity_export_jobs),
        },
        "category_counts": dict(sorted(category_counts.items(), key=lambda entry: (-entry[1], entry[0]))),
        "items": items,
        "browser_jobs": browser_jobs,
        "unity_export_jobs": unity_export_jobs,
    }
    write_json(resolved_output_dir / "unity_download_wave.json", report)
    write_text(resolved_output_dir / "unity_download_wave.md", render_unity_download_wave_markdown(report))
    return report
