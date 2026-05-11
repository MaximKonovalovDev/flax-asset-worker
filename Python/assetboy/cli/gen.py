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

met_app = typer.Typer(
    name="met-museum",
    help="Metropolitan Museum of Art Open Access (CC0) image fetcher.",
    add_completion=False,
    no_args_is_help=True,
)
wikimedia_app = typer.Typer(
    name="wikimedia",
    help="Wikimedia Commons CC-licensed media fetcher.",
    add_completion=False,
    no_args_is_help=True,
)
archive_app = typer.Typer(
    name="archive-org",
    help="Internet Archive (archive.org) CC/PD media fetcher.",
    add_completion=False,
    no_args_is_help=True,
)
scryfall_app = typer.Typer(
    name="scryfall",
    help="Scryfall MTG card art fetcher (CC-BY-SA-4.0).",
    add_completion=False,
    no_args_is_help=True,
)
iconify_app = typer.Typer(
    name="iconify",
    help="Iconify open-source icon fetcher (MIT/Apache/CC0/OFL).",
    add_completion=False,
    no_args_is_help=True,
)
pexels_app = typer.Typer(
    name="pexels",
    help="Pexels free stock photos + videos (requires PEXELS_API_KEY env).",
    add_completion=False,
    no_args_is_help=True,
)
pixabay_app = typer.Typer(
    name="pixabay",
    help="Pixabay CC0-equivalent photos + videos + vectors (requires PIXABAY_API_KEY env).",
    add_completion=False,
    no_args_is_help=True,
)

app.add_typer(comfy_app, name="comfyui")
app.add_typer(sd_app, name="sd")
app.add_typer(met_app, name="met-museum")
app.add_typer(wikimedia_app, name="wikimedia")
app.add_typer(archive_app, name="archive-org")
app.add_typer(scryfall_app, name="scryfall")
app.add_typer(iconify_app, name="iconify")
app.add_typer(pexels_app, name="pexels")
app.add_typer(pixabay_app, name="pixabay")


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


# --------------------------------------------------------------------------- #
# gen met-museum fetch  (v1.10.s26)
# --------------------------------------------------------------------------- #

@met_app.command("fetch")
def met_fetch_cmd(
    query: Annotated[
        str,
        typer.Option("--query", "-q", help="Search term (matches title/artist/medium)."),
    ],
    count: Annotated[
        int, typer.Option("--count", "-n", help="Max public-domain images to download."),
    ] = 6,
    pack_id: Annotated[
        str,
        typer.Option("--pack-id", help="Pack id for output dir (default: derived from query)."),
    ] = "",
    department_id: Annotated[
        int,
        typer.Option(
            "--department",
            help="Met department filter (e.g. 13=Greek/Roman, 11=European Paintings).",
        ),
    ] = -1,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Override output dir (default: <manual_drop>/met_museum/<pack_id>/).",
        ),
    ] = Path(""),
    small: Annotated[
        bool,
        typer.Option("--small", help="Use primaryImageSmall (faster) instead of primaryImage."),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Plan only; hit search but skip image downloads."),
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Fetch CC0 reference images from The Met (Path B v1.10.s26).

    The Metropolitan Museum of Art Open Access program publishes ~500K artworks
    as CC0 public domain. This command searches by free-text query, filters to
    isPublicDomain=true objects, and downloads up to --count primary images
    along with a JSON manifest (titles, artists, dates, license).

    Examples:
      assetboy gen met-museum fetch -q "roman fresco" -n 4
      assetboy gen met-museum fetch -q "japanese woodblock" --department 6 -n 8
      assetboy gen met-museum fetch -q "ancient greek vase" --small --dry-run

    Output: <manual_drop>/met_museum/<pack_id>/ contains the image files +
    met_museum_manifest.json with per-image metadata.
    """
    from assetboy.execution.met_museum_runner import run_met_museum_batch

    dep_id: int | None = department_id if department_id >= 0 else None
    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None

    try:
        result = run_met_museum_batch(
            query=query,
            pack_id=pack_id_arg,
            count=count,
            department_id=dep_id,
            output_dir=out_dir_arg,
            use_small_image=small,
            dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"met_museum_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_met_museum_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok,
        "pack_id": result.pack_id,
        "query": result.query,
        "output_dir": str(result.output_dir),
        "objects_matched": result.objects_matched,
        "objects_public_domain": result.objects_public_domain,
        "objects_downloaded": result.objects_downloaded,
        "objects_skipped_non_pd": result.objects_skipped_non_pd,
        "objects_failed": result.objects_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_met_museum_pack_id={result.pack_id}")
        print(f"gen_met_museum_query={result.query!r}")
        print(f"gen_met_museum_matched={result.objects_matched}")
        print(f"gen_met_museum_downloaded={result.objects_downloaded}")
        print(f"gen_met_museum_skipped_non_pd={result.objects_skipped_non_pd}")
        print(f"gen_met_museum_failed={result.objects_failed}")
        print(f"gen_met_museum_output_dir={result.output_dir}")
        if result.manifest_path:
            print(f"gen_met_museum_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_met_museum_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# gen wikimedia fetch  (v1.10.s27)
# --------------------------------------------------------------------------- #

@wikimedia_app.command("fetch")
def wikimedia_fetch_cmd(
    query: Annotated[
        str, typer.Option("--query", "-q", help="Free-text search term."),
    ],
    count: Annotated[
        int, typer.Option("--count", "-n", help="Max CC-licensed files to download."),
    ] = 6,
    pack_id: Annotated[
        str,
        typer.Option("--pack-id", help="Pack id for output dir (default: derived from query)."),
    ] = "",
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Override output dir (default: <manual_drop>/wikimedia/<pack_id>/).",
        ),
    ] = Path(""),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Plan only; skip binary image downloads."),
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Fetch CC-licensed images from Wikimedia Commons (Path B v1.10.s27).

    Wikimedia Commons hosts ~100M media files. This command searches the
    File: namespace, filters to CC-BY / CC-BY-SA / CC0 / Public Domain only
    (restrictive licenses are skipped), and downloads up to --count images
    along with a JSON manifest (titles, license, artist HTML, dimensions).

    Examples:
      assetboy gen wikimedia fetch -q "roman fresco" -n 4
      assetboy gen wikimedia fetch -q "medieval stone wall texture" -n 8
      assetboy gen wikimedia fetch -q "japanese ukiyo-e" --dry-run

    Output: <manual_drop>/wikimedia/<pack_id>/ contains image files plus
    wikimedia_manifest.json with per-file license + attribution data.
    """
    from assetboy.execution.wikimedia_runner import run_wikimedia_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None

    try:
        result = run_wikimedia_batch(
            query=query,
            pack_id=pack_id_arg,
            count=count,
            output_dir=out_dir_arg,
            dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"wikimedia_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_wikimedia_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok,
        "pack_id": result.pack_id,
        "query": result.query,
        "output_dir": str(result.output_dir),
        "files_matched": result.files_matched,
        "files_accepted_license": result.files_accepted_license,
        "files_downloaded": result.files_downloaded,
        "files_skipped_restricted": result.files_skipped_restricted,
        "files_failed": result.files_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_wikimedia_pack_id={result.pack_id}")
        print(f"gen_wikimedia_query={result.query!r}")
        print(f"gen_wikimedia_matched={result.files_matched}")
        print(f"gen_wikimedia_downloaded={result.files_downloaded}")
        print(f"gen_wikimedia_skipped_restricted={result.files_skipped_restricted}")
        print(f"gen_wikimedia_failed={result.files_failed}")
        print(f"gen_wikimedia_output_dir={result.output_dir}")
        if result.manifest_path:
            print(f"gen_wikimedia_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_wikimedia_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# gen archive-org fetch  (v1.10.s28)
# --------------------------------------------------------------------------- #

@archive_app.command("fetch")
def archive_fetch_cmd(
    query: Annotated[
        str,
        typer.Option(
            "--query", "-q",
            help="Lucene-ish query (e.g. 'subject:roman' or 'creator:nasa').",
        ),
    ],
    mediatype: Annotated[
        str,
        typer.Option(
            "--mediatype",
            help="Restrict to one mediatype: image | audio | movies | texts.",
        ),
    ] = "",
    count: Annotated[
        int, typer.Option("--count", "-n", help="Max CC/PD items to download."),
    ] = 4,
    pack_id: Annotated[
        str,
        typer.Option("--pack-id", help="Pack id for output dir."),
    ] = "",
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Override output dir (default: <manual_drop>/archive_org/<pack_id>/).",
        ),
    ] = Path(""),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Plan only; skip binary downloads."),
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Fetch CC/PD media from the Internet Archive (Path B v1.10.s28).

    archive.org hosts ~50M+ items. This command runs advancedsearch.php,
    filters to items with CC-BY / CC-BY-SA / CC0 / Public Domain licenseurl,
    picks one preview-quality file per item, and downloads up to --count
    files along with a JSON manifest.

    Examples:
      assetboy gen archive-org fetch -q "subject:roman" --mediatype image -n 4
      assetboy gen archive-org fetch -q "creator:NASA" --mediatype image -n 8
      assetboy gen archive-org fetch -q "ambient field recording" --mediatype audio -n 6

    Output: <manual_drop>/archive_org/<pack_id>/ contains the downloaded files
    plus archive_org_manifest.json with per-item identifiers + license URLs.
    """
    from assetboy.execution.archive_org_runner import run_archive_org_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None
    mediatype_arg: str | None = mediatype.strip().lower() if mediatype.strip() else None

    try:
        result = run_archive_org_batch(
            query=query,
            mediatype=mediatype_arg,
            pack_id=pack_id_arg,
            count=count,
            output_dir=out_dir_arg,
            dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"archive_org_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_archive_org_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok,
        "pack_id": result.pack_id,
        "query": result.query,
        "output_dir": str(result.output_dir),
        "items_matched": result.items_matched,
        "items_accepted_license": result.items_accepted_license,
        "items_downloaded": result.items_downloaded,
        "items_skipped_restricted": result.items_skipped_restricted,
        "items_failed": result.items_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_archive_org_pack_id={result.pack_id}")
        print(f"gen_archive_org_query={result.query!r}")
        print(f"gen_archive_org_matched={result.items_matched}")
        print(f"gen_archive_org_downloaded={result.items_downloaded}")
        print(f"gen_archive_org_skipped_restricted={result.items_skipped_restricted}")
        print(f"gen_archive_org_failed={result.items_failed}")
        print(f"gen_archive_org_output_dir={result.output_dir}")
        if result.manifest_path:
            print(f"gen_archive_org_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_archive_org_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# gen scryfall fetch  (v1.10.s29)
# --------------------------------------------------------------------------- #

@scryfall_app.command("fetch")
def scryfall_fetch_cmd(
    query: Annotated[
        str,
        typer.Option(
            "--query", "-q",
            help="Scryfall query syntax (e.g. 'type:dragon', 'art:landscape c:r').",
        ),
    ],
    count: Annotated[
        int, typer.Option("--count", "-n", help="Max cards to download."),
    ] = 6,
    variant: Annotated[
        str,
        typer.Option(
            "--variant",
            help="Image variant: png | large | normal | small | art_crop | border_crop.",
        ),
    ] = "art_crop",
    pack_id: Annotated[
        str, typer.Option("--pack-id", help="Pack id for output dir."),
    ] = "",
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Override output dir."),
    ] = Path(""),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Plan only; skip binary downloads."),
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Fetch CC-BY-SA card art from Scryfall (Path B v1.10.s29).

    Scryfall hosts ~25K MTG cards' images, all CC-BY-SA-4.0. Useful for
    fantasy reference plates, card UI mood boards, ComfyUI img2img seeds.

    Variants:
      art_crop   art only, no frame      -> best for img2img seed
      png        745x1040 full card      -> best for UI mood / framed
      large      672x936 full card
      normal     488x680
      small      146x204
      border_crop full card minus border

    Examples:
      assetboy gen scryfall fetch -q "type:dragon" -n 8
      assetboy gen scryfall fetch -q "art:landscape c:r" --variant art_crop -n 6
      assetboy gen scryfall fetch -q "set:lea" --variant png -n 10  # Alpha set

    Output: <manual_drop>/scryfall/<pack_id>/ contains image files plus
    scryfall_manifest.json with artist/set/license attribution data.

    IMPORTANT: CC-BY-SA-4.0 requires attribution. Manifest captures the
    'artist' field per card; downstream credits must use it. Also subject
    to Wizards' fan content policy for derivative use.
    """
    from assetboy.execution.scryfall_runner import run_scryfall_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None

    try:
        result = run_scryfall_batch(
            query=query,
            pack_id=pack_id_arg,
            count=count,
            variant=variant,
            output_dir=out_dir_arg,
            dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"scryfall_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_scryfall_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok,
        "pack_id": result.pack_id,
        "query": result.query,
        "variant": result.variant,
        "output_dir": str(result.output_dir),
        "cards_matched": result.cards_matched,
        "cards_with_image": result.cards_with_image,
        "cards_downloaded": result.cards_downloaded,
        "cards_failed": result.cards_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_scryfall_pack_id={result.pack_id}")
        print(f"gen_scryfall_query={result.query!r}")
        print(f"gen_scryfall_variant={result.variant}")
        print(f"gen_scryfall_matched={result.cards_matched}")
        print(f"gen_scryfall_downloaded={result.cards_downloaded}")
        print(f"gen_scryfall_failed={result.cards_failed}")
        print(f"gen_scryfall_output_dir={result.output_dir}")
        if result.manifest_path:
            print(f"gen_scryfall_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_scryfall_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# gen iconify fetch  (v1.10.s30)
# --------------------------------------------------------------------------- #

@iconify_app.command("fetch")
def iconify_fetch_cmd(
    query: Annotated[
        str, typer.Option("--query", "-q", help="Free-text icon search."),
    ],
    count: Annotated[
        int, typer.Option("--count", "-n", help="Max icons to download."),
    ] = 16,
    width: Annotated[
        int, typer.Option("--width", help="Render width in pixels (height auto-scales)."),
    ] = 64,
    color: Annotated[
        str,
        typer.Option(
            "--color",
            help="Hex color override like '#FF6600' (default: original colors).",
        ),
    ] = "",
    pack_id: Annotated[
        str, typer.Option("--pack-id"),
    ] = "",
    output_dir: Annotated[
        Path, typer.Option("--output-dir"),
    ] = Path(""),
    skip_collections_check: Annotated[
        bool,
        typer.Option(
            "--skip-license-check",
            help="DANGER: skip /collections license filter; download all matches.",
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Plan only; skip SVG downloads."),
    ] = False,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Fetch open-licensed icons from Iconify (Path B v1.10.s30).

    Iconify aggregates 150+ open-source icon sets (Material, Tabler, Lucide,
    Phosphor, Game-Icons, Carbon, Heroicons, etc.). This command searches,
    filters to MIT/Apache/CC0/CC-BY/OFL/GPL licenses, and downloads SVGs.

    Examples:
      assetboy gen iconify fetch -q "sword" -n 20
      assetboy gen iconify fetch -q "inventory" --width 128 --color "#FFAA00" -n 12
      assetboy gen iconify fetch -q "dragon" --skip-license-check -n 30

    Output: <manual_drop>/iconify/<pack_id>/*.svg plus iconify_manifest.json
    with per-icon collection + license SPDX + source URL.
    """
    from assetboy.execution.iconify_runner import run_iconify_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None
    color_arg: str | None = color if color.strip() else None

    try:
        result = run_iconify_batch(
            query=query,
            pack_id=pack_id_arg,
            count=count,
            width=width,
            color=color_arg,
            output_dir=out_dir_arg,
            skip_collections_check=skip_collections_check,
            dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"iconify_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_iconify_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok,
        "pack_id": result.pack_id,
        "query": result.query,
        "output_dir": str(result.output_dir),
        "icons_matched": result.icons_matched,
        "icons_accepted_license": result.icons_accepted_license,
        "icons_downloaded": result.icons_downloaded,
        "icons_skipped_restricted": result.icons_skipped_restricted,
        "icons_failed": result.icons_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_iconify_pack_id={result.pack_id}")
        print(f"gen_iconify_query={result.query!r}")
        print(f"gen_iconify_matched={result.icons_matched}")
        print(f"gen_iconify_downloaded={result.icons_downloaded}")
        print(f"gen_iconify_skipped_restricted={result.icons_skipped_restricted}")
        print(f"gen_iconify_failed={result.icons_failed}")
        print(f"gen_iconify_output_dir={result.output_dir}")
        if result.manifest_path:
            print(f"gen_iconify_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_iconify_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# gen pexels photos / videos  (v1.10.s31)
# --------------------------------------------------------------------------- #

@pexels_app.command("photos")
def pexels_photos_cmd(
    query: Annotated[str, typer.Option("--query", "-q", help="Free-text search.")],
    count: Annotated[int, typer.Option("--count", "-n")] = 6,
    variant: Annotated[
        str,
        typer.Option(
            "--variant",
            help="src key: original | large2x | large | medium | small | tiny | "
                 "portrait | landscape.",
        ),
    ] = "large",
    pack_id: Annotated[str, typer.Option("--pack-id")] = "",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path(""),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fetch free stock photos from Pexels (Path B v1.10.s31).

    Requires PEXELS_API_KEY env var (free signup at pexels.com/api).
    All photos under Pexels License: free personal + commercial, no attrib req.

    Examples:
      assetboy gen pexels photos -q "stone wall" -n 4 --variant large
      assetboy gen pexels photos -q "fire" --variant original -n 2
    """
    from assetboy.execution.pexels_runner import run_pexels_photo_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None

    try:
        result = run_pexels_photo_batch(
            query=query, pack_id=pack_id_arg, count=count, variant=variant,
            output_dir=out_dir_arg, dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"pexels_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_pexels_photos_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok, "kind": "photos",
        "pack_id": result.pack_id, "query": result.query,
        "output_dir": str(result.output_dir),
        "items_matched": result.items_matched,
        "items_downloaded": result.items_downloaded,
        "items_failed": result.items_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }
    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_pexels_photos_pack_id={result.pack_id}")
        print(f"gen_pexels_photos_matched={result.items_matched}")
        print(f"gen_pexels_photos_downloaded={result.items_downloaded}")
        print(f"gen_pexels_photos_failed={result.items_failed}")
        print(f"gen_pexels_photos_output_dir={result.output_dir}")
        if result.manifest_path:
            print(f"gen_pexels_photos_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_pexels_photos_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


@pexels_app.command("videos")
def pexels_videos_cmd(
    query: Annotated[str, typer.Option("--query", "-q", help="Free-text search.")],
    count: Annotated[int, typer.Option("--count", "-n")] = 3,
    max_height: Annotated[
        int,
        typer.Option(
            "--max-height",
            help="Prefer highest-quality file at or below this many pixels.",
        ),
    ] = 1080,
    pack_id: Annotated[str, typer.Option("--pack-id")] = "",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path(""),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fetch free stock videos from Pexels (FAW's first video provider).

    Requires PEXELS_API_KEY. Pexels License: free personal + commercial.

    Examples:
      assetboy gen pexels videos -q "fire crackling" -n 2 --max-height 1080
      assetboy gen pexels videos -q "ocean waves" --max-height 720 -n 4
    """
    from assetboy.execution.pexels_runner import run_pexels_video_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None

    try:
        result = run_pexels_video_batch(
            query=query, pack_id=pack_id_arg, count=count,
            max_height=max_height, output_dir=out_dir_arg, dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"pexels_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_pexels_videos_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok, "kind": "videos",
        "pack_id": result.pack_id, "query": result.query,
        "output_dir": str(result.output_dir),
        "items_matched": result.items_matched,
        "items_downloaded": result.items_downloaded,
        "items_failed": result.items_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }
    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_pexels_videos_pack_id={result.pack_id}")
        print(f"gen_pexels_videos_matched={result.items_matched}")
        print(f"gen_pexels_videos_downloaded={result.items_downloaded}")
        print(f"gen_pexels_videos_failed={result.items_failed}")
        print(f"gen_pexels_videos_output_dir={result.output_dir}")
        if result.manifest_path:
            print(f"gen_pexels_videos_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_pexels_videos_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# gen pixabay photos / videos  (v1.10.s32)
# --------------------------------------------------------------------------- #

@pixabay_app.command("photos")
def pixabay_photos_cmd(
    query: Annotated[str, typer.Option("--query", "-q")],
    count: Annotated[int, typer.Option("--count", "-n")] = 6,
    image_type: Annotated[
        str,
        typer.Option(
            "--image-type",
            help="photo | illustration | vector | all (default: photo).",
        ),
    ] = "photo",
    variant: Annotated[
        str,
        typer.Option(
            "--variant",
            help="URL key: largeImageURL | fullHDURL | imageURL | webformatURL | previewURL.",
        ),
    ] = "largeImageURL",
    pack_id: Annotated[str, typer.Option("--pack-id")] = "",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path(""),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fetch CC0-equivalent photos/illustrations/vectors from Pixabay.

    Pixabay Content License = CC0-equivalent (free personal+commercial, no attrib).
    Requires PIXABAY_API_KEY env (free signup at pixabay.com/api/docs/).

    Examples:
      assetboy gen pixabay photos -q "stone wall" -n 6
      assetboy gen pixabay photos -q "fantasy castle" --image-type illustration -n 4
      assetboy gen pixabay photos -q "leaf" --image-type vector -n 8
    """
    from assetboy.execution.pixabay_runner import run_pixabay_photo_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None

    try:
        result = run_pixabay_photo_batch(
            query=query, pack_id=pack_id_arg, count=count,
            image_type=image_type, variant=variant,
            output_dir=out_dir_arg, dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"pixabay_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_pixabay_photos_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok, "kind": "photos",
        "pack_id": result.pack_id, "query": result.query,
        "output_dir": str(result.output_dir),
        "items_matched": result.items_matched,
        "items_downloaded": result.items_downloaded,
        "items_failed": result.items_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }
    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_pixabay_photos_pack_id={result.pack_id}")
        print(f"gen_pixabay_photos_matched={result.items_matched}")
        print(f"gen_pixabay_photos_downloaded={result.items_downloaded}")
        print(f"gen_pixabay_photos_failed={result.items_failed}")
        print(f"gen_pixabay_photos_output_dir={result.output_dir}")
        if result.manifest_path:
            print(f"gen_pixabay_photos_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_pixabay_photos_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


@pixabay_app.command("videos")
def pixabay_videos_cmd(
    query: Annotated[str, typer.Option("--query", "-q")],
    count: Annotated[int, typer.Option("--count", "-n")] = 3,
    variant: Annotated[
        str,
        typer.Option("--variant", help="large (1920x1080) | medium (1280x720, default) | small | tiny."),
    ] = "medium",
    pack_id: Annotated[str, typer.Option("--pack-id")] = "",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path(""),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fetch CC0-equivalent stock videos from Pixabay.

    Requires PIXABAY_API_KEY. Twin to 'gen pexels videos' for redundancy.

    Examples:
      assetboy gen pixabay videos -q "fire" -n 2 --variant large
      assetboy gen pixabay videos -q "rain" --variant medium -n 4
    """
    from assetboy.execution.pixabay_runner import run_pixabay_video_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None

    try:
        result = run_pixabay_video_batch(
            query=query, pack_id=pack_id_arg, count=count, variant=variant,
            output_dir=out_dir_arg, dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"pixabay_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_pixabay_videos_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok, "kind": "videos",
        "pack_id": result.pack_id, "query": result.query,
        "output_dir": str(result.output_dir),
        "items_matched": result.items_matched,
        "items_downloaded": result.items_downloaded,
        "items_failed": result.items_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }
    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_pixabay_videos_pack_id={result.pack_id}")
        print(f"gen_pixabay_videos_matched={result.items_matched}")
        print(f"gen_pixabay_videos_downloaded={result.items_downloaded}")
        print(f"gen_pixabay_videos_failed={result.items_failed}")
        print(f"gen_pixabay_videos_output_dir={result.output_dir}")
        if result.manifest_path:
            print(f"gen_pixabay_videos_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_pixabay_videos_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
