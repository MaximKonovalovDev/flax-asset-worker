"""
animationgpt_runner.py — Colab-based combat animation generation via AnimationGPT.

AnimationGPT generates game combat animations (BVH) from text prompts.
Built on MotionGPT (NeurIPS 2023). Trained on CombatMotion Processed (CMP):
8,700 professional combat animations across swords, axes, spears, magic, unarmed.

Source     : https://github.com/fyyakaxyy/AnimationGPT
License    : MIT (model + code). Generated outputs: no restriction.
Output     : .npy → BVH skeletal animation → Blender retarget → .glb → Flax

VERDICT:
  ✅ Works — produces game-ready BVH combat animations from text prompts
  ✅ 20 preset prompts across sword, axe, spear, shield, magic, dodge, death
  ✅ MIT license — free, open source, commercial use OK
  ⚠️  Colab A100/V100 recommended — T4 may OOM on large batches
  ⚠️  Python 3.9.19 required — 3.10+ breaks BVH conversion scripts
  ⚠️  BVH output needs Mixamo-rig retargeting before Flax import
  ❌  COMBAT ONLY — walk, run, idle: use Mixamo instead
  ❌  Duration not precisely controllable (±20% frame variance)

Output pipeline:
  prompt → AnimationGPT → .npy → tools/npy2bvh → .bvh → Blender → .glb → Flax

Usage (via CLI):
    python -m assetboy.cli run-animationgpt --use-presets --dry-run
    python -m assetboy.cli run-animationgpt --use-presets --tags-filter sword
    python -m assetboy.cli run-animationgpt --list-presets
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from assetboy.library.paths import generated_output_root


# ---------------------------------------------------------------------------
# Combat animation presets — 20 prompts covering all major combat categories
# Format: (prompt_id, prompt_text, weapon_type, motion_type, tags)
# ---------------------------------------------------------------------------
ANIMATION_PRESETS: list[tuple[str, str, str, str, list[str]]] = [
    # ── Sword ────────────────────────────────────────────────────────────────
    ("SK_SWORD_SLASH_HORIZONTAL",
     "A warrior performs a fast horizontal sword slash to the right",
     "sword", "attack", ["sword", "melee", "attack", "roman"]),
    ("SK_SWORD_OVERHEAD_SMASH",
     "A warrior performs a slow heavy overhead sword swing downward",
     "sword", "attack", ["sword", "melee", "attack", "heavy"]),
    ("SK_SWORD_THRUST",
     "A warrior thrusts the sword forward with a quick lunging stab",
     "sword", "attack", ["sword", "melee", "attack", "roman"]),
    ("SK_SWORD_COMBO_THREE",
     "A warrior performs a three-hit sword combo: slash right, slash left, then thrust",
     "sword", "combo", ["sword", "melee", "combo"]),
    ("SK_SWORD_BLOCK",
     "A warrior raises the sword to block an incoming horizontal attack",
     "sword", "defense", ["sword", "melee", "defense", "block"]),
    # ── Axe ──────────────────────────────────────────────────────────────────
    ("SK_AXE_OVERHEAD_SMASH",
     "A warrior swings a heavy axe overhead and slams it down with great force",
     "axe", "attack", ["axe", "melee", "attack", "heavy"]),
    ("SK_AXE_SPINNING_SWEEP",
     "A warrior spins and sweeps the axe in a wide horizontal arc",
     "axe", "attack", ["axe", "melee", "attack", "aoe"]),
    # ── Spear ────────────────────────────────────────────────────────────────
    ("SK_SPEAR_THRUST",
     "A warrior thrusts a spear forward rapidly in a quick jab",
     "spear", "attack", ["spear", "polearm", "attack", "roman"]),
    ("SK_SPEAR_SWEEP",
     "A warrior sweeps the spear in a low horizontal arc to knock enemies off balance",
     "spear", "attack", ["spear", "polearm", "attack", "sweep"]),
    # ── Shield ───────────────────────────────────────────────────────────────
    ("SK_SHIELD_BASH",
     "A warrior charges forward and slams the shield into an enemy",
     "shield", "attack", ["shield", "melee", "attack", "roman"]),
    ("SK_SHIELD_RAISE",
     "A warrior holds up the shield in a defensive pose bracing for impact",
     "shield", "defense", ["shield", "defense", "block"]),
    # ── Unarmed ──────────────────────────────────────────────────────────────
    ("SK_UNARMED_PUNCH_COMBO",
     "A fighter performs a fast left-right punch combination followed by an uppercut",
     "unarmed", "combo", ["unarmed", "melee", "combo", "brawl"]),
    ("SK_UNARMED_KICK",
     "A fighter delivers a powerful roundhouse kick to the right side",
     "unarmed", "attack", ["unarmed", "melee", "attack"]),
    # ── Magic ─────────────────────────────────────────────────────────────────
    ("SK_MAGIC_CAST_FIREBALL",
     "A mage raises both hands forward and releases a powerful fireball spell",
     "magic", "cast", ["magic", "fantasy", "cast", "ranged"]),
    ("SK_MAGIC_AOE_GROUND_SLAM",
     "A mage slams both hands into the ground releasing a shockwave of magical energy",
     "magic", "cast", ["magic", "fantasy", "cast", "aoe"]),
    # ── Hit Reactions / Death ────────────────────────────────────────────────
    ("SK_HIT_STAGGER_BACK",
     "A warrior staggers backward after being hit by a heavy blow",
     "none", "hit_reaction", ["reaction", "hit", "stagger", "all"]),
    ("SK_DEATH_FALL_FORWARD",
     "A warrior stumbles and falls forward to the ground after a fatal blow",
     "none", "death", ["death", "all"]),
    ("SK_DEATH_FALL_BACKWARD",
     "A warrior is struck and falls backward to the ground",
     "none", "death", ["death", "all"]),
    # ── Dodge ────────────────────────────────────────────────────────────────
    ("SK_DODGE_ROLL_LEFT",
     "A warrior dives and rolls to the left to evade an attack",
     "none", "dodge", ["dodge", "mobility", "all"]),
    ("SK_DODGE_BACKSTEP",
     "A warrior quickly steps backward to avoid a forward thrust",
     "none", "dodge", ["dodge", "mobility", "all"]),
]


@dataclass
class AnimationGPTBatchResult:
    pack_id: str
    game_scope: str
    total_jobs: int
    colab_script_path: Path
    manifest_path: Path
    provenance_path: Path
    dry_run: bool

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "game_scope": self.game_scope,
            "total_jobs": self.total_jobs,
            "colab_script_path": str(self.colab_script_path),
            "manifest_path": str(self.manifest_path),
            "provenance_path": str(self.provenance_path),
            "dry_run": self.dry_run,
        }


def list_presets() -> list[tuple[str, str, str]]:
    """Return (prompt_id, motion_type, short summary) for all built-in presets."""
    return [
        (pid, motion, f"{weapon} — {prompt[:60]}...")
        for pid, prompt, weapon, motion, _ in ANIMATION_PRESETS
    ]


def run_animationgpt_presets(
    *,
    game_scope: str = "roman_arena",
    pack_id: str | None = None,
    tags_filter: list[str] | None = None,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
) -> AnimationGPTBatchResult:
    """
    Prepare an AnimationGPT batch from preset prompts.

    Generates:
      1. Colab-ready Python batch script (run on Colab A100/V100)
      2. Job manifest JSON (all prompts + expected BVH output filenames)
      3. Provenance JSON for the batch

    Actual Colab execution: upload the generated script to a Colab notebook
    and run it. Download the resulting .bvh files + batch_results.json.

    Parameters
    ----------
    game_scope   : Game scope tag (e.g. 'roman_arena', 'shared')
    pack_id      : Override pack ID. Defaults to ANIM_COMBAT_<SCOPE>_01
    tags_filter  : Only include prompts matching any of these tags
    output_dir   : Override output directory
    dry_run      : Print plan without writing files.
    """
    pid = pack_id or f"ANIM_COMBAT_{game_scope.upper()}_01"
    out = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / "animationgpt" / game_scope / pid
    )

    # Filter prompts
    selected = [
        (prompt_id, prompt, weapon, motion, tags)
        for prompt_id, prompt, weapon, motion, tags in ANIMATION_PRESETS
        if not tags_filter or any(t in tags for t in tags_filter)
    ]

    mode = "DRY RUN" if dry_run else "LIVE"
    print(f"[AnimationGPT | {mode}] pack={pid}  jobs={len(selected)}")
    for prompt_id, prompt, _, _, _ in selected:
        print(f"  {prompt_id}: {prompt[:70]}...")

    if dry_run:
        print("  [dry-run] Skipping file generation.")
        return AnimationGPTBatchResult(
            pack_id=pid,
            game_scope=game_scope,
            total_jobs=len(selected),
            colab_script_path=out / "animationgpt_batch.py",
            manifest_path=out / "job_manifest.json",
            provenance_path=out / "provenance.json",
            dry_run=True,
        )

    out.mkdir(parents=True, exist_ok=True)

    # Write Colab batch script
    colab_script_path = out / "animationgpt_batch.py"
    colab_script_path.write_text(_build_colab_script(selected), encoding="utf-8")
    print(f"  Colab script: {colab_script_path}")

    # Write job manifest
    manifest = {
        "pack_id": pid,
        "game_scope": game_scope,
        "total_jobs": len(selected),
        "jobs": [
            {
                "prompt_id": prompt_id,
                "prompt_text": prompt,
                "weapon_type": weapon,
                "motion_type": motion,
                "expected_output": f"{prompt_id}.bvh",
            }
            for prompt_id, prompt, weapon, motion, _ in selected
        ],
    }
    manifest_path = out / "job_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  Manifest: {manifest_path}")

    provenance_path = _write_provenance(out, pack_id=pid, game_scope=game_scope,
                                         total_jobs=len(selected))
    return AnimationGPTBatchResult(
        pack_id=pid,
        game_scope=game_scope,
        total_jobs=len(selected),
        colab_script_path=colab_script_path,
        manifest_path=manifest_path,
        provenance_path=provenance_path,
        dry_run=False,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_colab_script(selected: list[tuple[str, str, str, str, list[str]]]) -> str:
    """Build a Colab-executable Python batch script for the given prompts."""
    job_lines = "\n".join(
        f"    ({repr(pid)}, {repr(prompt)}),"
        for pid, prompt, _, _, _ in selected
    )
    return f"""\
# AnimationGPT Batch Script — Auto-generated by AssetBoy
# Run on Colab with GPU (A100 recommended, V100 ok, T4 may OOM)
# Requirements: Python 3.9.19, AnimationGPT repo cloned, pre-trained model downloaded
#
# Setup (run once per session):
#   !git clone https://github.com/fyyakaxyy/AnimationGPT.git
#   %cd AnimationGPT
#   !pip install -r tools/requirements.txt --quiet
#   # Download pre-trained weights from the repo README drive link

import glob, json, os, shutil, subprocess

JOBS = [
{job_lines}
]

results = []
for prompt_id, prompt_text in JOBS:
    print(f"Generating: {{prompt_id}}")
    with open("input.txt", "w") as f:
        f.write(prompt_text)
    ret = subprocess.run(
        ["python", "demo.py", "--cfg", "./config_AGPT.yaml", "--example", "./input.txt"],
        capture_output=True, text=True,
    )
    if ret.returncode != 0:
        print(f"  FAILED: {{ret.stderr[-300:]}}")
        results.append({{"id": prompt_id, "status": "failed"}})
        continue
    subprocess.run(["python", "tools/npy2bvh/joints2bvh.py"], capture_output=True)
    bvh_files = glob.glob("output/**/*.bvh", recursive=True)
    if bvh_files:
        shutil.copy(bvh_files[-1], f"{{prompt_id}}.bvh")
        results.append({{"id": prompt_id, "status": "done", "bvh": f"{{prompt_id}}.bvh"}})
        print(f"  Done: {{prompt_id}}.bvh")
    else:
        results.append({{"id": prompt_id, "status": "no_bvh"}})
        print(f"  WARNING: No BVH output for {{prompt_id}}")

with open("batch_results.json", "w") as f:
    json.dump(results, f, indent=2)
print(f"Batch complete. {{sum(1 for r in results if r['status'] == 'done')}}/{{len(results)}} succeeded.")
print("Download all .bvh files and batch_results.json")
"""


def _write_provenance(
    out_dir: Path,
    *,
    pack_id: str,
    game_scope: str,
    total_jobs: int,
) -> Path:
    provenance = {
        "schema_version": "assetboy.provenance.v1",
        "pack_id": pack_id,
        "game_scope": game_scope,
        "source": "https://github.com/fyyakaxyy/AnimationGPT",
        "model": "AnimationGPT (MotionGPT / T5-770M, trained on CombatMotion Processed dataset)",
        "license": "MIT",
        "license_notes": (
            "AnimationGPT code and model weights: MIT license. "
            "Generated BVH animations: treat as pipeline output, no explicit restriction. "
            "CombatMotion dataset derived from game assets — review at commercial scale."
        ),
        "output_format": "BVH → retarget to Mixamo rig → GLB for Flax",
        "total_jobs": total_jobs,
        "download_date": date.today().isoformat(),
        "source_adapter": "animationgpt_colab",
        "lane": "generator_colab",
        "notes": [
            "Colab A100/V100 recommended. T4 may OOM on large batches.",
            "BVH output needs retargeting to Mixamo rig before Flax/Unreal import.",
            "Combat animations only. Use Mixamo for walk, run, idle, social.",
            "Duration is approximate — expect ±20% frame count variance.",
            "Python 3.9.19 required on Colab. 3.10+ breaks npy2bvh scripts.",
        ],
    }
    path = out_dir / "provenance.json"
    path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"  Provenance written: {path}")
    return path
