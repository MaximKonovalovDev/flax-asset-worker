from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assetboy.cleanup.blender_mcp import build_cleanup_plan
from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, manual_drop_dir, publish_payload_dir
from assetboy.provenance.templates import build_provenance_template
from assetboy.providers.lanes import ProviderLane


@dataclass(frozen=True)
class Cue4ParseJob:
    pack_id: str
    game_scope: str
    source_url: str
    source_package_name: str
    license_note: str
    input_path_hint: str
    output_path: str
    mesh_output_format: str
    texture_formats: tuple[str, ...]
    source_adapter: str = "cue4parse"

    def to_dict(self) -> dict[str, object]:
        return {
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "source_url": self.source_url,
            "source_package_name": self.source_package_name,
            "license_note": self.license_note,
            "input_path_hint": self.input_path_hint,
            "output_path": self.output_path,
            "mesh_output_format": self.mesh_output_format,
            "texture_formats": list(self.texture_formats),
            "source_adapter": self.source_adapter,
            "preferred_next_step": "blender_psk_batch",
        }


@dataclass(frozen=True)
class Cue4ParseArtifacts:
    output_dir: Path
    job_spec_path: Path
    provenance_template_path: Path
    review_checklist_path: Path
    command_template_path: Path
    payload_target_path_file: Path
    cleanup_plan_path: Path
    output_path_hint_file: Path
    output_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "job_spec_path": str(self.job_spec_path),
            "provenance_template_path": str(self.provenance_template_path),
            "review_checklist_path": str(self.review_checklist_path),
            "command_template_path": str(self.command_template_path),
            "payload_target_path_file": str(self.payload_target_path_file),
            "cleanup_plan_path": str(self.cleanup_plan_path),
            "output_path_hint_file": str(self.output_path_hint_file),
            "output_path": str(self.output_path),
        }


def _command_template(job: Cue4ParseJob) -> str:
    return "\n".join(
        [
            "# CUE4Parse mass extract template (adjust for your build/fork)",
            'Cue4Parse --help',
            f'Cue4Parse --input "{job.input_path_hint}" --output "{job.output_path}" --export-mesh "{job.mesh_output_format}" --export-textures',
            "",
            "# Then convert PSK -> FBX/GLB using Blender batch helper:",
            f'python -m assetboy.cli emit-blender-psk-batch --pack-id {job.pack_id} --game-scope {job.game_scope} --input-dir "{job.output_path}"',
        ]
    ) + "\n"


def emit_cue4parse_job(
    *,
    pack_id: str,
    game_scope: str,
    source_package_name: str,
    source_url: str,
    license_note: str,
    input_path_hint: str,
    mesh_output_format: str = "psk",
    texture_formats: tuple[str, ...] = ("png", "tga"),
    asset_kind: str = "prop",
    output_dir: str | Path | None = None,
) -> Cue4ParseArtifacts:
    output_path = manual_drop_dir() / pack_id / "cue4parse_exports"
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
    cleanup_plan = build_cleanup_plan(
        pack_id=pack_id,
        asset_kind=asset_kind,
        source_lane=ProviderLane.MANUAL_BROWSER.value,
    )
    job = Cue4ParseJob(
        pack_id=pack_id,
        game_scope=game_scope,
        source_package_name=source_package_name,
        source_url=source_url,
        license_note=license_note,
        input_path_hint=input_path_hint,
        output_path=str(output_path),
        mesh_output_format=mesh_output_format,
        texture_formats=texture_formats,
    )
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "cue4parse_bridge" / pack_id
    )
    provenance = build_provenance_template(
        pack_id=pack_id,
        game_scope=game_scope,
        lane=ProviderLane.MANUAL_BROWSER,
        source_adapter="cue4parse",
        payload_target_path=str(payload_target),
        notes=("CUE4Parse mass extraction path used for owned/licensed UE package content.",),
    )
    provenance["values"]["source_page_url"] = source_url
    provenance["values"]["download_notes"] = license_note

    checklist = "\n".join(
        [
            "# CUE4Parse Mass Extract Checklist",
            "",
            f"- Pack: `{pack_id}`",
            f"- Game scope: `{game_scope}`",
            f"- Source package: `{source_package_name}`",
            f"- Input path: `{input_path_hint}`",
            f"- Output path: `{output_path}`",
            f"- Mesh format: `{mesh_output_format}`",
            f"- Texture formats: `{', '.join(texture_formats)}`",
            f"- Payload target: `{payload_target}`",
            "",
            "## Steps",
            "- Extract only owned/licensed package content.",
            "- Keep meshes, textures, animations, and audio only.",
            "- Skip code/plugins/editor-only files.",
            "- Run Blender batch conversion and cleanup before publish.",
        ]
    ) + "\n"

    job_spec_path = write_json(root_dir / "cue4parse_job.json", job.to_dict())
    provenance_template_path = write_json(root_dir / "provenance_template.json", provenance)
    review_checklist_path = write_text(root_dir / "review_checklist.md", checklist)
    command_template_path = write_text(root_dir / "commands.txt", _command_template(job))
    payload_target_path_file = write_text(root_dir / "payload_target.txt", str(payload_target) + "\n")
    cleanup_plan_path = write_json(root_dir / "cleanup_plan.json", cleanup_plan.to_dict())
    output_path_hint_file = write_text(root_dir / "output_path_hint.txt", str(output_path) + "\n")

    return Cue4ParseArtifacts(
        output_dir=root_dir,
        job_spec_path=job_spec_path,
        provenance_template_path=provenance_template_path,
        review_checklist_path=review_checklist_path,
        command_template_path=command_template_path,
        payload_target_path_file=payload_target_path_file,
        cleanup_plan_path=cleanup_plan_path,
        output_path_hint_file=output_path_hint_file,
        output_path=output_path,
    )
