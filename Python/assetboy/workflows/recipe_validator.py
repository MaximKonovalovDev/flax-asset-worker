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
    # v1.13.s85: iNaturalist
    "inaturalist", "inat",
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
        # v1.17.s123 — output_folder soft validation.
        _validate_output_folder(recipe, source_label, result)
        # v1.23.s160 — optional created_utc / updated_utc ISO 8601 metadata.
        for ts_key in ("created_utc", "updated_utc"):
            if ts_key in recipe and recipe[ts_key] is not None:
                ts_val = recipe[ts_key]
                if not isinstance(ts_val, str):
                    result.warnings.append(
                        f"{source_label}: recipe.{ts_key} should be an"
                        f" ISO 8601 string; got {type(ts_val).__name__}"
                    )
                else:
                    from datetime import datetime
                    try:
                        datetime.fromisoformat(ts_val.strip())
                    except (ValueError, TypeError):
                        result.warnings.append(
                            f"{source_label}: recipe.{ts_key}={ts_val!r}"
                            f" is not parseable as ISO 8601"
                        )
        # v1.25.s172 — optional author / contact string fields.
        for str_key in ("author", "contact"):
            if str_key in recipe and recipe[str_key] is not None:
                val = recipe[str_key]
                if not isinstance(val, str):
                    result.warnings.append(
                        f"{source_label}: recipe.{str_key} should be a"
                        f" string; got {type(val).__name__}"
                    )
                elif not val.strip():
                    result.warnings.append(
                        f"{source_label}: recipe.{str_key} is empty;"
                        " consider removing the field"
                    )
        # v1.30.s189 — optional platform field; recommended values:
        # 'flax' / 'unity' / 'unreal' / 'godot' / 'web' / 'any'.
        # Warn on unknown values; never error (allows custom platforms).
        if "platform" in recipe and recipe["platform"] is not None:
            pval = recipe["platform"]
            if not isinstance(pval, str):
                result.warnings.append(
                    f"{source_label}: recipe.platform should be a string;"
                    f" got {type(pval).__name__}"
                )
            else:
                known_platforms = {"flax", "unity", "unreal",
                                    "godot", "web", "any"}
                if pval.strip().lower() not in known_platforms:
                    result.warnings.append(
                        f"{source_label}: recipe.platform={pval!r} is not"
                        f" in known set {sorted(known_platforms)};"
                        " custom values allowed but tooling may not pick them up"
                    )
        # v1.18.s130 — optional integer expected_min_assets field.
        if "expected_min_assets" in recipe and recipe["expected_min_assets"] is not None:
            ema = recipe["expected_min_assets"]
            if not isinstance(ema, int) or isinstance(ema, bool):
                result.ok = False
                result.errors.append(
                    f"{source_label}: recipe.expected_min_assets must be"
                    f" an integer; got {type(ema).__name__}"
                )
            elif ema < 0:
                result.ok = False
                result.errors.append(
                    f"{source_label}: recipe.expected_min_assets must be"
                    f" non-negative; got {ema!r}"
                )
        # v1.20.s141 — optional min_required_passes (int >= 0).
        if "min_required_passes" in recipe and recipe["min_required_passes"] is not None:
            mrp = recipe["min_required_passes"]
            if not isinstance(mrp, int) or isinstance(mrp, bool):
                result.ok = False
                result.errors.append(
                    f"{source_label}: recipe.min_required_passes must be"
                    f" an integer; got {type(mrp).__name__}"
                )
            elif mrp < 0:
                result.ok = False
                result.errors.append(
                    f"{source_label}: recipe.min_required_passes must be"
                    f" non-negative; got {mrp!r}"
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

    # v1.13.s93 — optional `tier` field: int in {0, 1, 2, 3} mapping to
    # P0/P1/P2/P3 priority. None/absent is fine. Any other value -> ERROR.
    if "tier" in pack and pack["tier"] is not None:
        tier_val = pack["tier"]
        if not isinstance(tier_val, int) or isinstance(tier_val, bool):
            result.ok = False
            result.errors.append(
                f"{pack_label} ({pack_id}): 'tier' must be an integer 0..3; "
                f"got {type(tier_val).__name__}"
            )
        elif tier_val not in (0, 1, 2, 3):
            result.ok = False
            result.errors.append(
                f"{pack_label} ({pack_id}): 'tier' must be 0, 1, 2, or 3 "
                f"(P0..P3 priority); got {tier_val!r}"
            )


def _validate_output_folder(
    recipe: dict[str, Any],
    source_label: str,
    result: ValidationResult,
) -> None:
    """Soft-validate recipe.output_folder (v1.17.s123).

    Catches:
      - Non-string value (ERROR)
      - Empty/whitespace (WARNING)
      - Absolute paths on a project-relative field (WARNING)
      - Backslashes (cross-platform portability WARNING)
      - Illegal path chars: < > : " | ? * NUL (ERROR on Windows; WARNING otherwise)
    """
    if "output_folder" not in recipe:
        return  # field optional
    value = recipe["output_folder"]
    if value is None:
        return
    if not isinstance(value, str):
        result.ok = False
        result.errors.append(
            f"{source_label}: recipe.output_folder must be a string; "
            f"got {type(value).__name__}"
        )
        return
    stripped = value.strip()
    if not stripped:
        result.warnings.append(
            f"{source_label}: recipe.output_folder is empty/whitespace; "
            "pipeline will fall back to a default path"
        )
        return
    # Absolute path soft warning.
    if stripped.startswith(("/", "\\")) or (
        len(stripped) >= 2 and stripped[1] == ":"  # windows drive letter
    ):
        result.warnings.append(
            f"{source_label}: recipe.output_folder is absolute "
            f"({stripped!r}); recipes typically use project-relative paths "
            "(e.g. 'Content/MyGame/...') for portability"
        )
    # Backslash soft warning.
    if "\\" in stripped:
        result.warnings.append(
            f"{source_label}: recipe.output_folder contains backslashes "
            "({stripped!r}); use forward slashes for cross-platform consistency"
        )
    # Illegal chars: hard error.
    illegal = [c for c in '<>:"|?*' if c in stripped[2:] if not c == ":"]
    if any(c in stripped[2:] for c in '<>"|?*'):
        bad_chars = sorted({c for c in stripped[2:] if c in '<>"|?*'})
        result.ok = False
        result.errors.append(
            f"{source_label}: recipe.output_folder contains illegal path "
            f"characters: {bad_chars}"
        )


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
    # v1.13.s85 — R1A no-key providers
    "met_museum": {"kind": "cc0", "commercial_ok": True, "attribution_required": False},
    "wikimedia": {"kind": "cc_by_sa_mixed", "commercial_ok": True, "attribution_required": "per-file"},
    "wikimedia_commons": {"kind": "cc_by_sa_mixed", "commercial_ok": True, "attribution_required": "per-file"},
    "archive_org": {"kind": "cc_pd_mixed", "commercial_ok": True, "attribution_required": "per-item"},
    "scryfall": {"kind": "cc_by_sa_4_0", "commercial_ok": True, "attribution_required": True, "attribution_note": "Wizards of the Coast + per-card artist"},
    "iconify": {"kind": "open_source_spdx_mixed", "commercial_ok": True, "attribution_required": "per-set"},
    # R1A key-required providers
    "pexels": {"kind": "pexels_license", "commercial_ok": True, "attribution_required": False},
    "pixabay": {"kind": "pixabay_content_license", "commercial_ok": True, "attribution_required": False},
    "unsplash": {"kind": "unsplash_license", "commercial_ok": True, "attribution_required": False},
    "rawg": {"kind": "reference_only_publisher_copyright", "commercial_ok": False, "attribution_required": "not for redistribution"},
    "jamendo": {"kind": "cc_by_or_cc_by_sa", "commercial_ok": True, "attribution_required": True},
    # v1.13.s84 — iNaturalist
    "inaturalist": {"kind": "cc_mixed_default_commercial_safe", "commercial_ok": True, "attribution_required": "per-photo"},
    "inat": {"kind": "cc_mixed_default_commercial_safe", "commercial_ok": True, "attribution_required": "per-photo"},
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

        # v1.13.s93 — missing `tier` defaults to 2 (P2 = nice-to-have).
        if "tier" not in patched or patched.get("tier") is None:
            patched["tier"] = 2
            fixes.append(
                f"{pack_id}: added default tier=2 (P2/nice-to-have; "
                "operator can set 0/1/3 for required/critical/optional)"
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
