"""AI generation sub-app for assetboy CLI.

Wraps ``execution/comfyui_runner.py`` + ``execution/local_image_runner.py``.

Commands:
    gen comfyui status   -- check local ComfyUI is running on :8188
    gen comfyui run      -- submit a workflow JSON to ComfyUI
    gen sd run           -- run local stable-diffusion.cpp (sd.exe) on a prompt
    gen list-presets     -- show available ComfyUI + UI prompt presets
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="gen",
    help="AI generation via local ComfyUI or stable-diffusion.cpp.",
    add_completion=False,
    no_args_is_help=True,
)

comfy_app = typer.Typer(
    name="comfyui",
    help="ComfyUI (local :8188) workflow submission.",
    add_completion=False,
    no_args_is_help=True,
)
sd_app = typer.Typer(
    name="sd",
    help="stable-diffusion.cpp CUDA wrapper (RTX 3050 6GB target).",
    add_completion=False,
    no_args_is_help=True,
)

app.add_typer(comfy_app, name="comfyui")
app.add_typer(sd_app, name="sd")


# --------------------------------------------------------------------------- #
# gen comfyui status
# --------------------------------------------------------------------------- #

@comfy_app.command("status")
def comfy_status_cmd(
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Check ComfyUI is running on :8188; report GPU + free VRAM."""
    from assetboy.execution.comfyui_runner import COMFYUI_API, is_comfyui_running

    if not is_comfyui_running():
        msg = "connection_refused (is ComfyUI running on :8188?)"
        if json_out:
            json.dump({"running": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_comfyui_running=false")
            print(f"gen_comfyui_error={msg}")
        raise typer.Exit(code=1)

    try:
        with urllib.request.urlopen(
            f"{COMFYUI_API}/system_stats", timeout=5
        ) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        # Server is up but stats endpoint flaky -- still green
        payload = {"running": True, "stats_error": str(exc)}
        if json_out:
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_comfyui_running=true")
            print(f"gen_comfyui_stats_error={exc}")
        return

    gpu = (data.get("devices") or [{}])[0]
    payload = {
        "running": True,
        "api": COMFYUI_API,
        "gpu_name": gpu.get("name", "?"),
        "vram_free_gb": (gpu.get("vram_free", 0) // (1024 ** 3))
        if isinstance(gpu.get("vram_free"), int)
        else 0,
        "vram_total_gb": (gpu.get("vram_total", 0) // (1024 ** 3))
        if isinstance(gpu.get("vram_total"), int)
        else 0,
    }
    if json_out:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        for k, v in payload.items():
            if isinstance(v, bool):
                v = "true" if v else "false"
            print(f"gen_comfyui_{k}={v}")


# --------------------------------------------------------------------------- #
# gen comfyui run
# --------------------------------------------------------------------------- #

@comfy_app.command("run")
def comfy_run_cmd(
    workflow: Annotated[
        Path,
        typer.Argument(
            help="Path to a ComfyUI workflow JSON file (the /prompt-format payload).",
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Print the workflow that would be submitted; do not POST.",
        ),
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Submission timeout."),
    ] = 600.0,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Submit a ComfyUI workflow JSON; wait for completion via /history."""
    if not workflow.exists():
        if json_out:
            json.dump({"error": f"workflow_not_found: {workflow}"}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_comfyui_run_error=workflow_not_found: {workflow}")
        raise typer.Exit(code=1)

    from assetboy.execution.comfyui_runner import run_comfyui_batch

    try:
        result = run_comfyui_batch(
            workflow_path=workflow,
            dry_run=dry_run,
            timeout_seconds=timeout,
        )
    except Exception as exc:
        if json_out:
            json.dump({"error": str(exc)}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_comfyui_run_error={exc}")
        raise typer.Exit(code=1)

    if json_out:
        if hasattr(result, "__dict__"):
            json.dump(result.__dict__, sys.stdout, indent=2, default=str)
        else:
            json.dump(result, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        if hasattr(result, "__dict__"):
            for k, v in result.__dict__.items():
                print(f"gen_comfyui_run_{k}={v}")
        else:
            print(f"gen_comfyui_run_result={result}")


# --------------------------------------------------------------------------- #
# gen sd run
# --------------------------------------------------------------------------- #

@sd_app.command("run")
def sd_run_cmd(
    prompt: Annotated[
        str, typer.Argument(help="Text prompt for image generation."),
    ],
    out: Annotated[
        Path, typer.Option("--out", help="Output PNG path."),
    ] = Path("./out.png"),
    steps: Annotated[
        int, typer.Option("--steps", help="Diffusion steps (lower = faster)."),
    ] = 20,
    width: Annotated[
        int, typer.Option("--width", help="Image width."),
    ] = 512,
    height: Annotated[
        int, typer.Option("--height", help="Image height."),
    ] = 512,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the command; do not run."),
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Run stable-diffusion.cpp on a single prompt. 6GB-VRAM-friendly (SD 1.5)."""
    from assetboy.execution.local_image_runner import run_local_image_batch

    try:
        result = run_local_image_batch(
            prompts=[prompt],
            out_dir=out.parent if out.suffix else out,
            steps=steps,
            width=width,
            height=height,
            dry_run=dry_run,
        )
    except Exception as exc:
        if json_out:
            json.dump({"error": str(exc)}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_sd_run_error={exc}")
        raise typer.Exit(code=1)

    if json_out:
        if hasattr(result, "__dict__"):
            json.dump(result.__dict__, sys.stdout, indent=2, default=str)
        else:
            json.dump(result, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        if hasattr(result, "__dict__"):
            for k, v in result.__dict__.items():
                print(f"gen_sd_run_{k}={v}")
        else:
            print(f"gen_sd_run_result={result}")


# --------------------------------------------------------------------------- #
# gen list-presets
# --------------------------------------------------------------------------- #

@app.command("list-presets")
def list_presets_cmd(
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            "-p",
            help=(
                "Filter to one provider: comfyui | local_image | stable_audio. "
                "Default: list all 3."
            ),
        ),
    ] = "",
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """List preset prompts available per generator provider.

    Pulls from the 3 KEEP runner modules:
      - comfyui_runner.ROMAN_MATERIAL_PRESETS  (dict per preset: pack_id/type/prompt)
      - local_image_runner.UI_PROMPT_TEMPLATES (dict per preset)
      - stable_audio_runner.STABLE_AUDIO_PRESETS (tuple: id/text/duration_s)

    The --provider filter restricts the listing to one source.
    """
    from assetboy.execution.comfyui_runner import ROMAN_MATERIAL_PRESETS
    from assetboy.execution.local_image_runner import UI_PROMPT_TEMPLATES
    from assetboy.execution.stable_audio_runner import STABLE_AUDIO_PRESETS

    provider = (provider or "").strip().lower()

    def _normalize_dict_preset(p, fallback_idx):
        if isinstance(p, dict):
            return {
                "id": p.get("id") or p.get("pack_id") or p.get("name") or f"preset_{fallback_idx}",
                "type": p.get("type") or p.get("asset_type", ""),
                "prompt": p.get("prompt") or p.get("text", ""),
            }
        if hasattr(p, "__dict__"):
            return p.__dict__
        return {"raw": str(p)}

    comfyui_presets = (
        [
            _normalize_dict_preset(p, i)
            for i, p in enumerate(ROMAN_MATERIAL_PRESETS or [])
        ]
        if not provider or provider == "comfyui"
        else []
    )
    # UI_PROMPT_TEMPLATES is a dict[str, dict]: {preset_id: {prompt, width, ...}}
    if not provider or provider in ("local_image", "sd.cpp", "sd"):
        local_image_presets = []
        for preset_id, preset_data in (UI_PROMPT_TEMPLATES or {}).items():
            if isinstance(preset_data, dict):
                local_image_presets.append({
                    "id": str(preset_id),
                    "prompt": preset_data.get("prompt", ""),
                    "width": preset_data.get("width"),
                    "height": preset_data.get("height"),
                })
            else:
                local_image_presets.append({"id": str(preset_id), "prompt": str(preset_data)})
    else:
        local_image_presets = []
    stable_audio_presets = (
        [
            {"id": entry[0], "text": entry[1], "duration_s": entry[2]}
            for entry in (STABLE_AUDIO_PRESETS or [])
        ]
        if not provider or provider in ("stable_audio", "stable_audio_open_small")
        else []
    )

    payload = {
        "comfyui_material_presets": comfyui_presets,
        "local_image_ui_prompts": local_image_presets,
        "stable_audio_presets": stable_audio_presets,
    }

    if json_out:
        json.dump(payload, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
        return

    # Human-readable output
    if comfyui_presets:
        print(f"gen_comfyui_preset_count={len(comfyui_presets)}")
        for idx, preset in enumerate(comfyui_presets, start=1):
            print(
                f"gen_comfyui_preset={idx}  "
                f"id={preset.get('id', '?')}  "
                f"type={preset.get('type', '')}"
            )
    if local_image_presets:
        print(f"gen_local_image_preset_count={len(local_image_presets)}")
        for idx, preset in enumerate(local_image_presets, start=1):
            print(
                f"gen_local_image_preset={idx}  "
                f"id={preset.get('id', '?')}"
            )
    if stable_audio_presets:
        print(f"gen_stable_audio_preset_count={len(stable_audio_presets)}")
        for idx, preset in enumerate(stable_audio_presets, start=1):
            print(
                f"gen_stable_audio_preset={idx}  "
                f"id={preset.get('id', '?')}  "
                f"duration_s={preset.get('duration_s', 0)}"
            )


if __name__ == "__main__":
    app()
