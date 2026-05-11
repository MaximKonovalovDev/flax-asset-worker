from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from assetboy.library.paths import colab_profiles_dir
from assetboy.providers.epic_vault import (
    build_local_epic_extraction_readiness,
    default_epic_launcher_saved_data_dir,
    default_local_fab_library_db_path,
)
from assetboy.providers.fab_hybrid import FabHybridDownloader
from assetboy.providers.lanes import LANE_POLICIES, ProviderLane, adapters_for_lane
from assetboy.providers.legendary_bridge import build_legendary_status_report
from assetboy.providers.mixamo_auth import MixamoAuthSession
from assetboy.providers.unity_auth import UnityAuthSession
from assetboy.providers.unity_runner import list_unity_installations
from assetboy.providers.unreal_runner import list_unreal_installations


# ---------------------------------------------------------------------------
# Path B s2.6a (2026-05-11): inline AI_PROVIDER_PROFILES + profile_ids() +
# provider_runbook_ids() loading. Reads parked YAML data (s2 extraction) so
# we can delete ai_bridge.py + generator.py + runbooks.py in s2.6d.
# ---------------------------------------------------------------------------

def _load_parked_provider_profiles() -> dict[str, object]:
    """Read assetboy/data/provider_profiles.yaml once (cached).

    Returns the inner `data` dict. Falls back to an empty dict if PyYAML
    or the file isn't available so this module never blocks import.
    """
    try:
        import yaml
    except ImportError:
        return {}
    yaml_path = Path(__file__).resolve().parent.parent / "data" / "provider_profiles.yaml"
    if not yaml_path.exists():
        return {}
    try:
        doc = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict((doc or {}).get("data") or {})


# Cached module-level data — read once, cheap re-reads.
_PARKED = _load_parked_provider_profiles()
_AI_PROVIDER_IDS: tuple[str, ...] = tuple(sorted((_PARKED.get("AI_PROVIDER_PROFILES") or {}).keys()))
_RUNBOOK_IDS: tuple[str, ...] = tuple(sorted((_PARKED.get("STATIC_PROVIDER_RUNBOOKS") or {}).keys()))


def _iter_colab_profile_ids() -> tuple[str, ...]:
    """Inline replacement for the deleted ``generator.profile_ids()``.

    Lists ``*.json`` files under colab_profiles_dir() (skipping ``*.example``).
    """
    try:
        root = colab_profiles_dir()
    except Exception:
        return ()
    if not root.exists():
        return ()
    return tuple(
        sorted(
            path.stem
            for path in root.glob("*.json")
            if not path.stem.endswith(".example")
        )
    )


def _load_colab_profile_summary(profile_id: str) -> dict[str, object]:
    """Inline replacement for the deleted ``generator.load_colab_profile()``.

    Reads only the 6 fields ``provider_readiness`` actually consumes
    (the original returned a 17-field frozen dataclass). Tolerant of
    missing fields and broken files.
    """
    try:
        root = colab_profiles_dir()
        payload = json.loads((root / f"{profile_id}.json").read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return {
        "profile_id": str(payload.get("profile_id", profile_id)),
        "display_name": str(payload.get("display_name", profile_id)),
        "adapter_id": str(payload.get("adapter_id", "")),
        "model_name": str(payload.get("model_name", "")),
        "lane": str(payload.get("lane", "")),
        "asset_kind": str(payload.get("asset_kind", "")),
    }


_STATUS_PRIORITY: dict[str, int] = {
    "setup_required": 0,
    "partial": 1,
    "ready_now": 2,
}

_AUTH_BLOCKER_REASONS = {
    "browser_auth_required",
    "browser_auth_refresh_recommended",
    "epic_auth_import_required",
}

_TOOLING_BLOCKER_REASONS = {
    "unity_editor_missing",
    "unreal_editor_missing",
    "legendary_cli_missing",
    "epic_extraction_tooling_missing",
}

_PROVIDER_PRIORITY: dict[str, int] = {
    "direct_url_lane": 0,
    "generator_profiles": 1,
    "epic_extraction": 2,
    "unity_export_bridge": 3,
    "fab": 4,
    "mixamo": 5,
    "unity_asset_store": 6,
    "legendary": 7,
    "unreal_export_bridge": 8,
}


def _status_text(
    *,
    ready: bool,
    partial: bool = False,
) -> str:
    if ready:
        return "ready_now"
    if partial:
        return "partial"
    return "setup_required"


def _row(
    *,
    provider_id: str,
    display_name: str,
    lane: ProviderLane,
    status: str,
    next_action: str,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "provider_id": provider_id,
        "display_name": display_name,
        "lane": lane.value,
        "status": status,
        "next_action": next_action,
        "details": details or {},
        "runbook_id": provider_id,
    }


def _blocking_reasons(row: dict[str, object]) -> list[str]:
    provider_id = str(row.get("provider_id") or "")
    details = row.get("details", {})
    details = details if isinstance(details, dict) else {}
    reasons: list[str] = []

    if provider_id in {"fab", "mixamo", "unity_asset_store"} and not bool(details.get("authenticated")):
        reasons.append("browser_auth_required")
    if provider_id in {"fab", "mixamo", "unity_asset_store"} and bool(details.get("auth_state_stale")):
        reasons.append("browser_auth_refresh_recommended")

    if provider_id in {"unity_asset_store", "unity_export_bridge"}:
        if int(details.get("unity_usable_install_count", 0) or 0) <= 0:
            reasons.append("unity_editor_missing")

    if provider_id == "unreal_export_bridge":
        if int(details.get("unreal_usable_install_count", 0) or 0) <= 0:
            reasons.append("unreal_editor_missing")

    if provider_id == "epic_extraction" and not bool(details.get("can_extract_now")):
        reasons.append("epic_extraction_tooling_missing")

    if provider_id == "legendary":
        session = details.get("session", {})
        session = session if isinstance(session, dict) else {}
        if not bool(details.get("legendary_path")):
            reasons.append("legendary_cli_missing")
        if not bool(session.get("remember_me_data_present")):
            reasons.append("epic_auth_import_required")

    return reasons


def _annotate_row(row: dict[str, object]) -> dict[str, object]:
    annotated = dict(row)
    provider_id = str(annotated.get("provider_id") or "")
    reasons = _blocking_reasons(annotated)
    operator_action_required = any(reason in _AUTH_BLOCKER_REASONS for reason in reasons)
    local_tooling_required = any(reason in _TOOLING_BLOCKER_REASONS for reason in reasons)
    backed_by_local_tooling = provider_id in {
        "unity_export_bridge",
        "unreal_export_bridge",
        "epic_extraction",
        "legendary",
    }
    backed_by_saved_auth = provider_id in {
        "fab",
        "mixamo",
        "unity_asset_store",
    }

    if annotated["status"] == "ready_now":
        if local_tooling_required or backed_by_local_tooling:
            autonomy_mode = "local_tooling_ready"
        elif operator_action_required or backed_by_saved_auth:
            autonomy_mode = "auth_bootstrapped"
        else:
            autonomy_mode = "autonomous_ready"
    elif operator_action_required:
        autonomy_mode = "operator_action_required"
    elif local_tooling_required:
        autonomy_mode = "local_tooling_required"
    else:
        autonomy_mode = "setup_required"

    annotated["blocking_reasons"] = reasons
    annotated["operator_action_required"] = operator_action_required
    annotated["local_tooling_required"] = local_tooling_required
    annotated["autonomy_mode"] = autonomy_mode
    return annotated


def _provider_sort_key(row: dict[str, object]) -> tuple[int, str]:
    provider_id = str(row.get("provider_id") or "")
    display_name = str(row.get("display_name") or provider_id)
    return (_PROVIDER_PRIORITY.get(provider_id, 999), display_name)


def _sorted_provider_ids(rows: list[dict[str, object]], limit: int = 0) -> list[str]:
    provider_ids = [str(row["provider_id"]) for row in sorted(rows, key=_provider_sort_key)]
    if limit > 0:
        return provider_ids[:limit]
    return provider_ids


def _autonomy_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    ready_rows = [row for row in rows if row["status"] == "ready_now"]
    auth_blocker_rows = [row for row in rows if row.get("operator_action_required")]
    tooling_blocker_rows = [row for row in rows if row.get("local_tooling_required")]
    unblock_rows = [row for row in rows if row["status"] != "ready_now"]
    unblock_rows.sort(
        key=lambda row: (
            0 if row["status"] == "partial" else 1,
            0 if row.get("operator_action_required") else 1,
            len(row.get("blocking_reasons", [])),
            *_provider_sort_key(row),
        )
    )

    return {
        "recommended_provider_ids": _sorted_provider_ids(ready_rows, limit=5),
        "highest_leverage_unblock_provider_ids": _sorted_provider_ids(unblock_rows, limit=5),
        "autonomous_ready_provider_ids": _sorted_provider_ids(
            [row for row in ready_rows if row.get("autonomy_mode") == "autonomous_ready"]
        ),
        "auth_bootstrapped_provider_ids": _sorted_provider_ids(
            [row for row in ready_rows if row.get("autonomy_mode") == "auth_bootstrapped"]
        ),
        "local_tooling_ready_provider_ids": _sorted_provider_ids(
            [row for row in ready_rows if row.get("autonomy_mode") == "local_tooling_ready"]
        ),
        "auth_blocker_provider_ids": _sorted_provider_ids(auth_blocker_rows),
        "tooling_blocker_provider_ids": _sorted_provider_ids(tooling_blocker_rows),
    }


def _blocker_delta_rows(
    rows: list[dict[str, object]],
    *,
    reason_scope: set[str],
) -> list[dict[str, object]]:
    scoped_rows: list[dict[str, object]] = []
    for row in sorted(rows, key=_provider_sort_key):
        matching_reasons = [reason for reason in row.get("blocking_reasons", []) if reason in reason_scope]
        if not matching_reasons:
            continue
        scoped_rows.append(
            {
                "provider_id": row["provider_id"],
                "display_name": row["display_name"],
                "lane": row["lane"],
                "status": row["status"],
                "autonomy_mode": row["autonomy_mode"],
                "blocking_reasons": matching_reasons,
                "next_action": row["next_action"],
            }
        )
    return scoped_rows


def _direct_url_row() -> dict[str, object]:
    adapters = adapters_for_lane(ProviderLane.DIRECT_URL)
    return _row(
        provider_id="direct_url_lane",
        display_name="Direct URL Lane",
        lane=ProviderLane.DIRECT_URL,
        status="ready_now",
        next_action="Queue direct-download sources immediately with `run-*-batch` or the shared queue lane.",
        details={
            "adapter_count": len(adapters),
            "adapter_ids": [adapter.adapter_id for adapter in adapters],
            "destination": LANE_POLICIES[ProviderLane.DIRECT_URL].default_destination,
        },
    )


def _fab_row() -> dict[str, object]:
    status = FabHybridDownloader(debug=False).auth_status()
    authenticated = bool(status.get("authenticated"))
    stale = bool(status.get("auth_state_stale"))
    ready = authenticated and not stale
    partial = bool(status.get("auth_state_exists")) or bool(status.get("browser_profile_has_state"))
    if stale:
        next_action = "Fab saved auth looks stale. Run `python scripts/cli.py asset-factory fab-auth --reuse-profile` to refresh the shared session before automation."
    elif authenticated:
        next_action = "Fab browser auth is ready."
    elif partial:
        next_action = "Fab has some saved browser state. Try `python scripts/cli.py asset-factory fab-auth --reuse-profile` before opening a fresh login window."
    else:
        next_action = "No Fab browser state is cached yet. Run `python scripts/cli.py asset-factory fab-auth --allow-browser` and complete the visible Epic/Fab login once."
    return _row(
        provider_id="fab",
        display_name="Fab",
        lane=ProviderLane.MANUAL_BROWSER,
        status=_status_text(ready=ready, partial=partial),
        next_action=next_action,
        details=status,
    )


def _mixamo_row() -> dict[str, object]:
    status = MixamoAuthSession(debug=False).auth_status()
    authenticated = bool(status.get("authenticated"))
    stale = bool(status.get("auth_state_stale"))
    ready = authenticated and not stale
    partial = bool(status.get("auth_state_exists")) or bool(status.get("browser_profile_has_state"))
    if stale:
        next_action = "Mixamo saved auth looks stale. Run `python scripts/cli.py asset-factory mixamo-auth --reuse-profile` to refresh the shared session before automation."
    elif authenticated:
        next_action = "Mixamo browser auth is ready."
    elif partial:
        next_action = "Mixamo has partial saved browser state. Try `python scripts/cli.py asset-factory mixamo-auth --reuse-profile` before opening a fresh login window."
    else:
        next_action = "No Mixamo browser state is cached yet. Run `python scripts/cli.py asset-factory mixamo-auth --allow-browser` and complete the visible Adobe login once."
    return _row(
        provider_id="mixamo",
        display_name="Mixamo",
        lane=ProviderLane.MANUAL_BROWSER,
        status=_status_text(ready=ready, partial=partial),
        next_action=next_action,
        details=status,
    )


def _unity_store_row(unity_installations: tuple[dict[str, object], ...]) -> dict[str, object]:
    status = UnityAuthSession().auth_status()
    authenticated = bool(status.get("authenticated"))
    stale = bool(status.get("auth_state_stale"))
    install_ready = any(bool(item.get("usable")) for item in unity_installations)
    ready = authenticated and install_ready and not stale
    partial = authenticated or install_ready or bool(status.get("auth_state_exists")) or bool(status.get("browser_profile_has_state"))

    if stale and install_ready:
        next_action = "Unity export is ready, but saved store auth looks stale. Run `python scripts/cli.py asset-factory unity-auth --reuse-profile` before claim/export automation."
    elif authenticated and install_ready:
        next_action = "Unity Asset Store auth and local Unity export support are both ready."
    elif not authenticated and install_ready:
        if bool(status.get("auth_state_exists")) or bool(status.get("browser_profile_has_state")):
            next_action = "Unity export is ready, but store auth is incomplete. Try `python scripts/cli.py asset-factory unity-auth --reuse-profile` first."
        else:
            next_action = "Unity export is ready, but no Unity browser auth is cached yet. Run `python scripts/cli.py asset-factory unity-auth --allow-browser` once."
    elif authenticated and not install_ready:
        next_action = "Install a usable Unity editor so acquired packages can be unpacked and exported."
    else:
        next_action = "Set up Unity auth, then make sure at least one usable Unity editor install is detectable."

    details = dict(status)
    details["unity_install_count"] = len(unity_installations)
    details["unity_usable_install_count"] = sum(1 for item in unity_installations if item.get("usable"))
    return _row(
        provider_id="unity_asset_store",
        display_name="Unity Asset Store",
        lane=ProviderLane.MANUAL_BROWSER,
        status=_status_text(ready=ready, partial=partial),
        next_action=next_action,
        details=details,
    )


def _unity_export_row(unity_installations: tuple[dict[str, object], ...]) -> dict[str, object]:
    usable_count = sum(1 for item in unity_installations if item.get("usable"))
    return _row(
        provider_id="unity_export_bridge",
        display_name="Unity Export Bridge",
        lane=ProviderLane.MANUAL_BROWSER,
        status=_status_text(ready=usable_count > 0),
        next_action=(
            "Unity export bridge is ready."
            if usable_count > 0
            else "Install or expose a usable Unity editor before attempting Unity package export or ingest."
        ),
        details={
            "unity_install_count": len(unity_installations),
            "unity_usable_install_count": usable_count,
            "installations": list(unity_installations),
        },
    )


def _unreal_export_row(unreal_installations: tuple[dict[str, object], ...]) -> dict[str, object]:
    usable_count = sum(1 for item in unreal_installations if item.get("usable"))
    detected_count = len(unreal_installations)
    if usable_count > 0:
        next_action = "Unreal export bridge is ready."
    elif detected_count > 0:
        next_action = "An Unreal version root was detected, but it does not contain usable editor binaries. Repair or reinstall that Unreal editor build."
    else:
        next_action = "Install or expose a usable Unreal editor command path before attempting Unreal export automation."
    return _row(
        provider_id="unreal_export_bridge",
        display_name="Unreal Export Bridge",
        lane=ProviderLane.MANUAL_BROWSER,
        status=_status_text(ready=usable_count > 0),
        next_action=next_action,
        details={
            "unreal_install_count": len(unreal_installations),
            "unreal_usable_install_count": usable_count,
            "installations": list(unreal_installations),
        },
    )


def _epic_extraction_row() -> dict[str, object]:
    readiness = build_local_epic_extraction_readiness()
    fab_library_db = default_local_fab_library_db_path()
    launcher_data_dir = default_epic_launcher_saved_data_dir()
    partial = bool(readiness.get("can_extract_now")) or fab_library_db.exists() or launcher_data_dir.exists()
    details = dict(readiness)
    details["local_fab_library_db"] = str(fab_library_db)
    details["local_fab_library_db_exists"] = fab_library_db.exists()
    details["epic_launcher_saved_data_dir"] = str(launcher_data_dir)
    details["epic_launcher_saved_data_dir_exists"] = launcher_data_dir.exists()
    return _row(
        provider_id="epic_extraction",
        display_name="Epic/Fab Extraction",
        lane=ProviderLane.MANUAL_BROWSER,
        status=_status_text(ready=bool(readiness.get("can_extract_now")), partial=partial),
        next_action=str(readiness.get("recommended_path") or "Set up an Unreal extraction path before bulk Epic/Fab extraction."),
        details=details,
    )


def _legendary_row(timeout_seconds: float) -> dict[str, object]:
    status = build_legendary_status_report(timeout_seconds=timeout_seconds)
    exe_ready = bool(status.get("legendary_path"))
    session = status.get("session", {})
    token_ready = bool(session.get("remember_me_data_present"))
    ready = exe_ready and token_ready and not status.get("error")
    partial = exe_ready or token_ready
    if ready:
        next_action = "Legendary bridge is ready."
    elif exe_ready and not token_ready:
        next_action = "Import Epic auth first with `python scripts/cli.py asset-factory legendary-import-auth`."
    elif token_ready and not exe_ready:
        next_action = "Install `legendary` so Epic auth can drive the owned-library bridge."
    else:
        next_action = "Install `legendary` and import Epic auth before relying on the owned-library bridge."
    return _row(
        provider_id="legendary",
        display_name="Legendary Bridge",
        lane=ProviderLane.MANUAL_BROWSER,
        status=_status_text(ready=ready, partial=partial),
        next_action=next_action,
        details=status,
    )


def _generator_row(colab_profiles: tuple[dict[str, object], ...]) -> dict[str, object]:
    ai_provider_ids = _AI_PROVIDER_IDS  # parked YAML (Path B s2.6a)
    ready = bool(colab_profiles or ai_provider_ids)
    next_action = (
        "Generator profiles are available. Pick a profile or provider runbook before batch emission."
        if ready
        else "Add at least one generator profile under `scripts/asset_factory/profiles/colab/`."
    )
    return _row(
        provider_id="generator_profiles",
        display_name="Generator Profiles",
        lane=ProviderLane.GENERATOR,
        status=_status_text(ready=ready),
        next_action=next_action,
        details={
            "colab_profile_count": len(colab_profiles),
            "colab_profiles": list(colab_profiles),
            "ai_provider_count": len(ai_provider_ids),
            "ai_provider_ids": list(ai_provider_ids),
        },
    )


def _lane_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for lane in ProviderLane:
        matching_rows = [row for row in rows if row["lane"] == lane.value]
        counter = Counter(str(row["status"]) for row in matching_rows)
        aggregate_status = "setup_required"
        if matching_rows:
            aggregate_status = max((str(row["status"]) for row in matching_rows), key=lambda value: _STATUS_PRIORITY[value])
        adapters = adapters_for_lane(lane)
        summaries.append(
            {
                "lane": lane.value,
                "status": aggregate_status,
                "provider_count": len(matching_rows),
                "ready_now": counter.get("ready_now", 0),
                "partial": counter.get("partial", 0),
                "setup_required": counter.get("setup_required", 0),
                "review_required": LANE_POLICIES[lane].review_required,
                "destination": LANE_POLICIES[lane].default_destination,
                "adapter_ids": [adapter.adapter_id for adapter in adapters],
            }
        )
    return summaries


def _recommended_actions(rows: list[dict[str, object]]) -> list[str]:
    actions: list[str] = []
    for row in rows:
        if row["status"] != "ready_now":
            actions.append(str(row["next_action"]))
    return actions[:8]


def build_provider_readiness_report(*, timeout_seconds: float = 15.0) -> dict[str, object]:
    unity_installations = tuple(item.to_dict() for item in list_unity_installations())
    unreal_installations = tuple(item.to_dict() for item in list_unreal_installations())

    colab_profiles: list[dict[str, object]] = []
    for profile_id in _iter_colab_profile_ids():  # Path B s2.6a (was generator.profile_ids)
        colab_profiles.append(_load_colab_profile_summary(profile_id))

    providers = [
        _direct_url_row(),
        _fab_row(),
        _mixamo_row(),
        _unity_store_row(unity_installations),
        _unity_export_row(unity_installations),
        _unreal_export_row(unreal_installations),
        _epic_extraction_row(),
        _legendary_row(timeout_seconds),
        _generator_row(tuple(colab_profiles)),
    ]
    providers = [_annotate_row(row) for row in providers]

    status_counts = Counter(str(row["status"]) for row in providers)
    return {
        "summary": {
            "total": len(providers),
            "ready_now": status_counts.get("ready_now", 0),
            "partial": status_counts.get("partial", 0),
            "setup_required": status_counts.get("setup_required", 0),
        },
        "autonomy": _autonomy_summary(providers),
        "lanes": _lane_summary(providers),
        "providers": providers,
        "available_runbook_ids": list(_RUNBOOK_IDS),  # Path B s2.6a (was runbooks.provider_runbook_ids)
        "recommended_actions": _recommended_actions(providers),
    }


def build_provider_autonomy_delta_report(*, timeout_seconds: float = 15.0) -> dict[str, object]:
    report = build_provider_readiness_report(timeout_seconds=timeout_seconds)
    providers = report.get("providers", []) or []
    providers = providers if isinstance(providers, list) else []
    auth_blockers = _blocker_delta_rows(providers, reason_scope=_AUTH_BLOCKER_REASONS)
    tooling_blockers = _blocker_delta_rows(providers, reason_scope=_TOOLING_BLOCKER_REASONS)
    return {
        "summary": {
            "all_clear": not auth_blockers and not tooling_blockers,
            "auth_blocker_count": len(auth_blockers),
            "tooling_blocker_count": len(tooling_blockers),
        },
        "auth_blocker_provider_ids": [row["provider_id"] for row in auth_blockers],
        "tooling_blocker_provider_ids": [row["provider_id"] for row in tooling_blockers],
        "auth_blockers": auth_blockers,
        "tooling_blockers": tooling_blockers,
    }


def render_provider_readiness_report(report: dict[str, object]) -> str:
    lines: list[str] = []
    summary = report.get("summary", {})
    lines.append(
        "provider_readiness_summary="
        + str(
            {
                "total": summary.get("total", 0),
                "ready_now": summary.get("ready_now", 0),
                "partial": summary.get("partial", 0),
                "setup_required": summary.get("setup_required", 0),
            }
        )
    )
    autonomy = report.get("autonomy", {}) or {}
    lines.append(
        "provider_autonomy_summary="
        + str(
            {
                "recommended_provider_ids": autonomy.get("recommended_provider_ids", []),
                "highest_leverage_unblock_provider_ids": autonomy.get("highest_leverage_unblock_provider_ids", []),
                "auth_blocker_provider_ids": autonomy.get("auth_blocker_provider_ids", []),
                "tooling_blocker_provider_ids": autonomy.get("tooling_blocker_provider_ids", []),
            }
        )
    )

    for lane in report.get("lanes", []) or []:
        adapters = ",".join(str(item) for item in lane.get("adapter_ids", [])) or "-"
        lines.append(
            f"lane={lane.get('lane')} status={lane.get('status')} providers={lane.get('provider_count')} "
            f"ready_now={lane.get('ready_now')} partial={lane.get('partial')} setup_required={lane.get('setup_required')} "
            f"destination={lane.get('destination')} adapters={adapters}"
        )

    for row in report.get("providers", []) or []:
        details = row.get("details", {})
        detail_bits: list[str] = []
        if isinstance(details, dict):
            for key in (
                "authenticated",
                "unity_usable_install_count",
                "unreal_usable_install_count",
                "colab_profile_count",
                "ai_provider_count",
                "can_extract_now",
            ):
                if key in details:
                    detail_bits.append(f"{key}={details[key]}")
        detail_suffix = ""
        if detail_bits:
            detail_suffix = " " + " ".join(detail_bits)
        lines.append(
            f"provider={row.get('provider_id')} lane={row.get('lane')} status={row.get('status')} "
            f"autonomy_mode={row.get('autonomy_mode')}{detail_suffix}"
        )
        blocking_reasons = ",".join(str(item) for item in row.get("blocking_reasons", [])) or "-"
        lines.append(f"  blocking_reasons={blocking_reasons}")
        lines.append(f"  next_action={row.get('next_action')}")

    actions = report.get("recommended_actions", []) or []
    for index, action in enumerate(actions, start=1):
        lines.append(f"action_{index}={action}")

    return "\n".join(lines)


def render_provider_autonomy_delta_report(report: dict[str, object]) -> str:
    summary = report.get("summary", {}) or {}
    lines = [
        "provider_autonomy_deltas="
        + str(
            {
                "all_clear": bool(summary.get("all_clear", False)),
                "auth_blocker_count": int(summary.get("auth_blocker_count", 0) or 0),
                "tooling_blocker_count": int(summary.get("tooling_blocker_count", 0) or 0),
            }
        )
    ]

    auth_ids = ",".join(str(item) for item in report.get("auth_blocker_provider_ids", []) or []) or "-"
    tooling_ids = ",".join(str(item) for item in report.get("tooling_blocker_provider_ids", []) or []) or "-"
    lines.append(f"auth_blockers={auth_ids}")
    lines.append(f"tooling_blockers={tooling_ids}")

    for group_name in ("auth_blockers", "tooling_blockers"):
        for row in report.get(group_name, []) or []:
            reasons = ",".join(str(item) for item in row.get("blocking_reasons", []) or []) or "-"
            lines.append(
                f"{group_name[:-1]}={row.get('provider_id')} lane={row.get('lane')} status={row.get('status')} "
                f"autonomy_mode={row.get('autonomy_mode')} reasons={reasons}"
            )
            lines.append(f"  next_action={row.get('next_action')}")

    return "\n".join(lines)
