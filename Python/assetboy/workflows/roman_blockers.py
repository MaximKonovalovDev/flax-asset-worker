from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from assetboy.cleanup.blender_mcp import build_cleanup_plan
from assetboy.library.files import write_json, write_text
from assetboy.library.paths import (
    download_queue_csv,
    publish_payload_dir,
    roman_blocker_summary_path,
    roman_blocker_task_path,
)
from assetboy.library.shared_packs import SHARED_PACK_FAMILIES
from assetboy.provenance.templates import provenance_requirements_for
from assetboy.providers.direct_url import build_queue_template_rows
from assetboy.providers.lanes import ProviderLane
from assetboy.providers.manual_browser import ManualBrowserSite, SITE_CHECKLISTS, build_manual_browser_request
from assetboy.workflows.catalog import CatalogSummary, load_catalog_summary
from assetboy.workflows.gate_report import GateReport, load_gate_report
from assetboy.workflows.roman_first_playable import (
    RomanFirstPlayableSpec,
    RomanPackAudit,
    audit_roman_first_playable,
    roman_first_playable_specs,
)


@dataclass(frozen=True)
class RomanBlockerTask:
    pack_id: str
    slot: str
    roman_category: str
    priority: str
    asset_category: str
    bridge_id: str
    lane: ProviderLane
    source_adapter: str
    source_strategy: str
    fallback_adapters: tuple[str, ...]
    provenance_requirements: tuple[str, ...]
    acquisition_target: str
    payload_target: str
    shared_pack_families: tuple[str, ...]
    notes: tuple[str, ...]
    lane_details: dict[str, object]
    expected_contents: tuple[str, ...]
    matured_quality_lane: str
    generator_lane: str
    blender_required: bool
    output_formats: tuple[str, ...]
    extra_sidecars: tuple[str, ...]
    flax_intended_use: str
    user_maturity_label: str
    audit_status: str
    ready_for_flax_packet: bool
    imported_into_flax: bool
    payload_files: tuple[str, ...]
    mock_files: tuple[str, ...]
    audit_findings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "pack_id": self.pack_id,
            "slot": self.slot,
            "roman_category": self.roman_category,
            "priority": self.priority,
            "asset_category": self.asset_category,
            "bridge_id": self.bridge_id,
            "lane": self.lane.value,
            "source_adapter": self.source_adapter,
            "source_strategy": self.source_strategy,
            "fallback_adapters": list(self.fallback_adapters),
            "provenance_requirements": list(self.provenance_requirements),
            "acquisition_target": self.acquisition_target,
            "payload_target": self.payload_target,
            "shared_pack_families": list(self.shared_pack_families),
            "notes": list(self.notes),
            "lane_details": self.lane_details,
            "expected_contents": list(self.expected_contents),
            "matured_quality_lane": self.matured_quality_lane,
            "generator_lane": self.generator_lane,
            "blender_required": self.blender_required,
            "output_formats": list(self.output_formats),
            "extra_sidecars": list(self.extra_sidecars),
            "flax_intended_use": self.flax_intended_use,
            "user_maturity_label": self.user_maturity_label,
            "audit_status": self.audit_status,
            "ready_for_flax_packet": self.ready_for_flax_packet,
            "imported_into_flax": self.imported_into_flax,
            "payload_files": list(self.payload_files),
            "mock_files": list(self.mock_files),
            "audit_findings": list(self.audit_findings),
        }


@dataclass(frozen=True)
class RomanBlockerPlan:
    generated_at_utc: str
    game_scope: str
    recipe: str
    gate_report: GateReport
    catalog: CatalogSummary
    tasks: tuple[RomanBlockerTask, ...]

    @property
    def blocking_tasks(self) -> tuple[RomanBlockerTask, ...]:
        return tuple(task for task in self.tasks if not task.ready_for_flax_packet)

    @property
    def ready_tasks(self) -> tuple[RomanBlockerTask, ...]:
        return tuple(task for task in self.tasks if task.ready_for_flax_packet)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "assetboy.roman_blocker_plan.v2",
            "generated_at_utc": self.generated_at_utc,
            "game_scope": self.game_scope,
            "recipe": self.recipe,
            "gate_report_path": str(self.gate_report.path),
            "catalog_path": str(self.catalog.path),
            "gate_reasons": list(self.gate_report.gate_reasons),
            "gate_unresolved_slots": len(self.gate_report.unresolved_slots),
            "catalog": self.catalog.to_dict(),
            "roman_pack_count": len(self.tasks),
            "blocking_pack_count": len(self.blocking_tasks),
            "ready_reviewed_pack_count": len(self.ready_tasks),
            "tasks": [task.to_dict() for task in self.tasks],
            "shared_pack_families": [family.to_dict() for family in SHARED_PACK_FAMILIES],
        }


def _queue_lane_details(spec: RomanFirstPlayableSpec, *, game_scope: str) -> tuple[dict[str, object], str]:
    lane_details: dict[str, object] = {
        "queue_templates": build_queue_template_rows(
            pack_id=spec.pack_id,
            game_scope=game_scope,
            request_count=spec.request_count,
            source_adapter=spec.source_adapter,
            notes=f"{spec.pack_id}: {spec.source_strategy}",
        ),
        "accepted_output_formats": list(spec.output_formats),
    }
    if spec.blender_required:
        lane_details["cleanup_plan"] = build_cleanup_plan(
            pack_id=spec.pack_id,
            asset_kind=spec.asset_kind,
            source_lane=spec.bootstrap_lane.value,
            animated=spec.animated,
        ).to_dict()
    return lane_details, str(download_queue_csv())


def _manual_lane_details(spec: RomanFirstPlayableSpec, *, game_scope: str) -> tuple[dict[str, object], str]:
    source_adapter = spec.source_adapter
    if source_adapter == "mixamo_animations":
        request = build_manual_browser_request(
            pack_id=spec.pack_id,
            game_scope=game_scope,
            site=ManualBrowserSite.MIXAMO,
            search_terms=spec.search_terms,
            source_strategy=spec.source_strategy,
            notes=("Animation-only Mixamo pass for the Roman combat slice.",),
        )
        lane_details = request.to_dict()
        lane_details["source_adapter"] = "mixamo_animations"
        lane_details["login_required"] = True
    else:
        request = build_manual_browser_request(
            pack_id=spec.pack_id,
            game_scope=game_scope,
            site=ManualBrowserSite(source_adapter),
            search_terms=spec.search_terms,
            source_strategy=spec.source_strategy,
            fallback_sites=tuple(ManualBrowserSite(value) for value in spec.fallback_adapters),
        )
        lane_details = request.to_dict()
        lane_details["login_required"] = source_adapter in {
            ManualBrowserSite.FAB.value,
            ManualBrowserSite.UNITY_ASSET_STORE.value,
            ManualBrowserSite.MIXAMO.value,
        }

    if spec.blender_required:
        lane_details["cleanup_plan"] = build_cleanup_plan(
            pack_id=spec.pack_id,
            asset_kind=spec.asset_kind,
            source_lane=spec.bootstrap_lane.value,
            animated=spec.animated,
        ).to_dict()
    lane_details["expected_contents"] = list(spec.expected_contents)
    lane_details["generator_lane"] = spec.generator_lane
    return lane_details, str(lane_details["destination"])


def _lane_details(spec: RomanFirstPlayableSpec, *, game_scope: str) -> tuple[dict[str, object], str]:
    if spec.bootstrap_lane == ProviderLane.DIRECT_URL:
        return _queue_lane_details(spec, game_scope=game_scope)
    if spec.bootstrap_lane == ProviderLane.MANUAL_BROWSER:
        return _manual_lane_details(spec, game_scope=game_scope)
    lane_details = {
        "accepted_output_formats": list(spec.output_formats),
        "cleanup_plan": build_cleanup_plan(
            pack_id=spec.pack_id,
            asset_kind=spec.asset_kind,
            source_lane=spec.bootstrap_lane.value,
            animated=spec.animated,
        ).to_dict(),
    }
    return lane_details, str(publish_payload_dir(game_scope=game_scope, pack_id=spec.pack_id))


def _task_from_spec(
    spec: RomanFirstPlayableSpec,
    audit: RomanPackAudit,
    *,
    game_scope: str,
) -> RomanBlockerTask:
    effective_source_adapter = audit.actual_source_adapter
    if effective_source_adapter in {"", "unknown", "invalid_json"}:
        effective_source_adapter = spec.source_adapter
    lane_details, acquisition_target = _lane_details(spec, game_scope=game_scope)
    payload_target = str(publish_payload_dir(game_scope=game_scope, pack_id=spec.pack_id))
    notes = tuple(item for item in audit.blocker_reasons if item)
    if not notes and audit.imported_exists:
        notes = ("already imported into Flax proof workspace",)

    return RomanBlockerTask(
        pack_id=spec.pack_id,
        slot=spec.pack_id,
        roman_category=spec.roman_category,
        priority=spec.priority,
        asset_category=spec.asset_category.value,
        bridge_id=spec.bridge_id,
        lane=spec.bootstrap_lane,
        source_adapter=effective_source_adapter,
        source_strategy=spec.source_strategy,
        fallback_adapters=spec.fallback_adapters,
        provenance_requirements=provenance_requirements_for(spec.bootstrap_lane, spec.source_adapter),
        acquisition_target=acquisition_target,
        payload_target=payload_target,
        shared_pack_families=spec.shared_family_tags,
        notes=notes,
        lane_details=lane_details,
        expected_contents=spec.expected_contents,
        matured_quality_lane=spec.matured_quality_lane,
        generator_lane=spec.generator_lane,
        blender_required=spec.blender_required,
        output_formats=spec.output_formats,
        extra_sidecars=spec.extra_sidecars,
        flax_intended_use=spec.flax_intended_use,
        user_maturity_label=audit.maturity_label,
        audit_status=audit.audit_status,
        ready_for_flax_packet=audit.ready_for_flax_packet,
        imported_into_flax=audit.imported_exists,
        payload_files=audit.payload_files,
        mock_files=audit.mock_files,
        audit_findings=audit.blocker_reasons,
    )


def plan_roman_blockers(gate_path: str | Path, catalog_path: str | Path) -> RomanBlockerPlan:
    gate_report = load_gate_report(gate_path)
    catalog = load_catalog_summary(catalog_path)
    game_scope = catalog.scope or "roman_arena"
    audits = {audit.pack_id: audit for audit in audit_roman_first_playable(game_scope=game_scope)}
    tasks = tuple(
        _task_from_spec(spec, audits[spec.pack_id], game_scope=game_scope)
        for spec in roman_first_playable_specs()
    )
    return RomanBlockerPlan(
        generated_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        game_scope=game_scope,
        recipe=gate_report.recipe,
        gate_report=gate_report,
        catalog=catalog,
        tasks=tasks,
    )


def format_planned_blockers(plan: RomanBlockerPlan) -> str:
    lines = [
        f"gate_path={plan.gate_report.path}",
        f"catalog_path={plan.catalog.path}",
        f"game_scope={plan.game_scope}",
        f"catalog_packs={','.join(plan.catalog.pack_ids) if plan.catalog.pack_ids else '<none>'}",
        f"gate_unresolved_slots={len(plan.gate_report.unresolved_slots)}",
        f"roman_pack_count={len(plan.tasks)}",
        f"blocking_packs={len(plan.blocking_tasks)}",
        f"ready_reviewed_packs={len(plan.ready_tasks)}",
    ]
    for task in plan.tasks:
        findings = "; ".join(task.audit_findings[:3]) if task.audit_findings else "no blocking findings"
        lines.append(
            " - "
            f"{task.pack_id}: category={task.roman_category} priority={task.priority} "
            f"status={task.audit_status} maturity={task.user_maturity_label} "
            f"lane={task.lane.value} adapter={task.source_adapter} imported={str(task.imported_into_flax).lower()} "
            f"findings={findings}"
        )
    return "\n".join(lines)


def build_summary_markdown(plan: RomanBlockerPlan) -> str:
    shared_tags: list[str] = []
    for task in plan.tasks:
        for tag in task.shared_pack_families:
            if tag and tag not in shared_tags:
                shared_tags.append(tag)

    lines = [
        "# Roman Blocker Summary",
        "",
        f"- Generated UTC: `{plan.generated_at_utc}`",
        f"- Game scope: `{plan.game_scope}`",
        f"- Gate unresolved slots: `{len(plan.gate_report.unresolved_slots)}`",
        f"- Roman pack count: `{len(plan.tasks)}`",
        f"- Blocking packs: `{len(plan.blocking_tasks)}`",
        f"- Ready reviewed packs: `{len(plan.ready_tasks)}`",
        "",
        "| Pack ID | Category | Priority | Audit | Maturity | Lane | Packet Ready | Imported |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for task in plan.tasks:
        lines.append(
            f"| `{task.pack_id}` | `{task.roman_category}` | `{task.priority}` | `{task.audit_status}` | "
            f"`{task.user_maturity_label}` | `{task.lane.value}` | `{str(task.ready_for_flax_packet).lower()}` | "
            f"`{str(task.imported_into_flax).lower()}` |"
        )

    lines.extend(["", "## Pack Findings"])
    for task in plan.tasks:
        findings = ", ".join(task.audit_findings) if task.audit_findings else "No blocking findings."
        lines.append(f"- `{task.pack_id}`: {findings}")

    lines.extend(["", "## Shared Family Candidates"])
    if not shared_tags:
        lines.append("- None")
    else:
        for tag in shared_tags:
            lines.append(f"- `{tag}`")

    return "\n".join(lines) + "\n"


def write_plan_outputs(
    plan: RomanBlockerPlan,
    *,
    task_output_path: str | Path | None = None,
    summary_output_path: str | Path | None = None,
) -> tuple[Path, Path]:
    task_path = write_json(task_output_path or roman_blocker_task_path(), plan.to_dict())
    summary_path = write_text(summary_output_path or roman_blocker_summary_path(), build_summary_markdown(plan))
    return task_path, summary_path
