from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from assetboy.cleanup.blender_mcp import build_cleanup_plan
from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, publish_payload_dir
from assetboy.provenance.templates import build_provenance_template
from assetboy.providers.lanes import ProviderLane


class EngineBridgeKind(str, Enum):
    UNITY = "unity"
    UNREAL = "unreal"


DEFAULT_ASSET_TYPES: tuple[str, ...] = ("models", "animations", "textures", "audio")
DEFAULT_SKIP_TYPES: tuple[str, ...] = ("plugins", "editor_tools", "code_heavy_packages")


@dataclass(frozen=True)
class EngineBridgeProfile:
    engine: EngineBridgeKind
    display_name: str
    source_adapter: str
    export_formats: tuple[str, ...]
    import_notes: tuple[str, ...]
    export_notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "engine": self.engine.value,
            "display_name": self.display_name,
            "source_adapter": self.source_adapter,
            "export_formats": list(self.export_formats),
            "import_notes": list(self.import_notes),
            "export_notes": list(self.export_notes),
        }


ENGINE_BRIDGE_PROFILES: dict[EngineBridgeKind, EngineBridgeProfile] = {
    EngineBridgeKind.UNITY: EngineBridgeProfile(
        engine=EngineBridgeKind.UNITY,
        display_name="Unity Engine Bridge",
        source_adapter="unity_engine_bridge",
        export_formats=("glb", "fbx", "png", "tga", "wav"),
        import_notes=(
            "Import the package into a throwaway Unity project, not the live game project.",
            "Let Unity reimport fully before choosing export targets.",
            "Skip editor tools, scripts, and package infrastructure unless they are required to reach the content.",
        ),
        export_notes=(
            "Export models and rigs to GLB or FBX.",
            "Export textures to PNG or TGA.",
            "Export audio to WAV when possible.",
        ),
    ),
    EngineBridgeKind.UNREAL: EngineBridgeProfile(
        engine=EngineBridgeKind.UNREAL,
        display_name="Unreal Engine Bridge",
        source_adapter="unreal_engine_bridge",
        export_formats=("glb", "fbx", "png", "tga", "wav"),
        import_notes=(
            "Import the package into a throwaway Unreal project or use owned Fab content in an isolated project.",
            "Skip plugins and code-heavy packages by default.",
            "Only bridge owned or licensed content.",
        ),
        export_notes=(
            "Export meshes and animations to FBX or GLB where available.",
            "Export textures to PNG or TGA.",
            "Export audio to WAV.",
        ),
    ),
}


@dataclass(frozen=True)
class EngineExportJob:
    engine: EngineBridgeKind
    pack_id: str
    game_scope: str
    source_url: str
    license_note: str
    asset_types: tuple[str, ...]
    export_formats: tuple[str, ...]
    skip_types: tuple[str, ...]
    source_package_name: str = ""
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        profile = ENGINE_BRIDGE_PROFILES[self.engine]
        return {
            "engine": self.engine.value,
            "profile": profile.to_dict(),
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "source_url": self.source_url,
            "license_note": self.license_note,
            "source_package_name": self.source_package_name,
            "asset_types": list(self.asset_types),
            "export_formats": list(self.export_formats),
            "skip_types": list(self.skip_types),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class EngineBridgeArtifacts:
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


def build_engine_export_job(
    *,
    engine: EngineBridgeKind | str,
    pack_id: str,
    game_scope: str,
    source_url: str,
    license_note: str,
    source_package_name: str = "",
    asset_types: tuple[str, ...] = DEFAULT_ASSET_TYPES,
    skip_types: tuple[str, ...] = DEFAULT_SKIP_TYPES,
    notes: tuple[str, ...] = (),
) -> EngineExportJob:
    engine_kind = EngineBridgeKind(engine)
    profile = ENGINE_BRIDGE_PROFILES[engine_kind]
    return EngineExportJob(
        engine=engine_kind,
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        license_note=license_note,
        source_package_name=source_package_name,
        asset_types=asset_types,
        export_formats=profile.export_formats,
        skip_types=skip_types,
        notes=notes,
    )


def emit_engine_export_job(
    *,
    engine: EngineBridgeKind | str,
    pack_id: str,
    game_scope: str,
    source_url: str,
    license_note: str,
    source_package_name: str = "",
    asset_kind: str = "prop",
    output_dir: str | Path | None = None,
    notes: tuple[str, ...] = (),
) -> EngineBridgeArtifacts:
    job = build_engine_export_job(
        engine=engine,
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        license_note=license_note,
        source_package_name=source_package_name,
        notes=notes,
    )
    profile = ENGINE_BRIDGE_PROFILES[job.engine]
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
    cleanup_plan = build_cleanup_plan(
        pack_id=pack_id,
        asset_kind=asset_kind,
        source_lane=ProviderLane.MANUAL_BROWSER.value,
    )
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "engine_bridge" / job.engine.value / pack_id
    )
    provenance = build_provenance_template(
        pack_id=pack_id,
        game_scope=game_scope,
        lane=ProviderLane.MANUAL_BROWSER,
        source_adapter=profile.source_adapter,
        payload_target_path=str(payload_target),
        notes=notes,
    )
    provenance["values"]["source_page_url"] = source_url
    provenance["values"]["download_notes"] = license_note

    checklist_lines = [
        f"# {profile.display_name} Checklist",
        "",
        f"- Pack: `{pack_id}`",
        f"- Game scope: `{game_scope}`",
        f"- Source URL: `{source_url}`",
        f"- Payload target: `{payload_target}`",
        "",
        "## Import",
    ]
    checklist_lines.extend(f"- {line}" for line in profile.import_notes)
    checklist_lines.extend(["", "## Export"])
    checklist_lines.extend(f"- {line}" for line in profile.export_notes)
    checklist_lines.extend(["", "## Skip By Default"])
    checklist_lines.extend(f"- `{item}`" for item in job.skip_types)

    job_spec_path = write_json(root_dir / "engine_export_job.json", job.to_dict())
    provenance_template_path = write_json(root_dir / "provenance_template.json", provenance)
    review_checklist_path = write_text(root_dir / "review_checklist.md", "\n".join(checklist_lines) + "\n")
    payload_target_path_file = write_text(root_dir / "payload_target.txt", str(payload_target) + "\n")
    cleanup_plan_path = write_json(root_dir / "cleanup_plan.json", cleanup_plan.to_dict())

    return EngineBridgeArtifacts(
        output_dir=root_dir,
        job_spec_path=job_spec_path,
        provenance_template_path=provenance_template_path,
        review_checklist_path=review_checklist_path,
        payload_target_path_file=payload_target_path_file,
        cleanup_plan_path=cleanup_plan_path,
        payload_target_path=payload_target,
    )
