"""
mixamo_glb_runner.py — AssetBoy runner for the Mixamo-to-Flax GLB merger.

Drives scripts/mixamo_merge.py via Blender headless (blender.exe --background --python).

Usage (via CLI):
    python -m assetboy.cli run-mixamo-glb-merge \\
        --pack-id RA_PACK_CHR_PLAYER_SLICE_01 \\
        --char-fbx "C:\\...\\character.fbx" \\
        --anim-fbx "C:\\...\\idle.fbx" "C:\\...\\slash.fbx" \\
        --dry-run

Adapted from: https://github.com/m-danya/godot-mixamo-glb-generator
Flax difference: outputs char.glb (SkinnedModel) + per-clip FBX (Animation).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from assetboy.library.paths import generated_output_root


# Default Blender executable locations (Windows)
_BLENDER_CANDIDATES: list[str] = [
    "blender",                         # if blender.exe is on PATH
    r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
    r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
]

# Location of the bpy merge script relative to AssetBoy root
_MERGE_SCRIPT_REL = Path("scripts") / "mixamo_merge.py"


@dataclass
class MixamoMergeResult:
    pack_id: str
    char_fbx: Path
    anim_fbxs: list[Path]
    output_dir: Path
    char_glb: Path
    anims_dir: Path
    merge_plan_path: Path
    provenance_path: Path
    blender_cmd: list[str]
    dry_run: bool

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "char_fbx": str(self.char_fbx),
            "anim_fbxs": [str(p) for p in self.anim_fbxs],
            "output_dir": str(self.output_dir),
            "char_glb": str(self.char_glb),
            "anims_dir": str(self.anims_dir),
            "merge_plan_path": str(self.merge_plan_path),
            "provenance_path": str(self.provenance_path),
            "blender_cmd": self.blender_cmd,
            "dry_run": self.dry_run,
        }


def run_mixamo_glb_merge(
    *,
    pack_id: str,
    char_fbx: str | Path,
    anim_fbxs: list[str | Path],
    output_dir: str | Path | None = None,
    game_scope: str = "roman_arena",
    blender_exe: str | None = None,
    dry_run: bool = False,
) -> MixamoMergeResult:
    """
    Merge a Mixamo character FBX + animation FBXs into Flax-ready output.

    Parameters
    ----------
    pack_id      : AssetBoy pack ID
    char_fbx     : Path to character.fbx (downloaded with skin, T-pose)
    anim_fbxs    : List of animation FBX paths (without skin)
    output_dir   : Where to write output. Defaults to state/generated/mixamo_glb/<pack_id>/
    game_scope   : Used in provenance.json
    blender_exe  : Path to blender.exe. Auto-detected if None.
    dry_run      : Print everything, skip actual Blender invocation.
    """
    char_fbx = Path(char_fbx)
    anim_list = [Path(p) for p in anim_fbxs]

    out_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "mixamo_glb" / pack_id
    )
    anims_dir = out_dir / "anims"

    # Locate the bpy merge script
    script_path = _find_merge_script()

    # Build the Blender headless command
    blender = blender_exe or _find_blender(allow_placeholder=dry_run)
    cmd = [
        blender,
        "--background",
        "--python", str(script_path),
        "--",
        "--char", str(char_fbx),
        "--output-dir", str(out_dir),
        "--pack-id", pack_id,
    ]
    if anim_list:
        cmd += ["--anims"] + [str(p) for p in anim_list]

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"\n[MixamoGLB | {mode}] Pack: {pack_id}")
    print(f"  Char FBX : {char_fbx}")
    print(f"  Anims    : {[str(p) for p in anim_list]}")
    print(f"  Output   : {out_dir}")
    print(f"  Expected outputs:")
    print(f"    {out_dir / (pack_id + '.glb')}  -> Flax SkinnedModel")
    for anim_fbx in anim_list:
        print(f"    {anims_dir / (anim_fbx.stem + '.fbx')}  -> Flax Animation")
    print(f"\n  Blender cmd: {' '.join(cmd)}")

    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
        print("\n  Running Blender...")
        proc = subprocess.run(cmd, check=True)
        print(f"\n  Blender exited: {proc.returncode}")

    # Write merge plan JSON
    plan = {
        "schema_version": "assetboy.mixamo_merge_plan.v1",
        "pack_id": pack_id,
        "game_scope": game_scope,
        "char_fbx": str(char_fbx),
        "anim_fbxs": [str(p) for p in anim_list],
        "output_dir": str(out_dir),
        "char_glb": str(out_dir / f"{pack_id}.glb"),
        "anims_dir": str(anims_dir),
        "blender_cmd": cmd,
        "expected_clips": [p.stem for p in anim_list],
        "dry_run": dry_run,
    }
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    plan_path = out_dir / "merge_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"  Merge plan: {plan_path}")

    # Write provenance template
    provenance_path = _write_provenance(
        out_dir,
        pack_id=pack_id,
        game_scope=game_scope,
        char_fbx=char_fbx,
        anim_fbxs=anim_list,
    )

    return MixamoMergeResult(
        pack_id=pack_id,
        char_fbx=char_fbx,
        anim_fbxs=anim_list,
        output_dir=out_dir,
        char_glb=out_dir / f"{pack_id}.glb",
        anims_dir=anims_dir,
        merge_plan_path=plan_path,
        provenance_path=provenance_path,
        blender_cmd=cmd,
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_blender(*, allow_placeholder: bool = False) -> str:
    for candidate in _iter_blender_candidates():
        found = shutil.which(candidate)
        if found:
            return found
        if Path(candidate).exists():
            return candidate
    if allow_placeholder:
        # Dry-run mode still needs a stable command preview even without a local install.
        return _BLENDER_CANDIDATES[0]
    raise FileNotFoundError(
        "Blender not found. Install Blender and ensure blender.exe is on PATH,\n"
        "or pass --blender-exe to the CLI command."
    )


def _iter_blender_candidates() -> list[str]:
    candidates = list(_BLENDER_CANDIDATES)
    blender_root = Path(r"C:\Program Files\Blender Foundation")
    if blender_root.exists():
        discovered = sorted(
            blender_root.glob(r"Blender *\blender.exe"),
            key=lambda path: path.name,
            reverse=True,
        )
        for candidate in discovered:
            candidate_str = str(candidate)
            if candidate_str not in candidates:
                candidates.append(candidate_str)
    return candidates


def _find_merge_script() -> Path:
    """Locate scripts/mixamo_merge.py relative to AssetBoy workspace root."""
    # Walk up from this file to find the AssetBoy root (contains scripts/)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / _MERGE_SCRIPT_REL
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Cannot find '{_MERGE_SCRIPT_REL}' relative to {here}.\n"
        "Make sure scripts/mixamo_merge.py exists in the AssetBoy root."
    )


def _write_provenance(
    out_dir: Path,
    *,
    pack_id: str,
    game_scope: str,
    char_fbx: Path,
    anim_fbxs: list[Path],
) -> Path:
    provenance = {
        "schema_version": "assetboy.provenance.v1",
        "pack_id": pack_id,
        "game_scope": game_scope,
        "source_url": "https://www.mixamo.com/",
        "license": "Mixamo ToS",
        "license_notes": (
            "Mixamo content is free for personal and commercial use under Adobe/Mixamo ToS. "
            "No redistribution of raw FBX files. Use in a compiled game product is OK. "
            "Attribution: 'Character animation by Adobe Mixamo' as good practice."
        ),
        "author": "Adobe Mixamo",
        "download_date": date.today().isoformat(),
        "source_adapter": "mixamo_manual_browser",
        "lane": "manual_browser",
        "merge_tool": "AssetBoy mixamo_merge.py (godot-mixamo-glb-generator port)",
        "char_fbx": str(char_fbx),
        "anim_fbxs": [str(p) for p in anim_fbxs],
        "output_format": "GLB (SkinnedModel) + per-clip FBX (Animation)",
        "notes": [
            "character.glb -> import as Flax SkinnedModel",
            "anims/*.fbx -> import each as Flax Animation asset",
            "All clips are retargetable to any Mixamo-rig humanoid skeleton",
        ],
    }
    path = out_dir / "provenance.json"
    path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"  Provenance: {path}")
    return path
