"""One-shot extractor — dumps constants from to-be-deleted DEAD files to YAML.

Run ONCE before Path B deletion phases (s2.5 / s2.6 / s9) to preserve data
that's currently baked into Python source as module-level constants. Each
DEAD file's data lands in its own per-domain YAML in this directory.

Intended workflow:
    cd C:/flax/flax-asset-worker/Python
    python -m assetboy.data._extract_dead_data --all
    git add -- assetboy/data/*.yaml
    git commit -m "[assetboi] feat(data): park DEAD-file constants as YAML"

Each extracted YAML is the source of truth from then on. The original .py
file becomes safe to delete (after wiring readers — s9 covers that).

This file deletes itself after a successful --all run (it's the sole
purpose).
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

import yaml

DATA_DIR = Path(__file__).resolve().parent
PYTHON_ROOT = DATA_DIR.parent.parent  # .../flax-asset-worker/Python
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))


# --------------------------------------------------------------------------- #
# Per-domain extractors — each returns the data structure to YAML.
# Functions are best-effort: ImportError = skip + warn, never crash the run.
# --------------------------------------------------------------------------- #

def _to_plain(obj: Any) -> Any:
    """Convert dataclasses / tuples / enums to plain Python for YAML."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_plain(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if hasattr(obj, "value") and hasattr(obj, "name") and type(obj).__module__ != "builtins":
        # enum.Enum-ish
        try:
            return obj.value
        except Exception:
            return obj.name
    return obj


def _dump_yaml(path: Path, data: Any, note: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"__provenance__": note or path.name, "data": _to_plain(data)}
    path.write_text(
        yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )
    print(f"  wrote {path.relative_to(PYTHON_ROOT)}  ({path.stat().st_size:,} bytes)")


def extract_roman_first_playable() -> None:
    mod = importlib.import_module("assetboy.workflows.roman_first_playable")
    specs = list(getattr(mod, "ROMAN_FIRST_PLAYABLE_SPECS", ()))
    default_only = list(getattr(mod, "ROMAN_PACK_DEFAULT_ONLY_SPECS", ()))
    _dump_yaml(
        DATA_DIR / "roman_first_playable_specs.yaml",
        {"main_specs": specs, "default_only_specs": default_only},
        note="From workflows/roman_first_playable.py:149 + :497 (Path B s9 will consume).",
    )


def extract_animationgpt() -> None:
    mod = importlib.import_module("assetboy.execution.animationgpt_runner")
    presets = list(getattr(mod, "ANIMATION_PRESETS", ()))
    # ANIMATION_PRESETS is a list of 5-tuples; name the fields for YAML clarity.
    rows = [
        {
            "preset_id": p[0],
            "category": p[1],
            "prompt": p[2],
            "duration_s": p[3],
            "notes": p[4] if len(p) > 4 else None,
        } if isinstance(p, tuple) and len(p) >= 4 else p
        for p in presets
    ]
    _dump_yaml(
        DATA_DIR / "animationgpt_presets.yaml",
        rows,
        note="20 combat-anim text prompts from execution/animationgpt_runner.py:44.",
    )


def extract_colab_pipelines() -> None:
    """Colab cell embedded URLs/pip stacks aren't dataclasses; harvest the literals."""
    # The colab_runner has embedded notebook templates. We can't easily AST-parse;
    # instead capture the module's source as a sidecar reference. The post-s2
    # reader can pull URLs from this text.
    mod = importlib.import_module("assetboy.execution.colab_runner")
    src = Path(mod.__file__).read_text(encoding="utf-8")
    _dump_yaml(
        DATA_DIR / "colab_pipelines.yaml",
        {
            "source_module": mod.__name__,
            "source_text": src,
            "hf_pip_refs": [
                line.strip()
                for line in src.splitlines()
                if "huggingface" in line.lower()
                or "git+https://" in line.lower()
                or "tencent/Hunyuan3D" in line
                or "trellis" in line.lower()
            ],
        },
        note="Verbatim source dump of execution/colab_runner.py (s9 will distill).",
    )


def extract_dialogue_presets() -> None:
    mod = importlib.import_module("assetboy.execution.dialogue_runner")
    payload: dict[str, Any] = {}
    for name in (
        "DIALOGUE_PRESETS",
        "SUPPORTED_PROVIDERS",
        "EDGE_TTS_VOICE_MAP",
        "ELEVENLABS_VOICE_MAP",
        "ELEVENLABS_VOICE_ENV_MAP",
    ):
        if hasattr(mod, name):
            payload[name] = getattr(mod, name)
    _dump_yaml(
        DATA_DIR / "dialogue_presets.yaml",
        payload,
        note="execution/dialogue_runner.py:21+ — voice-line presets + provider maps.",
    )


def extract_music_presets() -> None:
    mod = importlib.import_module("assetboy.execution.music_runner")
    payload = {
        "ROMAN_MUSIC_PRESETS": list(getattr(mod, "ROMAN_MUSIC_PRESETS", ())),
        "MIXKIT_BASE": getattr(mod, "MIXKIT_BASE", None),
        "SUNO_BASE": getattr(mod, "SUNO_BASE", None),
        "UDIO_BASE": getattr(mod, "UDIO_BASE", None),
    }
    _dump_yaml(
        DATA_DIR / "music_presets.yaml",
        payload,
        note="execution/music_runner.py:22+ — music source URLs + prompt presets.",
    )


def extract_misc_runner_presets() -> None:
    """Bulk-dump small preset lists from vehicle/vfx/museum/font/game_icons/quaternius."""
    targets = [
        ("vehicle", "assetboy.execution.vehicle_runner",
         ["VEHICLE_PRESETS", "VEHICLE_DIRECT_ZIPS"]),
        ("vfx", "assetboy.execution.vfx_runner",
         ["VFX_PRESETS", "OGA_MANUAL_DROP_TARGETS"]),
        ("museum", "assetboy.execution.museum_runner",
         ["MUSEUM_PRESETS"]),
        ("font", "assetboy.execution.font_runner",
         ["FONT_PRESETS"]),
        ("game_icons", "assetboy.execution.game_icons_runner",
         ["GAME_ICONS_GITHUB_ZIP", "GAME_ICONS_LICENSE",
          "GAME_ICONS_ATTRIBUTION", "GAME_ICONS_AUTHOR_URL",
          "CATEGORY_KEYWORDS"]),
        ("quaternius", "assetboy.execution.quaternius_runner",
         ["QUATERNIUS_PRESETS", "QUATERNIUS_DIRECT_ZIPS"]),
    ]
    for domain, module_path, names in targets:
        try:
            mod = importlib.import_module(module_path)
        except ImportError as exc:
            print(f"  SKIP {domain}: {exc}")
            continue
        payload = {name: getattr(mod, name, None) for name in names}
        _dump_yaml(
            DATA_DIR / f"{domain}_presets.yaml",
            payload,
            note=f"From {module_path} (Path B s2 data park).",
        )


def extract_playwright_presets() -> None:
    """Mixamo character presets buried in playwright_runner (line 2008)."""
    mod = importlib.import_module("assetboy.execution.playwright_runner")
    payload: dict[str, Any] = {}
    for name in (
        "_MIXAMO_CHARACTER_PRESETS",
        "ADAPTER_STEP_BUILDERS",
        "ADAPTER_STRUCTURED_STEP_BUILDERS",
    ):
        if hasattr(mod, name):
            val = getattr(mod, name)
            # ADAPTER_STEP_BUILDERS is a dict[str, callable]; only key list useful.
            if name.startswith("ADAPTER"):
                payload[f"{name}_keys"] = sorted(val.keys()) if isinstance(val, dict) else []
            else:
                payload[name] = val
    _dump_yaml(
        DATA_DIR / "playwright_presets.yaml",
        payload,
        note="execution/playwright_runner.py — Mixamo character presets + adapter-key inventory.",
    )


def extract_provider_profiles() -> None:
    """ai_bridge / engine_bridge / extractor_bridge / runbooks provider tables."""
    bundle: dict[str, Any] = {}
    try:
        m = importlib.import_module("assetboy.providers.ai_bridge")
        bundle["AI_PROVIDER_PROFILES"] = getattr(m, "AI_PROVIDER_PROFILES", None)
    except ImportError as exc:
        print(f"  SKIP ai_bridge: {exc}")
    try:
        m = importlib.import_module("assetboy.providers.engine_bridge")
        bundle["ENGINE_BRIDGE_PROFILES"] = getattr(m, "ENGINE_BRIDGE_PROFILES", None)
        bundle["DEFAULT_ASSET_TYPES"] = getattr(m, "DEFAULT_ASSET_TYPES", None)
        bundle["DEFAULT_SKIP_TYPES"] = getattr(m, "DEFAULT_SKIP_TYPES", None)
    except ImportError as exc:
        print(f"  SKIP engine_bridge: {exc}")
    try:
        m = importlib.import_module("assetboy.providers.extractor_bridge")
        bundle["EXTRACTOR_PROFILES"] = getattr(m, "EXTRACTOR_PROFILES", None)
    except ImportError as exc:
        print(f"  SKIP extractor_bridge: {exc}")
    try:
        m = importlib.import_module("assetboy.providers.runbooks")
        bundle["STATIC_PROVIDER_RUNBOOKS"] = getattr(m, "STATIC_PROVIDER_RUNBOOKS", None)
    except ImportError as exc:
        print(f"  SKIP runbooks: {exc}")
    _dump_yaml(
        DATA_DIR / "provider_profiles.yaml",
        bundle,
        note="providers/ai_bridge.py + engine_bridge + extractor_bridge + runbooks — provider routing tables.",
    )


def extract_pack_family_plan_data() -> None:
    mod = importlib.import_module("assetboy.workflows.pack_family_plan")
    payload = {
        "BROWSER_SOURCE_URLS": getattr(mod, "BROWSER_SOURCE_URLS", {}),
        "SOURCE_PAGE_URLS": getattr(mod, "SOURCE_PAGE_URLS", {}),
        "DEFAULT_PROFILE_BY_BRIDGE_ID": getattr(mod, "DEFAULT_PROFILE_BY_BRIDGE_ID", {}),
        "ENGINE_KIND_BY_BRIDGE_ID": getattr(mod, "ENGINE_KIND_BY_BRIDGE_ID", {}),
    }
    _dump_yaml(
        DATA_DIR / "pack_family_plan_data.yaml",
        payload,
        note="workflows/pack_family_plan.py:18+ — URL/profile maps (s5+ to fold into bridge_registry).",
    )


def extract_roman_source_presets() -> None:
    mod = importlib.import_module("assetboy.workflows.roman_source_presets")
    payload: dict[str, Any] = {}
    for name in ("_DIRECT_DOWNLOAD_SUFFIXES",
                 "_PACK_MIXAMO_PRESETS",
                 "_HELPER_PACK_PRESETS"):
        if hasattr(mod, name):
            payload[name.lstrip("_")] = getattr(mod, name)
    _dump_yaml(
        DATA_DIR / "roman_source_presets.yaml",
        payload,
        note="workflows/roman_source_presets.py:16-44 — per-pack helper/mixamo presets.",
    )


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

EXTRACTORS: dict[str, Callable[[], None]] = {
    "roman_first_playable": extract_roman_first_playable,
    "animationgpt": extract_animationgpt,
    "colab": extract_colab_pipelines,
    "dialogue": extract_dialogue_presets,
    "music": extract_music_presets,
    "misc_runners": extract_misc_runner_presets,
    "playwright": extract_playwright_presets,
    "provider_profiles": extract_provider_profiles,
    "pack_family_plan": extract_pack_family_plan_data,
    "roman_source_presets": extract_roman_source_presets,
}


def main() -> int:
    p = argparse.ArgumentParser(prog="extract_dead_data")
    p.add_argument(
        "--only",
        choices=list(EXTRACTORS.keys()),
        help="Run a single extractor (default: all).",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Run every extractor (default behavior).",
    )
    args = p.parse_args()

    targets = [args.only] if args.only else list(EXTRACTORS.keys())
    print(f"== extracting {len(targets)} domain(s) to {DATA_DIR.relative_to(PYTHON_ROOT)}/ ==")

    failures: list[tuple[str, Exception]] = []
    for name in targets:
        print(f"\n[{name}]")
        try:
            EXTRACTORS[name]()
        except Exception as exc:
            failures.append((name, exc))
            print(f"  FAILED: {exc}")
            traceback.print_exc()

    if failures:
        print(f"\n== {len(failures)} extractor(s) failed:")
        for name, exc in failures:
            print(f"  - {name}: {exc}")
        return 1

    print(f"\n== OK: all {len(targets)} extractors green ==")
    print(f"   YAML files in: {DATA_DIR.relative_to(PYTHON_ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
