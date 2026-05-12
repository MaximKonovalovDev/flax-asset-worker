"""Recipe YAML schema validator (Path B v1.6.s5, 2026-05-11).

Lints `recipes/<game>/<recipe>.yaml` against the v1 schema BEFORE
`pack from-recipe` runs them. Catches:

  - Missing top-level `recipe` or `packs` keys
  - Missing required pack fields (id, provider, acquisition_method)
  - Unknown acquisition_method values (anything outside the 3 canonical lanes)
  - Unknown provider for the given lane (e.g. `provider: mystery` on direct_url)
  - generator packs missing `prompts: [...]`
  - manual_browser packs missing `source_url` AND no `assets:` list
  - direct_url packs missing `assets: [...]` (and no `search_terms` either)
  - gates referencing pack IDs that don't exist in the recipe
  - Duplicate pack IDs within the recipe

Returns a `ValidationResult` with:
  ok: bool
  errors: list[str]    (HARD failures - recipe will not run correctly)
  warnings: list[str]  (likely-wrong but not blocking)

This is a SHALLOW validator: it checks shape, not semantics. It does NOT
verify provider IDs are installed/configured or that assets exist on
external services. For that, run the actual `pack from-recipe`.

CLI integration: `python -m assetboy.cli pack validate <recipe.yaml>`
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------------- #
# Schema constants
# --------------------------------------------------------------------------- #

VALID_ACQUISITION_METHODS = {"direct_url", "manual_browser", "generator"}

# Known providers per lane (sourced from acquisition_router.py's dispatch tables).
# Empty set in any value = no per-provider whitelist (we accept anything and
# let the runtime fail if unsupported).
DIRECT_URL_PROVIDERS = {
    "polyhaven", "kenney", "ambientcg", "freesound", "quaternius",
    # v1.11.s41: R1A no-key providers wired into acquisition_router.
    "met_museum", "met-museum",
    "wikimedia", "wikimedia_commons",
    "archive_org", "archive-org", "archiveorg",
    "scryfall",
    "iconify",
    # v1.11.s43: R1A key-required providers (env-var-aware).
    "pexels", "pexels_photos", "pexels_videos",
    "pixabay", "pixabay_photos", "pixabay_videos",
    "unsplash",
    "rawg",
    "jamendo",
}
MANUAL_BROWSER_PROVIDERS = {
    "fab", "mixamo", "unity", "epic",
    # Aliases the router accepts:
    "unity_asset_store", "epic_games", "epic_vault",
}
GENERATOR_PROVIDERS = {
    "comfyui",
    "local_image", "sd.cpp", "sd",
    "stable_audio_open_small", "stable_audio",
}

REQUIRED_RECIPE_KEYS = {"id", "game"}
REQUIRED_PACK_KEYS = {"id", "provider", "acquisition_method"}


# --------------------------------------------------------------------------- #
# Result type
# --------------------------------------------------------------------------- #

@dataclass
class ValidationResult:
    """Outcome of validating a recipe.

    `ok` is True iff there are zero errors. Warnings don't flip ok.
    `pack_count` and `recipe_id` are populated when the recipe parses
    far enough to know them (helps CLI output regardless of failure).
    """
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recipe_id: str = ""
    pack_count: int = 0


# --------------------------------------------------------------------------- #
# Validators
# --------------------------------------------------------------------------- #

def validate_recipe_doc(doc: Any, source_label: str = "<recipe>") -> ValidationResult:
    """Validate a parsed recipe dict. Returns ValidationResult never raises.

    Args:
        doc:           the parsed YAML document (top-level)
        source_label:  human-readable identifier for the recipe (file path or "stdin")
    """
    result = ValidationResult(ok=True)

    if not isinstance(doc, dict):
        result.ok = False
        result.errors.append(
            f"{source_label}: recipe root must be a mapping; "
            f"got {type(doc).__name__}"
        )
        return result

    recipe = doc.get("recipe")
    if not isinstance(recipe, dict):
        result.ok = False
        result.errors.append(
            f"{source_label}: missing or non-dict top-level 'recipe' key"
        )
        # Continue checking packs even without recipe block (may be salvageable)
    else:
        result.recipe_id = str(recipe.get("id", ""))
        for k in REQUIRED_RECIPE_KEYS:
            if k not in recipe or not str(recipe[k]).strip():
                result.ok = False
                result.errors.append(
                    f"{source_label}: recipe.{k} is required but missing/empty"
                )
        # v1.11.s51: optional discovery metadata fields. Each must be a
        # string OR list of strings when present. Used by future
        # `pack list-recipes --filter genre:rpg` style queries.
        _validate_recipe_metadata_field(
            recipe, "genre", source_label, result
        )
        _validate_recipe_metadata_field(
            recipe, "theme", source_label, result
        )
        _validate_recipe_metadata_field(
            recipe, "style", source_label, result
        )
        _validate_recipe_metadata_field(
            recipe, "tags", source_label, result
        )

    packs = doc.get("packs")
    if not isinstance(packs, list):
        result.ok = False
        result.errors.append(
            f"{source_label}: top-level 'packs' must be a list; "
            f"got {type(packs).__name__}"
        )
        return result

    result.pack_count = len(packs)
    if not packs:
        result.warnings.append(
            f"{source_label}: 'packs' list is empty; recipe will do nothing"
        )

    seen_pack_ids: set[str] = set()
    for idx, pack in enumerate(packs):
        if not isinstance(pack, dict):
            result.ok = False
            result.errors.append(
                f"{source_label}: packs[{idx}] must be a mapping; "
                f"got {type(pack).__name__}"
            )
            continue
        _validate_pack(pack, idx, seen_pack_ids, source_label, result)

    _validate_gates(doc.get("gates"), seen_pack_ids, source_label, result)
    return result


def _validate_pack(
    pack: dict[str, Any],
    idx: int,
    seen_ids: set[str],
    source_label: str,
    result: ValidationResult,
) -> None:
    pack_label = f"{source_label}: packs[{idx}]"
    pack_id = pack.get("id")

    if not pack_id or not str(pack_id).strip():
        result.ok = False
        result.errors.append(f"{pack_label}: missing required 'id' field")
        # No further checks possible without an id
        return

    pack_id = str(pack_id)
    if pack_id in seen_ids:
        result.ok = False
        result.errors.append(
            f"{pack_label}: duplicate pack id {pack_id!r} (already declared earlier)"
        )
    seen_ids.add(pack_id)

    # Required fields
    for k in REQUIRED_PACK_KEYS:
        if k not in pack or not str(pack[k]).strip():
            result.ok = False
            result.errors.append(
                f"{pack_label} ({pack_id}): required field {k!r} missing or empty"
            )

    method = str(pack.get("acquisition_method", "")).strip().lower()
    provider = str(pack.get("provider", "")).strip().lower()

    # Method must be one of the 3 canonical lanes
    if method and method not in VALID_ACQUISITION_METHODS:
        result.ok = False
        result.errors.append(
            f"{pack_label} ({pack_id}): unknown acquisition_method {method!r}; "
            f"expected one of {sorted(VALID_ACQUISITION_METHODS)}"
        )

    # Lane-specific provider whitelist + per-lane field requirements
    if method == "direct_url":
        if provider and provider not in DIRECT_URL_PROVIDERS:
            result.warnings.append(
                f"{pack_label} ({pack_id}): provider {provider!r} not in "
                f"known direct_url providers {sorted(DIRECT_URL_PROVIDERS)} "
                "(will fail at runtime unless router gains support)"
            )
        assets = pack.get("assets") or []
        search_terms = pack.get("search_terms") or []
        if not assets and not search_terms:
            result.ok = False
            result.errors.append(
                f"{pack_label} ({pack_id}): direct_url pack must have "
                "either 'assets: [...]' or 'search_terms: [...]'"
            )
    elif method == "manual_browser":
        if provider and provider not in MANUAL_BROWSER_PROVIDERS:
            result.warnings.append(
                f"{pack_label} ({pack_id}): provider {provider!r} not in "
                f"known manual_browser providers {sorted(MANUAL_BROWSER_PROVIDERS)}"
            )
        source_url = pack.get("source_url")
        assets = pack.get("assets") or []
        if not source_url and not assets:
            result.warnings.append(
                f"{pack_label} ({pack_id}): manual_browser pack should have "
                "'source_url' or 'assets: [...]' for operator instructions"
            )
    elif method == "generator":
        if provider and provider not in GENERATOR_PROVIDERS:
            result.warnings.append(
                f"{pack_label} ({pack_id}): provider {provider!r} not in "
                f"known generator providers {sorted(GENERATOR_PROVIDERS)}"
            )
        prompts = pack.get("prompts") or []
        if not prompts:
            result.ok = False
            result.errors.append(
                f"{pack_label} ({pack_id}): generator pack must have 'prompts: [...]'"
            )

    # asset_kind (optional but recommended)
    if "asset_kind" not in pack:
        result.warnings.append(
            f"{pack_label} ({pack_id}): no 'asset_kind' set; pipeline will "
            "default to 'prop'"
        )

    # license block (optional but recommended for shipped recipes)
    if "license" not in pack:
        result.warnings.append(
            f"{pack_label} ({pack_id}): no 'license' block; consider adding "
            "'license: {kind: ..., commercial_ok: ...}' for clarity"
        )

    # *_refs fields (v1.11.s36): optional reference URL lists for video/music/icons.
    # Lists of strings; entries should look like URLs (start with http(s)://)
    # but we permit any non-empty string for forward-compat (local paths, IDs).
    _validate_refs_field(pack, "video_refs", pack_label, pack_id, result)
    _validate_refs_field(pack, "music_refs", pack_label, pack_id, result)
    _validate_refs_field(pack, "icon_refs", pack_label, pack_id, result)
    _validate_refs_field(pack, "reference_image_urls", pack_label, pack_id, result)


def _validate_recipe_metadata_field(
    recipe: dict[str, Any],
    field_name: str,
    source_label: str,
    result: ValidationResult,
) -> None:
    """Validate optional recipe-level discovery metadata fields (v1.11.s51).

    Each metadata field (genre, theme, style, tags) must be one of:
      - string (single value): 'rpg' or 'fantasy'
      - list[str] (multiple values): ['rpg', 'roguelite']
      - omitted/null (no validation)

    Anything else (int, dict, mixed list) -> ERROR.
    Empty string -> WARNING (field present but no value).
    """
    if field_name not in recipe:
        return
    value = recipe[field_name]
    if value is None:
        return
    if isinstance(value, str):
        if not value.strip():
            result.warnings.append(
                f"{source_label}: recipe.{field_name} is empty string; "
                "consider removing or filling"
            )
        return
    if isinstance(value, list):
        for i, entry in enumerate(value):
            if not isinstance(entry, str):
                result.ok = False
                result.errors.append(
                    f"{source_label}: recipe.{field_name}[{i}] must be a "
                    f"string; got {type(entry).__name__}"
                )
            elif not entry.strip():
                result.ok = False
                result.errors.append(
                    f"{source_label}: recipe.{field_name}[{i}]: empty string "
                    "not allowed"
                )
        return
    # Not str, not list, not None — wrong type.
    result.ok = False
    result.errors.append(
        f"{source_label}: recipe.{field_name} must be a string or list of "
        f"strings; got {type(value).__name__}"
    )


def _validate_refs_field(
    pack: dict[str, Any],
    field_name: str,
    pack_label: str,
    pack_id: str,
    result: ValidationResult,
) -> None:
    """Validate optional ref-list fields (v1.11.s36 schema extension).

    Shape: `<field>: [str, str, ...]`. Non-list -> ERROR. Empty list ok.
    Non-string entries -> ERROR. Entries that aren't URL-shaped (don't start
    with http/https/file/<local-path-marker>) -> WARNING.
    """
    if field_name not in pack:
        return
    value = pack[field_name]
    if value is None:
        return
    if not isinstance(value, list):
        result.ok = False
        result.errors.append(
            f"{pack_label} ({pack_id}): {field_name!r} must be a list of strings; "
            f"got {type(value).__name__}"
        )
        return
    for i, entry in enumerate(value):
        entry_label = f"{pack_label} ({pack_id}): {field_name}[{i}]"
        if not isinstance(entry, str):
            result.ok = False
            result.errors.append(
                f"{entry_label}: must be a string; got {type(entry).__name__}"
            )
            continue
        stripped = entry.strip()
        if not stripped:
            result.ok = False
            result.errors.append(f"{entry_label}: empty string not allowed")
            continue
        # Soft check: URL-shaped?
        lower = stripped.lower()
        is_url_shaped = (
            lower.startswith(("http://", "https://", "file://", "ftp://"))
            or lower.startswith("/")  # absolute local
            or lower.startswith("./")  # relative local
            or lower.startswith("../")
            or (len(stripped) >= 3 and stripped[1] == ":")  # windows drive
        )
        if not is_url_shaped:
            result.warnings.append(
                f"{entry_label}: {stripped!r} doesn't look URL-shaped "
                "(expected http(s)://... or local path)"
            )


def _validate_gates(
    gates: Any,
    pack_ids: set[str],
    source_label: str,
    result: ValidationResult,
) -> None:
    if gates is None:
        return  # gates block is optional
    if not isinstance(gates, dict):
        result.warnings.append(
            f"{source_label}: 'gates' should be a mapping; "
            f"got {type(gates).__name__}; ignoring"
        )
        return

    for field_name in ("required_pack_ids", "optional_pack_ids"):
        gate_ids = gates.get(field_name) or []
        if not isinstance(gate_ids, list):
            result.warnings.append(
                f"{source_label}: gates.{field_name} should be a list; ignoring"
            )
            continue
        for gid in gate_ids:
            gid_str = str(gid)
            if gid_str not in pack_ids:
                result.ok = False
                result.errors.append(
                    f"{source_label}: gates.{field_name} references "
                    f"unknown pack_id {gid_str!r}; not present in this recipe's packs[]"
                )


def validate_recipe_file(recipe_path: str | Path) -> ValidationResult:
    """Load a YAML file from disk and validate it.

    Returns ValidationResult with errors populated if the file can't be
    read or parsed.
    """
    path = Path(recipe_path)
    if not path.exists():
        result = ValidationResult(ok=False)
        result.errors.append(f"recipe_not_found: {path}")
        return result

    try:
        import yaml
    except ImportError as exc:
        result = ValidationResult(ok=False)
        result.errors.append(f"pyyaml_not_installed: {exc}")
        return result

    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        result = ValidationResult(ok=False)
        result.errors.append(f"yaml_parse_error: {exc}")
        return result
    except Exception as exc:
        result = ValidationResult(ok=False)
        result.errors.append(f"read_failed: {exc}")
        return result

    return validate_recipe_doc(doc, source_label=str(path))


__all__ = [
    "ValidationResult",
    "VALID_ACQUISITION_METHODS",
    "DIRECT_URL_PROVIDERS",
    "MANUAL_BROWSER_PROVIDERS",
    "GENERATOR_PROVIDERS",
    "validate_recipe_doc",
    "validate_recipe_file",
    "auto_fix_warnings",
]


# --------------------------------------------------------------------------- #
# Auto-fix (v1.9.s24)
# --------------------------------------------------------------------------- #

# Default source_url per manual_browser provider. Used by auto-fix when a
# manual_browser pack is missing source_url. These are "safe defaults" --
# generic landing pages the operator can refine.
_DEFAULT_MANUAL_BROWSER_URLS = {
    "fab": "https://www.fab.com/",
    "mixamo": "https://www.mixamo.com/",
    "unity": "https://assetstore.unity.com/",
    "unity_asset_store": "https://assetstore.unity.com/",
    "epic": "https://store.epicgames.com/",
    "epic_games": "https://store.epicgames.com/",
    "epic_vault": "https://www.fab.com/vault",
}

# Default license-block shape per provider. Sensible commercial_ok defaults.
_DEFAULT_LICENSE_BY_PROVIDER = {
    "polyhaven": {"kind": "cc0", "commercial_ok": True, "attribution_required": False},
    "kenney": {"kind": "cc0", "commercial_ok": True, "attribution_required": False},
    "ambientcg": {"kind": "cc0", "commercial_ok": True, "attribution_required": False},
    "quaternius": {"kind": "cc0", "commercial_ok": True, "attribution_required": False},
    "freesound": {"kind": "cc0_or_cc_by_filtered", "commercial_ok": True, "attribution_required": "per-file"},
    "fab": {"kind": "fab_standard", "commercial_ok": True, "cross_engine_ok": True},
    "mixamo": {"kind": "mixamo_free", "commercial_ok": True, "attribution_required": False},
    "unity": {"kind": "manual_per_source", "commercial_ok": True, "cross_engine_ok": True},
    "unity_asset_store": {"kind": "manual_per_source", "commercial_ok": True, "cross_engine_ok": True},
    "epic": {"kind": "manual_per_source", "commercial_ok": True, "cross_engine_ok": True},
    "comfyui": {"kind": "comfyui_workflow_dependent"},
    "local_image": {"kind": "sd_model_dependent"},
    "sd.cpp": {"kind": "sd_model_dependent"},
    "stable_audio_open_small": {"kind": "stability_community", "commercial_ok": True, "training_data_clean": True},
    "stable_audio": {"kind": "stability_community", "commercial_ok": True, "training_data_clean": True},
}


def auto_fix_warnings(doc: dict) -> tuple[dict, list[str]]:
    """Auto-fix common validator warnings.

    Path B v1.9.s24 (2026-05-11). Returns (fixed_doc, list_of_fix_descriptions).

    Fixes applied (in order):
      1. manual_browser packs missing 'source_url' get a default per-provider
         landing page (Fab.com root, Mixamo root, etc.) so operators see a
         real URL instead of nothing.
      2. Packs missing 'license' block get a sensible per-provider default
         (cc0 for polyhaven/kenney/ambientcg/quaternius; fab_standard for
         fab; stability_community for stable_audio; etc.).
      3. Packs missing 'asset_kind' get a conservative 'prop' default.

    Does NOT fix:
      - Hard errors (missing id, unknown method, etc.) -- those need
        operator decision, not autocomplete.
      - License kind values the operator already set -- only fills empty.

    The returned doc is a shallow-modified copy of the input (top-level
    keys preserved; only 'packs' list entries get patched in place).
    """
    if not isinstance(doc, dict):
        return doc, []

    fixed_doc = dict(doc)
    fixes: list[str] = []
    packs = list(fixed_doc.get("packs") or [])
    new_packs: list[dict] = []

    for idx, pack in enumerate(packs):
        if not isinstance(pack, dict):
            new_packs.append(pack)
            continue
        patched = dict(pack)
        pack_id = patched.get("id", f"packs[{idx}]")
        method = str(patched.get("acquisition_method", "")).strip().lower()
        provider = str(patched.get("provider", "")).strip().lower()

        # Fix 1: manual_browser missing source_url + assets
        if method == "manual_browser":
            has_url = bool(patched.get("source_url"))
            has_assets = bool(patched.get("assets"))
            if not has_url and not has_assets:
                default_url = _DEFAULT_MANUAL_BROWSER_URLS.get(provider)
                if default_url:
                    patched["source_url"] = default_url
                    fixes.append(
                        f"{pack_id}: added default source_url={default_url!r} for manual_browser/{provider}"
                    )

        # Fix 2: missing license block
        if "license" not in patched or not patched["license"]:
            default_license = _DEFAULT_LICENSE_BY_PROVIDER.get(provider)
            if default_license:
                patched["license"] = dict(default_license)
                fixes.append(
                    f"{pack_id}: added default license block "
                    f"(kind={default_license.get('kind', '?')}) for provider {provider!r}"
                )

        # Fix 3: missing asset_kind
        if "asset_kind" not in patched or not str(patched.get("asset_kind", "")).strip():
            patched["asset_kind"] = "prop"
            fixes.append(
                f"{pack_id}: added default asset_kind='prop' (operator can refine)"
            )

        new_packs.append(patched)

    fixed_doc["packs"] = new_packs

    # v1.13.s81 — recipe-level metadata auto-fill.
    # If recipe block exists and lacks 'tags', add a single 'auto' tag
    # so future discovery queries can filter "untagged" recipes by absence.
    recipe = fixed_doc.get("recipe")
    if isinstance(recipe, dict):
        recipe_changed = False
        # Only fill 'tags' if absent or empty — never overwrite operator values.
        if "tags" not in recipe or (
            isinstance(recipe.get("tags"), list) and not recipe["tags"]
        ):
            recipe["tags"] = ["auto-tagged"]
            recipe_changed = True
            fixes.append(
                "recipe: added default tags=['auto-tagged'] (operator can refine via "
                "pack list-recipes --filter tags:<tag>)"
            )
        if recipe_changed:
            fixed_doc["recipe"] = recipe

    return fixed_doc, fixes
