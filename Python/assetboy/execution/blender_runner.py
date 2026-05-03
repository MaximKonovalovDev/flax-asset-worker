"""
blender_runner.py — Emits an actionable Blender cleanup runbook for Blender MCP.

When the blender MCP server is active in the current session, the AI can
call these functions to drive Blender directly from a chat command. The CLI
path prepares a cleanup plan plus concrete Blender MCP tool calls aligned
with the local blender-mcp 0.1.6 tool surface. Actual Blender execution
still happens in the MCP/chat session or by a human operator.

Usage (via CLI):
    python -m assetboy.cli run-blender-cleanup --pack-id RA_PACK_WPN_COMBAT_SLICE_01 --input-dir C:\\path\\to\\raw
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from assetboy.cleanup.blender_mcp import CleanupPlan, build_cleanup_plan
from assetboy.library.paths import generated_output_root, manual_drop_dir, publish_payload_dir
from assetboy.workflows.roman_first_playable import get_roman_first_playable_spec, roman_first_playable_specs


@dataclass
class BlenderRunResult:
    pack_id: str
    input_dir: Path
    output_dir: Path
    steps_run: list[str]
    export_formats: list[str]
    dry_run: bool
    cleanup_plan_path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "input_dir": str(self.input_dir),
            "output_dir": str(self.output_dir),
            "steps_run": self.steps_run,
            "export_formats": self.export_formats,
            "dry_run": self.dry_run,
            "cleanup_plan_path": str(self.cleanup_plan_path) if self.cleanup_plan_path else None,
        }


@dataclass
class RomanCleanupPackResult:
    pack_id: str
    roman_category: str
    blender_required: bool
    status: str
    asset_kind: str
    animated: bool
    source_lane: str
    source_adapter: str
    input_dir: Path | None = None
    output_dir: Path | None = None
    cleanup_plan_path: Path | None = None
    export_formats: list[str] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    candidate_input_dirs: list[str] = field(default_factory=list)
    blocker_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "pack_id": self.pack_id,
            "roman_category": self.roman_category,
            "blender_required": self.blender_required,
            "status": self.status,
            "asset_kind": self.asset_kind,
            "animated": self.animated,
            "source_lane": self.source_lane,
            "source_adapter": self.source_adapter,
            "input_dir": str(self.input_dir) if self.input_dir else "",
            "output_dir": str(self.output_dir) if self.output_dir else "",
            "cleanup_plan_path": str(self.cleanup_plan_path) if self.cleanup_plan_path else "",
            "export_formats": list(self.export_formats),
            "source_files": list(self.source_files),
            "candidate_input_dirs": list(self.candidate_input_dirs),
            "blocker_reasons": list(self.blocker_reasons),
        }


@dataclass
class RomanCleanupWaveResult:
    game_scope: str
    output_dir: Path
    manifest_path: Path
    summary_path: Path
    total_packs: int
    blender_required_packs: int
    cleanup_ready_packs: int
    blocked_packs: int
    skipped_packs: int
    packs: list[RomanCleanupPackResult]

    def to_dict(self) -> dict[str, object]:
        return {
            "game_scope": self.game_scope,
            "output_dir": str(self.output_dir),
            "manifest_path": str(self.manifest_path),
            "summary_path": str(self.summary_path),
            "total_packs": self.total_packs,
            "blender_required_packs": self.blender_required_packs,
            "cleanup_ready_packs": self.cleanup_ready_packs,
            "blocked_packs": self.blocked_packs,
            "skipped_packs": self.skipped_packs,
            "packs": [item.to_dict() for item in self.packs],
        }


_SUPPORTED_CLEANUP_INPUT_SUFFIXES = {".fbx", ".glb", ".gltf", ".obj"}
_MOCK_INPUT_TOKENS = ("_mock.", "placeholder", "stub", "example")


def run_blender_cleanup(
    *,
    pack_id: str,
    input_dir: str | Path,
    asset_kind: str = "prop",
    source_lane: str = "generator",
    animated: bool = False,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
    quiet: bool = False,
) -> BlenderRunResult:
    """
    Build a Blender MCP cleanup plan for a pack.

    Executes the steps from a CleanupPlan:
      1. normalize_origin_to_grounded_pivot
      2. apply_scale_in_meters
      3. run_basic_ascii_naming_cleanup
      4. prune_helper_and_lod_meshes
      5. export (GLB and/or FBX based on asset_kind)

    When dry_run=True, steps are printed as a runbook without calling Blender.
    When dry_run=False, outputs the exact MCP tool calls needed.
    """
    plan = build_cleanup_plan(
        pack_id=pack_id,
        asset_kind=asset_kind,
        source_lane=source_lane,
        animated=animated,
    )

    in_dir = Path(input_dir)
    out_dir = (
        Path(output_dir) if output_dir is not None
        else generated_output_root() / "blender_cleanup" / pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    export_formats = list(plan.export_decision.export_targets)
    steps_run = list(plan.steps)

    blender_calls = _build_blender_mcp_calls(plan, in_dir, out_dir, export_formats)
    if not quiet:
        mode = "DRY RUN" if dry_run else "PLAN"
        print(f"[{mode}] Blender cleanup: {pack_id}")
        print(f"Input:  {in_dir}")
        print(f"Output: {out_dir}")
        print(f"Asset kind: {asset_kind} | Animated: {animated}")
        print(f"Export formats: {', '.join(export_formats)}")
        print()
        print("=== Blender MCP Steps ===")
        for i, call in enumerate(blender_calls, 1):
            print(f"  {i}. {call}")
        print()

        if not dry_run:
            print(">>> This command emits the cleanup plan only; it does not invoke Blender MCP directly.")
            print(">>> Run the emitted steps in Blender MCP or follow the plan manually.")

    # Write the plan JSON to the output dir for reference
    plan_out = out_dir / "cleanup_plan.json"
    plan_out.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")

    return BlenderRunResult(
        pack_id=pack_id,
        input_dir=in_dir,
        output_dir=out_dir,
        steps_run=steps_run,
        export_formats=export_formats,
        dry_run=dry_run,
        cleanup_plan_path=plan_out,
    )


def _is_mock_input(path: Path) -> bool:
    lowered = path.name.lower()
    return any(token in lowered for token in _MOCK_INPUT_TOKENS)


def _cleanup_source_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return [
        path
        for path in sorted(directory.rglob("*"))
        if path.is_file()
        and path.suffix.lower() in _SUPPORTED_CLEANUP_INPUT_SUFFIXES
        and not _is_mock_input(path)
    ]


def _roman_cleanup_candidate_dirs(
    *,
    pack_id: str,
    game_scope: str,
    source_adapter: str,
    fallback_adapters: Sequence[str] = (),
    input_root: str | Path | None = None,
) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def _append(path: Path | None) -> None:
        if path is None:
            return
        resolved = str(path.resolve())
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(path.resolve())

    if input_root is not None:
        root = Path(input_root).resolve()
        _append(root / pack_id)

    manual_root = manual_drop_dir()
    _append(manual_root / pack_id)

    adapter_dirs = {source_adapter}
    for fallback in fallback_adapters:
        if str(fallback).strip():
            adapter_dirs.add(str(fallback).strip())
    if source_adapter.startswith("mixamo"):
        adapter_dirs.add("mixamo")
    if any(str(adapter).startswith("mixamo") for adapter in adapter_dirs):
        adapter_dirs.add("mixamo")
    if source_adapter == "fab":
        adapter_dirs.add("fab")
    if source_adapter == "unity_asset_store":
        adapter_dirs.add("unity_asset_store")

    for adapter_dir in sorted(adapter_dirs):
        _append(manual_root / adapter_dir / pack_id)

    _append(publish_payload_dir(game_scope=game_scope, pack_id=pack_id))
    return candidates


def _build_roman_cleanup_summary(
    *,
    game_scope: str,
    packs: Sequence[RomanCleanupPackResult],
    cleanup_ready_packs: int,
    blocked_packs: int,
    skipped_packs: int,
) -> str:
    lines = [
        "# Roman Blender Cleanup Wave",
        "",
        f"- Game scope: `{game_scope}`",
        f"- Cleanup-ready packs: `{cleanup_ready_packs}`",
        f"- Blocked packs: `{blocked_packs}`",
        f"- Skipped non-Blender packs: `{skipped_packs}`",
        "",
        "## Pack Status",
    ]
    for pack in packs:
        lines.append(
            f"- `{pack.pack_id}` [{pack.status}] kind=`{pack.asset_kind}` animated=`{str(pack.animated).lower()}`"
        )
        if pack.input_dir is not None:
            lines.append(f"- input: `{pack.input_dir}`")
        if pack.cleanup_plan_path is not None:
            lines.append(f"- cleanup plan: `{pack.cleanup_plan_path}`")
        if pack.blocker_reasons:
            lines.append(f"- blockers: `{' | '.join(pack.blocker_reasons)}`")
    return "\n".join(lines) + "\n"


def run_roman_blender_cleanup_wave(
    *,
    game_scope: str = "roman_arena",
    pack_ids: Sequence[str] | None = None,
    input_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
) -> RomanCleanupWaveResult:
    requested_pack_ids = {str(item).strip() for item in (pack_ids or []) if str(item).strip()}
    specs = [spec for spec in roman_first_playable_specs() if not requested_pack_ids or spec.pack_id in requested_pack_ids]
    if requested_pack_ids and len(specs) != len(requested_pack_ids):
        known = {spec.pack_id for spec in roman_first_playable_specs()}
        missing = sorted(requested_pack_ids - known)
        raise KeyError(f"Unknown Roman cleanup pack ids: {', '.join(missing)}")

    root_dir = (
        Path(output_dir).resolve()
        if output_dir is not None
        else (generated_output_root() / "roman_blender_cleanup" / game_scope).resolve()
    )
    root_dir.mkdir(parents=True, exist_ok=True)

    pack_results: list[RomanCleanupPackResult] = []
    for spec in specs:
        if not spec.blender_required:
            pack_results.append(
                RomanCleanupPackResult(
                    pack_id=spec.pack_id,
                    roman_category=spec.roman_category,
                    blender_required=False,
                    status="skipped_no_blender",
                    asset_kind=spec.asset_kind,
                    animated=spec.animated,
                    source_lane=spec.bootstrap_lane.value,
                    source_adapter=spec.source_adapter,
                )
            )
            continue

        candidates = _roman_cleanup_candidate_dirs(
            pack_id=spec.pack_id,
            game_scope=game_scope,
            source_adapter=spec.source_adapter,
            fallback_adapters=spec.fallback_adapters,
            input_root=input_root,
        )

        selected_input_dir: Path | None = None
        selected_files: list[Path] = []
        for candidate in candidates:
            source_files = _cleanup_source_files(candidate)
            if source_files:
                selected_input_dir = candidate
                selected_files = source_files
                break

        if selected_input_dir is None:
            pack_results.append(
                RomanCleanupPackResult(
                    pack_id=spec.pack_id,
                    roman_category=spec.roman_category,
                    blender_required=True,
                    status="missing_input",
                    asset_kind=spec.asset_kind,
                    animated=spec.animated,
                    source_lane=spec.bootstrap_lane.value,
                    source_adapter=spec.source_adapter,
                    candidate_input_dirs=[str(path) for path in candidates],
                    blocker_reasons=["No real .fbx/.glb/.gltf/.obj inputs found in the expected Roman source folders."],
                )
            )
            continue

        pack_output_dir = root_dir / spec.pack_id
        cleanup_result = run_blender_cleanup(
            pack_id=spec.pack_id,
            input_dir=selected_input_dir,
            asset_kind=spec.asset_kind,
            source_lane=spec.bootstrap_lane.value,
            animated=spec.animated,
            output_dir=pack_output_dir,
            dry_run=dry_run,
            quiet=True,
        )
        pack_results.append(
            RomanCleanupPackResult(
                pack_id=spec.pack_id,
                roman_category=spec.roman_category,
                blender_required=True,
                status="cleanup_ready",
                asset_kind=spec.asset_kind,
                animated=spec.animated,
                source_lane=spec.bootstrap_lane.value,
                source_adapter=spec.source_adapter,
                input_dir=selected_input_dir,
                output_dir=cleanup_result.output_dir,
                cleanup_plan_path=cleanup_result.cleanup_plan_path,
                export_formats=list(cleanup_result.export_formats),
                source_files=[path.name for path in selected_files],
                candidate_input_dirs=[str(path) for path in candidates],
            )
        )

    cleanup_ready_packs = sum(1 for item in pack_results if item.status == "cleanup_ready")
    blocked_packs = sum(1 for item in pack_results if item.status == "missing_input")
    skipped_packs = sum(1 for item in pack_results if item.status == "skipped_no_blender")
    blender_required_packs = sum(1 for item in pack_results if item.blender_required)

    manifest_payload = {
        "schema_version": "assetboy.roman_blender_cleanup_wave.v1",
        "game_scope": game_scope,
        "output_dir": str(root_dir),
        "total_packs": len(pack_results),
        "blender_required_packs": blender_required_packs,
        "cleanup_ready_packs": cleanup_ready_packs,
        "blocked_packs": blocked_packs,
        "skipped_packs": skipped_packs,
        "packs": [item.to_dict() for item in pack_results],
    }
    manifest_path = root_dir / "roman_blender_cleanup_wave.json"
    manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    summary_path = root_dir / "README.md"
    summary_path.write_text(
        _build_roman_cleanup_summary(
            game_scope=game_scope,
            packs=pack_results,
            cleanup_ready_packs=cleanup_ready_packs,
            blocked_packs=blocked_packs,
            skipped_packs=skipped_packs,
        ),
        encoding="utf-8",
    )

    return RomanCleanupWaveResult(
        game_scope=game_scope,
        output_dir=root_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
        total_packs=len(pack_results),
        blender_required_packs=blender_required_packs,
        cleanup_ready_packs=cleanup_ready_packs,
        blocked_packs=blocked_packs,
        skipped_packs=skipped_packs,
        packs=pack_results,
    )


def _build_blender_mcp_calls(
    plan: CleanupPlan,
    input_dir: Path,
    output_dir: Path,
    export_formats: list[str],
) -> list[str]:
    """Generate Blender MCP tool calls using the local proxy's real tool names."""
    calls = [
        _render_tool_call(
            "scene_get_overview",
            note="Confirm the Blender MCP addon server is running before cleanup begins.",
        ),
        _render_tool_call(
            "execute_python",
            {
                "code": _build_import_script(input_dir),
                "timeout": 120.0,
            },
            note="Import every mesh source from the input folder into the current scene.",
        ),
        _render_tool_call(
            "scene_get_hierarchy",
            {
                "include_hidden": True,
                "max_depth": 2,
            },
            note="Capture imported mesh and armature names for validation and export targeting.",
        ),
        _render_tool_call(
            "execute_python",
            {
                "code": _build_cleanup_script(plan),
                "timeout": 120.0,
            },
            note="Apply scale, ground the pivot, normalize ASCII names, and prune helper objects.",
        ),
    ]

    if "generate_lod_chain" in plan.steps:
        calls.append(
            _render_tool_call(
                "execute_python",
                {
                    "code": _build_lod_script(),
                    "timeout": 120.0,
                },
                note="Generate LOD1 and LOD2 from the primary mesh using Decimate modifiers.",
            )
        )

    calls.extend(
        [
            _render_tool_call(
                "viewport_screenshot_angles",
                {
                    "angles": ["FRONT", "RIGHT", "TOP", "PERSPECTIVE"],
                    "shading_mode": "MATERIAL",
                    "show_overlays": False,
                    "resolution_x": 768,
                    "resolution_y": 768,
                    "frame_selection": True,
                },
                note="Capture review screenshots after cleanup and before export.",
            ),
            _render_tool_call(
                "unity_validate_mesh",
                {
                    "object_name": "<primary_mesh_from_scene_get_hierarchy>",
                    "vertex_limit": 65535,
                    "mobile_target": False,
                    "check_uvs": True,
                    "check_scale": True,
                    "check_ngons": True,
                },
                note="Replace the placeholder with the hero mesh name from the hierarchy snapshot.",
            ),
        ]
    )

    if plan.animated:
        calls.append(
            _render_tool_call(
                "unity_validate_rig",
                {
                    "object_name": "<armature_name_from_scene_get_hierarchy>",
                    "check_humanoid": True,
                    "check_t_pose": True,
                    "check_hierarchy": True,
                    "t_pose_tolerance": 30.0,
                },
                note="Run rig validation for animated or character exports.",
            )
        )

    calls.append(
        _render_tool_call(
            "viewport_screenshot",
            {
                "shading_mode": "MATERIAL",
                "show_overlays": False,
                "show_gizmos": False,
                "resolution_x": 1024,
                "resolution_y": 1024,
                "transparent_background": False,
            },
            note="Store a single hero preview for cleanup review logs.",
        )
    )

    if any(fmt in {"fbx", "glb"} for fmt in export_formats):
        calls.append(
            _render_tool_call(
                "unity_export_textures",
                {
                    "output_dir": str(output_dir / "textures"),
                    "objects": [],
                    "format": "PNG",
                    "normal_map_format": "OPENGL",
                },
                note="Export linked textures beside the mesh payloads when materials are present.",
            )
        )

    for fmt in export_formats:
        out_path = output_dir / f"{plan.pack_id}.{fmt}"
        if fmt == "glb":
            calls.append(
                _render_tool_call(
                    "execute_python",
                    {
                        "code": _build_glb_export_script(out_path),
                        "timeout": 120.0,
                    },
                    note="Export a GLB review build from the cleaned scene.",
                )
            )
        elif fmt == "fbx":
            calls.append(
                _render_tool_call(
                    "unity_export_fbx",
                    {
                        "filepath": str(out_path),
                        "objects": [],
                        "apply_modifiers": True,
                        "triangulate": True,
                        "include_animation": plan.animated,
                        "bake_animation": plan.animated,
                    },
                    note="Export a Unity/Flax-friendly FBX from the cleaned scene.",
                )
            )
    return calls


def _render_tool_call(
    tool_name: str,
    params: dict[str, object] | None = None,
    *,
    note: str | None = None,
) -> str:
    rendered = f"{tool_name}()" if not params else f"{tool_name}({json.dumps(params, ensure_ascii=True)})"
    if note:
        return f"{rendered}  # {note}"
    return rendered


def _build_import_script(input_dir: Path) -> str:
    return (
        "from pathlib import Path\n"
        "import bpy\n"
        f"source_dir = Path(r\"{input_dir}\")\n"
        "imported = []\n"
        "for path in sorted(source_dir.iterdir()):\n"
        "    suffix = path.suffix.lower()\n"
        "    if suffix == '.fbx':\n"
        "        bpy.ops.import_scene.fbx(filepath=str(path))\n"
        "        imported.append(path.name)\n"
        "    elif suffix in {'.glb', '.gltf'}:\n"
        "        bpy.ops.import_scene.gltf(filepath=str(path))\n"
        "        imported.append(path.name)\n"
        "    elif suffix == '.obj':\n"
        "        bpy.ops.wm.obj_import(filepath=str(path))\n"
        "        imported.append(path.name)\n"
        "result = {'source_dir': str(source_dir), 'imported_files': imported}\n"
    )


def _build_cleanup_script(plan: CleanupPlan) -> str:
    prune_tokens = json.dumps(list(plan.prune_tokens), ensure_ascii=True)
    return (
        "import bpy\n"
        "import re\n"
        f"PRUNE_TOKENS = {prune_tokens}\n"
        "def snake_case_ascii(value: str) -> str:\n"
        "    cleaned = value.encode('ascii', 'ignore').decode('ascii')\n"
        "    cleaned = re.sub(r'[^A-Za-z0-9]+', '_', cleaned.strip().lower()).strip('_')\n"
        "    return cleaned or 'asset'\n"
        "mesh_names = []\n"
        "for obj in list(bpy.data.objects):\n"
        "    lowered = obj.name.lower()\n"
        "    if any(token in lowered for token in PRUNE_TOKENS):\n"
        "        bpy.data.objects.remove(obj, do_unlink=True)\n"
        "for obj in [o for o in bpy.data.objects if o.type == 'MESH']:\n"
        "    bpy.ops.object.select_all(action='DESELECT')\n"
        "    obj.select_set(True)\n"
        "    bpy.context.view_layer.objects.active = obj\n"
        "    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)\n"
        "    bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='BOUNDS')\n"
        "    if obj.data.vertices:\n"
        "        min_z = min((obj.matrix_world @ vertex.co).z for vertex in obj.data.vertices)\n"
        "        obj.location.z -= min_z\n"
        "    obj.name = snake_case_ascii(obj.name)\n"
        "    mesh_names.append(obj.name)\n"
        "    obj.select_set(False)\n"
        "result = {'mesh_objects': mesh_names, 'pack_id': "
        f"'{plan.pack_id}'"
        "}\n"
    )


def _build_lod_script() -> str:
    return (
        "import bpy\n"
        "mesh_objects = [obj for obj in bpy.data.objects if obj.type == 'MESH']\n"
        "created = []\n"
        "if mesh_objects:\n"
        "    source = mesh_objects[0]\n"
        "    for suffix, ratio in [('LOD1', 0.5), ('LOD2', 0.15)]:\n"
        "        lod = source.copy()\n"
        "        lod.data = source.data.copy()\n"
        "        lod.name = f'{source.name}_{suffix}'\n"
        "        bpy.context.collection.objects.link(lod)\n"
        "        modifier = lod.modifiers.new(name=f'{suffix}_Decimate', type='DECIMATE')\n"
        "        modifier.ratio = ratio\n"
        "        created.append(lod.name)\n"
        "result = {'lods_created': created}\n"
    )


def _build_glb_export_script(output_path: Path) -> str:
    return (
        "import bpy\n"
        f"bpy.ops.export_scene.gltf(filepath=r\"{output_path}\", export_format='GLB')\n"
        f"result = {{'exported_glb': r\"{output_path}\"}}\n"
    )
