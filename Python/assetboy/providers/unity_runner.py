from __future__ import annotations

import os
import re
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath

from assetboy.library.files import ensure_dir, read_json, write_json, write_text
from assetboy.providers.engine_bridge import emit_engine_export_job
from assetboy.providers.unreal_runner import detect_blender_executable


UNITY_EDITOR_CANDIDATES: tuple[str, ...] = (
    "Editor/Unity.exe",
    "Unity.exe",
)
DEFAULT_UNITY_SEARCH_ROOTS: tuple[Path, ...] = (
    Path(r"C:\Program Files\Unity\Hub\Editor"),
    Path(r"C:\Program Files (x86)\Unity\Hub\Editor"),
    Path(r"C:\Program Files\Unity\Editor"),
    Path(r"D:\Unity\Hub\Editor"),
    Path(r"C:\Unity\Hub\Editor"),
)
UNITY_EXPORTABLE_FORMATS: tuple[str, ...] = ("glb", "gltf", "fbx", "obj", "png", "tga", "wav", "ogg", "mp3")
ASSETBOY_SRC_ROOT = Path(__file__).resolve().parents[2]


def _slug(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def _looks_like_unity_version(value: str) -> bool:
    return bool(re.match(r"^\d{4}\.\d+\.\d+.*$", value))


def _guess_version(path: Path) -> str:
    if _looks_like_unity_version(path.name):
        return path.name
    if _looks_like_unity_version(path.parent.name):
        return path.parent.name
    return path.name


@dataclass(frozen=True)
class UnityInstallation:
    version: str
    root_dir: Path
    editor_path: Path | None
    detection_source: str

    @property
    def usable(self) -> bool:
        return self.editor_path is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "root_dir": str(self.root_dir),
            "editor_path": str(self.editor_path) if self.editor_path else "",
            "detection_source": self.detection_source,
            "usable": self.usable,
        }


@dataclass(frozen=True)
class UnityRunnerJob:
    pack_id: str
    game_scope: str
    engine_job_spec_path: Path
    project_path: Path
    package_root: str
    asset_paths: tuple[str, ...]
    unitypackage_paths: tuple[str, ...]
    staged_export_dir: Path
    payload_target_path: Path
    cleanup_plan_path: Path
    export_formats: tuple[str, ...]
    editor_path_hint: str
    blender_executable_hint: str
    notes: tuple[str, ...]
    detected_installations: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "engine_job_spec_path": str(self.engine_job_spec_path),
            "project_path": str(self.project_path),
            "package_root": self.package_root,
            "asset_paths": list(self.asset_paths),
            "unitypackage_paths": list(self.unitypackage_paths),
            "staged_export_dir": str(self.staged_export_dir),
            "payload_target_path": str(self.payload_target_path),
            "cleanup_plan_path": str(self.cleanup_plan_path),
            "export_formats": list(self.export_formats),
            "editor_path_hint": self.editor_path_hint,
            "blender_executable_hint": self.blender_executable_hint,
            "notes": list(self.notes),
            "detected_installations": list(self.detected_installations),
        }


@dataclass(frozen=True)
class UnityRunnerArtifacts:
    output_dir: Path
    engine_job_spec_path: Path
    runner_job_path: Path
    powershell_path: Path
    unity_csharp_path: Path
    blender_handoff_path: Path
    launch_command_path: Path
    payload_target_path: Path
    editor_path_hint: str

    def to_dict(self) -> dict[str, str]:
        return {
            "output_dir": str(self.output_dir),
            "engine_job_spec_path": str(self.engine_job_spec_path),
            "runner_job_path": str(self.runner_job_path),
            "powershell_path": str(self.powershell_path),
            "unity_csharp_path": str(self.unity_csharp_path),
            "blender_handoff_path": str(self.blender_handoff_path),
            "launch_command_path": str(self.launch_command_path),
            "payload_target_path": str(self.payload_target_path),
            "editor_path_hint": self.editor_path_hint,
        }


def list_unity_installations(search_roots: tuple[Path, ...] | None = None) -> tuple[UnityInstallation, ...]:
    roots = search_roots or DEFAULT_UNITY_SEARCH_ROOTS
    installations: list[UnityInstallation] = []
    seen_roots: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        candidates = [root]
        candidates.extend(child for child in root.iterdir() if child.is_dir())
        for candidate in candidates:
            resolved_root = candidate.resolve()
            if resolved_root in seen_roots:
                continue
            editor_path = next(
                (resolved_root / rel for rel in UNITY_EDITOR_CANDIDATES if (resolved_root / rel).exists()),
                None,
            )
            if editor_path is None:
                continue
            seen_roots.add(resolved_root)
            installations.append(
                UnityInstallation(
                    version=_guess_version(candidate),
                    root_dir=resolved_root,
                    editor_path=editor_path,
                    detection_source="directory_scan",
                )
            )
    return tuple(sorted(installations, key=lambda item: (not item.usable, item.version), reverse=False))


def _load_cleanup_plan(cleanup_plan_path: Path) -> dict[str, object]:
    return read_json(cleanup_plan_path)


def _build_runner_powershell(
    job: UnityRunnerJob,
    *,
    runner_job_name: str = "unity_export_runner.json",
    unity_csharp_name: str = "AssetBoyUnityExporter.cs",
) -> str:
    editor_hint = job.editor_path_hint or "<set Unity.exe path>"
    return "\n".join(
        [
            "param(",
            f"  [string]$UnityEditorPath = \"{editor_hint}\",",
            f"  [string]$ProjectPath = \"{job.project_path}\",",
            f"  [string]$RunnerJson = \"$PSScriptRoot\\{runner_job_name}\",",
            f"  [string]$ExporterScript = \"$PSScriptRoot\\{unity_csharp_name}\",",
            f"  [string]$AssetBoySrc = \"{ASSETBOY_SRC_ROOT}\",",
            "  [string]$ExportMethod = \"AssetBoyUnityExporter.Run\"",
            ")",
            "",
            '$ErrorActionPreference = "Stop"',
            "",
            'if (!(Test-Path $RunnerJson)) { throw "Runner job file not found: $RunnerJson" }',
            '$pythonCode = @"',
            "import json",
            "import sys",
            'sys.path.insert(0, r"$AssetBoySrc")',
            "from assetboy.providers.unity_runner import extract_open_assets_from_runner_job",
            'result = extract_open_assets_from_runner_job(r"$RunnerJson")',
            "print(json.dumps(result, indent=2))",
            '"@',
            '$directExtractJson = $pythonCode | python -',
            'if ($LASTEXITCODE -ne 0) { throw "Direct Unity package extraction failed." }',
            '$directExtract = ($directExtractJson | Out-String | ConvertFrom-Json)',
            'if ($null -ne $directExtract -and [int]$directExtract.exported_count -gt 0) { return }',
            "",
            'if (!(Test-Path $UnityEditorPath)) { throw "Unity editor executable not found: $UnityEditorPath" }',
            'if (!(Test-Path $ProjectPath)) {',
            '  & $UnityEditorPath -batchmode -quit -createProject "$ProjectPath" -logFile "$PSScriptRoot\\unity_create_project.log"',
            '}',
            'if (!(Test-Path $ProjectPath)) { throw "Unity project path could not be created: $ProjectPath" }',
            'if (!(Test-Path $ExporterScript)) { throw "Unity exporter script not found: $ExporterScript" }',
            "",
            '$targetEditorDir = Join-Path $ProjectPath "Assets\\Editor"',
            'if (!(Test-Path $targetEditorDir)) { New-Item -ItemType Directory -Path $targetEditorDir | Out-Null }',
            'Copy-Item $ExporterScript (Join-Path $targetEditorDir "AssetBoyUnityExporter.cs") -Force',
            "",
            '$env:ASSETBOY_UNITY_RUNNER_JSON = $RunnerJson',
            '& $UnityEditorPath -batchmode -quit -projectPath "$ProjectPath" -executeMethod $ExportMethod -logFile "$PSScriptRoot\\unity_export.log"',
        ]
    ) + "\n"


def _normalize_unitypackage_pathname(value: str) -> str:
    cleaned = str(value or "").replace("\x00", "").replace("\\", "/")
    cleaned = cleaned.splitlines()[0] if cleaned.splitlines() else cleaned
    return cleaned.strip()


def _path_is_under_root(asset_path: str, package_root: str) -> bool:
    normalized_asset = _normalize_unitypackage_pathname(asset_path)
    normalized_root = _normalize_unitypackage_pathname(package_root)
    if not normalized_root:
        return True
    asset_parts = PurePosixPath(normalized_asset).parts
    root_parts = PurePosixPath(normalized_root).parts
    if not root_parts:
        return True
    return len(asset_parts) >= len(root_parts) and asset_parts[: len(root_parts)] == root_parts


def _path_matches_selected_assets(asset_path: str, selected_paths: tuple[str, ...]) -> bool:
    if not selected_paths:
        return True
    normalized_asset = _normalize_unitypackage_pathname(asset_path)
    asset_parts = PurePosixPath(normalized_asset).parts
    for selected in selected_paths:
        normalized_selected = _normalize_unitypackage_pathname(selected)
        if not normalized_selected:
            continue
        selected_parts = PurePosixPath(normalized_selected).parts
        if asset_parts == selected_parts:
            return True
        if len(asset_parts) > len(selected_parts) and asset_parts[: len(selected_parts)] == selected_parts:
            return True
    return False


def _relative_unitypackage_export_path(asset_path: str, package_root: str) -> Path | None:
    normalized_asset = _normalize_unitypackage_pathname(asset_path)
    if not normalized_asset:
        return None
    asset_path_obj = PurePosixPath(normalized_asset)
    if asset_path_obj.is_absolute() or any(part == ".." for part in asset_path_obj.parts):
        return None
    normalized_root = _normalize_unitypackage_pathname(package_root)
    if normalized_root:
        root_obj = PurePosixPath(normalized_root)
        try:
            relative = asset_path_obj.relative_to(root_obj)
        except ValueError:
            return None
    else:
        relative = asset_path_obj
    if not relative.parts:
        return None
    return Path(*relative.parts)


def _build_unique_output_path(output_dir: Path, relative_path: Path) -> Path:
    destination = output_dir / relative_path
    if len(str(destination)) > 230:
        parent_slug_parts = [_slug(part, "") for part in relative_path.parts[-3:-1] if part not in {"", ".", ".."}]
        stem = _slug(relative_path.stem, "asset")
        suffix = relative_path.suffix
        file_name = "_".join(part for part in (*parent_slug_parts, stem) if part)
        if not file_name:
            file_name = "asset"
        max_stem_length = max(24, 180 - len(str(output_dir)) - len(suffix))
        file_name = file_name[:max_stem_length]
        destination = output_dir / f"{file_name}{suffix}"
    if not destination.exists():
        return destination
    base_name = relative_path.stem or "asset"
    suffix = relative_path.suffix
    parent = destination.parent
    counter = 1
    while True:
        candidate = parent / f"{base_name}_{counter:02d}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def extract_open_assets_from_unitypackage(
    *,
    package_path: str | Path,
    output_dir: str | Path,
    package_root: str = "Assets",
    asset_paths: tuple[str, ...] = (),
    export_formats: tuple[str, ...] = UNITY_EXPORTABLE_FORMATS,
) -> dict[str, object]:
    package_file = Path(package_path)
    staged_root = ensure_dir(output_dir)
    exportable_extensions = {f".{fmt.lower().lstrip('.')}" for fmt in export_formats}
    results: list[dict[str, str]] = []
    exported_count = 0
    roots_seen = 0
    roots_with_payload = 0

    with tarfile.open(package_file, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
        roots = sorted({member.name.split("/", 1)[0] for member in archive.getmembers() if "/" in member.name})
        roots_seen = len(roots)
        for root in roots:
            pathname_member = members.get(f"{root}/pathname")
            asset_member = members.get(f"{root}/asset")
            if pathname_member is None or asset_member is None:
                continue
            roots_with_payload += 1
            with archive.extractfile(pathname_member) as handle:
                raw_asset_path = handle.read().decode("utf-8", "replace")
            asset_path = _normalize_unitypackage_pathname(raw_asset_path)
            if not asset_path:
                continue
            if not _path_is_under_root(asset_path, package_root):
                continue
            if not _path_matches_selected_assets(asset_path, asset_paths):
                continue
            extension = os.path.splitext(asset_path)[1].lower()
            if extension not in exportable_extensions:
                continue
            relative_path = _relative_unitypackage_export_path(asset_path, package_root)
            if relative_path is None:
                continue
            destination = _build_unique_output_path(staged_root, relative_path)
            ensure_dir(destination.parent)
            with archive.extractfile(asset_member) as source_handle, destination.open("wb") as output_handle:
                shutil.copyfileobj(source_handle, output_handle)
            exported_count += 1
            results.append(
                {
                    "asset_path": asset_path,
                    "status": "exported",
                    "file_path": str(destination),
                    "message": "direct unitypackage open-format extract",
                }
            )

    return {
        "package_path": str(package_file),
        "output_dir": str(staged_root),
        "package_root": package_root,
        "roots_seen": roots_seen,
        "roots_with_payload": roots_with_payload,
        "exported_count": exported_count,
        "results": results,
    }


def extract_open_assets_from_runner_job(runner_job_path: str | Path) -> dict[str, object]:
    runner_path = Path(runner_job_path)
    payload = read_json(runner_path)
    staged_export_dir = Path(payload["staged_export_dir"])
    if staged_export_dir.exists():
        shutil.rmtree(staged_export_dir)
    ensure_dir(staged_export_dir)

    package_root = str(payload.get("package_root", "Assets") or "Assets")
    selected_asset_paths = tuple(str(path) for path in payload.get("asset_paths", []) if str(path).strip())
    export_formats = tuple(str(fmt) for fmt in payload.get("export_formats", []) if str(fmt).strip()) or UNITY_EXPORTABLE_FORMATS
    package_summaries: list[dict[str, object]] = []
    combined_results: list[dict[str, str]] = []
    exported_count = 0

    for package_path in payload.get("unitypackage_paths", []):
        package_summary = extract_open_assets_from_unitypackage(
            package_path=package_path,
            output_dir=staged_export_dir,
            package_root=package_root,
            asset_paths=selected_asset_paths,
            export_formats=export_formats,
        )
        package_summaries.append(package_summary)
        exported_count += int(package_summary["exported_count"])
        combined_results.extend(package_summary["results"])

    summary = {
        "mode": "unitypackage_direct_extract",
        "runner_job_path": str(runner_path),
        "staged_export_dir": str(staged_export_dir),
        "package_root": package_root,
        "selected_asset_paths": list(selected_asset_paths),
        "exported_count": exported_count,
        "packages": package_summaries,
        "results": combined_results,
    }
    write_json(staged_export_dir / "export_summary.json", summary)
    return summary


def _build_unity_csharp() -> str:
    return "\n".join(
        [
            "using System;",
            "using System.Collections.Generic;",
            "using System.IO;",
            "using System.Linq;",
            "using System.Text.RegularExpressions;",
            "using UnityEditor;",
            "using UnityEngine;",
            "",
            "public static class AssetBoyUnityExporter",
            "{",
            "    [Serializable]",
            "    private class RunnerPayload",
            "    {",
            "        public string staged_export_dir = \"\";",
            "        public string package_root = \"Assets\";",
            "        public string[] asset_paths = Array.Empty<string>();",
            "        public string[] unitypackage_paths = Array.Empty<string>();",
            "    }",
            "",
            "    [Serializable]",
            "    private class ItemResult",
            "    {",
            "        public string asset_path = \"\";",
            "        public string status = \"\";",
            "        public string file_path = \"\";",
            "        public string message = \"\";",
            "    }",
            "",
            "    [Serializable]",
            "    private class SummaryPayload",
            "    {",
            "        public ItemResult[] results = Array.Empty<ItemResult>();",
            "    }",
            "",
            "    private static readonly HashSet<string> CopyExtensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase)",
            "    {",
            "        \".fbx\", \".glb\", \".gltf\", \".obj\", \".png\", \".tga\", \".wav\", \".ogg\", \".mp3\"",
            "    };",
            "",
            "    private static readonly HashSet<string> SkipExtensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase)",
            "    {",
            "        \".cs\", \".dll\", \".asmdef\", \".meta\", \".shader\", \".cginc\", \".hlsl\", \".unitypackage\"",
            "    };",
            "",
            "    public static void Run()",
            "    {",
            "        var runnerJsonPath = Environment.GetEnvironmentVariable(\"ASSETBOY_UNITY_RUNNER_JSON\") ?? string.Empty;",
            "        if (string.IsNullOrWhiteSpace(runnerJsonPath) || !File.Exists(runnerJsonPath))",
            "        {",
            "            Debug.LogError(\"AssetBoy Unity export failed: ASSETBOY_UNITY_RUNNER_JSON is missing or invalid.\");",
            "            EditorApplication.Exit(2);",
            "            return;",
            "        }",
            "",
            "        var payload = JsonUtility.FromJson<RunnerPayload>(File.ReadAllText(runnerJsonPath));",
            "        if (payload == null || string.IsNullOrWhiteSpace(payload.staged_export_dir))",
            "        {",
            "            Debug.LogError(\"AssetBoy Unity export failed: runner payload is invalid.\");",
            "            EditorApplication.Exit(2);",
            "            return;",
            "        }",
            "",
            "        Directory.CreateDirectory(payload.staged_export_dir);",
            "        var preImportAssetPaths = new HashSet<string>(ResolveAssetPaths(payload), StringComparer.OrdinalIgnoreCase);",
            "        ImportUnityPackages(payload);",
            "        AssetDatabase.Refresh();",
            "        var assetPaths = ResolveAssetPaths(payload);",
            "        if ((payload.asset_paths == null || payload.asset_paths.Length == 0) && payload.unitypackage_paths != null && payload.unitypackage_paths.Length > 0)",
            "        {",
            "            var importedAssetPaths = assetPaths.Where(path => !preImportAssetPaths.Contains(path)).ToList();",
            "            if (importedAssetPaths.Count > 0)",
            "            {",
            "                assetPaths = importedAssetPaths;",
            "            }",
            "        }",
            "        var results = new List<ItemResult>();",
            "        foreach (var assetPath in assetPaths)",
            "        {",
            "            try",
            "            {",
            "                results.Add(ExportAsset(assetPath, payload.staged_export_dir));",
            "            }",
            "            catch (Exception ex)",
            "            {",
            "                results.Add(new ItemResult { asset_path = assetPath, status = \"error\", message = ex.Message });",
            "            }",
            "        }",
            "",
            "        var summary = new SummaryPayload { results = results.ToArray() };",
            "        var summaryPath = Path.Combine(payload.staged_export_dir, \"export_summary.json\");",
            "        File.WriteAllText(summaryPath, JsonUtility.ToJson(summary, true));",
            "        AssetDatabase.Refresh();",
            "        Debug.Log(\"AssetBoy Unity export finished: \" + summaryPath);",
            "        EditorApplication.Exit(0);",
            "    }",
            "",
            "    private static void ImportUnityPackages(RunnerPayload payload)",
            "    {",
            "        if (payload.unitypackage_paths == null || payload.unitypackage_paths.Length == 0)",
            "        {",
            "            return;",
            "        }",
            "        foreach (var packagePath in payload.unitypackage_paths.Where(path => !string.IsNullOrWhiteSpace(path)).Distinct(StringComparer.OrdinalIgnoreCase))",
            "        {",
            "            if (!File.Exists(packagePath))",
            "            {",
            "                Debug.LogWarning(\"AssetBoy Unity import skipped missing package: \" + packagePath);",
            "                continue;",
            "            }",
            "            Debug.Log(\"AssetBoy importing Unity package: \" + packagePath);",
            "            AssetDatabase.ImportPackage(packagePath, false);",
            "        }",
            "    }",
            "",
            "    private static List<string> ResolveAssetPaths(RunnerPayload payload)",
            "    {",
            "        var paths = new List<string>();",
            "        if (payload.asset_paths != null && payload.asset_paths.Length > 0)",
            "        {",
            "            paths.AddRange(payload.asset_paths.Where(path => !string.IsNullOrWhiteSpace(path)));",
            "            return paths.Distinct(StringComparer.OrdinalIgnoreCase).ToList();",
            "        }",
            "",
            "        var packageRoot = string.IsNullOrWhiteSpace(payload.package_root) ? \"Assets\" : payload.package_root;",
            "        var guids = AssetDatabase.FindAssets(string.Empty, new[] { packageRoot });",
            "        foreach (var guid in guids)",
            "        {",
            "            var path = AssetDatabase.GUIDToAssetPath(guid);",
            "            if (string.IsNullOrWhiteSpace(path) || AssetDatabase.IsValidFolder(path))",
            "            {",
            "                continue;",
            "            }",
            "            paths.Add(path);",
            "        }",
            "        return paths.Distinct(StringComparer.OrdinalIgnoreCase).ToList();",
            "    }",
            "",
            "    private static ItemResult ExportAsset(string assetPath, string exportDir)",
            "    {",
            "        var extension = Path.GetExtension(assetPath).ToLowerInvariant();",
            "        if (SkipExtensions.Contains(extension))",
            "        {",
            "            return new ItemResult { asset_path = assetPath, status = \"skipped\", message = \"non-exportable extension\" };",
            "        }",
            "        if (!CopyExtensions.Contains(extension))",
            "        {",
            "            return new ItemResult { asset_path = assetPath, status = \"skipped\", message = \"no open-format exporter configured\" };",
            "        }",
            "",
            "        var sourceFile = Path.GetFullPath(Path.Combine(Directory.GetCurrentDirectory(), assetPath));",
            "        if (!File.Exists(sourceFile))",
            "        {",
            "            return new ItemResult { asset_path = assetPath, status = \"missing\", message = \"source file not found\" };",
            "        }",
            "",
            "        var baseName = Sanitize(Path.GetFileNameWithoutExtension(assetPath));",
            "        var destination = BuildUniquePath(exportDir, baseName, extension);",
            "        File.Copy(sourceFile, destination, true);",
            "        return new ItemResult",
            "        {",
            "            asset_path = assetPath,",
            "            status = \"exported\",",
            "            file_path = destination,",
            "            message = \"copied open-format asset\"",
            "        };",
            "    }",
            "",
            "    private static string BuildUniquePath(string exportDir, string baseName, string extension)",
            "    {",
            "        var candidate = Path.Combine(exportDir, baseName + extension);",
            "        var index = 1;",
            "        while (File.Exists(candidate))",
            "        {",
            "            candidate = Path.Combine(exportDir, $\"{baseName}_{index:00}{extension}\");",
            "            index += 1;",
            "        }",
            "        return candidate;",
            "    }",
            "",
            "    private static string Sanitize(string value)",
            "    {",
            "        var cleaned = Regex.Replace(value ?? string.Empty, \"[^A-Za-z0-9._-]+\", \"_\");",
            "        cleaned = cleaned.Trim('_', '.', '-');",
            "        return string.IsNullOrWhiteSpace(cleaned) ? \"asset\" : cleaned;",
            "    }",
            "}",
            "",
        ]
    )


def emit_unity_export_runner(
    *,
    pack_id: str,
    game_scope: str,
    source_url: str,
    license_note: str,
    project_path: str | Path,
    package_root: str = "Assets",
    asset_paths: tuple[str, ...] = (),
    unitypackage_paths: tuple[str, ...] = (),
    source_package_name: str = "",
    asset_kind: str = "prop",
    output_dir: str | Path | None = None,
    notes: tuple[str, ...] = (),
    unity_search_roots: tuple[Path, ...] | None = None,
    blender_search_roots: tuple[Path, ...] | None = None,
) -> UnityRunnerArtifacts:
    engine_artifacts = emit_engine_export_job(
        engine="unity",
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        license_note=license_note,
        source_package_name=source_package_name,
        asset_kind=asset_kind,
        output_dir=output_dir,
        notes=notes,
    )
    installations = list_unity_installations(search_roots=unity_search_roots)
    preferred_install = next((item for item in installations if item.usable), None)
    blender_path = detect_blender_executable(search_roots=blender_search_roots)
    cleanup_plan = _load_cleanup_plan(engine_artifacts.cleanup_plan_path)
    engine_job = read_json(engine_artifacts.job_spec_path)
    staged_export_dir = engine_artifacts.output_dir / "staged_exports"
    runner_job = UnityRunnerJob(
        pack_id=pack_id,
        game_scope=game_scope,
        engine_job_spec_path=engine_artifacts.job_spec_path,
        project_path=Path(project_path),
        package_root=package_root,
        asset_paths=asset_paths,
        unitypackage_paths=unitypackage_paths,
        staged_export_dir=staged_export_dir,
        payload_target_path=engine_artifacts.payload_target_path,
        cleanup_plan_path=engine_artifacts.cleanup_plan_path,
        export_formats=tuple(
            fmt for fmt in engine_job["export_formats"] if fmt in UNITY_EXPORTABLE_FORMATS
        ),
        editor_path_hint=str(preferred_install.editor_path) if preferred_install and preferred_install.editor_path else "",
        blender_executable_hint=str(blender_path) if blender_path else "",
        notes=notes,
        detected_installations=tuple(item.to_dict() for item in installations),
    )
    runner_job_path = write_json(engine_artifacts.output_dir / "unity_export_runner.json", runner_job.to_dict())
    unity_csharp_path = write_text(engine_artifacts.output_dir / "AssetBoyUnityExporter.cs", _build_unity_csharp())
    powershell_path = write_text(
        engine_artifacts.output_dir / "run_unity_export.ps1",
        _build_runner_powershell(
            runner_job,
            runner_job_name=runner_job_path.name,
            unity_csharp_name=unity_csharp_path.name,
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
        "next_step": "Run Blender cleanup on the staged Unity exports, then copy accepted outputs into the payload target.",
    }
    blender_handoff_path = write_json(engine_artifacts.output_dir / "blender_handoff.json", blender_handoff)
    launch_command = f'pwsh -ExecutionPolicy Bypass -File "{powershell_path}"\n'
    launch_command_path = write_text(engine_artifacts.output_dir / "launch_unity_export.txt", launch_command)
    return UnityRunnerArtifacts(
        output_dir=engine_artifacts.output_dir,
        engine_job_spec_path=engine_artifacts.job_spec_path,
        runner_job_path=runner_job_path,
        powershell_path=powershell_path,
        unity_csharp_path=unity_csharp_path,
        blender_handoff_path=blender_handoff_path,
        launch_command_path=launch_command_path,
        payload_target_path=engine_artifacts.payload_target_path,
        editor_path_hint=runner_job.editor_path_hint,
    )
