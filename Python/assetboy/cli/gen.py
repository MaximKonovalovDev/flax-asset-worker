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
# gen status-all (v1.8.s18)
# --------------------------------------------------------------------------- #

@app.command("status-all")
def status_all_cmd(
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Probe all 3 generator providers in one shot (Path B v1.8.s18).

    Returns a status table: comfyui (server-running check), local_image
    (sd.cpp binary check via is_*_available), stable_audio (env vars
    + binary check).

    Exit code:
      0 if at least one generator is available
      1 if NONE are available

    JSON shape:
      { generators: [{provider, available, notes}, ...], any_available: bool }
    """
    statuses: list[dict] = []

    # ComfyUI: HTTP probe on :8188
    try:
        from assetboy.execution.comfyui_runner import (
            COMFYUI_API,
            is_comfyui_running,
        )
        comfy_up = is_comfyui_running()
        statuses.append({
            "provider": "comfyui",
            "available": comfy_up,
            "notes": f"server at {COMFYUI_API}" if comfy_up else "not running on :8188",
        })
    except ImportError as exc:
        statuses.append({
            "provider": "comfyui",
            "available": False,
            "notes": f"import_failed: {exc}",
        })

    # local_image / sd.cpp: check for sd binary (best-effort)
    # The runner has no public is_available helper; do a lightweight check
    # by inspecting the module import succeeds.
    try:
        import assetboy.execution.local_image_runner as _lir  # noqa: F401
        statuses.append({
            "provider": "local_image",
            "available": True,
            "notes": "runner importable (actual sd.exe binary check is per-invocation)",
        })
    except ImportError as exc:
        statuses.append({
            "provider": "local_image",
            "available": False,
            "notes": f"import_failed: {exc}",
        })

    # Stable Audio: explicit availability check
    try:
        from assetboy.execution.stable_audio_runner import (
            is_stable_audio_available,
        )
        sa_avail = is_stable_audio_available()
        statuses.append({
            "provider": "stable_audio_open_small",
            "available": sa_avail,
            "notes": (
                "model + runner configured"
                if sa_avail
                else "set STABLE_AUDIO_MODEL_DIR + STABLE_AUDIO_RUNNER_BIN env vars"
            ),
        })
    except ImportError as exc:
        statuses.append({
            "provider": "stable_audio_open_small",
            "available": False,
            "notes": f"import_failed: {exc}",
        })

    any_available = any(s["available"] for s in statuses)

    if json_out:
        json.dump(
            {"generators": statuses, "any_available": any_available},
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        print(f"gen_status_all_any_available={'true' if any_available else 'false'}")
        for s in statuses:
            avail = "true" if s["available"] else "false"
            print(f"gen_status  {s['provider']:30}  available={avail:5}  {s['notes']}")

    if not any_available:
        raise typer.Exit(code=1)


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


# --------------------------------------------------------------------------- #
# gen comfyui submit-workflow  (v1.9.s25)
# --------------------------------------------------------------------------- #

@comfy_app.command("submit-workflow")
def comfy_submit_workflow_cmd(
    workflow_path: Annotated[
        Path,
        typer.Argument(
            help="Path to a ComfyUI workflow JSON file (the /prompt-format payload).",
        ),
    ],
    params: Annotated[
        list[str],
        typer.Option(
            "--param",
            help=(
                "Workflow parameter override: 'node.field=value' (repeatable). "
                "E.g. --param '6.text=stone wall mossy' --param '5.seed=42'."
            ),
        ),
    ] = None,
    poll_interval_s: Annotated[
        float,
        typer.Option(
            "--poll-interval",
            help="Seconds between /history/{id} polls (default 1.0).",
        ),
    ] = 1.0,
    timeout_s: Annotated[
        float,
        typer.Option(
            "--timeout",
            help="Max seconds to wait for workflow completion (default 300).",
        ),
    ] = 300.0,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Directory to write downloaded output files (default: ./comfyui_out/<prompt_id>/).",
        ),
    ] = Path("."),
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Submit an arbitrary ComfyUI workflow JSON (Path B v1.9.s25).

    Reads a workflow JSON file, optionally applies --param overrides
    (e.g. `--param 6.text=...`), POSTs to local ComfyUI :8188/prompt,
    polls /history/{prompt_id} until done, downloads output files.

    Workflow JSON shape (standard ComfyUI 'API format'):
      { "<node_id>": {"class_type": "...", "inputs": {<field>: <value>}}, ... }

    --param 'N.field=value' overrides nodes[N].inputs[field] before submit.
    Use for parameterized workflows (prompt text, seed, etc.).
    """
    import urllib.error
    import urllib.parse
    import urllib.request
    from assetboy.execution.comfyui_runner import COMFYUI_API, is_comfyui_running

    if not workflow_path.exists():
        msg = f"workflow_not_found: {workflow_path}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_comfyui_submit_error={msg}")
        raise typer.Exit(code=1)

    if not is_comfyui_running():
        msg = "comfyui_not_running (start ComfyUI on :8188 first)"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_comfyui_submit_error={msg}")
        raise typer.Exit(code=1)

    # Load workflow JSON
    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except Exception as exc:
        msg = f"workflow_parse_failed: {exc}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_comfyui_submit_error={msg}")
        raise typer.Exit(code=1)

    # Apply --param overrides: "N.field=value"
    applied_overrides: list[dict] = []
    for p in (params or []):
        try:
            key, value = p.split("=", 1)
            node_id, field_name = key.rsplit(".", 1)
        except ValueError:
            msg = f"bad_param_shape: {p!r} (expected 'node_id.field=value')"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"gen_comfyui_submit_error={msg}")
            raise typer.Exit(code=1)
        if node_id not in workflow:
            msg = f"unknown_node: {node_id!r} (workflow has nodes: {list(workflow.keys())[:5]}...)"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"gen_comfyui_submit_error={msg}")
            raise typer.Exit(code=1)
        node = workflow[node_id]
        if not isinstance(node, dict) or "inputs" not in node:
            continue
        # Try to coerce value: int/float if possible, else string
        coerced: object = value
        try:
            coerced = int(value)
        except ValueError:
            try:
                coerced = float(value)
            except ValueError:
                pass
        node["inputs"][field_name] = coerced
        applied_overrides.append({"node": node_id, "field": field_name, "value": coerced})

    # POST /prompt
    payload = json.dumps({"prompt": workflow}).encode("utf-8")
    req = urllib.request.Request(
        f"{COMFYUI_API}/prompt",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            submit_resp = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        msg = f"submit_failed: HTTP {exc.code}: {body}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_comfyui_submit_error={msg}")
        raise typer.Exit(code=1)
    except Exception as exc:
        msg = f"submit_failed: {exc}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_comfyui_submit_error={msg}")
        raise typer.Exit(code=1)

    prompt_id = submit_resp.get("prompt_id")
    if not prompt_id:
        msg = f"no_prompt_id_in_response: {submit_resp}"
        if json_out:
            json.dump({"error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_comfyui_submit_error={msg}")
        raise typer.Exit(code=1)

    if not json_out:
        print(f"gen_comfyui_submit_prompt_id={prompt_id}")
        print(f"gen_comfyui_submit_overrides_applied={len(applied_overrides)}")

    # Poll /history/{prompt_id}
    import time as _time
    deadline = _time.time() + timeout_s
    history_entry: dict | None = None
    while _time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"{COMFYUI_API}/history/{prompt_id}", timeout=10
            ) as resp:
                history = json.loads(resp.read())
        except Exception:
            _time.sleep(poll_interval_s)
            continue
        if prompt_id in history:
            history_entry = history[prompt_id]
            break
        _time.sleep(poll_interval_s)

    if history_entry is None:
        msg = f"timeout_waiting_for_completion (prompt_id={prompt_id}, {timeout_s}s elapsed)"
        if json_out:
            json.dump({"error": msg, "prompt_id": prompt_id}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_comfyui_submit_error={msg}")
        raise typer.Exit(code=1)

    # Resolve output dir
    out_dir = output_dir if output_dir != Path(".") else Path(".") / "comfyui_out" / prompt_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # Download outputs
    downloaded: list[str] = []
    outputs = history_entry.get("outputs", {})
    for node_id, node_output in outputs.items():
        for img in (node_output.get("images") or []):
            fname = img.get("filename")
            subfolder = img.get("subfolder", "")
            ftype = img.get("type", "output")
            if not fname:
                continue
            query = urllib.parse.urlencode({"filename": fname, "subfolder": subfolder, "type": ftype})
            url = f"{COMFYUI_API}/view?{query}"
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = resp.read()
                dest = out_dir / fname
                dest.write_bytes(data)
                downloaded.append(str(dest))
            except Exception as exc:
                if not json_out:
                    print(f"  warn: download_failed for {fname}: {exc}")

    summary = {
        "prompt_id": prompt_id,
        "workflow_path": str(workflow_path),
        "overrides_applied": applied_overrides,
        "output_dir": str(out_dir),
        "downloaded": downloaded,
        "download_count": len(downloaded),
        "ok": True,
    }
    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_comfyui_submit_output_dir={out_dir}")
        print(f"gen_comfyui_submit_downloaded_count={len(downloaded)}")
        for d in downloaded:
            print(f"  downloaded={d}")


if __name__ == "__main__":
    app()
