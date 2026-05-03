"""
colab_runner.py — Emits a Colab notebook and batch artifacts for manual execution.

This module reads the batch artifact emitted by `emit_generator_setup` and
prepares each job for the active colab_exec MCP server. The CLI path writes
the notebook and prompt batch, but does not itself execute the Colab runtime.

Usage (via CLI):
    python -m assetboy.cli run-hunyuan-batch --pack-id RA_PACK_WPN_COMBAT_SLICE_01
    python -m assetboy.cli run-colab-batch --batch-file path/to/prompt_batch.json
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from assetboy.execution.gdrive_mcp_merger import build_drive_stage_plan, drive_folder_for_colab
from assetboy.library.files import write_json, write_text
from assetboy.library.paths import generated_output_root


# ---------------------------------------------------------------------------
# Batch reading helpers
# ---------------------------------------------------------------------------

def load_prompt_batch(batch_path: str | Path) -> dict:
    path = Path(batch_path)
    if not path.exists():
        raise FileNotFoundError(f"Prompt batch not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _slug(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def _colab_notebook_for_profile(profile_id: str) -> str:
    """Return a Colab-ready Python cell block for a given profile."""
    if "hunyuan3d" in profile_id:
        return _hunyuan3d_colab_code()
    if "trellis" in profile_id:
        return _trellis_colab_code()
    if "animationgpt" in profile_id:
        return _animationgpt_colab_code()
    raise ValueError(f"No Colab template for profile: {profile_id}")


def _hunyuan3d_colab_code() -> str:
    return """\
# === AssetBoy: Hunyuan3D-2 Batch Runner ===
import subprocess, sys, json, shutil
from pathlib import Path

# Install
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "git+https://github.com/tencent/hunyuan3d-2",
    "torch", "diffusers", "Pillow"], check=True)

import torch
from hunyuan3d2 import Hunyuan3DPipeline
from PIL import Image

pipe = Hunyuan3DPipeline.from_pretrained("tencent/Hunyuan3D-2")
if torch.cuda.is_available():
    pipe = pipe.to("cuda")

import json, pathlib, os

batch = json.loads(pathlib.Path("/content/prompt_batch.json").read_text())
out_root = pathlib.Path("/content/outputs")
out_root.mkdir(exist_ok=True)

for job in batch["jobs"]:
    prompt = job["payload"]["prompt"]
    job_name = job["job_name"]
    print(f"Generating: {job_name} | {prompt}")
    result = pipe(prompt=prompt, num_inference_steps=30)
    mesh_path = out_root / f"{job_name}.glb"
    result.save(str(mesh_path))
    print(f"Saved: {mesh_path}")

print("=== DONE ===")
"""


def _trellis_colab_code() -> str:
    return """\
# === AssetBoy: TRELLIS Batch Runner ===
import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "git+https://github.com/microsoft/TRELLIS",
    "torch", "Pillow"], check=True)

import json, pathlib, torch
from PIL import Image
from trellis.pipelines import TrellisImageTo3DPipeline

pipe = TrellisImageTo3DPipeline.from_pretrained("microsoft/TRELLIS-image-large")
if torch.cuda.is_available():
    pipe.to("cuda")

batch = json.loads(pathlib.Path("/content/prompt_batch.json").read_text())
out_root = pathlib.Path("/content/outputs")
out_root.mkdir(exist_ok=True)

for job in batch["jobs"]:
    prompt = job["payload"]["prompt"]
    job_name = job["job_name"]
    print(f"Generating: {job_name} | {prompt}")
    # TRELLIS image-to-3D requires a reference image, use a blank or prompted one
    outputs = pipe(prompt, output_formats=["mesh"])
    mesh_path = out_root / f"{job_name}.glb"
    outputs["mesh"].save(str(mesh_path))
    print(f"Saved: {mesh_path}")

print("=== DONE ===")
"""


def _animationgpt_colab_code() -> str:
    return """\
# === AssetBoy: AnimationGPT Pilot Batch Runner ===
import subprocess, sys
subprocess.run([sys.executable, "-m", "pip", "install", "-q",
    "git+https://github.com/cuducos/animationgpt",
    "torch"], check=True)

import json, pathlib
batch = json.loads(pathlib.Path("/content/prompt_batch.json").read_text())
out_root = pathlib.Path("/content/outputs")
out_root.mkdir(exist_ok=True)

for job in batch["jobs"]:
    prompt = job["payload"]["prompt"]
    job_name = job["job_name"]
    clip_len = job["payload"].get("clip_length_sec", 1.5)
    print(f"Generating animation: {job_name} | {prompt} | {clip_len}s")
    # AnimationGPT integration placeholder — wire to active model API here
    out_path = out_root / f"{job_name}.bvh"
    out_path.write_text(f"# AnimationGPT output for: {prompt}")
    print(f"Saved: {out_path}")

print("=== DONE ===")
"""


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

class ColabSubmissionResult:
    """Result of submitting a batch to a Colab execution server."""

    def __init__(
        self,
        profile_id: str,
        pack_id: str,
        batch_path: Path,
        output_dir: Path,
        job_count: int,
        drive_folder: str,
        handoff_manifest_path: Path,
        drive_stage_plan_path: Path,
        dry_run: bool = False,
    ) -> None:
        self.profile_id = profile_id
        self.pack_id = pack_id
        self.batch_path = batch_path
        self.output_dir = output_dir
        self.job_count = job_count
        self.drive_folder = drive_folder
        self.handoff_manifest_path = handoff_manifest_path
        self.drive_stage_plan_path = drive_stage_plan_path
        self.dry_run = dry_run

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "pack_id": self.pack_id,
            "batch_path": str(self.batch_path),
            "output_dir": str(self.output_dir),
            "job_count": self.job_count,
            "drive_folder": self.drive_folder,
            "handoff_manifest_path": str(self.handoff_manifest_path),
            "drive_stage_plan_path": str(self.drive_stage_plan_path),
            "dry_run": self.dry_run,
        }


def _companion_paths(root_dir: Path) -> dict[str, Path]:
    candidates = {
        "prompt_batch": root_dir / "prompt_batch.json",
        "colab_notebook": root_dir / "colab_notebook.py",
        "provenance_template": root_dir / "provenance_template.json",
        "review_checklist": root_dir / "review_checklist.md",
        "cleanup_plan": root_dir / "cleanup_plan.json",
        "payload_target": root_dir / "payload_target.txt",
    }
    return {key: value for key, value in candidates.items() if value.exists()}


def _build_handoff_manifest(
    *,
    profile_id: str,
    pack_id: str,
    batch_id: str,
    game_scope: str,
    root_dir: Path,
    notebook_code_path: Path,
    batch_copy_path: Path,
    drive_folder: str,
    companions: dict[str, Path],
) -> dict[str, object]:
    upload_items: list[dict[str, object]] = [
        {
            "role": "prompt_batch",
            "path": str(batch_copy_path),
            "drive_name": batch_copy_path.name,
            "required": True,
        },
        {
            "role": "colab_notebook",
            "path": str(notebook_code_path),
            "drive_name": notebook_code_path.name,
            "required": True,
        },
    ]
    for role in ("provenance_template", "review_checklist", "cleanup_plan", "payload_target"):
        path = companions.get(role)
        if path is not None:
            upload_items.append(
                {
                    "role": role,
                    "path": str(path),
                    "drive_name": path.name,
                    "required": role in {"provenance_template", "review_checklist", "cleanup_plan", "payload_target"},
                }
            )

    download_items = [
        {
            "role": "colab_outputs",
            "path": str(root_dir / "outputs"),
            "drive_name": "outputs",
        },
        {
            "role": "execution_log",
            "path": str(root_dir / "execution_log.json"),
            "drive_name": "execution_log.json",
        },
    ]

    return {
        "schema_version": "assetboy.colab_handoff.v1",
        "profile_id": profile_id,
        "pack_id": pack_id,
        "batch_id": batch_id,
        "game_scope": game_scope,
        "local_artifacts_dir": str(root_dir),
        "drive_folder": drive_folder,
        "upload_items": upload_items,
        "download_items": download_items,
        "companion_roles": sorted(companions.keys()),
        "notes": [
            "Upload the prompt batch, notebook, and companion artifacts to the listed Drive folder.",
            "Run the notebook in Colab from that Drive folder, then sync the outputs back into the local artifacts dir.",
        ],
    }


def submit_batch_to_colab(
    batch_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    drive_folder: str | None = None,
    dry_run: bool = False,
) -> ColabSubmissionResult:
    """
    Prepare a prompt_batch.json for Colab execution.

    When dry_run=True, the code is printed locally instead of prepared.
    This is the safe default when the colab_exec MCP server is not active.
    """
    batch = load_prompt_batch(batch_path)
    profile_id = batch.get("profile", {}).get("profile_id", "unknown")
    pack_id = batch.get("pack_id", "unknown")
    game_scope = str(batch.get("game_scope", "unknown"))
    batch_id = str(batch.get("batch_id", f"{game_scope}_{_slug(pack_id)}_{_slug(profile_id)}"))
    jobs = batch.get("jobs", [])

    colab_code = _colab_notebook_for_profile(profile_id)

    root_dir = (
        Path(output_dir)
        if output_dir is not None
        else generated_output_root() / profile_id / pack_id / "colab_run"
    )
    root_dir.mkdir(parents=True, exist_ok=True)

    # Write the Colab notebook code locally (also referenced by the MCP call)
    notebook_code_path = root_dir / "colab_notebook.py"
    notebook_code_path.write_text(colab_code, encoding="utf-8")

    # Copy the batch file into the run dir so Colab can read it from /content
    batch_copy_path = root_dir / "prompt_batch.json"
    import shutil
    shutil.copy2(batch_path, batch_copy_path)

    companions = _companion_paths(Path(batch_path).parent)
    if "prompt_batch" not in companions:
        companions["prompt_batch"] = batch_copy_path

    drive_folder_value = drive_folder or drive_folder_for_colab(profile_id, pack_id, batch_id)
    handoff_manifest = _build_handoff_manifest(
        profile_id=profile_id,
        pack_id=pack_id,
        batch_id=batch_id,
        game_scope=game_scope,
        root_dir=root_dir,
        notebook_code_path=notebook_code_path,
        batch_copy_path=batch_copy_path,
        drive_folder=drive_folder_value,
        companions=companions,
    )
    handoff_manifest_path = write_json(root_dir / "colab_handoff_manifest.json", handoff_manifest)
    drive_stage_plan = build_drive_stage_plan(
        local_artifacts_dir=root_dir,
        drive_folder=drive_folder_value,
        upload_items=handoff_manifest["upload_items"],
        download_items=handoff_manifest["download_items"],
        notes=list(handoff_manifest["notes"]),
    )
    drive_stage_plan_path = write_json(root_dir / "drive_stage_plan.json", drive_stage_plan)
    write_text(
        root_dir / "colab_handoff.md",
        "\n".join(
            [
                f"# Colab Handoff",
                "",
                f"- Pack: `{pack_id}`",
                f"- Profile: `{profile_id}`",
                f"- Batch: `{batch_id}`",
                f"- Drive folder: `{drive_folder_value}`",
                "",
                "## Upload",
                *[f"- `{item['role']}` -> `{item['drive_name']}`" for item in handoff_manifest["upload_items"]],
                "",
                "## Download",
                *[f"- `{item['role']}` -> `{item['drive_name']}`" for item in handoff_manifest["download_items"]],
                "",
            ]
        )
        + "\n",
    )

    if dry_run:
        print(f"[DRY RUN] Would prepare {len(jobs)} jobs for Colab profile={profile_id}")
        print(f"[DRY RUN] Batch: {batch_path}")
        print(f"[DRY RUN] Notebook written to: {notebook_code_path}")
        print(f"[DRY RUN] Handoff manifest: {handoff_manifest_path}")
        print(f"[DRY RUN] Drive stage plan: {drive_stage_plan_path}")
        print(f"[DRY RUN] Drive folder: {drive_folder_value}")
        print("[DRY RUN] To execute for real, open the notebook in colab_exec and run it there.")
    else:
        print(f"Prepared {len(jobs)} Colab jobs for profile={profile_id}")
        print(f"Profile: {profile_id} | Pack: {pack_id}")
        print(f"Batch: {batch_path}")
        print(f"Notebook: {notebook_code_path}")
        print(f"Handoff manifest: {handoff_manifest_path}")
        print(f"Drive stage plan: {drive_stage_plan_path}")
        print(f"Drive folder: {drive_folder_value}")
        print()
        print(">>> This command emits the notebook and batch only; it does not invoke colab_exec.")
        print(">>> Open the notebook in colab_exec_a or colab_exec_b to perform the actual run.")

    return ColabSubmissionResult(
        profile_id=profile_id,
        pack_id=pack_id,
        batch_path=Path(batch_path),
        output_dir=root_dir,
        job_count=len(jobs),
        drive_folder=drive_folder_value,
        handoff_manifest_path=handoff_manifest_path,
        drive_stage_plan_path=drive_stage_plan_path,
        dry_run=dry_run,
    )
