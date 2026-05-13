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
rawg_app = typer.Typer(
    name="rawg",
    help="RAWG.io game DB (covers + screenshots; reference-only; requires RAWG_API_KEY env).",
    add_completion=False,
    no_args_is_help=True,
)
jamendo_app = typer.Typer(
    name="jamendo",
    help="Jamendo CC-licensed music tracks (requires JAMENDO_CLIENT_ID env).",
    add_completion=False,
    no_args_is_help=True,
)
unsplash_app = typer.Typer(
    name="unsplash",
    help="Unsplash free stock photos (requires UNSPLASH_ACCESS_KEY env).",
    add_completion=False,
    no_args_is_help=True,
)
inaturalist_app = typer.Typer(
    name="inaturalist",
    help="iNaturalist CC-licensed nature observation photos (no key).",
    add_completion=False,
    no_args_is_help=True,
)
openlibrary_app = typer.Typer(
    name="openlibrary",
    help="Open Library book cover images (reference-only; no key).",
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
app.add_typer(rawg_app, name="rawg")
app.add_typer(jamendo_app, name="jamendo")
app.add_typer(unsplash_app, name="unsplash")
app.add_typer(inaturalist_app, name="inaturalist")
app.add_typer(openlibrary_app, name="openlibrary")


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

@met_app.command("departments")
def met_departments_cmd(
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List all Met Museum departments (v1.23.s158).

    Helpful for picking a --department id for fetch.
    Common: 11=European Paintings, 13=Greek/Roman, 6=Asian, 9=Drawings/Prints.
    """
    from assetboy.execution.met_museum_runner import list_met_departments

    try:
        depts = list_met_departments()
    except Exception as exc:
        msg = f"met_departments_failed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_met_museum_departments_error={msg}")
        raise typer.Exit(code=1)

    if json_out:
        json.dump({"departments": depts, "count": len(depts)},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_met_museum_departments_count={len(depts)}")
        for d in depts:
            did = d.get("departmentId")
            name = d.get("displayName", "")
            print(f"  {did:>3}  {name}")


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
    ] = "",
    category: Annotated[
        str,
        typer.Option(
            "--category",
            help=(
                "v1.19.s134: walk a Wikimedia category instead of free-text"
                " search. Pass without 'Category:' prefix (added automatically)."
            ),
        ),
    ] = "",
    count: Annotated[
        int, typer.Option("--count", "-n", help="Max CC-licensed files to download."),
    ] = 6,
    license_filter: Annotated[
        str,
        typer.Option(
            "--license",
            help=(
                "v1.25.s173: narrow accepted licenses to one family:"
                " 'cc0' | 'pd' | 'cc-by' | 'cc-by-sa'. Default empty"
                " (accept any of those four)."
            ),
        ),
    ] = "",
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

    if not query.strip() and not category.strip():
        msg = "missing_query_or_category"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_wikimedia_error={msg}")
        raise typer.Exit(code=1)

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None
    category_arg: str | None = category.strip() or None  # v1.19.s134

    license_filter_arg: str | None = license_filter.strip().lower() or None  # v1.25.s173

    try:
        result = run_wikimedia_batch(
            query=query,
            pack_id=pack_id_arg,
            count=count,
            category=category_arg,
            license_filter=license_filter_arg,
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
    collection: Annotated[
        str,
        typer.Option(
            "--collection",
            help=(
                "v1.20.s140: scope to an archive.org collection id"
                " (e.g. 'prelinger', 'librivoxaudio', 'image_collection')."
            ),
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
    collection_arg: str | None = collection.strip() or None  # v1.20.s140

    try:
        result = run_archive_org_batch(
            query=query,
            mediatype=mediatype_arg,
            collection=collection_arg,
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
    set_code: Annotated[
        str,
        typer.Option(
            "--set",
            help=(
                "v1.22.s153: Scryfall set code (e.g. 'cmm', 'lea', 'mh3')."
                " Appends 'set:<code>' to query."
            ),
        ),
    ] = "",
    card_type: Annotated[
        str,
        typer.Option(
            "--type",
            help=(
                "v1.24.s164: card type filter (e.g. 'creature', 'land',"
                " 'artifact', 'planeswalker'). Appends 'type:<value>' to query."
            ),
        ),
    ] = "",
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
    set_code_arg: str | None = set_code.strip() or None  # v1.22.s153
    card_type_arg: str | None = card_type.strip() or None  # v1.24.s164

    try:
        result = run_scryfall_batch(
            query=query,
            pack_id=pack_id_arg,
            count=count,
            variant=variant,
            set_code=set_code_arg,
            card_type=card_type_arg,
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

@iconify_app.command("list-sets")
def iconify_list_sets_cmd(
    accepted_only: Annotated[
        bool,
        typer.Option(
            "--accepted-only",
            help="Show only sets whose SPDX license is in our open-source allowlist.",
        ),
    ] = False,
    limit: Annotated[
        int,
        typer.Option("--limit", help="Max sets to show in plain output (default 50)."),
    ] = 50,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Browse Iconify icon sets with license info (Path B v1.15.s111).

    Hits /collections and shows prefix, name, SPDX license, sample category.

    Examples:
      assetboy gen iconify list-sets
      assetboy gen iconify list-sets --accepted-only --limit 20
      assetboy gen iconify list-sets --json
    """
    from assetboy.execution.iconify_runner import (
        fetch_iconify_collections, is_license_accepted,
    )

    try:
        collections = fetch_iconify_collections()
    except Exception as exc:
        msg = f"iconify_collections_fetch_failed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_iconify_list_sets_error={msg}")
        raise typer.Exit(code=1)

    if not isinstance(collections, dict):
        msg = "iconify_collections_unexpected_shape"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_iconify_list_sets_error={msg}")
        raise typer.Exit(code=1)

    rows: list[dict] = []
    for prefix, meta in collections.items():
        if not isinstance(meta, dict):
            continue
        license_meta = meta.get("license") or {}
        spdx = str(license_meta.get("spdx", "") or "")
        title = str(license_meta.get("title", "") or "")
        accepted = is_license_accepted(spdx) if spdx else False
        if accepted_only and not accepted:
            continue
        rows.append({
            "prefix": prefix,
            "name": str(meta.get("name", "") or ""),
            "category": str(meta.get("category", "") or ""),
            "total": int(meta.get("total", 0) or 0),
            "license_spdx": spdx,
            "license_title": title,
            "license_accepted": accepted,
        })

    rows.sort(key=lambda r: r["prefix"])

    summary = {
        "total_sets": len(rows),
        "accepted_only_filter": accepted_only,
        "sets": rows,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_iconify_list_sets_total={len(rows)}")
        print(f"gen_iconify_list_sets_accepted_only={accepted_only}")
        for r in rows[:limit]:
            mark = "+" if r["license_accepted"] else "-"
            print(
                f"  [{mark}] {r['prefix']:24s} {r['name']:50s} "
                f"icons={r['total']:>5d}  spdx={r['license_spdx']}"
            )
        if len(rows) > limit:
            print(f"  ... and {len(rows) - limit} more (use --limit or --json)")


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
    prefix: Annotated[
        str,
        typer.Option(
            "--prefix",
            help=(
                "v1.20.s138: scope search to one or more icon sets by prefix"
                " (comma-separated; e.g. 'game-icons' or 'mdi,game-icons')."
            ),
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
    prefix_arg: str | None = prefix.strip() or None  # v1.20.s138

    try:
        result = run_iconify_batch(
            query=query,
            pack_id=pack_id_arg,
            count=count,
            width=width,
            color=color_arg,
            prefix=prefix_arg,
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
            # v1.16.s117 — attribution summary from manifest entries.
            try:
                mf_doc = json.loads(result.manifest_path.read_text(encoding="utf-8"))
                spdx_counts: dict[str, int] = {}
                attr_required: list[str] = []
                for entry in (mf_doc.get("entries") or []):
                    if not isinstance(entry, dict):
                        continue
                    spdx = str(entry.get("license_spdx", "") or "?")
                    spdx_counts[spdx] = spdx_counts.get(spdx, 0) + 1
                    # Substring check on accepted-license tokens that require credit.
                    lower = spdx.lower()
                    if ("cc-by" in lower) or ("ofl" in lower) or ("gpl" in lower) or ("lgpl" in lower):
                        attr_required.append(str(entry.get("icon_id", "?")))
                if spdx_counts:
                    parts = ", ".join(f"{k}={v}" for k, v in sorted(spdx_counts.items()))
                    print(f"gen_iconify_attribution_breakdown={parts}")
                if attr_required:
                    print(
                        f"gen_iconify_attribution_required_count={len(attr_required)} "
                        "(see manifest 'license_spdx' + 'collection' per icon)"
                    )
            except Exception as exc:
                _ = exc
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
    orientation: Annotated[
        str,
        typer.Option(
            "--orientation",
            help=(
                "v1.24.s166: filter by aspect: 'landscape' | 'portrait'"
                " | 'square' (default empty = unset, no filter)."
            ),
        ),
    ] = "",
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
    orientation_arg: str | None = orientation.strip().lower() or None

    try:
        result = run_pexels_photo_batch(
            query=query, pack_id=pack_id_arg, count=count, variant=variant,
            orientation=orientation_arg,
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
    min_duration_s: Annotated[
        float,
        typer.Option(
            "--min-duration",
            help=(
                "v1.28.s183: skip videos shorter than N seconds."
                " 0.0 (default) = no filter."
            ),
        ),
    ] = 0.0,
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
      assetboy gen pexels videos -q "fog" --min-duration 8 -n 3
    """
    from assetboy.execution.pexels_runner import run_pexels_video_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None

    try:
        result = run_pexels_video_batch(
            query=query, pack_id=pack_id_arg, count=count,
            max_height=max_height,
            min_duration_s=min_duration_s,
            output_dir=out_dir_arg, dry_run=dry_run,
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
    orientation: Annotated[
        str,
        typer.Option(
            "--orientation",
            help=(
                "v1.24.s165: filter by aspect: 'horizontal' | 'vertical'"
                " | 'all' (default empty = unset, no filter)."
            ),
        ),
    ] = "",
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

    orientation_arg: str | None = orientation.strip().lower() or None  # v1.24.s165

    try:
        result = run_pixabay_photo_batch(
            query=query, pack_id=pack_id_arg, count=count,
            image_type=image_type, variant=variant,
            orientation=orientation_arg,
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
    video_type: Annotated[
        str,
        typer.Option(
            "--video-type",
            help=(
                "v1.24.s167: filter by content kind: 'film' | 'animation'"
                " | 'all' (default empty = unset, no filter)."
            ),
        ),
    ] = "",
    min_duration_s: Annotated[
        float,
        typer.Option(
            "--min-duration",
            help=(
                "v1.29.s184: skip videos shorter than N seconds."
                " 0.0 (default) = no filter."
            ),
        ),
    ] = 0.0,
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
      assetboy gen pixabay videos -q "magic" --video-type animation -n 3
      assetboy gen pixabay videos -q "wave" --min-duration 12 -n 2
    """
    from assetboy.execution.pixabay_runner import run_pixabay_video_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None
    video_type_arg: str | None = video_type.strip().lower() or None

    try:
        result = run_pixabay_video_batch(
            query=query, pack_id=pack_id_arg, count=count, variant=variant,
            video_type=video_type_arg,
            min_duration_s=min_duration_s,
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


# --------------------------------------------------------------------------- #
# gen rawg games  (v1.10.s33)
# --------------------------------------------------------------------------- #

@rawg_app.command("games")
def rawg_games_cmd(
    query: Annotated[str, typer.Option("--query", "-q", help="Game name or theme.")],
    count: Annotated[int, typer.Option("--count", "-n")] = 6,
    genres: Annotated[
        str,
        typer.Option(
            "--genres",
            help="Comma-separated genre slugs (e.g. 'roguelike,strategy').",
        ),
    ] = "",
    platforms: Annotated[
        str,
        typer.Option(
            "--platforms",
            help=(
                "v1.18.s129: comma-separated RAWG platform IDs. Common:"
                " 4=PC, 187=PS5, 18=PS4, 1=XB1, 186=XBS, 7=Switch, 3=iOS, 21=Android."
            ),
        ),
    ] = "",
    max_screenshots: Annotated[
        int,
        typer.Option(
            "--max-screenshots",
            help="Cap short_screenshots per game (default 3; 0 to skip).",
        ),
    ] = 3,
    pack_id: Annotated[str, typer.Option("--pack-id")] = "",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path(""),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fetch game covers + screenshots from RAWG.io (Path B v1.10.s33).

    REFERENCE-ONLY USE. RAWG images are copyrighted by game publishers.
    Acceptable: mood boards, genre studies, design analysis, ComfyUI
    img2img seeds destined for transformative output.
    NOT acceptable: redistribution, inclusion in shipped games.

    Requires RAWG_API_KEY env (free signup at rawg.io/apidocs; 20K req/month).

    Examples:
      assetboy gen rawg games -q "roguelike" -n 6
      assetboy gen rawg games -q "tactics" --genres "strategy,role-playing-games-rpg" -n 4
      assetboy gen rawg games -q "metroidvania" --max-screenshots 5 -n 4
    """
    from assetboy.execution.rawg_runner import run_rawg_games_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None
    genres_arg: str | None = genres if genres.strip() else None
    platforms_arg: str | None = platforms.strip() or None  # v1.18.s129
    include_shots = max_screenshots > 0

    try:
        result = run_rawg_games_batch(
            query=query, pack_id=pack_id_arg, count=count,
            include_screenshots=include_shots,
            max_screenshots_per_game=max_screenshots,
            genres=genres_arg,
            platforms=platforms_arg,
            output_dir=out_dir_arg, dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"rawg_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_rawg_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok,
        "pack_id": result.pack_id,
        "query": result.query,
        "output_dir": str(result.output_dir),
        "games_matched": result.games_matched,
        "games_downloaded": result.games_downloaded,
        "screenshots_downloaded": result.screenshots_downloaded,
        "games_failed": result.games_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_rawg_pack_id={result.pack_id}")
        print(f"gen_rawg_query={result.query!r}")
        print(f"gen_rawg_matched={result.games_matched}")
        print(f"gen_rawg_games_downloaded={result.games_downloaded}")
        print(f"gen_rawg_screenshots_downloaded={result.screenshots_downloaded}")
        print(f"gen_rawg_failed={result.games_failed}")
        print(f"gen_rawg_output_dir={result.output_dir}")
        print("gen_rawg_USE_POLICY=reference-only_not_for_redistribution")
        if result.manifest_path:
            print(f"gen_rawg_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_rawg_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# gen jamendo tracks  (v1.10.s34)
# --------------------------------------------------------------------------- #

@jamendo_app.command("tracks")
def jamendo_tracks_cmd(
    query: Annotated[str, typer.Option("--query", "-q")],
    count: Annotated[int, typer.Option("--count", "-n")] = 4,
    allow_restrictive: Annotated[
        bool,
        typer.Option(
            "--allow-restrictive",
            help="Also accept CC-NC / CC-ND variants (default: only CC-BY/CC-BY-SA).",
        ),
    ] = False,
    instrument: Annotated[
        str,
        typer.Option(
            "--instrument",
            help=(
                "v1.21.s146: filter by instrument tag (e.g. 'piano', 'guitar',"
                " 'synthesizer'). Uses Jamendo's fuzzytags= parameter."
            ),
        ),
    ] = "",
    pack_id: Annotated[str, typer.Option("--pack-id")] = "",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path(""),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fetch CC-licensed music tracks from Jamendo (Path B v1.10.s34).

    Jamendo hosts ~500K CC-licensed tracks. By default we accept ONLY
    commercial-OK and derivative-OK variants (CC-BY, CC-BY-SA).
    Use --allow-restrictive to broaden to CC-NC / CC-ND (personal use only).

    All accepted tracks REQUIRE attribution. The manifest captures
    'attribution_text' (artist - title + license URL) per track for
    downstream credit handling.

    Requires JAMENDO_CLIENT_ID env (free signup at developer.jamendo.com).

    Examples:
      assetboy gen jamendo tracks -q "ambient cinematic" -n 3
      assetboy gen jamendo tracks -q "8-bit chiptune" -n 5
      assetboy gen jamendo tracks -q "dark orchestral" --allow-restrictive -n 4
    """
    from assetboy.execution.jamendo_runner import run_jamendo_tracks_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None
    instrument_arg: str | None = instrument.strip() or None  # v1.21.s146

    try:
        result = run_jamendo_tracks_batch(
            query=query, pack_id=pack_id_arg, count=count,
            allow_restrictive=allow_restrictive,
            instrument=instrument_arg,
            output_dir=out_dir_arg, dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"jamendo_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_jamendo_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok,
        "pack_id": result.pack_id,
        "query": result.query,
        "output_dir": str(result.output_dir),
        "tracks_matched": result.tracks_matched,
        "tracks_accepted_license": result.tracks_accepted_license,
        "tracks_downloaded": result.tracks_downloaded,
        "tracks_skipped_restricted": result.tracks_skipped_restricted,
        "tracks_failed": result.tracks_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_jamendo_pack_id={result.pack_id}")
        print(f"gen_jamendo_query={result.query!r}")
        print(f"gen_jamendo_matched={result.tracks_matched}")
        print(f"gen_jamendo_downloaded={result.tracks_downloaded}")
        print(f"gen_jamendo_skipped_restricted={result.tracks_skipped_restricted}")
        print(f"gen_jamendo_failed={result.tracks_failed}")
        print(f"gen_jamendo_output_dir={result.output_dir}")
        print("gen_jamendo_ATTRIBUTION_REQUIRED=see_per_track_attribution_text")
        if result.manifest_path:
            print(f"gen_jamendo_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_jamendo_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# gen unsplash photos  (v1.10.s35)
# --------------------------------------------------------------------------- #

@unsplash_app.command("photos")
def unsplash_photos_cmd(
    query: Annotated[str, typer.Option("--query", "-q")],
    count: Annotated[int, typer.Option("--count", "-n")] = 6,
    variant: Annotated[
        str,
        typer.Option(
            "--variant",
            help="raw | full | regular (1080w default) | small | thumb.",
        ),
    ] = "regular",
    orientation: Annotated[
        str,
        typer.Option(
            "--orientation",
            help="landscape | portrait | squarish (default: any).",
        ),
    ] = "",
    collection: Annotated[
        str,
        typer.Option(
            "--collection",
            help="v1.19.s133: comma-separated Unsplash collection IDs to scope search to.",
        ),
    ] = "",
    pack_id: Annotated[str, typer.Option("--pack-id")] = "",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path(""),
    skip_download_ping: Annotated[
        bool,
        typer.Option(
            "--skip-download-ping",
            help="Skip /photos/<id>/download analytics ping (testing only).",
        ),
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fetch free stock photos from Unsplash (Path B v1.10.s35).

    Requires UNSPLASH_ACCESS_KEY env var (free dev signup at
    unsplash.com/developers; 50 req/hour). All photos under Unsplash License:
    free personal + commercial, attribution appreciated (not required).

    Per Unsplash API guidelines, downloads automatically trigger
    /photos/<id>/download for usage analytics (suppress with
    --skip-download-ping for testing).

    Examples:
      assetboy gen unsplash photos -q "stone wall" -n 4
      assetboy gen unsplash photos -q "fog forest" --orientation landscape -n 6
      assetboy gen unsplash photos -q "neon" --variant full -n 3
    """
    from assetboy.execution.unsplash_runner import run_unsplash_photo_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None
    orientation_arg: str | None = orientation.strip().lower() if orientation.strip() else None
    collection_arg: str | None = collection.strip() or None  # v1.19.s133

    try:
        result = run_unsplash_photo_batch(
            query=query, pack_id=pack_id_arg, count=count, variant=variant,
            orientation=orientation_arg,
            collections=collection_arg,
            output_dir=out_dir_arg, dry_run=dry_run,
            skip_download_ping=skip_download_ping,
        )
    except Exception as exc:
        msg = f"unsplash_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_unsplash_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok,
        "pack_id": result.pack_id,
        "query": result.query,
        "output_dir": str(result.output_dir),
        "photos_matched": result.photos_matched,
        "photos_downloaded": result.photos_downloaded,
        "photos_failed": result.photos_failed,
        "download_pings": result.download_pings,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_unsplash_pack_id={result.pack_id}")
        print(f"gen_unsplash_query={result.query!r}")
        print(f"gen_unsplash_matched={result.photos_matched}")
        print(f"gen_unsplash_downloaded={result.photos_downloaded}")
        print(f"gen_unsplash_failed={result.photos_failed}")
        print(f"gen_unsplash_download_pings={result.download_pings}")
        print(f"gen_unsplash_output_dir={result.output_dir}")
        if result.manifest_path:
            print(f"gen_unsplash_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_unsplash_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# gen all-no-key  (v1.11.s37)
# --------------------------------------------------------------------------- #

@app.command("all-no-key")
def all_no_key_cmd(
    query: Annotated[
        str, typer.Option("--query", "-q", help="Search query (fans out across all providers)."),
    ],
    count: Annotated[
        int, typer.Option("--count", "-n", help="Per-provider count."),
    ] = 3,
    pack_id: Annotated[str, typer.Option("--pack-id")] = "",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path(""),
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Plan only across all providers; recommended default for scouting.",
        ),
    ] = True,
    parallel: Annotated[
        bool,
        typer.Option(
            "--parallel",
            help="v1.12.s64: dispatch all 5 providers concurrently (ThreadPoolExecutor); ~5x faster wall time.",
        ),
    ] = False,
    write_history: Annotated[
        bool,
        typer.Option(
            "--write-history",
            help=(
                "v1.15.s108: append this run to state/r1a_history/<utc>.json"
                " for trend tracking. One file per run; timestamped + indexed."
            ),
        ),
    ] = False,
    provider_filter: Annotated[
        str,
        typer.Option(
            "--provider",
            help=(
                "v1.21.s145: comma-separated subset of provider ids"
                " (met_museum/wikimedia/archive_org/scryfall/iconify/inaturalist)."
                " If unset, all 6 are dispatched."
            ),
        ),
    ] = "",
    bail_on_error: Annotated[
        bool,
        typer.Option(
            "--bail-on-error",
            help=(
                "v1.28.s181: stop on the first provider that fails (ok=False);"
                " skip remaining. Has no effect in --parallel mode."
                " Useful for CI / scout-debugging."
            ),
        ),
    ] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fan out one query across all 6 no-key R1A providers (Path B v1.11.s37+).

    Hits Met Museum, Wikimedia Commons, Archive.org (image mediatype),
    Scryfall, Iconify, iNaturalist. Use --parallel for concurrent dispatch.

    Examples:
      assetboy gen all-no-key -q "dragon" -n 2 --dry-run
      assetboy gen all-no-key -q "stone wall" -n 1 --parallel --no-dry-run
    """
    from assetboy.execution.met_museum_runner import run_met_museum_batch
    from assetboy.execution.wikimedia_runner import run_wikimedia_batch
    from assetboy.execution.archive_org_runner import run_archive_org_batch
    from assetboy.execution.scryfall_runner import run_scryfall_batch
    from assetboy.execution.iconify_runner import run_iconify_batch
    from assetboy.execution.inaturalist_runner import run_inaturalist_batch  # v1.13.s87

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    base_pack_id = pack_id or f"ALL_NO_KEY_{query.replace(' ', '_').upper()}"

    # v1.16.s115 — wall-time measurement for history enrichment.
    import time as _time
    _wall_start = _time.perf_counter()

    def _result_to_record(provider: str, r) -> dict:
        return {
            "provider": provider,
            "ok": r.ok,
            "matched": getattr(r, "items_matched", 0)
                       or getattr(r, "objects_matched", 0)
                       or getattr(r, "files_matched", 0)
                       or getattr(r, "cards_matched", 0)
                       or getattr(r, "icons_matched", 0)
                       or getattr(r, "observations_matched", 0),  # v1.13.s87 iNat
            "downloaded": getattr(r, "items_downloaded", 0)
                          or getattr(r, "objects_downloaded", 0)
                          or getattr(r, "files_downloaded", 0)
                          or getattr(r, "cards_downloaded", 0)
                          or getattr(r, "icons_downloaded", 0)
                          or getattr(r, "photos_downloaded", 0),  # v1.13.s87 iNat
            "manifest_path": str(r.manifest_path) if getattr(r, "manifest_path", None) else None,
            "error": r.error,
            "output_dir": str(r.output_dir),
        }

    def _crashed_record(provider: str, exc: Exception) -> dict:
        return {
            "provider": provider, "ok": False,
            "matched": 0, "downloaded": 0,
            "manifest_path": None,
            "error": f"crashed: {exc}",
            "output_dir": "",
        }

    # Build dispatch table: (provider_id, runner, kwargs).
    tasks: list[tuple[str, object, dict]] = [
        ("met_museum", run_met_museum_batch, dict(
            query=query, pack_id=f"{base_pack_id}_MET", count=count,
            output_dir=(out_dir_arg / "met_museum") if out_dir_arg else None,
            dry_run=dry_run,
        )),
        ("wikimedia", run_wikimedia_batch, dict(
            query=query, pack_id=f"{base_pack_id}_WM", count=count,
            output_dir=(out_dir_arg / "wikimedia") if out_dir_arg else None,
            dry_run=dry_run,
        )),
        ("archive_org", run_archive_org_batch, dict(
            query=query, mediatype="image",
            pack_id=f"{base_pack_id}_AO", count=count,
            output_dir=(out_dir_arg / "archive_org") if out_dir_arg else None,
            dry_run=dry_run,
        )),
        ("scryfall", run_scryfall_batch, dict(
            query=query, pack_id=f"{base_pack_id}_SF", count=count,
            output_dir=(out_dir_arg / "scryfall") if out_dir_arg else None,
            dry_run=dry_run,
        )),
        ("iconify", run_iconify_batch, dict(
            query=query, pack_id=f"{base_pack_id}_IC", count=count,
            output_dir=(out_dir_arg / "iconify") if out_dir_arg else None,
            dry_run=dry_run,
        )),
        # v1.13.s87 — iNaturalist in fan-out (now 6 no-key providers).
        ("inaturalist", run_inaturalist_batch, dict(
            query=query, pack_id=f"{base_pack_id}_INAT", count=count,
            output_dir=(out_dir_arg / "inaturalist") if out_dir_arg else None,
            dry_run=dry_run,
        )),
    ]

    # v1.21.s145 — filter tasks by --provider.
    if provider_filter.strip():
        wanted = {p.strip().lower() for p in provider_filter.split(",") if p.strip()}
        tasks = [t for t in tasks if t[0].lower() in wanted]
        if not tasks:
            msg = f"no_providers_matched_filter: {sorted(wanted)} (valid: met_museum/wikimedia/archive_org/scryfall/iconify/inaturalist)"
            if json_out:
                json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"gen_all_no_key_error={msg}")
            raise typer.Exit(code=1)

    providers_run: list[dict] = []

    if parallel:
        # v1.12.s64 — concurrent dispatch via ThreadPoolExecutor.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        # Preserve original task order via index.
        results_by_idx: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
            future_to_idx = {
                pool.submit(fn, **kwargs): (i, pid)
                for i, (pid, fn, kwargs) in enumerate(tasks)
            }
            for fut in as_completed(future_to_idx):
                idx, pid = future_to_idx[fut]
                try:
                    r = fut.result()
                    results_by_idx[idx] = _result_to_record(pid, r)
                except Exception as exc:
                    results_by_idx[idx] = _crashed_record(pid, exc)
        for i in range(len(tasks)):
            providers_run.append(results_by_idx[i])
    else:
        # Original sequential path.
        bailed = False  # v1.28.s181
        for pid, fn, kwargs in tasks:
            try:
                r = fn(**kwargs)
                rec = _result_to_record(pid, r)
            except Exception as exc:
                rec = _crashed_record(pid, exc)
            providers_run.append(rec)
            # v1.28.s181 — bail out on first failure (sequential only).
            if bail_on_error and not rec.get("ok", False):
                bailed = True
                break

    total_matched = sum(p["matched"] for p in providers_run)
    total_downloaded = sum(p["downloaded"] for p in providers_run)
    providers_ok = sum(1 for p in providers_run if p["ok"])
    providers_failed = sum(1 for p in providers_run if not p["ok"])

    summary = {
        "query": query,
        "count_per_provider": count,
        "dry_run": dry_run,
        "parallel": parallel,
        "bail_on_error": bail_on_error,
        "bailed": locals().get("bailed", False),
        "providers_run": len(providers_run),
        "providers_ok": providers_ok,
        "providers_failed": providers_failed,
        "total_matched": total_matched,
        "total_downloaded": total_downloaded,
        "providers": providers_run,
    }

    # v1.15.s108 — append to history directory.
    if write_history:
        import datetime
        utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        # Repo state dir; relative to CWD (where assetboy is invoked from).
        history_dir = Path("state") / "r1a_history"
        history_dir.mkdir(parents=True, exist_ok=True)
        fname = f"all_no_key_{utc.strftime('%Y%m%dT%H%M%SZ')}.json"
        history_path = history_dir / fname
        history_record = {
            **summary,
            "kind": "all_no_key",
            "utc": utc.isoformat() + "Z",
            # v1.16.s115 enrichment
            "wall_time_s": round(_time.perf_counter() - _wall_start, 3),
            "command_shape": (
                f"gen all-no-key --query {query!r} --count {count} "
                + ("--parallel " if parallel else "")
                + ("--dry-run " if dry_run else "--no-dry-run ")
                + "--write-history"
            ),
        }
        history_path.write_text(
            json.dumps(history_record, indent=2), encoding="utf-8"
        )
        summary["history_path"] = str(history_path)

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_all_no_key_query={query!r}")
        print(f"gen_all_no_key_dry_run={dry_run}")
        print(f"gen_all_no_key_parallel={parallel}")
        if write_history:
            print(f"gen_all_no_key_history_path={summary['history_path']}")
        print(f"gen_all_no_key_providers_ok={providers_ok}/{len(providers_run)}")
        print(f"gen_all_no_key_total_matched={total_matched}")
        print(f"gen_all_no_key_total_downloaded={total_downloaded}")
        for p in providers_run:
            status = "OK " if p["ok"] else "RED"
            note = f" ({p['error']})" if p["error"] else ""
            print(f"  [{status}] {p['provider']:15s} matched={p['matched']:3d} "
                  f"downloaded={p['downloaded']:3d}{note}")


# --------------------------------------------------------------------------- #
# gen all-key  (v1.11.s38)
# --------------------------------------------------------------------------- #

@app.command("all-key")
def all_key_cmd(
    query: Annotated[
        str, typer.Option("--query", "-q", help="Search query (fans out across key-required providers)."),
    ],
    count: Annotated[
        int, typer.Option("--count", "-n", help="Per-provider count."),
    ] = 3,
    pack_id: Annotated[str, typer.Option("--pack-id")] = "",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path(""),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Plan only; recommended for scouting."),
    ] = True,
    include_video: Annotated[
        bool,
        typer.Option("--include-video", help="Also fan out to Pexels+Pixabay video providers."),
    ] = False,
    parallel: Annotated[
        bool,
        typer.Option(
            "--parallel",
            help="v1.12.s65: dispatch keyed runners concurrently (ThreadPoolExecutor).",
        ),
    ] = False,
    write_history: Annotated[
        bool,
        typer.Option(
            "--write-history",
            help="v1.17.s120: append run to state/r1a_history/<utc>.json (kind=all_key).",
        ),
    ] = False,
    provider_filter: Annotated[
        str,
        typer.Option(
            "--provider",
            help=(
                "v1.22.s155: comma-separated subset of keyed provider ids"
                " (pexels_photos/pexels_videos/pixabay_photos/pixabay_videos/"
                "unsplash/rawg/jamendo). If unset, all are dispatched."
            ),
        ),
    ] = "",
    bail_on_error: Annotated[
        bool,
        typer.Option(
            "--bail-on-error",
            help=(
                "v1.28.s182: stop on first provider that fails (sequential"
                " only; no effect with --parallel). Mirrors all-no-key flag."
            ),
        ),
    ] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fan out one query across key-required R1A providers (Path B v1.11.s38).

    Probes env vars and SKIPS any provider whose key is missing.
    Use --parallel (v1.12.s65) for concurrent dispatch.

    Providers (gated on env var presence):
      Pexels photos        PEXELS_API_KEY
      Pexels videos        PEXELS_API_KEY   (if --include-video)
      Pixabay photos       PIXABAY_API_KEY
      Pixabay videos       PIXABAY_API_KEY  (if --include-video)
      Unsplash photos      UNSPLASH_ACCESS_KEY
      RAWG games           RAWG_API_KEY
      Jamendo tracks       JAMENDO_CLIENT_ID

    Examples:
      assetboy gen all-key -q "fire" -n 2 --include-video --dry-run
      assetboy gen all-key -q "ambient" -n 1 --parallel
    """
    from assetboy.execution.pexels_runner import (
        get_api_key as _pexels_key, run_pexels_photo_batch, run_pexels_video_batch,
    )
    from assetboy.execution.pixabay_runner import (
        get_api_key as _pixabay_key, run_pixabay_photo_batch, run_pixabay_video_batch,
    )
    from assetboy.execution.unsplash_runner import (
        get_access_key as _unsplash_key, run_unsplash_photo_batch,
    )
    from assetboy.execution.rawg_runner import (
        get_api_key as _rawg_key, run_rawg_games_batch,
    )
    from assetboy.execution.jamendo_runner import (
        get_client_id as _jamendo_key, run_jamendo_tracks_batch,
    )

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    base_pack_id = pack_id or f"ALL_KEY_{query.replace(' ', '_').upper()}"

    def _get_count(r, *attrs: str) -> int:
        for a in attrs:
            v = getattr(r, a, 0)
            if v:
                return int(v)
        return 0

    def _ok_record(provider: str, r) -> dict:
        return {
            "provider": provider, "ok": r.ok, "skipped": False,
            "matched": _get_count(r, "items_matched", "games_matched",
                                  "tracks_matched", "photos_matched"),
            "downloaded": _get_count(r, "items_downloaded", "games_downloaded",
                                     "tracks_downloaded", "photos_downloaded"),
            "manifest_path": str(r.manifest_path) if getattr(r, "manifest_path", None) else None,
            "error": r.error,
            "output_dir": str(r.output_dir),
        }

    def _skipped_record(provider: str) -> dict:
        return {
            "provider": provider, "ok": False, "skipped": True,
            "matched": 0, "downloaded": 0,
            "manifest_path": None, "error": "missing_env_key",
            "output_dir": "",
        }

    def _crashed_record(provider: str, exc: Exception) -> dict:
        return {
            "provider": provider, "ok": False, "skipped": False,
            "matched": 0, "downloaded": 0,
            "manifest_path": None, "error": f"crashed: {exc}",
            "output_dir": "",
        }

    # v1.17.s120 — wall-time bracket for history snapshot.
    import time as _time
    _wall_start = _time.perf_counter()

    # Build dispatch tasks. Each entry: (pid, key_getter, runner, kwargs).
    tasks: list[tuple[str, object, object, dict]] = [
        ("pexels_photos", _pexels_key, run_pexels_photo_batch, dict(
            query=query, pack_id=f"{base_pack_id}_PXP", count=count,
            output_dir=(out_dir_arg / "pexels_photos") if out_dir_arg else None,
            dry_run=dry_run,
        )),
    ]
    if include_video:
        tasks.append(("pexels_videos", _pexels_key, run_pexels_video_batch, dict(
            query=query, pack_id=f"{base_pack_id}_PXV", count=count,
            output_dir=(out_dir_arg / "pexels_videos") if out_dir_arg else None,
            dry_run=dry_run,
        )))
    tasks.append(("pixabay_photos", _pixabay_key, run_pixabay_photo_batch, dict(
        query=query, pack_id=f"{base_pack_id}_PBP", count=count,
        output_dir=(out_dir_arg / "pixabay_photos") if out_dir_arg else None,
        dry_run=dry_run,
    )))
    if include_video:
        tasks.append(("pixabay_videos", _pixabay_key, run_pixabay_video_batch, dict(
            query=query, pack_id=f"{base_pack_id}_PBV", count=count,
            output_dir=(out_dir_arg / "pixabay_videos") if out_dir_arg else None,
            dry_run=dry_run,
        )))
    tasks.append(("unsplash", _unsplash_key, run_unsplash_photo_batch, dict(
        query=query, pack_id=f"{base_pack_id}_US", count=count,
        output_dir=(out_dir_arg / "unsplash") if out_dir_arg else None,
        dry_run=dry_run,
    )))
    tasks.append(("rawg", _rawg_key, run_rawg_games_batch, dict(
        query=query, pack_id=f"{base_pack_id}_RAWG", count=count,
        output_dir=(out_dir_arg / "rawg") if out_dir_arg else None,
        dry_run=dry_run,
    )))
    tasks.append(("jamendo", _jamendo_key, run_jamendo_tracks_batch, dict(
        query=query, pack_id=f"{base_pack_id}_JAM", count=count,
        output_dir=(out_dir_arg / "jamendo") if out_dir_arg else None,
        dry_run=dry_run,
    )))

    # v1.22.s155 — filter tasks by --provider.
    if provider_filter.strip():
        wanted = {p.strip().lower() for p in provider_filter.split(",") if p.strip()}
        tasks = [t for t in tasks if t[0].lower() in wanted]
        if not tasks:
            msg = (
                f"no_providers_matched_filter: {sorted(wanted)} "
                "(valid: pexels_photos/pexels_videos/pixabay_photos/"
                "pixabay_videos/unsplash/rawg/jamendo)"
            )
            if json_out:
                json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"gen_all_key_error={msg}")
            raise typer.Exit(code=1)

    providers_run: list[dict] = []

    if parallel:
        # v1.12.s65 — parallel dispatch for tasks with non-missing keys.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        # First: classify each task by env-key presence; skipped tasks are
        # pre-recorded (no futures needed for them).
        results_by_idx: dict[int, dict] = {}
        futures: dict = {}
        with ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
            for i, (pid, key_getter, fn, kwargs) in enumerate(tasks):
                key = key_getter()
                if not key:
                    results_by_idx[i] = _skipped_record(pid)
                    continue
                fut = pool.submit(fn, **kwargs)
                futures[fut] = (i, pid)
            for fut in as_completed(futures):
                idx, pid = futures[fut]
                try:
                    r = fut.result()
                    results_by_idx[idx] = _ok_record(pid, r)
                except Exception as exc:
                    results_by_idx[idx] = _crashed_record(pid, exc)
        for i in range(len(tasks)):
            providers_run.append(results_by_idx[i])
    else:
        bailed = False  # v1.28.s182
        for pid, key_getter, fn, kwargs in tasks:
            key = key_getter()
            if not key:
                providers_run.append(_skipped_record(pid))
                continue
            try:
                r = fn(**kwargs)
                rec = _ok_record(pid, r)
            except Exception as exc:
                rec = _crashed_record(pid, exc)
            providers_run.append(rec)
            # v1.28.s182 — bail on first failure (sequential only).
            if bail_on_error and not rec.get("ok", False) and not rec.get("skipped", False):
                bailed = True
                break

    providers_ok = sum(1 for p in providers_run if p["ok"])
    providers_skipped = sum(1 for p in providers_run if p["skipped"])
    providers_failed = sum(1 for p in providers_run if not p["ok"] and not p["skipped"])
    total_matched = sum(p["matched"] for p in providers_run)
    total_downloaded = sum(p["downloaded"] for p in providers_run)

    summary = {
        "query": query,
        "count_per_provider": count,
        "dry_run": dry_run,
        "bail_on_error": bail_on_error,
        "bailed": locals().get("bailed", False),
        "include_video": include_video,
        "parallel": parallel,
        "providers_run": len(providers_run),
        "providers_ok": providers_ok,
        "providers_skipped": providers_skipped,
        "providers_failed": providers_failed,
        "total_matched": total_matched,
        "total_downloaded": total_downloaded,
        "providers": providers_run,
    }

    # v1.17.s120 — history snapshot (mirrors v1.15.s108 for all-no-key).
    if write_history:
        import datetime
        utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        history_dir = Path("state") / "r1a_history"
        history_dir.mkdir(parents=True, exist_ok=True)
        fname = f"all_key_{utc.strftime('%Y%m%dT%H%M%SZ')}.json"
        history_path = history_dir / fname
        history_record = {
            **summary,
            "kind": "all_key",
            "utc": utc.isoformat() + "Z",
            "wall_time_s": round(_time.perf_counter() - _wall_start, 3),
            "command_shape": (
                f"gen all-key --query {query!r} --count {count} "
                + ("--include-video " if include_video else "")
                + ("--parallel " if parallel else "")
                + ("--dry-run " if dry_run else "--no-dry-run ")
                + "--write-history"
            ),
        }
        history_path.write_text(
            json.dumps(history_record, indent=2), encoding="utf-8"
        )
        summary["history_path"] = str(history_path)

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_all_key_query={query!r}")
        print(f"gen_all_key_dry_run={dry_run}")
        print(f"gen_all_key_include_video={include_video}")
        print(f"gen_all_key_parallel={parallel}")
        if write_history:
            print(f"gen_all_key_history_path={summary['history_path']}")
        print(f"gen_all_key_providers_ok={providers_ok}/{len(providers_run)}")
        print(f"gen_all_key_providers_skipped={providers_skipped}")
        print(f"gen_all_key_providers_failed={providers_failed}")
        print(f"gen_all_key_total_matched={total_matched}")
        print(f"gen_all_key_total_downloaded={total_downloaded}")
        for p in providers_run:
            if p["skipped"]:
                status = "SKP"
            elif p["ok"]:
                status = "OK "
            else:
                status = "RED"
            note = f" ({p['error']})" if p["error"] else ""
            print(f"  [{status}] {p['provider']:15s} matched={p['matched']:3d} "
                  f"downloaded={p['downloaded']:3d}{note}")


# --------------------------------------------------------------------------- #
# gen list-providers  (v1.11.s45)
# --------------------------------------------------------------------------- #

@app.command("list-providers")
def list_providers_cmd(
    filter_: Annotated[
        list[str],
        typer.Option(
            "--filter",
            help=(
                "v1.12.s71: filter providers by attribute. Supported:"
                " 'env_set:true', 'env_set:false', 'env_var:none' (no-key only),"
                " 'env_var:<NAME>' (specific env var). Repeatable; ANDed."
            ),
        ),
    ] = None,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON output."),
    ] = False,
) -> None:
    """Catalog all R1A-and-friends providers reachable from gen sub-app (Path B v1.11.s45).

    Shows each provider's:
      - cli command
      - auth requirement (env var or 'none')
      - env-var detection (set or not)
      - license summary
      - asset class

    v1.12.s71: --filter env_set:true to see only ready-to-use providers.
    """
    import os

    # Catalog: declarative table. ENV_VAR=None means no key required.
    providers = [
        {
            "id": "met-museum",
            "cli": "gen met-museum fetch",
            "env_var": None,
            "license": "CC0",
            "asset_class": "image:photograph",
            "what": "Met Museum Open Access (~500K artworks)",
        },
        {
            "id": "wikimedia",
            "cli": "gen wikimedia fetch",
            "env_var": None,
            "license": "CC0 | CC-BY | CC-BY-SA | PD",
            "asset_class": "image:any",
            "what": "Wikimedia Commons (~100M files)",
        },
        {
            "id": "archive-org",
            "cli": "gen archive-org fetch",
            "env_var": None,
            "license": "CC-BY/SA | CC0 | PD",
            "asset_class": "image|audio|video|texts",
            "what": "Internet Archive (~50M items)",
        },
        {
            "id": "scryfall",
            "cli": "gen scryfall fetch",
            "env_var": None,
            "license": "CC-BY-SA-4.0",
            "asset_class": "image:fantasy_art",
            "what": "Scryfall MTG cards (~25K unique arts)",
        },
        {
            "id": "iconify",
            "cli": "gen iconify fetch",
            "env_var": None,
            "license": "MIT | Apache-2.0 | CC0 | CC-BY | OFL | etc",
            "asset_class": "image:icon_svg",
            "what": "Iconify (150+ open-source icon sets)",
        },
        {
            "id": "pexels",
            "cli": "gen pexels photos|videos",
            "env_var": "PEXELS_API_KEY",
            "license": "Pexels License (free personal+commercial)",
            "asset_class": "image:photo + VIDEO",
            "what": "Pexels stock photos + videos",
        },
        {
            "id": "pixabay",
            "cli": "gen pixabay photos|videos",
            "env_var": "PIXABAY_API_KEY",
            "license": "CC0-equivalent (Pixabay Content License)",
            "asset_class": "image:any + VIDEO",
            "what": "Pixabay photos+illustrations+vectors+videos",
        },
        {
            "id": "unsplash",
            "cli": "gen unsplash photos",
            "env_var": "UNSPLASH_ACCESS_KEY",
            "license": "Unsplash License (free personal+commercial)",
            "asset_class": "image:photo",
            "what": "Unsplash high-quality photography",
        },
        {
            "id": "rawg",
            "cli": "gen rawg games",
            "env_var": "RAWG_API_KEY",
            "license": "REFERENCE-ONLY (publisher copyright)",
            "asset_class": "image:game_screenshot",
            "what": "RAWG.io game DB (covers + screenshots; reference only)",
        },
        {
            "id": "jamendo",
            "cli": "gen jamendo tracks",
            "env_var": "JAMENDO_CLIENT_ID",
            "license": "CC-BY | CC-BY-SA (commercial-OK)",
            "asset_class": "audio:music_track",
            "what": "Jamendo CC music tracks (~500K)",
        },
        {
            "id": "inaturalist",
            "cli": "gen inaturalist fetch",
            "env_var": None,
            "license": "CC0 | CC-BY | CC-BY-SA (commercial-OK)",
            "asset_class": "image:nature_reference",
            "what": "iNaturalist nature observation photos (~200M+ records)",
        },
        {
            "id": "comfyui",
            "cli": "gen comfyui run|submit-workflow",
            "env_var": None,
            "license": "user-generated (depends on prompts)",
            "asset_class": "image:generated",
            "what": "ComfyUI workflow runner (local :8188)",
        },
        {
            "id": "sd",
            "cli": "gen sd run",
            "env_var": None,
            "license": "user-generated",
            "asset_class": "image:generated",
            "what": "stable-diffusion.cpp CUDA wrapper",
        },
    ]

    # Annotate env_var with current detection state.
    for p in providers:
        ev = p["env_var"]
        if ev is None:
            p["env_set"] = None  # N/A
        else:
            p["env_set"] = bool(os.environ.get(ev, "").strip())

    # v1.12.s71 — apply --filter (env_set / env_var).
    parsed_filters: list[tuple[str, str]] = []
    for f in (filter_ or []):
        if ":" not in f:
            msg = f"bad_filter_shape: {f!r} (expected 'field:value')"
            if json_out:
                json.dump({"error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"gen_list_providers_error={msg}")
            raise typer.Exit(code=1)
        fname, _, fval = f.partition(":")
        parsed_filters.append((fname.strip(), fval.strip()))

    def _matches_filter(provider: dict, field_name: str, value: str) -> bool:
        if field_name == "env_set":
            wanted = value.lower() in ("true", "yes", "1")
            # Providers with env_var=None have env_set=None; treat as "no key, irrelevant".
            return bool(provider.get("env_set")) is wanted
        if field_name == "env_var":
            ev = provider.get("env_var")
            if value.lower() == "none":
                return ev is None
            return ev == value or (ev is not None and ev.lower() == value.lower())
        if field_name == "kind":
            # v1.25.s170 — substring match on asset_class (case-insensitive).
            # Supports 'image', 'audio', 'video', 'icon', 'generated', 'photo',
            # 'fantasy', 'nature', etc.
            ac = str(provider.get("asset_class", "")).lower()
            return value.strip().lower() in ac
        return False  # unknown field -> never matches

    if parsed_filters:
        providers = [
            p for p in providers
            if all(_matches_filter(p, fn, fv) for fn, fv in parsed_filters)
        ]

    no_key_count = sum(1 for p in providers if p["env_var"] is None)
    key_required = [p for p in providers if p["env_var"] is not None]
    key_set = sum(1 for p in key_required if p["env_set"])
    key_unset = len(key_required) - key_set

    summary = {
        "providers": providers,
        "total": len(providers),
        "no_key_count": no_key_count,
        "key_required_count": len(key_required),
        "key_set_count": key_set,
        "key_unset_count": key_unset,
        "filters_applied": [f"{fn}:{fv}" for fn, fv in parsed_filters],
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    print(f"gen_list_providers_total={len(providers)}")
    print(f"gen_list_providers_no_key={no_key_count}")
    print(f"gen_list_providers_key_set={key_set}/{len(key_required)} "
          f"(unset: {key_unset})")
    print()
    print("Provider                CLI                              Env var                Set  License/Asset class")
    print("=" * 130)
    for p in providers:
        if p["env_var"] is None:
            envset = " - "
            envv = "(no key)"
        else:
            envset = "YES" if p["env_set"] else "no "
            envv = p["env_var"]
        print(
            f"{p['id']:23s} {p['cli']:32s} {envv:22s} {envset}  "
            f"{p['license']:38s} {p['asset_class']}"
        )


# --------------------------------------------------------------------------- #
# gen bench-fanout  (v1.12.s70)
# --------------------------------------------------------------------------- #

@app.command("bench-fanout")
def bench_fanout_cmd(
    query: Annotated[
        str, typer.Option("--query", "-q", help="Search query for the benchmark."),
    ],
    count: Annotated[
        int, typer.Option("--count", "-n", help="Per-provider count."),
    ] = 1,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Benchmark sequential vs parallel fan-out for the 6 no-key R1A providers.

    Runs `gen all-no-key` TWICE (sequential then parallel) with the SAME
    query + count, both in --dry-run mode (no downloads). Reports
    per-mode wall time and the speedup factor.

    v1.13.s87: includes iNaturalist (6 providers now, was 5).

    Examples:
      assetboy gen bench-fanout -q "stone wall" -n 1
    """
    import time
    from assetboy.execution.met_museum_runner import run_met_museum_batch
    from assetboy.execution.wikimedia_runner import run_wikimedia_batch
    from assetboy.execution.archive_org_runner import run_archive_org_batch
    from assetboy.execution.scryfall_runner import run_scryfall_batch
    from assetboy.execution.iconify_runner import run_iconify_batch
    from assetboy.execution.inaturalist_runner import run_inaturalist_batch
    from concurrent.futures import ThreadPoolExecutor

    tasks = [
        ("met_museum", run_met_museum_batch, dict(
            query=query, pack_id="BENCH_MET", count=count, dry_run=True,
        )),
        ("wikimedia", run_wikimedia_batch, dict(
            query=query, pack_id="BENCH_WM", count=count, dry_run=True,
        )),
        ("archive_org", run_archive_org_batch, dict(
            query=query, mediatype="image", pack_id="BENCH_AO", count=count, dry_run=True,
        )),
        ("scryfall", run_scryfall_batch, dict(
            query=query, pack_id="BENCH_SF", count=count, dry_run=True,
        )),
        ("iconify", run_iconify_batch, dict(
            query=query, pack_id="BENCH_IC", count=count, dry_run=True,
        )),
        ("inaturalist", run_inaturalist_batch, dict(
            query=query, pack_id="BENCH_INAT", count=count, dry_run=True,
        )),
    ]

    # Sequential run.
    seq_t0 = time.perf_counter()
    seq_per_provider: dict[str, float] = {}
    for pid, fn, kwargs in tasks:
        t = time.perf_counter()
        try:
            fn(**kwargs)
        except Exception:
            pass
        seq_per_provider[pid] = time.perf_counter() - t
    seq_total = time.perf_counter() - seq_t0

    # Parallel run.
    par_t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = [pool.submit(fn, **kwargs) for _, fn, kwargs in tasks]
        for f in futures:
            try:
                f.result()
            except Exception:
                pass
    par_total = time.perf_counter() - par_t0

    speedup = seq_total / par_total if par_total > 0 else 0.0

    summary = {
        "query": query,
        "count_per_provider": count,
        "providers": [pid for pid, _, _ in tasks],
        "sequential_total_s": round(seq_total, 3),
        "parallel_total_s": round(par_total, 3),
        "speedup_x": round(speedup, 2),
        "sequential_per_provider_s": {
            pid: round(t, 3) for pid, t in seq_per_provider.items()
        },
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_bench_fanout_query={query!r}")
        print(f"gen_bench_fanout_count={count}")
        print(f"gen_bench_fanout_providers={len(tasks)}")
        print(f"gen_bench_fanout_sequential_total_s={seq_total:.3f}")
        print(f"gen_bench_fanout_parallel_total_s={par_total:.3f}")
        print(f"gen_bench_fanout_speedup_x={speedup:.2f}")
        print()
        print("Per-provider sequential timing:")
        for pid, t in seq_per_provider.items():
            print(f"  {pid:14s} {t:.3f}s")


# --------------------------------------------------------------------------- #
# gen inaturalist fetch  (v1.13.s84)
# --------------------------------------------------------------------------- #

@inaturalist_app.command("fetch")
def inaturalist_fetch_cmd(
    query: Annotated[str, typer.Option("--query", "-q")],
    count: Annotated[int, typer.Option("--count", "-n")] = 6,
    allow_restrictive: Annotated[
        bool,
        typer.Option(
            "--allow-restrictive",
            help="Also accept CC-NC variants (default: only CC0/CC-BY/CC-BY-SA).",
        ),
    ] = False,
    pack_id: Annotated[str, typer.Option("--pack-id")] = "",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path(""),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fetch CC-licensed nature photos from iNaturalist (Path B v1.13.s84).

    iNaturalist citizen-science platform; ~200M+ observations of plants,
    animals, fungi, etc. No API key. Default license gate: CC0/CC-BY/CC-BY-SA
    (commercial-OK). Use --allow-restrictive for CC-NC variants (personal only).

    Attribution: CC-BY/SA photos REQUIRE crediting; per-photo 'attribution'
    string captured in manifest.

    Examples:
      assetboy gen inaturalist fetch -q "oak tree" -n 4
      assetboy gen inaturalist fetch -q "wolf" -n 6
      assetboy gen inaturalist fetch -q "mycelium" --allow-restrictive -n 8
    """
    from assetboy.execution.inaturalist_runner import run_inaturalist_batch

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None

    try:
        result = run_inaturalist_batch(
            query=query, pack_id=pack_id_arg, count=count,
            allow_restrictive=allow_restrictive,
            output_dir=out_dir_arg, dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"inaturalist_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_inaturalist_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok,
        "pack_id": result.pack_id,
        "query": result.query,
        "output_dir": str(result.output_dir),
        "observations_matched": result.observations_matched,
        "observations_with_photo": result.observations_with_photo,
        "photos_downloaded": result.photos_downloaded,
        "photos_skipped_restricted": result.photos_skipped_restricted,
        "photos_failed": result.photos_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_inaturalist_pack_id={result.pack_id}")
        print(f"gen_inaturalist_query={result.query!r}")
        print(f"gen_inaturalist_matched={result.observations_matched}")
        print(f"gen_inaturalist_downloaded={result.photos_downloaded}")
        print(f"gen_inaturalist_skipped_restricted={result.photos_skipped_restricted}")
        print(f"gen_inaturalist_failed={result.photos_failed}")
        print(f"gen_inaturalist_output_dir={result.output_dir}")
        if result.manifest_path:
            print(f"gen_inaturalist_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_inaturalist_note={result.error}")

    if not result.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# gen openlibrary fetch  (v1.13.s91)
# --------------------------------------------------------------------------- #

@openlibrary_app.command("fetch")
def openlibrary_fetch_cmd(
    query: Annotated[str, typer.Option("--query", "-q")] = "",
    author: Annotated[
        str,
        typer.Option(
            "--author",
            help="v1.18.s128: filter by author name (uses native author= param).",
        ),
    ] = "",
    count: Annotated[int, typer.Option("--count", "-n")] = 6,
    size: Annotated[
        str,
        typer.Option("--size", help="S | M | L (default L, ~500px)."),
    ] = "L",
    pack_id: Annotated[str, typer.Option("--pack-id")] = "",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path(""),
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fetch book cover images from Open Library (Path B v1.13.s91).

    REFERENCE-ONLY. Cover images are user-uploaded thumbnails; treat as
    mood-board / img2img-seed material. NOT for redistribution in shipped games.

    No API key. Examples:
      assetboy gen openlibrary fetch -q "alchemy" -n 6
      assetboy gen openlibrary fetch --author "ursula k le guin" -n 10
      assetboy gen openlibrary fetch -q "subject:dragons" --size M -n 10
    """
    from assetboy.execution.openlibrary_runner import run_openlibrary_batch

    if not query.strip() and not author.strip():
        msg = "missing_query_or_author"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_openlibrary_error={msg}")
        raise typer.Exit(code=1)

    out_dir_arg: Path | None = output_dir if str(output_dir) else None
    pack_id_arg: str | None = pack_id if pack_id else None
    author_arg: str | None = author.strip() or None

    try:
        result = run_openlibrary_batch(
            query=query, pack_id=pack_id_arg, count=count, size=size,
            author=author_arg,
            output_dir=out_dir_arg, dry_run=dry_run,
        )
    except Exception as exc:
        msg = f"openlibrary_runner_crashed: {exc}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_openlibrary_error={msg}")
        raise typer.Exit(code=1)

    summary = {
        "ok": result.ok,
        "pack_id": result.pack_id,
        "query": result.query,
        "output_dir": str(result.output_dir),
        "docs_matched": result.docs_matched,
        "covers_with_id": result.covers_with_id,
        "covers_downloaded": result.covers_downloaded,
        "covers_failed": result.covers_failed,
        "downloaded_paths": [str(p) for p in result.downloaded_paths],
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "dry_run": result.dry_run,
        "error": result.error,
    }
    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_openlibrary_pack_id={result.pack_id}")
        print(f"gen_openlibrary_query={result.query!r}")
        print(f"gen_openlibrary_matched={result.docs_matched}")
        print(f"gen_openlibrary_downloaded={result.covers_downloaded}")
        print(f"gen_openlibrary_failed={result.covers_failed}")
        print(f"gen_openlibrary_output_dir={result.output_dir}")
        print("gen_openlibrary_USE_POLICY=reference-only_not_for_redistribution")
        if result.manifest_path:
            print(f"gen_openlibrary_manifest={result.manifest_path}")
        if result.error:
            print(f"gen_openlibrary_note={result.error}")
    if not result.ok:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# gen scout-by-license  (v1.13.s94)
# --------------------------------------------------------------------------- #

@app.command("scout-by-license")
def scout_by_license_cmd(
    license_token: Annotated[
        str,
        typer.Option(
            "--license",
            help=(
                "Substring (case-insensitive) matched against each provider's"
                " license string. Examples: 'cc0', 'cc-by', 'mit', 'pexels'."
            ),
        ),
    ],
    query: Annotated[
        str, typer.Option("--query", "-q", help="Search query."),
    ],
    count: Annotated[
        int, typer.Option("--count", "-n", help="Per-provider count."),
    ] = 2,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = True,
    parallel: Annotated[
        bool,
        typer.Option(
            "--parallel",
            help="v1.17.s122: dispatch license-filtered providers concurrently.",
        ),
    ] = False,
    max_providers: Annotated[
        int,
        typer.Option(
            "--max-providers",
            help=(
                "v1.32.s196: cap how many license-matched providers to"
                " actually fan out to (0 = unlimited, default). When >0"
                " and matched > N, only the first N (in catalog order)"
                " run; the rest appear in 'deferred' in the summary."
            ),
        ),
    ] = 0,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Scout across providers filtered by license token (Path B v1.13.s94).

    Picks every gen-catalog provider whose license string contains the given
    token, then fans out the query across them. Useful when shipping art
    needs strictly e.g. CC0:

      assetboy gen scout-by-license --license cc0 --query "stone wall"
        -> hits Met Museum + Pixabay (CC0-equivalent) + iNaturalist + ...

      assetboy gen scout-by-license --license mit --query "sword"
        -> hits Iconify only

    Skips providers whose env key is unset (clean per-provider note).
    """
    import os

    token = license_token.strip().lower()
    if not token:
        msg = "empty_license_token"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_scout_by_license_error={msg}")
        raise typer.Exit(code=1)

    # Provider catalog (mirror of list-providers but with runner refs).
    from assetboy.execution.met_museum_runner import run_met_museum_batch
    from assetboy.execution.wikimedia_runner import run_wikimedia_batch
    from assetboy.execution.archive_org_runner import run_archive_org_batch
    from assetboy.execution.scryfall_runner import run_scryfall_batch
    from assetboy.execution.iconify_runner import run_iconify_batch
    from assetboy.execution.inaturalist_runner import run_inaturalist_batch
    from assetboy.execution.pexels_runner import run_pexels_photo_batch, get_api_key as _pexels_key
    from assetboy.execution.pixabay_runner import run_pixabay_photo_batch, get_api_key as _pixabay_key
    from assetboy.execution.unsplash_runner import run_unsplash_photo_batch, get_access_key as _unsplash_key

    catalog = [
        ("met-museum", "CC0", None, run_met_museum_batch, dict(query=query, count=count, dry_run=dry_run)),
        ("wikimedia", "CC0 | CC-BY | CC-BY-SA | PD", None, run_wikimedia_batch, dict(query=query, count=count, dry_run=dry_run)),
        ("archive-org", "CC-BY | CC-BY-SA | CC0 | PD", None, run_archive_org_batch, dict(query=query, mediatype="image", count=count, dry_run=dry_run)),
        ("scryfall", "CC-BY-SA-4.0", None, run_scryfall_batch, dict(query=query, count=count, dry_run=dry_run)),
        ("iconify", "MIT | Apache-2.0 | CC0 | CC-BY | OFL", None, run_iconify_batch, dict(query=query, count=count, dry_run=dry_run)),
        ("inaturalist", "CC0 | CC-BY | CC-BY-SA", None, run_inaturalist_batch, dict(query=query, count=count, dry_run=dry_run)),
        ("pexels", "Pexels License (free personal+commercial)", "PEXELS_API_KEY", run_pexels_photo_batch, dict(query=query, count=count, dry_run=dry_run)),
        ("pixabay", "Pixabay Content License (CC0-equivalent)", "PIXABAY_API_KEY", run_pixabay_photo_batch, dict(query=query, count=count, dry_run=dry_run)),
        ("unsplash", "Unsplash License", "UNSPLASH_ACCESS_KEY", run_unsplash_photo_batch, dict(query=query, count=count, dry_run=dry_run)),
    ]

    # Filter by license token.
    matched = [t for t in catalog if token in t[1].lower()]

    # v1.32.s196 — apply --max-providers cap (catalog order preserved).
    deferred_ids: list[str] = []
    if max_providers > 0 and len(matched) > max_providers:
        deferred_ids = [t[0] for t in matched[max_providers:]]
        matched = matched[:max_providers]

    def _run_one(pid: str, lic: str, env_var, fn, kwargs) -> dict:
        if env_var and not os.environ.get(env_var, "").strip():
            return {
                "provider": pid, "license": lic, "ok": False,
                "skipped": True, "matched": 0, "downloaded": 0,
                "error": f"missing_env_key:{env_var}",
            }
        call_kwargs = dict(kwargs)
        if pid == "pexels":
            call_kwargs["api_key"] = _pexels_key()
        elif pid == "pixabay":
            call_kwargs["api_key"] = _pixabay_key()
        elif pid == "unsplash":
            call_kwargs["access_key"] = _unsplash_key()
        try:
            r = fn(**call_kwargs)
            return {
                "provider": pid, "license": lic, "ok": r.ok, "skipped": False,
                "matched": getattr(r, "items_matched", 0)
                           or getattr(r, "objects_matched", 0)
                           or getattr(r, "files_matched", 0)
                           or getattr(r, "cards_matched", 0)
                           or getattr(r, "icons_matched", 0)
                           or getattr(r, "observations_matched", 0)
                           or getattr(r, "photos_matched", 0),
                "downloaded": getattr(r, "items_downloaded", 0)
                              or getattr(r, "objects_downloaded", 0)
                              or getattr(r, "files_downloaded", 0)
                              or getattr(r, "cards_downloaded", 0)
                              or getattr(r, "icons_downloaded", 0)
                              or getattr(r, "photos_downloaded", 0),
                "error": r.error,
            }
        except Exception as exc:
            return {
                "provider": pid, "license": lic, "ok": False,
                "skipped": False, "matched": 0, "downloaded": 0,
                "error": f"crashed: {exc}",
            }

    results: list[dict] = []
    if parallel and matched:
        # v1.17.s122 — concurrent dispatch.
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results_by_idx: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(matched))) as pool:
            futs = {
                pool.submit(_run_one, pid, lic, ev, fn, kw): i
                for i, (pid, lic, ev, fn, kw) in enumerate(matched)
            }
            for fut in as_completed(futs):
                results_by_idx[futs[fut]] = fut.result()
        for i in range(len(matched)):
            results.append(results_by_idx[i])
    else:
        for pid, lic, env_var, fn, kwargs in matched:
            results.append(_run_one(pid, lic, env_var, fn, kwargs))

    summary = {
        "license_token": token,
        "query": query,
        "count_per_provider": count,
        "dry_run": dry_run,
        "parallel": parallel,
        "providers_matched_by_license": len(matched) + len(deferred_ids),
        "max_providers": max_providers if max_providers > 0 else None,
        "deferred": deferred_ids,
        "providers_run": len(results),
        "providers_ok": sum(1 for r in results if r["ok"]),
        "providers_skipped": sum(1 for r in results if r["skipped"]),
        "providers_failed": sum(1 for r in results if not r["ok"] and not r["skipped"]),
        "total_matched": sum(r["matched"] for r in results),
        "total_downloaded": sum(r["downloaded"] for r in results),
        "providers": results,
    }

    if json_out:
        json.dump(summary, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_scout_by_license_token={token!r}")
        print(f"gen_scout_by_license_query={query!r}")
        print(f"gen_scout_by_license_providers_matched={len(matched)}")
        print(f"gen_scout_by_license_providers_ok={summary['providers_ok']}/{len(results)}")
        print(f"gen_scout_by_license_providers_skipped={summary['providers_skipped']}")
        print(f"gen_scout_by_license_total_matched={summary['total_matched']}")
        print(f"gen_scout_by_license_total_downloaded={summary['total_downloaded']}")
        for r in results:
            status = "SKP" if r["skipped"] else ("OK " if r["ok"] else "RED")
            note = f" ({r['error']})" if r["error"] else ""
            print(f"  [{status}] {r['provider']:13s} matched={r['matched']:3d} "
                  f"downloaded={r['downloaded']:3d}{note}")


# --------------------------------------------------------------------------- #
# gen history-tail  (v1.24.s162)
# --------------------------------------------------------------------------- #


@app.command("history-tail")
def history_tail_cmd(
    n: Annotated[
        int,
        typer.Option(
            "--last",
            help=(
                "v1.24.s162: number of most-recent r1a_history snapshots"
                " to aggregate (default 10). 0 = all available."
            ),
        ),
    ] = 10,
    kind_filter: Annotated[
        str,
        typer.Option(
            "--kind",
            help=(
                "Filter by run kind: 'all_no_key', 'all_key', or empty"
                " for both (default)."
            ),
        ),
    ] = "",
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Summarize the last N R1A fan-out runs from state/r1a_history.

    v1.24.s162: companion to --write-history flags on gen all-no-key
    and gen all-key. Reports per-provider rolling averages: matched
    count, downloaded count, ok-rate, and total runs seen.

    Useful for spotting provider regressions or rate-limit creep.
    """
    history_root = Path("state") / "r1a_history"
    if not history_root.exists():
        msg = f"history_root_not_found: {history_root}"
        if json_out:
            json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"gen_history_tail_error={msg}")
        raise typer.Exit(code=1)

    # Collect snapshot files sorted by mtime desc (newest first).
    snapshots = sorted(
        history_root.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    # Optional kind filter (operates on filename prefix).
    kind_norm = kind_filter.strip().lower()
    if kind_norm:
        if kind_norm not in ("all_no_key", "all_key"):
            msg = (
                f"unknown_kind: {kind_norm!r}"
                " (valid: 'all_no_key', 'all_key', or empty)"
            )
            if json_out:
                json.dump({"ok": False, "error": msg}, sys.stdout, indent=2)
                sys.stdout.write("\n")
            else:
                print(f"gen_history_tail_error={msg}")
            raise typer.Exit(code=1)
        snapshots = [
            s for s in snapshots if s.name.startswith(kind_norm)
        ]

    # Apply --last truncation (0 = all).
    if n > 0:
        snapshots = snapshots[:n]

    # Aggregate per-provider totals.
    per_provider: dict[str, dict] = {}
    runs_seen = 0
    for snap_path in snapshots:
        try:
            doc = json.loads(snap_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        runs_seen += 1
        for p in (doc.get("providers") or []):
            name = p.get("provider", "?")
            slot = per_provider.setdefault(name, {
                "runs": 0, "matched_sum": 0, "downloaded_sum": 0,
                "ok_count": 0, "skipped_count": 0,
            })
            slot["runs"] += 1
            slot["matched_sum"] += int(p.get("matched", 0) or 0)
            slot["downloaded_sum"] += int(p.get("downloaded", 0) or 0)
            if p.get("ok"):
                slot["ok_count"] += 1
            if p.get("skipped"):
                slot["skipped_count"] += 1

    # Compute derived stats (avg + ok_rate).
    summary: list[dict] = []
    for name, slot in sorted(per_provider.items()):
        runs = slot["runs"] or 1
        summary.append({
            "provider": name,
            "runs": slot["runs"],
            "avg_matched": round(slot["matched_sum"] / runs, 2),
            "avg_downloaded": round(slot["downloaded_sum"] / runs, 2),
            "ok_rate": round(slot["ok_count"] / runs, 3),
            "skipped_count": slot["skipped_count"],
        })

    payload = {
        "ok": True,
        "history_root": str(history_root),
        "runs_seen": runs_seen,
        "kind_filter": kind_norm or None,
        "last_n": n if n > 0 else None,
        "providers_seen": len(summary),
        "providers": summary,
    }

    if json_out:
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"gen_history_tail_history_root={history_root}")
        print(f"gen_history_tail_runs_seen={runs_seen}")
        print(f"gen_history_tail_providers_seen={len(summary)}")
        if kind_norm:
            print(f"gen_history_tail_kind={kind_norm}")
        for row in summary:
            print(
                f"  {row['provider']:18s} runs={row['runs']:3d}  "
                f"avg_matched={row['avg_matched']:6.2f}  "
                f"avg_downloaded={row['avg_downloaded']:6.2f}  "
                f"ok_rate={row['ok_rate']:.3f}  "
                f"skipped={row['skipped_count']}"
            )


if __name__ == "__main__":
    app()
