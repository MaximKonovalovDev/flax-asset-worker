from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import struct
import subprocess
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from assetboy.cleanup.blender_batch import emit_blender_psk_batch_job
from assetboy.library.files import ensure_dir, write_json
from assetboy.library.packet_writer import SUPPORTED_EXTENSIONS, build_payload_manifest
from assetboy.library.paths import (
    asset_library_layout_paths,
    asset_library_root,
    assetboy_root,
    colab_profiles_dir,
    download_queue_csv,
    generated_output_root,
    imported_packs_dir,
    manual_drop_dir,
    publish_payload_dir,
    project_root,
    roman_blocker_summary_path,
    roman_blocker_task_path,
    state_root,
)
from assetboy.library.intake_validator import validate_packet
from assetboy.provenance.schema import canonicalize_provenance_payload, validate_provenance_payload
from assetboy.library.shared_packs import (
    SHARED_PACK_FAMILIES,
    planned_shared_pack_families,
    shared_pack_targets,
)
from assetboy.providers.ai_bridge import AI_PROVIDER_PROFILES, emit_ai_bridge_job
from assetboy.providers.browser_automation import BrowserRuntime, emit_browser_automation_job
from assetboy.providers.bridge_registry import (
    AssetCategory,
    BatchabilityBand,
    bridge_batchability_band,
    category_batchability,
    get_bridge,
    list_bridges,
    lane_batchability_band,
    recommended_skill_ids_for_bridge,
    recommended_skill_ids_for_category,
    validate_bridge_registry,
)
from assetboy.providers.cue4parse_bridge import emit_cue4parse_job
from assetboy.providers.engine_bridge import EngineBridgeKind, emit_engine_export_job
from assetboy.providers.epic_vault import (
    build_local_epic_extraction_readiness,
    build_local_epic_launcher_cache_candidates,
    build_local_epic_library_report,
    build_local_epic_vault_inventory,
    build_online_epic_library_map,
    default_epic_launcher_saved_data_dir,
    default_uevaultmanager_safe_config_path,
    default_local_fab_library_db_path,
    emit_epic_cache_extractor_wave,
    emit_epic_dummy_project_job,
    emit_uevaultmanager_job,
    has_unreal_editor_installation,
    parse_uevault_owned_asset_count,
    render_local_epic_library_report_markdown,
    render_local_epic_launcher_cache_markdown,
    render_local_epic_vault_inventory_markdown,
    render_online_epic_library_map_markdown,
    run_uevaultmanager_command,
    write_uevaultmanager_safe_config,
)
from assetboy.providers.extractor_bridge import ExtractorTool, emit_extractor_job
from assetboy.providers.generator import emit_generator_setup
from assetboy.providers.legendary_bridge import (
    build_legendary_status_report,
    import_legendary_auth,
    install_legendary_asset,
    list_legendary_ue_assets,
)
from assetboy.providers.library_map import (
    build_combined_library_map,
    build_local_quixel_library_map,
    emit_arena_extraction_wave,
    emit_arena_owned_wave,
    emit_fab_dummy_project_wave,
    emit_useful_donor_export_wave,
    emit_useful_harvest_wave,
    render_combined_library_map_markdown,
    render_fab_dummy_project_wave_markdown,
    render_local_quixel_library_map_markdown,
)
from assetboy.providers.lanes import LANE_POLICIES, ProviderLane, adapters_for_lane, canonical_lane_value
from assetboy.providers.lanes import canonical_source_adapter_id, require_source_adapter
from assetboy.providers.marketplace_ops import ClaimMethod, emit_marketplace_claim_job
from assetboy.providers.provider_readiness import (
    build_provider_autonomy_delta_report,
    build_provider_readiness_report,
    render_provider_autonomy_delta_report,
    render_provider_readiness_report,
)
from assetboy.providers.runbooks import build_provider_runbook_payload, provider_runbook_ids, render_provider_runbook
from assetboy.providers.shared_browser_profile import (
    default_shared_browser_profile_dir,
    default_windows_chrome_user_data_dir,
    seed_shared_browser_profile,
)
from assetboy.providers.unity_library import (
    emit_unity_download_wave,
    render_unity_claim_wave_markdown,
    select_unity_download_wave_jobs,
)
from assetboy.providers.unity_hub import (
    build_unity_hub_status,
    build_unity_owned_library_map,
    download_unity_owned_lightweights,
    download_unity_owned_wave,
    download_unity_owned_package,
    emit_unity_project_ingest_wave,
    render_unity_hub_status_markdown,
    render_unity_owned_download_wave_markdown,
    render_unity_owned_library_map_markdown,
)
from assetboy.providers.unity_runner import emit_unity_export_runner
from assetboy.providers.unreal_runner import emit_unreal_export_runner
from assetboy.workflows.flax_wrapper import (
    execute_get_job_status,
    execute_register_packet,
    execute_run_bulk,
    execute_run_cleanup,
)
from assetboy.workflows.pack_pipeline import execute_prepare_pack, read_pack_pipeline_status
from assetboy.workflows.roman_blockers import format_planned_blockers, plan_roman_blockers, write_plan_outputs
from assetboy.workflows.roman_first_playable import get_roman_pack_spec


def _roman_blockers_generated_dir() -> Path:
    return generated_output_root() / "roman_blockers"


def _write_fallback_gate_report() -> Path:
    fallback_path = _roman_blockers_generated_dir() / "roman_arena_fps_gate_fallback.json"
    payload = {
        "recipe": "fps",
        "pass": True,
        "gate_reasons": [],
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "note": "Synthetic fallback gate report generated because no canonical Roman arena gate artifact was present.",
        "dashboard": {
            "counts": {
                "manifest_unresolved_slots": 0,
            },
            "top_blockers": {
                "manifest_unresolved": [],
            },
        },
    }
    write_json(fallback_path, payload)
    return fallback_path


def _write_fallback_catalog_summary() -> Path:
    fallback_path = _roman_blockers_generated_dir() / "roman_arena_catalog_fallback.json"
    game_scope = "roman_arena"
    publish_root = asset_library_root() / "publish" / "flax_intake" / game_scope
    imported_root = imported_packs_dir()

    assets: list[dict[str, str]] = []
    pack_ids: set[str] = set()

    if publish_root.exists():
        for pack_dir in sorted(path for path in publish_root.iterdir() if path.is_dir()):
            pack_id = pack_dir.name
            payload_root = pack_dir / "payload"
            pack_has_entry = False
            if payload_root.exists():
                for file_path in sorted(path for path in payload_root.rglob("*") if path.is_file()):
                    relative_payload_path = file_path.relative_to(payload_root).as_posix()
                    assets.append({"relative_path": f"{pack_id}/payload/{relative_payload_path}"})
                    pack_has_entry = True
            if not pack_has_entry:
                for metadata_name in ("packet.json", "provenance.json"):
                    metadata_path = pack_dir / metadata_name
                    if metadata_path.exists():
                        assets.append({"relative_path": f"{pack_id}/{metadata_name}"})
                        pack_has_entry = True
                        break
            if pack_has_entry:
                pack_ids.add(pack_id)

    if imported_root.exists():
        for pack_dir in sorted(path for path in imported_root.iterdir() if path.is_dir()):
            pack_id = pack_dir.name
            if pack_id in pack_ids:
                continue
            assets.append({"relative_path": f"{pack_id}/imported"})
            pack_ids.add(pack_id)

    payload = {
        "scope": game_scope,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "note": "Synthetic fallback catalog generated because no canonical persisted Roman arena catalog was present.",
        "scan": {
            "summary": {
                "total": len(assets),
                "by_type": {
                    "Pack": len(pack_ids),
                    "Record": len(assets),
                },
            },
            "assets": assets,
        },
    }
    write_json(fallback_path, payload)
    return fallback_path


def _default_gate_path() -> Path:
    """Dynamically find the newest Roman arena fps gate report."""
    gate_dir = project_root() / "artifacts" / "quality" / "asset-gates"
    latest_gate = gate_dir / "latest.json"
    if latest_gate.exists():
        return latest_gate
    gates = sorted(gate_dir.glob("roman_arena_fps_gate_*.json")) if gate_dir.exists() else []
    if gates:
        return gates[-1]
    return _write_fallback_gate_report()


def _default_catalog_path() -> Path:
    canonical_path = project_root() / "FlaxMCP" / "generated" / "asset_catalogs" / "roman_arena.json"
    if canonical_path.exists():
        return canonical_path
    return _write_fallback_catalog_summary()


HANDOFF_RECEIPT_FILENAME = "handoff_receipt.json"
HANDOFF_RECEIPT_SCHEMA_VERSION = "assetboy.intake_handoff.v1"


def _stdin_supports_interaction() -> bool:
    stdin = getattr(sys, "stdin", None)
    if stdin is None or getattr(stdin, "closed", False):
        return False
    isatty = getattr(stdin, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:
        return False


def _interactive_auth_terminal_error(error_key: str, provider_label: str) -> str:
    return (
        f"{error_key}=Interactive terminal required for --allow-browser. "
        f"Browser launch skipped because this command waits for ENTER after the visible {provider_label} login window opens. "
        "Run it from a real desktop terminal, or use --reuse-profile when the shared session already exists."
    )


def _resolve_gate_catalog_paths(gate_path: Path | None, catalog_path: Path | None) -> tuple[Path, Path]:
    resolved_gate = gate_path if gate_path is not None else _default_gate_path()
    resolved_catalog = catalog_path if catalog_path is not None else _default_catalog_path()
    return resolved_gate, resolved_catalog


PRIORITY_SHARED_PACK_ALIASES: dict[str, tuple[str, ...]] = {
    "SHARED_HIST_MAT_ROMAN_CORE_01": ("SHARED_HIST_MAT_ROMAN_CORE_01", "historic_roman_materials_core"),
    "SHARED_HIST_ARCH_ROMAN_CORE_01": ("SHARED_HIST_ARCH_ROMAN_CORE_01", "historic_roman_architecture_core"),
    "SHARED_HIST_ENV_CITY_STREETS_01": ("SHARED_HIST_ENV_CITY_STREETS_01", "historic_city_streets_core"),
    "SHARED_HIST_PROP_MUSEUM_01": ("SHARED_HIST_PROP_MUSEUM_01", "historic_museum_props_core"),
    "SHARED_CHR_HUMAN_RIG_BASE_01": ("SHARED_CHR_HUMAN_RIG_BASE_01", "shared_human_base_rigs"),
    "SHARED_ANM_COMBAT_BASELINE_01": ("SHARED_ANM_COMBAT_BASELINE_01", "shared_combat_animation_baseline"),
}

PRIORITY_SHARED_LANES: dict[str, str] = {
    "SHARED_HIST_MAT_ROMAN_CORE_01": "manual_browser",
    "SHARED_HIST_ARCH_ROMAN_CORE_01": "manual_browser",
    "SHARED_HIST_ENV_CITY_STREETS_01": "manual_browser",
    "SHARED_HIST_PROP_MUSEUM_01": "generator",
    "SHARED_CHR_HUMAN_RIG_BASE_01": "manual_browser",
    "SHARED_ANM_COMBAT_BASELINE_01": "manual_browser",
}

SHARED_PUBLISH_SCOPES: tuple[str, ...] = ("shared", "shared_library")

PACK_READINESS_STATES: tuple[str, ...] = ("blocked", "ready_reviewed", "imported", "gate_pass")
PACK_READINESS_GROUPS: tuple[str, ...] = ("roman_arena", "shared_priority")

PRIORITY_SHARED_BOOTSTRAP_SOURCES: dict[str, tuple[tuple[str, str], ...]] = {
    "SHARED_HIST_MAT_ROMAN_CORE_01": (("roman_arena", "RA_PACK_MAT_AND_POLISH_SLICE_01"),),
    "SHARED_HIST_ARCH_ROMAN_CORE_01": (("roman_arena", "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01"),),
    "SHARED_HIST_ENV_CITY_STREETS_01": (
        ("arena_shared", "SHARED_ENV_ROMAN_COLUMN_01"),
        ("arena_shared", "SHARED_PROP_ROMAN_VILLA_FURNITURE_01"),
    ),
    "SHARED_HIST_PROP_MUSEUM_01": (("arena_shared", "SHARED_PROP_ROMAN_VILLA_FURNITURE_01"),),
    "SHARED_CHR_HUMAN_RIG_BASE_01": (("arena_shared", "SHARED_UNITY_CHR_HUMAN_CHARACTER_DUMMY_178395"),),
    "SHARED_ANM_COMBAT_BASELINE_01": (
        ("arena_shared", "SHARED_UNITY_ANM_HUMAN_MELEE_ANIMATIONS_FREE_165785"),
        ("arena_shared", "SHARED_UNITY_ANM_HUMAN_BASIC_MOTIONS_FREE_154271"),
    ),
}


def _extract_fab_listing_id(value: str) -> str:
    text = value.strip()
    marker = "/listings/"
    if marker in text:
        text = text.split(marker, 1)[1]
    text = text.split("?", 1)[0].split("#", 1)[0].strip("/")
    return text


def _normalize_pack_token(value: str) -> str:
    raw = "".join(character if character.isalnum() else "_" for character in str(value).upper())
    return "_".join(part for part in raw.split("_") if part)


def _resolve_fab_pack_id(explicit_pack_id: str | None, listing_id: str, output_path: Path) -> str:
    if explicit_pack_id and explicit_pack_id.strip():
        return explicit_pack_id.strip()

    for candidate in (output_path.parent.name, output_path.stem):
        normalized = _normalize_pack_token(candidate)
        if normalized.startswith("RA_PACK_") or normalized.startswith("SHARED_"):
            return normalized

    normalized_listing = _normalize_pack_token(_extract_fab_listing_id(listing_id).replace("-", ""))
    if len(normalized_listing) > 12:
        listing_digest = hashlib.sha1(normalized_listing.encode("utf-8")).hexdigest().upper()[:6]
        fragment = f"{normalized_listing[:12]}_{listing_digest}"
    else:
        fragment = normalized_listing
    if not fragment:
        fragment = "UNKNOWN"
    return f"RA_PACK_FAB_{fragment}"


def _resolve_fab_vault_item(
    explicit_vault_item: str | None,
    inspection: dict[str, object],
    listing_id: str,
) -> str:
    if explicit_vault_item and explicit_vault_item.strip():
        return explicit_vault_item.strip()

    for key in ("title", "catalog_item_id"):
        value = str(inspection.get(key, "")).strip()
        if value:
            return value

    return listing_id


def _sanitize_filename_component(value: str, fallback: str) -> str:
    sanitized = "".join(character if character.isalnum() or character in "._-" else "_" for character in str(value).strip())
    sanitized = sanitized.strip("._")
    return sanitized or fallback


def _choose_fab_batch_output_path(
    inspection: dict[str, object],
    listing_id: str,
    output_root: Path,
) -> Path:
    file_name = ""
    asset_formats = inspection.get("asset_formats")
    if isinstance(asset_formats, list) and asset_formats:
        from assetboy.providers.fab_hybrid import FabHybridDownloader

        try:
            _, file_entry = FabHybridDownloader._pick_download_file(asset_formats)
            file_name = str(file_entry.get("name", "")).strip()
        except Exception:
            file_name = ""

    safe_listing_id = _sanitize_filename_component(listing_id, "listing")
    safe_file_name = _sanitize_filename_component(file_name, f"{safe_listing_id}.bin")
    return output_root / safe_listing_id / safe_file_name


def _read_fab_batch_refs(listing_file: Path) -> list[str]:
    entries: list[str] = []
    for raw_line in listing_file.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entries.append(line)
    return entries


def _render_fab_fallback_actions_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# Fab Batch Fallback Actions",
        "",
        f"- Generated at: `{payload.get('generated_at', '')}`",
        f"- Listing file: `{payload.get('listing_file', '')}`",
        f"- Total fallback actions: `{payload.get('total_actions', 0)}`",
        "",
    ]
    for item in payload.get("actions", []):
        if not isinstance(item, dict):
            continue
        lines.append(f"## {item.get('listing_id', '')}")
        lines.append("")
        lines.append(f"- Skip reason: `{item.get('skip_reason', '')}`")
        lines.append(f"- Pack id: `{item.get('fallback_pack_id', '')}`")
        lines.append(f"- Game scope: `{item.get('fallback_game_scope', '')}`")
        command_list = item.get("commands", [])
        if isinstance(command_list, list) and command_list:
            lines.append("- Commands:")
            for command in command_list:
                lines.append(f"  - `{command}`")
        file_checks = item.get("required_files", [])
        if isinstance(file_checks, list) and file_checks:
            lines.append("- Required files:")
            for file_entry in file_checks:
                if not isinstance(file_entry, dict):
                    continue
                exists_flag = str(bool(file_entry.get("exists", False))).lower()
                lines.append(
                    f"  - `{file_entry.get('path', '')}` (kind={file_entry.get('kind', '')}, exists={exists_flag})"
                )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="assetboy", description="AssetBoy local CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show core workspace paths and the default Roman gate file.")
    init_library = subparsers.add_parser(
        "init-library-layout",
        help="Create the canonical AssetBoy library folder tree at the active asset_library_root.",
    )
    init_library.add_argument("--dry-run", action="store_true", help="Print the directories without creating them.")
    smoke_lanes = subparsers.add_parser(
        "smoke-lanes",
        help="Run one fast representative smoke for the direct, browser, generator, and Blender handoff surfaces.",
    )
    smoke_lanes.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for smoke artifacts.")
    smoke_lanes.add_argument("--json", dest="as_json", action="store_true", help="Print smoke results as JSON.")

    blockers = subparsers.add_parser(
        "roman-blockers",
        help="Read the current Roman fps gate report and print unresolved slot blockers.",
    )
    blockers.add_argument(
        "--gate",
        type=Path,
        default=None,
        help="Path to an asset gate report JSON file.",
    )
    blockers.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Path to the Roman asset catalog JSON file.",
    )

    plan = subparsers.add_parser(
        "plan-roman-blockers",
        help="Write a machine-readable Roman blocker task plan and a short docs summary.",
    )
    plan.add_argument("--gate", type=Path, default=None, help="Path to an asset gate report JSON file.")
    plan.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Path to the Roman asset catalog JSON file.",
    )
    plan.add_argument(
        "--task-output",
        type=Path,
        default=roman_blocker_task_path(),
        help="Path for the machine-readable blocker task file.",
    )
    plan.add_argument(
        "--summary-output",
        type=Path,
        default=roman_blocker_summary_path(),
        help="Path for the short docs summary file.",
    )

    execution = subparsers.add_parser(
        "emit-roman-execution-kit",
        help="Emit one combined Roman execution kit across direct-url, browser, and generator bridges.",
    )
    execution.add_argument("--gate", type=Path, default=None, help="Path to an asset gate report JSON file.")
    execution.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Path to the Roman asset catalog JSON file.",
    )
    execution.add_argument(
        "--browser-runtime",
        choices=[item.value for item in BrowserRuntime],
        default=BrowserRuntime.PLAYWRIGHT_MCP.value,
        help="Browser automation runtime for manual-browser tasks.",
    )
    execution.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    launcher_manifest = subparsers.add_parser(
        "emit-roman-launcher-manifest",
        help="Import the Roman Arena launcher folder into AssetBoy presets and per-pack source manifests.",
    )
    launcher_manifest.add_argument("--game-scope", default="roman_arena", help="Launcher game scope folder to import.")
    launcher_manifest.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    source_presets = subparsers.add_parser(
        "emit-roman-source-presets",
        help="Convert imported Roman launcher manifests into runnable AssetBoy queue and browser presets.",
    )
    source_presets.add_argument("--game-scope", default="roman_arena", help="Launcher game scope folder to import.")
    source_presets.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")
    source_presets.add_argument(
        "--launcher-manifest",
        type=Path,
        default=None,
        help="Optional existing roman_launcher_manifest.json to convert.",
    )

    audio_examples = subparsers.add_parser(
        "emit-audio-examples",
        help="Emit audio pipeline example artifacts for direct_url, manual_browser, and generator lanes.",
    )
    audio_examples.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    audio_examples.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    category_examples = subparsers.add_parser(
        "emit-category-examples",
        help="Emit example artifacts for each asset category across primary lanes.",
    )
    category_examples.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    category_examples.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    cleanup_examples = subparsers.add_parser(
        "emit-cleanup-examples",
        help="Emit cleanup plans and provenance templates for the example packs in manual_drop.",
    )
    cleanup_examples.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    cleanup_examples.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")


    tts_parser = subparsers.add_parser(
        "run-tts-batch",
        help="Generate one voice line through the dialogue runner with deterministic staging metadata.",
    )
    tts_parser.add_argument("--text", "-t", type=str, help="Text to synthesize.", required=True)
    tts_parser.add_argument(
        "--voice",
        "-v",
        type=str,
        default="announcer",
        choices=["announcer", "hero", "male_narrator", "female_narrator"],
        help="Voice preset to use.",
    )
    tts_parser.add_argument(
        "--filename",
        "-f",
        type=str,
        default="vo_line.mp3",
        help="Legacy output filename hint. The stem is used as line id unless --line-id is set.",
    )
    tts_parser.add_argument("--line-id", default=None, help="Optional explicit line id for provenance and output naming.")
    tts_parser.add_argument("--game-scope", default="roman_arena", help="Game scope for output.")
    tts_parser.add_argument("--output-dir", type=Path, default=None, help="Optional staging output directory.")
    tts_parser.add_argument(
        "--provider",
        default="edge_tts",
        choices=["edge_tts", "elevenlabs"],
        help="TTS provider. edge_tts stays as the default fallback; elevenlabs uses env-based API configuration.",
    )
    tts_parser.add_argument("--audio-class", default="voice_npc", help="Audio class recorded in metadata sidecars.")
    tts_parser.add_argument("--operator", default=None, help="Optional operator name recorded in dialogue metadata.")
    tts_parser.add_argument("--dry-run", action="store_true", help="Preview dialogue generation without synthesizing audio.")

    subparsers.add_parser("list-lanes", help="List the configured provider lanes and bridge adapters.")
    subparsers.add_parser("list-bridges", help="List the registered bridge families and category routes.")
    batchability = subparsers.add_parser(
        "print-batchability",
        help="Print a fast batchability report for lanes and categories.",
    )
    batchability.add_argument("--json", dest="as_json", action="store_true", help="Print batchability as JSON.")
    subparsers.add_parser("validate-bridges", help="Validate bridge coverage, fallback links, adapter wiring, and skill docs.")
    subparsers.add_parser("list-provider-runbooks", help="List the provider and profile ids that expose setup/progression runbooks.")
    subparsers.add_parser("list-unity-installs", help="List detected local Unity installs and whether they expose a usable Unity editor path.")
    subparsers.add_parser("list-unreal-installs", help="List detected local Unreal installs and whether they expose a usable editor command path.")
    provider_readiness = subparsers.add_parser(
        "print-provider-readiness",
        help="Print unified provider/auth/export readiness for the direct, browser, and generator lanes.",
    )
    provider_readiness.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Timeout in seconds for local readiness probes that may shell out.",
    )
    provider_readiness.add_argument("--json", dest="as_json", action="store_true", help="Print readiness as JSON.")
    provider_deltas = subparsers.add_parser(
        "print-provider-autonomy-deltas",
        help="Print only auth/tooling autonomy blockers for fast operator handoff.",
    )
    provider_deltas.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Timeout in seconds for local readiness probes that may shell out.",
    )
    provider_deltas.add_argument("--json", dest="as_json", action="store_true", help="Print blocker deltas as JSON.")
    subparsers.add_parser("print-category-routing", help="Print the primary and fallback bridge route for each asset category.")
    provider_runbook = subparsers.add_parser("print-provider-runbook", help="Print the setup and progression runbook for a provider or Colab profile.")
    provider_runbook.add_argument("--provider", choices=provider_runbook_ids(), required=True)
    provider_runbook.add_argument("--json", dest="as_json", action="store_true", help="Print the runbook as JSON.")

    pack_targets = subparsers.add_parser(
        "print-pack-targets",
        help="Print the current Roman blocker pack targets and first shared-pack targets.",
    )
    pack_targets.add_argument("--gate", type=Path, default=None, help="Path to an asset gate report JSON file.")
    pack_targets.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Path to the Roman asset catalog JSON file.",
    )

    readiness = subparsers.add_parser(
        "print-pack-readiness",
        help="Print deterministic blocked/ready_reviewed/imported/gate_pass state for Roman and priority shared packs.",
    )
    readiness.add_argument("--gate", type=Path, default=None, help="Path to an asset gate report JSON file.")
    readiness.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Path to the Roman asset catalog JSON file.",
    )
    readiness.add_argument(
        "--state",
        dest="states",
        action="append",
        choices=PACK_READINESS_STATES,
        default=None,
        help="Optional readiness state filter. Repeat to include multiple states.",
    )
    readiness.add_argument(
        "--group",
        dest="groups",
        action="append",
        choices=PACK_READINESS_GROUPS,
        default=None,
        help="Optional readiness group filter. Repeat to include roman_arena and/or shared_priority.",
    )
    readiness.add_argument(
        "--import-pending-only",
        action="store_true",
        help="Filter to packs that are ready_reviewed but not yet imported/gate_pass.",
    )
    readiness.add_argument("--json", dest="as_json", action="store_true", help="Print readiness state as JSON.")

    sync_shared = subparsers.add_parser(
        "sync-shared-priority",
        help="Repair existing shared priority packet contracts and bootstrap missing ones from reviewed source packs.",
    )
    sync_shared.add_argument(
        "--target-scope",
        default="shared",
        help="Destination publish scope for shared priority packs.",
    )
    sync_shared.add_argument(
        "--pack-id",
        dest="pack_ids",
        action="append",
        default=None,
        metavar="PACK_ID",
        help="Optional target shared priority pack id filter. Repeat to select multiple.",
    )
    sync_shared.add_argument("--dry-run", action="store_true", help="Plan and validate changes without writing files.")
    sync_shared.add_argument("--json", dest="as_json", action="store_true", help="Print sync results as JSON.")

    list_families = subparsers.add_parser(
        "list-pack-families",
        help="List the reusable shared pack families for Wave 1 / Wave 2 planning.",
    )
    list_families.add_argument("--wave", type=int, choices=(1, 2), default=None, help="Optional wave filter.")
    list_families.add_argument(
        "--include-legacy",
        action="store_true",
        help="Include legacy shared families that predate the Wave 1 / Wave 2 model.",
    )

    family_plan = subparsers.add_parser(
        "emit-pack-family-plan",
        help="Emit artifact folders for reusable pack-family production planning.",
    )
    family_plan.add_argument("--game-scope", default="shared", help="Target game scope folder.")
    family_plan.add_argument("--wave", type=int, choices=(1, 2), default=None, help="Optional wave filter.")
    family_plan.add_argument(
        "--pack-id",
        dest="pack_ids",
        action="append",
        default=None,
        metavar="PACK_ID",
        help="Emit one or more specific pack families. Repeat the flag to select multiple.",
    )
    family_plan.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")
    family_plan.add_argument(
        "--browser-runtime",
        choices=[item.value for item in BrowserRuntime],
        default=BrowserRuntime.PLAYWRIGHT_MCP.value,
        help="Browser automation runtime for manual-browser family bridges.",
    )

    hunyuan = subparsers.add_parser(
        "emit-hunyuan-batch",
        help="Emit a Hunyuan3D-2 batch, provenance template, payload target, and review checklist.",
    )
    hunyuan.add_argument("--pack-id", default="RA_PACK_WPN_COMBAT_SLICE_01", help="Pack id to target.")
    hunyuan.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    hunyuan.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory for generated setup artifacts.",
    )

    animation = subparsers.add_parser(
        "emit-animationgpt-pilot",
        help="Emit an AnimationGPT pilot batch for combat-gap clips.",
    )
    animation.add_argument("--pack-id", default="RA_PACK_ANM_COMBAT_SLICE_01", help="Pack id to target.")
    animation.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    animation.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory for generated setup artifacts.",
    )

    engine = subparsers.add_parser(
        "emit-engine-export-job",
        help="Emit a Unity or Unreal engine-bridge export job, provenance template, and cleanup handoff.",
    )
    engine.add_argument("--engine", choices=[kind.value for kind in EngineBridgeKind], required=True)
    engine.add_argument("--pack-id", required=True, help="Pack id to target.")
    engine.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    engine.add_argument("--source-url", required=True, help="Licensed package or product URL.")
    engine.add_argument("--license-note", required=True, help="Short license note to preserve in provenance.")
    engine.add_argument("--source-package-name", default="", help="Optional package name as installed/downloaded.")
    engine.add_argument("--asset-kind", default="prop", help="Cleanup asset kind for export normalization.")
    engine.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Optional output directory for generated engine-bridge artifacts.",
    )

    unity_runner = subparsers.add_parser(
        "emit-unity-export-runner",
        help="Emit a complete Unity export runner with editor launch script, Unity C# exporter, and Blender handoff.",
    )
    unity_runner.add_argument("--pack-id", required=True, help="Pack id to target.")
    unity_runner.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    unity_runner.add_argument("--source-url", required=True, help="Licensed package or product URL.")
    unity_runner.add_argument("--license-note", required=True, help="Short license note to preserve in provenance.")
    unity_runner.add_argument("--project-path", required=True, help="Path to the throwaway Unity project root.")
    unity_runner.add_argument("--package-root", default="Assets", help="Asset root used when asset paths are not specified.")
    unity_runner.add_argument("--asset-path", dest="asset_paths", action="append", default=[], help="Specific Unity asset path to export. May be repeated.")
    unity_runner.add_argument("--unitypackage-path", dest="unitypackage_paths", action="append", default=[], help="Local .unitypackage file to import before export. May be repeated.")
    unity_runner.add_argument("--source-package-name", default="", help="Optional package name as installed/downloaded.")
    unity_runner.add_argument("--asset-kind", default="prop", help="Cleanup asset kind for export normalization.")
    unity_runner.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for generated artifacts.")

    unity_wave = subparsers.add_parser(
        "emit-unity-download-wave",
        help="Parse an approved Unity Asset Store markdown sheet and emit browser intake jobs plus Unity export runners for asset-bearing packs.",
    )
    unity_wave.add_argument("--source-file", type=Path, required=True, help="Markdown file containing approved Unity Asset Store URLs.")
    unity_wave.add_argument("--game-scope", default="arena_shared", help="Game scope for payload output.")
    unity_wave.add_argument(
        "--project-root",
        type=Path,
        default=Path.home() / "Documents" / "Unity AssetBoy",
        help="Root directory for generated throwaway Unity projects.",
    )
    unity_wave.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for generated artifacts.")

    unity_claim_wave = subparsers.add_parser(
        "run-unity-claim-wave",
        help="Run a headless Unity Asset Store claim wave from a generated unity_download_wave.json manifest.",
    )
    unity_claim_wave.add_argument("--wave-json", type=Path, required=True, help="Path to unity_download_wave.json.")
    unity_claim_wave.add_argument("--best-first", action="store_true", help="Only run items marked as Best First Wave.")
    unity_claim_wave.add_argument("--exportable-only", action="store_true", help="Only run exportable asset packs.")
    unity_claim_wave.add_argument("--category", dest="categories", action="append", default=[], help="Filter by category. May be repeated.")
    unity_claim_wave.add_argument("--pack-id", dest="pack_ids", action="append", default=[], help="Filter to specific pack ids. May be repeated.")
    unity_claim_wave.add_argument("--limit", type=int, default=0, help="Optional max number of Unity jobs to run.")
    unity_claim_wave.add_argument("--dry-run", action="store_true", help="Print plans without executing claims.")
    unity_claim_wave.add_argument("--headless", action="store_true", help="Run the Unity claim wave headless.")
    unity_claim_wave.add_argument("--browser-profile-dir", type=Path, default=None, help="Optional shared browser profile directory for Unity claim jobs.")
    unity_claim_wave.add_argument("--timeout-ms", type=int, default=20000, help="Timeout per Playwright action.")
    unity_claim_wave.add_argument("--retries", type=int, default=2, help="Total browser execution attempts per Unity claim job.")
    unity_claim_wave.add_argument(
        "--hydrate-provenance",
        action="store_true",
        help="After successful Unity browser execution, hydrate provenance.json from saved browser artifacts when possible.",
    )
    unity_claim_wave.add_argument(
        "--prepare-pack",
        action="store_true",
        help="After successful hydration, auto-run prepare-pack when provenance and payload files are complete.",
    )
    unity_claim_wave.add_argument(
        "--auto-intake",
        action="store_true",
        help="After claim-wave postprocess succeeds, validate the reviewed packet and write handoff_receipt.json in the same pass.",
    )
    unity_claim_wave.add_argument(
        "--cleanup-mode",
        default="auto",
        choices=["auto", "skip", "force"],
        help="Forwarded to prepare-pack when --prepare-pack is enabled.",
    )
    unity_claim_wave.add_argument("--asset-kind", default="prop", help="Cleanup asset kind when --prepare-pack is enabled.")
    unity_claim_wave.add_argument("--animated", action="store_true", help="Treat Unity claim-wave packs as animated when --prepare-pack is enabled.")
    unity_claim_wave.add_argument("--packet-status", default="ai_reviewed", help="Packet status to write when --prepare-pack is enabled.")
    unity_claim_wave.add_argument("--overwrite-packet", action="store_true", help="Overwrite an existing publish packet when --prepare-pack is enabled.")
    unity_claim_wave.add_argument(
        "--no-verify-hashes",
        dest="verify_hashes",
        action="store_false",
        help="Skip SHA-256 calculation when --prepare-pack is enabled.",
    )
    unity_claim_wave.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Process remaining claim jobs even if one job fails.",
    )
    unity_claim_wave.add_argument(
        "--require-complete",
        action="store_true",
        help="Return non-zero when execution leaves pending manual Unity claim jobs.",
    )
    unity_claim_wave.add_argument(
        "--emit-project-ingest-wave",
        action="store_true",
        help="After the claim wave runs, emit the follow-up Unity project ingest wave manifest with the same filters.",
    )
    unity_claim_wave.add_argument("--project-path", type=Path, default=None, help="Unity project path for --emit-project-ingest-wave.")
    unity_claim_wave.add_argument("--game-scope", default="arena_shared", help="Game scope used by --emit-project-ingest-wave.")
    unity_claim_wave.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for claim-wave reports.")
    unity_claim_wave.add_argument("--json", dest="as_json", action="store_true", help="Print machine-readable claim-wave execution payload.")
    unity_claim_wave.set_defaults(verify_hashes=True)

    unity_hub_status = subparsers.add_parser(
        "unity-hub-status",
        help="Report the current Unity Hub project list, installed Unity editors, and any local Unity Asset Store cache files.",
    )
    unity_hub_status.add_argument("--projects-path", type=Path, default=None, help="Optional override for Unity Hub projects-v1.json.")
    unity_hub_status.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for status reports.")
    unity_owned_map = subparsers.add_parser(
        "map-unity-owned-library",
        help="Read the signed-in Unity Hub token store and map owned Unity Asset Store purchases.",
    )
    unity_owned_map.add_argument("--page-size", type=int, default=200, help="Number of Unity purchases to fetch per page.")
    unity_owned_map.add_argument("--max-pages", type=int, default=5, help="Maximum number of purchase pages to fetch.")
    unity_owned_map.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for the owned-library reports.")
    unity_download_owned = subparsers.add_parser(
        "unity-download-owned",
        help="Direct-download one owned Unity Asset Store package as a .unitypackage using the local Unity Hub session.",
    )
    unity_download_owned.add_argument("--product-id", required=True, help="Unity Asset Store numeric product id.")
    unity_download_owned.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for the downloaded package.")
    unity_download_owned.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds.")
    unity_download_lightweights = subparsers.add_parser(
        "download-unity-owned-lightweights",
        help="Scan the live owned Unity library, estimate package sizes, and direct-download lightweight packages under a chosen max MB threshold.",
    )
    unity_download_lightweights.add_argument("--max-mb", type=float, default=150.0, help="Maximum expected package size in MB to include.")
    unity_download_lightweights.add_argument("--limit", type=int, default=0, help="Optional max number of matching packages to download.")
    unity_download_lightweights.add_argument("--include-hidden", action="store_true", help="Include hidden Unity owned items in the scan.")
    unity_download_lightweights.add_argument("--include-unknown-size", action="store_true", help="Allow downloads even when Unity does not report a package size.")
    unity_download_lightweights.add_argument("--page-size", type=int, default=200, help="Number of Unity purchases to fetch per page.")
    unity_download_lightweights.add_argument("--max-pages", type=int, default=5, help="Maximum number of purchase pages to fetch.")
    unity_download_lightweights.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for lightweight downloads and reports.")
    unity_download_lightweights.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds.")
    unity_download_wave = subparsers.add_parser(
        "download-unity-owned-wave",
        help="Match a generated unity_download_wave.json against the live owned Unity library and direct-download any already-owned packages.",
    )
    unity_download_wave.add_argument("--wave-json", type=Path, required=True, help="Path to unity_download_wave.json.")
    unity_download_wave.add_argument("--best-first", action="store_true", help="Only include Best First Wave Unity items.")
    unity_download_wave.add_argument("--exportable-only", action="store_true", help="Only include exportable asset packs.")
    unity_download_wave.add_argument("--asset-donor-only", action="store_true", help="Only include exportable donor categories like character, animation, environment, audio, and props.")
    unity_download_wave.add_argument("--category", dest="categories", action="append", default=[], help="Filter by category. May be repeated.")
    unity_download_wave.add_argument("--pack-id", dest="pack_ids", action="append", default=[], help="Filter to specific pack ids. May be repeated.")
    unity_download_wave.add_argument("--limit", type=int, default=0, help="Optional max number of Unity jobs to include.")
    unity_download_wave.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for the owned download wave report and package files.")
    unity_download_wave.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout in seconds.")

    unity_project_ingest_wave = subparsers.add_parser(
        "emit-unity-project-ingest-wave",
        help="Emit a Unity project ingest wave that opens claimed Unity Asset Store items into a real Unity project and regenerates export runners against that project.",
    )
    unity_project_ingest_wave.add_argument("--wave-json", type=Path, required=True, help="Path to unity_download_wave.json.")
    unity_project_ingest_wave.add_argument("--project-path", type=Path, default=None, help="Unity project path to use for Package Manager ingest. Defaults to the newest Unity Hub project.")
    unity_project_ingest_wave.add_argument("--game-scope", default="arena_shared", help="Game scope for payload output.")
    unity_project_ingest_wave.add_argument("--best-first", action="store_true", help="Only include Best First Wave Unity items.")
    unity_project_ingest_wave.add_argument("--exportable-only", action="store_true", help="Only include exportable asset packs.")
    unity_project_ingest_wave.add_argument("--category", dest="categories", action="append", default=[], help="Filter by category. May be repeated.")
    unity_project_ingest_wave.add_argument("--pack-id", dest="pack_ids", action="append", default=[], help="Filter to specific pack ids. May be repeated.")
    unity_project_ingest_wave.add_argument("--limit", type=int, default=0, help="Optional max number of Unity jobs to include.")
    unity_project_ingest_wave.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for ingest-wave reports and export runners.")

    unreal_runner = subparsers.add_parser(
        "emit-unreal-export-runner",
        help="Emit a complete Unreal export runner with editor launch script, Unreal Python export script, and Blender handoff.",
    )
    unreal_runner.add_argument("--pack-id", required=True, help="Pack id to target.")
    unreal_runner.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    unreal_runner.add_argument("--source-url", required=True, help="Licensed package or product URL.")
    unreal_runner.add_argument("--license-note", required=True, help="Short license note to preserve in provenance.")
    unreal_runner.add_argument("--project-file", required=True, help="Path to the throwaway Unreal .uproject file.")
    unreal_runner.add_argument("--package-root", default="/Game", help="Package root to enumerate when asset paths are not specified.")
    unreal_runner.add_argument("--asset-path", dest="asset_paths", action="append", default=[], help="Specific Unreal asset path to export. May be repeated.")
    unreal_runner.add_argument("--source-package-name", default="", help="Optional package name as installed/downloaded.")
    unreal_runner.add_argument("--asset-kind", default="prop", help="Cleanup asset kind for export normalization.")
    unreal_runner.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for generated artifacts.")

    fab_auth = subparsers.add_parser("fab-auth", help="Interactive login to Fab.com to save session state for hybrid downloader.")
    fab_auth.add_argument(
        "--reuse-profile",
        action="store_true",
        help="Reuse the existing Fab browser profile and refresh auth_state.json without asking for a fresh login.",
    )
    fab_auth.add_argument(
        "--allow-browser",
        action="store_true",
        help="Explicitly allow AssetBoy to open a visible browser window for Fab login. Omit this to stay in safe no-browser mode.",
    )
    fab_auth.add_argument(
        "--timeout",
        type=float,
        default=12.0,
        help="Timeout in seconds for each Fab browser state capture step.",
    )

    subparsers.add_parser("fab-auth-status", help="Print whether Fab auth_state.json exists and is still authenticated.")

    seed_shared_profile = subparsers.add_parser(
        "seed-shared-browser-profile",
        help="Seed the repo-local shared browser profile from an existing Chrome user-data profile so provider auth can be refreshed without a brand-new login.",
    )
    seed_shared_profile.add_argument(
        "--source-root",
        type=Path,
        default=default_windows_chrome_user_data_dir(),
        help="Chrome user-data root to copy from. Defaults to the standard Windows Chrome profile root.",
    )
    seed_shared_profile.add_argument(
        "--source-profile",
        default="Default",
        help="Source Chrome profile directory name to seed from. Defaults to Default.",
    )
    seed_shared_profile.add_argument(
        "--target-dir",
        type=Path,
        default=default_shared_browser_profile_dir(),
        help="Repo-local shared browser profile target. Defaults to AssetBoy .private/fab_browser_profile.",
    )
    seed_shared_profile.add_argument(
        "--force",
        action="store_true",
        help="Replace the target profile if it already contains data.",
    )
    seed_shared_profile.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be copied without mutating the target profile.",
    )

    mixamo_auth = subparsers.add_parser(
        "mixamo-auth",
        help="Interactive login to Mixamo using the same saved browser profile as Fab.",
    )
    mixamo_auth.add_argument(
        "--reuse-profile",
        action="store_true",
        help="Reuse the existing shared browser profile and refresh mixamo_auth_state.json without asking for a fresh login.",
    )
    mixamo_auth.add_argument(
        "--allow-browser",
        action="store_true",
        help="Explicitly allow AssetBoy to open a visible browser window for Mixamo login. Omit this to stay in safe no-browser mode.",
    )
    mixamo_auth.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Timeout in seconds for each Mixamo browser state capture step.",
    )

    subparsers.add_parser(
        "mixamo-auth-status",
        help="Print whether mixamo_auth_state.json exists and whether Mixamo looked signed in when it was saved.",
    )

    unity_auth = subparsers.add_parser(
        "unity-auth",
        help="Refresh or capture a reusable Unity Asset Store session using the shared browser profile.",
    )
    unity_auth.add_argument(
        "--reuse-profile",
        action="store_true",
        help="Reuse the existing shared browser profile and refresh unity_auth_state.json without asking for a fresh visible login window.",
    )
    unity_auth.add_argument(
        "--allow-browser",
        action="store_true",
        help="Explicitly allow AssetBoy to open one visible Unity login window. Omit this to stay in safe no-browser mode.",
    )
    unity_auth.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Timeout in seconds for Unity session capture.",
    )

    subparsers.add_parser(
        "unity-auth-status",
        help="Print whether unity_auth_state.json exists and whether Unity Asset Store looked signed in when it was saved.",
    )
    
    fab_download = subparsers.add_parser("fab-download", help="Download a Fab asset payload via hybrid Playwright/curl_cffi approach.")
    fab_listing = fab_download.add_mutually_exclusive_group(required=True)
    fab_listing.add_argument("--listing-id", help="Fab listing id (UUID/slug) from /listings/<id>.")
    fab_listing.add_argument("--listing-url", help="Full Fab listing URL (the listing id is parsed automatically).")
    fab_download.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output file path for direct Fab downloads. Unreal-only listings ignore this file and emit Epic acquisition jobs instead.",
    )
    fab_download.add_argument("--pack-id", default=None, help="Optional pack id for Unreal-only Epic acquisition fallback.")
    fab_download.add_argument("--game-scope", default="roman_arena", help="Game scope for Unreal-only Epic acquisition fallback.")
    fab_download.add_argument("--vault-item", default="", help="Optional UEVaultManager vault item hint for Unreal-only fallback.")
    fab_download.add_argument("--engine-association", default="5.3", help="Engine association hint for Unreal-only fallback job emission.")
    fab_download.add_argument("--project-name", default="DummyProject", help="Dummy project name for Unreal-only fallback job emission.")
    fab_download.add_argument("--project-dir", default=None, help="Optional explicit dummy project directory for Unreal-only fallback.")
    fab_download.add_argument("--job-output-dir", type=Path, default=None, help="Optional root directory for emitted Unreal fallback job artifacts.")

    fab_batch = subparsers.add_parser(
        "run-fab-batch",
        help="Process a newline-delimited Fab listing file, download direct assets, and emit deterministic fallback jobs for skipped items.",
    )
    fab_batch.add_argument("--listing-file", type=Path, required=True, help="Text file containing Fab listing ids or URLs, one per line.")
    fab_batch.add_argument("--output-dir", type=Path, default=generated_output_root() / "fab_batch", help="Root output directory for batch downloads and reports.")
    fab_batch.add_argument("--game-scope", default="shared", help="Game scope to use when emitting fallback jobs for skipped listings.")
    fab_batch.add_argument("--engine-association", default="5.3", help="Engine association hint for Unreal-only fallback job emission.")
    fab_batch.add_argument("--project-name", default="DummyProject", help="Dummy project name for Unreal-only fallback job emission.")
    fab_batch.add_argument("--project-dir", default=None, help="Optional explicit dummy project directory for Unreal-only fallback.")

    run_fab_fallback = subparsers.add_parser(
        "run-fab-fallback-actions",
        help="Execute or preview a full fab_batch_fallback_actions.json manifest deterministically.",
    )
    run_fab_fallback.add_argument("--actions-file", type=Path, required=True, help="Path to fab_batch_fallback_actions.json.")
    run_fab_fallback.add_argument("--execute", action="store_true", help="Execute actions; omit to preview plans only.")
    run_fab_fallback.add_argument("--headless", action="store_true", help="Run browser execution headless when --execute is set.")
    run_fab_fallback.add_argument("--browser-profile-dir", type=Path, default=None, help="Optional shared browser profile directory for browser jobs.")
    run_fab_fallback.add_argument("--timeout-ms", type=int, default=15000, help="Timeout per browser action when --execute is set.")
    run_fab_fallback.add_argument("--retries", type=int, default=2, help="Total browser execution attempts per job spec when --execute is set.")
    run_fab_fallback.add_argument("--run-pwsh", action="store_true", help="When --execute is set, run emitted fallback .ps1 scripts (uevault/dummy-project).")
    run_fab_fallback.add_argument(
        "--hydrate-provenance",
        action="store_true",
        help="After a successful browser fallback action, hydrate provenance.json from browser artifacts.",
    )
    run_fab_fallback.add_argument(
        "--prepare-pack",
        action="store_true",
        help="After successful browser fallback hydration, auto-run prepare-pack when provenance and payload files are complete.",
    )
    run_fab_fallback.add_argument(
        "--auto-intake",
        action="store_true",
        help="After fallback postprocess succeeds, validate the reviewed packet and write handoff_receipt.json in the same pass.",
    )
    run_fab_fallback.add_argument(
        "--cleanup-mode",
        default="auto",
        choices=["auto", "skip", "force"],
        help="Forwarded to prepare-pack when --prepare-pack is enabled.",
    )
    run_fab_fallback.add_argument("--asset-kind", default="prop", help="Cleanup asset kind when --prepare-pack is enabled.")
    run_fab_fallback.add_argument("--animated", action="store_true", help="Treat the fallback pack as animated when --prepare-pack is enabled.")
    run_fab_fallback.add_argument("--packet-status", default="ai_reviewed", help="Packet status to write when --prepare-pack is enabled.")
    run_fab_fallback.add_argument("--overwrite-packet", action="store_true", help="Overwrite an existing publish packet when --prepare-pack is enabled.")
    run_fab_fallback.add_argument(
        "--no-verify-hashes",
        dest="verify_hashes",
        action="store_false",
        help="Skip SHA-256 calculation when --prepare-pack is enabled.",
    )
    run_fab_fallback.add_argument("--pwsh-timeout-sec", type=float, default=600.0, help="Timeout for each fallback PowerShell script when --run-pwsh is enabled.")
    run_fab_fallback.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Process remaining actions even if one action fails.",
    )
    run_fab_fallback.add_argument(
        "--require-complete",
        action="store_true",
        help="Return non-zero when execution leaves pending manual steps.",
    )
    run_fab_fallback.add_argument("--json", dest="as_json", action="store_true", help="Print machine-readable execution payload.")
    run_fab_fallback.set_defaults(verify_hashes=True)


    uevault = subparsers.add_parser(
        "emit-uevaultmanager-job",
        help="Emit a launcher-free Fab/Marketplace acquisition job via UEVaultManager.",
    )
    uevault.add_argument("--pack-id", required=True, help="Pack id to target.")
    uevault.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    uevault.add_argument("--source-url", required=True, help="Fab/Marketplace source URL.")
    uevault.add_argument("--vault-item", default="", help="Optional vault item id or name hint.")
    uevault.add_argument("--engine-association", default="5.3", help="Engine association hint for fallback dummy project file.")
    uevault.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    uevault_repair = subparsers.add_parser(
        "uevault-repair-config",
        help="Rewrite AssetBoy's no-browser UEVaultManager config file to a known-good minimal form.",
    )
    uevault_repair.add_argument(
        "--config-path",
        type=Path,
        default=default_uevaultmanager_safe_config_path(),
        help="Safe config path to rewrite.",
    )

    uevault_status = subparsers.add_parser(
        "uevault-status",
        help="Run UEVaultManager status with AssetBoy's safe no-browser wrapper.",
    )
    uevault_status.add_argument("--timeout", type=float, default=120.0, help="Timeout in seconds.")
    uevault_status.add_argument("--online", action="store_true", help="Use normal status instead of --offline.")

    uevault_import = subparsers.add_parser(
        "uevault-import-auth",
        help="Import Epic Launcher auth into UEVaultManager without opening a browser.",
    )
    uevault_import.add_argument("--timeout", type=float, default=120.0, help="Timeout in seconds.")

    uevault_list = subparsers.add_parser(
        "uevault-list-owned",
        help="Write the owned-library JSON using AssetBoy's safe no-browser UEVaultManager wrapper.",
    )
    uevault_list.add_argument(
        "--output",
        type=Path,
        default=generated_output_root() / "uevault_owned_assets.json",
        help="Output JSON file path.",
    )
    uevault_list.add_argument("--force-refresh", action="store_true", help="Ask UEVaultManager to refresh owned metadata before listing.")
    uevault_list.add_argument("--timeout", type=float, default=300.0, help="Timeout in seconds.")

    uevault_install = subparsers.add_parser(
        "uevault-install-owned",
        help="Attempt a no-browser UEVaultManager install/download for one specific owned vault item.",
    )
    uevault_install.add_argument("--vault-item", required=True, help="Vault item title or app name to install.")
    uevault_install.add_argument("--download-dir", type=Path, required=True, help="Raw download target directory.")
    uevault_install.add_argument("--full-install", action="store_true", help="Allow a full install instead of --download-only.")
    uevault_install.add_argument("--timeout", type=float, default=600.0, help="Timeout in seconds.")

    legendary_status = subparsers.add_parser(
        "legendary-status",
        help="Check Legendary path, offline status, and whether Epic RememberMe session data exists.",
    )
    legendary_status.add_argument("--timeout", type=float, default=45.0, help="Timeout in seconds.")

    legendary_import = subparsers.add_parser(
        "legendary-import-auth",
        help="Import Epic Launcher auth into Legendary without opening a browser.",
    )
    legendary_import.add_argument("--timeout", type=float, default=60.0, help="Timeout in seconds.")

    legendary_list = subparsers.add_parser(
        "legendary-list-ue",
        help="List installable Epic/Unreal assets through Legendary and write the raw JSON report.",
    )
    legendary_list.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "legendary_ue",
        help="Directory for the JSON and markdown reports.",
    )
    legendary_list.add_argument("--timeout", type=float, default=120.0, help="Timeout in seconds.")

    legendary_install = subparsers.add_parser(
        "legendary-install-owned",
        help="Download a specific owned Epic/Unreal asset through Legendary without opening a browser.",
    )
    legendary_install.add_argument("--app-name", required=True, help="Legendary app name or title to install.")
    legendary_install.add_argument(
        "--base-path",
        type=Path,
        default=generated_output_root() / "legendary_downloads",
        help="Base directory for downloaded content.",
    )
    legendary_install.add_argument("--timeout", type=float, default=300.0, help="Timeout in seconds.")

    uevault_inventory = subparsers.add_parser(
        "inventory-epic-vault-cache",
        help="Build a local inventory report from the FabLibrary cache database and cached VaultCache content.",
    )
    uevault_inventory.add_argument(
        "--db-path",
        type=Path,
        default=default_local_fab_library_db_path(),
        help="Path to the local FabLibrary SQLite database.",
    )
    uevault_inventory.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "epic_vault_inventory",
        help="Directory for the JSON and markdown reports.",
    )
    uevault_inventory.add_argument(
        "--include-launcher-cache",
        action="store_true",
        help="Also scan Epic launcher Saved/Data cache files for likely library families.",
    )

    launcher_inventory = subparsers.add_parser(
        "inventory-epic-launcher-cache",
        help="Build a likely-owned family report from Epic launcher Saved/Data cache blobs.",
    )
    launcher_inventory.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "epic_launcher_inventory",
        help="Directory for the JSON and markdown reports.",
    )
    launcher_inventory.add_argument(
        "--data-dir",
        type=Path,
        default=default_epic_launcher_saved_data_dir(),
        help="Epic launcher Saved/Data directory to scan.",
    )

    epic_extractor_wave = subparsers.add_parser(
        "emit-epic-cache-extractor-wave",
        help="Emit extractor jobs for cached owned Unreal packs that look 3D-useful.",
    )
    epic_extractor_wave.add_argument(
        "--db-path",
        type=Path,
        default=default_local_fab_library_db_path(),
        help="Path to the local FabLibrary SQLite database.",
    )
    epic_extractor_wave.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "epic_extractors",
        help="Directory for generated extractor jobs.",
    )
    epic_extractor_wave.add_argument(
        "--game-scope",
        default="arena_shared",
        help="Game scope for extractor payload targets.",
    )

    epic_online_map = subparsers.add_parser(
        "map-epic-library",
        help="Use the locally cached Epic launcher auth to build a real online Epic/Fab library map without opening a browser.",
    )
    epic_online_map.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "epic_online_library_map",
        help="Directory for the JSON and markdown reports.",
    )
    epic_online_map.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout in seconds for each Epic API request.",
    )

    fab_online_map = subparsers.add_parser(
        "map-fab-library",
        help="Use the saved Fab auth state to build a real online Fab library map without opening a browser.",
    )
    fab_online_map.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "fab_online_library_map",
        help="Directory for the JSON and markdown reports.",
    )
    fab_online_map.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout in seconds for each Fab API request.",
    )

    quixel_map = subparsers.add_parser(
        "map-quixel-library",
        help="Map local Quixel Bridge / Megascans assets without opening a browser.",
    )
    quixel_map.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "quixel_library_map",
        help="Directory for the JSON and markdown reports.",
    )
    quixel_map.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="Timeout in seconds for Bridge API probes.",
    )
    quixel_map.add_argument(
        "--root",
        dest="quixel_roots",
        action="append",
        default=[],
        help="Optional extra Quixel/Megascans library root. Repeat the flag to add more.",
    )

    combined_map = subparsers.add_parser(
        "map-all-libraries",
        help="Build one combined AssetBoy library map across Fab online, Epic online/local, and Quixel local surfaces.",
    )
    combined_map.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "combined_library_map",
        help="Directory for the JSON and markdown reports.",
    )
    combined_map.add_argument(
        "--db-path",
        type=Path,
        default=default_local_fab_library_db_path(),
        help="Path to the local FabLibrary SQLite database.",
    )
    combined_map.add_argument(
        "--data-dir",
        type=Path,
        default=default_epic_launcher_saved_data_dir(),
        help="Epic launcher Saved/Data directory to scan.",
    )
    combined_map.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout in seconds for Epic/Fab API requests.",
    )
    combined_map.add_argument(
        "--quixel-root",
        dest="quixel_roots",
        action="append",
        default=[],
        help="Optional extra Quixel/Megascans library root. Repeat the flag to add more.",
    )

    dummy_wave = subparsers.add_parser(
        "emit-fab-dummy-project-wave",
        help="Rank owned Unreal-only Fab listings and emit dummy-project jobs for the best extraction candidates.",
    )
    dummy_wave.add_argument("--game-scope", default="arena_shared", help="Game scope for emitted payload targets.")
    dummy_wave.add_argument("--engine-association", default="5.3", help="Engine association for generated dummy projects.")
    dummy_wave.add_argument("--max-jobs", type=int, default=8, help="Maximum number of do-first dummy-project jobs to emit.")
    dummy_wave.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "fab_dummy_project_wave",
        help="Directory for generated dummy-project wave artifacts.",
    )
    arena_wave = subparsers.add_parser(
        "emit-arena-owned-wave",
        help="Map the best owned Fab/Epic assets onto the Roman first-playable arena packs and emit supporting dummy-project jobs.",
    )
    arena_wave.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "arena_owned_wave",
        help="Directory for generated arena-owned wave artifacts.",
    )
    arena_extract = subparsers.add_parser(
        "emit-arena-extraction-wave",
        help="Emit extractor jobs for the arena-owned wave: local cached Unreal packs first, then dummy-project Unreal-only Fab items.",
    )
    arena_extract.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "arena_extraction_wave",
        help="Directory for generated arena extraction wave artifacts.",
    )
    arena_extract.add_argument(
        "--game-scope",
        default="arena_shared",
        help="Game scope for emitted extractor payload targets.",
    )
    useful_harvest = subparsers.add_parser(
        "emit-useful-harvest-wave",
        help="Rank the most useful owned Fab, Epic, and Unity assets into an immediate extract-now wave and next-step queue.",
    )
    useful_harvest.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "useful_harvest_wave",
        help="Directory for generated useful-harvest wave artifacts.",
    )
    useful_donor_export = subparsers.add_parser(
        "emit-useful-donor-export-wave",
        help="Emit cleanup/export job folders for the highest-value harvested Fab and Unity donor files.",
    )
    useful_donor_export.add_argument(
        "--output-dir",
        type=Path,
        default=generated_output_root() / "useful_donor_export_wave",
        help="Directory for generated useful-donor export wave artifacts.",
    )
    useful_donor_export.add_argument(
        "--game-scope",
        default="arena_shared",
        help="Game scope for emitted payload targets.",
    )
    useful_donor_export.add_argument(
        "--project-path",
        type=Path,
        default=Path(r"C:\Users\me\My project (1)"),
        help="Throwaway Unity project path for generated Unity import/export jobs.",
    )

    dummy = subparsers.add_parser(
        "emit-epic-dummy-project",
        aliases=["emit-epic-dummy-project-job"],
        help="Emit a dummy .uproject acquisition job for Epic Launcher without Unreal Engine install.",
    )
    dummy.add_argument("--pack-id", required=True, help="Pack id to target.")
    dummy.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    dummy.add_argument("--source-url", required=True, help="Fab/Marketplace source URL.")
    dummy.add_argument("--engine-association", default="5.3", help="Engine association value for the .uproject.")
    dummy.add_argument("--project-name", default="DummyProject", help="Dummy .uproject file stem.")
    dummy.add_argument("--project-dir", default=None, help="Optional explicit dummy project directory.")
    dummy.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    claim = subparsers.add_parser(
        "emit-marketplace-claim-job",
        help="Emit a free-asset claim automation job for Fab auto-redeemer or Free Games Claimer workflows.",
    )
    claim.add_argument("--method", choices=[item.value for item in ClaimMethod], required=True, help="Claim automation method.")
    claim.add_argument("--pack-id", required=True, help="Pack id to target.")
    claim.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    claim.add_argument("--source-url", default="https://www.fab.com/", help="Source listing URL.")
    claim.add_argument("--target-filter", default="free", help="Target listing filter.")
    claim.add_argument("--account-scope", default="epic_account_primary", help="Account scope label for provenance notes.")
    claim.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    cue4parse = subparsers.add_parser(
        "emit-cue4parse-job",
        help="Emit a CUE4Parse mass-extract job with Blender batch handoff templates.",
    )
    cue4parse.add_argument("--pack-id", required=True, help="Pack id to target.")
    cue4parse.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    cue4parse.add_argument("--source-package-name", required=True, help="Owned/licensed package name.")
    cue4parse.add_argument("--source-url", required=True, help="Store/package source URL.")
    cue4parse.add_argument("--license-note", required=True, help="Short rights note.")
    cue4parse.add_argument("--input-path-hint", required=True, help="Input folder containing Unreal content to parse.")
    cue4parse.add_argument("--mesh-output-format", default="psk", help="Mesh output format hint.")
    cue4parse.add_argument("--asset-kind", default="prop", help="Cleanup asset kind.")
    cue4parse.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    blender_batch = subparsers.add_parser(
        "emit-blender-psk-batch",
        help="Emit a Blender batch conversion job (PSK -> FBX/GLB) for extracted Unreal assets.",
    )
    blender_batch.add_argument("--pack-id", required=True, help="Pack id to target.")
    blender_batch.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    blender_batch.add_argument("--input-dir", required=True, help="Directory containing PSK files.")
    blender_batch.add_argument("--source-format", default="psk", help="Input mesh format.")
    blender_batch.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    browser = subparsers.add_parser(
        "emit-browser-job",
        help="Emit a browser automation bridge job for Fab, Unity Store, Mixamo, or museum flows.",
    )
    browser.add_argument("--source-adapter", required=True, help="Browser/manual adapter id.")
    browser.add_argument("--runtime", choices=[item.value for item in BrowserRuntime], default=BrowserRuntime.PLAYWRIGHT_MCP.value)
    browser.add_argument("--pack-id", required=True, help="Pack id to target.")
    browser.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    browser.add_argument("--source-url", required=True, help="Starting source or listing URL.")
    browser.add_argument("--search-terms", nargs="*", default=[], help="Optional search terms for the browser flow.")
    browser.add_argument("--login-required", action="store_true", help="Mark the source as requiring account login.")
    browser.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    ai = subparsers.add_parser(
        "emit-ai-bridge-job",
        help="Emit an AI bridge job for ChatGPT Pro, Google Pro, Hunyuan Image Colab, MusicGen, AudioLDM2, or ComfyUI local.",
    )
    ai.add_argument("--provider", choices=sorted(AI_PROVIDER_PROFILES.keys()), required=True)
    ai.add_argument("--pack-id", required=True, help="Pack id to target.")
    ai.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    ai.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    chatgpt = subparsers.add_parser(
        "emit-chatgpt-pro-batch",
        help="Emit a ChatGPT Pro image bridge batch with provenance and review checklist.",
    )
    chatgpt.add_argument("--pack-id", default="RA_PACK_UI_COMBAT_SLICE_01", help="Pack id to target.")
    chatgpt.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    chatgpt.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    extractor = subparsers.add_parser(
        "emit-extractor-job",
        help="Emit an extractor bridge job for AssetRipper, AssetStudio, FModel, or Umodel."
    )
    extractor.add_argument("--tool", choices=[item.value for item in ExtractorTool], required=True)
    extractor.add_argument("--pack-id", required=True, help="Pack id to target.")
    extractor.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    extractor.add_argument("--source-package-name", required=True, help="Owned/licensed package name.")
    extractor.add_argument("--source-url", required=True, help="Store, package, or reference URL.")
    extractor.add_argument("--license-note", required=True, help="Short rights note.")
    extractor.add_argument("--input-path-hint", required=True, help="Local input path or package hint.")
    extractor.add_argument("--asset-kind", default="prop", help="Cleanup asset kind.")
    extractor.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")

    # â”€â”€ Prepared / manual execution commands â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    run_hunyuan = subparsers.add_parser(
        "run-hunyuan-batch",
        help="Prepare a Hunyuan3D-2 Colab batch; manual execution happens in colab_exec.",
    )
    run_hunyuan.add_argument("--pack-id", default="RA_PACK_WPN_COMBAT_SLICE_01", help="Pack id to target.")
    run_hunyuan.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    run_hunyuan.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")
    run_hunyuan.add_argument(
        "--drive-folder",
        default=None,
        help="Optional Google Drive folder path for the Colab handoff manifest.",
    )
    run_hunyuan.add_argument("--dry-run", action="store_true", help="Print what would happen without submitting.")

    run_colab = subparsers.add_parser(
        "run-colab-batch",
        help="Prepare an existing prompt_batch.json for Colab; manual execution happens in colab_exec.",
    )
    run_colab.add_argument("--batch-file", type=Path, required=True, help="Path to prompt_batch.json.")
    run_colab.add_argument("--output-dir", type=Path, default=None, help="Optional run output directory.")
    run_colab.add_argument(
        "--drive-folder",
        default=None,
        help="Optional Google Drive folder path for the Colab handoff manifest.",
    )
    run_colab.add_argument("--dry-run", action="store_true", help="Print what would happen without submitting.")

    run_browser = subparsers.add_parser(
        "run-browser-job",
        help="Preview or execute a browser job. Structured Playwright jobs can run with the shared logged-in browser profile.",
    )
    run_browser.add_argument("--job-spec", type=Path, required=True, help="Path to browser_job.json.")
    run_browser.add_argument("--dry-run", action="store_true", help="Print the Playwright step plan without executing.")
    run_browser.add_argument("--execute", action="store_true", help="Execute a structured Playwright job instead of only printing the plan.")
    run_browser.add_argument("--headless", action="store_true", help="Run the real Playwright executor headless.")
    run_browser.add_argument("--browser-profile-dir", type=Path, default=None, help="Optional shared browser profile directory. Defaults to AssetBoy .private/fab_browser_profile.")
    run_browser.add_argument("--timeout-ms", type=int, default=15000, help="Timeout per Playwright action when --execute is used.")
    run_browser.add_argument("--retries", type=int, default=1, help="Total execution attempts when --execute is used (must be >= 1).")
    run_browser.add_argument(
        "--hydrate-provenance",
        action="store_true",
        help="After a successful browser execution, hydrate provenance.json from browser artifacts.",
    )
    run_browser.add_argument(
        "--prepare-pack",
        action="store_true",
        help="After successful hydration, auto-run prepare-pack when provenance and payload files are complete.",
    )
    run_browser.add_argument(
        "--auto-intake",
        action="store_true",
        help="After browser postprocess succeeds, validate the reviewed packet and write handoff_receipt.json in the same pass.",
    )
    run_browser.add_argument(
        "--cleanup-mode",
        default="auto",
        choices=["auto", "skip", "force"],
        help="Forwarded to prepare-pack when --prepare-pack is enabled.",
    )
    run_browser.add_argument("--asset-kind", default="prop", help="Cleanup asset kind when --prepare-pack is enabled.")
    run_browser.add_argument("--animated", action="store_true", help="Treat the browser job pack as animated when --prepare-pack is enabled.")
    run_browser.add_argument("--packet-status", default="ai_reviewed", help="Packet status to write when --prepare-pack is enabled.")
    run_browser.add_argument("--overwrite-packet", action="store_true", help="Overwrite an existing publish packet when --prepare-pack is enabled.")
    run_browser.add_argument(
        "--no-verify-hashes",
        dest="verify_hashes",
        action="store_false",
        help="Skip SHA-256 calculation when --prepare-pack is enabled.",
    )
    run_browser.set_defaults(verify_hashes=True)

    run_blender = subparsers.add_parser(
        "run-blender-cleanup",
        help="Prepare Blender MCP cleanup steps for a pack's raw mesh directory; manual execution happens in Blender MCP.",
    )
    run_blender.add_argument("--pack-id", required=True, help="Pack id to clean up.")
    run_blender.add_argument("--input-dir", required=True, help="Directory containing raw mesh files.")
    run_blender.add_argument("--asset-kind", default="prop", help="Asset kind for export decision.")
    run_blender.add_argument("--animated", action="store_true", help="Mark asset as animated (FBX priority).")
    run_blender.add_argument("--output-dir", type=Path, default=None, help="Optional cleaned output directory.")
    run_blender.add_argument("--dry-run", action="store_true", help="Print the Blender MCP step plan without executing.")

    roman_cleanup = subparsers.add_parser(
        "run-roman-cleanup-wave",
        help="Prepare Blender cleanup plans for the Roman first-playable packs that currently have real 3D inputs.",
    )
    roman_cleanup.add_argument("--game-scope", default="roman_arena", help="Game scope for payload output.")
    roman_cleanup.add_argument(
        "--pack-id",
        dest="pack_ids",
        action="append",
        default=None,
        metavar="PACK_ID",
        help="Optional Roman pack id filter. Repeat to queue multiple specific packs.",
    )
    roman_cleanup.add_argument(
        "--input-root",
        type=Path,
        default=None,
        help="Optional root containing raw pack folders. Checked before the normal Roman manual_drop/publish search paths.",
    )
    roman_cleanup.add_argument("--output-dir", type=Path, default=None, help="Optional output directory for the cleanup wave.")
    roman_cleanup.add_argument("--dry-run", action="store_true", help="Build the cleanup wave manifest without claiming Blender execution.")

    run_local_img = subparsers.add_parser(
        "run-local-image-batch",
        help="Generate UI/icon/HUD images locally using stable-diffusion.cpp (RTX 3050 6GB ready).",
    )
    run_local_img.add_argument("--pack-id", default="RA_PACK_UI_COMBAT_SLICE_01", help="Pack id to target.")
    run_local_img.add_argument("--game-scope", default="roman_arena", help="Game scope for output.")
    run_local_img.add_argument("--prompt", default=None, help="Custom prompt (uses built-in Roman templates if omitted).")
    run_local_img.add_argument("--count", type=int, default=6, help="Number of images to generate.")
    run_local_img.add_argument("--width", type=int, default=512, help="Image width in pixels.")
    run_local_img.add_argument("--height", type=int, default=512, help="Image height in pixels.")
    run_local_img.add_argument("--steps", type=int, default=20, help="Diffusion steps.")
    run_local_img.add_argument("--cfg", type=float, default=7.0, help="CFG scale.")
    run_local_img.add_argument("--model-path", default=None, help="Path to model file (auto-detected if omitted).")
    run_local_img.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")
    run_local_img.add_argument("--dry-run", action="store_true",
                               help="Print what would be generated without calling sd.exe.")
    run_local_img.add_argument("--list-templates", action="store_true",
                               help="List available built-in Roman UI/icon prompt templates.")

    # â”€â”€ Poly Haven (CC0 textures, models, HDRIs) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    run_polyhaven = subparsers.add_parser(
        "run-polyhaven-batch",
        help="Prepare Playwright job specs and step plans for CC0 assets from Poly Haven.",
    )
    run_polyhaven.add_argument("--category", default="textures",
                               choices=["textures", "models", "hdris"],
                               help="Asset category to download.")
    run_polyhaven.add_argument("--search", default="stone",
                               help="Search terms for Poly Haven.")
    run_polyhaven.add_argument("--pack-id", default=None,
                               help="Pack ID for output folder (auto-generated if omitted).")
    run_polyhaven.add_argument("--count", type=int, default=6, help="Number of assets to fetch.")
    run_polyhaven.add_argument("--resolution", default="2k",
                               choices=["1k", "2k", "4k"],
                               help="Download resolution.")
    run_polyhaven.add_argument("--use-presets", action="store_true",
                               help="Run all 9 built-in Roman Arena Poly Haven presets.")
    run_polyhaven.add_argument("--dry-run", action="store_true",
                               help="Print Playwright step plan without executing.")

    # â”€â”€ Mixamo (characters + animations) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    run_mixamo = subparsers.add_parser(
        "run-mixamo-batch",
        help="Prepare Playwright MCP steps to download Mixamo characters or animations.",
    )
    run_mixamo.add_argument("--pack-id", default=None,
                            help="Pack ID (uses preset search if found, else requires --search).")
    run_mixamo.add_argument("--search", default=None,
                            help="Search terms for Mixamo character or animation search.")
    run_mixamo.add_argument("--type", dest="asset_type", default="character",
                            choices=["character", "animation"],
                            help="Asset type to download.")
    run_mixamo.add_argument("--use-presets", action="store_true",
                            help="Run all 7 preset Roman Arena Mixamo jobs (5 chars + 2 anim sets).")
    run_mixamo.add_argument("--output-dir", type=Path, default=None,
                            help="Optional output directory for Mixamo downloads and job specs.")
    run_mixamo.add_argument("--execute", action="store_true",
                            help="Execute the structured Mixamo job(s) immediately with the saved shared browser profile.")
    run_mixamo.add_argument("--headless", action="store_true",
                            help="Run the real Mixamo executor headless when --execute is used.")
    run_mixamo.add_argument("--browser-profile-dir", type=Path, default=None,
                            help="Optional browser profile directory. Defaults to AssetBoy .private/fab_browser_profile.")
    run_mixamo.add_argument("--timeout-ms", type=int, default=15000,
                            help="Timeout per Mixamo Playwright action when --execute is used.")
    run_mixamo.add_argument("--dry-run", action="store_true",
                            help="Print Playwright step plan without executing.")

    # -- Freesound SFX -------------------------------------------------------
    run_freesound = subparsers.add_parser(
        "run-freesound-batch",
        help="Prepare Playwright MCP steps to acquire CC0/CC-BY SFX from Freesound.org.",
    )
    run_freesound.add_argument("--search", default="combat sword metal", help="Search terms.")
    run_freesound.add_argument("--pack-id", default=None, help="Pack ID (auto-generated if omitted).")
    run_freesound.add_argument("--count", type=int, default=10, help="Number of SFX to download.")
    run_freesound.add_argument("--output-dir", type=Path, default=None,
                               help="Optional output directory for Freesound downloads and job specs.")
    run_freesound.add_argument("--use-presets", action="store_true",
                               help="Run all 10 built-in Roman Arena SFX presets.")
    run_freesound.add_argument("--execute", action="store_true",
                               help="Execute the structured Freesound job(s) immediately with the shared browser profile.")
    run_freesound.add_argument("--headless", action="store_true",
                               help="Run the real Freesound executor headless when --execute is used.")
    run_freesound.add_argument("--browser-profile-dir", type=Path, default=None,
                               help="Optional browser profile directory. Defaults to AssetBoy .private/fab_browser_profile.")
    run_freesound.add_argument("--timeout-ms", type=int, default=15000,
                               help="Timeout per Freesound Playwright action when --execute is used.")
    run_freesound.add_argument("--dry-run", action="store_true",
                               help="Print Playwright step plan without executing.")

    # -- Music ---------------------------------------------------------------
    run_music = subparsers.add_parser(
        "run-music-batch",
        help="Prepare music acquisition plans via Suno, Udio (Playwright AI gen), or Mixkit.",
    )
    run_music.add_argument("--source", default="suno",
                           choices=["suno", "udio", "mixkit"],
                           help="Music acquisition source.")
    run_music.add_argument("--prompt", default=None,
                           help="AI generation prompt (for suno/udio).")
    run_music.add_argument("--search", default=None,
                           help="Search terms (for mixkit).")
    run_music.add_argument("--pack-id", default=None, help="Pack ID for output folder.")
    run_music.add_argument("--count", type=int, default=2,
                           help="Number of tracks to download (mixkit only).")
    run_music.add_argument("--output-dir", type=Path, default=None,
                           help="Optional output directory for music downloads and job specs.")
    run_music.add_argument("--use-presets", action="store_true",
                           help="Run all 6 built-in Roman Arena music presets.")
    run_music.add_argument("--execute", action="store_true",
                           help="Execute the structured music job(s) immediately with the shared browser profile.")
    run_music.add_argument("--headless", action="store_true",
                           help="Run the real music executor headless when --execute is used.")
    run_music.add_argument("--browser-profile-dir", type=Path, default=None,
                           help="Optional browser profile directory. Defaults to AssetBoy .private/fab_browser_profile.")
    run_music.add_argument("--timeout-ms", type=int, default=15000,
                           help="Timeout per music Playwright action when --execute is used.")
    run_music.add_argument("--dry-run", action="store_true",
                           help="Print Playwright step plan without executing.")

    # -- Quaternius (CC0 direct-download packs) --------------------------------
    run_quaternius = subparsers.add_parser(
        "run-quaternius-batch",
        help="Download free CC0 low-poly packs from quaternius.com (no Playwright needed).",
    )
    run_quaternius.add_argument("--pack-id", default=None, help="Pack ID (required unless --use-presets).")
    run_quaternius.add_argument("--url", default=None, help="Direct .zip URL or pack page URL.")
    run_quaternius.add_argument("--game-scope", default="shared", help="'shared' for reusable packs.")
    run_quaternius.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")
    run_quaternius.add_argument("--use-presets", action="store_true", help="Run all 5 built-in Roman/shared Quaternius presets.")
    run_quaternius.add_argument("--list-presets", action="store_true", help="List all available Quaternius presets.")
    run_quaternius.add_argument("--dry-run", action="store_true", help="Print what would be downloaded without downloading.")

    # -- Mixamo GLB merger (bpy headless, Flax-native output) ----------------
    run_mix_glb = subparsers.add_parser(
        "run-mixamo-glb-merge",
        help="Merge Mixamo char.fbx + anim FBXs into Flax-ready GLB + per-clip FBX via Blender headless.",
    )
    run_mix_glb.add_argument("--pack-id", required=True, help="Pack ID for output naming.")
    run_mix_glb.add_argument("--char-fbx", required=True, help="Path to character.fbx (with skin, T-pose).")
    run_mix_glb.add_argument("--anim-fbx", dest="anim_fbxs", nargs="+", default=[], metavar="ANIM_FBX", help="Animation FBX files (without skin). Repeat for multiple clips.")
    run_mix_glb.add_argument("--game-scope", default="roman_arena", help="Game scope for provenance.")
    run_mix_glb.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")
    run_mix_glb.add_argument("--blender-exe", default=None, help="Path to blender.exe (auto-detected if omitted).")
    run_mix_glb.add_argument("--dry-run", action="store_true", help="Print the Blender command without executing.")

    # -- ComfyUI Materials ---------------------------------------------------
    run_comfyui = subparsers.add_parser(
        "run-comfyui-batch",
        help="Generate PBR materials/textures locally via ComfyUI (requires ComfyUI running).",
    )
    run_comfyui.add_argument("--prompt", default=None, help="Text prompt for texture generation.")
    run_comfyui.add_argument("--pack-id", default=None, help="Pack ID for output folder.")
    run_comfyui.add_argument("--type", dest="asset_type", default="texture",
                             choices=["texture", "pbr_material"],
                             help="Asset type to generate.")
    run_comfyui.add_argument("--width", type=int, default=1024, help="Output width in pixels.")
    run_comfyui.add_argument("--height", type=int, default=1024, help="Output height in pixels.")
    run_comfyui.add_argument("--steps", type=int, default=25, help="Sampling steps.")
    run_comfyui.add_argument("--cfg", type=float, default=7.0, help="CFG scale.")
    run_comfyui.add_argument("--input-image", default=None, help="Optional input image for img2img.")
    run_comfyui.add_argument("--use-presets", action="store_true",
                             help="Run all 6 built-in Roman material presets.")
    run_comfyui.add_argument("--dry-run", action="store_true",
                             help="Preview workflow without submitting to ComfyUI.")

    run_kenney = subparsers.add_parser(
        "run-kenney-batch",
        help="Download free CC0 packs from Kenney.nl for props, UI, and reusable starter kits.",
    )
    run_kenney.add_argument("--pack-id", default=None, help="Pack ID (required unless --use-presets).")
    run_kenney.add_argument("--url", default=None, help="Direct .zip URL or pack page URL.")
    run_kenney.add_argument("--game-scope", default="shared", help="'shared' for reusable packs.")
    run_kenney.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")
    run_kenney.add_argument("--use-presets", action="store_true", help="Run the built-in Kenney presets.")
    run_kenney.add_argument("--list-presets", action="store_true", help="List available Kenney presets.")
    run_kenney.add_argument("--tags-filter", default=None, help="Comma-separated tag filter for preset selection.")
    run_kenney.add_argument("--dry-run", action="store_true", help="Print what would be downloaded without downloading.")

    run_game_icons = subparsers.add_parser(
        "run-game-icons",
        help="Download CC0 SVG icons from game-icons.net for UI and HUD packs.",
    )
    run_game_icons.add_argument("--game-scope", default="shared", help="'shared' for reusable icon packs.")
    run_game_icons.add_argument("--output-dir", type=Path, default=None, help="Optional output directory.")
    run_game_icons.add_argument("--filter", default=None, help="Optional category filter.")
    run_game_icons.add_argument("--list-categories", action="store_true", help="List available icon categories.")
    run_game_icons.add_argument("--dry-run", action="store_true", help="Print the planned icon download without downloading.")

    run_font = subparsers.add_parser(
        "run-font-batch",
        help="Download OFL/CC0 font packs for UI, HUD, and title typography.",
    )
    run_font.add_argument("--pack-id", default="FONT_CUSTOM", help="Pack ID for the output folder.")
    run_font.add_argument("--url", default=None, help="Direct .ttf/.otf/.zip URL.")
    run_font.add_argument("--game-scope", default="shared", help="'shared' for reusable font packs.")
    run_font.add_argument("--use-presets", action="store_true", help="Run all built-in font presets.")
    run_font.add_argument("--list-presets", action="store_true", help="List available font presets.")
    run_font.add_argument("--tags-filter", nargs="*", default=None, help="Optional tag filter for preset selection.")
    run_font.add_argument("--dry-run", action="store_true", help="Print what would be downloaded without downloading.")

    run_vfx = subparsers.add_parser(
        "run-vfx-batch",
        help="Download CC0 VFX sprite and audio packs from Kenney and print OGA manual targets.",
    )
    run_vfx.add_argument("--pack-id", default="VFX_CUSTOM", help="Pack ID for the output folder.")
    run_vfx.add_argument("--url", default=None, help="Direct .zip URL for a VFX pack.")
    run_vfx.add_argument("--game-scope", default="shared", help="'shared' for reusable VFX packs.")
    run_vfx.add_argument("--use-presets", action="store_true", help="Run all built-in VFX presets.")
    run_vfx.add_argument("--list-presets", action="store_true", help="List available VFX presets.")
    run_vfx.add_argument("--show-oga", action="store_true", help="Print OpenGameArt manual-drop targets.")
    run_vfx.add_argument("--tags-filter", nargs="*", default=None, help="Optional tag filter for preset selection.")
    run_vfx.add_argument("--dry-run", action="store_true", help="Print what would be downloaded without downloading.")

    run_animationgpt = subparsers.add_parser(
        "run-animationgpt",
        help="Prepare an AnimationGPT Colab batch for combat animation generation.",
    )
    run_animationgpt.add_argument("--game-scope", default="roman_arena", help="Game scope for output.")
    run_animationgpt.add_argument("--pack-id", default=None, help="Optional override pack ID.")
    run_animationgpt.add_argument("--use-presets", action="store_true", help="Use the built-in combat prompt presets.")
    run_animationgpt.add_argument("--list-presets", action="store_true", help="List available AnimationGPT presets.")
    run_animationgpt.add_argument("--tags-filter", nargs="*", default=None, help="Optional tag filter for preset selection.")
    run_animationgpt.add_argument("--dry-run", action="store_true", help="Print the planned Colab batch without writing files.")

    run_museum = subparsers.add_parser(
        "run-museum-batch",
        help="Prepare museum/public-domain acquisition targets and provenance stubs.",
    )
    run_museum.add_argument("--game-scope", default="roman_arena", help="Game scope for output.")
    run_museum.add_argument("--use-presets", action="store_true", help="Use the built-in museum presets.")
    run_museum.add_argument("--list-presets", action="store_true", help="List available museum presets.")
    run_museum.add_argument("--tags-filter", nargs="*", default=None, help="Optional tag filter for preset selection.")
    run_museum.add_argument("--dry-run", action="store_true", help="Print the planned museum jobs without writing files.")

    run_vehicle = subparsers.add_parser(
        "run-vehicle-batch",
        help="Download reusable vehicle packs or print the plan for registered vehicle presets.",
    )
    run_vehicle.add_argument("--pack-id", default="VEH_CUSTOM", help="Pack ID for the output folder.")
    run_vehicle.add_argument("--url", default=None, help="Direct .zip URL or pack page URL.")
    run_vehicle.add_argument("--game-scope", default="shared", help="'shared' for reusable vehicle packs.")
    run_vehicle.add_argument("--use-presets", action="store_true", help="Run all built-in vehicle presets.")
    run_vehicle.add_argument("--list-presets", action="store_true", help="List available vehicle presets.")
    run_vehicle.add_argument("--tags-filter", nargs="*", default=None, help="Optional tag filter for preset selection.")
    run_vehicle.add_argument("--dry-run", action="store_true", help="Print what would be downloaded without downloading.")

    run_skybox = subparsers.add_parser(
        "run-skybox-batch",
        help="Prepare Playwright download plans for Poly Haven HDRI skybox presets.",
    )
    run_skybox.add_argument("--count", type=int, default=3, help="Number of assets to fetch per preset.")
    run_skybox.add_argument("--resolution", default="2k", choices=["1k", "2k", "4k"], help="Download resolution.")
    run_skybox.add_argument("--tags-filter", nargs="*", default=None, help="Optional tag filter for preset selection.")
    run_skybox.add_argument("--dry-run", action="store_true", help="Print the planned skybox jobs without executing.")

    run_terrain = subparsers.add_parser(
        "run-terrain-batch",
        help="Prepare Playwright download plans for Poly Haven terrain texture and prop presets.",
    )
    run_terrain.add_argument("--count", type=int, default=3, help="Number of assets to fetch per preset.")
    run_terrain.add_argument("--resolution", default="2k", choices=["1k", "2k", "4k"], help="Download resolution.")
    run_terrain.add_argument("--tags-filter", nargs="*", default=None, help="Optional tag filter for preset selection.")
    run_terrain.add_argument("--dry-run", action="store_true", help="Print the planned terrain jobs without executing.")

    run_dialogue = subparsers.add_parser(
        "run-dialogue-batch",
        help="Generate or preview dialogue audio batches via edge-tts or ElevenLabs.",
    )
    run_dialogue.add_argument("--game-scope", default="roman_arena", help="Game scope for output.")
    run_dialogue.add_argument("--line-id", default="DIA_CUSTOM", help="Line ID for a custom dialogue line.")
    run_dialogue.add_argument("--text", default=None, help="Custom dialogue line text. Uses presets when omitted.")
    run_dialogue.add_argument("--voice", default=None, help="Voice type for preset filtering or single-line generation.")
    run_dialogue.add_argument(
        "--provider",
        default="edge_tts",
        choices=["edge_tts", "elevenlabs"],
        help="Dialogue provider. edge_tts stays as the default fallback; elevenlabs uses env-based API configuration.",
    )
    run_dialogue.add_argument("--audio-class", default="voice_npc", help="Audio class recorded in metadata sidecars.")
    run_dialogue.add_argument("--operator", default=None, help="Optional operator name recorded in dialogue metadata.")
    run_dialogue.add_argument("--list-presets", action="store_true", help="List available dialogue presets.")
    run_dialogue.add_argument("--tags-filter", nargs="*", default=None, help="Optional tag filter for preset selection.")
    run_dialogue.add_argument("--dry-run", action="store_true", help="Preview dialogue generation without synthesizing audio.")


    # â”€â”€ build-dungeon: fire a dungeon grid into a running Flax Editor â”€â”€â”€â”€â”€â”€â”€â”€
    build_dungeon = subparsers.add_parser(
        "build-dungeon",
        help="POST a dungeon grid layout to the FlaxMCP HTTP server to physically spawn it in the Flax Editor.",
    )
    build_dungeon.add_argument(
        "--preset",
        default="colosseum",
        choices=["colosseum", "throne_arena", "temple_pit"],
        help="Which pre-built layout to use (default: colosseum).",
    )
    build_dungeon.add_argument(
        "--name",
        default="RomanArena_GrandColosseum",
        help="Name given to the root EmptyActor spawned in the scene.",
    )
    build_dungeon.add_argument(
        "--tile-size",
        type=float,
        default=200.0,
        dest="tile_size",
        help="World units per grid cell (default: 200).",
    )
    build_dungeon.add_argument(
        "--port",
        type=int,
        default=8080,
        help="FlaxMCP HTTP server port (default: 8080).",
    )

    # ── AI-first publish / intake commands ────────────────────────────────
    check_pub = subparsers.add_parser(
        "check-publish",
        help="Scan publish/flax_intake/ and report status of all packs.",
    )
    check_pub.add_argument(
        "--game",
        default=None,
        metavar="GAME_SCOPE",
        help="Filter by game scope (e.g. roman_arena). Default: all.",
    )
    check_pub.add_argument(
        "--include-examples",
        action="store_true",
        help="Include RA_PACK_EXAMPLE_* packs in the report.",
    )
    check_pub.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON.")

    auto_in = subparsers.add_parser(
        "auto-intake",
        help="Validate all ready packs and print the MCP run_intake calls to execute.",
    )
    auto_in.add_argument("--game", default=None, metavar="GAME_SCOPE")
    auto_in.add_argument("--pack-id", dest="pack_id", default=None, metavar="PACK_ID", help="Target one specific pack.")
    auto_in.add_argument(
        "--include-examples",
        action="store_true",
        help="Include RA_PACK_EXAMPLE_* packs in validation results.",
    )
    auto_in.add_argument("--dry-run", dest="dry_run", action="store_true", help="Validate only; skip writing intake_log.json.")
    auto_in.add_argument("--json", dest="as_json", action="store_true", help="Output results as JSON.")

    write_packet = subparsers.add_parser(
        "write-packet",
        help="Write packet.json and provenance.json for one publish pack.",
    )
    write_packet.add_argument("--pack-id", required=True, help="Pack ID to write.")
    write_packet.add_argument("--game-scope", default="roman_arena", help="Game scope folder.")
    write_packet.add_argument("--payload-dir", type=Path, required=True, help="Payload directory for the pack.")
    write_packet.add_argument("--source-url", required=True, help="Source page or acquisition URL.")
    write_packet.add_argument("--license", required=True, dest="license_name", help="License or rights statement.")
    write_packet.add_argument("--author", required=True, help="Author, vendor, or creator name.")
    write_packet.add_argument("--lane", default="unknown", help="Lane label for provenance.")
    write_packet.add_argument("--notes", default="", help="Extra provenance notes.")
    write_packet.add_argument("--dry-run", action="store_true", help="Preview only; do not write files.")
    write_packet.add_argument(
        "--no-verify-hashes",
        dest="verify_hashes",
        action="store_false",
        help="Skip SHA-256 calculation when building payload_files.",
    )
    write_packet.set_defaults(verify_hashes=True)

    run_bulk = subparsers.add_parser(
        "run-bulk",
        help="Run one pack-centric AssetBoy bulk wave and return machine-readable wrapper output.",
    )
    run_bulk.add_argument(
        "--profile",
        required=True,
        choices=sorted(
            {
                "animationgpt_presets",
                "font_presets",
                "game_icons",
                "kenney_presets",
                "museum_presets",
                "polyhaven_roman",
                "quaternius_presets",
                "skybox_presets",
                "terrain_presets",
                "vehicle_presets",
                "vfx_presets",
            }
        ),
        help="Bulk profile to run.",
    )
    run_bulk.add_argument("--game-scope", default="roman_arena", help="Target game scope for the batch.")
    run_bulk.add_argument("--pack-id", dest="pack_ids", action="append", default=None, help="Optional pack id filter. Repeat to select multiple.")
    run_bulk.add_argument("--tags-filter", nargs="*", default=None, help="Optional tag filter for preset selection.")
    run_bulk.add_argument("--count", type=int, default=3, help="Optional count override for Poly Haven preset waves.")
    run_bulk.add_argument("--resolution", default="2k", choices=["1k", "2k", "4k"], help="Optional resolution override for Poly Haven preset waves.")
    run_bulk.add_argument("--category-filter", default=None, help="Optional category filter for game-icons bulk runs.")
    run_bulk.add_argument("--output-dir", type=Path, default=None, help="Optional output directory root.")
    run_bulk.add_argument("--job-id", default=None, help="Optional external job id for wrapper-side status tracking.")
    run_bulk.add_argument("--dry-run", action="store_true", help="Print the planned wave without downloading or generating files.")
    run_bulk.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Keep a batch wave running and record per-pack failures instead of aborting on the first error.",
    )

    run_cleanup = subparsers.add_parser(
        "run-cleanup",
        help="Run AssetBoy Blender cleanup for one pack and return machine-readable wrapper output.",
    )
    run_cleanup.add_argument("--pack-id", required=True, help="Pack id to clean.")
    run_cleanup.add_argument("--game-scope", default="roman_arena", help="Target game scope for the cleaned pack.")
    run_cleanup.add_argument("--input-dir", type=Path, required=True, help="Source directory to clean.")
    run_cleanup.add_argument("--asset-kind", default="prop", help="Cleanup asset kind profile.")
    run_cleanup.add_argument("--animated", action="store_true", help="Treat the source as animated or rigged.")
    run_cleanup.add_argument("--output-dir", type=Path, default=None, help="Optional cleanup output directory.")
    run_cleanup.add_argument("--job-id", default=None, help="Optional external job id for wrapper-side status tracking.")
    run_cleanup.add_argument("--dry-run", action="store_true", help="Emit the cleanup plan without live execution.")

    prepare_pack = subparsers.add_parser(
        "prepare-pack",
        help="Advance one pack through source -> cleanup -> reviewed-source -> packet using a persistent pack ledger.",
    )
    prepare_pack.add_argument("--pack-id", required=True, help="Target pack id.")
    prepare_pack.add_argument("--game-scope", default="roman_arena", help="Target game scope.")
    prepare_pack.add_argument("--source-dir", type=Path, default=None, help="Existing source folder containing provenance.json and source payload.")
    prepare_pack.add_argument(
        "--bulk-profile",
        default=None,
        choices=sorted(
            {
                "animationgpt_presets",
                "font_presets",
                "game_icons",
                "kenney_presets",
                "museum_presets",
                "polyhaven_roman",
                "quaternius_presets",
                "skybox_presets",
                "terrain_presets",
                "vehicle_presets",
                "vfx_presets",
            }
        ),
        help="Optional bulk profile to source the pack before preparation.",
    )
    prepare_pack.add_argument(
        "--cleanup-mode",
        default="auto",
        choices=["auto", "skip", "force"],
        help="auto = run cleanup only when mesh payloads are present; skip = bypass cleanup; force = always generate cleanup plan.",
    )
    prepare_pack.add_argument("--asset-kind", default="prop", help="Cleanup asset kind profile when cleanup runs.")
    prepare_pack.add_argument("--animated", action="store_true", help="Treat the pack as animated when cleanup runs.")
    prepare_pack.add_argument("--bulk-output-dir", type=Path, default=None, help="Optional output root for bulk-sourced packs.")
    prepare_pack.add_argument("--cleanup-output-dir", type=Path, default=None, help="Optional cleanup output directory.")
    prepare_pack.add_argument("--packet-status", default="ai_reviewed", help="Packet status to write when register-packet runs.")
    prepare_pack.add_argument("--overwrite-packet", action="store_true", help="Overwrite an existing publish packet.")
    prepare_pack.add_argument(
        "--no-verify-hashes",
        dest="verify_hashes",
        action="store_false",
        help="Skip SHA-256 calculation when register-packet runs.",
    )
    prepare_pack.add_argument("--dry-run", action="store_true", help="Plan the flow without writing a publish packet.")
    prepare_pack.add_argument("--resume", action="store_true", help="Resume from the existing pack ledger.")
    prepare_pack.set_defaults(verify_hashes=True)

    pack_status = subparsers.add_parser(
        "pack-status",
        help="Show the persistent AssetBoy pack ledger and current next step for one pack.",
    )
    pack_status.add_argument("--pack-id", required=True, help="Target pack id.")
    pack_status.add_argument("--game-scope", default="roman_arena", help="Target game scope.")

    register_packet = subparsers.add_parser(
        "register-packet",
        help="Promote one AssetBoy output folder into the publish/flax_intake packet contract.",
    )
    register_packet.add_argument("--pack-id", required=True, help="Target pack id.")
    register_packet.add_argument("--game-scope", default="roman_arena", help="Target game scope.")
    register_packet.add_argument("--source-dir", type=Path, required=True, help="Source folder containing payload files and provenance.json.")
    register_packet.add_argument("--overwrite", action="store_true", help="Overwrite an existing publish packet.")
    register_packet.add_argument("--packet-status", default="ai_reviewed", help="Packet status to write into packet.json.")
    register_packet.add_argument(
        "--no-verify-hashes",
        dest="verify_hashes",
        action="store_false",
        help="Skip SHA-256 calculation when building payload_files.",
    )
    register_packet.add_argument("--job-id", default=None, help="Optional external job id for wrapper-side status tracking.")
    register_packet.set_defaults(verify_hashes=True)

    get_job_status = subparsers.add_parser(
        "get-job-status",
        help="Read the latest AssetBoy wrapper job status JSON for one job id.",
    )
    get_job_status.add_argument("--job-id", required=True, help="Job id to inspect.")

    return parser



def _run_status() -> int:
    from assetboy.providers.generator import profile_ids
    from assetboy.providers.unity_runner import list_unity_installations
    from assetboy.providers.unreal_runner import list_unreal_installations

    unity_install_count = len(list_unity_installations())
    unreal_install_count = len(list_unreal_installations())
    print(f"assetboy_root={assetboy_root()}")
    print(f"project_root={project_root()}")
    print(f"asset_library_root={asset_library_root()}")
    print(f"download_queue_csv={download_queue_csv()}")
    print(f"manual_drop_dir={manual_drop_dir()}")
    print(f"state_root={state_root()}")
    print(f"pack_pipeline_root={state_root() / 'pack_pipeline'}")
    print(f"roman_blocker_tasks={roman_blocker_task_path()}")
    print(f"roman_blocker_summary={roman_blocker_summary_path()}")
    print(f"generated_output_root={generated_output_root()}")
    print(f"colab_profiles_dir={colab_profiles_dir()}")
    print(f"colab_profiles={len(profile_ids())}")
    print(f"ai_bridge_profiles={len(AI_PROVIDER_PROFILES)}")
    print(f"unity_installs={unity_install_count}")
    print(f"unreal_installs={unreal_install_count}")
    print(f"bridge_count={len(list_bridges())}")
    print(f"shared_pack_families={len(SHARED_PACK_FAMILIES)}")
    print(f"default_gate_report={_default_gate_path()}")
    print(f"default_catalog={_default_catalog_path()}")
    return 0


def _run_init_library_layout(*, dry_run: bool) -> int:
    created: list[Path] = []
    for path in asset_library_layout_paths():
        if not dry_run:
            ensure_dir(path)
        created.append(path)

    print(f"asset_library_root={asset_library_root()}")
    print(f"dry_run={str(dry_run).lower()}")
    for path in created:
        print(f"layout_path={path}")
    return 0


def _run_smoke_lanes(*, output_dir: Path | None, as_json: bool) -> int:
    from assetboy.execution.blender_runner import run_blender_cleanup
    from assetboy.execution.colab_runner import submit_batch_to_colab
    from assetboy.execution.kenney_runner import KENNEY_PRESETS, run_kenney_batch
    from assetboy.execution.playwright_runner import run_browser_job, run_mixamo_batch
    from assetboy.providers.browser_automation import BrowserRuntime, emit_browser_automation_job
    from assetboy.providers.generator import emit_generator_setup

    root = output_dir if output_dir is not None else generated_output_root() / "lane_smoke"
    ensure_dir(root)
    results: list[dict[str, object]] = []

    def _record(name: str, lane: str, adapter: str, runner) -> None:
        started = perf_counter()
        try:
            data = runner()
            elapsed_ms = round((perf_counter() - started) * 1000, 2)
            results.append(
                {
                    "name": name,
                    "lane": lane,
                    "adapter": adapter,
                    "status": "pass",
                    "elapsed_ms": elapsed_ms,
                    "details": data,
                }
            )
        except Exception as exc:
            elapsed_ms = round((perf_counter() - started) * 1000, 2)
            results.append(
                {
                    "name": name,
                    "lane": lane,
                    "adapter": adapter,
                    "status": "fail",
                    "elapsed_ms": elapsed_ms,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    def _direct_smoke() -> dict[str, object]:
        pack_id, source_url, _, _ = KENNEY_PRESETS[0]
        result = run_kenney_batch(
            pack_id=pack_id,
            source_url=source_url,
            output_dir=root / "direct_url" / pack_id,
            dry_run=True,
        )
        return {
            "pack_id": result.pack_id,
            "source_url": result.source_url,
            "output_dir": str(result.output_dir),
            "dry_run": result.dry_run,
        }

    def _fab_browser_smoke() -> dict[str, object]:
        artifacts = emit_browser_automation_job(
            source_adapter="fab",
            runtime=BrowserRuntime.PLAYWRIGHT_MCP,
            pack_id="SMOKE_FAB_ROMAN_ARENA",
            game_scope="roman_arena",
            source_url="https://www.fab.com/search?q=roman+arena&priceMax=0",
            search_terms=("roman arena modular", "sandstone arena"),
            login_required=True,
            output_dir=root / "manual_browser" / "fab",
            notes=("Smoke test for Fab browser automation.",),
        )
        result = run_browser_job(artifacts.job_spec_path, dry_run=True)
        return {
            "pack_id": result.pack_id,
            "job_spec_path": str(result.job_spec_path),
            "steps": len(result.steps_emitted),
            "destination": str(result.download_target),
            "dry_run": result.dry_run,
        }

    def _mixamo_browser_smoke() -> dict[str, object]:
        results_local = run_mixamo_batch(
            pack_id="RA_PACK_CHR_CORE_SLICE_01",
            search="male fighter humanoid base",
            output_dir=root / "manual_browser" / "mixamo",
            dry_run=True,
        )
        result = results_local[0]
        return {
            "pack_id": result.pack_id,
            "search": result.search,
            "job_spec_path": str(result.job_spec_path) if result.job_spec_path else "",
            "steps": len(result.steps),
            "destination": str(result.download_target),
            "dry_run": result.dry_run,
        }

    def _generator_smoke() -> dict[str, object]:
        artifacts = emit_generator_setup(
            profile_id="hunyuan3d2.production",
            pack_id="RA_PACK_WPN_COMBAT_SLICE_01",
            game_scope="roman_arena",
            output_dir=root / "generator" / "hunyuan3d2",
        )
        result = submit_batch_to_colab(
            batch_path=artifacts.prompt_batch_path,
            output_dir=root / "generator" / "hunyuan3d2" / "colab_run",
            dry_run=True,
        )
        return {
            "profile_id": result.profile_id,
            "pack_id": result.pack_id,
            "batch_path": str(result.batch_path),
            "job_count": result.job_count,
            "output_dir": str(result.output_dir),
            "dry_run": result.dry_run,
        }

    def _blender_smoke() -> dict[str, object]:
        result = run_blender_cleanup(
            pack_id="RA_PACK_WPN_COMBAT_SLICE_01",
            input_dir=publish_payload_dir("roman_arena", "RA_PACK_WPN_COMBAT_SLICE_01").parent,
            asset_kind="weapon",
            source_lane="manual_browser",
            animated=False,
            output_dir=root / "blender" / "weapons",
            dry_run=True,
            quiet=True,
        )
        return {
            "pack_id": result.pack_id,
            "input_dir": str(result.input_dir),
            "output_dir": str(result.output_dir),
            "steps": len(result.steps_run),
            "export_formats": list(result.export_formats),
            "cleanup_plan_path": str(result.cleanup_plan_path) if result.cleanup_plan_path else "",
            "dry_run": result.dry_run,
        }

    _record("kenney_direct", "direct_url", "kenney_direct", _direct_smoke)
    _record("fab_browser", "manual_browser", "fab", _fab_browser_smoke)
    _record("mixamo_browser", "manual_browser", "mixamo_manual_browser", _mixamo_browser_smoke)
    _record("hunyuan_generator", "generator", "hunyuan3d2.production", _generator_smoke)
    _record("blender_handoff", "cleanup", "blender_mcp", _blender_smoke)

    if as_json:
        print(json.dumps({"output_dir": str(root), "results": results}, indent=2))
        return 0

    print(f"lane_smoke_output_dir={root}")
    for result in results:
        print(
            f"{result['name']}: lane={result['lane']} adapter={result['adapter']} "
            f"status={result['status']} elapsed_ms={result['elapsed_ms']}"
        )
        if result["status"] == "fail":
            print(f"  error={result['error']}")
    return 0 if all(item["status"] == "pass" for item in results) else 1


def _run_roman_blockers(gate_path: Path | None, catalog_path: Path | None) -> int:
    resolved_gate, resolved_catalog = _resolve_gate_catalog_paths(gate_path, catalog_path)
    plan = plan_roman_blockers(resolved_gate, resolved_catalog)
    print(format_planned_blockers(plan))
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# AI-first publish / intake helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_example_pack_id(pack_id: str) -> bool:
    return str(pack_id).upper().startswith("RA_PACK_EXAMPLE_")


def _filter_publish_packs(
    packs: list[dict[str, object]],
    *,
    include_examples: bool,
) -> tuple[list[dict[str, object]], int]:
    if include_examples:
        return packs, 0

    filtered = [pack for pack in packs if not _is_example_pack_id(str(pack.get("pack_id", "")))]
    return filtered, len(packs) - len(filtered)


def _run_check_publish(game: str | None, *, as_json: bool, include_examples: bool) -> int:
    from assetboy.library.intake_validator import scan_publish_dir

    packs = scan_publish_dir(game_scope=game)
    packs, omitted_examples = _filter_publish_packs(packs, include_examples=include_examples)
    if not packs:
        msg = "No packs found in publish/flax_intake/"
        if game:
            msg += f" for game '{game}'"
        print(msg)
        return 0

    if as_json:
        print(json.dumps(packs, indent=2))
        return 0

    ok = "Y"
    no = "N"
    header = f"{'GAME':<22} {'PACK_ID':<42} {'STATUS':<16} {'FILES':>5}  PKT  PROV"
    print(header)
    print("-" * len(header))
    missing = 0
    for p in packs:
        pkt  = ok if p["has_packet"]     else no
        prov = ok if p["has_provenance"] else no
        status = p["packet_status"] or "(no packet)"
        print(
            f"{p['game_scope']:<22} {p['pack_id']:<42} {status:<16} "
            f"{p['payload_file_count']:>5}  {pkt}    {prov}"
        )
        if not p["has_packet"]:
            missing += 1
    print()
    print(f"Total: {len(packs)} pack(s).  {missing} missing packet.json.")
    if omitted_examples:
        print(f"Note: omitted {omitted_examples} example pack(s). Use --include-examples to include them.")
    if missing:
        print("Tip: run write-packet to generate missing packet.json files.")
    return 0


def _run_auto_intake(
    game: str | None,
    pack_id_filter: str | None,
    *,
    dry_run: bool,
    as_json: bool,
    include_examples: bool,
) -> int:
    from assetboy.library.intake_validator import scan_publish_dir, validate_packet

    packs = scan_publish_dir(game_scope=game)
    packs, omitted_examples = _filter_publish_packs(packs, include_examples=include_examples)
    if pack_id_filter:
        packs = [p for p in packs if p["pack_id"] == pack_id_filter]

    if not packs:
        print("No packs match the filter.")
        return 0

    results = []
    overall_pass = True
    for p in packs:
        if not p["has_packet"]:
            entry = {
                "pack_id": p["pack_id"],
                "game_scope": p["game_scope"],
                "pass": False,
                "errors": ["packet.json missing - run write-packet first"],
                "warnings": [],
                "mcp_call": None,
            }
            results.append(entry)
            overall_pass = False
            continue

        entry = _auto_intake_result_for_pack(
            pack_id=str(p["pack_id"]),
            game_scope=str(p["game_scope"]),
            validate_packet_fn=validate_packet,
        )
        results.append(entry)
        if not entry.get("pass"):
            overall_pass = False

    persistence: dict[str, object] = {}
    if not dry_run:
        _annotate_intake_results(results)
        persistence = _write_intake_log(results, quiet=as_json)

    if as_json:
        payload = {
            "results": results,
            "log_path": str(persistence.get("log_path", "")).strip(),
            "receipt_paths": [str(path) for path in persistence.get("receipt_paths", [])],
        }
        print(json.dumps(payload, indent=2))
    else:
        if omitted_examples:
            print(f"Note: omitted {omitted_examples} example pack(s). Use --include-examples to include them.")
            print()
        for r in results:
            tag = "PASS" if r["pass"] else "FAIL"
            print(f"[{tag}] {r['game_scope']}/{r['pack_id']}")
            for e in r.get("errors", []):
                print(f"       ERROR: {e}")
            for w in r.get("warnings", []):
                print(f"       WARN:  {w}")
            if r.get("mcp_call"):
                print(f"       MCP:   {r['mcp_call']}")
            if r.get("handoff_receipt_path"):
                print(f"       RECEIPT: {r['handoff_receipt_path']}")
            print()
    return 0 if overall_pass else 1


def _auto_intake_result_for_pack(
    *,
    pack_id: str,
    game_scope: str,
    validate_packet_fn=None,
) -> dict[str, object]:
    if validate_packet_fn is None:
        from assetboy.library.intake_validator import validate_packet as validate_packet_fn

    result = validate_packet_fn(pack_id, game_scope, library_root=asset_library_root())
    mcp_call = None
    if result.pass_:
        mcp_call = f"assetboy_ops run_intake  pack_id={result.pack_id}  game_scope={result.game_scope}"
    return {**result.to_dict(), "mcp_call": mcp_call}


def _auto_intake_one_pack(
    *,
    pack_id: str,
    game_scope: str,
    dry_run: bool = False,
) -> dict[str, object]:
    entry = _auto_intake_result_for_pack(pack_id=pack_id, game_scope=game_scope)
    persistence: dict[str, object] = {}
    if not dry_run:
        _annotate_intake_results([entry])
        persistence = _write_intake_log([entry], quiet=True)

    payload = dict(entry)
    receipt_paths = [str(path) for path in persistence.get("receipt_paths", [])]
    payload["log_path"] = str(persistence.get("log_path", "")).strip()
    payload["receipt_paths"] = receipt_paths
    if receipt_paths and not str(payload.get("handoff_receipt_path", "")).strip():
        payload["handoff_receipt_path"] = receipt_paths[0]
    return payload


def _run_write_packet(
    *,
    pack_id: str,
    game_scope: str,
    payload_dir: Path,
    source_url: str,
    license_name: str,
    author: str,
    lane: str,
    notes: str,
    dry_run: bool,
    verify_hashes: bool,
) -> int:
    from assetboy.library.packet_writer import write_packet

    lane_value = canonical_lane_value(lane)
    packet_path = write_packet(
        pack_id=pack_id,
        game_scope=game_scope,
        payload_dir=payload_dir,
        source_url=source_url,
        license=license_name,
        author=author,
        lane=lane_value,
        source_adapter=_default_source_adapter_for_lane(lane_value),
        notes=notes,
        dry_run=dry_run,
        verify_hashes=verify_hashes,
    )
    print(f"packet_path={packet_path}")
    return 0


def _run_json_wrapper(payload: dict[str, object]) -> int:
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("status") != "failed" else 1


def _publish_pack_dir(*, scope: str, pack_id: str) -> Path:
    return asset_library_root() / "publish" / "flax_intake" / scope / pack_id


def _handoff_receipt_path(*, scope: str, pack_id: str, packet_path: Path | None = None) -> Path:
    if packet_path is not None:
        return packet_path.parent / HANDOFF_RECEIPT_FILENAME
    return _publish_pack_dir(scope=scope, pack_id=pack_id) / HANDOFF_RECEIPT_FILENAME


def _annotate_intake_results(results: list[dict]) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    for entry in results:
        game_scope = str(entry.get("game_scope", "")).strip()
        pack_id = str(entry.get("pack_id", "")).strip()
        if not str(entry.get("logged_at", "")).strip():
            entry["logged_at"] = ts
        entry["status"] = "validated_pending_mcp" if entry.get("pass") else "validation_failed"
        if game_scope and pack_id:
            entry["handoff_receipt_path"] = str(_handoff_receipt_path(scope=game_scope, pack_id=pack_id))


def _write_handoff_receipts(results: list[dict]) -> list[Path]:
    receipt_paths: list[Path] = []
    for entry in results:
        game_scope = str(entry.get("game_scope", "")).strip()
        pack_id = str(entry.get("pack_id", "")).strip()
        if not game_scope or not pack_id:
            continue
        receipt_path = _handoff_receipt_path(scope=game_scope, pack_id=pack_id)
        ensure_dir(receipt_path.parent)
        receipt_payload = {
            "schema_version": HANDOFF_RECEIPT_SCHEMA_VERSION,
            "receipt_kind": "auto_intake",
            "written_at": datetime.now(timezone.utc).isoformat(),
            "logged_at": str(entry.get("logged_at", "")).strip(),
            "pack_id": pack_id,
            "game_scope": game_scope,
            "pass": bool(entry.get("pass")),
            "status": str(entry.get("status", "")).strip(),
            "errors": [str(item) for item in entry.get("errors", []) if str(item).strip()],
            "warnings": [str(item) for item in entry.get("warnings", []) if str(item).strip()],
            "mcp_call": str(entry.get("mcp_call", "")).strip(),
        }
        write_json(receipt_path, receipt_payload)
        entry["handoff_receipt_path"] = str(receipt_path)
        receipt_paths.append(receipt_path)
    return receipt_paths


def _write_intake_log(results: list[dict], *, quiet: bool = False) -> dict[str, object]:
    _annotate_intake_results(results)
    state_dir = state_root()
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = state_dir / "intake_log.json"
    existing: list[dict] = []
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing = []
    existing.extend(results)
    log_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    receipt_paths = _write_handoff_receipts(results)
    if not quiet:
        print(f"[OK] Intake log updated: {log_path}")
        if receipt_paths:
            print(f"[OK] Handoff receipts updated: {len(receipt_paths)}")
    return {"log_path": log_path, "receipt_paths": receipt_paths}


def _read_intake_log_entries() -> list[dict[str, object]]:
    log_path = state_root() / "intake_log.json"
    if not log_path.exists():
        return []
    try:
        payload = json.loads(log_path.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _latest_intake_statuses() -> dict[tuple[str, str], dict[str, object]]:
    latest: dict[tuple[str, str], dict[str, object]] = {}
    for entry in _read_intake_log_entries():
        game_scope = str(entry.get("game_scope", "")).strip()
        pack_id = str(entry.get("pack_id", "")).strip()
        if not game_scope or not pack_id:
            continue
        key = (game_scope, pack_id)
        logged_at = str(entry.get("logged_at", "")).strip()
        previous_logged_at = str(latest.get(key, {}).get("logged_at", "")).strip()
        if previous_logged_at and logged_at and previous_logged_at > logged_at:
            continue
        latest[key] = dict(entry)
    return latest


def _read_handoff_receipt(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return {
            "source": "handoff_receipt_invalid",
            "pass": False,
            "status": "handoff_receipt_invalid",
            "logged_at": "",
            "handoff_receipt_path": str(path),
            "handoff_error": (
                f"handoff receipt '{path}' is malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}."
            ),
        }
    if not isinstance(payload, dict):
        return {
            "source": "handoff_receipt_invalid",
            "pass": False,
            "status": "handoff_receipt_invalid",
            "logged_at": "",
            "handoff_receipt_path": str(path),
            "handoff_error": f"handoff receipt '{path}' must contain a JSON object.",
        }
    receipt = dict(payload)
    receipt["source"] = "handoff_receipt"
    receipt["handoff_receipt_path"] = str(path)
    receipt["handoff_error"] = ""
    return receipt


def _resolve_handoff_status(
    *,
    game_scope: str,
    pack_id: str,
    packet_path: Path | None = None,
    intake_statuses: dict[tuple[str, str], dict[str, object]] | None = None,
) -> dict[str, object]:
    receipt_path = _handoff_receipt_path(scope=game_scope, pack_id=pack_id, packet_path=packet_path)
    receipt = _read_handoff_receipt(receipt_path)
    if receipt:
        return receipt

    statuses = intake_statuses if intake_statuses is not None else _latest_intake_statuses()
    log_entry = dict(statuses.get((game_scope, pack_id), {}))
    if log_entry:
        log_entry["source"] = "intake_log"
        log_entry["handoff_receipt_path"] = str(receipt_path)
        log_entry["handoff_error"] = ""
        return log_entry

    return {
        "source": "missing",
        "pass": False,
        "status": "",
        "logged_at": "",
        "handoff_receipt_path": str(receipt_path),
        "handoff_error": "",
    }





def _run_plan_roman_blockers(
    gate_path: Path | None,
    catalog_path: Path | None,
    task_output: Path,
    summary_output: Path,
) -> int:
    resolved_gate, resolved_catalog = _resolve_gate_catalog_paths(gate_path, catalog_path)
    plan = plan_roman_blockers(resolved_gate, resolved_catalog)
    task_path, summary_path = write_plan_outputs(
        plan,
        task_output_path=task_output,
        summary_output_path=summary_output,
    )
    print(f"task_output={task_path}")
    print(f"summary_output={summary_path}")
    print(f"gate_unresolved_slots={len(plan.gate_report.unresolved_slots)}")
    print(f"blocking_packs={len(plan.blocking_tasks)}")
    print(f"ready_reviewed_packs={len(plan.ready_tasks)}")
    return 0


def _run_emit_roman_execution_kit(
    gate_path: Path | None,
    catalog_path: Path | None,
    browser_runtime: str,
    output_dir: Path | None,
) -> int:
    from assetboy.workflows.execution_kit import emit_roman_execution_kit

    resolved_gate, resolved_catalog = _resolve_gate_catalog_paths(gate_path, catalog_path)
    artifacts = emit_roman_execution_kit(
        gate_path=resolved_gate,
        catalog_path=resolved_catalog,
        browser_runtime=browser_runtime,
        output_dir=output_dir,
    )
    print(f"execution_kit_output_dir={artifacts.output_dir}")
    print(f"execution_kit_manifest={artifacts.manifest_path}")
    if artifacts.queue_template_path is not None:
        print(f"execution_kit_queue_templates={artifacts.queue_template_path}")
    print(f"execution_kit_summary={artifacts.summary_path}")
    return 0


def _run_emit_audio_examples(game_scope: str, output_dir: Path | None) -> int:
    from assetboy.workflows.audio_examples import emit_audio_pipeline_examples

    artifacts = emit_audio_pipeline_examples(game_scope=game_scope, output_dir=output_dir)
    print(f"audio_examples_output_dir={artifacts.output_dir}")
    print(f"audio_examples_queue_template={artifacts.direct_url_queue_template}")
    print(f"audio_examples_manual_job_dir={artifacts.manual_browser_job_dir}")
    print(f"audio_examples_musicgen_job_dir={artifacts.musicgen_job_dir}")
    print(f"audio_examples_audioldm2_job_dir={artifacts.audioldm2_job_dir}")
    return 0


def _run_emit_roman_launcher_manifest(game_scope: str, output_dir: Path | None) -> int:
    from assetboy.workflows.roman_launchers import emit_roman_launcher_manifest

    artifacts = emit_roman_launcher_manifest(game_scope=game_scope, output_dir=output_dir)
    print(f"roman_launchers_output_dir={artifacts.output_dir}")
    print(f"roman_launchers_manifest={artifacts.manifest_path}")
    print(f"roman_launchers_summary={artifacts.summary_path}")
    print(f"roman_launchers_source_manifests_dir={artifacts.source_manifests_dir}")
    return 0


def _run_emit_roman_source_presets(
    game_scope: str,
    output_dir: Path | None,
    launcher_manifest: Path | None,
) -> int:
    from assetboy.workflows.roman_source_presets import emit_roman_source_presets

    artifacts = emit_roman_source_presets(
        game_scope=game_scope,
        output_dir=output_dir,
        launcher_manifest_path=launcher_manifest,
    )
    print(f"roman_source_presets_output_dir={artifacts.output_dir}")
    print(f"roman_source_presets_manifest={artifacts.manifest_path}")
    print(f"roman_source_presets_summary={artifacts.summary_path}")
    return 0


def _run_emit_category_examples(game_scope: str, output_dir: Path | None) -> int:
    from assetboy.workflows.category_examples import emit_category_examples

    artifacts = emit_category_examples(game_scope=game_scope, output_dir=output_dir)
    print(f"category_examples_output_dir={artifacts.output_dir}")
    print(f"category_examples_summary={artifacts.summary_path}")
    return 0


def _run_emit_cleanup_examples(game_scope: str, output_dir: Path | None) -> int:
    from assetboy.workflows.cleanup_examples import emit_cleanup_examples

    artifacts = emit_cleanup_examples(game_scope=game_scope, output_dir=output_dir)
    print(f"cleanup_examples_output_dir={artifacts.output_dir}")
    print(f"cleanup_examples_summary={artifacts.summary_path}")
    return 0


def _run_list_lanes() -> int:
    for lane in ProviderLane:
        policy = LANE_POLICIES[lane]
        print(f"{lane.value}: {policy.description} batchability={lane_batchability_band(lane).value}")
        print(f"  destination={policy.default_destination}")
        for adapter in adapters_for_lane(lane):
            profile_note = f" profile={adapter.default_profile}" if adapter.default_profile else ""
            print(f"  adapter={adapter.adapter_id}{profile_note} :: {adapter.source_strategy}")
    return 0


def _run_list_bridges() -> int:
    for bridge in list_bridges():
        fallbacks = ",".join(bridge.fallback_bridge_ids) if bridge.fallback_bridge_ids else "-"
        skills = ",".join(recommended_skill_ids_for_bridge(bridge.bridge_id))
        print(
            f"{bridge.bridge_id}: family={bridge.family.value} lane={bridge.lane.value} "
            f"batchability={bridge_batchability_band(bridge.bridge_id).value} "
            f"adapter={bridge.adapter_id} categories={','.join(category.value for category in bridge.categories)} "
            f"fallbacks={fallbacks} skills={skills}"
        )
    return 0


def _run_validate_bridges() -> int:
    issues = validate_bridge_registry()
    if issues:
        print(f"bridge_validation=failed")
        print(f"bridge_validation_issue_count={len(issues)}")
        for issue in issues:
            print(f"bridge_validation_issue={issue}")
        return 1

    print("bridge_validation=passed")
    print(f"bridge_count={len(list_bridges())}")
    print(f"category_route_count={len(tuple(AssetCategory))}")
    return 0


def _run_list_provider_runbooks() -> int:
    for provider_id in provider_runbook_ids():
        print(provider_id)
    return 0


def _run_list_unity_installs() -> int:
    from assetboy.providers.unity_runner import list_unity_installations

    installs = list_unity_installations()
    if not installs:
        print("unity_installs=<none>")
        return 0
    for install in installs:
        print(
            f"version={install.version} usable={str(install.usable).lower()} "
            f"root={install.root_dir} editor={install.editor_path or ''}"
        )
    return 0


def _run_list_unreal_installs() -> int:
    from assetboy.providers.unreal_runner import list_unreal_installations

    installs = list_unreal_installations()
    if not installs:
        print("unreal_installs=<none>")
        return 0
    for install in installs:
        print(
            f"version={install.version} usable={str(install.usable).lower()} "
            f"root={install.root_dir} editor_cmd={install.editor_cmd_path or ''} editor_gui={install.editor_gui_path or ''}"
        )
    return 0


def _run_print_provider_runbook(provider_id: str, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(build_provider_runbook_payload(provider_id), indent=2, sort_keys=True))
        return 0
    print(render_provider_runbook(provider_id))
    return 0


def _run_print_provider_readiness(*, as_json: bool, timeout_seconds: float) -> int:
    report = build_provider_readiness_report(timeout_seconds=timeout_seconds)
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    print(render_provider_readiness_report(report))
    return 0


def _run_print_provider_autonomy_deltas(*, as_json: bool, timeout_seconds: float) -> int:
    report = build_provider_autonomy_delta_report(timeout_seconds=timeout_seconds)
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    print(render_provider_autonomy_delta_report(report))
    return 0


def _run_print_category_routing() -> int:
    for category in AssetCategory:
        batchability = category_batchability(category)
        primary = get_bridge(batchability.primary_bridge_id)
        best = get_bridge(batchability.best_bridge_id)
        skills = ",".join(recommended_skill_ids_for_category(category))
        print(
            f"{category.value}: primary={batchability.primary_bridge_id}({primary.lane.value}/{batchability.primary_status.value}) "
            f"best={batchability.best_bridge_id}({best.lane.value}/{batchability.best_status.value}) "
            f"fallbacks={','.join(batchability.route.fallback_bridge_ids)}"
        )
        print(f"  rationale={batchability.route.rationale}")
        print(f"  skills={skills}")
    return 0


def _run_print_batchability(as_json: bool) -> int:
    lane_rows = []
    for lane in ProviderLane:
        adapters = adapters_for_lane(lane)
        lane_rows.append(
            {
                "lane": lane.value,
                "status": lane_batchability_band(lane).value,
                "adapter_count": len(adapters),
                "adapters": [adapter.adapter_id for adapter in adapters],
                "destination": LANE_POLICIES[lane].default_destination,
            }
        )

    category_rows = []
    for category in AssetCategory:
        batchability = category_batchability(category)
        category_rows.append(
            {
                "category": category.value,
                "primary_bridge_id": batchability.primary_bridge_id,
                "primary_status": batchability.primary_status.value,
                "best_bridge_id": batchability.best_bridge_id,
                "best_status": batchability.best_status.value,
                "best_bridge_lane": batchability.best_bridge_lane.value,
                "fallback_bridge_ids": list(batchability.route.fallback_bridge_ids),
                "rationale": batchability.route.rationale,
            }
        )

    summary = {
        "batchable_now": sum(1 for row in category_rows if row["best_status"] == BatchabilityBand.BATCHABLE_NOW.value),
        "batchable_with_manual_steps": sum(
            1 for row in category_rows if row["best_status"] == BatchabilityBand.BATCHABLE_WITH_MANUAL_STEPS.value
        ),
        "manual_gap_fill": sum(1 for row in category_rows if row["best_status"] == BatchabilityBand.MANUAL_GAP_FILL.value),
    }

    if as_json:
        print(
            json.dumps(
                {
                    "summary": summary,
                    "lanes": lane_rows,
                    "categories": category_rows,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print(f"batchability_summary={summary}")
    for row in lane_rows:
        adapters = ",".join(row["adapters"]) if row["adapters"] else "-"
        print(
            f"lane={row['lane']} status={row['status']} adapters={row['adapter_count']} "
            f"destination={row['destination']} adapter_ids={adapters}"
        )
    for row in category_rows:
        fallbacks = ",".join(row["fallback_bridge_ids"]) if row["fallback_bridge_ids"] else "-"
        print(
            f"category={row['category']} primary={row['primary_bridge_id']}({row['primary_status']}) "
            f"best={row['best_bridge_id']}({row['best_status']}/{row['best_bridge_lane']}) fallbacks={fallbacks}"
        )
    return 0


def _run_print_pack_targets(gate_path: Path | None, catalog_path: Path | None) -> int:
    resolved_gate, resolved_catalog = _resolve_gate_catalog_paths(gate_path, catalog_path)
    plan = plan_roman_blockers(resolved_gate, resolved_catalog)
    for task in plan.tasks:
        print(
            f"{plan.game_scope}/{task.pack_id}: lane={task.lane.value} "
            f"maturity={task.user_maturity_label} status={task.audit_status} "
            f"acquisition={task.acquisition_target} payload={task.payload_target}"
        )
    for pack_id, target in shared_pack_targets().items():
        print(f"shared/{pack_id}: lane=shared_pack payload={target}")
    return 0


def _find_publish_contract_for_aliases(
    *,
    aliases: tuple[str, ...],
    scopes: tuple[str, ...] = SHARED_PUBLISH_SCOPES,
) -> tuple[str, str, Path] | None:
    library_root = asset_library_root()
    for scope in scopes:
        for pack_id in aliases:
            packet_path = library_root / "publish" / "flax_intake" / scope / pack_id / "packet.json"
            provenance_path = packet_path.parent / "provenance.json"
            payload_dir = packet_path.parent / "payload"
            if packet_path.exists() and provenance_path.exists() and payload_dir.is_dir():
                return scope, pack_id, packet_path
    return None


def _shared_pack_readiness_rows() -> list[dict[str, object]]:
    imported_root = imported_packs_dir()
    intake_statuses = _latest_intake_statuses()
    rows: list[dict[str, object]] = []

    for canonical_pack_id, aliases in PRIORITY_SHARED_PACK_ALIASES.items():
        match = _find_publish_contract_for_aliases(aliases=aliases)
        imported = any((imported_root / alias).exists() for alias in aliases)
        lane = PRIORITY_SHARED_LANES.get(canonical_pack_id, "shared_pack")

        if match is None:
            state = "imported" if imported else "blocked"
            rows.append(
                {
                    "group": "shared_priority",
                    "pack_id": canonical_pack_id,
                    "alias_pack_ids": list(aliases),
                    "lane": lane,
                    "state": state,
                    "ready_reviewed": False,
                    "imported": imported,
                    "gate_pass": False,
                    "intake_validated": False,
                    "intake_status": "",
                    "intake_logged_at": "",
                    "handoff_source": "missing",
                    "handoff_receipt_path": str(_handoff_receipt_path(scope="shared", pack_id=canonical_pack_id)),
                    "handoff_error": "",
                    "scope": "",
                    "source_pack_id": "",
                    "packet_path": "",
                    "reason": "publish packet contract missing",
                }
            )
            continue

        scope, source_pack_id, packet_path = match
        validation = validate_packet(
            source_pack_id,
            scope,
            packet_path=packet_path,
            library_root=asset_library_root(),
        )
        ready_reviewed = validation.pass_
        intake_entry = _resolve_handoff_status(
            game_scope=scope,
            pack_id=source_pack_id,
            packet_path=packet_path,
            intake_statuses=intake_statuses,
        )
        intake_validated = bool(intake_entry.get("pass"))
        intake_status = str(intake_entry.get("status", "")).strip()
        intake_logged_at = str(intake_entry.get("logged_at", "")).strip()
        handoff_source = str(intake_entry.get("source", "")).strip()
        handoff_receipt_path = str(intake_entry.get("handoff_receipt_path", "")).strip()
        handoff_error = str(intake_entry.get("handoff_error", "")).strip()
        gate_pass = ready_reviewed and imported and intake_validated
        if gate_pass:
            state = "gate_pass"
        elif imported:
            state = "imported"
        elif ready_reviewed:
            state = "ready_reviewed"
        else:
            state = "blocked"
        if gate_pass:
            reason = ""
        elif handoff_error:
            reason = handoff_error
        elif not validation.pass_:
            reason = "; ".join(validation.errors[:3]) or "packet validation failed"
        elif not imported:
            reason = "awaiting Flax import"
        else:
            reason = "awaiting durable auto-intake handoff receipt"

        rows.append(
            {
                "group": "shared_priority",
                "pack_id": canonical_pack_id,
                "alias_pack_ids": list(aliases),
                "lane": lane,
                "state": state,
                "ready_reviewed": ready_reviewed,
                "imported": imported,
                "gate_pass": gate_pass,
                "intake_validated": intake_validated,
                "intake_status": intake_status,
                "intake_logged_at": intake_logged_at,
                "handoff_source": handoff_source,
                "handoff_receipt_path": handoff_receipt_path,
                "handoff_error": handoff_error,
                "scope": scope,
                "source_pack_id": source_pack_id,
                "packet_path": str(packet_path),
                "reason": reason,
            }
        )

    return rows


def _build_pack_readiness_summary(rows: list[dict[str, object]]) -> dict[str, int]:
    return {
        "total": len(rows),
        "blocked": sum(1 for row in rows if row["state"] == "blocked"),
        "ready_reviewed": sum(1 for row in rows if row["state"] == "ready_reviewed"),
        "imported": sum(1 for row in rows if row["state"] == "imported"),
        "gate_pass": sum(1 for row in rows if row["state"] == "gate_pass"),
        "import_pending": sum(1 for row in rows if row["import_pending"]),
    }


def _build_pack_readiness_group_summary(rows: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        group = str(row.get("group", "")).strip() or "unknown"
        grouped.setdefault(group, []).append(row)
    return {
        group: _build_pack_readiness_summary(group_rows)
        for group, group_rows in sorted(grouped.items())
    }


def _run_print_pack_readiness(
    gate_path: Path | None,
    catalog_path: Path | None,
    *,
    as_json: bool,
    states: list[str] | None = None,
    groups: list[str] | None = None,
    import_pending_only: bool = False,
) -> int:
    selected_states = tuple(dict.fromkeys(str(item).strip() for item in (states or []) if str(item).strip()))
    selected_groups = tuple(dict.fromkeys(str(item).strip() for item in (groups or []) if str(item).strip()))
    selected_state_set = set(selected_states)
    selected_group_set = set(selected_groups)
    include_roman = not selected_group_set or "roman_arena" in selected_group_set

    resolved_gate: Path | None = None
    resolved_catalog: Path | None = None
    roman_plan = None
    roman_plan_error = ""
    if include_roman:
        resolved_gate, resolved_catalog = _resolve_gate_catalog_paths(gate_path, catalog_path)
        try:
            roman_plan = plan_roman_blockers(resolved_gate, resolved_catalog)
        except FileNotFoundError as exc:
            roman_plan_error = str(exc)

    intake_statuses = _latest_intake_statuses()
    rows: list[dict[str, object]] = []

    if roman_plan is not None:
        roman_gate_pass = bool(roman_plan.gate_report.pass_state)
        for task in roman_plan.tasks:
            ready_reviewed = bool(task.ready_for_flax_packet)
            imported = bool(task.imported_into_flax)
            intake_entry = _resolve_handoff_status(
                game_scope=roman_plan.game_scope,
                pack_id=task.pack_id,
                intake_statuses=intake_statuses,
            )
            intake_validated = bool(intake_entry.get("pass"))
            intake_status = str(intake_entry.get("status", "")).strip()
            intake_logged_at = str(intake_entry.get("logged_at", "")).strip()
            handoff_source = str(intake_entry.get("source", "")).strip()
            handoff_receipt_path = str(intake_entry.get("handoff_receipt_path", "")).strip()
            handoff_error = str(intake_entry.get("handoff_error", "")).strip()
            gate_pass = roman_gate_pass and imported and intake_validated
            import_pending = ready_reviewed and not imported and not gate_pass
            if gate_pass:
                state = "gate_pass"
            elif imported:
                state = "imported"
            elif ready_reviewed:
                state = "ready_reviewed"
            else:
                state = "blocked"
            findings = "; ".join(task.audit_findings[:3]) if task.audit_findings else ""
            if gate_pass:
                reason = ""
            elif handoff_error:
                reason = handoff_error
            elif imported and not intake_validated:
                reason = "awaiting durable auto-intake handoff receipt"
            else:
                reason = findings
            rows.append(
                {
                    "group": "roman_arena",
                    "pack_id": task.pack_id,
                    "lane": task.lane.value,
                    "state": state,
                    "ready_reviewed": ready_reviewed,
                    "imported": imported,
                    "gate_pass": gate_pass,
                    "intake_validated": intake_validated,
                    "intake_status": intake_status,
                    "intake_logged_at": intake_logged_at,
                    "handoff_source": handoff_source,
                    "handoff_receipt_path": handoff_receipt_path,
                    "handoff_error": handoff_error,
                    "import_pending": import_pending,
                    "scope": roman_plan.game_scope,
                    "source_pack_id": task.pack_id,
                    "packet_path": "",
                    "reason": reason,
                }
            )

    for shared_row in _shared_pack_readiness_rows():
        normalized_shared_row = dict(shared_row)
        normalized_shared_row["import_pending"] = bool(
            normalized_shared_row.get("ready_reviewed")
            and not normalized_shared_row.get("imported")
            and not normalized_shared_row.get("gate_pass")
        )
        rows.append(normalized_shared_row)

    all_summary = _build_pack_readiness_summary(rows)
    all_summary_by_group = _build_pack_readiness_group_summary(rows)
    filtered_rows = rows
    if selected_state_set:
        filtered_rows = [row for row in filtered_rows if row["state"] in selected_state_set]
    if selected_group_set:
        filtered_rows = [row for row in filtered_rows if row["group"] in selected_group_set]
    if import_pending_only:
        filtered_rows = [row for row in filtered_rows if row["import_pending"]]

    summary = _build_pack_readiness_summary(filtered_rows)
    summary_by_group = _build_pack_readiness_group_summary(filtered_rows)

    if as_json:
        print(
            json.dumps(
                {
                    "gate_path": str(resolved_gate) if resolved_gate is not None else None,
                    "catalog_path": str(resolved_catalog) if resolved_catalog is not None else None,
                    "roman_plan_error": roman_plan_error or None,
                    "filters": {
                        "states": list(selected_states),
                        "groups": list(selected_groups),
                        "import_pending_only": import_pending_only,
                    },
                    "all_summary": all_summary,
                    "all_summary_by_group": all_summary_by_group,
                    "summary": summary,
                    "summary_by_group": summary_by_group,
                    "rows": filtered_rows,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print(f"pack_readiness_total={summary['total']}")
    print(f"pack_readiness_blocked={summary['blocked']}")
    print(f"pack_readiness_ready_reviewed={summary['ready_reviewed']}")
    print(f"pack_readiness_imported={summary['imported']}")
    print(f"pack_readiness_gate_pass={summary['gate_pass']}")
    print(f"pack_readiness_import_pending={summary['import_pending']}")
    for group, group_summary in summary_by_group.items():
        print(f"pack_readiness_group_{group}_total={group_summary['total']}")
        print(f"pack_readiness_group_{group}_blocked={group_summary['blocked']}")
        print(f"pack_readiness_group_{group}_ready_reviewed={group_summary['ready_reviewed']}")
        print(f"pack_readiness_group_{group}_imported={group_summary['imported']}")
        print(f"pack_readiness_group_{group}_gate_pass={group_summary['gate_pass']}")
        print(f"pack_readiness_group_{group}_import_pending={group_summary['import_pending']}")
    if selected_state_set or selected_group_set or import_pending_only:
        print(f"pack_readiness_all_total={all_summary['total']}")
        print(f"pack_readiness_filter_states={','.join(selected_states) if selected_states else 'all'}")
        print(f"pack_readiness_filter_groups={','.join(selected_groups) if selected_groups else 'all'}")
        print(f"pack_readiness_filter_import_pending_only={str(import_pending_only).lower()}")
    if roman_plan_error:
        print(f"pack_readiness_roman_plan_error={roman_plan_error}")
    for row in filtered_rows:
        print(
            f"{row['group']}/{row['pack_id']}: state={row['state']} lane={row['lane']} "
            f"ready_reviewed={str(bool(row['ready_reviewed'])).lower()} "
            f"imported={str(bool(row['imported'])).lower()} "
            f"gate_pass={str(bool(row['gate_pass'])).lower()} "
            f"intake_validated={str(bool(row.get('intake_validated'))).lower()} "
            f"intake_status={row.get('intake_status', '')} "
            f"handoff_source={row.get('handoff_source', '')} "
            f"import_pending={str(bool(row['import_pending'])).lower()} "
            f"scope={row['scope']} source_pack={row['source_pack_id']} "
            f"reason={row['reason']}"
        )
    return 0


def _shared_publish_paths(*, scope: str, pack_id: str) -> tuple[Path, Path, Path]:
    base = asset_library_root() / "publish" / "flax_intake" / scope / pack_id
    return base / "packet.json", base / "provenance.json", base / "payload"


def _default_source_adapter_for_lane(lane: str) -> str:
    lane_enum = ProviderLane(lane)
    adapters = adapters_for_lane(lane_enum)
    if not adapters:
        raise ValueError(f"No adapters registered for lane '{lane}'.")
    return adapters[0].adapter_id


def _resolve_shared_priority_selection(pack_ids: list[str] | None) -> tuple[list[str], list[str]]:
    if not pack_ids:
        return list(PRIORITY_SHARED_PACK_ALIASES.keys()), []

    alias_map: dict[str, str] = {}
    for canonical_pack_id, aliases in PRIORITY_SHARED_PACK_ALIASES.items():
        alias_map[canonical_pack_id.upper()] = canonical_pack_id
        for alias in aliases:
            alias_map[str(alias).upper()] = canonical_pack_id

    selected: list[str] = []
    selected_set: set[str] = set()
    unknown: list[str] = []
    for token in pack_ids:
        raw = str(token).strip()
        if not raw:
            continue
        canonical_pack_id = alias_map.get(raw.upper())
        if not canonical_pack_id:
            unknown.append(raw)
            continue
        if canonical_pack_id in selected_set:
            continue
        selected_set.add(canonical_pack_id)
        selected.append(canonical_pack_id)
    return selected, unknown


def _locate_shared_priority_source(
    *,
    canonical_pack_id: str,
    target_scope: str,
) -> dict[str, object] | None:
    aliases = PRIORITY_SHARED_PACK_ALIASES.get(canonical_pack_id, (canonical_pack_id,))
    scope_candidates: list[str] = []
    for scope in (target_scope, *SHARED_PUBLISH_SCOPES):
        normalized = str(scope).strip()
        if not normalized or normalized in scope_candidates:
            continue
        scope_candidates.append(normalized)

    for scope in scope_candidates:
        for candidate_pack_id in aliases:
            packet_path, provenance_path, payload_dir = _shared_publish_paths(scope=scope, pack_id=candidate_pack_id)
            if packet_path.exists() and provenance_path.exists() and payload_dir.is_dir():
                return {
                    "scope": scope,
                    "pack_id": candidate_pack_id,
                    "packet_path": packet_path,
                    "provenance_path": provenance_path,
                    "payload_dir": payload_dir,
                    "origin": "existing_contract",
                }

    for scope, source_pack_id in PRIORITY_SHARED_BOOTSTRAP_SOURCES.get(canonical_pack_id, ()):
        packet_path, provenance_path, payload_dir = _shared_publish_paths(scope=scope, pack_id=source_pack_id)
        if packet_path.exists() and provenance_path.exists() and payload_dir.is_dir():
            return {
                "scope": scope,
                "pack_id": source_pack_id,
                "packet_path": packet_path,
                "provenance_path": provenance_path,
                "payload_dir": payload_dir,
                "origin": "bootstrap_source",
            }

    return None


def _run_sync_shared_priority(
    *,
    target_scope: str,
    pack_ids: list[str] | None,
    dry_run: bool,
    as_json: bool,
) -> int:
    resolved_target_scope = str(target_scope or "shared").strip() or "shared"
    library_root = asset_library_root()
    selected_pack_ids, unknown_pack_ids = _resolve_shared_priority_selection(pack_ids)

    results: list[dict[str, object]] = []
    failed = 0

    for token in unknown_pack_ids:
        failed += 1
        results.append(
            {
                "pack_id": token,
                "status": "failed",
                "action": "none",
                "reason": "unknown shared priority pack id",
                "target_scope": resolved_target_scope,
            }
        )

    for target_pack_id in selected_pack_ids:
        target_packet_path, target_provenance_path, target_payload_dir = _shared_publish_paths(
            scope=resolved_target_scope,
            pack_id=target_pack_id,
        )
        target_exists = target_packet_path.exists() and target_provenance_path.exists()

        source = _locate_shared_priority_source(
            canonical_pack_id=target_pack_id,
            target_scope=resolved_target_scope,
        )
        if source is None:
            failed += 1
            results.append(
                {
                    "pack_id": target_pack_id,
                    "status": "failed",
                    "action": "none",
                    "reason": "no source contract found in aliases or bootstrap sources",
                    "target_scope": resolved_target_scope,
                }
            )
            continue

        source_packet = json.loads(Path(source["packet_path"]).read_text(encoding="utf-8-sig"))
        source_provenance = json.loads(Path(source["provenance_path"]).read_text(encoding="utf-8-sig"))
        source_payload_dir = Path(source["payload_dir"])

        lane_hint = (
            str(source_packet.get("lane", "")).strip()
            or str(source_provenance.get("lane", "")).strip()
            or PRIORITY_SHARED_LANES.get(target_pack_id, "manual_browser")
        )
        try:
            lane_value = canonical_lane_value(lane_hint)
        except ValueError as exc:
            failed += 1
            results.append(
                {
                    "pack_id": target_pack_id,
                    "status": "failed",
                    "action": "normalize",
                    "reason": str(exc),
                    "target_scope": resolved_target_scope,
                    "source_scope": source.get("scope", ""),
                    "source_pack_id": source.get("pack_id", ""),
                }
            )
            continue

        warnings: list[str] = []
        adapter_hint = canonical_source_adapter_id(str(source_provenance.get("source_adapter", "")))
        source_adapter = adapter_hint
        if source_adapter:
            try:
                adapter_record = require_source_adapter(source_adapter)
                if adapter_record.lane.value != lane_value:
                    warnings.append(
                        f"source_adapter '{source_adapter}' maps to lane '{adapter_record.lane.value}', using lane default."
                    )
                    source_adapter = ""
            except ValueError:
                warnings.append(f"source_adapter '{adapter_hint}' unsupported, using lane default.")
                source_adapter = ""
        if not source_adapter:
            source_adapter = _default_source_adapter_for_lane(lane_value)

        payload_manifest: list[dict[str, object]] = []
        if source_payload_dir.is_dir():
            payload_manifest = build_payload_manifest(source_payload_dir, verify_hashes=True)
        if not payload_manifest and not target_exists:
            failed += 1
            results.append(
                {
                    "pack_id": target_pack_id,
                    "status": "failed",
                    "action": "bootstrap",
                    "reason": "source payload does not contain supported files for bootstrap",
                    "target_scope": resolved_target_scope,
                    "source_scope": source.get("scope", ""),
                    "source_pack_id": source.get("pack_id", ""),
                }
            )
            continue

        source_payload_files = source_packet.get("payload_files")
        if not isinstance(source_payload_files, list):
            source_payload_files = []
        final_payload_files = payload_manifest if payload_manifest else source_payload_files

        packet_payload: dict[str, object] = {
            "pack_id": target_pack_id,
            "game_scope": resolved_target_scope,
            "packet_status": str(source_packet.get("packet_status", "ai_reviewed")).strip() or "ai_reviewed",
            "lane": lane_value,
            "payload_path": "payload",
            "payload_files": final_payload_files,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        provenance_payload = canonicalize_provenance_payload(source_provenance, keep_extra=True)
        provenance_payload["pack_id"] = target_pack_id
        provenance_payload["game_scope"] = resolved_target_scope
        provenance_payload["lane"] = lane_value
        provenance_payload["source_adapter"] = source_adapter
        provenance_payload["payload_target_path"] = str(target_payload_dir)
        if not str(provenance_payload.get("acquired_at", "")).strip():
            provenance_payload["acquired_at"] = datetime.now(timezone.utc).isoformat()
        if not str(provenance_payload.get("downloaded_filename", "")).strip():
            if payload_manifest:
                provenance_payload["downloaded_filename"] = str(payload_manifest[0].get("relative_pack_path", ""))
            elif source_payload_files:
                first = source_payload_files[0]
                if isinstance(first, dict):
                    provenance_payload["downloaded_filename"] = str(
                        first.get("relative_pack_path") or first.get("published_relative_path") or ""
                    )
            if not str(provenance_payload.get("downloaded_filename", "")).strip() and lane_value in {"direct_url", "manual_browser"}:
                provenance_payload["downloaded_filename"] = f"{target_pack_id.lower()}_registration_only"
                warnings.append("downloaded_filename missing; wrote deterministic registration marker.")
        if not str(provenance_payload.get("license_snapshot", "")).strip() and str(provenance_payload.get("license", "")).strip():
            provenance_payload["license_snapshot"] = str(provenance_payload["license"])

        _, provenance_errors, provenance_warnings = validate_provenance_payload(
            provenance_payload,
            expected_lane=lane_value,
            expected_payload_target_path=target_payload_dir,
        )
        warnings.extend(provenance_warnings)
        if provenance_errors:
            failed += 1
            results.append(
                {
                    "pack_id": target_pack_id,
                    "status": "failed",
                    "action": "normalize",
                    "reason": "; ".join(provenance_errors),
                    "target_scope": resolved_target_scope,
                    "source_scope": source.get("scope", ""),
                    "source_pack_id": source.get("pack_id", ""),
                    "warnings": warnings,
                }
            )
            continue

        if not dry_run:
            ensure_dir(target_payload_dir)
            source_payload_resolved = source_payload_dir.resolve()
            target_payload_resolved = target_payload_dir.resolve()
            if source_payload_resolved != target_payload_resolved and source_payload_dir.is_dir():
                if target_payload_dir.exists():
                    shutil.rmtree(target_payload_dir)
                shutil.copytree(source_payload_dir, target_payload_dir)
            write_json(target_packet_path, packet_payload)
            write_json(target_provenance_path, provenance_payload)

        validation_pass = True
        validation_errors: list[str] = []
        validation_warnings: list[str] = []
        if not dry_run:
            validation = validate_packet(
                target_pack_id,
                resolved_target_scope,
                packet_path=target_packet_path,
                library_root=library_root,
            )
            validation_pass = validation.pass_
            validation_errors = validation.errors
            validation_warnings = validation.warnings
            if not validation_pass:
                failed += 1

        status = "repaired_existing" if target_exists else "bootstrapped"
        if dry_run:
            status = "planned_repair" if target_exists else "planned_bootstrap"
        if not validation_pass:
            status = "failed"

        results.append(
            {
                "pack_id": target_pack_id,
                "status": status,
                "action": "repair" if target_exists else "bootstrap",
                "reason": "",
                "target_scope": resolved_target_scope,
                "source_scope": source.get("scope", ""),
                "source_pack_id": source.get("pack_id", ""),
                "lane": lane_value,
                "source_adapter": source_adapter,
                "payload_files": len(final_payload_files),
                "validation_pass": validation_pass,
                "validation_errors": validation_errors,
                "validation_warnings": validation_warnings,
                "warnings": warnings,
            }
        )

    summary = {
        "target_scope": resolved_target_scope,
        "total": len(results),
        "bootstrapped": sum(1 for item in results if item.get("status") in {"bootstrapped", "planned_bootstrap"}),
        "repaired_existing": sum(1 for item in results if item.get("status") in {"repaired_existing", "planned_repair"}),
        "failed": sum(1 for item in results if item.get("status") == "failed"),
        "dry_run": dry_run,
    }

    if as_json:
        print(json.dumps({"summary": summary, "results": results}, indent=2, sort_keys=True))
    else:
        print(f"sync_shared_priority_target_scope={resolved_target_scope}")
        print(f"sync_shared_priority_total={summary['total']}")
        print(f"sync_shared_priority_bootstrapped={summary['bootstrapped']}")
        print(f"sync_shared_priority_repaired_existing={summary['repaired_existing']}")
        print(f"sync_shared_priority_failed={summary['failed']}")
        for item in results:
            reasons = str(item.get("reason", "")).strip()
            source = ""
            if str(item.get("source_pack_id", "")).strip():
                source = f" source={item.get('source_scope')}/{item.get('source_pack_id')}"
            print(
                f"shared_priority/{item['pack_id']}: status={item['status']} action={item['action']} "
                f"validation_pass={str(bool(item.get('validation_pass', True))).lower()}{source} reason={reasons}"
            )

    return 0 if summary["failed"] == 0 and failed == 0 else 1


def _resolve_pack_cleanup_defaults(pack_id: str, asset_kind: str, animated: bool) -> tuple[str, bool]:
    if asset_kind != "prop" or animated:
        return asset_kind, animated

    try:
        spec = get_roman_pack_spec(pack_id)
    except KeyError:
        return asset_kind, animated

    return spec.asset_kind, spec.animated


def _run_list_pack_families(*, wave: int | None, include_legacy: bool) -> int:
    if wave is not None:
        families = planned_shared_pack_families(wave=wave)
    elif include_legacy:
        families = SHARED_PACK_FAMILIES
    else:
        families = planned_shared_pack_families()

    for family in families:
        primary = family.primary_bridge_id or "-"
        fallbacks = ",".join(family.fallback_bridge_ids) if family.fallback_bridge_ids else "-"
        wave_label = str(family.wave) if family.wave else "legacy"
        print(
            f"{family.pack_id}: wave={wave_label} domain={family.domain} "
            f"bridge={primary} fallbacks={fallbacks}"
        )
    return 0


def _run_emit_pack_family_plan(
    *,
    game_scope: str,
    wave: int | None,
    pack_ids: list[str] | None,
    output_dir: Path | None,
    browser_runtime: str,
) -> int:
    from assetboy.workflows.pack_family_plan import emit_pack_family_plan

    artifacts = emit_pack_family_plan(
        game_scope=game_scope,
        wave=wave,
        pack_ids=tuple(pack_ids) if pack_ids else None,
        output_dir=output_dir,
        browser_runtime=browser_runtime,
    )
    print(f"pack_family_output_dir={artifacts.output_dir}")
    print(f"pack_family_manifest={artifacts.manifest_path}")
    print(f"pack_family_summary={artifacts.summary_path}")
    return 0


def _print_artifacts(prefix: str, artifacts: dict[str, str]) -> None:
    print(f"{prefix}_output_dir={artifacts['output_dir']}")
    print(f"{prefix}_prompt_batch={artifacts['prompt_batch_path']}")
    print(f"{prefix}_provenance_template={artifacts['provenance_template_path']}")
    print(f"{prefix}_payload_target_file={artifacts['payload_target_path_file']}")
    print(f"{prefix}_review_checklist={artifacts['review_checklist_path']}")
    print(f"{prefix}_cleanup_plan={artifacts['cleanup_plan_path']}")
    print(f"{prefix}_payload_target={artifacts['payload_target_path']}")


def _print_engine_bridge_artifacts(prefix: str, artifacts: dict[str, str]) -> None:
    print(f"{prefix}_output_dir={artifacts['output_dir']}")
    print(f"{prefix}_job_spec={artifacts['job_spec_path']}")
    print(f"{prefix}_provenance_template={artifacts['provenance_template_path']}")
    print(f"{prefix}_review_checklist={artifacts['review_checklist_path']}")
    print(f"{prefix}_payload_target_file={artifacts['payload_target_path_file']}")
    print(f"{prefix}_cleanup_plan={artifacts['cleanup_plan_path']}")
    print(f"{prefix}_payload_target={artifacts['payload_target_path']}")


def _print_unreal_runner_artifacts(prefix: str, artifacts: dict[str, str]) -> None:
    print(f"{prefix}_output_dir={artifacts['output_dir']}")
    print(f"{prefix}_engine_job={artifacts['engine_job_spec_path']}")
    print(f"{prefix}_runner_job={artifacts['runner_job_path']}")
    print(f"{prefix}_powershell={artifacts['powershell_path']}")
    print(f"{prefix}_unreal_python={artifacts['unreal_python_path']}")
    print(f"{prefix}_blender_handoff={artifacts['blender_handoff_path']}")
    print(f"{prefix}_launch_command={artifacts['launch_command_path']}")
    print(f"{prefix}_payload_target={artifacts['payload_target_path']}")
    print(f"{prefix}_editor_cmd_hint={artifacts['editor_cmd_path_hint']}")


def _print_unity_runner_artifacts(prefix: str, artifacts: dict[str, str]) -> None:
    print(f"{prefix}_output_dir={artifacts['output_dir']}")
    print(f"{prefix}_engine_job={artifacts['engine_job_spec_path']}")
    print(f"{prefix}_runner_job={artifacts['runner_job_path']}")
    print(f"{prefix}_powershell={artifacts['powershell_path']}")
    print(f"{prefix}_unity_csharp={artifacts['unity_csharp_path']}")
    print(f"{prefix}_blender_handoff={artifacts['blender_handoff_path']}")
    print(f"{prefix}_launch_command={artifacts['launch_command_path']}")
    print(f"{prefix}_payload_target={artifacts['payload_target_path']}")
    print(f"{prefix}_editor_hint={artifacts['editor_path_hint']}")


def _print_epic_vault_artifacts(prefix: str, artifacts: dict[str, str]) -> None:
    print(f"{prefix}_output_dir={artifacts['output_dir']}")
    print(f"{prefix}_job_spec={artifacts['job_spec_path']}")
    print(f"{prefix}_review_checklist={artifacts['review_checklist_path']}")
    print(f"{prefix}_provenance_template={artifacts['provenance_template_path']}")
    print(f"{prefix}_payload_target_file={artifacts['payload_target_path_file']}")
    print(f"{prefix}_script={artifacts['script_path']}")
    print(f"{prefix}_command_template={artifacts['command_template_path']}")
    print(f"{prefix}_uproject={artifacts['uproject_path']}")
    print(f"{prefix}_download_target={artifacts['download_target_path']}")
    print(f"{prefix}_staging_target={artifacts['staging_target_path']}")


def _print_marketplace_claim_artifacts(prefix: str, artifacts: dict[str, str]) -> None:
    print(f"{prefix}_output_dir={artifacts['output_dir']}")
    print(f"{prefix}_job_spec={artifacts['job_spec_path']}")
    print(f"{prefix}_review_checklist={artifacts['review_checklist_path']}")
    print(f"{prefix}_provenance_template={artifacts['provenance_template_path']}")
    print(f"{prefix}_command_template={artifacts['command_template_path']}")
    print(f"{prefix}_payload_target_file={artifacts['payload_target_path_file']}")
    print(f"{prefix}_stash_target={artifacts['stash_target_path']}")


def _print_cue4parse_artifacts(prefix: str, artifacts: dict[str, str]) -> None:
    print(f"{prefix}_output_dir={artifacts['output_dir']}")
    print(f"{prefix}_job_spec={artifacts['job_spec_path']}")
    print(f"{prefix}_provenance_template={artifacts['provenance_template_path']}")
    print(f"{prefix}_review_checklist={artifacts['review_checklist_path']}")
    print(f"{prefix}_command_template={artifacts['command_template_path']}")
    print(f"{prefix}_cleanup_plan={artifacts['cleanup_plan_path']}")
    print(f"{prefix}_payload_target_file={artifacts['payload_target_path_file']}")
    print(f"{prefix}_output_path_hint_file={artifacts['output_path_hint_file']}")
    print(f"{prefix}_output_path={artifacts['output_path']}")


def _print_blender_batch_artifacts(prefix: str, artifacts: dict[str, str]) -> None:
    print(f"{prefix}_output_dir={artifacts['output_dir']}")
    print(f"{prefix}_job_spec={artifacts['job_spec_path']}")
    print(f"{prefix}_blender_script={artifacts['blender_script_path']}")
    print(f"{prefix}_powershell={artifacts['powershell_path']}")
    print(f"{prefix}_command_template={artifacts['command_template_path']}")
    print(f"{prefix}_review_checklist={artifacts['review_checklist_path']}")
    print(f"{prefix}_payload_target_file={artifacts['payload_target_path_file']}")
    print(f"{prefix}_converted_output_dir={artifacts['converted_output_dir']}")


def _run_emit_hunyuan_batch(pack_id: str, game_scope: str, output_dir: Path | None) -> int:
    artifacts = emit_generator_setup(
        profile_id="hunyuan3d2.production",
        pack_id=pack_id,
        game_scope=game_scope,
        output_dir=output_dir,
    )
    _print_artifacts("hunyuan", artifacts.to_dict())
    return 0


def _run_emit_animationgpt_pilot(pack_id: str, game_scope: str, output_dir: Path | None) -> int:
    artifacts = emit_generator_setup(
        profile_id="animationgpt.pilot",
        pack_id=pack_id,
        game_scope=game_scope,
        output_dir=output_dir,
        animated=True,
    )
    _print_artifacts("animationgpt", artifacts.to_dict())
    return 0


def _run_emit_engine_export_job(
    engine: str,
    pack_id: str,
    game_scope: str,
    source_url: str,
    license_note: str,
    source_package_name: str,
    asset_kind: str,
    output_dir: Path | None,
) -> int:
    artifacts = emit_engine_export_job(
        engine=engine,
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        license_note=license_note,
        source_package_name=source_package_name,
        asset_kind=asset_kind,
        output_dir=output_dir,
    )
    _print_engine_bridge_artifacts("engine_bridge", artifacts.to_dict())
    return 0


def _run_emit_unity_export_runner(
    pack_id: str,
    game_scope: str,
    source_url: str,
    license_note: str,
    project_path: str,
    package_root: str,
    asset_paths: list[str],
    unitypackage_paths: list[str],
    source_package_name: str,
    asset_kind: str,
    output_dir: Path | None,
) -> int:
    artifacts = emit_unity_export_runner(
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        license_note=license_note,
        project_path=project_path,
        package_root=package_root,
        asset_paths=tuple(asset_paths),
        unitypackage_paths=tuple(unitypackage_paths),
        source_package_name=source_package_name,
        asset_kind=asset_kind,
        output_dir=output_dir,
    )
    _print_unity_runner_artifacts("unity_runner", artifacts.to_dict())
    return 0


def _run_emit_unity_download_wave(
    source_file: Path,
    game_scope: str,
    project_root: Path,
    output_dir: Path | None,
) -> int:
    report = emit_unity_download_wave(
        source_file=source_file,
        game_scope=game_scope,
        project_root=project_root,
        output_dir=output_dir,
    )
    summary = dict(report.get("summary", {}))
    actual_output_dir = Path(str(report.get("output_dir", "")))
    print(f"unity_download_wave_source={source_file}")
    print(f"unity_download_wave_asset_store_entries={summary.get('asset_store_entries', 0)}")
    print(f"unity_download_wave_best_first={summary.get('best_first_wave_entries', 0)}")
    print(f"unity_download_wave_export_candidates={summary.get('export_runner_candidates', 0)}")
    print(f"unity_download_wave_browser_jobs={summary.get('browser_jobs_emitted', 0)}")
    print(f"unity_download_wave_export_runners={summary.get('unity_export_runners_emitted', 0)}")
    print(f"unity_download_wave_json={actual_output_dir / 'unity_download_wave.json'}")
    print(f"unity_download_wave_md={actual_output_dir / 'unity_download_wave.md'}")
    return 0


def _run_unity_claim_wave(
    wave_json: Path,
    *,
    best_first: bool,
    exportable_only: bool,
    categories: list[str],
    pack_ids: list[str],
    limit: int,
    dry_run: bool,
    headless: bool,
    browser_profile_dir: Path | None,
    timeout_ms: int,
    retries: int,
    hydrate_provenance: bool,
    prepare_pack: bool,
    auto_intake: bool,
    cleanup_mode: str,
    asset_kind: str,
    animated: bool,
    packet_status: str,
    overwrite_packet: bool,
    verify_hashes: bool,
    continue_on_error: bool,
    require_complete: bool,
    emit_project_ingest_wave: bool,
    project_path: Path | None,
    game_scope: str,
    output_dir: Path | None,
    as_json: bool,
) -> int:
    from assetboy.execution.playwright_runner import run_browser_job

    report = json.loads(wave_json.read_text(encoding="utf-8"))
    asset_donor_only = best_first and not categories and not pack_ids
    selected = select_unity_download_wave_jobs(
        report,
        best_first_only=best_first,
        exportable_only=exportable_only or asset_donor_only,
        asset_donor_only=asset_donor_only,
        categories=tuple(categories),
        pack_ids=tuple(pack_ids),
        limit=limit if limit > 0 else None,
    )
    actual_output_dir = output_dir if output_dir is not None else wave_json.parent / "unity_claim_wave"
    ensure_dir(actual_output_dir)

    results: list[dict[str, object]] = []
    aborted = False
    for item in selected:
        job_result: dict[str, object] = {
            "name": str(item.get("name", "")),
            "pack_id": str(item.get("pack_id", "")),
            "category": str(item.get("category", "")),
            "url": str(item.get("url", "")),
            "status": "planned",
            "error": "",
            "steps": [],
        }
        job_spec = Path(str(item["browser_job_spec"]))
        if job_spec.exists():
            try:
                job_payload = json.loads(job_spec.read_text(encoding="utf-8"))
            except Exception:
                job_payload = {}
        else:
            job_payload = {}
        if not isinstance(job_payload.get("playwright_steps"), list):
            refreshed = emit_browser_automation_job(
                source_adapter="unity_asset_store",
                runtime=BrowserRuntime.PLAYWRIGHT_MCP,
                pack_id=str(item.get("pack_id", "")),
                game_scope="arena_shared",
                source_url=str(item.get("url", "")),
                search_terms=(str(item.get("name", "")),),
                login_required=True,
                output_dir=job_spec.parent,
                notes=tuple(),
            )
            job_spec = refreshed.job_spec_path
        step_payload: dict[str, object] = {
            "kind": "browser_job_spec",
            "path": str(job_spec),
            "exists": job_spec.exists(),
            "status": "planned",
            "execution_mode": "",
            "attempts": 0,
            "error": "",
        }
        if not job_spec.exists():
            step_payload["status"] = "failed"
            step_payload["error"] = "Browser job spec path does not exist."
            job_result["status"] = "failed"
            job_result["error"] = str(step_payload["error"])
            job_result["steps"] = [step_payload]
            results.append(job_result)
            if not continue_on_error:
                aborted = True
                break
            continue
        try:
            run_result = run_browser_job(
                job_spec_path=job_spec,
                dry_run=dry_run,
                execute=not dry_run,
                headed=not headless,
                browser_profile_dir=browser_profile_dir,
                timeout_ms=timeout_ms,
                retries=retries,
            )
        except Exception as exc:
            step_payload["status"] = "failed"
            step_payload["error"] = str(exc)
            job_result["status"] = "failed"
            job_result["error"] = str(exc)
            job_result["execution_mode"] = "failed"
            job_result["last_url"] = ""
            job_result["artifacts_dir"] = ""
            job_result["claimed_or_owned"] = False
            job_result["unity_claim_state"] = {}
            job_result["steps"] = [step_payload]
            results.append(job_result)
            if not continue_on_error:
                aborted = True
                break
            continue
        step_payload["execution_mode"] = str(run_result.execution_mode)
        step_payload["attempts"] = int(getattr(run_result, "attempts", 0) or 0)
        step_payload["last_url"] = str(getattr(run_result, "last_url", "") or "")
        if getattr(run_result, "artifacts_dir", None) is not None:
            step_payload["artifacts_dir"] = str(run_result.artifacts_dir)
        if getattr(run_result, "browser_profile_dir", None) is not None:
            step_payload["browser_profile_dir"] = str(run_result.browser_profile_dir)
        repair_reason = _safe_result_text_attr(run_result, "repair_reason")
        repair_command = _safe_result_text_attr(run_result, "repair_command")
        provider_runbook_id = _safe_result_text_attr(run_result, "provider_runbook_id")
        if repair_reason:
            step_payload["repair_reason"] = repair_reason
        if repair_command:
            step_payload["repair_command"] = repair_command
        if provider_runbook_id:
            step_payload["provider_runbook_id"] = provider_runbook_id
        claim_state_path = (
            run_result.artifacts_dir / "unity_claim_state.json"
            if run_result.artifacts_dir is not None
            else None
        )
        claim_state: dict[str, object] = {}
        if claim_state_path is not None and claim_state_path.exists():
            try:
                claim_state = json.loads(claim_state_path.read_text(encoding="utf-8"))
            except Exception:
                claim_state = {}
        claimed_or_owned = (
            bool(claim_state.get("purchased", False))
            or bool(claim_state.get("openInUnity", False))
            or bool(claim_state.get("myAssetsContainsProduct", False))
        )
        browser_error = str(getattr(run_result, "error", "") or "").strip()
        if dry_run:
            step_payload["status"] = "planned"
            job_result["status"] = "planned"
        elif run_result.execution_mode == "repair_required":
            step_payload["status"] = "repair_required"
            step_payload["error"] = browser_error or "Unity browser auth repair is required before this claim can continue."
            job_result["status"] = "pending_manual"
            job_result["error"] = str(step_payload["error"])
        elif run_result.execution_mode == "failed":
            step_payload["status"] = "failed"
            step_payload["error"] = browser_error or "Unity claim browser execution failed."
            job_result["status"] = "failed"
            job_result["error"] = str(step_payload["error"])
        elif run_result.execution_mode == "interactive_required":
            step_payload["status"] = "pending_manual"
            step_payload["error"] = browser_error or "Unity claim browser session still requires interactive sign-in/consent."
            job_result["status"] = "pending_manual"
            job_result["error"] = str(step_payload["error"])
        else:
            step_payload["status"] = "executed"
            if hydrate_provenance or prepare_pack or auto_intake:
                try:
                    postprocess = _postprocess_browser_job(
                        job_spec_path=job_spec,
                        artifacts_dir=Path(run_result.artifacts_dir) if getattr(run_result, "artifacts_dir", None) is not None else None,
                        last_url=str(getattr(run_result, "last_url", "") or ""),
                        fallback_pack_id=str(item.get("pack_id", "")).strip(),
                        fallback_game_scope=game_scope,
                        hydrate_provenance=hydrate_provenance,
                        prepare_pack=prepare_pack,
                        cleanup_mode=cleanup_mode,
                        asset_kind=asset_kind,
                        animated=animated,
                        packet_status=packet_status,
                        overwrite_packet=overwrite_packet,
                        verify_hashes=verify_hashes,
                        auto_intake=auto_intake,
                    )
                except Exception as exc:
                    step_payload["status"] = "failed"
                    step_payload["error"] = str(exc)
                    job_result["status"] = "failed"
                    job_result["error"] = str(exc)
                else:
                    step_payload.update(postprocess)
                    post_status = str(postprocess.get("status", "")).strip()
                    if isinstance(postprocess.get("hydration"), dict):
                        job_result["hydration_status"] = str(postprocess["hydration"].get("status", "")).strip()
                        job_result["hydration_report_path"] = str(postprocess["hydration"].get("hydration_report_path", "")).strip()
                        job_result["provenance_path"] = str(postprocess["hydration"].get("provenance_path", "")).strip()
                        job_result["register_packet_ready"] = bool(postprocess["hydration"].get("register_packet_ready"))
                        job_result["provenance_confidence_band"] = str(
                            postprocess["hydration"].get("provenance_confidence_band", "")
                        ).strip()
                        job_result["provenance_confidence_score"] = int(
                            postprocess["hydration"].get("provenance_confidence_score", 0) or 0
                        )
                    if isinstance(postprocess.get("prepare_pack"), dict):
                        job_result["prepare_pack_state"] = str(postprocess["prepare_pack"].get("current_state", "")).strip()
                        job_result["packet_path"] = str(postprocess["prepare_pack"].get("packet_path", "")).strip()
                    if isinstance(postprocess.get("auto_intake"), dict):
                        job_result["auto_intake_pass"] = bool(postprocess["auto_intake"].get("pass"))
                        job_result["handoff_receipt_path"] = str(postprocess["auto_intake"].get("handoff_receipt_path", "")).strip()
                    if post_status == "failed":
                        job_result["status"] = "failed"
                        job_result["error"] = str(postprocess.get("error", "Unity postprocess failed")).strip()
                    elif post_status == "pending_manual":
                        job_result["status"] = "pending_manual"
                        job_result["error"] = str(postprocess.get("error", "Unity postprocess requires manual follow-up")).strip()
                    else:
                        job_result["status"] = "executed"
            else:
                job_result["status"] = "executed"

        job_result["execution_mode"] = str(run_result.execution_mode)
        job_result["last_url"] = str(getattr(run_result, "last_url", "") or "")
        job_result["artifacts_dir"] = str(run_result.artifacts_dir) if run_result.artifacts_dir else ""
        job_result["claimed_or_owned"] = claimed_or_owned
        job_result["unity_claim_state"] = claim_state
        if repair_reason:
            job_result["repair_reason"] = repair_reason
        if repair_command:
            job_result["repair_command"] = repair_command
        if provider_runbook_id:
            job_result["provider_runbook_id"] = provider_runbook_id
        job_result["steps"] = [step_payload]
        results.append(job_result)
        if job_result["status"] == "failed" and not continue_on_error:
            aborted = True
            break

    summary = {
        "selected_jobs": len(selected),
        "processed_jobs": len(results),
        "executed": sum(1 for item in results if str(item.get("status", "")) == "executed"),
        "planned": sum(1 for item in results if str(item.get("status", "")) == "planned"),
        "pending_manual": sum(1 for item in results if str(item.get("status", "")) == "pending_manual"),
        "failed": sum(1 for item in results if str(item.get("status", "")) == "failed"),
        "repair_required": sum(1 for item in results if str(item.get("execution_mode", "")) == "repair_required"),
        "claimed_or_owned": sum(1 for item in results if bool(item.get("claimed_or_owned"))),
        "interactive_required": sum(1 for item in results if str(item.get("execution_mode", "")) == "interactive_required"),
        "handoff_ready": sum(1 for item in results if bool(item.get("auto_intake_pass")) and str(item.get("handoff_receipt_path", "")).strip()),
        "hydration_completed": sum(
            1
            for item in results
            if (
                str(item.get("hydration_status", "")).strip() == "completed"
                or str(item.get("steps", [{}])[0].get("hydration", {}).get("status", "")).strip() == "completed"
            )
        ),
        "packeted": sum(
            1
            for item in results
            if (
                str(item.get("prepare_pack_state", "")).strip() == "packeted"
                or str(item.get("steps", [{}])[0].get("prepare_pack", {}).get("current_state", "")).strip() == "packeted"
            )
        ),
        "auto_intake_passed": sum(
            1
            for item in results
            if bool(item.get("steps", [{}])[0].get("auto_intake", {}).get("pass"))
        ),
        "register_packet_ready": sum(1 for item in results if bool(item.get("register_packet_ready"))),
        "aborted": aborted,
    }
    wave_report = {
        "schema_version": "assetboy.unity_claim_wave.v2",
        "wave_json": str(wave_json),
        "output_dir": str(actual_output_dir),
        "execute": not dry_run,
        "headless": headless,
        "browser_profile_dir": str(browser_profile_dir) if browser_profile_dir is not None else "",
        "timeout_ms": timeout_ms,
        "retries": retries,
        "hydrate_provenance": hydrate_provenance,
        "prepare_pack": prepare_pack,
        "auto_intake": auto_intake,
        "cleanup_mode": cleanup_mode,
        "asset_kind": asset_kind,
        "animated": animated,
        "packet_status": packet_status,
        "overwrite_packet": overwrite_packet,
        "verify_hashes": verify_hashes,
        "continue_on_error": continue_on_error,
        "require_complete": require_complete,
        "summary": summary,
        "results": results,
    }
    if emit_project_ingest_wave and not dry_run:
        ingest_output_dir = actual_output_dir / "unity_project_ingest_wave"
        ingest_report = emit_unity_project_ingest_wave(
            wave_json=wave_json,
            project_path=project_path,
            game_scope=game_scope,
            best_first_only=best_first,
            exportable_only=exportable_only,
            categories=tuple(categories),
            pack_ids=tuple(pack_ids),
            limit=limit if limit > 0 else None,
            claimed_or_owned_only=True,
            output_dir=ingest_output_dir,
        )
        wave_report["project_ingest_wave"] = {
            "output_dir": str(ingest_report.get("output_dir", "")),
            "json_path": str(Path(str(ingest_report.get("output_dir", ""))) / "unity_project_ingest_wave.json"),
            "md_path": str(Path(str(ingest_report.get("output_dir", ""))) / "unity_project_ingest_wave.md"),
            "project_path": str(ingest_report.get("project_path", "")),
            "selected_jobs": int(dict(ingest_report.get("summary", {})).get("selected_jobs", 0) or 0),
            "claimed_or_owned": int(dict(ingest_report.get("summary", {})).get("claimed_or_owned", 0) or 0),
            "reviewed_packet_ready": int(dict(ingest_report.get("summary", {})).get("reviewed_packet_ready", 0) or 0),
            "handoff_ready": int(dict(ingest_report.get("summary", {})).get("handoff_ready", 0) or 0),
            "project_ingest_required": int(dict(ingest_report.get("summary", {})).get("project_ingest_required", 0) or 0),
        }
    write_json(actual_output_dir / "unity_claim_wave.json", wave_report)
    (actual_output_dir / "unity_claim_wave.md").write_text(
        render_unity_claim_wave_markdown(wave_report),
        encoding="utf-8",
    )
    print(f"unity_claim_wave_json={actual_output_dir / 'unity_claim_wave.json'}")
    print(f"unity_claim_wave_md={actual_output_dir / 'unity_claim_wave.md'}")
    print(f"unity_claim_wave_selected={summary['selected_jobs']}")
    print(f"unity_claim_wave_processed={summary['processed_jobs']}")
    print(f"unity_claim_wave_executed={summary['executed']}")
    print(f"unity_claim_wave_pending_manual={summary['pending_manual']}")
    print(f"unity_claim_wave_claimed_or_owned={summary['claimed_or_owned']}")
    print(f"unity_claim_wave_interactive_required={summary['interactive_required']}")
    print(f"unity_claim_wave_repair_required={summary['repair_required']}")
    print(f"unity_claim_wave_handoff_ready={summary['handoff_ready']}")
    print(f"unity_claim_wave_failed={summary['failed']}")
    if "project_ingest_wave" in wave_report:
        project_ingest_wave = dict(wave_report["project_ingest_wave"])
        print(f"unity_claim_wave_project_ingest_json={project_ingest_wave.get('json_path', '')}")
        print(f"unity_claim_wave_project_ingest_md={project_ingest_wave.get('md_path', '')}")
    if as_json:
        print(json.dumps(wave_report, indent=2, sort_keys=True))
    if summary["failed"] > 0:
        return 1
    if require_complete and summary["pending_manual"] > 0:
        return 1
    return 0


def _run_unity_hub_status(projects_path: Path | None, output_dir: Path | None) -> int:
    report = build_unity_hub_status(projects_path=projects_path)
    actual_output_dir = output_dir if output_dir is not None else generated_output_root() / "unity_hub_status"
    ensure_dir(actual_output_dir)
    write_json(actual_output_dir / "unity_hub_status.json", report)
    (actual_output_dir / "unity_hub_status.md").write_text(
        render_unity_hub_status_markdown(report),
        encoding="utf-8",
    )
    print(f"unity_hub_status_json={actual_output_dir / 'unity_hub_status.json'}")
    print(f"unity_hub_status_md={actual_output_dir / 'unity_hub_status.md'}")
    print(f"unity_hub_project_count={report.get('project_count', 0)}")
    print(f"unity_hub_recommended_project={report.get('recommended_project_path', '')}")
    print(f"unity_hub_cached_files={report.get('cache', {}).get('cached_file_count', 0)}")
    print(f"unity_hub_cached_unitypackages={report.get('cache', {}).get('cached_unitypackage_count', 0)}")
    print(f"unity_hub_tokens_available={str(bool(report.get('auth', {}).get('tokens_available'))).lower()}")
    print(f"unity_hub_access_token_expired={str(bool(report.get('auth', {}).get('access_token_expired'))).lower()}")
    return 0


def _run_map_unity_owned_library(
    *,
    page_size: int,
    max_pages: int,
    output_dir: Path | None,
) -> int:
    report = build_unity_owned_library_map(page_size=page_size, max_pages=max_pages)
    actual_output_dir = output_dir if output_dir is not None else generated_output_root() / "unity_owned_library_map"
    ensure_dir(actual_output_dir)
    write_json(actual_output_dir / "unity_owned_library_map.json", report)
    (actual_output_dir / "unity_owned_library_map.md").write_text(
        render_unity_owned_library_map_markdown(report),
        encoding="utf-8",
    )
    print(f"unity_owned_library_map_json={actual_output_dir / 'unity_owned_library_map.json'}")
    print(f"unity_owned_library_map_md={actual_output_dir / 'unity_owned_library_map.md'}")
    print(f"unity_owned_library_owned_count={report.get('owned_count', 0)}")
    print(f"unity_owned_library_pages_fetched={report.get('pages_fetched', 0)}")
    print(f"unity_owned_library_tokens_available={str(bool(report.get('auth', {}).get('tokens_available'))).lower()}")
    return 0


def _run_unity_download_owned(
    *,
    product_id: str,
    output_dir: Path | None,
    timeout: float,
) -> int:
    actual_output_dir = output_dir if output_dir is not None else generated_output_root() / "unity_owned_downloads"
    ensure_dir(actual_output_dir)
    report = download_unity_owned_package(
        product_id=product_id,
        output_dir=actual_output_dir,
        timeout=timeout,
    )
    report_path = actual_output_dir / f"unity_owned_download_{product_id}.json"
    write_json(report_path, report)
    print(f"unity_owned_download_json={report_path}")
    print(f"unity_owned_download_output_path={report.get('output_path', '')}")
    print(f"unity_owned_download_bytes_written={report.get('bytes_written', 0)}")
    print(f"unity_owned_download_selected_upload_version={report.get('selected_upload_version', '')}")
    return 0


def _run_download_unity_owned_lightweights(
    *,
    max_mb: float,
    limit: int,
    include_hidden: bool,
    include_unknown_size: bool,
    page_size: int,
    max_pages: int,
    output_dir: Path | None,
    timeout: float,
) -> int:
    report = download_unity_owned_lightweights(
        max_mb=max_mb,
        limit=limit if limit > 0 else None,
        include_hidden=include_hidden,
        include_unknown_size=include_unknown_size,
        page_size=page_size,
        max_pages=max_pages,
        output_dir=output_dir,
        timeout=timeout,
    )
    actual_output_dir = Path(str(report.get("output_dir", "")))
    summary = dict(report.get("summary", {}))
    print(f"unity_owned_lightweights_json={actual_output_dir / 'unity_owned_lightweights.json'}")
    print(f"unity_owned_lightweights_md={actual_output_dir / 'unity_owned_lightweights.md'}")
    print(f"unity_owned_lightweights_scanned={summary.get('owned_items_scanned', 0)}")
    print(f"unity_owned_lightweights_eligible={summary.get('eligible_lightweights', 0)}")
    print(f"unity_owned_lightweights_downloaded={summary.get('downloaded', 0)}")
    print(f"unity_owned_lightweights_skipped_large={summary.get('skipped_large', 0)}")
    print(f"unity_owned_lightweights_skipped_unknown_size={summary.get('skipped_unknown_size', 0)}")
    print(f"unity_owned_lightweights_failed_inspection={summary.get('failed_inspection', 0)}")
    print(f"unity_owned_lightweights_failed_download={summary.get('failed_download', 0)}")
    return 0


def _run_download_unity_owned_wave(
    wave_json: Path,
    *,
    best_first: bool,
    exportable_only: bool,
    asset_donor_only: bool,
    categories: list[str],
    pack_ids: list[str],
    limit: int,
    output_dir: Path | None,
    timeout: float,
) -> int:
    report = download_unity_owned_wave(
        wave_json=wave_json,
        best_first_only=best_first,
        exportable_only=exportable_only,
        asset_donor_only=asset_donor_only,
        categories=tuple(categories),
        pack_ids=tuple(pack_ids),
        limit=limit if limit > 0 else None,
        output_dir=output_dir,
        timeout=timeout,
    )
    actual_output_dir = Path(str(report.get("output_dir", "")))
    summary = dict(report.get("summary", {}))
    print(f"unity_owned_download_wave_json={actual_output_dir / 'unity_owned_download_wave.json'}")
    print(f"unity_owned_download_wave_md={actual_output_dir / 'unity_owned_download_wave.md'}")
    print(f"unity_owned_download_wave_selected={summary.get('selected_jobs', 0)}")
    print(f"unity_owned_download_wave_owned_matches={summary.get('owned_matches', 0)}")
    print(f"unity_owned_download_wave_downloaded={summary.get('downloaded', 0)}")
    print(f"unity_owned_download_wave_not_owned={summary.get('not_owned', 0)}")
    print(f"unity_owned_download_wave_failed={summary.get('failed', 0)}")
    return 0


def _run_emit_unity_project_ingest_wave(
    wave_json: Path,
    *,
    project_path: Path | None,
    game_scope: str,
    best_first: bool,
    exportable_only: bool,
    categories: list[str],
    pack_ids: list[str],
    limit: int,
    output_dir: Path | None,
) -> int:
    report = emit_unity_project_ingest_wave(
        wave_json=wave_json,
        project_path=project_path,
        game_scope=game_scope,
        best_first_only=best_first,
        exportable_only=exportable_only,
        categories=tuple(categories),
        pack_ids=tuple(pack_ids),
        limit=limit if limit > 0 else None,
        output_dir=output_dir,
    )
    actual_output_dir = Path(str(report.get("output_dir", "")))
    summary = dict(report.get("summary", {}))
    print(f"unity_project_ingest_wave_json={actual_output_dir / 'unity_project_ingest_wave.json'}")
    print(f"unity_project_ingest_wave_md={actual_output_dir / 'unity_project_ingest_wave.md'}")
    print(f"unity_project_ingest_wave_script={actual_output_dir / 'run_unity_project_ingest.ps1'}")
    print(f"unity_project_ingest_project={report.get('project_path', '')}")
    print(f"unity_project_ingest_selected={summary.get('selected_jobs', 0)}")
    print(f"unity_project_ingest_claimed_or_owned={summary.get('claimed_or_owned', 0)}")
    print(f"unity_project_ingest_missing_asset_id={summary.get('missing_asset_id', 0)}")
    return 0


def _run_emit_unreal_export_runner(
    pack_id: str,
    game_scope: str,
    source_url: str,
    license_note: str,
    project_file: str,
    package_root: str,
    asset_paths: list[str],
    source_package_name: str,
    asset_kind: str,
    output_dir: Path | None,
) -> int:
    artifacts = emit_unreal_export_runner(
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        license_note=license_note,
        project_file=project_file,
        package_root=package_root,
        asset_paths=tuple(asset_paths),
        source_package_name=source_package_name,
        asset_kind=asset_kind,
        output_dir=output_dir,
    )
    _print_unreal_runner_artifacts("unreal_runner", artifacts.to_dict())
    return 0


def _run_emit_uevaultmanager_job(
    pack_id: str,
    game_scope: str,
    source_url: str,
    vault_item: str,
    engine_association: str,
    output_dir: Path | None,
) -> int:
    artifacts = emit_uevaultmanager_job(
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        vault_item=vault_item,
        engine_association=engine_association,
        output_dir=output_dir,
    )
    _print_epic_vault_artifacts("uevaultmanager", artifacts.to_dict())
    return 0


def _run_emit_epic_dummy_project(
    pack_id: str,
    game_scope: str,
    source_url: str,
    engine_association: str,
    project_name: str,
    project_dir: str | None,
    output_dir: Path | None,
) -> int:
    artifacts = emit_epic_dummy_project_job(
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        engine_association=engine_association,
        project_name=project_name,
        project_dir=project_dir,
        output_dir=output_dir,
    )
    _print_epic_vault_artifacts("epic_dummy_project", artifacts.to_dict())
    return 0


def _print_uevault_command_result(result: object) -> None:
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    if stdout:
        print(stdout.rstrip())
    if stderr:
        print(stderr.rstrip())


def _run_uevault_repair_config(config_path: Path) -> int:
    resolved = write_uevaultmanager_safe_config(config_path)
    print(f"uevault_safe_config={resolved}")
    print("uevault_safe_config_rewritten=true")
    return 0


def _run_uevault_status(timeout: float, online: bool) -> int:
    args = ["status", "--json"]
    if not online:
        args.insert(1, "--offline")
    result = run_uevaultmanager_command(args, timeout_seconds=timeout)
    print(f"uevault_safe_config={write_uevaultmanager_safe_config()}")
    print(f"uevault_exit_code={result.returncode}")
    _print_uevault_command_result(result)
    return result.returncode


def _run_uevault_import_auth(timeout: float) -> int:
    result = run_uevaultmanager_command(["auth", "--import"], timeout_seconds=timeout)
    print(f"uevault_safe_config={write_uevaultmanager_safe_config()}")
    print(f"uevault_exit_code={result.returncode}")
    _print_uevault_command_result(result)
    return result.returncode


def _run_uevault_list_owned(output_path: Path, force_refresh: bool, timeout: float) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    args = ["list", "--json"]
    if force_refresh:
        args.append("-f")
    args.extend(["-o", str(output_path)])
    result = run_uevaultmanager_command(args, timeout_seconds=timeout)
    print(f"uevault_safe_config={write_uevaultmanager_safe_config()}")
    print(f"uevault_exit_code={result.returncode}")
    print(f"uevault_owned_output={output_path}")
    _print_uevault_command_result(result)
    if output_path.exists():
        try:
            owned_count, total_count = parse_uevault_owned_asset_count(output_path)
        except Exception as exc:
            print(f"uevault_warning=Owned output file is invalid or empty: {exc}")
            return 1
        print(f"uevault_owned_count={owned_count}")
        print(f"uevault_total_count={total_count}")
        if owned_count == 0:
            print("uevault_warning=Owned count is zero. Auth may still be missing or UEVaultManager metadata may still be stale.")
    return result.returncode if output_path.exists() else 1


def _run_uevault_install_owned(vault_item: str, download_dir: Path, full_install: bool, timeout: float) -> int:
    download_dir.mkdir(parents=True, exist_ok=True)
    args = ["install", vault_item, "-dp", str(download_dir)]
    if not full_install:
        args.append("--download-only")
    result = run_uevaultmanager_command(args, timeout_seconds=timeout)
    print(f"uevault_safe_config={write_uevaultmanager_safe_config()}")
    print(f"uevault_exit_code={result.returncode}")
    print(f"uevault_vault_item={vault_item}")
    print(f"uevault_download_dir={download_dir}")
    _print_uevault_command_result(result)
    if result.returncode != 0:
        print("uevault_recommendation=If this item is owned but install still fails, switch to the dummy-project plus extractor path for that pack.")
    return result.returncode


def _run_legendary_status(timeout: float) -> int:
    report = build_legendary_status_report(timeout_seconds=timeout)
    session = dict(report.get("session", {}))
    status = dict(report.get("status", {}))
    print(f"legendary_path={report.get('legendary_path', '')}")
    print(f"legendary_exit_code={report.get('exit_code')}")
    print(f"legendary_session_path={session.get('config_path', '')}")
    print(f"legendary_remember_me_present={str(bool(session.get('remember_me_present'))).lower()}")
    print(f"legendary_remember_me_data_present={str(bool(session.get('remember_me_data_present'))).lower()}")
    if status:
        print(f"legendary_account={status.get('account', '')}")
        print(f"legendary_games_available={status.get('games_available', 0)}")
        print(f"legendary_games_installed={status.get('games_installed', 0)}")
        print(f"legendary_config_directory={status.get('config_directory', '')}")
    stdout = str(report.get("stdout", "")).strip()
    stderr = str(report.get("stderr", "")).strip()
    if stderr:
        print(stderr)
    if report.get("error"):
        print(f"legendary_error={report['error']}")
        return 1
    if stdout and not status:
        print(stdout)
    return 0


def _run_legendary_import_auth(timeout: float) -> int:
    report = import_legendary_auth(timeout_seconds=timeout)
    session = dict(report.get("session", {}))
    print(f"legendary_path={report.get('legendary_path', '')}")
    print(f"legendary_exit_code={report.get('exit_code')}")
    print(f"legendary_session_path={session.get('config_path', '')}")
    print(f"legendary_remember_me_present={str(bool(session.get('remember_me_present'))).lower()}")
    print(f"legendary_remember_me_data_present={str(bool(session.get('remember_me_data_present'))).lower()}")
    stdout = str(report.get("stdout", "")).strip()
    stderr = str(report.get("stderr", "")).strip()
    if stdout:
        print(stdout)
    if stderr:
        print(stderr)
    if report.get("error"):
        print("legendary_recommendation=If RememberMe is missing, log into Epic Launcher once and then rerun this no-browser import.")
        return 1
    return 0


def _run_legendary_list_ue(output_dir: Path, timeout: float) -> int:
    report = list_legendary_ue_assets(timeout_seconds=timeout)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_json(output_dir / "legendary_ue_assets.json", report)
    markdown_lines = [
        "# Legendary UE Assets",
        "",
        f"- Total records: `{dict(report.get('summary', {})).get('total_records', 0)}`",
        f"- Titles present: `{dict(report.get('summary', {})).get('has_titles', 0)}`",
        f"- Legendary path: `{report.get('legendary_path', '')}`",
        "",
    ]
    if report.get("error"):
        markdown_lines.append(f"- Error: `{report['error']}`")
    markdown_path = output_dir / "legendary_ue_assets.md"
    markdown_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    session = dict(report.get("session", {}))
    summary = dict(report.get("summary", {}))
    print(f"legendary_path={report.get('legendary_path', '')}")
    print(f"legendary_exit_code={report.get('exit_code')}")
    print(f"legendary_remember_me_present={str(bool(session.get('remember_me_present'))).lower()}")
    print(f"legendary_remember_me_data_present={str(bool(session.get('remember_me_data_present'))).lower()}")
    print(f"legendary_ue_total_records={summary.get('total_records', 0)}")
    print(f"legendary_ue_titles_present={summary.get('has_titles', 0)}")
    print(f"legendary_ue_json={json_path}")
    print(f"legendary_ue_md={markdown_path}")
    if report.get("error"):
        return 1
    return 0


def _run_legendary_install_owned(app_name: str, base_path: Path, timeout: float) -> int:
    base_path.mkdir(parents=True, exist_ok=True)
    report = install_legendary_asset(app_name, base_path=base_path, timeout_seconds=timeout)
    print(f"legendary_path={report.get('legendary_path', '')}")
    print(f"legendary_exit_code={report.get('exit_code')}")
    print(f"legendary_app_name={report.get('app_name', '')}")
    print(f"legendary_base_path={report.get('base_path', '')}")
    stdout = str(report.get("stdout", "")).strip()
    stderr = str(report.get("stderr", "")).strip()
    if stdout:
        print(stdout)
    if stderr:
        print(stderr)
    if report.get("error"):
        print("legendary_recommendation=If install fails while you own the item, rerun legendary-list-ue after auth import and use the exact app name from that list.")
        return 1
    return 0


def _run_inventory_epic_vault_cache(db_path: Path, output_dir: Path) -> int:
    entries = build_local_epic_vault_inventory(db_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_json(output_dir / "epic_vault_inventory.json", {"entries": entries})
    markdown_path = (output_dir / "epic_vault_inventory.md")
    markdown_path.write_text(render_local_epic_vault_inventory_markdown(entries), encoding="utf-8")
    print(f"epic_vault_inventory_db={db_path}")
    print(f"epic_vault_inventory_count={len(entries)}")
    print(f"epic_vault_inventory_json={json_path}")
    print(f"epic_vault_inventory_md={markdown_path}")
    return 0


def _run_inventory_epic_library_report(db_path: Path, output_dir: Path) -> int:
    report = build_local_epic_library_report(db_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_json(output_dir / "epic_library_report.json", report)
    markdown_path = output_dir / "epic_library_report.md"
    markdown_path.write_text(render_local_epic_library_report_markdown(report), encoding="utf-8")
    confirmed_entries = list(report.get("confirmed_cached_entries", []))
    launcher_candidates = list(report.get("launcher_cache_candidates", []))
    readiness = dict(report.get("extraction_readiness", {}))
    print(f"epic_library_report_db={db_path}")
    print(f"epic_library_confirmed_cached={len(confirmed_entries)}")
    print(f"epic_library_launcher_candidates={len(launcher_candidates)}")
    print(f"epic_library_can_extract_now={bool(readiness.get('can_extract_now'))}")
    print(f"epic_library_report_json={json_path}")
    print(f"epic_library_report_md={markdown_path}")
    return 0


def _run_inventory_epic_launcher_cache(data_dir: Path, output_dir: Path) -> int:
    data_paths = tuple(sorted(data_dir.glob("OC_*.dat"))) if data_dir.exists() else ()
    entries = build_local_epic_launcher_cache_candidates(data_paths)
    readiness = build_local_epic_extraction_readiness()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_json(
        output_dir / "epic_launcher_inventory.json",
        {"entries": entries, "extraction_readiness": readiness},
    )
    markdown_path = output_dir / "epic_launcher_inventory.md"
    markdown = render_local_epic_launcher_cache_markdown(entries)
    if readiness:
        markdown = (
            "# Launcher Cache Extraction Readiness\n\n"
            f"- Can extract now: `{bool(readiness.get('can_extract_now'))}`\n"
            f"- Recommended path: {readiness.get('recommended_path', '')}\n\n"
            + markdown
        )
    markdown_path.write_text(markdown, encoding="utf-8")
    print(f"epic_launcher_data_dir={data_dir}")
    print(f"epic_launcher_cache_files={len(data_paths)}")
    print(f"epic_launcher_candidate_count={len(entries)}")
    print(f"epic_launcher_inventory_json={json_path}")
    print(f"epic_launcher_inventory_md={markdown_path}")
    return 0


def _run_emit_epic_cache_extractor_wave(db_path: Path, output_dir: Path, game_scope: str) -> int:
    entries = build_local_epic_vault_inventory(db_path)
    emitted = emit_epic_cache_extractor_wave(entries, game_scope=game_scope, output_dir=output_dir)
    manifest_path = write_json(output_dir / "epic_cache_extractor_wave.json", {"jobs": emitted})
    print(f"epic_cache_extractor_db={db_path}")
    print(f"epic_cache_extractor_jobs={len(emitted)}")
    print(f"epic_cache_extractor_manifest={manifest_path}")
    for item in emitted:
        print(f"epic_cache_extractor_pack={item['pack_id']}")
    return 0


def _run_map_epic_library(output_dir: Path, timeout: float) -> int:
    report = build_online_epic_library_map(timeout_seconds=timeout)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_json(output_dir / "epic_online_library_map.json", report)
    markdown_path = output_dir / "epic_online_library_map.md"
    markdown_path.write_text(render_online_epic_library_map_markdown(report), encoding="utf-8")
    summary = dict(report.get("summary", {}))
    print(f"epic_online_library_total={summary.get('total_records', 0)}")
    print(f"epic_online_library_marketplace={summary.get('ue_marketplace_records', 0)}")
    print(f"epic_online_library_engines={summary.get('engine_records', 0)}")
    print(f"epic_online_library_assets={summary.get('marketplace_asset_records', 0)}")
    print(f"epic_online_library_samples={summary.get('marketplace_sample_records', 0)}")
    print(f"epic_online_library_games={summary.get('game_or_app_records', 0)}")
    print(f"epic_online_library_json={json_path}")
    print(f"epic_online_library_md={markdown_path}")
    return 0


def _run_map_fab_library(output_dir: Path, timeout: float) -> int:
    from assetboy.providers.fab_hybrid import (
        build_online_fab_library_map,
        render_online_fab_library_map_markdown,
    )

    report = build_online_fab_library_map(timeout_seconds=timeout)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_json(output_dir / "fab_online_library_map.json", report)
    markdown_path = output_dir / "fab_online_library_map.md"
    markdown_path.write_text(render_online_fab_library_map_markdown(report), encoding="utf-8")
    summary = dict(report.get("summary", {}))
    print(f"fab_online_library_total={summary.get('total_records', 0)}")
    print(f"fab_online_library_downloadable={summary.get('downloadable_records', 0)}")
    print(f"fab_online_library_neutral_or_mixed={summary.get('neutral_or_mixed_records', 0)}")
    print(f"fab_online_library_unreal_only={summary.get('unreal_only_records', 0)}")
    print(f"fab_online_library_pages={summary.get('page_count', 0)}")
    print(f"fab_online_library_roman_candidates={summary.get('roman_candidate_count', 0)}")
    print(f"fab_online_library_json={json_path}")
    print(f"fab_online_library_md={markdown_path}")
    if report.get("error"):
        print(f"fab_online_library_error={report['error']}")
        return 1
    return 0


def _run_map_quixel_library(output_dir: Path, timeout: float, quixel_roots: list[Path]) -> int:
    report = build_local_quixel_library_map(
        extra_roots=tuple(quixel_roots),
        timeout_seconds=timeout,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = write_json(output_dir / "quixel_library_map.json", report)
    markdown_path = output_dir / "quixel_library_map.md"
    markdown_path.write_text(render_local_quixel_library_map_markdown(report), encoding="utf-8")
    summary = dict(report.get("summary", {}))
    print(f"quixel_detected_roots={summary.get('detected_root_count', 0)}")
    print(f"quixel_total_assets={summary.get('total_assets', 0)}")
    print(f"quixel_bridge_api_reachable={str(bool(summary.get('bridge_api_reachable'))).lower()}")
    print(f"quixel_library_json={json_path}")
    print(f"quixel_library_md={markdown_path}")
    return 0


def _run_map_all_libraries(
    output_dir: Path,
    db_path: Path,
    data_dir: Path,
    timeout: float,
    quixel_roots: list[Path],
) -> int:
    report = build_combined_library_map(
        db_path=db_path,
        launcher_data_dir=data_dir,
        quixel_roots=tuple(quixel_roots),
        timeout_seconds=timeout,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    fab_report = dict(report.get("fab_online", {}))
    epic_online_report = dict(report.get("epic_online", {}))
    epic_local_report = dict(report.get("epic_local", {}))
    quixel_report = dict(report.get("quixel_local", {}))

    fab_json = write_json(output_dir / "fab_online_library_map.json", fab_report)
    fab_md = output_dir / "fab_online_library_map.md"
    from assetboy.providers.fab_hybrid import render_online_fab_library_map_markdown

    fab_md.write_text(render_online_fab_library_map_markdown(fab_report), encoding="utf-8")

    epic_online_json = write_json(output_dir / "epic_online_library_map.json", epic_online_report)
    epic_online_md = output_dir / "epic_online_library_map.md"
    epic_online_md.write_text(render_online_epic_library_map_markdown(epic_online_report), encoding="utf-8")

    epic_local_json = write_json(output_dir / "epic_library_report.json", epic_local_report)
    epic_local_md = output_dir / "epic_library_report.md"
    epic_local_md.write_text(render_local_epic_library_report_markdown(epic_local_report), encoding="utf-8")

    quixel_json = write_json(output_dir / "quixel_library_map.json", quixel_report)
    quixel_md = output_dir / "quixel_library_map.md"
    quixel_md.write_text(render_local_quixel_library_map_markdown(quixel_report), encoding="utf-8")

    combined_json = write_json(output_dir / "combined_library_map.json", report)
    combined_md = output_dir / "combined_library_map.md"
    combined_md.write_text(render_combined_library_map_markdown(report), encoding="utf-8")

    summary = dict(report.get("summary", {}))
    print(f"combined_fab_owned_total={summary.get('fab_owned_total', 0)}")
    print(f"combined_fab_neutral_or_mixed={summary.get('fab_neutral_or_mixed', 0)}")
    print(f"combined_epic_online_total={summary.get('epic_online_total', 0)}")
    print(f"combined_epic_local_cached={summary.get('epic_local_cached', 0)}")
    print(f"combined_epic_launcher_candidates={summary.get('epic_launcher_candidates', 0)}")
    print(f"combined_quixel_detected_roots={summary.get('quixel_detected_roots', 0)}")
    print(f"combined_quixel_total_assets={summary.get('quixel_total_assets', 0)}")
    print(f"combined_library_fab_json={fab_json}")
    print(f"combined_library_epic_online_json={epic_online_json}")
    print(f"combined_library_epic_local_json={epic_local_json}")
    print(f"combined_library_quixel_json={quixel_json}")
    print(f"combined_library_json={combined_json}")
    print(f"combined_library_md={combined_md}")
    return 0


def _run_emit_fab_dummy_project_wave(
    output_dir: Path,
    game_scope: str,
    engine_association: str,
    max_jobs: int,
) -> int:
    report = emit_fab_dummy_project_wave(
        game_scope=game_scope,
        engine_association=engine_association,
        max_jobs=max_jobs,
        output_dir=output_dir,
    )
    print(f"fab_dummy_project_do_first={len(report.get('do_first', []))}")
    print(f"fab_dummy_project_do_later={len(report.get('do_later', []))}")
    print(f"fab_dummy_project_skip={len(report.get('skip', []))}")
    print(f"fab_dummy_project_emitted_jobs={len(report.get('emitted_jobs', []))}")
    print(f"fab_dummy_project_json={output_dir / 'fab_dummy_project_wave.json'}")
    print(f"fab_dummy_project_md={output_dir / 'fab_dummy_project_wave.md'}")
    for item in report.get("emitted_jobs", []):
        print(f"fab_dummy_project_pack={item['pack_id']}")
    return 0


def _run_emit_arena_owned_wave(output_dir: Path) -> int:
    report = emit_arena_owned_wave(output_dir=output_dir)
    summary = dict(report.get("summary", {}))
    print(f"arena_owned_wave_direct_candidates={summary.get('direct_candidate_count', 0)}")
    print(f"arena_owned_wave_dummy_animation_jobs={summary.get('dummy_animation_job_count', 0)}")
    print(f"arena_owned_wave_dummy_environment_jobs={summary.get('dummy_environment_job_count', 0)}")
    print(f"arena_owned_wave_cached_animation_sources={summary.get('cached_animation_source_count', 0)}")
    print(f"arena_owned_wave_cached_environment_sources={summary.get('cached_environment_source_count', 0)}")
    print(f"arena_owned_wave_action_source_families={summary.get('action_source_count', 0)}")
    print(f"arena_owned_wave_json={output_dir / 'arena_owned_wave.json'}")
    print(f"arena_owned_wave_md={output_dir / 'arena_owned_wave.md'}")
    for pack_id, target in (report.get("roman_targets") or {}).items():
        primary = target.get("primary_direct_candidate")
        if isinstance(primary, dict):
            safe_title = str(primary.get("title", "")).encode("ascii", errors="backslashreplace").decode("ascii")
            print(f"arena_owned_wave_primary={pack_id}:{safe_title}")
    return 0


def _run_emit_arena_extraction_wave(output_dir: Path, game_scope: str) -> int:
    report = emit_arena_extraction_wave(output_dir=output_dir, game_scope=game_scope)
    summary = dict(report.get("summary", {}))
    print(f"arena_extraction_cached_extractors={summary.get('cached_extractors', 0)}")
    print(f"arena_extraction_dummy_project_extractors={summary.get('dummy_project_extractors', 0)}")
    print(f"arena_extraction_total_extractors={summary.get('total_extractors', 0)}")
    print(f"arena_extraction_json={output_dir / 'arena_extraction_wave.json'}")
    print(f"arena_extraction_md={output_dir / 'arena_extraction_wave.md'}")
    for entry in report.get("local_cached_extractors", []) or []:
        print(f"arena_extraction_cached_pack={entry.get('pack_id', '')}")
    for entry in report.get("dummy_project_extractors", []) or []:
        print(f"arena_extraction_dummy_pack={entry.get('pack_id', '')}")
    return 0


def _run_emit_useful_harvest_wave(output_dir: Path) -> int:
    report = emit_useful_harvest_wave(output_dir=output_dir)
    summary = dict(report.get("summary", {}))
    print(f"useful_harvest_fab_now={summary.get('fab_useful_now', 0)}")
    print(f"useful_harvest_epic_cached={summary.get('epic_cached_now', 0)}")
    print(f"useful_harvest_unity_owned={summary.get('unity_owned_useful', 0)}")
    print(f"useful_harvest_unity_downloaded={summary.get('unity_downloaded_ready', 0)}")
    print(f"useful_harvest_epic_launcher_next={summary.get('epic_launcher_next', 0)}")
    print(f"useful_harvest_fab_unreal_next={summary.get('fab_unreal_next', 0)}")
    print(f"useful_harvest_json={output_dir / 'useful_harvest_wave.json'}")
    print(f"useful_harvest_md={output_dir / 'useful_harvest_wave.md'}")

    extract_now = dict(report.get("extract_now", {}))
    for entry in extract_now.get("fab_neutral_owned", []) or []:
        safe_title = str(entry.get("title", "")).encode("ascii", errors="backslashreplace").decode("ascii")
        print(f"useful_harvest_fab_pick={safe_title}")
    for entry in extract_now.get("epic_cached", []) or []:
        safe_title = str(entry.get("title", "")).encode("ascii", errors="backslashreplace").decode("ascii")
        print(f"useful_harvest_epic_pick={safe_title}")
    for entry in extract_now.get("unity_downloaded", []) or []:
        safe_title = str(entry.get("name", "")).encode("ascii", errors="backslashreplace").decode("ascii")
        print(f"useful_harvest_unity_downloaded_pick={safe_title}")
    return 0


def _run_emit_useful_donor_export_wave(output_dir: Path, game_scope: str, project_path: Path) -> int:
    report = emit_useful_donor_export_wave(output_dir=output_dir, game_scope=game_scope, project_path=project_path)
    summary = dict(report.get("summary", {}))
    print(f"useful_donor_export_direct_cleanup_jobs={summary.get('direct_cleanup_jobs', 0)}")
    print(f"useful_donor_export_unity_export_jobs={summary.get('unity_export_jobs', 0)}")
    print(f"useful_donor_export_blocked_sources={summary.get('blocked_sources', 0)}")
    print(f"useful_donor_export_total_ready_jobs={summary.get('total_ready_jobs', 0)}")
    print(f"useful_donor_export_json={output_dir / 'useful_donor_export_wave.json'}")
    print(f"useful_donor_export_md={output_dir / 'useful_donor_export_wave.md'}")
    for entry in report.get("direct_cleanup_jobs", []) or []:
        print(f"useful_donor_export_direct_pack={entry.get('pack_id', '')}")
    for entry in report.get("unity_export_jobs", []) or []:
        print(f"useful_donor_export_unity_pack={entry.get('pack_id', '')}")
    for entry in report.get("blocked_sources", []) or []:
        print(f"useful_donor_export_blocked_pack={entry.get('pack_id', '')}")
    return 0


def _run_fab_download(
    listing_ref: str,
    output_path: Path,
    pack_id: str | None,
    game_scope: str,
    vault_item: str,
    engine_association: str,
    project_name: str,
    project_dir: str | None,
    job_output_dir: Path | None,
) -> int:
    from assetboy.providers.fab_hybrid import FabHybridDownloader

    downloader = FabHybridDownloader()
    listing_id = _extract_fab_listing_id(listing_ref)
    if not listing_id:
        print("fab_download_error=Unable to resolve listing id. Use --listing-id or --listing-url /listings/<id>.")
        return 2

    try:
        inspection = downloader.inspect_listing(listing_id)
        normalized_listing_id = inspection.get("listing_id", listing_id)
        route = inspection.get("route", "unknown")
        download_access = str(inspection.get("download_access", "")).strip()
        format_codes = inspection.get("format_codes") or []
        listing_title = str(inspection.get("title", "")).strip()
        safe_listing_title = listing_title.encode("ascii", errors="backslashreplace").decode("ascii")
        catalog_item_id = str(inspection.get("catalog_item_id", "")).strip()
        resolved_vault_item = _resolve_fab_vault_item(vault_item, inspection, normalized_listing_id)

        print(f"fab_download_listing_id={normalized_listing_id}")
        print(f"fab_download_route={route}")
        if download_access:
            print(f"fab_download_access={download_access}")
        print(f"fab_download_formats={','.join(format_codes)}")
        if listing_title:
            print(f"fab_download_title={safe_listing_title}")
        if catalog_item_id:
            print(f"fab_download_catalog_item_id={catalog_item_id}")

        if route == "direct":
            result = downloader.download_listing_asset(normalized_listing_id, str(output_path))
            print(f"fab_download_success={output_path}")
            print(f"fab_download_format={result['format_code']}")
            print(f"fab_download_file={result['file_name']}")
            return 0

        if route == "unreal-engine-only":
            resolved_pack_id = _resolve_fab_pack_id(pack_id, normalized_listing_id, output_path)
            source_url = f"https://www.fab.com/listings/{normalized_listing_id}"
            fallback_notes = (
                f"Fab listing {normalized_listing_id} is Unreal Engine-only on Fab; direct file download is unavailable.",
            )
            unreal_editor_detected = has_unreal_editor_installation()
            print(f"fab_download_unreal_editor_detected={'true' if unreal_editor_detected else 'false'}")
            if not unreal_editor_detected:
                print("fab_download_skipped=true")
                print("fab_download_skip_reason=unreal-engine-only-without-unreal-editor")
                print(f"fab_download_pack_id={resolved_pack_id}")
                print(f"fab_download_game_scope={game_scope}")
                print(f"fab_download_vault_item={resolved_vault_item}")
                print("fab_download_recommendation=Skipping Unreal-only Fab listing because no Unreal Engine installation was detected on this machine.")
                return 0

            uevault_output_dir = job_output_dir / "uevaultmanager" if job_output_dir is not None else None
            dummy_output_dir = job_output_dir / "epic_dummy_project" if job_output_dir is not None else None
            uevault_artifacts = emit_uevaultmanager_job(
                pack_id=resolved_pack_id,
                game_scope=game_scope,
                source_url=source_url,
                vault_item=resolved_vault_item,
                engine_association=engine_association,
                output_dir=uevault_output_dir,
                notes=fallback_notes,
            )
            print("fab_download_fallback=epic_vault")
            print(f"fab_download_pack_id={resolved_pack_id}")
            print(f"fab_download_game_scope={game_scope}")
            print(f"fab_download_vault_item={resolved_vault_item}")
            if unreal_editor_detected:
                dummy_artifacts = emit_epic_dummy_project_job(
                    pack_id=resolved_pack_id,
                    game_scope=game_scope,
                    source_url=source_url,
                    engine_association=engine_association,
                    project_name=project_name,
                    project_dir=project_dir,
                    output_dir=dummy_output_dir,
                    notes=fallback_notes,
                )
                print("fab_download_recommendation=If run_uevaultmanager.ps1 reports zero owned entries or metadata unavailable, switch to epic dummy-project fallback.")
                print(f"fab_download_recommended_script={dummy_artifacts.to_dict()['script_path']}")
            _print_epic_vault_artifacts("uevaultmanager", uevault_artifacts.to_dict())
            if unreal_editor_detected:
                _print_epic_vault_artifacts("epic_dummy_project", dummy_artifacts.to_dict())
            return 0

        print(f"fab_download_error=Listing route `{route}` is unsupported. Formats: {','.join(format_codes) or 'none'}")
        return 1
    except Exception as e:
        print(f"fab_download_error={e}")
        return 1


def _emit_fab_batch_fallback(
    *,
    item: dict[str, object],
    output_root: Path,
    fallback_jobs_root: Path,
    game_scope: str,
    engine_association: str,
    project_name: str,
    project_dir: str | None,
    unreal_editor_detected: bool,
) -> None:
    normalized_listing_id = str(item.get("listing_id", "")).strip()
    if not normalized_listing_id:
        return

    source_url = f"https://www.fab.com/listings/{normalized_listing_id}"
    fallback_pack_id = _resolve_fab_pack_id(
        None,
        normalized_listing_id,
        output_root / normalized_listing_id / f"{normalized_listing_id}.bin",
    )
    item["fallback_pack_id"] = fallback_pack_id
    item["fallback_game_scope"] = game_scope

    try:
        skip_reason = str(item.get("skip_reason", "")).strip() or "unknown"
        if skip_reason == "unreal-engine-only":
            resolved_vault_item = _resolve_fab_vault_item(
                "",
                {
                    "title": item.get("title", ""),
                    "catalog_item_id": item.get("catalog_item_id", ""),
                },
                normalized_listing_id,
            )
            uevault_output_dir = fallback_jobs_root / fallback_pack_id / "uevaultmanager"
            uevault_artifacts = emit_uevaultmanager_job(
                pack_id=fallback_pack_id,
                game_scope=game_scope,
                source_url=source_url,
                vault_item=resolved_vault_item,
                engine_association=engine_association,
                output_dir=uevault_output_dir,
                notes=("Auto-emitted from run-fab-batch for an Unreal-only listing.",),
            )
            uevault_payload = uevault_artifacts.to_dict()
            item["fallback_uevault_job_spec"] = uevault_payload["job_spec_path"]
            item["fallback_uevault_script"] = uevault_payload["script_path"]
            item["fallback_uevault_job_spec_exists"] = Path(str(uevault_payload["job_spec_path"])).exists()
            item["fallback_uevault_script_exists"] = Path(str(uevault_payload["script_path"])).exists()
            item["next_action"] = f"pwsh -File \"{uevault_payload['script_path']}\""

            if unreal_editor_detected:
                dummy_output_dir = fallback_jobs_root / fallback_pack_id / "epic_dummy_project"
                dummy_artifacts = emit_epic_dummy_project_job(
                    pack_id=fallback_pack_id,
                    game_scope=game_scope,
                    source_url=source_url,
                    engine_association=engine_association,
                    project_name=project_name,
                    project_dir=project_dir,
                    output_dir=dummy_output_dir,
                    notes=("Auto-emitted fallback when Unreal editor is installed.",),
                )
                dummy_payload = dummy_artifacts.to_dict()
                item["fallback_dummy_project_job_spec"] = dummy_payload["job_spec_path"]
                item["fallback_dummy_project_script"] = dummy_payload["script_path"]
                item["fallback_dummy_project_job_spec_exists"] = Path(str(dummy_payload["job_spec_path"])).exists()
                item["fallback_dummy_project_script_exists"] = Path(str(dummy_payload["script_path"])).exists()
            return

        title_hint = str(item.get("title", "")).strip()
        fallback_notes = (
            f"Auto-emitted from run-fab-batch because listing could not be downloaded automatically ({skip_reason}).",
        )
        browser_artifacts = emit_browser_automation_job(
            source_adapter="fab",
            runtime=BrowserRuntime.PLAYWRIGHT_MCP,
            pack_id=fallback_pack_id,
            game_scope=game_scope,
            source_url=source_url,
            search_terms=(title_hint or normalized_listing_id,),
            login_required=True,
            output_dir=fallback_jobs_root / fallback_pack_id / "browser_claim",
            notes=fallback_notes,
        )
        item["fallback_browser_job_spec"] = str(browser_artifacts.job_spec_path)
        item["fallback_browser_job_spec_exists"] = Path(str(browser_artifacts.job_spec_path)).exists()
        item["fallback_browser_runtime"] = BrowserRuntime.PLAYWRIGHT_MCP.value
        item["next_action"] = (
            "python scripts/cli.py asset-factory run-browser-job --job-spec "
            f"\"{browser_artifacts.job_spec_path}\" --execute --retries 2"
        )
    except Exception as fallback_exc:
        item["fallback_error"] = str(fallback_exc)


def _run_fab_batch(
    listing_file: Path,
    output_dir: Path,
    *,
    game_scope: str,
    engine_association: str,
    project_name: str,
    project_dir: str | None,
) -> int:
    from assetboy.providers.fab_hybrid import FabHybridDownloader

    downloader = FabHybridDownloader()
    output_root = ensure_dir(output_dir)
    download_root = ensure_dir(output_root / "downloads")
    fallback_jobs_root = ensure_dir(output_root / "fallback_jobs")
    summary_path = output_root / "fab_batch_summary.json"
    skip_report_path = output_root / "fab_batch_skipped.json"
    fallback_actions_path = output_root / "fab_batch_fallback_actions.json"
    fallback_actions_md_path = output_root / "fab_batch_fallback_actions.md"
    unreal_editor_detected = has_unreal_editor_installation()

    refs = _read_fab_batch_refs(listing_file)
    results: list[dict[str, object]] = []

    for listing_ref in refs:
        listing_id = _extract_fab_listing_id(listing_ref)
        if not listing_id:
            results.append(
                {
                    "listing_ref": listing_ref,
                    "listing_id": "",
                    "status": "failed",
                    "error": "Unable to resolve listing id. Use a Fab listing id or URL containing /listings/<id>.",
                }
            )
            continue

        item: dict[str, object] = {
            "listing_ref": listing_ref,
            "listing_id": listing_id,
        }
        try:
            inspection = downloader.inspect_listing(listing_id)
            normalized_listing_id = str(inspection.get("listing_id", listing_id)).strip() or listing_id
            route = str(inspection.get("route", "unknown")).strip() or "unknown"
            item["listing_id"] = normalized_listing_id
            item["route"] = route
            item["download_access"] = str(inspection.get("download_access", "")).strip()
            item["title"] = str(inspection.get("title", "")).strip()
            item["catalog_item_id"] = str(inspection.get("catalog_item_id", "")).strip()
            item["owned"] = bool(inspection.get("owned", False))
            item["is_free"] = bool(inspection.get("is_free", False))

            if route == "direct" and item["download_access"] == "batch-direct":
                output_path = _choose_fab_batch_output_path(inspection, normalized_listing_id, download_root)
                ensure_dir(output_path.parent)
                try:
                    download_result = downloader.download_listing_asset(normalized_listing_id, str(output_path))
                    item["status"] = "downloaded"
                    item["format_code"] = str(download_result.get("format_code", "")).strip()
                    item["file_name"] = str(download_result.get("file_name", "")).strip()
                    item["output_path"] = str(output_path)
                except Exception as download_exc:
                    item["status"] = "skipped"
                    item["skip_reason"] = "download-failed"
                    item["download_error"] = str(download_exc)
                    _emit_fab_batch_fallback(
                        item=item,
                        output_root=output_root,
                        fallback_jobs_root=fallback_jobs_root,
                        game_scope=game_scope,
                        engine_association=engine_association,
                        project_name=project_name,
                        project_dir=project_dir,
                        unreal_editor_detected=unreal_editor_detected,
                    )
            else:
                item["status"] = "skipped"
                if route == "unreal-engine-only":
                    item["skip_reason"] = "unreal-engine-only"
                elif item["download_access"] == "library-or-purchase-required":
                    item["skip_reason"] = "library-or-purchase-required"
                else:
                    item["skip_reason"] = f"unsupported-route:{route}"

                _emit_fab_batch_fallback(
                    item=item,
                    output_root=output_root,
                    fallback_jobs_root=fallback_jobs_root,
                    game_scope=game_scope,
                    engine_association=engine_association,
                    project_name=project_name,
                    project_dir=project_dir,
                    unreal_editor_detected=unreal_editor_detected,
                )
        except Exception as exc:
            item["status"] = "failed"
            item["error"] = str(exc)
        results.append(item)

    downloaded = sum(1 for item in results if item.get("status") == "downloaded")
    skipped = sum(1 for item in results if item.get("status") == "skipped")
    failed = sum(1 for item in results if item.get("status") == "failed")
    fallback_generated = sum(1 for item in results if str(item.get("fallback_pack_id", "")).strip())
    fallback_failed = sum(1 for item in results if str(item.get("fallback_error", "")).strip())
    generated_at = datetime.now(timezone.utc).isoformat()

    summary_payload = {
        "generated_at": generated_at,
        "listing_file": str(listing_file),
        "output_dir": str(output_root),
        "downloads_dir": str(download_root),
        "total": len(results),
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "fallback_jobs_root": str(fallback_jobs_root),
        "fallback_generated": fallback_generated,
        "fallback_failed": fallback_failed,
        "unreal_editor_detected": unreal_editor_detected,
        "items": results,
        "skip_report_path": str(skip_report_path),
        "fallback_actions_path": str(fallback_actions_path),
        "fallback_actions_markdown_path": str(fallback_actions_md_path),
    }
    skipped_items = [item for item in results if item.get("status") == "skipped"]
    skip_payload = {
        "generated_at": generated_at,
        "listing_file": str(listing_file),
        "total_skipped": len(skipped_items),
        "items": skipped_items,
    }

    fallback_actions: list[dict[str, object]] = []
    for item in skipped_items:
        action: dict[str, object] = {
            "listing_ref": item.get("listing_ref", ""),
            "listing_id": item.get("listing_id", ""),
            "skip_reason": item.get("skip_reason", ""),
            "fallback_pack_id": item.get("fallback_pack_id", ""),
            "fallback_game_scope": item.get("fallback_game_scope", ""),
            "fallback_error": item.get("fallback_error", ""),
            "commands": [],
            "required_files": [],
            "ready": False,
        }
        commands = action["commands"]
        required_files = action["required_files"]
        if item.get("fallback_uevault_script"):
            script_path = Path(str(item["fallback_uevault_script"]))
            if isinstance(commands, list):
                commands.append(f'pwsh -NoProfile -ExecutionPolicy Bypass -File "{script_path}"')
            if isinstance(required_files, list):
                required_files.append(
                    {
                        "kind": "uevault_script",
                        "path": str(script_path),
                        "exists": script_path.exists(),
                    }
                )
        if item.get("fallback_browser_job_spec"):
            browser_job_path = Path(str(item["fallback_browser_job_spec"]))
            if isinstance(commands, list):
                commands.append(
                    "python scripts/cli.py asset-factory run-browser-job --job-spec "
                    f"\"{browser_job_path}\" --execute --retries 2"
                )
            if isinstance(required_files, list):
                required_files.append(
                    {
                        "kind": "browser_job_spec",
                        "path": str(browser_job_path),
                        "exists": browser_job_path.exists(),
                    }
                )
        if item.get("fallback_dummy_project_script"):
            dummy_script_path = Path(str(item["fallback_dummy_project_script"]))
            if isinstance(commands, list):
                commands.append(f'pwsh -NoProfile -ExecutionPolicy Bypass -File "{dummy_script_path}"')
            if isinstance(required_files, list):
                required_files.append(
                    {
                        "kind": "dummy_project_script",
                        "path": str(dummy_script_path),
                        "exists": dummy_script_path.exists(),
                    }
                )
        if isinstance(required_files, list):
            action["ready"] = bool(required_files) and all(
                bool(entry.get("exists", False))
                for entry in required_files
                if isinstance(entry, dict)
            )
        fallback_actions.append(action)

    fallback_actions_payload = {
        "generated_at": generated_at,
        "listing_file": str(listing_file),
        "total_actions": len(fallback_actions),
        "actions": fallback_actions,
    }

    write_json(summary_path, summary_payload)
    write_json(skip_report_path, skip_payload)
    write_json(fallback_actions_path, fallback_actions_payload)
    fallback_actions_md_path.write_text(
        _render_fab_fallback_actions_markdown(fallback_actions_payload),
        encoding="utf-8",
    )

    print(f"fab_batch_listing_file={listing_file}")
    print(f"fab_batch_output_dir={output_root}")
    print(f"fab_batch_downloads_dir={download_root}")
    print(f"fab_batch_total={len(results)}")
    print(f"fab_batch_downloaded={downloaded}")
    print(f"fab_batch_skipped={skipped}")
    print(f"fab_batch_failed={failed}")
    print(f"fab_batch_fallback_generated={fallback_generated}")
    print(f"fab_batch_fallback_failed={fallback_failed}")
    print(f"fab_batch_fallback_root={fallback_jobs_root}")
    print(f"fab_batch_summary_path={summary_path}")
    print(f"fab_batch_skip_report_path={skip_report_path}")
    print(f"fab_batch_fallback_actions_path={fallback_actions_path}")
    print(f"fab_batch_fallback_actions_md={fallback_actions_md_path}")
    return 0


def _fallback_action_required_paths(action: dict[str, object], *, kind: str) -> list[Path]:
    required_files = action.get("required_files")
    if not isinstance(required_files, list):
        return []

    paths: list[Path] = []
    for entry in required_files:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("kind", "")).strip() != kind:
            continue
        path_text = str(entry.get("path", "")).strip()
        if not path_text:
            continue
        paths.append(Path(path_text))
    return paths


def _truncate_console_text(text: str, *, limit: int = 4000) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "...<truncated>"


def _run_fallback_pwsh_script(*, script_path: Path, timeout_sec: float) -> dict[str, object]:
    command = [
        "pwsh",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except FileNotFoundError as exc:
        return {
            "status": "failed",
            "exit_code": None,
            "error": f"pwsh is not available: {exc}",
            "stdout": "",
            "stderr": "",
            "command": " ".join(command),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "failed",
            "exit_code": None,
            "error": f"pwsh script timed out after {timeout_sec} seconds.",
            "stdout": _truncate_console_text(exc.stdout or ""),
            "stderr": _truncate_console_text(exc.stderr or ""),
            "command": " ".join(command),
        }

    status = "executed" if completed.returncode == 0 else "failed"
    return {
        "status": status,
        "exit_code": completed.returncode,
        "error": "" if completed.returncode == 0 else f"pwsh exited with code {completed.returncode}.",
        "stdout": _truncate_console_text(completed.stdout),
        "stderr": _truncate_console_text(completed.stderr),
        "command": " ".join(command),
    }


def _load_json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{label} is malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}."
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must contain a top-level JSON object.")
    return dict(payload)


def _set_if_missing(payload: dict[str, object], key: str, value: object) -> bool:
    if value is None:
        return False
    normalized_value = value
    if isinstance(normalized_value, str):
        normalized_value = normalized_value.strip()
        if not normalized_value:
            return False
    existing = payload.get(key)
    if isinstance(existing, str):
        existing = existing.strip()
    if existing is None or (isinstance(existing, str) and not existing):
        payload[key] = normalized_value
        return True
    return False


def _supported_payload_files(root_dir: Path) -> list[Path]:
    if not root_dir.exists():
        return []
    return [
        path
        for path in sorted(root_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]


def _relative_payload_name(path: Path, *, source_dir: Path) -> str:
    try:
        return path.resolve().relative_to(source_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def _artifact_timestamp(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _read_text_if_exists(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def _html_to_text(html_text: str) -> str:
    text = str(html_text or "")
    if not text.strip():
        return ""
    text = re.sub(r"(?is)<(script|style)\b.*?>.*?</\1>", "\n", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|section|article|li|tr|td|th|h[1-6])\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = html.unescape(text)
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return 0, 0
    try:
        width, height = struct.unpack(">II", data[16:24])
    except struct.error:
        return 0, 0
    return int(width), int(height)


def _browser_screenshot_metadata(path: Path | None) -> dict[str, object]:
    if path is None or not path.exists() or not path.is_file():
        return {}
    payload: dict[str, object] = {
        "filename": path.name,
        "size_bytes": int(path.stat().st_size),
        "captured_at": _artifact_timestamp(path),
    }
    if path.suffix.lower() == ".png":
        width, height = _png_dimensions(path)
        if width > 0 and height > 0:
            payload["width"] = width
            payload["height"] = height
    return payload


def _append_pipe_note(existing: object, addition: str) -> str:
    base = str(existing or "").strip()
    note = str(addition or "").strip()
    if not note:
        return base
    if not base:
        return note
    segments = [segment.strip() for segment in base.split("|") if segment.strip()]
    if any(segment.lower() == note.lower() for segment in segments):
        return base
    return f"{base} | {note}"


def _append_sentence_note(existing: object, addition: str) -> str:
    base = str(existing or "").strip()
    note = str(addition or "").strip()
    if not note:
        return base
    if not base:
        return note
    if note.lower() in base.lower():
        return base
    if base.endswith("."):
        return f"{base} {note}"
    return f"{base}. {note}"


def _safe_result_text_attr(result: object, name: str) -> str:
    if hasattr(result, "__dict__") and name in vars(result):
        value = vars(result).get(name)
    else:
        try:
            value = getattr(result, name, "")
        except Exception:
            value = ""
    if isinstance(value, Path):
        return str(value)
    return value.strip() if isinstance(value, str) else ""


def _parse_browser_metadata_text(text: str) -> dict[str, object]:
    normalized_text = str(text or "").replace("\r", "")
    lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
    if not lines:
        return {}

    def pick_labeled_value(labels: tuple[str, ...]) -> str:
        lowered_labels = tuple(label.strip().lower() for label in labels if label.strip())
        for index, line in enumerate(lines):
            lowered = line.lower()
            for label in lowered_labels:
                if lowered.startswith(label + ":"):
                    return line[len(label) + 1 :].strip()
                if lowered == label and index + 1 < len(lines):
                    return lines[index + 1].strip()
        return ""

    def snippet_around(tokens: tuple[str, ...]) -> str:
        lowered_tokens = tuple(token.strip().lower() for token in tokens if token.strip())
        for line in lines:
            lowered = line.lower()
            if any(token in lowered for token in lowered_tokens):
                return line
        return ""

    payload: dict[str, object] = {}
    first_url_match = re.search(r"https?://\S+", normalized_text)
    if first_url_match:
        payload["source_url"] = first_url_match.group(0).rstrip("),.;")

    title = pick_labeled_value(("Title", "Asset name", "Listing title"))
    if title:
        payload["title"] = title

    author = pick_labeled_value(("Publisher", "Seller", "Creator", "Vendor", "Author"))
    if author:
        payload["author_or_vendor"] = author

    license_name = pick_labeled_value(("Selected license", "License type", "License terms", "License"))
    if license_name:
        payload["license"] = license_name

    license_snapshot = pick_labeled_value(("License snapshot", "Rights snapshot", "License note"))
    if not license_snapshot:
        license_snapshot = snippet_around(
            (
                "fab standard license",
                "creative commons",
                "cc-by",
                "cc0",
                "standard unity asset store eula",
                "license",
                "eula",
            )
        )
    if license_snapshot:
        payload["license_snapshot"] = license_snapshot

    version = pick_labeled_value(("Latest version", "Version"))
    if version:
        payload["version"] = version

    entitlement = pick_labeled_value(("Entitlement note", "Entitlement", "Ownership", "Claim status"))
    if entitlement:
        payload["entitlement_note"] = entitlement

    return payload


def _metadata_value_missing(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, dict):
        return not bool(value)
    if isinstance(value, (list, tuple, set)):
        return not bool(value)
    return False


def _merge_browser_metadata_missing(target: dict[str, object], incoming: dict[str, object]) -> None:
    for key, incoming_value in incoming.items():
        if _metadata_value_missing(target.get(key)):
            target[key] = incoming_value
            continue
        existing_value = target.get(key)
        if isinstance(existing_value, dict) and isinstance(incoming_value, dict):
            _merge_browser_metadata_missing(existing_value, incoming_value)


def _collect_browser_artifact_metadata(
    *,
    source_dir: Path,
    artifacts_dir: Path | None,
    source_adapter: str,
    source_url: str,
) -> tuple[dict[str, object], set[str], dict[str, str]]:
    metadata: dict[str, object] = {}
    hydrated_from: set[str] = set()
    artifact_paths: dict[str, str] = {}

    provenance_notes_path = source_dir / "provenance.txt"
    provenance_notes = _parse_browser_metadata_text(_read_text_if_exists(provenance_notes_path))
    if provenance_notes:
        for key, value in provenance_notes.items():
            _set_if_missing(metadata, str(key), value)
        hydrated_from.add("browser_notes")
    if provenance_notes_path.exists():
        artifact_paths["browser_notes_path"] = str(provenance_notes_path)

    page_metadata_path = artifacts_dir / "page_metadata.json" if artifacts_dir is not None else None
    if page_metadata_path is not None and page_metadata_path.exists():
        page_metadata = _load_json_object(page_metadata_path, label=f"browser page metadata '{page_metadata_path}'")
        for key, value in page_metadata.items():
            _set_if_missing(metadata, str(key), value)
        hydrated_from.add("page_metadata")
        artifact_paths["page_metadata_path"] = str(page_metadata_path)

    page_text_path = artifacts_dir / "page_text.txt" if artifacts_dir is not None else None
    page_text_metadata = _parse_browser_metadata_text(_read_text_if_exists(page_text_path))
    if page_text_metadata:
        for key, value in page_text_metadata.items():
            _set_if_missing(metadata, str(key), value)
        hydrated_from.add("page_text")
    if page_text_path is not None and page_text_path.exists():
        artifact_paths["page_text_path"] = str(page_text_path)

    page_dom_text_path = artifacts_dir / "page_dom.txt" if artifacts_dir is not None else None
    page_dom_text_metadata = _parse_browser_metadata_text(_read_text_if_exists(page_dom_text_path))
    if page_dom_text_metadata:
        for key, value in page_dom_text_metadata.items():
            _set_if_missing(metadata, str(key), value)
        hydrated_from.add("page_dom_text")
    if page_dom_text_path is not None and page_dom_text_path.exists():
        artifact_paths["page_dom_text_path"] = str(page_dom_text_path)

    page_dom_path = artifacts_dir / "page_dom.html" if artifacts_dir is not None else None
    if page_dom_path is not None and page_dom_path.exists():
        artifact_paths["page_dom_path"] = str(page_dom_path)
        hydrated_from.add("page_dom")
        page_dom_text = _html_to_text(_read_text_if_exists(page_dom_path))
        if page_dom_text:
            dom_metadata = _parse_browser_metadata_text(page_dom_text)
            for key, value in dom_metadata.items():
                _set_if_missing(metadata, str(key), value)
            try:
                from assetboy.execution.playwright_runner import _augment_browser_metadata_from_page_text, _extract_unity_asset_id

                provider_evidence = metadata.get("provider_evidence")
                provider_product_id = ""
                if isinstance(provider_evidence, dict):
                    provider_product_id = str(provider_evidence.get("product_id", "")).strip()
                if not provider_product_id and source_adapter == "unity_asset_store":
                    provider_product_id = _extract_unity_asset_id({"source_url": source_url})
                metadata = _augment_browser_metadata_from_page_text(
                    metadata,
                    adapter=source_adapter,
                    product_id=provider_product_id,
                    page_text=page_dom_text,
                )
            except Exception:
                pass
            hydrated_from.add("page_dom_metadata")

    page_dom_metadata_path = artifacts_dir / "page_dom_metadata.json" if artifacts_dir is not None else None
    if page_dom_metadata_path is not None and page_dom_metadata_path.exists():
        artifact_paths["page_dom_metadata_path"] = str(page_dom_metadata_path)
        dom_metadata = _load_json_object(
            page_dom_metadata_path,
            label=f"browser dom metadata '{page_dom_metadata_path}'",
        )
        _merge_browser_metadata_missing(metadata, dom_metadata)
        hydrated_from.add("page_dom_sidecar")

    page_screenshot_meta_path = artifacts_dir / "page_screenshot_meta.json" if artifacts_dir is not None else None
    if page_screenshot_meta_path is not None and page_screenshot_meta_path.exists():
        artifact_paths["page_screenshot_meta_path"] = str(page_screenshot_meta_path)
        screenshot_sidecar = _load_json_object(
            page_screenshot_meta_path,
            label=f"browser screenshot metadata '{page_screenshot_meta_path}'",
        )
        if isinstance(screenshot_sidecar, dict) and screenshot_sidecar:
            _set_if_missing(metadata, "page_screenshot_meta", screenshot_sidecar)
            hydrated_from.add("page_screenshot_sidecar")

    page_screenshot_path = artifacts_dir / "page_screenshot.png" if artifacts_dir is not None else None
    if page_screenshot_path is not None and page_screenshot_path.exists():
        artifact_paths["page_screenshot_path"] = str(page_screenshot_path)
        hydrated_from.add("page_screenshot")
        existing_screenshot_meta = metadata.get("page_screenshot_meta")
        if not isinstance(existing_screenshot_meta, dict) or not existing_screenshot_meta:
            screenshot_metadata = _browser_screenshot_metadata(page_screenshot_path)
            if screenshot_metadata:
                metadata.setdefault("page_screenshot_meta", screenshot_metadata)
                hydrated_from.add("page_screenshot_metadata")

    return metadata, hydrated_from, artifact_paths


def _append_browser_evidence_refs(note: str, artifact_paths: dict[str, str]) -> str:
    text = str(note or "").strip()
    if not text:
        return text
    evidence_files = [
        Path(path).name
        for key in (
            "page_metadata_path",
            "page_text_path",
            "page_dom_path",
            "page_dom_text_path",
            "page_dom_metadata_path",
            "page_screenshot_path",
            "page_screenshot_meta_path",
        )
        for path in [artifact_paths.get(key, "")]
        if str(path).strip()
    ]
    if not evidence_files:
        return text
    evidence_suffix = "Evidence files: " + ", ".join(evidence_files) + "."
    if evidence_suffix.lower() in text.lower():
        return text
    if text.endswith("."):
        return f"{text} {evidence_suffix}"
    return f"{text}. {evidence_suffix}"


def _browser_metadata_value(browser_metadata: dict[str, object], key: str) -> object:
    if key in browser_metadata:
        return browser_metadata.get(key)
    nested = browser_metadata.get("provider_evidence")
    if isinstance(nested, dict):
        return nested.get(key)
    return None


def _browser_evidence_lines(browser_metadata: dict[str, object], *keys: str) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for key in keys:
        value = _browser_metadata_value(browser_metadata, key)
        candidates: list[object]
        if isinstance(value, list):
            candidates = list(value)
        else:
            candidates = [value]
        for candidate in candidates:
            text = str(candidate or "").strip()
            normalized = text.lower()
            if not text or normalized in seen:
                continue
            seen.add(normalized)
            lines.append(text)
    return lines


def _browser_license_value(browser_metadata: dict[str, object], *, source_adapter: str) -> str:
    explicit = str(browser_metadata.get("license", "")).strip()
    if explicit:
        return explicit

    evidence_lines = _browser_evidence_lines(browser_metadata, "license_lines", "license_snapshot", "page_text_excerpt")
    normalized_adapter = canonical_source_adapter_id(source_adapter)
    for line in evidence_lines:
        lowered = line.lower()
        if normalized_adapter == "unity_asset_store" and "standard unity asset store eula" in lowered:
            return "Standard Unity Asset Store EULA"
        if normalized_adapter == "fab" and "fab standard license" in lowered:
            return "Fab Standard License"
        if "creative commons attribution" in lowered or "creative commons - attribution" in lowered or "cc-by" in lowered:
            return "CC-BY"
        if "creative commons" in lowered and "cc0" in lowered:
            return "CC0"
        if lowered.startswith("license type:"):
            return line.split(":", 1)[1].strip()
        if lowered.startswith("license:"):
            return line.split(":", 1)[1].strip()
    return ""


def _browser_license_snapshot(browser_metadata: dict[str, object]) -> str:
    explicit = str(browser_metadata.get("license_snapshot", "")).strip()
    license_value = str(_browser_metadata_value(browser_metadata, "license") or "").strip()
    if explicit:
        if explicit.lower() in {"license", "license type", "license terms", "selected license"} and license_value:
            return f"{explicit}: {license_value}"
        return explicit
    evidence_lines = _browser_evidence_lines(browser_metadata, "license_lines")
    if evidence_lines:
        first_line = evidence_lines[0]
        if first_line.lower() in {"license", "license type", "license terms", "selected license"} and license_value:
            return f"{first_line}: {license_value}"
        return first_line
    if license_value:
        return f"License: {license_value}"
    return ""


def _browser_screenshot_note(browser_metadata: dict[str, object]) -> str:
    payload = browser_metadata.get("page_screenshot_meta")
    if not isinstance(payload, dict):
        return ""
    filename = str(payload.get("filename", "")).strip()
    if not filename:
        return ""
    fragments = [f"Browser screenshot: {filename}"]
    width = int(payload.get("width", 0) or 0)
    height = int(payload.get("height", 0) or 0)
    if width > 0 and height > 0:
        fragments.append(f"{width}x{height}")
    size_bytes = int(payload.get("size_bytes", 0) or 0)
    if size_bytes > 0:
        fragments.append(f"{size_bytes} bytes")
    captured_at = str(payload.get("captured_at", "")).strip()
    if captured_at:
        fragments.append(f"captured {captured_at}")
    return " ".join(fragments)


def _browser_entitlement_note(browser_metadata: dict[str, object], *, source_adapter: str) -> str:
    normalized_adapter = canonical_source_adapter_id(source_adapter)
    if normalized_adapter == "unity_asset_store":
        evidence: list[str] = []
        if bool(browser_metadata.get("purchased", False)):
            evidence.append("listing showed purchased state")
        if bool(browser_metadata.get("openInUnity", False)):
            evidence.append("listing exposed Open in Unity")
        if bool(browser_metadata.get("myAssetsContainsProduct", False)):
            evidence.append("myAssets local storage contained the product id")
        ownership_lines = _browser_evidence_lines(browser_metadata, "ownership_lines")
        if not evidence and ownership_lines:
            evidence.extend(f"browser text captured '{line}'" for line in ownership_lines[:3])
        visible_actions = _browser_evidence_lines(browser_metadata, "visible_actions")
        if visible_actions:
            for token, label in (
                ("open in unity", "listing exposed Open in Unity"),
                ("add to my assets", "listing exposed Add to My Assets"),
            ):
                if any(token in item.lower() for item in visible_actions) and label not in evidence:
                    evidence.append(label)
        if evidence:
            return "Unity Asset Store browser capture: " + "; ".join(evidence) + "."

    if normalized_adapter == "fab":
        for key in ("download_action", "ownership_action", "claim_action"):
            action_label = str(browser_metadata.get(key, "")).strip()
            if action_label:
                return f"Fab browser capture showed action '{action_label}'."
        ownership_lines = _browser_evidence_lines(browser_metadata, "ownership_lines", "visible_actions")
        if ownership_lines:
            return f"Fab browser capture showed '{ownership_lines[0]}'."

    return ""


def _provenance_license_requires_entitlement(license_name: str) -> bool:
    lowered = str(license_name or "").strip().lower()
    if not lowered:
        return True
    open_tokens = (
        "cc0",
        "public domain",
        "public-domain",
        "ofl",
        "mit",
        "bsd",
        "apache",
        "creative commons 0",
        "cc by",
        "cc-by",
    )
    return not any(token in lowered for token in open_tokens)


def _build_browser_provenance_confidence(
    *,
    normalized_provenance: dict[str, object],
    browser_metadata: dict[str, object],
    artifact_paths: dict[str, str],
    validation_errors: list[str],
    missing_required_fields: list[str],
    payload_file_count: int,
) -> dict[str, object]:
    score = 0
    reasons: list[str] = []

    artifact_files = [
        str(Path(path).name).strip()
        for key in (
            "page_metadata_path",
            "page_text_path",
            "page_dom_path",
            "page_dom_text_path",
            "page_dom_metadata_path",
            "page_screenshot_path",
            "page_screenshot_meta_path",
            "browser_notes_path",
        )
        for path in [artifact_paths.get(key, "")]
        if str(path).strip()
    ]
    has_artifact_evidence = bool(artifact_files)
    if has_artifact_evidence:
        score += 10
    else:
        reasons.append("browser_artifacts_missing")

    source_url = str(normalized_provenance.get("source_url", "")).strip()
    source_evidence = bool(
        source_url
        and (
            str(browser_metadata.get("source_url", "")).strip()
            or str(browser_metadata.get("url", "")).strip()
            or has_artifact_evidence
        )
    )
    if source_evidence:
        score += 15
    else:
        reasons.append("source_url_not_backed_by_browser_evidence")

    author_or_vendor = str(normalized_provenance.get("author_or_vendor", "")).strip()
    author_evidence = bool(
        author_or_vendor
        and (
            str(_browser_metadata_value(browser_metadata, "author_or_vendor") or "").strip()
            or str(_browser_metadata_value(browser_metadata, "publisher") or "").strip()
            or str(_browser_metadata_value(browser_metadata, "seller") or "").strip()
            or str(_browser_metadata_value(browser_metadata, "vendor") or "").strip()
        )
    )
    if author_evidence:
        score += 20
    else:
        reasons.append("author_or_vendor_not_backed_by_browser_evidence")

    license_name = str(normalized_provenance.get("license", "")).strip()
    license_snapshot = str(normalized_provenance.get("license_snapshot", "")).strip()
    license_evidence_lines = _browser_evidence_lines(browser_metadata, "license_lines", "license_snapshot", "page_text_excerpt")
    license_evidence = bool(
        license_name
        and (
            str(_browser_metadata_value(browser_metadata, "license") or "").strip()
            or license_evidence_lines
        )
    )
    if license_evidence:
        score += 25
    else:
        reasons.append("license_not_backed_by_browser_evidence")
    if license_snapshot:
        score += 10
    else:
        reasons.append("license_snapshot_missing")

    downloaded_filename = str(normalized_provenance.get("downloaded_filename", "")).strip()
    payload_detected = payload_file_count > 0 and bool(downloaded_filename)
    if payload_detected:
        score += 10
    else:
        reasons.append("download_payload_not_detected")

    acquired_at = str(normalized_provenance.get("acquired_at", "")).strip()
    if acquired_at:
        score += 5
    else:
        reasons.append("acquired_at_missing")

    entitlement_required = _provenance_license_requires_entitlement(license_name)
    entitlement_note = str(normalized_provenance.get("entitlement_note", "")).strip()
    ownership_evidence_lines = _browser_evidence_lines(browser_metadata, "ownership_lines", "visible_actions")
    entitlement_evidence = bool(entitlement_note and (ownership_evidence_lines or has_artifact_evidence))
    if entitlement_required:
        if entitlement_note and entitlement_evidence:
            score += 15
        elif entitlement_note:
            score += 8
            reasons.append("entitlement_note_not_backed_by_browser_evidence")
        else:
            reasons.append("entitlement_note_missing_for_store_gated_license")
    else:
        score += 15

    score = max(0, min(100, score))
    if score >= 85:
        band = "high"
    elif score >= 65:
        band = "medium"
    else:
        band = "low"

    register_packet_ready = (
        not validation_errors
        and not missing_required_fields
        and score >= 70
        and source_evidence
        and author_evidence
        and license_evidence
        and payload_detected
        and (not entitlement_required or (entitlement_note and entitlement_evidence))
    )

    if register_packet_ready:
        action = "register_packet"
    elif validation_errors or missing_required_fields:
        action = "fill_required_fields_and_rerun_hydrate"
    else:
        action = "capture_browser_evidence_or_fill_provenance_fields"

    unique_reasons = list(dict.fromkeys(reasons))
    return {
        "score": score,
        "band": band,
        "register_packet_ready": register_packet_ready,
        "needs_operator_fill": not register_packet_ready,
        "action": action,
        "reasons": unique_reasons,
        "required_missing_fields": list(missing_required_fields),
        "validation_error_count": len(validation_errors),
        "evidence": {
            "artifact_file_count": len(artifact_files),
            "artifact_files": artifact_files,
            "source_evidence": source_evidence,
            "author_evidence": author_evidence,
            "license_evidence": license_evidence,
            "entitlement_required": entitlement_required,
            "entitlement_evidence": (not entitlement_required) or entitlement_evidence,
            "payload_detected": payload_detected,
        },
    }


def _postprocess_browser_job(
    *,
    job_spec_path: Path,
    artifacts_dir: Path | None,
    last_url: str,
    fallback_pack_id: str,
    fallback_game_scope: str,
    hydrate_provenance: bool,
    prepare_pack: bool,
    cleanup_mode: str,
    asset_kind: str,
    animated: bool,
    packet_status: str,
    overwrite_packet: bool,
    verify_hashes: bool,
    auto_intake: bool,
) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "executed",
        "error": "",
    }
    if not (hydrate_provenance or prepare_pack or auto_intake):
        return result

    hydration_payload = _hydrate_browser_source_provenance(
        job_spec_path=job_spec_path,
        artifacts_dir=artifacts_dir,
        last_url=last_url,
        fallback_pack_id=fallback_pack_id,
        fallback_game_scope=fallback_game_scope,
    )
    result["hydration"] = hydration_payload
    result["source_dir"] = str(hydration_payload["source_dir"])
    result["register_packet_ready"] = bool(hydration_payload.get("register_packet_ready"))
    result["provenance_confidence"] = dict(hydration_payload.get("provenance_confidence", {}))

    if str(hydration_payload.get("status", "")).strip() != "completed":
        result["status"] = "pending_manual"
        result["error"] = (
            "Hydrated provenance is incomplete. "
            + "; ".join(str(item) for item in hydration_payload.get("validation_errors", [])[:3])
        ).strip()
        return result

    if not bool(hydration_payload.get("register_packet_ready")):
        confidence = dict(hydration_payload.get("provenance_confidence", {}))
        reasons = [str(item).strip() for item in confidence.get("reasons", []) if str(item).strip()]
        result["operator_action_required"] = True
        result["operator_action"] = str(confidence.get("action", "")).strip()
        result["operator_reasons"] = reasons

    if prepare_pack:
        prepare_result = _prepare_fallback_pack(
            pack_id=str(hydration_payload["pack_id"]),
            game_scope=str(hydration_payload["game_scope"]),
            source_dir=Path(str(hydration_payload["source_dir"])),
            cleanup_mode=cleanup_mode,
            asset_kind=asset_kind,
            animated=animated,
            packet_status=packet_status,
            overwrite_packet=overwrite_packet,
            verify_hashes=verify_hashes,
        )
        result["prepare_pack"] = prepare_result
        result["prepare_pack_current_state"] = str(prepare_result.get("current_state", "")).strip()
        if str(prepare_result.get("status", "")).strip() == "failed":
            result["status"] = "failed"
            result["error"] = str(prepare_result.get("error", "prepare-pack failed")).strip()
            return result
        if str(prepare_result.get("current_state", "")).strip() != "packeted":
            result["status"] = "pending_manual"
            result["error"] = (
                f"prepare-pack stopped at current_state='{prepare_result.get('current_state', '')}'. "
                f"next_step={prepare_result.get('next_step', '')}"
            ).strip()
            return result

    if auto_intake:
        auto_intake_result = _auto_intake_one_pack(
            pack_id=str(hydration_payload["pack_id"]),
            game_scope=str(hydration_payload["game_scope"]),
            dry_run=False,
        )
        result["auto_intake"] = auto_intake_result
        if auto_intake_result.get("handoff_receipt_path"):
            result["handoff_receipt_path"] = str(auto_intake_result["handoff_receipt_path"])
        if not bool(auto_intake_result.get("pass")):
            result["status"] = "failed"
            intake_errors = [str(item).strip() for item in auto_intake_result.get("errors", []) if str(item).strip()]
            result["error"] = (
                "auto-intake validation failed. "
                + "; ".join(intake_errors[:3] or ["reviewed packet did not validate"])
            ).strip()
    return result


def _hydrate_browser_source_provenance(
    *,
    job_spec_path: Path,
    artifacts_dir: Path | None,
    last_url: str,
    fallback_pack_id: str,
    fallback_game_scope: str,
) -> dict[str, object]:
    job = _load_json_object(job_spec_path, label=f"browser job spec '{job_spec_path}'")
    pack_id = str(job.get("pack_id") or fallback_pack_id or "").strip()
    game_scope = str(job.get("game_scope") or fallback_game_scope or "").strip()
    if not pack_id:
        raise ValueError(f"Browser job spec is missing pack_id: {job_spec_path}")
    if not game_scope:
        raise ValueError(f"Browser job spec is missing game_scope for pack '{pack_id}'.")

    destination_text = str(job.get("destination", "")).strip()
    if not destination_text:
        raise ValueError(f"Browser job spec is missing destination for pack '{pack_id}'.")
    source_dir = ensure_dir(Path(destination_text).resolve())
    provenance_path = source_dir / "provenance.json"
    hydration_report_path = source_dir / "provenance_hydration_report.json"

    raw_source_adapter = str(job.get("source_adapter", "")).strip()
    if not raw_source_adapter:
        raise ValueError(f"Browser job spec is missing source_adapter for pack '{pack_id}'.")
    canonical_source_adapter = canonical_source_adapter_id(raw_source_adapter)
    adapter_contract = require_source_adapter(canonical_source_adapter)
    expected_lane = adapter_contract.lane.value

    payload_target_path = ""
    payload_target_path_file = job_spec_path.parent / "payload_target.txt"
    if payload_target_path_file.exists():
        payload_target_path = payload_target_path_file.read_text(encoding="utf-8-sig").strip()
    if not payload_target_path:
        payload_target_path = str(publish_payload_dir(game_scope=game_scope, pack_id=pack_id))

    hydrated_from: set[str] = set()
    merged: dict[str, object] = {}
    if provenance_path.exists():
        merged.update(_load_json_object(provenance_path, label=f"source provenance '{provenance_path}'"))
        hydrated_from.add("existing_provenance")

    template_path = job_spec_path.parent / "provenance_template.json"
    if template_path.exists():
        template = _load_json_object(template_path, label=f"provenance template '{template_path}'")
        template_values = template.get("values")
        template_applied = False
        if isinstance(template_values, dict):
            for key, value in template_values.items():
                if _set_if_missing(merged, str(key), value):
                    template_applied = True
        for key in ("pack_id", "game_scope", "lane", "source_adapter", "payload_target_path"):
            if _set_if_missing(merged, key, template.get(key)):
                template_applied = True
        notes = template.get("notes")
        if isinstance(notes, list):
            note_text = " | ".join(str(item).strip() for item in notes if str(item).strip())
            if note_text and _set_if_missing(merged, "review_notes", note_text):
                template_applied = True
        if template_applied:
            hydrated_from.add("provenance_template")

    merged["pack_id"] = pack_id
    merged["game_scope"] = game_scope
    merged["lane"] = expected_lane
    merged["source_adapter"] = canonical_source_adapter
    merged["payload_target_path"] = str(Path(payload_target_path).resolve())

    browser_metadata, artifact_sources, artifact_paths = _collect_browser_artifact_metadata(
        source_dir=source_dir,
        artifacts_dir=artifacts_dir,
        source_adapter=canonical_source_adapter,
        source_url=str(job.get("source_url", "")).strip(),
    )
    if artifact_sources:
        hydrated_from.update(artifact_sources)

    source_url_applied = False
    if _set_if_missing(merged, "source_url", last_url):
        source_url_applied = True
        hydrated_from.add("browser_result")
    if _set_if_missing(merged, "source_url", job.get("source_url")):
        source_url_applied = True
        hydrated_from.add("browser_job")
    if _set_if_missing(merged, "source_url", browser_metadata.get("source_url")):
        source_url_applied = True
        hydrated_from.add("browser_artifacts")
    if not source_url_applied and str(merged.get("source_url", "")).strip():
        hydrated_from.add("existing_or_template_source_url")

    if _set_if_missing(
        merged,
        "author_or_vendor",
        browser_metadata.get("author_or_vendor")
        or browser_metadata.get("seller")
        or browser_metadata.get("publisher")
        or browser_metadata.get("vendor"),
    ):
        hydrated_from.add("browser_artifacts")
    if _set_if_missing(
        merged,
        "author_or_vendor",
        "Mixkit"
        if canonical_source_adapter == "mixkit"
        else ("Freesound" if canonical_source_adapter == "freesound_audio" else ""),
    ):
        hydrated_from.add("provider_defaults")
    derived_license = _browser_license_value(browser_metadata, source_adapter=canonical_source_adapter)
    if _set_if_missing(merged, "license", browser_metadata.get("license") or derived_license):
        hydrated_from.add("browser_artifacts")
    derived_license_snapshot = _browser_license_snapshot(browser_metadata)
    if _set_if_missing(
        merged,
        "license_snapshot",
        derived_license_snapshot
        or browser_metadata.get("license_snapshot")
        or browser_metadata.get("license")
        or derived_license,
    ):
        hydrated_from.add("browser_artifacts")
    explicit_entitlement_note = str(browser_metadata.get("entitlement_note", "")).strip()
    if explicit_entitlement_note:
        merged["entitlement_note"] = _append_sentence_note(merged.get("entitlement_note", ""), explicit_entitlement_note)
        hydrated_from.add("browser_artifacts")
    derived_entitlement_note = _browser_entitlement_note(browser_metadata, source_adapter=canonical_source_adapter)
    derived_entitlement_note = _append_browser_evidence_refs(derived_entitlement_note, artifact_paths)
    if derived_entitlement_note:
        merged["entitlement_note"] = _append_sentence_note(merged.get("entitlement_note", ""), derived_entitlement_note)
        hydrated_from.add("browser_artifacts")
    if str(merged.get("entitlement_note", "")).strip():
        merged["entitlement_note"] = _append_browser_evidence_refs(str(merged.get("entitlement_note", "")).strip(), artifact_paths)
    browser_download_notes: list[str] = []
    title_text = str(browser_metadata.get("title", "")).strip()
    if title_text:
        browser_download_notes.append(f"Listing title: {title_text}")
    version_text = str(browser_metadata.get("version", "")).strip()
    if version_text:
        browser_download_notes.append(f"Listing version: {version_text}")
    screenshot_note = _browser_screenshot_note(browser_metadata)
    if screenshot_note:
        browser_download_notes.append(screenshot_note)
    merged_download_notes = str(merged.get("download_notes", "")).strip()
    for note in browser_download_notes:
        merged_download_notes = _append_pipe_note(merged_download_notes, note)
    if merged_download_notes and merged_download_notes != str(merged.get("download_notes", "")).strip():
        merged["download_notes"] = merged_download_notes
        hydrated_from.add("browser_artifacts")

    execution_log_path = artifacts_dir / "execution_log.json" if artifacts_dir is not None else None
    execution_downloads: list[Path] = []
    if execution_log_path is not None and execution_log_path.exists():
        try:
            execution_log = json.loads(execution_log_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"browser execution log '{execution_log_path}' is malformed JSON at line {exc.lineno}, "
                f"column {exc.colno}: {exc.msg}."
            ) from exc
        if not isinstance(execution_log, list):
            raise ValueError(f"browser execution log '{execution_log_path}' must contain a JSON array.")
        for entry in execution_log:
            if not isinstance(entry, dict):
                continue
            download_path_text = str(entry.get("download_path", "")).strip()
            if download_path_text:
                execution_downloads.append(Path(download_path_text).resolve())

    payload_files = _supported_payload_files(source_dir)
    primary_payload: Path | None = None
    seen_payloads: set[str] = set()
    for candidate in execution_downloads + payload_files:
        resolved_candidate = candidate.resolve()
        candidate_key = str(resolved_candidate)
        if candidate_key in seen_payloads:
            continue
        seen_payloads.add(candidate_key)
        if not resolved_candidate.exists() or not resolved_candidate.is_file():
            continue
        if resolved_candidate.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        primary_payload = resolved_candidate
        break

    if primary_payload is not None:
        merged["downloaded_filename"] = _relative_payload_name(primary_payload, source_dir=source_dir)
        hydrated_from.add("browser_artifacts")
        if not str(merged.get("acquired_at", "")).strip():
            merged["acquired_at"] = _artifact_timestamp(primary_payload)
    elif not str(merged.get("acquired_at", "")).strip() and execution_log_path is not None and execution_log_path.exists():
        merged["acquired_at"] = _artifact_timestamp(execution_log_path)
        if str(merged.get("acquired_at", "")).strip():
            hydrated_from.add("browser_artifacts")

    canonical_provenance = canonicalize_provenance_payload(merged, keep_extra=True)
    canonical_provenance["pack_id"] = pack_id
    canonical_provenance["game_scope"] = game_scope
    canonical_provenance["lane"] = expected_lane
    canonical_provenance["source_adapter"] = canonical_source_adapter
    canonical_provenance["payload_target_path"] = str(Path(payload_target_path).resolve())
    if primary_payload is not None:
        canonical_provenance["downloaded_filename"] = _relative_payload_name(primary_payload, source_dir=source_dir)

    normalized_provenance, validation_errors, validation_warnings = validate_provenance_payload(
        canonical_provenance,
        expected_lane=expected_lane,
        expected_payload_target_path=canonical_provenance["payload_target_path"],
    )
    if not payload_files:
        validation_errors.append(
            f"No supported payload files found under '{source_dir}'. Download or copy accepted source files into this folder first."
        )

    missing_required_fields = [
        field_name
        for field_name in (
            "source_url",
            "license",
            "license_snapshot",
            "author_or_vendor",
            "acquired_at",
            "lane",
            "source_adapter",
            "payload_target_path",
            "downloaded_filename",
        )
        if (
            normalized_provenance.get(field_name) is None
            or (
                isinstance(normalized_provenance.get(field_name), str)
                and not str(normalized_provenance.get(field_name, "")).strip()
            )
        )
    ]

    confidence_payload = _build_browser_provenance_confidence(
        normalized_provenance=normalized_provenance,
        browser_metadata=browser_metadata,
        artifact_paths=artifact_paths,
        validation_errors=validation_errors,
        missing_required_fields=missing_required_fields,
        payload_file_count=len(payload_files),
    )

    write_json(provenance_path, canonical_provenance)
    hydration_payload: dict[str, object] = {
        "status": "completed" if not validation_errors else "incomplete",
        "pack_id": pack_id,
        "game_scope": game_scope,
        "lane": expected_lane,
        "source_adapter": canonical_source_adapter,
        "source_dir": str(source_dir),
        "job_spec_path": str(job_spec_path),
        "provenance_path": str(provenance_path),
        "payload_target_path": canonical_provenance["payload_target_path"],
        "payload_file_count": len(payload_files),
        "payload_files": [str(path) for path in payload_files],
        "downloaded_filename": str(canonical_provenance.get("downloaded_filename", "")).strip(),
        "artifacts_dir": str(artifacts_dir) if artifacts_dir is not None else "",
        "execution_log_path": str(execution_log_path) if execution_log_path is not None and execution_log_path.exists() else "",
        "page_metadata_path": artifact_paths.get("page_metadata_path", ""),
        "page_text_path": artifact_paths.get("page_text_path", ""),
        "page_dom_path": artifact_paths.get("page_dom_path", ""),
        "page_dom_text_path": artifact_paths.get("page_dom_text_path", ""),
        "page_dom_metadata_path": artifact_paths.get("page_dom_metadata_path", ""),
        "page_screenshot_path": artifact_paths.get("page_screenshot_path", ""),
        "page_screenshot_meta_path": artifact_paths.get("page_screenshot_meta_path", ""),
        "page_screenshot_meta": browser_metadata.get("page_screenshot_meta", {}) if isinstance(browser_metadata.get("page_screenshot_meta"), dict) else {},
        "browser_notes_path": artifact_paths.get("browser_notes_path", ""),
        "hydrated_from": sorted(hydrated_from),
        "missing_required_fields": missing_required_fields,
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings,
        "last_url": last_url,
        "provenance_confidence": confidence_payload,
        "provenance_confidence_score": int(confidence_payload.get("score", 0) or 0),
        "provenance_confidence_band": str(confidence_payload.get("band", "")).strip(),
        "register_packet_ready": bool(confidence_payload.get("register_packet_ready")),
        "operator_action_required": bool(confidence_payload.get("needs_operator_fill")),
        "operator_action": str(confidence_payload.get("action", "")).strip(),
        "operator_reasons": [str(item).strip() for item in confidence_payload.get("reasons", []) if str(item).strip()],
    }
    write_json(hydration_report_path, hydration_payload)
    hydration_payload["hydration_report_path"] = str(hydration_report_path)
    return hydration_payload


def _prepare_fallback_pack(
    *,
    pack_id: str,
    game_scope: str,
    source_dir: Path,
    cleanup_mode: str,
    asset_kind: str,
    animated: bool,
    packet_status: str,
    overwrite_packet: bool,
    verify_hashes: bool,
) -> dict[str, object]:
    resolved_asset_kind, resolved_animated = _resolve_pack_cleanup_defaults(pack_id, asset_kind, animated)
    return execute_prepare_pack(
        pack_id=pack_id,
        game_scope=game_scope,
        source_dir=source_dir,
        cleanup_mode=cleanup_mode,
        asset_kind=resolved_asset_kind,
        animated=resolved_animated,
        packet_status=packet_status,
        overwrite_packet=overwrite_packet,
        verify_hashes=verify_hashes,
    )


def _run_fab_fallback_actions(
    actions_file: Path,
    *,
    execute: bool,
    headless: bool,
    browser_profile_dir: Path | None,
    timeout_ms: int,
    retries: int,
    run_pwsh: bool,
    hydrate_provenance: bool,
    prepare_pack: bool,
    auto_intake: bool,
    cleanup_mode: str,
    asset_kind: str,
    animated: bool,
    packet_status: str,
    overwrite_packet: bool,
    verify_hashes: bool,
    pwsh_timeout_sec: float,
    continue_on_error: bool,
    require_complete: bool,
    as_json: bool,
) -> int:
    from assetboy.execution.playwright_runner import run_browser_job

    payload = json.loads(actions_file.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Fallback actions payload must be a JSON object: {actions_file}")

    raw_actions = payload.get("actions")
    if not isinstance(raw_actions, list):
        raise ValueError(f"Fallback actions payload is missing a valid actions[] list: {actions_file}")

    results: list[dict[str, object]] = []
    aborted = False

    for index, raw_action in enumerate(raw_actions):
        if not isinstance(raw_action, dict):
            action_result = {
                "index": index,
                "status": "failed",
                "error": "Action entry is not a JSON object.",
                "steps": [],
            }
            results.append(action_result)
            if not continue_on_error:
                aborted = True
                break
            continue

        action = dict(raw_action)
        fallback_error = str(action.get("fallback_error", "")).strip()
        action_result: dict[str, object] = {
            "index": index,
            "listing_ref": str(action.get("listing_ref", "")).strip(),
            "listing_id": str(action.get("listing_id", "")).strip(),
            "skip_reason": str(action.get("skip_reason", "")).strip(),
            "fallback_pack_id": str(action.get("fallback_pack_id", "")).strip(),
            "fallback_game_scope": str(action.get("fallback_game_scope", "")).strip(),
            "fallback_error": fallback_error,
            "status": "planned",
            "error": "",
            "steps": [],
        }

        step_results: list[dict[str, object]] = []
        action_failed = False
        action_pending_manual = False
        action_executed = False

        browser_specs = _fallback_action_required_paths(action, kind="browser_job_spec")
        uevault_scripts = _fallback_action_required_paths(action, kind="uevault_script")
        dummy_project_scripts = _fallback_action_required_paths(action, kind="dummy_project_script")

        if fallback_error and not browser_specs and not uevault_scripts and not dummy_project_scripts:
            action_failed = True
            action_result["error"] = fallback_error

        for job_spec_path in browser_specs:
            step_payload: dict[str, object] = {
                "kind": "browser_job_spec",
                "path": str(job_spec_path),
                "exists": job_spec_path.exists(),
                "status": "planned",
                "execution_mode": "",
                "attempts": 0,
                "error": "",
            }
            if not job_spec_path.exists():
                step_payload["status"] = "failed"
                step_payload["error"] = "Browser job spec path does not exist."
                action_failed = True
                step_results.append(step_payload)
                continue

            try:
                browser_result = run_browser_job(
                    job_spec_path=job_spec_path,
                    dry_run=not execute,
                    execute=execute,
                    headed=not headless,
                    browser_profile_dir=browser_profile_dir,
                    timeout_ms=timeout_ms,
                    retries=retries,
                )
            except Exception as exc:  # noqa: BLE001
                step_payload["status"] = "failed"
                step_payload["error"] = str(exc)
                action_failed = True
                step_results.append(step_payload)
                continue

            step_payload["execution_mode"] = str(browser_result.execution_mode)
            step_payload["attempts"] = int(getattr(browser_result, "attempts", 0) or 0)
            step_payload["last_url"] = str(getattr(browser_result, "last_url", "") or "")
            if getattr(browser_result, "artifacts_dir", None) is not None:
                step_payload["artifacts_dir"] = str(browser_result.artifacts_dir)
            if getattr(browser_result, "browser_profile_dir", None) is not None:
                step_payload["browser_profile_dir"] = str(browser_result.browser_profile_dir)
            repair_reason = _safe_result_text_attr(browser_result, "repair_reason")
            repair_command = _safe_result_text_attr(browser_result, "repair_command")
            provider_runbook_id = _safe_result_text_attr(browser_result, "provider_runbook_id")
            if repair_reason:
                step_payload["repair_reason"] = repair_reason
            if repair_command:
                step_payload["repair_command"] = repair_command
            if provider_runbook_id:
                step_payload["provider_runbook_id"] = provider_runbook_id

            browser_error = str(getattr(browser_result, "error", "") or "").strip()
            if execute:
                if browser_result.execution_mode == "repair_required":
                    step_payload["status"] = "repair_required"
                    step_payload["error"] = browser_error or "Browser auth repair is required before this job can continue."
                    action_pending_manual = True
                elif browser_result.execution_mode in {"failed", "interactive_required"}:
                    step_payload["status"] = "failed"
                    step_payload["error"] = browser_error or f"Browser execution_mode={browser_result.execution_mode}."
                    action_failed = True
                else:
                    step_payload["status"] = "executed"
                    if hydrate_provenance or prepare_pack or auto_intake:
                        try:
                            postprocess = _postprocess_browser_job(
                                job_spec_path=job_spec_path,
                                artifacts_dir=Path(browser_result.artifacts_dir) if getattr(browser_result, "artifacts_dir", None) is not None else None,
                                last_url=str(getattr(browser_result, "last_url", "") or ""),
                                fallback_pack_id=str(action_result.get("fallback_pack_id", "")).strip(),
                                fallback_game_scope=str(action_result.get("fallback_game_scope", "")).strip(),
                                hydrate_provenance=hydrate_provenance,
                                prepare_pack=prepare_pack,
                                cleanup_mode=cleanup_mode,
                                asset_kind=asset_kind,
                                animated=animated,
                                packet_status=packet_status,
                                overwrite_packet=overwrite_packet,
                                verify_hashes=verify_hashes,
                                auto_intake=auto_intake,
                            )
                        except Exception as exc:  # noqa: BLE001
                            step_payload["status"] = "failed"
                            step_payload["error"] = str(exc)
                            action_failed = True
                        else:
                            step_payload.update(postprocess)
                            if str(postprocess.get("status", "")).strip() == "failed":
                                action_failed = True
                            elif str(postprocess.get("status", "")).strip() == "pending_manual":
                                action_pending_manual = True
                            else:
                                action_executed = True
                    else:
                        action_executed = True
            else:
                step_payload["status"] = "planned"
            step_results.append(step_payload)

        for script_kind, script_paths in (
            ("uevault_script", uevault_scripts),
            ("dummy_project_script", dummy_project_scripts),
        ):
            for script_path in script_paths:
                step_payload: dict[str, object] = {
                    "kind": script_kind,
                    "path": str(script_path),
                    "exists": script_path.exists(),
                    "status": "planned",
                    "error": "",
                }
                if not script_path.exists():
                    step_payload["status"] = "failed"
                    step_payload["error"] = "Script path does not exist."
                    action_failed = True
                    step_results.append(step_payload)
                    continue

                if not execute:
                    step_results.append(step_payload)
                    continue

                if not run_pwsh:
                    step_payload["status"] = "pending_manual"
                    step_payload["error"] = "PowerShell execution disabled. Re-run with --run-pwsh to execute this script."
                    action_pending_manual = True
                    step_results.append(step_payload)
                    continue

                script_result = _run_fallback_pwsh_script(
                    script_path=script_path,
                    timeout_sec=pwsh_timeout_sec,
                )
                step_payload.update(script_result)
                if script_result["status"] == "failed":
                    action_failed = True
                else:
                    action_executed = True
                step_results.append(step_payload)

        if not step_results and not action_failed:
            action_failed = True
            action_result["error"] = "Action does not contain executable required_files entries."

        step_errors = [str(step.get("error", "")).strip() for step in step_results if str(step.get("error", "")).strip()]
        if action_failed:
            action_result["status"] = "failed"
            if not action_result["error"]:
                action_result["error"] = step_errors[0] if step_errors else "One or more action steps failed."
        elif execute and action_pending_manual:
            action_result["status"] = "pending_manual"
            if not action_result["error"]:
                action_result["error"] = step_errors[0] if step_errors else "One or more action steps still require manual input."
        elif execute and action_executed:
            action_result["status"] = "executed"
        else:
            action_result["status"] = "planned"

        action_result["steps"] = step_results
        results.append(action_result)

        if action_result["status"] == "failed" and not continue_on_error:
            aborted = True
            break

    summary = {
        "total_actions": len(raw_actions),
        "processed_actions": len(results),
        "executed_actions": sum(1 for row in results if str(row.get("status", "")) == "executed"),
        "planned_actions": sum(1 for row in results if str(row.get("status", "")) == "planned"),
        "pending_manual_actions": sum(1 for row in results if str(row.get("status", "")) == "pending_manual"),
        "repair_required_actions": sum(
            1
            for row in results
            for step in row.get("steps", [])
            if isinstance(step, dict) and str(step.get("status", "")).strip() == "repair_required"
        ),
        "failed_actions": sum(1 for row in results if str(row.get("status", "")) == "failed"),
        "auto_intake_passed": sum(
            1
            for row in results
            for step in row.get("steps", [])
            if isinstance(step, dict) and bool(step.get("auto_intake", {}).get("pass"))
        ),
        "aborted": aborted,
    }

    execution_payload: dict[str, object] = {
        "schema_version": "assetboy.fab_fallback_execution.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "actions_file": str(actions_file.resolve()),
        "execute": execute,
        "headless": headless,
        "run_pwsh": run_pwsh,
        "hydrate_provenance": hydrate_provenance,
        "prepare_pack": prepare_pack,
        "auto_intake": auto_intake,
        "cleanup_mode": cleanup_mode,
        "asset_kind": asset_kind,
        "animated": animated,
        "packet_status": packet_status,
        "overwrite_packet": overwrite_packet,
        "verify_hashes": verify_hashes,
        "browser_profile_dir": str(browser_profile_dir) if browser_profile_dir is not None else "",
        "timeout_ms": timeout_ms,
        "retries": retries,
        "pwsh_timeout_sec": pwsh_timeout_sec,
        "continue_on_error": continue_on_error,
        "require_complete": require_complete,
        "summary": summary,
        "results": results,
    }

    report_path = actions_file.parent / "fab_batch_fallback_execution.json"
    write_json(report_path, execution_payload)

    print(f"fab_fallback_actions_file={actions_file}")
    print(f"fab_fallback_execute={str(execute).lower()}")
    print(f"fab_fallback_prepare_pack={str(prepare_pack).lower()}")
    print(f"fab_fallback_auto_intake={str(auto_intake).lower()}")
    print(f"fab_fallback_total={summary['total_actions']}")
    print(f"fab_fallback_processed={summary['processed_actions']}")
    print(f"fab_fallback_executed={summary['executed_actions']}")
    print(f"fab_fallback_planned={summary['planned_actions']}")
    print(f"fab_fallback_pending_manual={summary['pending_manual_actions']}")
    print(f"fab_fallback_repair_required={summary['repair_required_actions']}")
    print(f"fab_fallback_failed={summary['failed_actions']}")
    print(f"fab_fallback_auto_intake_passed={summary['auto_intake_passed']}")
    print(f"fab_fallback_aborted={str(summary['aborted']).lower()}")
    print(f"fab_fallback_report={report_path}")
    if as_json:
        print(json.dumps(execution_payload, indent=2, sort_keys=True))

    if summary["failed_actions"] > 0:
        return 1
    if require_complete and summary["pending_manual_actions"] > 0:
        return 1
    return 0


def _run_emit_marketplace_claim_job(
    method: str,
    pack_id: str,
    game_scope: str,
    source_url: str,
    target_filter: str,
    account_scope: str,
    output_dir: Path | None,
) -> int:
    artifacts = emit_marketplace_claim_job(
        method=method,
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        target_filter=target_filter,
        account_scope=account_scope,
        output_dir=output_dir,
    )
    _print_marketplace_claim_artifacts("marketplace_claim", artifacts.to_dict())
    return 0


def _run_emit_cue4parse_job(
    pack_id: str,
    game_scope: str,
    source_package_name: str,
    source_url: str,
    license_note: str,
    input_path_hint: str,
    mesh_output_format: str,
    asset_kind: str,
    output_dir: Path | None,
) -> int:
    artifacts = emit_cue4parse_job(
        pack_id=pack_id,
        game_scope=game_scope,
        source_package_name=source_package_name,
        source_url=source_url,
        license_note=license_note,
        input_path_hint=input_path_hint,
        mesh_output_format=mesh_output_format,
        asset_kind=asset_kind,
        output_dir=output_dir,
    )
    _print_cue4parse_artifacts("cue4parse", artifacts.to_dict())
    return 0


def _run_emit_blender_psk_batch(
    pack_id: str,
    game_scope: str,
    input_dir: str,
    source_format: str,
    output_dir: Path | None,
) -> int:
    artifacts = emit_blender_psk_batch_job(
        pack_id=pack_id,
        game_scope=game_scope,
        input_dir=input_dir,
        source_format=source_format,
        output_dir=output_dir,
    )
    _print_blender_batch_artifacts("blender_batch", artifacts.to_dict())
    return 0


def _run_emit_browser_job(
    source_adapter: str,
    runtime: str,
    pack_id: str,
    game_scope: str,
    source_url: str,
    search_terms: list[str],
    login_required: bool,
    output_dir: Path | None,
) -> int:
    artifacts = emit_browser_automation_job(
        source_adapter=source_adapter,
        runtime=runtime,
        pack_id=pack_id,
        game_scope=game_scope,
        source_url=source_url,
        search_terms=tuple(search_terms),
        login_required=login_required,
        output_dir=output_dir,
    )
    print(f"browser_output_dir={artifacts.output_dir}")
    print(f"browser_job_spec={artifacts.job_spec_path}")
    print(f"browser_provenance_template={artifacts.provenance_template_path}")
    print(f"browser_review_checklist={artifacts.review_checklist_path}")
    print(f"browser_payload_target_file={artifacts.payload_target_path_file}")
    print(f"browser_download_target={artifacts.download_target_path}")
    return 0


def _run_emit_ai_bridge_job(provider: str, pack_id: str, game_scope: str, output_dir: Path | None) -> int:
    artifacts = emit_ai_bridge_job(
        provider_id=provider,
        pack_id=pack_id,
        game_scope=game_scope,
        output_dir=output_dir,
    )
    print(f"ai_bridge_output_dir={artifacts.output_dir}")
    print(f"ai_bridge_job_spec={artifacts.job_spec_path}")
    print(f"ai_bridge_provenance_template={artifacts.provenance_template_path}")
    print(f"ai_bridge_review_checklist={artifacts.review_checklist_path}")
    print(f"ai_bridge_payload_target_file={artifacts.payload_target_path_file}")
    print(f"ai_bridge_payload_target={artifacts.payload_target_path}")
    return 0


def _run_emit_chatgpt_pro_batch(pack_id: str, game_scope: str, output_dir: Path | None) -> int:
    return _run_emit_ai_bridge_job("chatgpt_pro", pack_id, game_scope, output_dir)


def _run_emit_extractor_job(
    tool: str,
    pack_id: str,
    game_scope: str,
    source_package_name: str,
    source_url: str,
    license_note: str,
    input_path_hint: str,
    asset_kind: str,
    output_dir: Path | None,
) -> int:
    artifacts = emit_extractor_job(
        tool=tool,
        pack_id=pack_id,
        game_scope=game_scope,
        source_package_name=source_package_name,
        source_url=source_url,
        license_note=license_note,
        input_path_hint=input_path_hint,
        asset_kind=asset_kind,
        output_dir=output_dir,
    )
    print(f"extractor_output_dir={artifacts.output_dir}")
    print(f"extractor_job_spec={artifacts.job_spec_path}")
    print(f"extractor_provenance_template={artifacts.provenance_template_path}")
    print(f"extractor_review_checklist={artifacts.review_checklist_path}")
    print(f"extractor_payload_target_file={artifacts.payload_target_path_file}")
    print(f"extractor_cleanup_plan={artifacts.cleanup_plan_path}")
    print(f"extractor_payload_target={artifacts.payload_target_path}")
    return 0


def _run_build_dungeon(preset: str, name: str, tile_size: float, port: int) -> int:
    from assetboy.execution.flax_mcp_bridge import (
        call_tool,
        DUNGEON_PRESETS,
        ROMAN_ARENA_LEGEND,
    )

    if preset not in DUNGEON_PRESETS:
        print(f"[ERROR] Unknown preset '{preset}'. Available: {', '.join(DUNGEON_PRESETS)}")
        return 2

    layout = DUNGEON_PRESETS[preset]
    print(f"Building preset '{preset}' as '{name}' on FlaxMCP port {port}...")

    try:
        result = call_tool(
            tool_name="workflow_ops/generate_dungeon_grid",
            arguments={
                "name": name,
                "tile_size": tile_size,
                "legend": ROMAN_ARENA_LEGEND,
                "layout": layout,
            },
            port=port,
        )
        print(f"[OK] {result}")
        return 0
    except ConnectionRefusedError as exc:
        print(f"[ERROR] {exc}")
        return 1
    except RuntimeError as exc:
        print(f"[TOOL ERROR] {exc}")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        return _run_status()

    if args.command == "init-library-layout":
        return _run_init_library_layout(dry_run=args.dry_run)

    if args.command == "smoke-lanes":
        return _run_smoke_lanes(output_dir=args.output_dir, as_json=args.as_json)

    if args.command == "roman-blockers":
        return _run_roman_blockers(args.gate, args.catalog)

    if args.command == "plan-roman-blockers":
        return _run_plan_roman_blockers(args.gate, args.catalog, args.task_output, args.summary_output)

    if args.command == "emit-roman-execution-kit":
        return _run_emit_roman_execution_kit(args.gate, args.catalog, args.browser_runtime, args.output_dir)

    if args.command == "emit-roman-launcher-manifest":
        return _run_emit_roman_launcher_manifest(args.game_scope, args.output_dir)

    if args.command == "emit-roman-source-presets":
        return _run_emit_roman_source_presets(args.game_scope, args.output_dir, args.launcher_manifest)

    if args.command == "emit-audio-examples":
        return _run_emit_audio_examples(args.game_scope, args.output_dir)

    if args.command == "emit-category-examples":
        return _run_emit_category_examples(args.game_scope, args.output_dir)

    if args.command == "emit-cleanup-examples":
        return _run_emit_cleanup_examples(args.game_scope, args.output_dir)

    if args.command == "list-lanes":
        return _run_list_lanes()

    if args.command == "list-bridges":
        return _run_list_bridges()

    if args.command == "print-batchability":
        return _run_print_batchability(args.as_json)

    if args.command == "validate-bridges":
        return _run_validate_bridges()

    if args.command == "list-provider-runbooks":
        return _run_list_provider_runbooks()

    if args.command == "list-unity-installs":
        return _run_list_unity_installs()

    if args.command == "list-unreal-installs":
        return _run_list_unreal_installs()

    if args.command == "print-provider-readiness":
        return _run_print_provider_readiness(as_json=args.as_json, timeout_seconds=args.timeout)

    if args.command == "print-provider-autonomy-deltas":
        return _run_print_provider_autonomy_deltas(as_json=args.as_json, timeout_seconds=args.timeout)

    if args.command == "print-category-routing":
        return _run_print_category_routing()

    if args.command == "print-provider-runbook":
        return _run_print_provider_runbook(args.provider, as_json=args.as_json)

    if args.command == "print-pack-targets":
        return _run_print_pack_targets(args.gate, args.catalog)

    if args.command == "print-pack-readiness":
        return _run_print_pack_readiness(
            args.gate,
            args.catalog,
            as_json=args.as_json,
            states=args.states,
            groups=args.groups,
            import_pending_only=args.import_pending_only,
        )

    if args.command == "sync-shared-priority":
        return _run_sync_shared_priority(
            target_scope=args.target_scope,
            pack_ids=args.pack_ids,
            dry_run=args.dry_run,
            as_json=args.as_json,
        )

    if args.command == "list-pack-families":
        return _run_list_pack_families(wave=args.wave, include_legacy=args.include_legacy)

    if args.command == "emit-pack-family-plan":
        return _run_emit_pack_family_plan(
            game_scope=args.game_scope,
            wave=args.wave,
            pack_ids=args.pack_ids,
            output_dir=args.output_dir,
            browser_runtime=args.browser_runtime,
        )

    if args.command == "emit-hunyuan-batch":
        return _run_emit_hunyuan_batch(args.pack_id, args.game_scope, args.output_dir)

    if args.command == "emit-animationgpt-pilot":
        return _run_emit_animationgpt_pilot(args.pack_id, args.game_scope, args.output_dir)

    if args.command == "emit-engine-export-job":
        return _run_emit_engine_export_job(
            args.engine,
            args.pack_id,
            args.game_scope,
            args.source_url,
            args.license_note,
            args.source_package_name,
            args.asset_kind,
            args.output_dir,
        )

    if args.command == "emit-unity-export-runner":
        return _run_emit_unity_export_runner(
            args.pack_id,
            args.game_scope,
            args.source_url,
            args.license_note,
            args.project_path,
            args.package_root,
            args.asset_paths,
            args.unitypackage_paths,
            args.source_package_name,
            args.asset_kind,
            args.output_dir,
        )

    if args.command == "emit-unity-download-wave":
        return _run_emit_unity_download_wave(
            args.source_file,
            args.game_scope,
            args.project_root,
            args.output_dir,
        )

    if args.command == "run-unity-claim-wave":
        return _run_unity_claim_wave(
            args.wave_json,
            best_first=args.best_first,
            exportable_only=args.exportable_only,
            categories=args.categories,
            pack_ids=args.pack_ids,
            limit=args.limit,
            dry_run=args.dry_run,
            headless=args.headless,
            browser_profile_dir=args.browser_profile_dir,
            timeout_ms=args.timeout_ms,
            retries=args.retries,
            hydrate_provenance=args.hydrate_provenance,
            prepare_pack=args.prepare_pack,
            auto_intake=args.auto_intake,
            cleanup_mode=args.cleanup_mode,
            asset_kind=args.asset_kind,
            animated=args.animated,
            packet_status=args.packet_status,
            overwrite_packet=args.overwrite_packet,
            verify_hashes=args.verify_hashes,
            continue_on_error=args.continue_on_error,
            require_complete=args.require_complete,
            emit_project_ingest_wave=args.emit_project_ingest_wave,
            project_path=args.project_path,
            game_scope=args.game_scope,
            output_dir=args.output_dir,
            as_json=args.as_json,
        )

    if args.command == "unity-hub-status":
        return _run_unity_hub_status(args.projects_path, args.output_dir)

    if args.command == "map-unity-owned-library":
        return _run_map_unity_owned_library(
            page_size=args.page_size,
            max_pages=args.max_pages,
            output_dir=args.output_dir,
        )

    if args.command == "unity-download-owned":
        return _run_unity_download_owned(
            product_id=args.product_id,
            output_dir=args.output_dir,
            timeout=args.timeout,
        )

    if args.command == "download-unity-owned-lightweights":
        return _run_download_unity_owned_lightweights(
            max_mb=args.max_mb,
            limit=args.limit,
            include_hidden=args.include_hidden,
            include_unknown_size=args.include_unknown_size,
            page_size=args.page_size,
            max_pages=args.max_pages,
            output_dir=args.output_dir,
            timeout=args.timeout,
        )

    if args.command == "download-unity-owned-wave":
        return _run_download_unity_owned_wave(
            args.wave_json,
            best_first=args.best_first,
            exportable_only=args.exportable_only,
            asset_donor_only=args.asset_donor_only,
            categories=args.categories,
            pack_ids=args.pack_ids,
            limit=args.limit,
            output_dir=args.output_dir,
            timeout=args.timeout,
        )

    if args.command == "emit-unity-project-ingest-wave":
        return _run_emit_unity_project_ingest_wave(
            args.wave_json,
            project_path=args.project_path,
            game_scope=args.game_scope,
            best_first=args.best_first,
            exportable_only=args.exportable_only,
            categories=args.categories,
            pack_ids=args.pack_ids,
            limit=args.limit,
            output_dir=args.output_dir,
        )

    if args.command == "emit-unreal-export-runner":
        return _run_emit_unreal_export_runner(
            args.pack_id,
            args.game_scope,
            args.source_url,
            args.license_note,
            args.project_file,
            args.package_root,
            args.asset_paths,
            args.source_package_name,
            args.asset_kind,
            args.output_dir,
        )

    if args.command == "emit-uevaultmanager-job":
        return _run_emit_uevaultmanager_job(
            args.pack_id,
            args.game_scope,
            args.source_url,
            args.vault_item,
            args.engine_association,
            args.output_dir,
        )

    if args.command == "uevault-repair-config":
        return _run_uevault_repair_config(args.config_path)

    if args.command == "uevault-status":
        return _run_uevault_status(args.timeout, args.online)

    if args.command == "uevault-import-auth":
        return _run_uevault_import_auth(args.timeout)

    if args.command == "uevault-list-owned":
        return _run_uevault_list_owned(args.output, args.force_refresh, args.timeout)

    if args.command == "uevault-install-owned":
        return _run_uevault_install_owned(args.vault_item, args.download_dir, args.full_install, args.timeout)

    if args.command == "legendary-status":
        return _run_legendary_status(args.timeout)

    if args.command == "legendary-import-auth":
        return _run_legendary_import_auth(args.timeout)

    if args.command == "legendary-list-ue":
        return _run_legendary_list_ue(args.output_dir, args.timeout)

    if args.command == "legendary-install-owned":
        return _run_legendary_install_owned(args.app_name, args.base_path, args.timeout)

    if args.command == "inventory-epic-vault-cache":
        if args.include_launcher_cache:
            return _run_inventory_epic_library_report(args.db_path, args.output_dir)
        return _run_inventory_epic_vault_cache(args.db_path, args.output_dir)

    if args.command == "inventory-epic-launcher-cache":
        return _run_inventory_epic_launcher_cache(args.data_dir, args.output_dir)

    if args.command == "emit-epic-cache-extractor-wave":
        return _run_emit_epic_cache_extractor_wave(args.db_path, args.output_dir, args.game_scope)

    if args.command == "map-epic-library":
        return _run_map_epic_library(args.output_dir, args.timeout)
    if args.command == "map-fab-library":
        return _run_map_fab_library(args.output_dir, args.timeout)
    if args.command == "map-quixel-library":
        return _run_map_quixel_library(args.output_dir, args.timeout, args.quixel_roots)
    if args.command == "map-all-libraries":
        return _run_map_all_libraries(args.output_dir, args.db_path, args.data_dir, args.timeout, args.quixel_roots)
    if args.command == "emit-fab-dummy-project-wave":
        return _run_emit_fab_dummy_project_wave(args.output_dir, args.game_scope, args.engine_association, args.max_jobs)
    if args.command == "emit-arena-owned-wave":
        return _run_emit_arena_owned_wave(args.output_dir)
    if args.command == "emit-arena-extraction-wave":
        return _run_emit_arena_extraction_wave(args.output_dir, args.game_scope)
    if args.command == "emit-useful-harvest-wave":
        return _run_emit_useful_harvest_wave(args.output_dir)
    if args.command == "emit-useful-donor-export-wave":
        return _run_emit_useful_donor_export_wave(args.output_dir, args.game_scope, args.project_path)

    if args.command in {"emit-epic-dummy-project", "emit-epic-dummy-project-job"}:
        return _run_emit_epic_dummy_project(
            args.pack_id,
            args.game_scope,
            args.source_url,
            args.engine_association,
            args.project_name,
            args.project_dir,
            args.output_dir,
        )

    if args.command == "emit-marketplace-claim-job":
        return _run_emit_marketplace_claim_job(
            args.method,
            args.pack_id,
            args.game_scope,
            args.source_url,
            args.target_filter,
            args.account_scope,
            args.output_dir,
        )

    if args.command == "emit-cue4parse-job":
        return _run_emit_cue4parse_job(
            args.pack_id,
            args.game_scope,
            args.source_package_name,
            args.source_url,
            args.license_note,
            args.input_path_hint,
            args.mesh_output_format,
            args.asset_kind,
            args.output_dir,
        )

    if args.command == "emit-blender-psk-batch":
        return _run_emit_blender_psk_batch(
            args.pack_id,
            args.game_scope,
            args.input_dir,
            args.source_format,
            args.output_dir,
        )

    if args.command == "emit-browser-job":
        return _run_emit_browser_job(
            args.source_adapter,
            args.runtime,
            args.pack_id,
            args.game_scope,
            args.source_url,
            args.search_terms,
            args.login_required,
            args.output_dir,
        )

    if args.command == "emit-ai-bridge-job":
        return _run_emit_ai_bridge_job(args.provider, args.pack_id, args.game_scope, args.output_dir)

    if args.command == "emit-chatgpt-pro-batch":
        return _run_emit_chatgpt_pro_batch(args.pack_id, args.game_scope, args.output_dir)

    if args.command == "emit-extractor-job":
        return _run_emit_extractor_job(
            args.tool,
            args.pack_id,
            args.game_scope,
            args.source_package_name,
            args.source_url,
            args.license_note,
            args.input_path_hint,
            args.asset_kind,
            args.output_dir,
        )

    if args.command == "fab-auth":
        import asyncio
        from assetboy.providers.fab_hybrid import FabHybridDownloader
        downloader = FabHybridDownloader()
        if not args.reuse_profile and not args.allow_browser:
            print("fab_auth_error=Browser launch blocked by default. Use --reuse-profile for the safe path, or add --allow-browser if you intentionally want one visible Fab login window.")
            return 1
        if args.allow_browser and not args.reuse_profile and not _stdin_supports_interaction():
            print(_interactive_auth_terminal_error("fab_auth_error", "Fab"))
            return 1
        try:
            with downloader.auth_lock():
                if args.reuse_profile:
                    state = asyncio.run(downloader.refresh_auth_from_profile(timeout_seconds=args.timeout))
                else:
                    state = asyncio.run(downloader.acquire_session_interactive(timeout_seconds=args.timeout))
        except EOFError:
            print(_interactive_auth_terminal_error("fab_auth_error", "Fab"))
            return 1
        except Exception as exc:
            print(f"fab_auth_error={exc}")
            return 1

        session = downloader.create_cffi_session(state)
        if downloader.is_authenticated(session):
            print("fab_auth_status=authenticated")
            print(f"fab_auth_saved={downloader.auth_state_path}")
            return 0

        print("fab_auth_error=Saved session is still unauthenticated. Finish login inside the opened Fab window, then rerun fab-auth.")
        print(f"fab_auth_saved={downloader.auth_state_path}")
        return 1

    if args.command == "fab-auth-status":
        from assetboy.providers.fab_hybrid import FabHybridDownloader

        downloader = FabHybridDownloader(debug=False)
        status = downloader.auth_status()
        print(f"fab_auth_state_path={status['auth_state_path']}")
        print(f"fab_auth_state_exists={'true' if status['auth_state_exists'] else 'false'}")
        print(f"fab_browser_profile_dir={status['browser_profile_dir']}")
        print(f"fab_browser_profile_has_state={'true' if status['browser_profile_has_state'] else 'false'}")
        print(f"fab_auth_authenticated={'true' if status['authenticated'] else 'false'}")
        if status.get("saved_at"):
            print(f"fab_auth_saved_at={status['saved_at']}")
        print(f"fab_auth_state_stale={'true' if status.get('auth_state_stale') else 'false'}")
        if status.get("repair_command"):
            print(f"fab_auth_repair_command={status['repair_command']}")
        if status["error"]:
            print(f"fab_auth_error={status['error']}")
            return 1
        return 0

    if args.command == "seed-shared-browser-profile":
        try:
            report = seed_shared_browser_profile(
                source_root=args.source_root,
                source_profile=args.source_profile,
                target_dir=args.target_dir,
                force=args.force,
                dry_run=args.dry_run,
            )
        except Exception as exc:
            print(f"shared_browser_profile_error={exc}")
            return 1

        print(f"shared_browser_profile_status={report['status']}")
        print(f"shared_browser_profile_source_root={report['source_root']}")
        print(f"shared_browser_profile_source_profile={report['source_profile']}")
        print(f"shared_browser_profile_source_profile_dir={report['source_profile_dir']}")
        print(f"shared_browser_profile_target_dir={report['target_dir']}")
        print(f"shared_browser_profile_force={'true' if report['force'] else 'false'}")
        print(f"shared_browser_profile_dry_run={'true' if report['dry_run'] else 'false'}")
        print(f"shared_browser_profile_target_has_state={'true' if report['target_has_state'] else 'false'}")
        print(f"shared_browser_profile_copied_files={report['copied_files']}")
        print(f"shared_browser_profile_copied_bytes={report['copied_bytes']}")
        print(f"shared_browser_profile_missing_entries={len(report['missing_entries'])}")
        print(f"shared_browser_profile_failed_entries={len(report['failed_entries'])}")
        if report["missing_entries"]:
            print("shared_browser_profile_missing_list=" + ",".join(str(item) for item in report["missing_entries"]))
        if report["failed_entries"]:
            print(
                "shared_browser_profile_failed_list="
                + ",".join(
                    f"{str(item.get('path', ''))}:{str(item.get('error', '')).replace(',', ';')}"
                    for item in report["failed_entries"]
                )
            )
        for index, action in enumerate(report["next_actions"], start=1):
            print(f"shared_browser_profile_next_action_{index}={action}")
        if report["success"]:
            return 0
        print("shared_browser_profile_error=Could not copy the required browser profile artifacts. Close Chrome and rerun with --force if the source is locked.")
        return 1

    if args.command == "mixamo-auth":
        import asyncio
        from assetboy.providers.mixamo_auth import MixamoAuthSession

        session = MixamoAuthSession(debug=False)
        if not args.reuse_profile and not args.allow_browser:
            print("mixamo_auth_error=Browser launch blocked by default. Use --reuse-profile for the safe path, or add --allow-browser if you intentionally want one visible Mixamo login window.")
            return 1
        if args.allow_browser and not args.reuse_profile and not _stdin_supports_interaction():
            print(_interactive_auth_terminal_error("mixamo_auth_error", "Mixamo"))
            return 1
        try:
            with session.auth_lock():
                if args.reuse_profile:
                    state = asyncio.run(session.refresh_auth_from_profile(timeout_seconds=args.timeout))
                else:
                    state = asyncio.run(session.acquire_session_interactive(timeout_seconds=args.timeout))
        except EOFError:
            print(_interactive_auth_terminal_error("mixamo_auth_error", "Mixamo"))
            return 1
        except Exception as exc:
            print(f"mixamo_auth_error={exc}")
            return 1

        if state.get("authenticated"):
            print("mixamo_auth_status=authenticated")
            print(f"mixamo_auth_saved={session.auth_state_path}")
            print(f"mixamo_browser_profile_dir={session.browser_profile_dir}")
            return 0

        print("mixamo_auth_error=Saved Mixamo session still looks unsigned-in. Finish login inside the opened Mixamo window, then rerun mixamo-auth.")
        print(f"mixamo_auth_saved={session.auth_state_path}")
        print(f"mixamo_browser_profile_dir={session.browser_profile_dir}")
        return 1

    if args.command == "mixamo-auth-status":
        from assetboy.providers.mixamo_auth import MixamoAuthSession

        session = MixamoAuthSession(debug=False)
        status = session.auth_status()
        print(f"mixamo_auth_state_path={status['auth_state_path']}")
        print(f"mixamo_auth_state_exists={'true' if status['auth_state_exists'] else 'false'}")
        print(f"mixamo_browser_profile_dir={status['browser_profile_dir']}")
        print(f"mixamo_browser_profile_has_state={'true' if status['browser_profile_has_state'] else 'false'}")
        print(f"mixamo_auth_authenticated={'true' if status['authenticated'] else 'false'}")
        if status.get("saved_at"):
            print(f"mixamo_auth_saved_at={status['saved_at']}")
        print(f"mixamo_auth_state_stale={'true' if status.get('auth_state_stale') else 'false'}")
        if status.get("repair_command"):
            print(f"mixamo_auth_repair_command={status['repair_command']}")
        print(f"mixamo_login_prompt_visible={'true' if status['login_prompt_visible'] else 'false'}")
        if status["page_url"]:
            print(f"mixamo_page_url={status['page_url']}")
        if status["page_title"]:
            print(f"mixamo_page_title={status['page_title']}")
        if status["error"]:
            print(f"mixamo_auth_error={status['error']}")
            return 1
        return 0

    if args.command == "unity-auth":
        from assetboy.providers.unity_auth import UnityAuthSession

        session = UnityAuthSession()
        if not args.reuse_profile and not args.allow_browser:
            print("unity_auth_error=Browser launch blocked by default. Use --reuse-profile for the safe path, or add --allow-browser if you intentionally want one visible Unity login window.")
            return 1
        if args.allow_browser and not args.reuse_profile and not _stdin_supports_interaction():
            print(_interactive_auth_terminal_error("unity_auth_error", "Unity Asset Store"))
            return 1
        try:
            with session.auth_lock():
                if args.reuse_profile:
                    state = session.refresh_auth_from_profile(timeout_seconds=args.timeout)
                else:
                    state = session.acquire_session_interactive(timeout_seconds=args.timeout)
        except EOFError:
            print(_interactive_auth_terminal_error("unity_auth_error", "Unity Asset Store"))
            return 1
        except Exception as exc:
            print(f"unity_auth_error={exc}")
            return 1

        if state.get("authenticated"):
            print("unity_auth_status=authenticated")
            print(f"unity_auth_saved={session.auth_state_path}")
            print(f"unity_browser_profile_dir={session.browser_profile_dir}")
            return 0

        print("unity_auth_error=Saved Unity session still looks unsigned-in. Finish login inside the Unity window, then rerun unity-auth.")
        print(f"unity_auth_saved={session.auth_state_path}")
        print(f"unity_browser_profile_dir={session.browser_profile_dir}")
        return 1

    if args.command == "unity-auth-status":
        from assetboy.providers.unity_auth import UnityAuthSession

        session = UnityAuthSession()
        status = session.auth_status()
        print(f"unity_auth_state_path={status['auth_state_path']}")
        print(f"unity_auth_state_exists={'true' if status['auth_state_exists'] else 'false'}")
        print(f"unity_browser_profile_dir={status['browser_profile_dir']}")
        print(f"unity_browser_profile_has_state={'true' if status['browser_profile_has_state'] else 'false'}")
        print(f"unity_auth_authenticated={'true' if status['authenticated'] else 'false'}")
        if status.get("saved_at"):
            print(f"unity_auth_saved_at={status['saved_at']}")
        print(f"unity_auth_state_stale={'true' if status.get('auth_state_stale') else 'false'}")
        if status.get("repair_command"):
            print(f"unity_auth_repair_command={status['repair_command']}")
        print(f"unity_api_checked={'true' if status['api_checked'] else 'false'}")
        print(f"unity_api_authenticated={'true' if status['api_authenticated'] else 'false'}")
        if status["current_user_id"]:
            print(f"unity_current_user_id={status['current_user_id']}")
        if status["current_user_name"]:
            print(f"unity_current_user_name={status['current_user_name']}")
        if status["current_user_email"]:
            print(f"unity_current_user_email={status['current_user_email']}")
        print(f"unity_login_prompt_visible={'true' if status['login_prompt_visible'] else 'false'}")
        if status["page_url"]:
            print(f"unity_page_url={status['page_url']}")
        if status["page_title"]:
            print(f"unity_page_title={status['page_title']}")
        if status["error"]:
            print(f"unity_auth_error={status['error']}")
            return 1
        return 0

    if args.command == "fab-download":
        listing_ref = args.listing_id or args.listing_url or ""
        return _run_fab_download(
            listing_ref=listing_ref,
            output_path=args.output,
            pack_id=args.pack_id,
            game_scope=args.game_scope,
            vault_item=args.vault_item,
            engine_association=args.engine_association,
            project_name=args.project_name,
            project_dir=args.project_dir,
            job_output_dir=args.job_output_dir,
        )

    if args.command == "run-fab-batch":
        return _run_fab_batch(
            listing_file=args.listing_file,
            output_dir=args.output_dir,
            game_scope=args.game_scope,
            engine_association=args.engine_association,
            project_name=args.project_name,
            project_dir=args.project_dir,
        )

    if args.command == "run-fab-fallback-actions":
        return _run_fab_fallback_actions(
            actions_file=args.actions_file,
            execute=args.execute,
            headless=args.headless,
            browser_profile_dir=args.browser_profile_dir,
            timeout_ms=args.timeout_ms,
            retries=args.retries,
            run_pwsh=args.run_pwsh,
            hydrate_provenance=args.hydrate_provenance,
            prepare_pack=args.prepare_pack,
            auto_intake=args.auto_intake,
            cleanup_mode=args.cleanup_mode,
            asset_kind=args.asset_kind,
            animated=args.animated,
            packet_status=args.packet_status,
            overwrite_packet=args.overwrite_packet,
            verify_hashes=args.verify_hashes,
            pwsh_timeout_sec=args.pwsh_timeout_sec,
            continue_on_error=args.continue_on_error,
            require_complete=args.require_complete,
            as_json=args.as_json,
        )

    # â”€â”€ Prepared / manual execution commands â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if args.command == "run-hunyuan-batch":
        from assetboy.providers.generator import emit_generator_setup
        from assetboy.execution.colab_runner import submit_batch_to_colab
        artifacts = emit_generator_setup(
            profile_id="hunyuan3d2.production",
            pack_id=args.pack_id,
            game_scope=args.game_scope,
            output_dir=args.output_dir,
        )
        result = submit_batch_to_colab(
            batch_path=artifacts.prompt_batch_path,
            output_dir=args.output_dir,
            drive_folder=args.drive_folder,
            dry_run=args.dry_run,
        )
        print(f"run_hunyuan_output_dir={result.output_dir}")
        print(f"run_hunyuan_batch_path={result.batch_path}")
        print(f"run_hunyuan_jobs={result.job_count}")
        print(f"run_hunyuan_drive_folder={result.drive_folder}")
        print(f"run_hunyuan_handoff_manifest={result.handoff_manifest_path}")
        print(f"run_hunyuan_drive_stage_plan={result.drive_stage_plan_path}")
        print(f"run_hunyuan_dry_run={result.dry_run}")
        return 0

    if args.command == "run-colab-batch":
        from assetboy.execution.colab_runner import submit_batch_to_colab

        result = submit_batch_to_colab(
            batch_path=args.batch_file,
            output_dir=args.output_dir,
            drive_folder=args.drive_folder,
            dry_run=args.dry_run,
        )
        print(f"run_colab_output_dir={result.output_dir}")
        print(f"run_colab_jobs={result.job_count}")
        print(f"run_colab_drive_folder={result.drive_folder}")
        print(f"run_colab_handoff_manifest={result.handoff_manifest_path}")
        print(f"run_colab_drive_stage_plan={result.drive_stage_plan_path}")
        print(f"run_colab_dry_run={result.dry_run}")
        return 0

    if args.command == "run-browser-job":
        from assetboy.execution.playwright_runner import run_browser_job

        result = run_browser_job(
            job_spec_path=args.job_spec,
            dry_run=args.dry_run,
            execute=args.execute,
            headed=not args.headless,
            browser_profile_dir=args.browser_profile_dir,
            timeout_ms=args.timeout_ms,
            retries=args.retries,
        )
        print(f"run_browser_source_adapter={result.source_adapter}")
        print(f"run_browser_pack_id={result.pack_id}")
        print(f"run_browser_steps={len(result.steps_emitted)}")
        print(f"run_browser_dry_run={result.dry_run}")
        print(f"run_browser_executed={result.executed}")
        print(f"run_browser_mode={result.execution_mode}")
        print(f"run_browser_attempts={result.attempts}")
        if result.browser_profile_dir is not None:
            print(f"run_browser_profile_dir={result.browser_profile_dir}")
        if result.artifacts_dir is not None:
            print(f"run_browser_artifacts={result.artifacts_dir}")
        if result.last_url:
            print(f"run_browser_last_url={result.last_url}")
        if result.error:
            print(f"run_browser_error={result.error}")
        repair_reason = _safe_result_text_attr(result, "repair_reason")
        repair_command = _safe_result_text_attr(result, "repair_command")
        provider_runbook_id = _safe_result_text_attr(result, "provider_runbook_id")
        if repair_reason:
            print(f"run_browser_repair_reason={repair_reason}")
        if repair_command:
            print(f"run_browser_repair_command={repair_command}")
        if provider_runbook_id:
            print(f"run_browser_provider_runbook={provider_runbook_id}")
        postprocess_status = ""
        if args.execute and result.execution_mode not in {"failed", "interactive_required", "repair_required"} and (
            args.hydrate_provenance or args.prepare_pack or args.auto_intake
        ):
            try:
                postprocess = _postprocess_browser_job(
                    job_spec_path=args.job_spec,
                    artifacts_dir=Path(result.artifacts_dir) if result.artifacts_dir is not None else None,
                    last_url=result.last_url,
                    fallback_pack_id="",
                    fallback_game_scope="",
                    hydrate_provenance=args.hydrate_provenance,
                    prepare_pack=args.prepare_pack,
                    cleanup_mode=args.cleanup_mode,
                    asset_kind=args.asset_kind,
                    animated=args.animated,
                    packet_status=args.packet_status,
                    overwrite_packet=args.overwrite_packet,
                    verify_hashes=args.verify_hashes,
                    auto_intake=args.auto_intake,
                )
            except Exception as exc:  # noqa: BLE001
                postprocess = {"status": "failed", "error": str(exc)}
            postprocess_status = str(postprocess.get("status", "")).strip()
            print(f"run_browser_post_status={postprocess_status}")
            if postprocess.get("source_dir"):
                print(f"run_browser_source_dir={postprocess['source_dir']}")
            hydration = postprocess.get("hydration")
            if isinstance(hydration, dict):
                print(f"run_browser_hydration_status={hydration.get('status', '')}")
                if hydration.get("provenance_path"):
                    print(f"run_browser_provenance={hydration['provenance_path']}")
                if hydration.get("hydration_report_path"):
                    print(f"run_browser_hydration_report={hydration['hydration_report_path']}")
                if "register_packet_ready" in hydration:
                    print(f"run_browser_register_packet_ready={'true' if hydration.get('register_packet_ready') else 'false'}")
                confidence_band = str(hydration.get("provenance_confidence_band", "")).strip()
                if confidence_band:
                    print(f"run_browser_provenance_confidence_band={confidence_band}")
                if "provenance_confidence_score" in hydration:
                    print(f"run_browser_provenance_confidence_score={hydration.get('provenance_confidence_score', 0)}")
            prepare_result = postprocess.get("prepare_pack")
            if isinstance(prepare_result, dict):
                print(f"run_browser_prepare_pack_state={prepare_result.get('current_state', '')}")
                if prepare_result.get("packet_path"):
                    print(f"run_browser_packet_path={prepare_result['packet_path']}")
            auto_intake_result = postprocess.get("auto_intake")
            if isinstance(auto_intake_result, dict):
                print(f"run_browser_auto_intake_pass={'true' if auto_intake_result.get('pass') else 'false'}")
                if auto_intake_result.get("handoff_receipt_path"):
                    print(f"run_browser_handoff_receipt={auto_intake_result['handoff_receipt_path']}")
            postprocess_error = str(postprocess.get("error", "")).strip()
            if postprocess_error:
                print(f"run_browser_post_error={postprocess_error}")
        if args.execute and (
            result.execution_mode in {"failed", "interactive_required", "repair_required"}
            or postprocess_status in {"failed", "pending_manual"}
        ):
            return 1
        return 0

    if args.command == "run-blender-cleanup":
        from assetboy.execution.blender_runner import run_blender_cleanup

        asset_kind, animated = _resolve_pack_cleanup_defaults(args.pack_id, args.asset_kind, args.animated)
        result = run_blender_cleanup(
            pack_id=args.pack_id,
            input_dir=args.input_dir,
            asset_kind=asset_kind,
            animated=animated,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
        )
        print(f"run_blender_output_dir={result.output_dir}")
        print(f"run_blender_formats={','.join(result.export_formats)}")
        print(f"run_blender_dry_run={result.dry_run}")
        return 0

    if args.command == "run-roman-cleanup-wave":
        from assetboy.execution.blender_runner import run_roman_blender_cleanup_wave

        result = run_roman_blender_cleanup_wave(
            game_scope=args.game_scope,
            pack_ids=args.pack_ids,
            input_root=args.input_root,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
        )
        print(f"roman_cleanup_output_dir={result.output_dir}")
        print(f"roman_cleanup_manifest={result.manifest_path}")
        print(f"roman_cleanup_summary={result.summary_path}")
        print(f"roman_cleanup_total={result.total_packs}")
        print(f"roman_cleanup_blender_required={result.blender_required_packs}")
        print(f"roman_cleanup_ready={result.cleanup_ready_packs}")
        print(f"roman_cleanup_blocked={result.blocked_packs}")
        print(f"roman_cleanup_skipped={result.skipped_packs}")
        for pack in result.packs:
            print(
                f"roman_cleanup_pack={pack.pack_id} status={pack.status} "
                f"kind={pack.asset_kind} animated={str(pack.animated).lower()}"
            )
        return 0

    if args.command == "run-local-image-batch":
        from assetboy.execution.local_image_runner import UI_PROMPT_TEMPLATES, run_local_image_batch

        if args.list_templates:
            for name, tpl in UI_PROMPT_TEMPLATES.items():
                print(f"  {name}: {tpl['prompt'][:70]}...")
            return 0
        result = run_local_image_batch(
            pack_id=args.pack_id,
            game_scope=args.game_scope,
            prompt=args.prompt,
            count=args.count,
            width=args.width,
            height=args.height,
            steps=args.steps,
            cfg=args.cfg,
            model_path=args.model_path,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
        )
        print(f"run_local_img_generated={len(result.generated)}")
        print(f"run_local_img_skipped={len(result.skipped)}")
        print(f"run_local_img_output_dir={result.output_dir}")
        return 0

    if args.command == "run-polyhaven-batch":
        from assetboy.execution.polyhaven_runner import run_polyhaven_batch

        results = run_polyhaven_batch(
            category=args.category,
            search=args.search,
            pack_id=args.pack_id,
            count=args.count,
            resolution=args.resolution,
            use_presets=args.use_presets,
            dry_run=args.dry_run,
        )
        for r in results:
            print(f"polyhaven_pack={r.pack_id} category={r.category} steps={r.job_spec_path}")
        return 0

    if args.command == "run-mixamo-batch":
        from assetboy.execution.playwright_runner import run_mixamo_batch

        results = run_mixamo_batch(
            pack_id=args.pack_id,
            search=args.search,
            asset_type=args.asset_type,
            output_dir=args.output_dir,
            use_presets=args.use_presets,
            execute=args.execute,
            headed=not args.headless,
            browser_profile_dir=args.browser_profile_dir,
            timeout_ms=args.timeout_ms,
            dry_run=args.dry_run,
        )
        for r in results:
            print(
                f"mixamo_pack={r.pack_id} search={r.search} steps={len(r.steps)} "
                f"executed={r.executed} mode={r.execution_mode}"
            )
            if r.artifacts_dir is not None:
                print(f"mixamo_artifacts={r.artifacts_dir}")
        return 0

    if args.command == "run-freesound-batch":
        from assetboy.execution.freesound_runner import run_freesound_batch

        results = run_freesound_batch(
            search=args.search,
            pack_id=args.pack_id,
            game_scope="roman_arena",
            count=args.count,
            output_dir=args.output_dir,
            use_presets=args.use_presets,
            execute=args.execute,
            headed=not args.headless,
            browser_profile_dir=args.browser_profile_dir,
            timeout_ms=args.timeout_ms,
            dry_run=args.dry_run,
        )
        for r in results:
            print(
                f"freesound_pack={r.pack_id} search={r.search} steps={len(r.steps)} "
                f"executed={r.executed} mode={r.execution_mode}"
            )
            if r.artifacts_dir is not None:
                print(f"freesound_artifacts={r.artifacts_dir}")
        return 0

    if args.command == "run-music-batch":
        from assetboy.execution.music_runner import run_music_batch

        results = run_music_batch(
            source=args.source,
            prompt=args.prompt,
            search=args.search,
            pack_id=args.pack_id,
            game_scope="roman_arena",
            count=args.count,
            output_dir=args.output_dir,
            use_presets=args.use_presets,
            execute=args.execute,
            headed=not args.headless,
            browser_profile_dir=args.browser_profile_dir,
            timeout_ms=args.timeout_ms,
            dry_run=args.dry_run,
        )
        for r in results:
            print(
                f"music_pack={r.pack_id} source={r.source} steps={len(r.steps)} "
                f"executed={r.executed} mode={r.execution_mode}"
            )
            if r.artifacts_dir is not None:
                print(f"music_artifacts={r.artifacts_dir}")
        return 0

    if args.command == "run-comfyui-batch":
        from assetboy.execution.comfyui_runner import run_comfyui_batch

        results = run_comfyui_batch(
            prompt=args.prompt,
            pack_id=args.pack_id,
            asset_type=args.asset_type,
            width=args.width,
            height=args.height,
            steps=args.steps,
            cfg=args.cfg,
            input_image=args.input_image,
            use_presets=args.use_presets,
            dry_run=args.dry_run,
        )
        for r in results:
            print(f"comfyui_pack={r.pack_id} type={r.asset_type} outputs={len(r.outputs)}")
        return 0


    if args.command == "run-quaternius-batch":
        from assetboy.execution.quaternius_runner import (
            list_presets as quaternius_list_presets,
            run_quaternius_batch,
            run_quaternius_presets,
        )

        if args.list_presets:
            for pid, url, desc in quaternius_list_presets():
                print(f"  {pid}  {desc}")
                print(f"    {url}")
            return 0
        if args.use_presets:
            results = run_quaternius_presets(game_scope=args.game_scope, dry_run=args.dry_run)
            for r in results:
                print(f"quaternius_pack={r.pack_id} files={len(r.files_extracted)} dry_run={r.dry_run}")
            return 0
        if not args.pack_id or not args.url:
            print("[ERROR] --pack-id and --url are required unless --use-presets or --list-presets is set.")
            return 2
        r = run_quaternius_batch(
            pack_id=args.pack_id,
            source_url=args.url,
            game_scope=args.game_scope,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
        )
        print(f"quaternius_pack={r.pack_id} files={len(r.files_extracted)} dry_run={r.dry_run}")
        return 0

    if args.command == "run-mixamo-glb-merge":
        from assetboy.execution.mixamo_glb_runner import run_mixamo_glb_merge

        r = run_mixamo_glb_merge(
            pack_id=args.pack_id,
            char_fbx=args.char_fbx,
            anim_fbxs=args.anim_fbxs,
            game_scope=args.game_scope,
            output_dir=args.output_dir,
            blender_exe=args.blender_exe,
            dry_run=args.dry_run,
        )
        print(f"mixamo_glb_pack={r.pack_id}")
        print(f"mixamo_glb_char={r.char_glb}")
        print(f"mixamo_glb_anims_dir={r.anims_dir}")
        print(f"mixamo_glb_clips={len(r.anim_fbxs)}")
        print(f"mixamo_glb_plan={r.merge_plan_path}")
        print(f"mixamo_glb_dry_run={r.dry_run}")
        return 0

    if args.command == "build-dungeon":
        return _run_build_dungeon(
            preset=args.preset,
            name=args.name,
            tile_size=args.tile_size,
            port=args.port,
        )

    if args.command == "run-bulk":
        return _run_json_wrapper(
            execute_run_bulk(
                profile=args.profile,
                game_scope=args.game_scope,
                pack_ids=args.pack_ids,
                output_dir=args.output_dir,
                tags_filter=args.tags_filter,
                count=args.count,
                resolution=args.resolution,
                category_filter=args.category_filter,
                dry_run=args.dry_run,
                continue_on_error=args.continue_on_error,
                job_id=args.job_id,
            )
        )

    if args.command == "run-cleanup":
        asset_kind, animated = _resolve_pack_cleanup_defaults(args.pack_id, args.asset_kind, args.animated)
        return _run_json_wrapper(
            execute_run_cleanup(
                pack_id=args.pack_id,
                input_dir=args.input_dir,
                game_scope=args.game_scope,
                asset_kind=asset_kind,
                animated=animated,
                output_dir=args.output_dir,
                dry_run=args.dry_run,
                job_id=args.job_id,
            )
        )

    if args.command == "prepare-pack":
        asset_kind, animated = _resolve_pack_cleanup_defaults(args.pack_id, args.asset_kind, args.animated)
        return _run_json_wrapper(
            execute_prepare_pack(
                pack_id=args.pack_id,
                game_scope=args.game_scope,
                source_dir=args.source_dir,
                bulk_profile=args.bulk_profile,
                cleanup_mode=args.cleanup_mode,
                asset_kind=asset_kind,
                animated=animated,
                bulk_output_dir=args.bulk_output_dir,
                cleanup_output_dir=args.cleanup_output_dir,
                packet_status=args.packet_status,
                overwrite_packet=args.overwrite_packet,
                verify_hashes=args.verify_hashes,
                dry_run=args.dry_run,
                resume=args.resume,
            )
        )

    if args.command == "pack-status":
        return _run_json_wrapper(
            read_pack_pipeline_status(
                pack_id=args.pack_id,
                game_scope=args.game_scope,
            )
        )

    if args.command == "register-packet":
        return _run_json_wrapper(
            execute_register_packet(
                pack_id=args.pack_id,
                game_scope=args.game_scope,
                source_dir=args.source_dir,
                overwrite=args.overwrite,
                packet_status=args.packet_status,
                verify_hashes=args.verify_hashes,
                job_id=args.job_id,
            )
        )

    if args.command == "get-job-status":
        return _run_json_wrapper(execute_get_job_status(job_id=args.job_id))

    if args.command == "run-kenney-batch":
        from assetboy.execution.kenney_runner import (
            list_presets as kenney_list_presets,
            run_kenney_batch,
            run_kenney_presets,
        )

        if getattr(args, "list_presets", False):
            for pid, url, desc in kenney_list_presets():
                print(f"  {pid}  {desc}")
                print(f"    {url}")
            return 0
        if getattr(args, "use_presets", False):
            kw_filter = getattr(args, "tags_filter", None)
            tags = kw_filter.split(",") if kw_filter else None
            results = run_kenney_presets(
                game_scope=getattr(args, "game_scope", "shared"),
                dry_run=getattr(args, "dry_run", False),
                tags_filter=tags,
            )
            for r in results:
                print(f"kenney_pack={r.pack_id} files={len(r.files_extracted)} dry_run={r.dry_run}")
            return 0
        if not getattr(args, "pack_id", None) or not getattr(args, "url", None):
            print("[ERROR] --pack-id and --url are required unless --use-presets or --list-presets is set.")
            return 2
        r = run_kenney_batch(
            pack_id=args.pack_id,
            source_url=args.url,
            game_scope=getattr(args, "game_scope", "shared"),
            output_dir=getattr(args, "output_dir", None),
            dry_run=getattr(args, "dry_run", False),
        )
        print(f"kenney_pack={r.pack_id} files={len(r.files_extracted)} dry_run={r.dry_run}")
        return 0

    if args.command == "run-game-icons":
        from assetboy.execution.game_icons_runner import (
            list_categories as game_icons_list_categories,
            run_game_icons,
        )

        if getattr(args, "list_categories", False):
            for cat in game_icons_list_categories():
                print(f"  {cat}")
            return 0
        r = run_game_icons(
            output_dir=getattr(args, "output_dir", None),
            category_filter=getattr(args, "filter", None),
            game_scope=getattr(args, "game_scope", "shared"),
            dry_run=getattr(args, "dry_run", False),
        )
        print(f"game_icons_total={r.total_icons} kept={r.filtered_icons} dry_run={r.dry_run}")
        print(f"game_icons_output={r.output_dir}")
        return 0

    if args.command == "run-font-batch":
        from assetboy.execution.font_runner import (
            list_presets as font_list_presets,
            run_font_batch,
            run_font_presets,
        )

        if getattr(args, "list_presets", False):
            for pid, url, desc in font_list_presets():
                print(f"  {pid}: {desc}")
            return 0
        if getattr(args, "use_presets", False):
            results = run_font_presets(
                game_scope=getattr(args, "game_scope", "shared"),
                dry_run=getattr(args, "dry_run", False),
                tags_filter=getattr(args, "tags_filter", None),
            )
            print(f"font_runner downloaded={sum(len(r.files_downloaded) for r in results)} packs={len(results)}")
        else:
            url = getattr(args, "url", None)
            if not url:
                parser.error("run-font-batch: --url required unless --use-presets")
            r = run_font_batch(
                pack_id=getattr(args, "pack_id", "FONT_CUSTOM"),
                source_url=url,
                game_scope=getattr(args, "game_scope", "shared"),
                dry_run=getattr(args, "dry_run", False),
            )
            print(f"font_runner downloaded={r.files_downloaded}")
        return 0

    if args.command == "run-vfx-batch":
        from assetboy.execution.vfx_runner import (
            list_presets as vfx_list_presets,
            print_oga_manual_targets,
            run_vfx_batch,
            run_vfx_presets,
        )

        if getattr(args, "list_presets", False):
            for pid, url, desc in vfx_list_presets():
                print(f"  {pid}: {desc}")
            return 0
        if getattr(args, "show_oga", False):
            print_oga_manual_targets()
            return 0
        if getattr(args, "use_presets", False):
            results = run_vfx_presets(
                game_scope=getattr(args, "game_scope", "shared"),
                dry_run=getattr(args, "dry_run", False),
                tags_filter=getattr(args, "tags_filter", None),
            )
            print(f"vfx_runner extracted={sum(len(r.files_extracted) for r in results)} packs={len(results)}")
        else:
            url = getattr(args, "url", None)
            if not url:
                parser.error("run-vfx-batch: --url required unless --use-presets")
            r = run_vfx_batch(
                pack_id=getattr(args, "pack_id", "VFX_CUSTOM"),
                source_url=url,
                game_scope=getattr(args, "game_scope", "shared"),
                dry_run=getattr(args, "dry_run", False),
            )
            print(f"vfx_runner extracted={r.files_extracted}")
        return 0

    if args.command == "run-animationgpt":
        from assetboy.execution.animationgpt_runner import (
            list_presets as animationgpt_list_presets,
            run_animationgpt_presets,
        )

        if getattr(args, "list_presets", False):
            for pid, motion, summary in animationgpt_list_presets():
                print(f"  {pid} [{motion}]: {summary}")
            return 0
        results = run_animationgpt_presets(
            game_scope=getattr(args, "game_scope", "roman_arena"),
            pack_id=getattr(args, "pack_id", None),
            tags_filter=getattr(args, "tags_filter", None),
            dry_run=getattr(args, "dry_run", False),
        )
        print(f"animationgpt jobs={results.total_jobs} script={results.colab_script_path}")
        return 0

    if args.command == "run-museum-batch":
        from assetboy.execution.museum_runner import (
            list_presets as museum_list_presets,
            run_museum_presets,
        )

        if getattr(args, "list_presets", False):
            for pid, url, desc in museum_list_presets():
                print(f"  {pid}: {desc}")
            return 0
        results = run_museum_presets(
            game_scope=getattr(args, "game_scope", "roman_arena"),
            dry_run=getattr(args, "dry_run", False),
            tags_filter=getattr(args, "tags_filter", None),
        )
        print(f"museum_runner packs={len(results)}")
        return 0

    if args.command == "run-vehicle-batch":
        from assetboy.execution.vehicle_runner import (
            list_presets as vehicle_list_presets,
            run_vehicle_batch,
            run_vehicle_presets,
        )

        if getattr(args, "list_presets", False):
            for pid, url, desc in vehicle_list_presets():
                print(f"  {pid}: {desc}")
            return 0
        if getattr(args, "use_presets", False):
            results = run_vehicle_presets(
                game_scope=getattr(args, "game_scope", "shared"),
                dry_run=getattr(args, "dry_run", False),
                tags_filter=getattr(args, "tags_filter", None),
            )
            print(f"vehicle_runner extracted={sum(len(r.files_extracted) for r in results)} packs={len(results)}")
        else:
            url = getattr(args, "url", None)
            if not url:
                parser.error("run-vehicle-batch: --url required unless --use-presets")
            r = run_vehicle_batch(
                pack_id=getattr(args, "pack_id", "VEH_CUSTOM"),
                source_url=url,
                game_scope=getattr(args, "game_scope", "shared"),
                dry_run=getattr(args, "dry_run", False),
            )
            print(f"vehicle_runner extracted={r.files_extracted}")
        return 0

    if args.command == "run-skybox-batch":
        from assetboy.execution.polyhaven_runner import run_skybox_presets

        results = run_skybox_presets(
            count=getattr(args, "count", 3),
            resolution=getattr(args, "resolution", "2k"),
            dry_run=getattr(args, "dry_run", False),
            tags_filter=getattr(args, "tags_filter", None),
        )
        print(f"skybox_runner batches={len(results)}")
        return 0

    if args.command == "run-terrain-batch":
        from assetboy.execution.polyhaven_runner import run_terrain_presets

        results = run_terrain_presets(
            count=getattr(args, "count", 3),
            resolution=getattr(args, "resolution", "2k"),
            dry_run=getattr(args, "dry_run", False),
            tags_filter=getattr(args, "tags_filter", None),
        )
        print(f"terrain_runner batches={len(results)}")
        return 0

    if args.command == "run-tts-batch":
        from assetboy.execution.dialogue_runner import run_dialogue_line

        filename_hint = str(getattr(args, "filename", "vo_line.mp3") or "vo_line.mp3").strip()
        explicit_line_id = str(getattr(args, "line_id", "") or "").strip()
        derived_line_id = Path(filename_hint).stem.strip() if filename_hint else ""
        line_id = explicit_line_id or derived_line_id or "DIA_CUSTOM"

        result = run_dialogue_line(
            line_id=line_id,
            text=getattr(args, "text", ""),
            voice_type=getattr(args, "voice", "announcer"),
            game_scope=getattr(args, "game_scope", "roman_arena"),
            output_dir=getattr(args, "output_dir", None),
            dry_run=getattr(args, "dry_run", False),
            provider=getattr(args, "provider", "edge_tts"),
            audio_class=getattr(args, "audio_class", "voice_npc"),
            operator=getattr(args, "operator", None),
        )

        print(
            "tts_runner "
            f"line_id={result.line_id} "
            f"provider={result.provider} "
            f"success={result.success} "
            f"file={result.output_path}"
        )
        return 0

    if args.command == "run-dialogue-batch":
        from assetboy.execution.dialogue_runner import (
            list_presets as dialogue_list_presets,
            run_dialogue_line,
            run_dialogue_presets,
        )

        if getattr(args, "list_presets", False):
            for lid, vt, text in dialogue_list_presets():
                print(f"  {lid} [{vt}]: {text}")
            return 0
        text = getattr(args, "text", None)
        if text:
            r = run_dialogue_line(
                line_id=getattr(args, "line_id", "DIA_CUSTOM"),
                text=text,
                voice_type=getattr(args, "voice", "announcer"),
                game_scope=getattr(args, "game_scope", "roman_arena"),
                dry_run=getattr(args, "dry_run", False),
                provider=getattr(args, "provider", "edge_tts"),
                audio_class=getattr(args, "audio_class", "voice_npc"),
                operator=getattr(args, "operator", None),
            )
            print(f"dialogue_runner provider={r.provider} success={r.success} file={r.output_path}")
        else:
            results = run_dialogue_presets(
                game_scope=getattr(args, "game_scope", "roman_arena"),
                dry_run=getattr(args, "dry_run", False),
                voice_type_filter=getattr(args, "voice", None),
                tags_filter=getattr(args, "tags_filter", None),
                provider=getattr(args, "provider", "edge_tts"),
                audio_class=getattr(args, "audio_class", "voice_npc"),
                operator=getattr(args, "operator", None),
            )
            done = sum(1 for r in results if r.success)
            print(f"dialogue_runner lines={done}/{len(results)}")
        return 0

    if args.command == "check-publish":
        return _run_check_publish(args.game, as_json=args.as_json, include_examples=args.include_examples)

    if args.command == "auto-intake":
        return _run_auto_intake(
            args.game,
            args.pack_id,
            dry_run=args.dry_run,
            as_json=args.as_json,
            include_examples=args.include_examples,
        )

    if args.command == "write-packet":
        return _run_write_packet(
            pack_id=args.pack_id,
            game_scope=args.game_scope,
            payload_dir=args.payload_dir,
            source_url=args.source_url,
            license_name=args.license_name,
            author=args.author,
            lane=args.lane,
            notes=args.notes,
            dry_run=args.dry_run,
            verify_hashes=args.verify_hashes,
        )

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
