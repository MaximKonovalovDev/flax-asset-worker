from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from assetboy.library.files import read_json, write_json, write_text
from assetboy.providers.engine_bridge import emit_engine_export_job


UNREAL_EDITOR_CMD_CANDIDATES: tuple[str, ...] = (
    "Engine/Binaries/Win64/UnrealEditor-Cmd.exe",
    "Engine/Binaries/Win64/UE4Editor-Cmd.exe",
)
UNREAL_EDITOR_GUI_CANDIDATES: tuple[str, ...] = (
    "Engine/Binaries/Win64/UnrealEditor.exe",
    "Engine/Binaries/Win64/UE4Editor.exe",
)
DEFAULT_UNREAL_SEARCH_ROOTS: tuple[Path, ...] = (
    Path(r"C:\Program Files\Epic Games"),
    Path(r"C:\Program Files (x86)\Epic Games"),
    Path(r"D:\Epic Games"),
    Path(r"C:\Epic Games"),
)
DEFAULT_BLENDER_SEARCH_ROOTS: tuple[Path, ...] = (
    Path(r"C:\Program Files\Blender Foundation"),
    Path(r"C:\Program Files (x86)\Blender Foundation"),
)
UNREAL_EXPORTABLE_FORMATS: tuple[str, ...] = ("fbx", "png", "tga", "wav")


def _slug(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


@dataclass(frozen=True)
class UnrealInstallation:
    version: str
    root_dir: Path
    editor_cmd_path: Path | None
    editor_gui_path: Path | None
    detection_source: str

    @property
    def usable(self) -> bool:
        return self.editor_cmd_path is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "root_dir": str(self.root_dir),
            "editor_cmd_path": str(self.editor_cmd_path) if self.editor_cmd_path else "",
            "editor_gui_path": str(self.editor_gui_path) if self.editor_gui_path else "",
            "detection_source": self.detection_source,
            "usable": self.usable,
        }


@dataclass(frozen=True)
class UnrealRunnerJob:
    pack_id: str
    game_scope: str
    engine_job_spec_path: Path
    project_file: Path
    package_root: str
    asset_paths: tuple[str, ...]
    staged_export_dir: Path
    payload_target_path: Path
    cleanup_plan_path: Path
    export_formats: tuple[str, ...]
    editor_cmd_path_hint: str
    editor_gui_path_hint: str
    blender_executable_hint: str
    notes: tuple[str, ...]
    detected_installations: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "engine_job_spec_path": str(self.engine_job_spec_path),
            "project_file": str(self.project_file),
            "package_root": self.package_root,
            "asset_paths": list(self.asset_paths),
            "staged_export_dir": str(self.staged_export_dir),
            "payload_target_path": str(self.payload_target_path),
            "cleanup_plan_path": str(self.cleanup_plan_path),
            "export_formats": list(self.export_formats),
            "editor_cmd_path_hint": self.editor_cmd_path_hint,
            "editor_gui_path_hint": self.editor_gui_path_hint,
            "blender_executable_hint": self.blender_executable_hint,
            "notes": list(self.notes),
            "detected_installations": list(self.detected_installations),
        }


@dataclass(frozen=True)
class UnrealRunnerArtifacts:
    output_dir: Path
    engine_job_spec_path: Path
    runner_job_path: Path
    powershell_path: Path
    unreal_python_path: Path
    blender_handoff_path: Path
    launch_command_path: Path
    payload_target_path: Path
    editor_cmd_path_hint: str

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "engine_job_spec_path": str(self.engine_job_spec_path),
            "runner_job_path": str(self.runner_job_path),
            "powershell_path": str(self.powershell_path),
            "unreal_python_path": str(self.unreal_python_path),
            "blender_handoff_path": str(self.blender_handoff_path),
            "launch_command_path": str(self.launch_command_path),
            "payload_target_path": str(self.payload_target_path),
            "editor_cmd_path_hint": self.editor_cmd_path_hint,
        }


def list_unreal_installations(search_roots: tuple[Path, ...] | None = None) -> tuple[UnrealInstallation, ...]:
    roots = search_roots or DEFAULT_UNREAL_SEARCH_ROOTS
    installations: list[UnrealInstallation] = []
    seen_roots: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            if not (child.name.startswith("UE_") or child.name[0:1].isdigit()):
                continue
            resolved_root = child.resolve()
            if resolved_root in seen_roots:
                continue
            seen_roots.add(resolved_root)
            editor_cmd = next((resolved_root / rel for rel in UNREAL_EDITOR_CMD_CANDIDATES if (resolved_root / rel).exists()), None)
            editor_gui = next((resolved_root / rel for rel in UNREAL_EDITOR_GUI_CANDIDATES if (resolved_root / rel).exists()), None)
            version = child.name.replace("UE_", "")
            installations.append(
                UnrealInstallation(
                    version=version,
                    root_dir=resolved_root,
                    editor_cmd_path=editor_cmd,
                    editor_gui_path=editor_gui,
                    detection_source="directory_scan",
                )
            )
    return tuple(sorted(installations, key=lambda item: (not item.usable, item.version)))


def detect_blender_executable(search_roots: tuple[Path, ...] | None = None) -> Path | None:
    roots = search_roots or DEFAULT_BLENDER_SEARCH_ROOTS
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            if not child.name.startswith("Blender"):
                continue
            executable = child / "blender.exe"
            if executable.exists():
                candidates.append(executable)
    if not candidates:
        return None
    return sorted(candidates, reverse=True)[0]


def _load_cleanup_plan(cleanup_plan_path: Path) -> dict[str, object]:
    return read_json(cleanup_plan_path)


def _build_runner_powershell(
    job: UnrealRunnerJob,
    *,
    runner_job_name: str = "unreal_export_runner.json",
    unreal_python_name: str = "unreal_export.py",
) -> str:
    editor_hint = job.editor_cmd_path_hint or "<set UnrealEditor-Cmd path>"
    return "\n".join(
        [
            "param(",
            f"  [string]$EditorCmdPath = \"{editor_hint}\",",
            f"  [string]$ProjectFile = \"{job.project_file}\",",
            f"  [string]$RunnerJson = \"$PSScriptRoot\\{runner_job_name}\",",
            f"  [string]$PythonScript = \"$PSScriptRoot\\{unreal_python_name}\"",
            ")",
            "",
            '$ErrorActionPreference = "Stop"',
            "",
            'if (!(Test-Path $EditorCmdPath)) { throw "Unreal editor cmd executable not found: $EditorCmdPath" }',
            'if (!(Test-Path $ProjectFile)) { throw "Unreal project file not found: $ProjectFile" }',
            'if (!(Test-Path $RunnerJson)) { throw "Runner job file not found: $RunnerJson" }',
            'if (!(Test-Path $PythonScript)) { throw "Unreal export python script not found: $PythonScript" }',
            "",
            '$env:ASSETBOY_UNREAL_RUNNER_JSON = $RunnerJson',
            '& $EditorCmdPath $ProjectFile -unattended -nullrhi -ExecutePythonScript="$PythonScript"',
        ]
    ) + "\n"


def _build_unreal_python(job: UnrealRunnerJob) -> str:
    return "\n".join(
        [
            "import json",
            "import os",
            "import re",
            "import traceback",
            "",
            "import unreal",
            "",
            "RUNNER_JSON = os.environ.get('ASSETBOY_UNREAL_RUNNER_JSON', '').strip()",
            "if not RUNNER_JSON or not os.path.exists(RUNNER_JSON):",
            "    raise RuntimeError('ASSETBOY_UNREAL_RUNNER_JSON is missing or invalid.')",
            "",
            "with open(RUNNER_JSON, 'r', encoding='utf-8') as handle:",
            "    RUNNER = json.load(handle)",
            "",
            "EXPORT_DIR = RUNNER['staged_export_dir']",
            "os.makedirs(EXPORT_DIR, exist_ok=True)",
            "",
            "EXPORTER_CANDIDATES = {",
            "    'StaticMesh': [('StaticMeshExporterFBX', '.fbx')],",
            "    'SkeletalMesh': [('SkeletalMeshExporterFBX', '.fbx')],",
            "    'AnimSequence': [('AnimSequenceExporterFBX', '.fbx')],",
            "    'Texture2D': [('TextureExporterPNG', '.png'), ('TextureExporterTGA', '.tga')],",
            "    'SoundWave': [('SoundExporterWAV', '.wav')],",
            "}",
            "",
            "def sanitize_name(value):",
            "    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', value.strip())",
            "    cleaned = cleaned.strip('._-')",
            "    return cleaned or 'asset'",
            "",
            "def choose_exporter(class_name):",
            "    for exporter_name, extension in EXPORTER_CANDIDATES.get(class_name, []):",
            "        exporter_class = getattr(unreal, exporter_name, None)",
            "        if exporter_class is not None:",
            "            return exporter_class(), extension",
            "    return None, ''",
            "",
            "def run_export(asset_path):",
            "    asset = unreal.EditorAssetLibrary.load_asset(asset_path)",
            "    if asset is None:",
            "        return {'asset_path': asset_path, 'status': 'missing'}",
            "    class_name = asset.get_class().get_name()",
            "    exporter, extension = choose_exporter(class_name)",
            "    if exporter is None:",
            "        return {'asset_path': asset_path, 'status': 'skipped', 'class_name': class_name}",
            "    file_name = sanitize_name(asset.get_name()) + extension",
            "    file_path = os.path.join(EXPORT_DIR, file_name)",
            "    task = unreal.AssetExportTask()",
            "    task.object = asset",
            "    task.filename = file_path",
            "    task.automated = True",
            "    task.prompt = False",
            "    task.replace_identical = True",
            "    task.exporter = exporter",
            "    task.use_file_archive = False",
            "    unreal.Exporter.run_asset_export_task(task)",
            "    return {'asset_path': asset_path, 'status': 'exported', 'class_name': class_name, 'file_path': file_path}",
            "",
            "asset_paths = list(RUNNER.get('asset_paths', []))",
            "if not asset_paths:",
            "    package_root = RUNNER.get('package_root', '/Game')",
            "    asset_paths = unreal.EditorAssetLibrary.list_assets(package_root, recursive=True, include_folder=False)",
            "",
            "results = []",
            "for asset_path in asset_paths:",
            "    try:",
            "        results.append(run_export(asset_path))",
            "    except Exception as exc:",
            "        results.append({'asset_path': asset_path, 'status': 'error', 'error': str(exc)})",
            "        traceback.print_exc()",
            "",
            "summary_path = os.path.join(EXPORT_DIR, 'export_summary.json')",
            "with open(summary_path, 'w', encoding='utf-8') as handle:",
            "    json.dump({'results': results}, handle, indent=2)",
            "",
            "print('AssetBoy Unreal export finished: ' + summary_path)",
            "",
        ]
    )


def emit_unreal_export_runner(
    *,
    pack_id: str,
    game_scope: str,
    source_url: str,
    license_note: str,
    project_file: str | Path,
    package_root: str = "/Game",
    asset_paths: tuple[str, ...] = (),
    source_package_name: str = "",
    asset_kind: str = "prop",
    output_dir: str | Path | None = None,
    notes: tuple[str, ...] = (),
    unreal_search_roots: tuple[Path, ...] | None = None,
    blender_search_roots: tuple[Path, ...] | None = None,
) -> UnrealRunnerArtifacts:
    engine_artifacts = emit_engine_export_job(
        engine="unreal",
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        license_note=license_note,
        source_package_name=source_package_name,
        asset_kind=asset_kind,
        output_dir=output_dir,
        notes=notes,
    )
    installations = list_unreal_installations(search_roots=unreal_search_roots)
    preferred_install = next((item for item in installations if item.usable), None)
    blender_path = detect_blender_executable(search_roots=blender_search_roots)
    cleanup_plan = _load_cleanup_plan(engine_artifacts.cleanup_plan_path)
    engine_job = read_json(engine_artifacts.job_spec_path)
    staged_export_dir = engine_artifacts.output_dir / "staged_exports"
    runner_job = UnrealRunnerJob(
        pack_id=pack_id,
        game_scope=game_scope,
        engine_job_spec_path=engine_artifacts.job_spec_path,
        project_file=Path(project_file),
        package_root=package_root,
        asset_paths=asset_paths,
        staged_export_dir=staged_export_dir,
        payload_target_path=engine_artifacts.payload_target_path,
        cleanup_plan_path=engine_artifacts.cleanup_plan_path,
        export_formats=tuple(
            fmt for fmt in engine_job["export_formats"] if fmt in UNREAL_EXPORTABLE_FORMATS
        ),
        editor_cmd_path_hint=str(preferred_install.editor_cmd_path) if preferred_install and preferred_install.editor_cmd_path else "",
        editor_gui_path_hint=str(preferred_install.editor_gui_path) if preferred_install and preferred_install.editor_gui_path else "",
        blender_executable_hint=str(blender_path) if blender_path else "",
        notes=notes,
        detected_installations=tuple(item.to_dict() for item in installations),
    )
    runner_job_path = write_json(engine_artifacts.output_dir / "unreal_export_runner.json", runner_job.to_dict())
    unreal_python_path = write_text(engine_artifacts.output_dir / "unreal_export.py", _build_unreal_python(runner_job))
    powershell_path = write_text(
        engine_artifacts.output_dir / "run_unreal_export.ps1",
        _build_runner_powershell(
            runner_job,
            runner_job_name=runner_job_path.name,
            unreal_python_name=unreal_python_path.name,
        ),
    )
    blender_handoff = {
        "pack_id": pack_id,
        "game_scope": game_scope,
        "staged_export_dir": str(staged_export_dir),
        "cleanup_plan_path": str(engine_artifacts.cleanup_plan_path),
        "payload_target_path": str(engine_artifacts.payload_target_path),
        "preferred_cleanup_exports": cleanup_plan["export_decision"]["export_targets"],
        "blender_executable_hint": str(blender_path) if blender_path else "",
        "next_step": "Run Blender cleanup on the staged Unreal exports, then copy accepted outputs into the payload target.",
    }
    blender_handoff_path = write_json(engine_artifacts.output_dir / "blender_handoff.json", blender_handoff)
    launch_command = f'pwsh -ExecutionPolicy Bypass -File "{powershell_path}"\n'
    launch_command_path = write_text(engine_artifacts.output_dir / "launch_unreal_export.txt", launch_command)
    return UnrealRunnerArtifacts(
        output_dir=engine_artifacts.output_dir,
        engine_job_spec_path=engine_artifacts.job_spec_path,
        runner_job_path=runner_job_path,
        powershell_path=powershell_path,
        unreal_python_path=unreal_python_path,
        blender_handoff_path=blender_handoff_path,
        launch_command_path=launch_command_path,
        payload_target_path=engine_artifacts.payload_target_path,
        editor_cmd_path_hint=runner_job.editor_cmd_path_hint,
    )
