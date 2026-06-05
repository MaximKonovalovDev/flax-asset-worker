from __future__ import annotations

import io
import json
import shutil
import traceback
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

# Path B s2.6c (2026-05-11): the 10 DEAD-runner imports below have been
# removed because v1.2 retires the bulk-profile dispatch path (_run_bulk_impl).
# Recipes drive pack runs directly via pack_pipeline.execute_prepare_pack; the
# bulk path will be re-introduced by the s11 acquisition router with a clean
# contract instead of the kitchen-sink fan-out _run_bulk_impl used to do.
#
# Removed:
#   - animationgpt_runner.run_animationgpt_presets         (DEAD; data in data/animationgpt_presets.yaml)
#   - dialogue_runner.DIALOGUE_PRESETS, run_dialogue_presets (DEAD; data in data/dialogue_presets.yaml)
#   - font_runner.FONT_PRESETS, run_font_batch              (DEAD; data in data/font_presets.yaml)
#   - game_icons_runner.run_game_icons                      (DEAD; data in data/game_icons_presets.yaml)
#   - music_runner.ROMAN_MUSIC_PRESETS, run_music_batch     (DEAD; data in data/music_presets.yaml)
#   - museum_runner.MUSEUM_PRESETS, run_museum_batch        (DEAD; data in data/museum_presets.yaml)
#   - playwright_runner._MIXAMO_CHARACTER_PRESETS, run_mixamo_batch (DEAD)
#   - quaternius_runner.QUATERNIUS_PRESETS, run_quaternius_batch    (DEAD)
#   - vfx_runner.VFX_PRESETS, run_vfx_batch                          (DEAD)
#   - vehicle_runner.VEHICLE_PRESETS, run_vehicle_batch              (DEAD)

from assetboy.execution.ambientcg_runner import AMBIENTCG_PRESETS, run_ambientcg_pack
from assetboy.execution.comfyui_runner import ROMAN_MATERIAL_PRESETS, run_comfyui_batch
from assetboy.execution.freesound_runner import ROMAN_SFX_PRESETS, run_freesound_batch
from assetboy.execution.kenney_runner import KENNEY_PRESETS, run_kenney_batch
from assetboy.execution.polyhaven_runner import (
    ROMAN_PRESETS,
    SKYBOX_PRESETS,
    TERRAIN_PRESETS,
    run_polyhaven_batch,
)
from assetboy.library.asset_metadata import (
    build_asset_metadata,
    load_generator_registry,
    write_asset_metadata,
)
from assetboy.library.packet_writer import PacketManifest, SUPPORTED_EXTENSIONS, build_payload_manifest
from assetboy.library.paths import asset_library_root, state_root
from assetboy.provenance.schema import canonicalize_provenance_payload, validate_provenance_payload
from assetboy.providers.lanes import (
    canonical_lane_value,
    canonical_source_adapter_id,
    require_source_adapter,
    resolve_lane_destination,
)


DEFAULT_PACKET_STATUS = "ai_reviewed"
DIRECT_URL_PROFILES = {
    "ambientcg_presets",
    "quaternius_presets",
    "kenney_presets",
    "game_icons",
    "font_presets",
    "vfx_presets",
    "vehicle_presets",
}
MANUAL_BROWSER_PROFILES = {
    "freesound_presets",
    "mixamo_presets",
    "music_presets",
    "museum_presets",
    "polyhaven_roman",
    "skybox_presets",
    "terrain_presets",
}
GENERATOR_PROFILES = {
    "animationgpt_presets",
    "comfyui_presets",
    "dialogue_presets",
}
SUPPORTED_BULK_PROFILES = DIRECT_URL_PROFILES | MANUAL_BROWSER_PROFILES | GENERATOR_PROFILES


def execute_run_bulk(
    *,
    profile: str,
    game_scope: str,
    pack_ids: Sequence[str] | None = None,
    output_dir: str | Path | None = None,
    tags_filter: Sequence[str] | None = None,
    count: int = 3,
    resolution: str = "2k",
    category_filter: str | None = None,
    dry_run: bool = False,
    continue_on_error: bool = False,
    job_id: str | None = None,
) -> dict[str, Any]:
    return _execute_command(
        command="run-bulk",
        job_id=job_id,
        metadata={
            "profile": profile,
            "game_scope": game_scope,
            "pack_ids": list(pack_ids or []),
        },
        runner=lambda: _run_bulk_impl(
            profile=profile,
            game_scope=game_scope,
            pack_ids=pack_ids,
            output_dir=output_dir,
            tags_filter=tags_filter,
            count=count,
            resolution=resolution,
            category_filter=category_filter,
            dry_run=dry_run,
            continue_on_error=continue_on_error,
        ),
    )


def execute_run_cleanup(
    *,
    pack_id: str,
    input_dir: str | Path,
    game_scope: str,
    asset_kind: str = "prop",
    animated: bool = False,
    output_dir: str | Path | None = None,
    dry_run: bool = False,
    job_id: str | None = None,
) -> dict[str, Any]:
    return _execute_command(
        command="run-cleanup",
        job_id=job_id,
        metadata={
            "pack_id": pack_id,
            "game_scope": game_scope,
            "asset_kind": asset_kind,
            "animated": animated,
        },
        runner=lambda: _run_cleanup_impl(
            pack_id=pack_id,
            input_dir=input_dir,
            game_scope=game_scope,
            asset_kind=asset_kind,
            animated=animated,
            output_dir=output_dir,
            dry_run=dry_run,
        ),
    )


def execute_register_packet(
    *,
    pack_id: str,
    game_scope: str,
    source_dir: str | Path,
    overwrite: bool = False,
    packet_status: str = DEFAULT_PACKET_STATUS,
    verify_hashes: bool = True,
    job_id: str | None = None,
) -> dict[str, Any]:
    return _execute_command(
        command="register-packet",
        job_id=job_id,
        metadata={
            "pack_id": pack_id,
            "game_scope": game_scope,
            "source_dir": str(source_dir),
        },
        runner=lambda: _register_packet_impl(
            pack_id=pack_id,
            game_scope=game_scope,
            source_dir=source_dir,
            overwrite=overwrite,
            packet_status=packet_status,
            verify_hashes=verify_hashes,
        ),
    )


def execute_get_job_status(*, job_id: str) -> dict[str, Any]:
    try:
        payload = _read_job_state(job_id)
    except FileNotFoundError as exc:
        return {
            "command": "get-job-status",
            "job_id": job_id,
            "status": "failed",
            "error": str(exc),
            "completed_at_utc": _utc_now(),
        }

    payload = dict(payload)
    payload.setdefault("command", "get-job-status")
    payload.setdefault("job_id", job_id)
    return payload


def _execute_command(
    *,
    command: str,
    job_id: str | None,
    metadata: dict[str, Any],
    runner,
) -> dict[str, Any]:
    started_at_utc = _utc_now()
    if job_id:
        _write_job_state(
            job_id,
            {
                "command": command,
                "job_id": job_id,
                "status": "running",
                "started_at_utc": started_at_utc,
                "metadata": metadata,
            },
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = runner()
        payload = {
            "command": command,
            "job_id": job_id,
            "status": "completed",
            "started_at_utc": started_at_utc,
            "completed_at_utc": _utc_now(),
            "stdout_tail": _tail(stdout.getvalue()),
            "stderr_tail": _tail(stderr.getvalue()),
        }
        payload.update(result)
        if job_id:
            _write_job_state(job_id, payload)
        return payload
    except Exception as exc:  # noqa: BLE001
        payload = {
            "command": command,
            "job_id": job_id,
            "status": "failed",
            "started_at_utc": started_at_utc,
            "completed_at_utc": _utc_now(),
            "stdout_tail": _tail(stdout.getvalue()),
            "stderr_tail": _tail(stderr.getvalue()),
            "error": str(exc),
            "error_type": type(exc).__name__,
            "traceback_tail": _tail(traceback.format_exc()),
        }
        if job_id:
            _write_job_state(job_id, payload)
        return payload


def _run_bulk_impl(
    *,
    profile: str,
    game_scope: str,
    pack_ids=None,
    output_dir=None,
    tags_filter=None,
    count: int = 1,
    resolution: str = "",
    category_filter=None,
    dry_run: bool = False,
    continue_on_error: bool = False,
) -> dict:
    """Path B s2.6c (2026-05-11): _run_bulk_impl body retired.

    The original 396-line implementation fanned out to 10 DEAD execution
    runners (animationgpt, dialogue, font, game_icons, music, museum,
    mixamo, quaternius, vfx, vehicle). With those runners removed in
    s2.6d, the bulk-profile dispatch path is no longer functional.

    Recipes drive pack runs directly via pack_pipeline.execute_prepare_pack
    today. v1.2 s11 (pre-pack acquisition router) will reintroduce bulk
    dispatch with a clean contract instead of the kitchen-sink fan-out
    this function used to do.

    Until then: calling _run_bulk_impl raises NotImplementedError. The
    pack_pipeline conditional at line ~120 (only fires if bulk_profile is
    supplied to execute_prepare_pack) is the gate; recipes don't set
    bulk_profile so this is unreachable in production today.
    """
    raise NotImplementedError(
        f"_run_bulk_impl is retired in Path B v1.2 (profile={profile!r}). "
        "Use recipe-driven pack runs via pack_pipeline.execute_prepare_pack_dispatched "
        "or wait for v1.2 s11 acquisition router. See docs/PATH_B_DAY11_PLAN.md."
    )

def _run_cleanup_impl(
    *,
    pack_id: str,
    input_dir: str | Path,
    game_scope: str,
    asset_kind: str,
    animated: bool,
    output_dir: str | Path | None,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "pack_id": pack_id,
        "game_scope": game_scope,
        "cleanup_profile": {
            "asset_kind": asset_kind,
            "animated": animated,
        },
        "input_dir": str(input_dir),
        "output_dir": str(output_dir or ""),
        "steps_run": [],
        "export_formats": [],
        "artifact_paths": [],
        "error": "Blender cleanup delegated to flax-blender-bridge plugin",
    }


def _register_packet_impl(
    *,
    pack_id: str,
    game_scope: str,
    source_dir: str | Path,
    overwrite: bool,
    packet_status: str,
    verify_hashes: bool,
) -> dict[str, Any]:
    source_root = Path(source_dir).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Source directory not found: {source_root}")

    payload_source = source_root / "payload"
    if not payload_source.is_dir():
        payload_source = source_root

    provenance_source = source_root / "provenance.json"
    if not provenance_source.exists():
        raise FileNotFoundError(f"provenance.json not found under source_dir: {source_root}")
    source_metadata_path = source_root / "asset_metadata.json"

    supported_files = [
        path for path in sorted(payload_source.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    if not supported_files:
        raise ValueError(
            f"No supported payload files found in {payload_source}. Supported extensions: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    publish_dir = _expected_publish_dir(game_scope, pack_id)
    payload_target = publish_dir / "payload"
    packet_path = publish_dir / "packet.json"
    provenance_target = publish_dir / "provenance.json"

    if publish_dir.exists():
        if not overwrite:
            existing_items = any(publish_dir.iterdir())
            if existing_items:
                raise FileExistsError(f"Publish pack already exists: {publish_dir}. Set overwrite=True to replace it.")
        else:
            shutil.rmtree(publish_dir)

    payload_target.mkdir(parents=True, exist_ok=True)

    copied_files: list[str] = []
    for source_file in supported_files:
        relative_path = source_file.relative_to(payload_source)
        destination_path = payload_target / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_path)
        copied_files.append(str(destination_path))

    try:
        provenance = json.loads(provenance_source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"provenance.json is malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}."
        ) from exc
    if not isinstance(provenance, dict):
        raise ValueError("provenance.json must contain a top-level JSON object.")

    rewritten_provenance = dict(provenance)
    rewritten_provenance["pack_id"] = pack_id
    rewritten_provenance["game_scope"] = game_scope

    raw_source_adapter = str(rewritten_provenance.get("source_adapter", "")).strip()
    canonical_source_adapter = ""
    expected_lane = ""
    if raw_source_adapter:
        normalized_source_adapter = canonical_source_adapter_id(raw_source_adapter)
        try:
            adapter_contract = require_source_adapter(normalized_source_adapter)
        except ValueError as exc:
            raise ValueError(
                f"provenance.source_adapter '{raw_source_adapter}' is invalid. "
                f"Use a canonical adapter id (for example: direct_url_queue, museum_page, chatgpt_pro). "
                f"Details: {exc}"
            ) from exc
        canonical_source_adapter = adapter_contract.adapter_id
        expected_lane = adapter_contract.lane.value

    raw_lane = str(rewritten_provenance.get("lane", "")).strip()
    if raw_lane:
        try:
            lane = canonical_lane_value(raw_lane)
        except ValueError as exc:
            raise ValueError(
                f"provenance.lane '{raw_lane}' is invalid. Use one of: direct_url, manual_browser, generator."
            ) from exc
    elif expected_lane:
        lane = expected_lane
    else:
        raise ValueError("provenance.lane is required and must use a canonical lane value.")

    if expected_lane and lane != expected_lane:
        raise ValueError(
            f"provenance.lane '{lane}' does not match source_adapter '{raw_source_adapter}' lane '{expected_lane}'."
        )

    rewritten_provenance["lane"] = lane
    if canonical_source_adapter:
        rewritten_provenance["source_adapter"] = canonical_source_adapter
    elif not str(rewritten_provenance.get("source_adapter", "")).strip():
        raise ValueError(
            "provenance.source_adapter is required and must use a canonical adapter id "
            "(for example: direct_url_queue, museum_page, chatgpt_pro)."
        )
    rewritten_provenance["payload_target_path"] = str(payload_target)
    if not str(rewritten_provenance.get("downloaded_filename", "")).strip():
        rewritten_provenance["downloaded_filename"] = supported_files[0].relative_to(payload_source).as_posix()
    _, provenance_errors, provenance_warnings = validate_provenance_payload(
        rewritten_provenance,
        expected_lane=lane,
        expected_payload_target_path=payload_target,
    )
    if provenance_errors:
        raise ValueError("Invalid provenance for packet registration: " + "; ".join(provenance_errors))
    if provenance_warnings:
        print("[WARN] provenance warnings: " + " | ".join(provenance_warnings))
    canonical_provenance = canonicalize_provenance_payload(rewritten_provenance, keep_extra=True)
    canonical_provenance["pack_id"] = pack_id
    canonical_provenance["game_scope"] = game_scope
    canonical_provenance["lane"] = lane
    canonical_provenance["source_adapter"] = str(rewritten_provenance.get("source_adapter", "")).strip()
    canonical_provenance["payload_target_path"] = str(payload_target)
    if not str(canonical_provenance.get("downloaded_filename", "")).strip():
        canonical_provenance["downloaded_filename"] = supported_files[0].relative_to(payload_source).as_posix()
    provenance_target.write_text(json.dumps(canonical_provenance, indent=2), encoding="utf-8")
    payload_manifest = build_payload_manifest(payload_target, verify_hashes=verify_hashes)
    source_metadata: dict[str, object] = {}
    if source_metadata_path.exists():
        try:
            source_metadata = json.loads(source_metadata_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            source_metadata = {}

    metadata_payload = build_asset_metadata(
        pack_id=pack_id,
        game_scope=game_scope,
        payload_files=payload_manifest,
        provenance=canonical_provenance,
        conversion_report=source_metadata.get("canonicalization")
        if isinstance(source_metadata, dict)
        else None,
        generator_registry=load_generator_registry(),
        source_folder=str(source_root),
    )
    if isinstance(source_metadata, dict):
        for extra_key in ("remote_links", "sync_links", "source_format", "sim_ready"):
            if extra_key in source_metadata and extra_key not in metadata_payload:
                metadata_payload[extra_key] = source_metadata[extra_key]
    metadata_path = write_asset_metadata(publish_dir, metadata_payload)

    manifest = PacketManifest(
        pack_id=pack_id,
        game_scope=game_scope,
        packet_status=packet_status,
        lane=lane,
        payload_path="payload",
        payload_files=payload_manifest,
    )
    packet_path.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")

    return {
        "pack_id": pack_id,
        "game_scope": game_scope,
        "packet_status": packet_status,
        "lane": lane,
        "source_dir": str(source_root),
        "source_payload_dir": str(payload_source),
        "source_provenance_path": str(provenance_source),
        "publish_dir": str(publish_dir),
        "payload_dir": str(payload_target),
        "payload_target_path": str(payload_target),
        "packet_path": str(packet_path),
        "provenance_path": str(provenance_target),
        "asset_metadata_path": str(metadata_path),
        "copied_file_count": len(copied_files),
        "copied_files": copied_files,
        "verify_hashes": verify_hashes,
    }


def _serialize_result(
    result: Any,
    *,
    game_scope: str,
    fallback_pack_id: str | None = None,
    fallback_lane: str | None = None,
) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        payload = dict(result.to_dict())
    elif isinstance(result, dict):
        payload = dict(result)
    else:
        payload = {"value": str(result)}

    pack_id = str(payload.get("pack_id", "")).strip() or fallback_pack_id
    raw_lane = payload.get("lane", fallback_lane)
    lane = canonical_lane_value(raw_lane) if raw_lane else ""
    if pack_id:
        payload["pack_id"] = pack_id
        payload["expected_publish_path"] = str(_expected_publish_dir(game_scope, pack_id))
        payload.setdefault("payload_target_path", str(_expected_publish_dir(game_scope, pack_id) / "payload"))
        if lane:
            payload["destination_path"] = str(resolve_lane_destination(lane, pack_id=pack_id, game_scope=game_scope))
    if lane:
        payload["lane"] = lane
    if "output_dir" in payload and "source_dir" not in payload:
        payload["source_dir"] = payload["output_dir"]
    return payload


def _matches_pack(
    pack_id: str,
    requested_pack_ids: set[str],
    preset_tags: Iterable[str],
    requested_tags: Sequence[str],
) -> bool:
    if requested_pack_ids and pack_id not in requested_pack_ids:
        return False
    if requested_tags:
        normalized_tags = {str(item).strip().lower() for item in preset_tags}
        if not any(tag.lower() in normalized_tags for tag in requested_tags):
            return False
    return True


def _pack_output_dir(output_root: Path | None, pack_id: str) -> str | None:
    if output_root is None:
        return None
    return str((output_root / pack_id).resolve())


def _expected_publish_dir(game_scope: str, pack_id: str) -> Path:
    return asset_library_root() / "publish" / "flax_intake" / game_scope / pack_id


def _profile_lane(profile: str) -> str:
    if profile in DIRECT_URL_PROFILES:
        return canonical_lane_value("direct_url")
    if profile in MANUAL_BROWSER_PROFILES:
        return canonical_lane_value("manual_browser")
    if profile in GENERATOR_PROFILES:
        return canonical_lane_value("generator")
    raise ValueError(f"Unsupported bulk profile '{profile}'.")


def _job_state_path(job_id: str) -> Path:
    return state_root() / "jobs" / f"{job_id}.json"


def _write_job_state(job_id: str, payload: dict[str, Any]) -> None:
    path = _job_state_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read_job_state(job_id: str) -> dict[str, Any]:
    path = _job_state_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"AssetBoy job status not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _tail(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
