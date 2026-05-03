from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root, publish_payload_dir


@dataclass(frozen=True)
class BlenderBatchJob:
    pack_id: str
    game_scope: str
    input_dir: str
    output_dir: str
    source_format: str
    export_targets: tuple[str, ...]
    source_adapter: str = "blender_psk_batch"

    def to_dict(self) -> dict[str, object]:
        return {
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "input_dir": self.input_dir,
            "output_dir": self.output_dir,
            "source_format": self.source_format,
            "export_targets": list(self.export_targets),
            "source_adapter": self.source_adapter,
        }


@dataclass(frozen=True)
class BlenderBatchArtifacts:
    output_dir: Path
    job_spec_path: Path
    blender_script_path: Path
    powershell_path: Path
    command_template_path: Path
    review_checklist_path: Path
    payload_target_path_file: Path
    converted_output_dir: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "job_spec_path": str(self.job_spec_path),
            "blender_script_path": str(self.blender_script_path),
            "powershell_path": str(self.powershell_path),
            "command_template_path": str(self.command_template_path),
            "review_checklist_path": str(self.review_checklist_path),
            "payload_target_path_file": str(self.payload_target_path_file),
            "converted_output_dir": str(self.converted_output_dir),
        }


def _blender_python_script() -> str:
    return "\n".join(
        [
            "import argparse",
            "import json",
            "from pathlib import Path",
            "",
            "import bpy",
            "",
            "",
            "def parse_args():",
            "    parser = argparse.ArgumentParser()",
            "    parser.add_argument('--job', required=True)",
            "    args, _ = parser.parse_known_args()",
            "    return args",
            "",
            "",
            "def clear_scene():",
            "    bpy.ops.object.select_all(action='SELECT')",
            "    bpy.ops.object.delete(use_global=False)",
            "",
            "",
            "def export_object(output_dir: Path, name: str, export_targets):",
            "    obj = bpy.context.active_object",
            "    if obj is None:",
            "        return",
            "    safe_name = ''.join(ch if ch.isalnum() or ch in ('_', '-', '.') else '_' for ch in name).strip('._-') or 'asset'",
            "    for target in export_targets:",
            "        target_path = output_dir / f'{safe_name}.{target}'",
            "        if target == 'fbx':",
            "            bpy.ops.export_scene.fbx(filepath=str(target_path), use_selection=True)",
            "        elif target == 'glb':",
            "            bpy.ops.export_scene.gltf(filepath=str(target_path), export_format='GLB', use_selection=True)",
            "",
            "",
            "def main():",
            "    args = parse_args()",
            "    payload = json.loads(Path(args.job).read_text(encoding='utf-8'))",
            "    input_dir = Path(payload['input_dir'])",
            "    output_dir = Path(payload['output_dir'])",
            "    source_format = payload.get('source_format', 'psk').lower()",
            "    export_targets = payload.get('export_targets', ['fbx', 'glb'])",
            "    output_dir.mkdir(parents=True, exist_ok=True)",
            "",
            "    source_files = sorted(input_dir.rglob(f'*.{source_format}'))",
            "    for source_file in source_files:",
            "        clear_scene()",
            "        if source_format == 'psk':",
            "            # Requires blender3d_import_psk_psa add-on enabled in Blender.",
            "            bpy.ops.import_scene.psk(filepath=str(source_file))",
            "        else:",
            "            continue",
            "        active_name = bpy.context.active_object.name if bpy.context.active_object else source_file.stem",
            "        export_object(output_dir, active_name, export_targets)",
            "",
            "    print('AssetBoy Blender batch complete: ' + str(output_dir))",
            "",
            "",
            "if __name__ == '__main__':",
            "    main()",
            "",
        ]
    )


def _powershell_script(job_path: Path, script_path: Path) -> str:
    return "\n".join(
        [
            "param(",
            '  [string]$BlenderExe = "blender",',
            f'  [string]$JobJson = "{job_path}",',
            f'  [string]$BlenderScript = "{script_path}"',
            ")",
            "",
            '$ErrorActionPreference = "Stop"',
            '& $BlenderExe -b -P "$BlenderScript" -- --job "$JobJson"',
        ]
    ) + "\n"


def emit_blender_psk_batch_job(
    *,
    pack_id: str,
    game_scope: str,
    input_dir: str | Path,
    source_format: str = "psk",
    export_targets: tuple[str, ...] = ("fbx", "glb"),
    output_dir: str | Path | None = None,
) -> BlenderBatchArtifacts:
    payload_target = publish_payload_dir(game_scope=game_scope, pack_id=pack_id)
    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "blender_batch" / pack_id
    )
    converted_output_dir = root_dir / "converted"
    job = BlenderBatchJob(
        pack_id=pack_id,
        game_scope=game_scope,
        input_dir=str(Path(input_dir)),
        output_dir=str(converted_output_dir),
        source_format=source_format,
        export_targets=export_targets,
    )
    job_spec_path = write_json(root_dir / "blender_batch_job.json", job.to_dict())
    blender_script_path = write_text(root_dir / "blender_batch_convert.py", _blender_python_script())
    powershell_path = write_text(
        root_dir / "run_blender_batch.ps1",
        _powershell_script(job_spec_path, blender_script_path),
    )
    command_template_path = write_text(
        root_dir / "commands.txt",
        f'pwsh -ExecutionPolicy Bypass -File "{powershell_path}"\n',
    )
    review_checklist_path = write_text(
        root_dir / "review_checklist.md",
        "\n".join(
            [
                "# Blender PSK Batch Checklist",
                "",
                f"- Pack: `{pack_id}`",
                f"- Game scope: `{game_scope}`",
                f"- Input dir: `{Path(input_dir)}`",
                f"- Converted output dir: `{converted_output_dir}`",
                f"- Payload target: `{payload_target}`",
                "",
                "## Notes",
                "- Enable `blender3d_import_psk_psa` add-on before running batch conversion.",
                "- Review naming, scale, and topology before final payload copy.",
            ]
        )
        + "\n",
    )
    payload_target_path_file = write_text(root_dir / "payload_target.txt", str(payload_target) + "\n")
    return BlenderBatchArtifacts(
        output_dir=root_dir,
        job_spec_path=job_spec_path,
        blender_script_path=blender_script_path,
        powershell_path=powershell_path,
        command_template_path=command_template_path,
        review_checklist_path=review_checklist_path,
        payload_target_path_file=payload_target_path_file,
        converted_output_dir=converted_output_dir,
    )
