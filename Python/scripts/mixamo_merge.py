"""
mixamo_merge.py — Blender headless script for Mixamo FBX → Flax-ready output.

Run via:
    blender.exe --background --python mixamo_merge.py -- \\
        --char C:\\path\\to\\character.fbx \\
        --anims C:\\path\\to\\idle.fbx C:\\path\\to\\slash.fbx \\
        --output-dir C:\\path\\to\\output \\
        --pack-id RA_PACK_CHR_PLAYER_SLICE_01

What this produces (Flax-native layout):
    output/
        <pack_id>.glb          ← SkinnedModel: mesh + skeleton only
        anims/
            idle.fbx           ← Animation clip (retargetable)
            slash.fbx
            ...
        merge_log.json         ← Clip names + frame ranges baked

Ported/adapted from: https://github.com/m-danya/godot-mixamo-glb-generator
Flax differences:
  - Godot uses a single merged GLB (all clips embedded).
  - Flax imports clips as separate Animation assets → we export per-clip FBX.
  - The character GLB carries mesh + T-pose skeleton only.
"""

import sys
import argparse
import json
from pathlib import Path

import bpy


# ---------------------------------------------------------------------------
# Argument parsing  (everything after "--" is ours)
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []

    parser = argparse.ArgumentParser(
        description="Merge Mixamo FBX char + anim clips into Flax-ready output."
    )
    parser.add_argument("--char", required=True, help="Character FBX (with skin)")
    parser.add_argument("--anims", nargs="+", default=[], help="Animation FBX files (without skin)")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--pack-id", default="mixamo_pack", help="Pack ID for naming")
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Blender helpers
# ---------------------------------------------------------------------------

def _clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in list(bpy.data.meshes):
        bpy.data.meshes.remove(block)
    for block in list(bpy.data.armatures):
        bpy.data.armatures.remove(block)


def _import_fbx(path: str) -> list:
    before = set(bpy.data.objects.keys())
    bpy.ops.import_scene.fbx(
        filepath=path,
        use_manual_orientation=False,
        use_anim=True,
        automatic_bone_orientation=True,
    )
    after = set(bpy.data.objects.keys())
    return [bpy.data.objects[k] for k in (after - before)]


def _find_armature(objects: list):
    for obj in objects:
        if obj.type == "ARMATURE":
            return obj
    return None


def _apply_mixamo_scale(armature) -> None:
    """Mixamo exports at 1 unit = 1 cm. Rescale to 1 unit = 1 m for Flax."""
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    # Apply 1/100 scale: Mixamo FBX is in centimetres
    armature.scale = (0.01, 0.01, 0.01)
    bpy.ops.object.transform_apply(scale=True)


def _transfer_action_to_armature(action, target_armature) -> None:
    """Push an action onto target armature NLA (won't be in the final GLB, but useful for review)."""
    if target_armature.animation_data is None:
        target_armature.animation_data_create()
    track = target_armature.animation_data.nla_tracks.new()
    track.name = action.name
    strip = track.strips.new(action.name, start=int(action.frame_range[0]), action=action)
    strip.name = action.name


def _export_glb(armature, mesh_objects: list, output_path: str) -> None:
    """Export character mesh + skeleton as GLB (no animations — Flax imports separately)."""
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for obj in mesh_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.gltf(
        filepath=output_path,
        export_format="GLB",
        use_selection=True,
        export_animations=False,   # No anims in the SkinnedModel GLB
        export_skins=True,
        export_apply=True,
    )


def _export_anim_fbx(action, armature, output_path: str) -> None:
    """Export a single animation action as a retargetable FBX clip."""
    # Set the active action on the armature for the export
    if armature.animation_data is None:
        armature.animation_data_create()
    armature.animation_data.action = action

    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature

    bpy.ops.export_scene.fbx(
        filepath=output_path,
        use_selection=True,
        object_types={"ARMATURE"},
        bake_anim=True,
        bake_anim_use_all_actions=False,
        bake_anim_use_nla_strips=False,
        bake_anim_force_startend_keying=True,
        add_leaf_bones=False,
        apply_unit_scale=True,
        global_scale=1.0,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()

    output_dir = Path(args.output_dir)
    anims_dir = output_dir / "anims"
    output_dir.mkdir(parents=True, exist_ok=True)
    anims_dir.mkdir(parents=True, exist_ok=True)

    print(f"[mixamo_merge] Pack: {args.pack_id}")
    print(f"[mixamo_merge] Char: {args.char}")
    print(f"[mixamo_merge] Anims: {args.anims}")
    print(f"[mixamo_merge] Output: {output_dir}")

    _clear_scene()

    # 1. Import character FBX (mesh + skeleton)
    print("\n[mixamo_merge] Importing character FBX...")
    char_objects = _import_fbx(args.char)
    char_armature = _find_armature(char_objects)
    if char_armature is None:
        raise RuntimeError(f"No armature found in character FBX: {args.char}")
    char_meshes = [obj for obj in char_objects if obj.type == "MESH"]
    print(f"  Armature: {char_armature.name}  |  Meshes: {[m.name for m in char_meshes]}")

    # Apply Mixamo scale (cm → m)
    _apply_mixamo_scale(char_armature)

    # 2. Import each animation FBX and extract its actions
    clip_log: list[dict] = []
    for anim_fbx in args.anims:
        clip_name = Path(anim_fbx).stem
        print(f"\n[mixamo_merge] Importing anim: {clip_name}")

        before_actions = set(bpy.data.actions.keys())
        anim_objects = _import_fbx(anim_fbx)
        after_actions = set(bpy.data.actions.keys())
        new_action_names = after_actions - before_actions

        anim_armature = _find_armature(anim_objects)

        # Rename new actions to match the clip filename for clarity
        for a_name in new_action_names:
            action = bpy.data.actions[a_name]
            action.name = clip_name
            start, end = int(action.frame_range[0]), int(action.frame_range[1])
            print(f"  Action '{clip_name}': frames {start}→{end}")

            # Export this clip as a per-clip FBX
            clip_out = str(anims_dir / f"{clip_name}.fbx")
            _export_anim_fbx(action, char_armature, clip_out)
            print(f"  Exported: {clip_out}")

            clip_log.append({
                "clip_name": clip_name,
                "source_fbx": anim_fbx,
                "output_fbx": clip_out,
                "frame_start": start,
                "frame_end": end,
            })

        # Remove the imported anim armature+objects (not needed in scene)
        if anim_armature:
            for obj in anim_objects:
                bpy.data.objects.remove(obj, do_unlink=True)

    # 3. Export character GLB (mesh + skeleton, no anims)
    glb_out = str(output_dir / f"{args.pack_id}.glb")
    print(f"\n[mixamo_merge] Exporting character GLB: {glb_out}")
    _export_glb(char_armature, char_meshes, glb_out)

    # 4. Write merge log
    log = {
        "schema_version": "assetboy.mixamo_merge.v1",
        "pack_id": args.pack_id,
        "char_fbx": args.char,
        "char_glb_output": glb_out,
        "anim_count": len(clip_log),
        "clips": clip_log,
    }
    log_path = output_dir / "merge_log.json"
    log_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"[mixamo_merge] Done. Merge log: {log_path}")


if __name__ == "__main__":
    main()
