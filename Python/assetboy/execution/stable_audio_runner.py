"""Stable Audio Open Small runner — text-to-audio generation, 6GB VRAM target.

Path B v1.4.1 (2026-05-11). Wraps Stability AI's `stable-audio-open-small`
model (~3B params, runs on RTX 3050 6GB; 11-second ambient clips at 44.1kHz
stereo). License: Stability Community License (free under $1M annual revenue,
training data is CC0/CC-BY/Sampling+ -- clean).

This runner emits a JOB SPEC + invocation plan; actual model inference
happens via a subprocess invocation of Stability's reference CLI OR via a
ComfyUI workflow that loads the model. We don't bundle the model weights;
operator downloads them once from huggingface.co/stabilityai/stable-audio-open-small.

Surface:
    StableAudioBatchResult dataclass
    STABLE_AUDIO_PRESETS — small starter library of ambient prompts
    run_stable_audio_batch(*, pack_id, prompt, duration_s, output_dir, ...)
        -> StableAudioBatchResult
    is_stable_audio_available()
        -> bool  (checks for model dir + sd-runner binary)

Out-of-scope (deferred):
    - Inline torch+diffusers model load (heavy dep; keep subprocess clean).
    - Per-clip duration variance batching.
    - Voice cloning (stable_audio_open isn't trained for that anyway).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from assetboy.library.paths import generated_output_root


# --------------------------------------------------------------------------- #
# Surface constants
# --------------------------------------------------------------------------- #

# Default home for Stable Audio Open Small model files. Operator can override
# by setting STABLE_AUDIO_MODEL_DIR env var.
DEFAULT_MODEL_DIR_ENV = "STABLE_AUDIO_MODEL_DIR"
DEFAULT_MODEL_DIR_SUFFIX = Path("stable_audio_open_small")

# Stability AI's HuggingFace model card URL (operator downloads from here):
MODEL_DOWNLOAD_URL = "https://huggingface.co/stabilityai/stable-audio-open-small"

# Optional binary that wraps the model (Python entry point typically; this
# is just a hint string operator can override).
DEFAULT_RUNNER_BIN_ENV = "STABLE_AUDIO_RUNNER_BIN"


# Starter preset library — useful for primitive_tech / roman_arena ambient
# clips. Each tuple is (preset_id, prompt_text, duration_s).
STABLE_AUDIO_PRESETS: tuple[tuple[str, str, int], ...] = (
    ("forest_dawn_loop",
     "forest at dawn, birds chirping, soft wind through leaves, loop-friendly",
     11),
    ("fire_crackle_close",
     "fire crackle close-up, wood embers, sparks, loop-friendly",
     11),
    ("river_over_rocks",
     "river over rocks, gentle flow, water rushing, loop-friendly",
     11),
    ("wind_through_leaves_distant",
     "wind through leaves, distant, gentle rustling, loop-friendly",
     11),
    ("roman_arena_crowd_distant",
     "distant roman arena crowd, low murmur, occasional cheers, loop-friendly",
     11),
    ("torch_flames_indoor",
     "torch flames indoor, low crackle, occasional pop, loop-friendly",
     11),
)


# --------------------------------------------------------------------------- #
# Result type
# --------------------------------------------------------------------------- #

@dataclass
class StableAudioBatchResult:
    pack_id: str
    prompt: str
    duration_s: int
    output_dir: Path
    job_spec_path: Path | None = None
    invocation_cmd: list[str] = field(default_factory=list)
    dry_run: bool = False
    error: str | None = None


# --------------------------------------------------------------------------- #
# Availability + paths
# --------------------------------------------------------------------------- #

def _default_model_dir() -> Path | None:
    """Resolve the model dir from env var or generated_output_root() fallback."""
    override = os.environ.get(DEFAULT_MODEL_DIR_ENV, "").strip()
    if override:
        path = Path(override).resolve()
        return path if path.exists() else None
    try:
        candidate = generated_output_root() / "models" / DEFAULT_MODEL_DIR_SUFFIX
        return candidate if candidate.exists() else None
    except Exception:
        return None


def is_stable_audio_available() -> bool:
    """True if both the model dir AND a runner binary look ready to use.

    Operator setup:
        1. Download model from https://huggingface.co/stabilityai/stable-audio-open-small
           into a folder (anywhere).
        2. Either:
           a. Set STABLE_AUDIO_MODEL_DIR env var to that folder, OR
           b. Place it under <repo>/state/generated/models/stable_audio_open_small/
        3. Set STABLE_AUDIO_RUNNER_BIN to the path of your inference script
           (a small Python CLI that takes --prompt + --duration + --out).
    """
    model_dir = _default_model_dir()
    if model_dir is None:
        return False
    runner_bin = os.environ.get(DEFAULT_RUNNER_BIN_ENV, "").strip()
    if not runner_bin:
        return False
    return Path(runner_bin).exists() or shutil.which(runner_bin) is not None


# --------------------------------------------------------------------------- #
# Batch runner
# --------------------------------------------------------------------------- #

def run_stable_audio_batch(
    *,
    pack_id: str,
    prompt: str,
    duration_s: int = 11,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
) -> StableAudioBatchResult:
    """Generate one Stable Audio Open Small clip (text-to-audio).

    Args:
        pack_id:    recipe pack id (used in job spec metadata + filename)
        prompt:     text prompt (max ~256 chars; tuned for ambient/SFX)
        duration_s: clip duration in seconds (11s is the model's sweet spot)
        output_dir: where the WAV + job spec land. If None, uses
                    generated_output_root() / "stable_audio" / pack_id
        dry_run:    plan only; emit job spec but don't invoke the runner

    Returns:
        StableAudioBatchResult with job_spec_path + invocation_cmd populated.
        On dry_run, .dry_run=True. On runner error (binary not found, model
        missing, subprocess crash), .error is non-None.

    Honest design notes:
        - We do NOT inline torch + diffusers here. The runner binary is the
          operator's responsibility — keeps this module lightweight and
          avoids dragging a multi-GB ML stack into FAW's import graph.
        - Recipe authors who want guaranteed bytes should use direct_url +
          freesound (CC0 audio samples) until the operator has the Stable
          Audio runner set up.
    """
    pack_id = str(pack_id or "default_pack")
    if not prompt.strip():
        return StableAudioBatchResult(
            pack_id=pack_id, prompt=prompt, duration_s=duration_s,
            output_dir=Path("."), error="empty_prompt",
        )

    if output_dir is None:
        try:
            output_dir = generated_output_root() / "stable_audio" / pack_id
        except Exception as exc:
            return StableAudioBatchResult(
                pack_id=pack_id, prompt=prompt, duration_s=duration_s,
                output_dir=Path("."),
                error=f"output_dir_resolution_failed: {exc}",
            )
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build invocation command. The runner_bin contract:
    #     <bin> --model <model_dir> --prompt "<text>" --duration <s> --out <wav_path>
    model_dir = _default_model_dir()
    runner_bin = os.environ.get(DEFAULT_RUNNER_BIN_ENV, "stable-audio-cli")
    safe_pack = "".join(c if c.isalnum() or c in "_-" else "_" for c in pack_id)
    wav_path = out_dir / f"{safe_pack}.wav"
    invocation = [
        runner_bin,
        "--model", str(model_dir) if model_dir else "<UNSET_STABLE_AUDIO_MODEL_DIR>",
        "--prompt", prompt,
        "--duration", str(duration_s),
        "--out", str(wav_path),
    ]

    # Emit job spec for operator reproducibility (mirrors freesound_runner pattern)
    job_spec = {
        "source_adapter": "stable_audio_open_small",
        "pack_id": pack_id,
        "prompt": prompt,
        "duration_s": duration_s,
        "model_dir": str(model_dir) if model_dir else None,
        "runner_bin": runner_bin,
        "wav_path": str(wav_path),
        "invocation_cmd": invocation,
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(),
        "license_kind": "stability_community",
        "license_notes": (
            "Stability Community License -- free under $1M annual revenue. "
            "Training data is CC0/CC-BY/Sampling+; clean for commercial."
        ),
        "model_download_url": MODEL_DOWNLOAD_URL,
    }
    job_spec_path = out_dir / "stable_audio_job.json"
    job_spec_path.write_text(json.dumps(job_spec, indent=2), encoding="utf-8")

    if dry_run:
        return StableAudioBatchResult(
            pack_id=pack_id, prompt=prompt, duration_s=duration_s,
            output_dir=out_dir, job_spec_path=job_spec_path,
            invocation_cmd=invocation, dry_run=True,
        )

    if not is_stable_audio_available():
        return StableAudioBatchResult(
            pack_id=pack_id, prompt=prompt, duration_s=duration_s,
            output_dir=out_dir, job_spec_path=job_spec_path,
            invocation_cmd=invocation,
            error=(
                "stable_audio_not_available: set STABLE_AUDIO_MODEL_DIR + "
                "STABLE_AUDIO_RUNNER_BIN env vars after downloading model "
                f"from {MODEL_DOWNLOAD_URL}. Job spec written for manual "
                "invocation."
            ),
        )

    # Invoke the subprocess (operator-provided binary).
    import subprocess
    try:
        # Limit walltime to 5 minutes per clip — Stable Audio Open Small
        # generates 11s clips in 10-30s on RTX 3050 6GB; 5min is generous.
        completed = subprocess.run(
            invocation,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (FileNotFoundError, OSError) as exc:
        return StableAudioBatchResult(
            pack_id=pack_id, prompt=prompt, duration_s=duration_s,
            output_dir=out_dir, job_spec_path=job_spec_path,
            invocation_cmd=invocation,
            error=f"runner_bin_invocation_failed: {exc}",
        )
    except subprocess.TimeoutExpired:
        return StableAudioBatchResult(
            pack_id=pack_id, prompt=prompt, duration_s=duration_s,
            output_dir=out_dir, job_spec_path=job_spec_path,
            invocation_cmd=invocation,
            error="runner_timeout_5min (consider reducing duration_s)",
        )

    if completed.returncode != 0:
        return StableAudioBatchResult(
            pack_id=pack_id, prompt=prompt, duration_s=duration_s,
            output_dir=out_dir, job_spec_path=job_spec_path,
            invocation_cmd=invocation,
            error=f"runner_exit_{completed.returncode}: {completed.stderr[:200]}",
        )

    if not wav_path.exists():
        return StableAudioBatchResult(
            pack_id=pack_id, prompt=prompt, duration_s=duration_s,
            output_dir=out_dir, job_spec_path=job_spec_path,
            invocation_cmd=invocation,
            error=f"runner_succeeded_but_no_output_wav: {wav_path}",
        )

    return StableAudioBatchResult(
        pack_id=pack_id, prompt=prompt, duration_s=duration_s,
        output_dir=out_dir, job_spec_path=job_spec_path,
        invocation_cmd=invocation,
    )


__all__ = [
    "STABLE_AUDIO_PRESETS",
    "StableAudioBatchResult",
    "is_stable_audio_available",
    "run_stable_audio_batch",
    "MODEL_DOWNLOAD_URL",
]
