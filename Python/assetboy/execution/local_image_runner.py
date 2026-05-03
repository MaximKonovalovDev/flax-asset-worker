"""
local_image_runner.py — Local Stable Diffusion image gen via stable-diffusion.cpp.

Uses sdcpp-cli-python wrapper around the sd.cpp C++ binary.
Designed for RTX 3050 6GB (and similar low-VRAM cards).
Handles batches of UI/icon/HUD prompts from AssetBoy job specs.

Setup (one-time):
    1. Download sd.cpp CUDA binary for Windows:
       https://github.com/leejet/stable-diffusion.cpp/releases
       → Extract sd.exe to C:\\SHARE\\AssetBoy\\tools\\sdcpp\\sd.exe
    2. pip install "git+https://github.com/g0g5/sdcpp-cli-python.git"
    3. Download a model (see MODEL RECOMMENDATIONS below)
       → Place in C:\\SHARE\\AssetBoy\\tools\\sdcpp\\models\\

MODEL RECOMMENDATIONS for 6GB VRAM:
    - dreamshaper_8.safetensors (1.5-based, ~2GB, great for icons)
      https://civitai.com/models/4384/dreamshaper
    - juggernautXL_v8Rundiffusion.safetensors (SDXL, ~6.5GB, use q4 GGUF)
      → Use SDXL only in GGUF format for 6GB!
    - SD 1.5 any fine-tune: always safe at 6GB

Usage (via CLI):
    python -m assetboy.cli run-local-image-batch --pack-id RA_PACK_UI_COMBAT_SLICE_01
    python -m assetboy.cli run-local-image-batch --prompt "roman arena HUD icon" --count 6
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from assetboy.library.paths import assetboy_root, generated_output_root

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _sdcpp_root() -> Path:
    return assetboy_root() / "tools" / "sdcpp"

def _sd_binary() -> Path:
    root = _sdcpp_root()
    for name in ("sd.exe", "sd-cli.exe"):
        candidate = root / name
        if candidate.exists():
            return candidate
    return root / "sd.exe"

def _models_dir() -> Path:
    return _sdcpp_root() / "models"

def _default_model() -> Path | None:
    """Return the first .safetensors or .gguf found in models/."""
    d = _models_dir()
    if not d.exists():
        return None
    for ext in ("*.safetensors", "*.gguf", "*.bin"):
        found = sorted(d.glob(ext))
        if found:
            return found[0]
    return None


# ---------------------------------------------------------------------------
# UI / Icon prompt templates
# ---------------------------------------------------------------------------

UI_PROMPT_TEMPLATES: dict[str, dict] = {
    "icon_weapon": {
        "prompt": "game inventory icon, roman gladius sword, isolated on dark background, detailed, stylized, 2D game art, no text",
        "negative": "blurry, 3d render, photorealistic, text, border, frame",
        "width": 512,
        "height": 512,
        "steps": 20,
        "cfg": 7.0,
    },
    "icon_shield": {
        "prompt": "game inventory icon, roman legionary shield scutum, isolated on dark background, detailed, stylized 2D game art, gold trim, no text",
        "negative": "blurry, 3d render, photorealistic, text, border",
        "width": 512,
        "height": 512,
        "steps": 20,
        "cfg": 7.0,
    },
    "hud_health_bar": {
        "prompt": "horizontal game HUD health bar, roman style, stone texture background, red fill, clean UI element, no text",
        "negative": "blurry, busy, cluttered, text",
        "width": 1024,
        "height": 128,
        "steps": 25,
        "cfg": 7.5,
    },
    "hud_stamina_bar": {
        "prompt": "horizontal game HUD stamina bar, roman style, bronze texture, yellow-gold fill, clean UI element, no text",
        "negative": "blurry, busy, cluttered, text",
        "width": 1024,
        "height": 128,
        "steps": 25,
        "cfg": 7.5,
    },
    "hud_minimap_border": {
        "prompt": "circular game minimap frame border, roman mosaic pattern, gold and stone, clean UI element, transparent center, no text",
        "negative": "blurry, busy, text, icons inside",
        "width": 512,
        "height": 512,
        "steps": 25,
        "cfg": 7.5,
    },
    "menu_background": {
        "prompt": "game main menu background, roman colosseum at sunset, dramatic, cinematic, epic composition, no text, no UI",
        "negative": "text, HUD, blurry, low quality",
        "width": 1920,
        "height": 1080,
        "steps": 30,
        "cfg": 8.0,
        "seed": 5901,
    },
}


# ---------------------------------------------------------------------------
# Seed sidecar helper  (local-genai-forge pattern)
# ---------------------------------------------------------------------------

def _write_gen_meta(
    image_path: Path,
    *,
    prompt: str,
    negative: str = "",
    seed: int | None = None,
    width: int = 512,
    height: int = 512,
    steps: int = 20,
    cfg: float = 7.0,
    model: str = "",
) -> Path:
    """Write a .gen_meta.json sidecar next to image_path for provenance."""
    meta_path = image_path.with_suffix(".gen_meta.json")
    meta = {
        "schema_version": "assetboy.gen_meta.v1",
        "image": image_path.name,
        "prompt": prompt,
        "negative_prompt": negative,
        "seed": seed,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": cfg,
        "model": model,
        "generator": "stable-diffusion.cpp",
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta_path


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class LocalImageBatchResult:
    pack_id: str
    output_dir: Path
    generated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    model_used: str = ""
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "output_dir": str(self.output_dir),
            "generated": self.generated,
            "skipped": self.skipped,
            "model_used": self.model_used,
            "dry_run": self.dry_run,
        }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_local_image_batch(
    *,
    pack_id: str = "RA_PACK_UI_COMBAT_SLICE_01",
    game_scope: str = "roman_arena",
    prompt: str | None = None,
    count: int = 6,
    width: int = 512,
    height: int = 512,
    steps: int = 20,
    cfg: float = 7.0,
    model_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
) -> LocalImageBatchResult:
    """
    Run a batch of UI/icon image generations using local sd.cpp.

    When dry_run=True, prints what would be generated without calling sd.exe.
    """
    # Resolve binary
    sd_bin = _sd_binary()
    model = Path(model_path) if model_path else _default_model()

    out_dir = (
        Path(output_dir) if output_dir is not None
        else generated_output_root() / "local_image" / pack_id
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    result = LocalImageBatchResult(
        pack_id=pack_id,
        output_dir=out_dir,
        model_used=str(model) if model else "<none>",
        dry_run=dry_run,
    )

    # Check binary / model availability
    if not dry_run:
        if not sd_bin.exists():
            print(f"[ERROR] stable-diffusion.cpp CLI binary not found at {sd_bin}")
            print(f"[ERROR] Download sd.cpp CUDA binary from:")
            print(f"        https://github.com/leejet/stable-diffusion.cpp/releases")
            print(f"        Extract sd.exe or sd-cli.exe to: {_sdcpp_root()}")
            return result
        if not model:
            print(f"[ERROR] No model found in {_models_dir()}")
            print(f"[ERROR] Download a model and place in: {_models_dir()}")
            print(f"        Recommended: dreamshaper_8.safetensors (~2GB, works great on 6GB VRAM)")
            print(f"        https://civitai.com/models/4384/dreamshaper")
            return result

    # Determine jobs
    if prompt:
        jobs = [
            {
                "name": f"custom_{i:02d}",
                "prompt": prompt,
                "negative": "blurry, low quality, text",
                "width": width,
                "height": height,
                "steps": steps,
                "cfg": cfg,
            }
            for i in range(count)
        ]
    else:
        all_templates = list(UI_PROMPT_TEMPLATES.items())
        jobs = [{"name": k, **v} for k, v in all_templates[:count]]

    print(f"[{'DRY RUN' if dry_run else 'RUN'}] Local SD image batch: {pack_id}")
    print(f"Model: {model or '<not set>'}")
    print(f"Binary: {sd_bin}")
    print(f"Output: {out_dir}")
    print(f"Jobs: {len(jobs)}")
    print()

    for job in jobs:
        out_path = out_dir / f"{job['name']}.png"
        print(f"  -> {job['name']}: {job['prompt'][:60]}...")

        if dry_run:
            print(f"     [DRY RUN] Would write: {out_path}")
            result.skipped.append(job["name"])
            continue

        try:
            from sdcli import SdCppCli
            cli = (
                SdCppCli(binary_path=str(sd_bin))
                .set_model(str(model))
                .set_prompt(job["prompt"])
                .set_negative_prompt(job.get("negative", ""))
                .set_width(job.get("width", 512))
                .set_height(job.get("height", 512))
                .set_steps(job.get("steps", 20))
                .set_cfg_scale(job.get("cfg", 7.0))
                .set_sampling_method("euler_a")
                .set_output(str(out_path))
            )
            cli.run()
            print(f"     ✅ {out_path.name}")
            result.generated.append(str(out_path))
            # ── seed sidecar (local-genai-forge pattern) ──────────────────
            _write_gen_meta(
                out_path,
                prompt=job["prompt"],
                negative=job.get("negative", ""),
                seed=job.get("seed"),
                width=job.get("width", 512),
                height=job.get("height", 512),
                steps=job.get("steps", 20),
                cfg=job.get("cfg", 7.0),
                model=str(model),
            )
        except ImportError:
            print("  [ERROR] sdcli not installed. Run: pip install git+https://github.com/g0g5/sdcpp-cli-python.git")
            result.skipped.append(job["name"])
        except Exception as e:
            print(f"  [ERROR] {job['name']}: {e}")
            result.skipped.append(job["name"])

    print()
    print(f"Done. Generated: {len(result.generated)} | Skipped: {len(result.skipped)}")
    return result
