from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from assetboy.cleanup.blender_mcp import build_cleanup_plan
from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, publish_payload_dir
from assetboy.provenance.templates import build_provenance_template
from assetboy.providers.lanes import ProviderLane


class ExtractorTool(str, Enum):
    ASSET_RIPPER = "asset_ripper"
    ASSET_STUDIO = "asset_studio"
    FMODEL = "fmodel"
    UMODEL = "umodel"


@dataclass(frozen=True)
class ExtractorProfile:
    tool: ExtractorTool
    display_name: str
    export_formats: tuple[str, ...]
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "tool": self.tool.value,
            "display_name": self.display_name,
            "export_formats": list(self.export_formats),
            "notes": list(self.notes),
        }


EXTRACTOR_PROFILES: dict[ExtractorTool, ExtractorProfile] = {
    ExtractorTool.ASSET_RIPPER: ExtractorProfile(
        tool=ExtractorTool.ASSET_RIPPER,
        display_name="AssetRipper",
        export_formats=("glb", "fbx", "png", "wav"),
        notes=("Use for owned or licensed Unity content only.", "Prefer when project reconstruction is useful."),
    ),
    ExtractorTool.ASSET_STUDIO: ExtractorProfile(
        tool=ExtractorTool.ASSET_STUDIO,
        display_name="AssetStudio",
        export_formats=("fbx", "obj", "png", "wav"),
        notes=("Use for owned or licensed Unity content only.", "Prefer when targeting specific assets."),
    ),
    ExtractorTool.FMODEL: ExtractorProfile(
        tool=ExtractorTool.FMODEL,
        display_name="FModel",
        export_formats=("glb", "fbx", "png", "wav"),
        notes=("Use for owned or licensed Unreal content only.", "Preferred modern Unreal extractor."),
    ),
    ExtractorTool.UMODEL: ExtractorProfile(
        tool=ExtractorTool.UMODEL,
        display_name="Umodel",
        export_formats=("glb", "fbx", "tga"),
        notes=("Use for owned or licensed Unreal content only.", "Fallback extractor for older titles."),
    ),
}


@dataclass(frozen=True)
class ExtractorJob:
    tool: ExtractorTool
    pack_id: str
    game_scope: str
    source_package_name: str
    source_url: str
    license_note: str
    input_path_hint: str

    def to_dict(self) -> dict[str, object]:
        profile = EXTRACTOR_PROFILES[self.tool]
        return {
            "tool": self.tool.value,
            "profile": profile.to_dict(),
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "source_package_name": self.source_package_name,
            "source_url": self.source_url,
            "license_note": self.license_note,
            "input_path_hint": self.input_path_hint,
        }


@dataclass(frozen=True)
class ExtractorArtifacts:
    output_dir: Path
    job_spec_path: Path
    provenance_template_path: Path
    review_checklist_path: Path
    payload_target_path_file: Path
    cleanup_plan_path: Path
    payload_target_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "job_spec_path": str(self.job_spec_path),
            "provenance_template_path": str(self.provenance_template_path),
            "review_checklist_path": str(self.review_checklist_path),
            "payload_target_path_file": str(self.payload_target_path_file),
            "cleanup_plan_path": str(self.cleanup_plan_path),
            "payload_target_path": str(self.payload_target_path),
        }


def emit_extractor_job(
    *,
    tool: ExtractorTool | str,
    pack_id: str,
    game_scope: str,
    source_package_name: str,
    source_url: str,
    license_note: str,
    input_path_hint: str,
    asset_kind: str = "prop",
    output_dir: str | Path | None = None,
) -> ExtractorArtifacts:
    tool_value = ExtractorTool(tool)
    profile = EXTRACTOR_PROFILES[tool_value]
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
    cleanup_plan = build_cleanup_plan(
        pack_id=pack_id,
        asset_kind=asset_kind,
        source_lane=ProviderLane.MANUAL_BROWSER.value,
    )
    job = ExtractorJob(
        tool=tool_value,
        pack_id=pack_id,
        game_scope=game_scope,
        source_package_name=source_package_name,
        source_url=source_url,
        license_note=license_note,
        input_path_hint=input_path_hint,
    )
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "extractor_bridge" / tool_value.value / pack_id
    )
    provenance = build_provenance_template(
        pack_id=pack_id,
        game_scope=game_scope,
        lane=ProviderLane.MANUAL_BROWSER,
        source_adapter=tool_value.value,
        payload_target_path=str(payload_target),
        notes=profile.notes,
    )
    provenance["values"]["source_page_url"] = source_url
    provenance["values"]["download_notes"] = license_note
    checklist_lines = [
        f"# {profile.display_name} Checklist",
        "",
        f"- Pack: `{pack_id}`",
        f"- Game scope: `{game_scope}`",
        f"- Source package: `{source_package_name}`",
        f"- Input hint: `{input_path_hint}`",
        f"- Payload target: `{payload_target}`",
        "",
        "## Notes",
    ]
    checklist_lines.extend(f"- {line}" for line in profile.notes)
    checklist_lines.extend(
        [
            "- Export models, textures, audio, and animations into open formats only.",
            "- Skip code, plugins, and editor-only content by default.",
            "- Run Blender cleanup before publish.",
        ]
    )

    job_spec_path = write_json(root_dir / "extractor_job.json", job.to_dict())
    provenance_template_path = write_json(root_dir / "provenance_template.json", provenance)
    review_checklist_path = write_text(root_dir / "review_checklist.md", "\n".join(checklist_lines) + "\n")
    payload_target_path_file = write_text(root_dir / "payload_target.txt", str(payload_target) + "\n")
    cleanup_plan_path = write_json(root_dir / "cleanup_plan.json", cleanup_plan.to_dict())

    return ExtractorArtifacts(
        output_dir=root_dir,
        job_spec_path=job_spec_path,
        provenance_template_path=provenance_template_path,
        review_checklist_path=review_checklist_path,
        payload_target_path_file=payload_target_path_file,
        cleanup_plan_path=cleanup_plan_path,
        payload_target_path=payload_target,
    )
