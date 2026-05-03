r"""
comfyui_runner.py — Local material and texture generation via ComfyUI API.

ComfyUI runs locally at C:\SHARE\ComfyUI and exposes a REST API on port 8188.
Workflows are submitted as JSON to /prompt endpoint and outputs polled from /history.

Use cases:
    - PBR material generation (from reference image or text prompt)
    - Texture upscaling and enhancement
    - img2img material remixing
    - Seamless texture tiling generation

Usage (via CLI):
    python -m assetboy.cli run-comfyui-batch --use-presets --dry-run
    python -m assetboy.cli run-comfyui-batch --prompt "stone wall roman aged" --type texture
    python -m assetboy.cli run-comfyui-batch --input-image path/to/ref.png --type pbr_material
"""
from __future__ import annotations

import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path

from assetboy.library.paths import generated_output_root, manual_drop_dir

COMFYUI_ROOT = Path(r"C:\SHARE\ComfyUI")
COMFYUI_API = "http://127.0.0.1:8188"
COMFYUI_MODELS_DIR = COMFYUI_ROOT / "models"
COMFYUI_OUTPUT_DIR = COMFYUI_ROOT / "output"

# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

ROMAN_MATERIAL_PRESETS: list[dict] = [
    {"pack_id": "SHARED_MAT_STONE_WALL_01",   "type": "texture", "prompt": "rough ancient roman stone wall, seamless PBR texture, 2k, high detail, neutral lighting, top-down view"},
    {"pack_id": "SHARED_MAT_SANDY_ARENA_01",  "type": "texture", "prompt": "dry sandy arena floor, compacted sand, organic variations, seamless PBR, 2k"},
    {"pack_id": "SHARED_MAT_MARBLE_FLOOR_01", "type": "texture", "prompt": "ancient roman white marble floor tiles, veins, worn edges, seamless PBR, 2k"},
    {"pack_id": "SHARED_MAT_WOOD_GATE_01",    "type": "texture", "prompt": "weathered oak wood gate planks, iron bands, seamless PBR texture, 2k"},
    {"pack_id": "SHARED_MAT_LEATHER_01",      "type": "texture", "prompt": "worn brown leather, stitched, ancient roman gladiator armor style, seamless PBR, 2k"},
    {"pack_id": "SHARED_MAT_BRONZE_01",       "type": "texture", "prompt": "ancient oxidized bronze metal, patina green highlights, seamless PBR, 2k"},
]


@dataclass
class ComfyUIResult:
    pack_id: str
    prompt: str
    asset_type: str
    output_dir: Path
    outputs: list[str] = field(default_factory=list)
    job_spec_path: Path | None = None
    dry_run: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "pack_id": self.pack_id,
            "prompt": self.prompt,
            "asset_type": self.asset_type,
            "output_dir": str(self.output_dir),
            "outputs": self.outputs,
            "job_spec_path": str(self.job_spec_path) if self.job_spec_path else None,
            "dry_run": self.dry_run,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# ComfyUI connectivity check
# ---------------------------------------------------------------------------

def is_comfyui_running() -> bool:
    """Check if ComfyUI API is accessible."""
    try:
        req = urllib.request.urlopen(f"{COMFYUI_API}/system_stats", timeout=3)
        return req.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Workflow builders
# ---------------------------------------------------------------------------

def _build_text_to_texture_workflow(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 7.0,
) -> dict:
    """
    Minimal ComfyUI API workflow for text-to-texture generation.
    Uses the default SDXL or SD1.5 checkpoint found in ComfyUI's models/checkpoints.
    """
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
                "seed": 42,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler_a",
                "scheduler": "karras",
                "denoise": 1.0,
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": "dreamshaper_8.safetensors",
            },
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": prompt + ", seamless, tileable, high quality, 4k, PBR ready",
                "clip": ["4", 1],
            },
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "blurry, seams, ugly, watermark, logo, text, person, face",
                "clip": ["4", 1],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "assetboy_texture"},
        },
    }


def _submit_workflow(workflow: dict) -> str | None:
    """Submit workflow to ComfyUI /prompt and return the prompt_id."""
    payload = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(
        f"{COMFYUI_API}/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            return body.get("prompt_id")
    except Exception as e:
        print(f"  [ERROR] ComfyUI submit failed: {e}")
        return None


def _poll_output(prompt_id: str, timeout: int = 120) -> list[str]:
    """Poll /history until the prompt is complete and return output image paths."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{COMFYUI_API}/history/{prompt_id}", timeout=5) as resp:
                history = json.loads(resp.read())
                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    images = []
                    for node_out in outputs.values():
                        for img in node_out.get("images", []):
                            img_path = COMFYUI_OUTPUT_DIR / img["filename"]
                            images.append(str(img_path))
                    return images
        except Exception:
            pass
        time.sleep(3)
    return []


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_comfyui_batch(
    *,
    prompt: str | None = None,
    pack_id: str | None = None,
    asset_type: str = "texture",
    width: int = 1024,
    height: int = 1024,
    steps: int = 25,
    cfg: float = 7.0,
    input_image: str | Path | None = None,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
    use_presets: bool = False,
) -> list[ComfyUIResult]:
    """
    Generate materials/textures locally using ComfyUI.

    Requires ComfyUI running at http://127.0.0.1:8188 with appropriate models.
    Start ComfyUI first: run_comfyui.bat in C:\\SHARE\\ComfyUI

    dry_run=True shows the workflow spec without submitting.
    """
    if use_presets:
        jobs = ROMAN_MATERIAL_PRESETS
    else:
        pid = pack_id or "SHARED_MAT_CUSTOM_01"
        p = prompt or "stone wall seamless PBR"
        jobs = [{"pack_id": pid, "type": asset_type, "prompt": p}]

    # Check connectivity first (unless dry-run)
    if not dry_run:
        if not is_comfyui_running():
            print("[ERROR] ComfyUI is not running at http://127.0.0.1:8188")
            print("[ERROR] Start it via: Run C:\\SHARE\\ComfyUI\\run_nvidia_gpu.bat")
            print("[ERROR] Then retry this command.")
            return []

    results = []
    for job in jobs:
        pid = job["pack_id"]
        p = job["prompt"]
        jtype = job.get("type", asset_type)
        out_dir = Path(output_dir) if output_dir else generated_output_root() / "comfyui" / pid
        out_dir.mkdir(parents=True, exist_ok=True)

        workflow = _build_text_to_texture_workflow(p, width, height, steps, cfg)

        spec = {
            "source": "comfyui_local",
            "pack_id": pid,
            "prompt": p,
            "type": jtype,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg": cfg,
            "output_dir": str(out_dir),
            "api": COMFYUI_API,
        }
        spec_path = out_dir / "comfyui_job.json"
        spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")

        result = ComfyUIResult(
            pack_id=pid, prompt=p, asset_type=jtype,
            output_dir=out_dir, job_spec_path=spec_path, dry_run=dry_run,
        )

        mode = "DRY RUN" if dry_run else "GENERATING"
        print(f"\n[{mode}] ComfyUI {jtype}: {pid}")
        print(f"Prompt: {p[:70]}...")
        print(f"Size: {width}x{height} | Steps: {steps} | CFG: {cfg}")
        print(f"Output: {out_dir}")

        if dry_run:
            print(f"  >> Would submit workflow to {COMFYUI_API}/prompt")
            print(f"  >> Workflow nodes: {len(workflow)}")
        else:
            prompt_id = _submit_workflow(workflow)
            if prompt_id:
                print(f"  Submitted. Prompt ID: {prompt_id}")
                print(f"  Polling for output (up to 120s)...")
                output_files = _poll_output(prompt_id)
                if output_files:
                    for f in output_files:
                        import shutil
                        dest = out_dir / Path(f).name
                        shutil.copy2(f, dest)
                        result.outputs.append(str(dest))
                        print(f"  >> Saved: {dest}")
                else:
                    result.error = "Timeout or no output from ComfyUI"
                    print(f"  [WARN] No output received. Check ComfyUI logs.")
            else:
                result.error = "Failed to submit workflow"

        results.append(result)

    print(f"\nTotal ComfyUI jobs: {len(results)}")
    return results
