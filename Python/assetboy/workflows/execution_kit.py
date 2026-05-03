from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root
from assetboy.providers.ai_bridge import AI_PROVIDER_PROFILES, emit_ai_bridge_job
from assetboy.providers.browser_automation import BrowserRuntime, emit_browser_automation_job
from assetboy.providers.direct_url import write_queue_rows
from assetboy.providers.generator import emit_generator_setup, load_colab_profile, profile_ids
from assetboy.workflows.roman_blockers import RomanBlockerPlan, RomanBlockerTask, plan_roman_blockers


BROWSER_SOURCE_URLS: dict[str, str] = {
    "fab": "https://www.fab.com/",
    "mixamo": "https://www.mixamo.com/",
    "mixamo_animations": "https://www.mixamo.com/",
    "museum_page": "https://www.si.edu/openaccess/",
    "unity_asset_store": "https://assetstore.unity.com/",
}

DIRECT_SOURCE_PAGES: dict[tuple[str, str], str] = {
    ("ambientcg", "material"): "https://ambientcg.com/list?category=Material",
    ("mixkit", "music"): "https://mixkit.co/free-stock-music/",
    ("mixkit", "sfx"): "https://mixkit.co/free-sound-effects/",
    ("pixabay_audio", "music"): "https://pixabay.com/music/",
    ("pixabay_audio", "sfx"): "https://pixabay.com/sound-effects/",
    ("freesound_audio", "sfx"): "https://freesound.org/",
    ("opengameart", "music"): "https://opengameart.org/art-search-advanced?keys=music",
    ("opengameart", "sfx"): "https://opengameart.org/art-search-advanced?keys=sfx",
}


@dataclass(frozen=True)
class RomanExecutionKitArtifacts:
    output_dir: Path
    manifest_path: Path
    queue_template_path: Path | None
    summary_path: Path

    def to_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {
            "output_dir": str(self.output_dir),
            "manifest_path": str(self.manifest_path),
            "summary_path": str(self.summary_path),
        }
        if self.queue_template_path is not None:
            payload["queue_template_path"] = str(self.queue_template_path)
        return payload


def _source_page_for_direct_task(task: RomanBlockerTask) -> str:
    return DIRECT_SOURCE_PAGES.get((task.source_adapter, task.asset_category), "")


def _browser_source_url(task: RomanBlockerTask) -> str:
    return BROWSER_SOURCE_URLS.get(task.source_adapter, "")


@lru_cache
def _colab_profile_ids() -> set[str]:
    return set(profile_ids())


@lru_cache
def _colab_profiles_by_adapter() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for profile_id in profile_ids():
        profile = load_colab_profile(profile_id)
        mapping.setdefault(profile.adapter_id, profile.profile_id)
    return mapping


def _resolve_profile_id(adapter_or_profile: str) -> str | None:
    if adapter_or_profile in _colab_profile_ids():
        return adapter_or_profile
    return _colab_profiles_by_adapter().get(adapter_or_profile)


def _emit_direct_queue_templates(plan: RomanBlockerPlan, root_dir: Path) -> Path | None:
    rows: list[dict[str, str]] = []
    for task in plan.blocking_tasks:
        if task.lane.value != "direct_url":
            continue
        templates = list(task.lane_details.get("queue_templates", []))
        for row in templates:
            enriched = dict(row)
            enriched["source_page_url"] = _source_page_for_direct_task(task)
            rows.append(enriched)
    if not rows:
        return None
    return write_queue_rows(rows, path=root_dir / "direct_url_queue_templates.csv")


def _emit_task_artifacts(
    task: RomanBlockerTask,
    *,
    game_scope: str,
    root_dir: Path,
    browser_runtime: BrowserRuntime,
) -> dict[str, object]:
    fallbacks: list[dict[str, object]] = []
    if task.lane.value == "manual_browser":
        runtime_adapter = str(task.lane_details.get("source_adapter", task.source_adapter))
        artifacts = emit_browser_automation_job(
            source_adapter=runtime_adapter,
            runtime=browser_runtime,
            pack_id=task.pack_id,
            game_scope=game_scope,
            source_url=str(task.lane_details.get("source_url", _browser_source_url(task))),
            search_terms=tuple(task.lane_details.get("search_terms", [])),
            login_required=bool(task.lane_details.get("login_required", True)),
            output_dir=root_dir / "browser" / task.pack_id,
            notes=tuple(task.notes),
        )
        if task.fallback_adapters:
            for adapter_id in task.fallback_adapters:
                fallback_artifacts = emit_browser_automation_job(
                    source_adapter=adapter_id,
                    runtime=browser_runtime,
                    pack_id=task.pack_id,
                    game_scope=game_scope,
                    source_url=BROWSER_SOURCE_URLS.get(adapter_id, ""),
                    search_terms=tuple(task.lane_details.get("search_terms", [])),
                    login_required=adapter_id in {"fab", "unity_asset_store", "mixamo", "mixamo_animations"},
                    output_dir=root_dir / "browser" / task.pack_id / "fallback" / adapter_id,
                    notes=tuple(task.notes),
                )
                fallbacks.append(
                    {
                        "source_adapter": adapter_id,
                        "artifact_dir": str(fallback_artifacts.output_dir),
                        "job_spec": str(fallback_artifacts.job_spec_path),
                        "download_target": str(fallback_artifacts.download_target_path),
                    }
                )
        entry: dict[str, object] = {
            "pack_id": task.pack_id,
            "slot": task.slot,
            "lane": task.lane.value,
            "bridge_id": task.bridge_id,
            "audit_status": task.audit_status,
            "maturity": task.user_maturity_label,
            "artifact_dir": str(artifacts.output_dir),
            "job_spec": str(artifacts.job_spec_path),
            "download_target": str(artifacts.download_target_path),
        }
        if fallbacks:
            entry["fallbacks"] = fallbacks
        return entry

    if task.lane.value == "generator":
        if task.source_adapter in AI_PROVIDER_PROFILES:
            artifacts = emit_ai_bridge_job(
                provider_id=task.source_adapter,
                pack_id=task.pack_id,
                game_scope=game_scope,
                output_dir=root_dir / "generator" / task.pack_id,
                notes=tuple(task.notes),
            )
            if task.fallback_adapters:
                for adapter_id in task.fallback_adapters:
                    if adapter_id in AI_PROVIDER_PROFILES:
                        fallback_artifacts = emit_ai_bridge_job(
                            provider_id=adapter_id,
                            pack_id=task.pack_id,
                            game_scope=game_scope,
                            output_dir=root_dir / "generator" / task.pack_id / "fallback" / adapter_id,
                            notes=tuple(task.notes),
                        )
                        fallbacks.append(
                            {
                                "provider_id": adapter_id,
                                "artifact_dir": str(fallback_artifacts.output_dir),
                                "job_spec": str(fallback_artifacts.job_spec_path),
                                "payload_target": str(fallback_artifacts.payload_target_path),
                            }
                        )
                        continue
                    profile_id = _resolve_profile_id(adapter_id)
                    if profile_id is None:
                        fallbacks.append(
                            {
                                "fallback_id": adapter_id,
                                "reason": "no_colab_profile_match",
                            }
                        )
                        continue
                    fallback_artifacts = emit_generator_setup(
                        profile_id=profile_id,
                        pack_id=task.pack_id,
                        game_scope=game_scope,
                        output_dir=root_dir / "generator" / task.pack_id / "fallback" / profile_id,
                        animated=task.asset_category == "animation",
                    )
                    fallbacks.append(
                        {
                            "profile_id": profile_id,
                            "artifact_dir": str(fallback_artifacts.output_dir),
                            "prompt_batch": str(fallback_artifacts.prompt_batch_path),
                            "payload_target": str(fallback_artifacts.payload_target_path),
                        }
                    )
            entry = {
                "pack_id": task.pack_id,
                "slot": task.slot,
                "lane": task.lane.value,
                "bridge_id": task.bridge_id,
                "audit_status": task.audit_status,
                "maturity": task.user_maturity_label,
                "artifact_dir": str(artifacts.output_dir),
                "job_spec": str(artifacts.job_spec_path),
                "payload_target": str(artifacts.payload_target_path),
            }
            if fallbacks:
                entry["fallbacks"] = fallbacks
            return entry

        artifacts = emit_generator_setup(
            profile_id=str(task.lane_details["profile_id"]),
            pack_id=task.pack_id,
            game_scope=game_scope,
            output_dir=root_dir / "generator" / task.pack_id,
            animated=task.asset_category == "animation",
        )
        if task.fallback_adapters:
            for adapter_id in task.fallback_adapters:
                profile_id = _resolve_profile_id(adapter_id)
                if profile_id is None:
                    fallbacks.append(
                        {
                            "fallback_id": adapter_id,
                            "reason": "no_colab_profile_match",
                        }
                    )
                    continue
                fallback_artifacts = emit_generator_setup(
                    profile_id=profile_id,
                    pack_id=task.pack_id,
                    game_scope=game_scope,
                    output_dir=root_dir / "generator" / task.pack_id / "fallback" / profile_id,
                    animated=task.asset_category == "animation",
                )
                fallbacks.append(
                    {
                        "profile_id": profile_id,
                        "artifact_dir": str(fallback_artifacts.output_dir),
                        "prompt_batch": str(fallback_artifacts.prompt_batch_path),
                        "payload_target": str(fallback_artifacts.payload_target_path),
                    }
                )
        entry = {
            "pack_id": task.pack_id,
            "slot": task.slot,
            "lane": task.lane.value,
            "bridge_id": task.bridge_id,
            "audit_status": task.audit_status,
            "maturity": task.user_maturity_label,
            "artifact_dir": str(artifacts.output_dir),
            "prompt_batch": str(artifacts.prompt_batch_path),
            "payload_target": str(artifacts.payload_target_path),
        }
        if fallbacks:
            entry["fallbacks"] = fallbacks
        return entry

    return {
        "pack_id": task.pack_id,
        "slot": task.slot,
        "lane": task.lane.value,
        "bridge_id": task.bridge_id,
        "audit_status": task.audit_status,
        "maturity": task.user_maturity_label,
        "queue_target": task.acquisition_target,
    }


def _build_summary(plan: RomanBlockerPlan, queue_template_path: Path | None, task_entries: list[dict[str, object]]) -> str:
    lines = [
        "# Roman Execution Kit",
        "",
        f"- Game scope: `{plan.game_scope}`",
        f"- Blocking packs: `{len(plan.blocking_tasks)}`",
        f"- Ready reviewed packs: `{len(plan.ready_tasks)}`",
    ]
    if queue_template_path is not None:
        lines.append(f"- Direct URL queue templates: `{queue_template_path}`")
    lines.extend(["", "## Tasks"])
    for entry in task_entries:
        line = (
            f"- `{entry['pack_id']}` -> `{entry['bridge_id']}` on `{entry['lane']}` "
            f"status=`{entry['audit_status']}` maturity=`{entry['maturity']}`"
        )
        if "artifact_dir" in entry:
            line += f" at `{entry['artifact_dir']}`"
        lines.append(line)
        fallbacks = entry.get("fallbacks", [])
        if fallbacks:
            fallback_ids: list[str] = []
            for fallback in fallbacks:
                if "provider_id" in fallback:
                    fallback_ids.append(str(fallback["provider_id"]))
                elif "profile_id" in fallback:
                    fallback_ids.append(str(fallback["profile_id"]))
                elif "source_adapter" in fallback:
                    fallback_ids.append(str(fallback["source_adapter"]))
                elif "fallback_id" in fallback:
                    fallback_ids.append(str(fallback["fallback_id"]))
            if fallback_ids:
                lines.append(f"- Fallback options for `{entry['pack_id']}`: `{', '.join(fallback_ids)}`")
    return "\n".join(lines) + "\n"


def emit_roman_execution_kit(
    *,
    gate_path: str | Path,
    catalog_path: str | Path,
    output_dir: str | Path | None = None,
    browser_runtime: BrowserRuntime | str = BrowserRuntime.PLAYWRIGHT_MCP,
) -> RomanExecutionKitArtifacts:
    plan = plan_roman_blockers(gate_path, catalog_path)
    runtime = BrowserRuntime(browser_runtime)
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "roman_execution" / plan.game_scope
    )
    queue_template_path = _emit_direct_queue_templates(plan, root_dir)
    task_entries = [
        _emit_task_artifacts(task, game_scope=plan.game_scope, root_dir=root_dir, browser_runtime=runtime)
        for task in plan.blocking_tasks
    ]
    manifest = {
        "schema_version": "assetboy.roman_execution_kit.v1",
        "game_scope": plan.game_scope,
        "gate_report_path": str(plan.gate_report.path),
        "catalog_path": str(plan.catalog.path),
        "browser_runtime": runtime.value,
        "queue_template_path": str(queue_template_path) if queue_template_path is not None else "",
        "roman_pack_count": len(plan.tasks),
        "blocking_pack_count": len(plan.blocking_tasks),
        "ready_reviewed_pack_count": len(plan.ready_tasks),
        "pack_audits": [task.to_dict() for task in plan.tasks],
        "tasks": task_entries,
    }
    manifest_path = write_json(root_dir / "execution_manifest.json", manifest)
    summary_path = write_text(root_dir / "README.md", _build_summary(plan, queue_template_path, task_entries))
    return RomanExecutionKitArtifacts(
        output_dir=root_dir,
        manifest_path=manifest_path,
        queue_template_path=queue_template_path,
        summary_path=summary_path,
    )
