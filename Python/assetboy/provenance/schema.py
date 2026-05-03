from __future__ import annotations

from pathlib import Path
from typing import Any

PUBLISHABLE_EXTENSIONS = {
    ".fbx", ".obj", ".gltf", ".glb",
    ".png", ".jpg", ".jpeg", ".tga", ".hdr",
    ".wav", ".ogg", ".mp3",
    ".ttf", ".otf", ".woff", ".woff2",
}


FIELD_GUIDANCE: dict[str, str] = {
    "source_url": "Canonical source page or direct asset URL used to acquire or generate the asset.",
    "license": "License name or rights label shown by the source.",
    "license_snapshot": "Short preserved rights text, entitlement note, or license summary captured at acquisition time.",
    "author_or_vendor": "Creator, publisher, vendor, or institution associated with the asset.",
    "acquired_at": "UTC timestamp or ISO date when the asset was acquired or generated.",
    "lane": "AssetBoy provider lane: direct_url, manual_browser, or generator.",
    "source_adapter": "Specific AssetBoy adapter or bridge id used to acquire the asset.",
    "payload_target_path": "Publish/intake payload target path expected downstream.",
    "download_url": "Direct download URL when one was used.",
    "downloaded_filename": "Original downloaded filename or archive name.",
    "download_notes": "Archive version notes, export settings, or operator observations.",
    "entitlement_note": "Required for non-open licenses: how the operator is entitled to use this asset.",
    "prompt": "Positive prompt used for generation.",
    "negative_prompt": "Negative prompt used for generation.",
    "model_name": "Generator model or notebook name.",
    "profile_id": "AssetBoy generator profile used for the run.",
    "seed": "Seed used for generation, if available.",
    "notebook_or_session": "Notebook URL, local run id, or session identifier for the generation job.",
    "cleanup_profile": "Cleanup recipe applied before publish.",
    "review_notes": "Reviewer notes before publish/intake.",
}


COMMON_REQUIRED_FIELDS: tuple[str, ...] = (
    "source_url",
    "license",
    "license_snapshot",
    "author_or_vendor",
    "acquired_at",
    "lane",
    "source_adapter",
    "payload_target_path",
)

DIRECT_URL_REQUIRED_FIELDS: tuple[str, ...] = COMMON_REQUIRED_FIELDS + (
    "downloaded_filename",
)

MANUAL_BROWSER_REQUIRED_FIELDS: tuple[str, ...] = COMMON_REQUIRED_FIELDS + (
    "downloaded_filename",
)

GENERATOR_REQUIRED_FIELDS: tuple[str, ...] = COMMON_REQUIRED_FIELDS + (
    "prompt",
    "model_name",
    "profile_id",
    "notebook_or_session",
)


LEGACY_TEMPLATE_KEYS: tuple[str, ...] = (
    "source_page_url",
    "license_url",
    "author",
    "vendor",
    "author_url",
    "download_date",
    "acquired_at_utc",
    "license_note",
    "license_notes",
)


_ALIASES: dict[str, tuple[str, ...]] = {
    "source_url": ("source_url", "source_page_url", "download_url"),
    "license": ("license",),
    "license_snapshot": ("license_snapshot", "license_note", "license_notes", "download_notes", "review_notes"),
    "author_or_vendor": ("author_or_vendor", "author", "vendor"),
    "acquired_at": ("acquired_at", "acquired_at_utc", "download_date"),
    "lane": ("lane",),
    "source_adapter": ("source_adapter",),
    "payload_target_path": ("payload_target_path", "payload_target"),
    "downloaded_filename": ("downloaded_filename",),
    "download_url": ("download_url",),
    "download_notes": ("download_notes", "license_notes", "license_note"),
    "entitlement_note": ("entitlement_note", "license_note", "license_notes", "download_notes", "notes"),
    "prompt": ("prompt",),
    "negative_prompt": ("negative_prompt",),
    "model_name": ("model_name",),
    "profile_id": ("profile_id",),
    "seed": ("seed",),
    "notebook_or_session": ("notebook_or_session",),
    "cleanup_profile": ("cleanup_profile",),
    "review_notes": ("review_notes",),
}

_ALIAS_KEYS: set[str] = {alias for aliases in _ALIASES.values() for alias in aliases}

_CANONICAL_FIELD_ORDER: tuple[str, ...] = (
    "pack_id",
    "game_scope",
    "source_url",
    "license",
    "license_snapshot",
    "author_or_vendor",
    "acquired_at",
    "lane",
    "source_adapter",
    "payload_target_path",
    "download_url",
    "downloaded_filename",
    "download_notes",
    "entitlement_note",
    "prompt",
    "negative_prompt",
    "model_name",
    "profile_id",
    "seed",
    "notebook_or_session",
    "cleanup_profile",
    "review_notes",
)


_OPEN_LICENSE_TOKENS: tuple[str, ...] = (
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

_LANE_ALIASES: dict[str, str] = {
    "direct-url": "direct_url",
    "manual-browser": "manual_browser",
    "manual browser": "manual_browser",
}


def provenance_requirements_for(lane: ProviderLane | str, source_adapter: str = "") -> tuple[str, ...]:
    lane_value = getattr(lane, "value", lane)
    lane_value = str(lane_value or "").strip()
    if lane_value == "direct_url":
        return DIRECT_URL_REQUIRED_FIELDS
    if lane_value == "manual_browser":
        return MANUAL_BROWSER_REQUIRED_FIELDS
    return GENERATOR_REQUIRED_FIELDS


def build_template_values(
    *,
    lane: ProviderLane | str,
    source_adapter: str,
    payload_target_path: str,
    required_fields: tuple[str, ...],
) -> dict[str, object]:
    lane_value = getattr(lane, "value", lane)
    lane_value = str(lane_value)
    values: dict[str, object] = {field_id: "" for field_id in required_fields}
    for key in LEGACY_TEMPLATE_KEYS:
        values.setdefault(key, "")

    values["lane"] = lane_value
    values["source_adapter"] = source_adapter
    values["payload_target_path"] = payload_target_path
    return values


def normalize_provenance(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for canonical, aliases in _ALIASES.items():
        for field_name in aliases:
            value = payload.get(field_name)
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            normalized[canonical] = value
            break

    return normalized


def canonicalize_provenance_payload(
    payload: dict[str, Any],
    *,
    keep_extra: bool = True,
) -> dict[str, Any]:
    """Return a stable canonical provenance payload.

    Canonical fields are normalized through alias mapping and emitted in a stable
    key order. Legacy alias keys are dropped. Optional unknown metadata keys are
    preserved when keep_extra=True.
    """
    normalized = normalize_provenance(payload)
    canonical: dict[str, Any] = {}

    for field_id in _CANONICAL_FIELD_ORDER:
        value = normalized.get(field_id)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        canonical[field_id] = value

    if keep_extra:
        for key, value in payload.items():
            if key in canonical or key in _ALIAS_KEYS:
                continue
            if value is None:
                continue
            if isinstance(value, str):
                trimmed = value.strip()
                if not trimmed:
                    continue
                canonical[key] = trimmed
            else:
                canonical[key] = value

    return canonical


def validate_provenance_payload(
    payload: dict[str, Any],
    *,
    expected_lane: str | None = None,
    expected_payload_target_path: str | Path | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    normalized = normalize_provenance(payload)

    lane = str(normalized.get("lane") or expected_lane or "").strip()
    lane = _normalize_lane_value(lane)
    if lane not in {"direct_url", "manual_browser", "generator"}:
        errors.append("provenance.lane is missing or invalid.")
        lane = expected_lane or lane

    required_fields = provenance_requirements_for(lane or "direct_url")
    for field_id in required_fields:
        value = normalized.get(field_id)
        if value is None:
            errors.append(f"provenance.{field_id} is missing.")
            continue
        if isinstance(value, str) and not value.strip():
            errors.append(f"provenance.{field_id} is empty.")

    license_name = str(normalized.get("license", "")).strip().lower()
    if license_name and _requires_entitlement_note(license_name):
        entitlement = str(normalized.get("entitlement_note", "")).strip()
        if not entitlement:
            errors.append("provenance.entitlement_note is required for non-open or store-gated licenses.")

    expected_target = str(expected_payload_target_path or "").strip()
    actual_target = str(normalized.get("payload_target_path", "")).strip()
    if expected_target and actual_target and _normalize_path(actual_target) != _normalize_path(expected_target):
        errors.append(
            f"provenance.payload_target_path '{actual_target}' != expected '{expected_target}'."
        )

    if expected_lane and lane and lane != expected_lane:
        warnings.append(f"provenance.lane '{lane}' != expected '{expected_lane}'.")

    return normalized, errors, warnings


def _requires_entitlement_note(license_name: str) -> bool:
    return not any(token in license_name for token in _OPEN_LICENSE_TOKENS)


def _normalize_path(value: str) -> str:
    return str(Path(value).resolve()) if value else ""


def _normalize_lane_value(value: str) -> str:
    if not value:
        return value

    lowered = value.strip().lower()
    if lowered in {"direct_url", "manual_browser", "generator"}:
        return lowered

    return _LANE_ALIASES.get(lowered, lowered.replace(" ", "_"))
