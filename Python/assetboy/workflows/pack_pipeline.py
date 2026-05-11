from __future__ import annotations

import json
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assetboy.library.asset_metadata import (
    build_asset_metadata,
    load_generator_registry,
    write_asset_metadata,
)
from assetboy.library.packet_writer import SUPPORTED_EXTENSIONS
from assetboy.library.paths import asset_library_root, state_root
from assetboy.provenance.schema import canonicalize_provenance_payload, validate_provenance_payload
from assetboy.providers.lanes import canonical_lane_value, canonical_source_adapter_id, require_source_adapter
from assetboy.workflows.flax_wrapper import (
    SUPPORTED_BULK_PROFILES,
    execute_register_packet,
    execute_run_bulk,
    execute_run_cleanup,
)


PACK_PIPELINE_SCHEMA_VERSION = "2026-03-23.pack_pipeline.v1"
PIPELINE_COMMAND_NAME = "prepare-pack"
PIPELINE_STATE_DIRNAME = "pack_pipeline"
PREPARED_SOURCE_DIRNAME = "prepared_sources"
MESH_SOURCE_EXTENSIONS = {
    ".blend",
    ".dae",
    ".fbx",
    ".glb",
    ".gltf",
    ".obj",
    ".psa",
    ".psk",
}


def execute_prepare_pack(
    *,
    pack_id: str,
    game_scope: str,
    source_dir: str | Path | None = None,
    bulk_profile: str | None = None,
    cleanup_mode: str = "auto",
    asset_kind: str = "prop",
    animated: bool = False,
    bulk_output_dir: str | Path | None = None,
    cleanup_output_dir: str | Path | None = None,
    packet_status: str = "ai_reviewed",
    overwrite_packet: bool = False,
    verify_hashes: bool = True,
    dry_run: bool = False,
    resume: bool = False,
) -> dict[str, Any]:
    normalized_pack_id = str(pack_id or "").strip()
    normalized_scope = str(game_scope or "").strip()
    if not normalized_pack_id:
        raise ValueError("pack_id is required.")
    if not normalized_scope:
        raise ValueError("game_scope is required.")

    normalized_cleanup_mode = str(cleanup_mode or "").strip().lower() or "auto"
    if normalized_cleanup_mode not in {"auto", "skip", "force"}:
        raise ValueError("cleanup_mode must be one of: auto, skip, force.")

    if source_dir and bulk_profile:
        raise ValueError("prepare-pack accepts either source_dir or bulk_profile, not both.")

    normalized_profile = str(bulk_profile or "").strip().lower()
    if normalized_profile and normalized_profile not in SUPPORTED_BULK_PROFILES:
        allowed = ", ".join(sorted(SUPPORTED_BULK_PROFILES))
        raise ValueError(f"Unsupported bulk_profile '{bulk_profile}'. Allowed: {allowed}.")

    ledger = _load_pipeline_state(normalized_pack_id, normalized_scope)
    if not ledger:
        ledger = _new_pipeline_state(normalized_pack_id, normalized_scope)

    ledger["schema_version"] = PACK_PIPELINE_SCHEMA_VERSION
    ledger["updated_at_utc"] = _utc_now()
    ledger["command"] = PIPELINE_COMMAND_NAME
    ledger["requested"] = {
        "bulk_profile": normalized_profile or None,
        "cleanup_mode": normalized_cleanup_mode,
        "asset_kind": asset_kind,
        "animated": animated,
        "bulk_output_dir": str(Path(bulk_output_dir).resolve()) if bulk_output_dir else None,
        "cleanup_output_dir": str(Path(cleanup_output_dir).resolve()) if cleanup_output_dir else None,
        "packet_status": packet_status,
        "overwrite_packet": overwrite_packet,
        "verify_hashes": verify_hashes,
        "dry_run": dry_run,
        "resume": resume,
    }

    stages = ledger.setdefault("stages", {})
    publish_dir = _expected_publish_dir(normalized_scope, normalized_pack_id)
    packet_path = publish_dir / "packet.json"
    reviewed_source_dir = _existing_dir(ledger.get("reviewed_source_dir"))
    if reviewed_source_dir is None:
        reviewed_source_dir = _existing_dir(_default_reviewed_source_dir(normalized_scope, normalized_pack_id))
    source_path = _resolve_source_dir(source_dir)

    if resume and not overwrite_packet and packet_path.exists():
        _mark_packeted_success(
            ledger,
            publish_dir=publish_dir,
            packet_path=packet_path,
            reviewed_source_dir=reviewed_source_dir,
        )
        return _finalize_success(ledger)

    if source_path is None and not normalized_profile and not resume and reviewed_source_dir is None:
        raise ValueError("prepare-pack requires source_dir, bulk_profile, or resume=True.")

    if normalized_profile:
        bulk_result = execute_run_bulk(
            profile=normalized_profile,
            game_scope=normalized_scope,
            pack_ids=[normalized_pack_id],
            output_dir=bulk_output_dir,
            dry_run=dry_run,
        )
        stages["bulk"] = bulk_result
        ledger["source_lane"] = bulk_result.get("lane", "unknown")
        if bulk_result.get("status") != "completed":
            return _finalize_failed(
                ledger,
                reason=str(bulk_result.get("error", "bulk execution failed")),
                current_state="failed",
                next_step="inspect_bulk_failure",
            )

        artifact = _select_bulk_artifact(bulk_result, normalized_pack_id)
        source_path = _resolve_source_dir(artifact.get("source_dir") or artifact.get("output_dir"))
        ledger["source_dir"] = str(source_path) if source_path else None

        if dry_run:
            ledger["status"] = "completed"
            ledger["current_state"] = "planned_source"
            ledger["next_step"] = "run prepare-pack without --dry-run after the source files exist"
            return _finalize_success(ledger)

    if source_path is None:
        source_path = _existing_dir(ledger.get("source_dir"))
    if source_path is None and reviewed_source_dir is not None:
        source_path = reviewed_source_dir
    if source_path is None:
        return _finalize_failed(
            ledger,
            reason="No source_dir could be resolved for this pack. Start with source_dir or bulk_profile, or resume an existing pack ledger.",
            current_state="failed",
            next_step="provide_source_dir_or_bulk_profile",
        )
    if not source_path.is_dir():
        return _finalize_failed(
            ledger,
            reason=f"Source directory not found: {source_path}",
            current_state="failed",
            next_step="fix_source_dir",
        )

    ledger["source_dir"] = str(source_path)
    source_summary = _summarize_source_dir(source_path)
    stages["source"] = source_summary
    ledger["source_lane"] = str(source_summary.get("lane") or ledger.get("source_lane") or "unknown")

    if not source_summary["provenance_exists"]:
        return _finalize_failed(
            ledger,
            reason=f"provenance.json not found under source_dir: {source_path}",
            current_state="failed",
            next_step="add_provenance_json",
        )

    should_run_cleanup = _should_run_cleanup(
        cleanup_mode=normalized_cleanup_mode,
        mesh_file_count=int(source_summary["mesh_file_count"]),
    )

    cleanup_result = stages.get("cleanup")
    cleanup_artifact_paths = _artifact_paths_from_stage(cleanup_result)
    if should_run_cleanup and not _all_paths_exist(cleanup_artifact_paths):
        if cleanup_result is None:
            cleanup_result = execute_run_cleanup(
                pack_id=normalized_pack_id,
                input_dir=source_path,
                game_scope=normalized_scope,
                asset_kind=asset_kind,
                animated=animated,
                output_dir=cleanup_output_dir or _default_cleanup_output_dir(normalized_scope, normalized_pack_id),
                dry_run=dry_run,
            )
            stages["cleanup"] = cleanup_result
            cleanup_artifact_paths = _artifact_paths_from_stage(cleanup_result)

        if cleanup_result.get("status") != "completed":
            return _finalize_failed(
                ledger,
                reason=str(cleanup_result.get("error", "cleanup execution failed")),
                current_state="failed",
                next_step="inspect_cleanup_failure",
            )

        ledger["cleanup_output_dir"] = cleanup_result.get("output_dir")
        if dry_run or not _all_paths_exist(cleanup_artifact_paths):
            ledger["status"] = "completed"
            ledger["current_state"] = "awaiting_cleanup_artifacts"
            ledger["next_step"] = "finish Blender cleanup exports, then rerun prepare-pack with --resume"
            return _finalize_success(ledger)

    should_refresh_reviewed_source = (
        reviewed_source_dir is None
        or not reviewed_source_dir.is_dir()
        or not resume
    )
    if should_refresh_reviewed_source:
        reviewed_source_dir = _default_reviewed_source_dir(normalized_scope, normalized_pack_id)
        try:
            if should_run_cleanup and _all_paths_exist(cleanup_artifact_paths):
                reviewed_summary = _stage_reviewed_source(
                    pack_id=normalized_pack_id,
                    game_scope=normalized_scope,
                    source_dir=source_path,
                    target_dir=reviewed_source_dir,
                    payload_paths=cleanup_artifact_paths,
                    cleanup_result=cleanup_result if isinstance(cleanup_result, dict) else None,
                    asset_kind=asset_kind,
                    animated=animated,
                )
            else:
                reviewed_summary = _stage_reviewed_source(
                    pack_id=normalized_pack_id,
                    game_scope=normalized_scope,
                    source_dir=source_path,
                    target_dir=reviewed_source_dir,
                    payload_paths=None,
                    cleanup_result=None,
                    asset_kind=asset_kind,
                    animated=animated,
                )
        except Exception as exc:  # noqa: BLE001
            return _finalize_failed(
                ledger,
                reason=str(exc),
                current_state="failed",
                next_step="inspect_reviewed_source_failure",
            )
        stages["reviewed_source"] = reviewed_summary
        ledger["reviewed_source_dir"] = reviewed_summary["reviewed_source_dir"]

    if dry_run:
        ledger["status"] = "completed"
        ledger["current_state"] = "reviewed_source"
        ledger["next_step"] = "register_packet"
        return _finalize_success(ledger)

    register_result = execute_register_packet(
        pack_id=normalized_pack_id,
        game_scope=normalized_scope,
        source_dir=reviewed_source_dir,
        overwrite=overwrite_packet,
        packet_status=packet_status,
        verify_hashes=verify_hashes,
    )
    stages["register_packet"] = register_result
    if register_result.get("status") != "completed":
        return _finalize_failed(
            ledger,
            reason=str(register_result.get("error", "register-packet failed")),
            current_state="failed",
            next_step="inspect_register_packet_failure",
        )

    ledger["publish_dir"] = register_result.get("publish_dir")
    ledger["packet_path"] = register_result.get("packet_path")
    ledger["provenance_path"] = register_result.get("provenance_path")
    ledger["status"] = "completed"
    ledger["current_state"] = "packeted"
    ledger["next_step"] = "call Flax assetboy_ops/run_intake"
    ledger["ready_for_flax_intake"] = True
    return _finalize_success(ledger)


def read_pack_pipeline_status(*, pack_id: str, game_scope: str) -> dict[str, Any]:
    normalized_pack_id = str(pack_id or "").strip()
    normalized_scope = str(game_scope or "").strip()
    if not normalized_pack_id:
        raise ValueError("pack_id is required.")
    if not normalized_scope:
        raise ValueError("game_scope is required.")

    ledger = _load_pipeline_state(normalized_pack_id, normalized_scope)
    if not ledger:
        ledger = _new_pipeline_state(normalized_pack_id, normalized_scope)

    publish_dir = _expected_publish_dir(normalized_scope, normalized_pack_id)
    packet_path = publish_dir / "packet.json"
    reviewed_source_dir = _default_reviewed_source_dir(normalized_scope, normalized_pack_id)
    packet_exists = packet_path.exists()
    reviewed_exists = reviewed_source_dir.exists()

    persisted_packeted = (
        str(ledger.get("status", "")).strip() == "completed"
        and str(ledger.get("current_state", "")).strip() == "packeted"
        and bool(ledger.get("ready_for_flax_intake"))
        and not str(ledger.get("error", "")).strip()
    )
    if packet_exists:
        _mark_packeted_success(
            ledger,
            publish_dir=publish_dir,
            packet_path=packet_path,
            reviewed_source_dir=reviewed_source_dir if reviewed_exists else None,
        )
        if not persisted_packeted:
            _finalize_success(ledger)
    else:
        ledger["publish_dir"] = str(publish_dir)
        ledger["packet_path"] = ledger.get("packet_path")
        ledger["reviewed_source_dir"] = str(reviewed_source_dir) if reviewed_exists else ledger.get("reviewed_source_dir")
        ledger["ready_for_flax_intake"] = False
        ledger["current_state"] = _infer_current_state(ledger, packet_exists=False, reviewed_exists=reviewed_exists)
        ledger["next_step"] = _infer_next_step(ledger["current_state"])

    ledger["exists"] = bool(ledger.get("updated_at_utc")) or packet_exists or reviewed_exists
    ledger["ledger_path"] = str(_pipeline_state_path(normalized_scope, normalized_pack_id))
    ledger["schema_version"] = ledger.get("schema_version", PACK_PIPELINE_SCHEMA_VERSION)
    return ledger


def _new_pipeline_state(pack_id: str, game_scope: str) -> dict[str, Any]:
    return {
        "command": PIPELINE_COMMAND_NAME,
        "schema_version": PACK_PIPELINE_SCHEMA_VERSION,
        "pack_id": pack_id,
        "game_scope": game_scope,
        "status": "pending",
        "current_state": "uninitialized",
        "next_step": "provide_source_dir_or_bulk_profile",
        "ready_for_flax_intake": False,
        "stages": {},
    }


def _resolve_source_dir(source_dir: str | Path | None) -> Path | None:
    if source_dir is None:
        return None
    return Path(source_dir).resolve()


def _load_pipeline_state(pack_id: str, game_scope: str) -> dict[str, Any] | None:
    path = _pipeline_state_path(game_scope, pack_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_pipeline_state(payload: dict[str, Any]) -> None:
    game_scope = str(payload["game_scope"])
    pack_id = str(payload["pack_id"])
    path = _pipeline_state_path(game_scope, pack_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _pipeline_state_path(game_scope: str, pack_id: str) -> Path:
    return state_root() / PIPELINE_STATE_DIRNAME / game_scope / f"{pack_id}.json"


def _default_reviewed_source_dir(game_scope: str, pack_id: str) -> Path:
    return state_root() / PREPARED_SOURCE_DIRNAME / game_scope / pack_id


def _default_cleanup_output_dir(game_scope: str, pack_id: str) -> Path:
    return state_root() / PIPELINE_STATE_DIRNAME / game_scope / pack_id / "cleanup_output"


def _expected_publish_dir(game_scope: str, pack_id: str) -> Path:
    return asset_library_root() / "publish" / "flax_intake" / game_scope / pack_id


def _select_bulk_artifact(bulk_result: dict[str, Any], pack_id: str) -> dict[str, Any]:
    artifacts = bulk_result.get("artifacts") or []
    for artifact in artifacts:
        if str(artifact.get("pack_id", "")).strip() == pack_id:
            return dict(artifact)
    raise ValueError(f"Bulk result did not include a matching artifact for pack_id '{pack_id}'.")


def _summarize_source_dir(source_dir: Path) -> dict[str, Any]:
    payload_dir = source_dir / "payload"
    if not payload_dir.is_dir():
        payload_dir = source_dir

    supported_files = [
        path
        for path in sorted(payload_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    mesh_files = [
        path
        for path in supported_files
        if path.suffix.lower() in MESH_SOURCE_EXTENSIONS
    ]

    provenance_path = source_dir / "provenance.json"
    lane = "unknown"
    if provenance_path.exists():
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8-sig"))
            lane = str(provenance.get("lane", "unknown")).strip() or "unknown"
        except json.JSONDecodeError:
            lane = "invalid_json"

    return {
        "source_dir": str(source_dir),
        "payload_dir": str(payload_dir),
        "provenance_path": str(provenance_path),
        "provenance_exists": provenance_path.exists(),
        "supported_file_count": len(supported_files),
        "mesh_file_count": len(mesh_files),
        "lane": lane,
        "supported_files": [str(path) for path in supported_files],
    }


def _should_run_cleanup(*, cleanup_mode: str, mesh_file_count: int) -> bool:
    if cleanup_mode == "force":
        return True
    if cleanup_mode == "skip":
        return False
    return mesh_file_count > 0


def _artifact_paths_from_stage(stage: dict[str, Any] | None) -> list[Path]:
    if not isinstance(stage, dict):
        return []
    result: list[Path] = []
    for item in stage.get("artifact_paths") or []:
        text = str(item).strip()
        if text:
            result.append(Path(text))
    return result


def _all_paths_exist(paths: list[Path]) -> bool:
    return bool(paths) and all(path.exists() for path in paths)


def _default_source_adapter_for_lane(lane: str) -> str:
    if lane == "manual_browser":
        return "manual_browser_drop"
    if lane == "generator":
        return "chatgpt_pro"
    return "direct_url_queue"


def _load_source_provenance(provenance_source: Path) -> dict[str, Any]:
    try:
        payload = json.loads(provenance_source.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"source provenance.json is malformed JSON at line {exc.lineno}, column {exc.colno}: {exc.msg} ({provenance_source})."
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"source provenance.json must contain a top-level JSON object: {provenance_source}")
    return payload


def _stage_reviewed_source(
    *,
    pack_id: str,
    game_scope: str,
    source_dir: Path,
    target_dir: Path,
    payload_paths: list[Path] | None,
    cleanup_result: dict[str, Any] | None,
    asset_kind: str,
    animated: bool,
) -> dict[str, Any]:
    provenance_source = source_dir / "provenance.json"
    if not provenance_source.exists():
        raise FileNotFoundError(f"provenance.json not found under source_dir: {source_dir}")

    if target_dir.exists():
        shutil.rmtree(target_dir)
    payload_dir = target_dir / "payload"
    payload_dir.mkdir(parents=True, exist_ok=True)

    if payload_paths:
        copied_payloads = _copy_cleanup_payloads(payload_paths=payload_paths, cleanup_result=cleanup_result, payload_dir=payload_dir)
    else:
        copied_payloads = _copy_source_payloads(source_dir=source_dir, payload_dir=payload_dir)
    canonicalization_report = _normalize_payload_to_canonical_gltf(payload_dir=payload_dir, pack_id=pack_id)
    copied_payloads = [
        str(path)
        for path in sorted(payload_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    provenance = _load_source_provenance(provenance_source)
    rewritten_provenance = dict(provenance)
    rewritten_provenance["pack_id"] = pack_id
    rewritten_provenance["game_scope"] = game_scope
    rewritten_provenance["prepared_at_utc"] = _utc_now()
    rewritten_provenance["prepared_source_dir"] = str(target_dir)
    rewritten_provenance["payload_target_path"] = str(payload_dir)
    rewritten_provenance["canonicalization"] = {
        "status": canonicalization_report.get("status", "unknown"),
        "canonical_mesh_count": len(canonicalization_report.get("canonical_mesh_files", [])),
        "noncanonical_mesh_count": canonicalization_report.get("noncanonical_mesh_count", 0),
    }
    if not str(rewritten_provenance.get("downloaded_filename", "")).strip() and copied_payloads:
        try:
            first_payload = Path(copied_payloads[0]).resolve()
            rewritten_provenance["downloaded_filename"] = first_payload.relative_to(payload_dir.resolve()).as_posix()
        except Exception:
            rewritten_provenance["downloaded_filename"] = Path(copied_payloads[0]).name
    if cleanup_result:
        rewritten_provenance["cleanup_profile"] = {
            "asset_kind": asset_kind,
            "animated": animated,
            "cleanup_output_dir": cleanup_result.get("output_dir"),
        }
        cleanup_output_dir = str(cleanup_result.get("output_dir", "")).strip()
        if cleanup_output_dir:
            cleanup_plan_path = Path(cleanup_output_dir) / "cleanup_plan.json"
            if cleanup_plan_path.exists():
                shutil.copy2(cleanup_plan_path, target_dir / "cleanup_plan.json")

    raw_lane = str(rewritten_provenance.get("lane", "")).strip() or "direct_url"
    try:
        lane = canonical_lane_value(raw_lane)
    except ValueError as exc:
        raise ValueError(
            f"source provenance lane '{raw_lane}' is invalid. Use one of: direct_url, manual_browser, generator."
        ) from exc

    raw_source_adapter = str(rewritten_provenance.get("source_adapter", "")).strip()
    try:
        source_adapter_input = (
            canonical_source_adapter_id(raw_source_adapter)
            if raw_source_adapter
            else _default_source_adapter_for_lane(lane)
        )
    except ValueError as exc:
        raise ValueError(
            f"source provenance source_adapter '{raw_source_adapter}' is invalid. "
            "Use a canonical adapter id (for example: direct_url_queue, museum_page, chatgpt_pro)."
        ) from exc
    try:
        adapter_contract = require_source_adapter(source_adapter_input)
    except ValueError as exc:
        source_adapter_label = raw_source_adapter or source_adapter_input
        raise ValueError(
            f"source provenance source_adapter '{source_adapter_label}' is invalid. "
            "Use a canonical adapter id (for example: direct_url_queue, museum_page, chatgpt_pro)."
        ) from exc
    if adapter_contract.lane.value != lane:
        raise ValueError(
            f"source provenance lane '{lane}' does not match source_adapter '{adapter_contract.adapter_id}' lane '{adapter_contract.lane.value}'."
        )

    rewritten_provenance["lane"] = lane
    rewritten_provenance["source_adapter"] = adapter_contract.adapter_id
    _, provenance_errors, provenance_warnings = validate_provenance_payload(
        rewritten_provenance,
        expected_lane=lane,
        expected_payload_target_path=payload_dir,
    )
    if provenance_errors:
        raise ValueError("Invalid source provenance for prepare-pack: " + "; ".join(provenance_errors))
    if provenance_warnings:
        print("[WARN] source provenance warnings: " + " | ".join(provenance_warnings))

    canonical_provenance = canonicalize_provenance_payload(rewritten_provenance, keep_extra=True)
    canonical_provenance["pack_id"] = pack_id
    canonical_provenance["game_scope"] = game_scope
    canonical_provenance["lane"] = lane
    canonical_provenance["source_adapter"] = adapter_contract.adapter_id
    canonical_provenance["payload_target_path"] = str(payload_dir)
    if not str(canonical_provenance.get("downloaded_filename", "")).strip() and copied_payloads:
        canonical_provenance["downloaded_filename"] = Path(copied_payloads[0]).name

    provenance_target = target_dir / "provenance.json"
    provenance_target.write_text(json.dumps(canonical_provenance, indent=2), encoding="utf-8")
    payload_manifest = [
        {
            "published_relative_path": str((Path("payload") / path.relative_to(payload_dir)).as_posix()),
            "relative_pack_path": path.relative_to(payload_dir).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": "",
        }
        for path in sorted(payload_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    metadata_payload = build_asset_metadata(
        pack_id=pack_id,
        game_scope=game_scope,
        payload_files=payload_manifest,
        provenance=canonical_provenance,
        conversion_report=canonicalization_report,
        generator_registry=load_generator_registry(),
        source_folder=str(source_dir),
    )
    metadata_path = write_asset_metadata(target_dir, metadata_payload)

    return {
        "reviewed_source_dir": str(target_dir),
        "payload_dir": str(payload_dir),
        "provenance_path": str(provenance_target),
        "asset_metadata_path": str(metadata_path),
        "canonicalization": canonicalization_report,
        "copied_file_count": len(copied_payloads),
        "copied_files": copied_payloads,
        "used_cleanup_output": bool(cleanup_result),
    }


def _copy_source_payloads(*, source_dir: Path, payload_dir: Path) -> list[str]:
    payload_source = source_dir / "payload"
    if not payload_source.is_dir():
        payload_source = source_dir

    copied: list[str] = []
    for source_file in sorted(payload_source.rglob("*")):
        if not source_file.is_file() or source_file.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        relative_path = source_file.relative_to(payload_source)
        destination_path = payload_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_path)
        copied.append(str(destination_path))
    if not copied:
        raise ValueError(
            f"No supported payload files found in {payload_source}. Supported extensions: {sorted(SUPPORTED_EXTENSIONS)}"
        )
    return copied


def _copy_cleanup_payloads(*, payload_paths: list[Path], cleanup_result: dict[str, Any] | None, payload_dir: Path) -> list[str]:
    cleanup_root = None
    if cleanup_result and cleanup_result.get("output_dir"):
        cleanup_root = Path(str(cleanup_result["output_dir"]))

    copied: list[str] = []
    for source_file in payload_paths:
        if not source_file.exists():
            continue
        if cleanup_root is not None:
            try:
                relative_path = source_file.relative_to(cleanup_root)
            except ValueError:
                relative_path = Path(source_file.name)
        else:
            relative_path = Path(source_file.name)
        destination_path = payload_dir / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_path)
        copied.append(str(destination_path))

    if not copied:
        raise FileNotFoundError("Cleanup completed but no exported payload files were found at the expected artifact paths.")
    return copied


def _normalize_payload_to_canonical_gltf(*, payload_dir: Path, pack_id: str) -> dict[str, Any]:
    mesh_files = [
        path for path in sorted(payload_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in MESH_SOURCE_EXTENSIONS
    ]
    report: dict[str, Any] = {
        "schema_version": "assetboy.canonicalization.v1",
        "requested": True,
        "status": "completed",
        "pack_id": pack_id,
        "mesh_file_count": len(mesh_files),
        "canonical_mesh_files": [],
        "noncanonical_mesh_count": 0,
        "tools": {
            "fbx2gltf": _resolve_tool_binary(("FBX2glTF", "fbx2gltf")),
            "assimp": _resolve_tool_binary(("assimp",)),
        },
        "entries": [],
    }
    if not mesh_files:
        report["status"] = "skipped_no_mesh_files"
        return report

    degraded = False
    for source_path in mesh_files:
        ext = source_path.suffix.lower()
        entry: dict[str, Any] = {
            "source_path": str(source_path),
            "source_extension": ext,
            "status": "skipped",
            "converter": "",
            "canonical_path": "",
            "message": "",
        }

        if ext in {".glb", ".gltf"}:
            entry["status"] = "already_canonical"
            entry["canonical_path"] = str(source_path)
            report["canonical_mesh_files"].append(str(source_path))
            report["entries"].append(entry)
            continue

        converter_result = _convert_mesh_to_canonical(
            source_path=source_path,
            fbx2gltf_binary=str(report["tools"]["fbx2gltf"] or "").strip(),
            assimp_binary=str(report["tools"]["assimp"] or "").strip(),
        )
        entry.update(converter_result)
        canonical_path = str(entry.get("canonical_path", "")).strip()
        if canonical_path:
            report["canonical_mesh_files"].append(canonical_path)
        status = str(entry.get("status", "")).strip()
        if status not in {"converted", "already_canonical"}:
            degraded = True
        report["entries"].append(entry)

    noncanonical_count = 0
    for path in sorted(payload_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in MESH_SOURCE_EXTENSIONS and path.suffix.lower() not in {".glb", ".gltf"}:
            noncanonical_count += 1
    report["noncanonical_mesh_count"] = noncanonical_count
    if noncanonical_count > 0:
        degraded = True
    report["status"] = "degraded" if degraded else "completed"
    return report


def _convert_mesh_to_canonical(*, source_path: Path, fbx2gltf_binary: str, assimp_binary: str) -> dict[str, Any]:
    ext = source_path.suffix.lower()
    if ext == ".fbx":
        if not fbx2gltf_binary:
            return {
                "status": "skipped_missing_converter",
                "converter": "fbx2gltf",
                "message": "FBX2glTF not found in PATH.",
                "canonical_path": "",
            }
        output_path = source_path.with_suffix(".glb")
        result = _run_fbx2gltf(source_path=source_path, output_path=output_path, binary=fbx2gltf_binary)
        if result["status"] == "converted":
            source_path.unlink(missing_ok=True)
        return result

    if not assimp_binary:
        return {
            "status": "skipped_missing_converter",
            "converter": "assimp",
            "message": "assimp not found in PATH.",
            "canonical_path": "",
        }
    output_path = source_path.with_suffix(".gltf")
    result = _run_assimp_export(source_path=source_path, output_path=output_path, binary=assimp_binary)
    if result["status"] == "converted":
        source_path.unlink(missing_ok=True)
    return result


def _run_fbx2gltf(*, source_path: Path, output_path: Path, binary: str) -> dict[str, Any]:
    commands = [
        [binary, "--input", str(source_path), "--output", str(output_path), "--binary", "--user-properties"],
        [binary, "-i", str(source_path), "-o", str(output_path), "--binary", "--user-properties"],
    ]
    for command in commands:
        run_result = _run_external_command(command)
        if run_result["ok"] and output_path.exists():
            return {
                "status": "converted",
                "converter": "fbx2gltf",
                "canonical_path": str(output_path),
                "message": "FBX converted to canonical GLB.",
                "command": run_result["command"],
            }
    return {
        "status": "failed",
        "converter": "fbx2gltf",
        "canonical_path": "",
        "message": "FBX2glTF conversion failed.",
    }


def _run_assimp_export(*, source_path: Path, output_path: Path, binary: str) -> dict[str, Any]:
    commands = [
        [binary, "export", str(source_path), str(output_path)],
        [binary, "export", str(source_path), str(output_path), "-f", "gltf2"],
    ]
    for command in commands:
        run_result = _run_external_command(command)
        if run_result["ok"] and output_path.exists():
            return {
                "status": "converted",
                "converter": "assimp",
                "canonical_path": str(output_path),
                "message": "Mesh converted to canonical glTF via assimp.",
                "command": run_result["command"],
            }
    return {
        "status": "failed",
        "converter": "assimp",
        "canonical_path": "",
        "message": "assimp export to glTF failed.",
    }


def _run_external_command(command: list[str], *, timeout_sec: int = 240) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except FileNotFoundError:
        return {"ok": False, "command": " ".join(command), "message": "binary_not_found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": " ".join(command), "message": "timeout"}
    return {
        "ok": completed.returncode == 0,
        "command": " ".join(command),
        "returncode": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-500:],
        "stderr_tail": (completed.stderr or "")[-500:],
    }


def _resolve_tool_binary(candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return ""


def _existing_dir(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.exists() else None


def _finalize_failed(ledger: dict[str, Any], *, reason: str, current_state: str, next_step: str) -> dict[str, Any]:
    ledger["status"] = "failed"
    ledger["current_state"] = current_state
    ledger["next_step"] = next_step
    ledger["error"] = reason
    ledger["ready_for_flax_intake"] = False
    return _finalize_success(ledger)


def _finalize_success(ledger: dict[str, Any]) -> dict[str, Any]:
    if ledger.get("status") == "completed" and ledger.get("current_state") != "failed":
        ledger.pop("error", None)
    ledger["updated_at_utc"] = _utc_now()
    ledger["ledger_path"] = str(_pipeline_state_path(str(ledger["game_scope"]), str(ledger["pack_id"])))
    _write_pipeline_state(ledger)
    return ledger


def _mark_packeted_success(
    ledger: dict[str, Any],
    *,
    publish_dir: Path,
    packet_path: Path,
    reviewed_source_dir: Path | None,
) -> None:
    ledger["status"] = "completed"
    ledger["current_state"] = "packeted"
    ledger["next_step"] = "call Flax assetboy_ops/run_intake"
    ledger["ready_for_flax_intake"] = True
    ledger["publish_dir"] = str(publish_dir)
    ledger["packet_path"] = str(packet_path)
    provenance_path = publish_dir / "provenance.json"
    if provenance_path.exists():
        ledger["provenance_path"] = str(provenance_path)
    if reviewed_source_dir is not None and reviewed_source_dir.exists():
        ledger["reviewed_source_dir"] = str(reviewed_source_dir)
    ledger.pop("error", None)


def _infer_current_state(ledger: dict[str, Any], *, packet_exists: bool, reviewed_exists: bool) -> str:
    explicit = str(ledger.get("current_state", "")).strip()
    if packet_exists:
        return "packeted"
    if reviewed_exists:
        return "reviewed_source"
    if explicit:
        return explicit
    return "uninitialized"


def _infer_next_step(current_state: str) -> str:
    mapping = {
        "uninitialized": "provide_source_dir_or_bulk_profile",
        "planned_source": "run prepare-pack without --dry-run after the source files exist",
        "awaiting_cleanup_artifacts": "finish Blender cleanup exports, then rerun prepare-pack with --resume",
        "reviewed_source": "register_packet",
        "packeted": "call Flax assetboy_ops/run_intake",
        "failed": "inspect the stored error and fix the broken stage",
    }
    return mapping.get(current_state, "inspect the pack ledger")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ===========================================================================
# Path B s7 (2026-05-10) — additive Stage-dispatch shim.
# ===========================================================================
#
# The legacy `execute_prepare_pack` above (lines 43-286-ish) is a 918-line
# monolithic state machine with 10 tests in test_pack_pipeline.py locking in
# subtle behaviors:
#
#   * canonical-glTF degradation is non-fatal (FBX2glTF missing -> "degraded",
#     pack still publishes)
#   * dry_run terminates in 3 different green-pause states depending on phase
#   * `_mark_packeted_success` -> `_finalize_success` two-phase heal must not
#     touch ledger mtime when packet already on disk
#   * `error` field is popped only when terminal status="completed"
#   * resume + reviewed_source_dir on disk -> skip _stage_reviewed_source
#   * resume + cleanup artifacts on disk -> skip execute_run_cleanup re-call
#
# A 1:1 mechanical extraction risks regressing one of these. Instead we ship
# the **public-facing Stage enum + dispatch contract** that future callers
# (s8 recipe runner, future s10 mechanical extraction) need, without touching
# the legacy body. Callers that want a clean dispatch shape import:
#
#     from assetboy.workflows.pack_pipeline import (
#         Stage,            # 5-value enum (BULK_SOURCE..REGISTER_PACKET)
#         STAGE_ORDER,      # canonical execution order
#         StageResult,      # ok/payload/error/pause dataclass
#         PipelineContext,  # frozen args bundle
#         execute_prepare_pack_dispatched,  # alternate entry point
#         PACK_PIPELINE_SCHEMA_VERSION_V2,  # for code that wants to gate on v2
#     )
#
# The mechanical extraction of the legacy body into the 5 stage handlers is
# tracked as Path B s10.5 (post-cleanup). Until then `execute_prepare_pack`
# remains the only certified-correct path.

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


PACK_PIPELINE_SCHEMA_VERSION_V2 = "2026-05-10.pack_pipeline.v2"


class Stage(str, Enum):
    """Canonical stages of the pack pipeline.

    Five entries; canonical-glTF is intentionally NOT its own stage (it lives
    inside REVIEWED_SOURCE as an inline sub-step). Splitting it out would open
    a window where reviewed_source_dir is half-built across a crash; the
    current code does the rebuild + canonical pass + asset_metadata write as
    one atomic rmtree-then-repopulate.
    """

    BULK_SOURCE = "bulk_source"        # optional; only with bulk_profile arg
    SOURCE_SUMMARY = "source_summary"  # always; enumerate + validate source_dir
    CLEANUP = "cleanup"                # gated by cleanup_mode + mesh count
    REVIEWED_SOURCE = "reviewed_source"  # copy + canonical-glTF + provenance
    REGISTER_PACKET = "register_packet"  # publish to flax_intake


STAGE_ORDER: tuple[Stage, ...] = (
    Stage.BULK_SOURCE,
    Stage.SOURCE_SUMMARY,
    Stage.CLEANUP,
    Stage.REVIEWED_SOURCE,
    Stage.REGISTER_PACKET,
)


@dataclass
class StageResult:
    """Outcome of a single stage invocation.

    Three terminal flavors:
      * ok=True, pause_state=None        -> stage completed; advance
      * ok=True, pause_state=<name>      -> stage green-paused (e.g. awaiting
                                            cleanup artifacts); ledger
                                            persists; do NOT mark stage as
                                            stages_completed; resume later
      * ok=True, skipped=True            -> stage not applicable (e.g.
                                            BULK_SOURCE without bulk_profile)
      * ok=False, error=<str>            -> stage failed; ledger writes
                                            status="failed"; halt
    """

    ok: bool
    payload: dict[str, Any] | None = None
    error: str | None = None
    pause_state: str | None = None
    pause_next_step: str | None = None
    skipped: bool = False
    # Optional warning channel (e.g. canonical-glTF degraded but still green).
    warnings: list[str] = field(default_factory=list)


@dataclass
class PipelineContext:
    """Frozen-after-construction args bundle for a single pack execution.

    Mirrors the kwargs of legacy `execute_prepare_pack` 1:1. New stage
    functions take this + a `PipelineState` (TBD; see s10.5).
    """

    pack_id: str
    game_scope: str
    source_dir: Path | None = None
    bulk_profile: str | None = None
    cleanup_mode: str = "auto"
    asset_kind: str = "prop"
    animated: bool = False
    bulk_output_dir: Path | None = None
    cleanup_output_dir: Path | None = None
    packet_status: str = "ai_reviewed"
    overwrite_packet: bool = False
    verify_hashes: bool = True
    dry_run: bool = False
    resume: bool = False


def execute_prepare_pack_dispatched(ctx: PipelineContext) -> dict[str, Any]:
    """New-shape entry point. Currently delegates to legacy `execute_prepare_pack`.

    Once s10.5 lands the mechanical extraction, this becomes the dispatch
    loop:

        state = _load_or_init_state(ctx.pack_id, ctx.game_scope)
        for stage in STAGE_ORDER:
            if stage.value in state.stages_completed and not _must_rerun(stage, state, ctx):
                continue
            result = STAGE_HANDLERS[stage](state, ctx)
            _persist(state)
            if not result.ok: return _finalize_failed(state, result)
            if result.pause_state: return _finalize_pause(state, result)
        return _finalize_packeted(state)

    For now: thin shim. Same args, same return shape, same ledger location.
    s8 recipe runner can call this and get forward-compatible behavior.
    """
    return execute_prepare_pack(
        pack_id=ctx.pack_id,
        game_scope=ctx.game_scope,
        source_dir=ctx.source_dir,
        bulk_profile=ctx.bulk_profile,
        cleanup_mode=ctx.cleanup_mode,
        asset_kind=ctx.asset_kind,
        animated=ctx.animated,
        bulk_output_dir=ctx.bulk_output_dir,
        cleanup_output_dir=ctx.cleanup_output_dir,
        packet_status=ctx.packet_status,
        overwrite_packet=ctx.overwrite_packet,
        verify_hashes=ctx.verify_hashes,
        dry_run=ctx.dry_run,
        resume=ctx.resume,
    )


# Stage handler registry. Empty in s7 — populated in s10.5 mechanical
# extraction. Exposed here so new callers can `from ... import STAGE_HANDLERS`
# and have a stable name to mock/patch in tests.
STAGE_HANDLERS: dict[Stage, Callable[..., StageResult]] = {}


def stage_for_current_state(current_state: str) -> Stage | None:
    """Best-effort map of legacy `current_state` -> nearest Stage.

    Helps tools that want to display "we're at stage X" without rebuilding
    the legacy state-inference. Returns None for terminal/uninitialized.
    """
    return {
        "uninitialized": None,
        "planned_source": Stage.BULK_SOURCE,
        "awaiting_cleanup_artifacts": Stage.CLEANUP,
        "reviewed_source": Stage.REVIEWED_SOURCE,
        "packeted": Stage.REGISTER_PACKET,
        "failed": None,
    }.get(current_state)


__all_dispatch_api__ = [
    "Stage",
    "STAGE_ORDER",
    "StageResult",
    "PipelineContext",
    "execute_prepare_pack_dispatched",
    "PACK_PIPELINE_SCHEMA_VERSION_V2",
    "STAGE_HANDLERS",
    "stage_for_current_state",
]
