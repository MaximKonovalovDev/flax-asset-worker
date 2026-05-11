"""Semantic recipe diff (Path B v1.7.s14, 2026-05-11).

Compares two recipe YAML docs and returns structured "what changed"
output:

  added_packs:    [pack_id, ...]    (in new, not in old)
  removed_packs:  [pack_id, ...]    (in old, not in new)
  modified_packs: [{pack_id, changed_fields: [{field, old, new}]}, ...]
  recipe_field_changes: [{field, old, new}]  (recipe block changes)
  gate_changes:   {added_required, removed_required, added_optional, removed_optional}

Used by `pack diff <old.yaml> <new.yaml>` so operators iterating on a
recipe can see semantic changes at a glance, instead of squinting at
raw YAML diffs.

Compared per-pack: a small set of fields (id, provider, acquisition_method,
asset_kind, license.kind, prompts count, assets count, search_terms count,
cleanup.mode, gate.required). Full structural diff is overkill — these
are the fields that matter for "did this recipe meaningfully change?"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Fields we compare per pack
_PACK_FIELDS_DIRECT = (
    "provider",
    "acquisition_method",
    "asset_kind",
)
_PACK_FIELDS_NESTED = {
    "license.kind": ("license", "kind"),
    "cleanup.mode": ("cleanup", "mode"),
    "gate.required": ("gate", "required"),
}
_PACK_FIELDS_LIST_SIZES = ("prompts", "assets", "search_terms", "fallback_providers")


@dataclass
class FieldChange:
    field: str
    old: Any
    new: Any


@dataclass
class PackModification:
    pack_id: str
    changed_fields: list[FieldChange] = field(default_factory=list)


@dataclass
class DiffResult:
    added_packs: list[str] = field(default_factory=list)
    removed_packs: list[str] = field(default_factory=list)
    modified_packs: list[PackModification] = field(default_factory=list)
    recipe_field_changes: list[FieldChange] = field(default_factory=list)
    gate_changes: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_packs
            or self.removed_packs
            or self.modified_packs
            or self.recipe_field_changes
            or any(v for v in self.gate_changes.values())
        )


def diff_recipes(old_doc: dict[str, Any], new_doc: dict[str, Any]) -> DiffResult:
    """Compute a semantic diff between two recipe docs.

    Tolerant of None / non-dict docs (treats as empty recipe).
    """
    result = DiffResult()

    if not isinstance(old_doc, dict):
        old_doc = {}
    if not isinstance(new_doc, dict):
        new_doc = {}

    # Recipe-level field changes (id, game, description, ...)
    old_recipe = old_doc.get("recipe") or {}
    new_recipe = new_doc.get("recipe") or {}
    if isinstance(old_recipe, dict) and isinstance(new_recipe, dict):
        for key in sorted(set(old_recipe.keys()) | set(new_recipe.keys())):
            old_val = old_recipe.get(key)
            new_val = new_recipe.get(key)
            if old_val != new_val:
                result.recipe_field_changes.append(
                    FieldChange(field=f"recipe.{key}", old=old_val, new=new_val)
                )

    # Pack-level diff
    old_packs = {
        str(p.get("id", "")): p
        for p in (old_doc.get("packs") or [])
        if isinstance(p, dict) and p.get("id")
    }
    new_packs = {
        str(p.get("id", "")): p
        for p in (new_doc.get("packs") or [])
        if isinstance(p, dict) and p.get("id")
    }

    old_ids = set(old_packs.keys())
    new_ids = set(new_packs.keys())
    result.added_packs = sorted(new_ids - old_ids)
    result.removed_packs = sorted(old_ids - new_ids)

    for pack_id in sorted(old_ids & new_ids):
        old_pack = old_packs[pack_id]
        new_pack = new_packs[pack_id]
        changes = _diff_one_pack(old_pack, new_pack)
        if changes:
            result.modified_packs.append(
                PackModification(pack_id=pack_id, changed_fields=changes)
            )

    # Gates diff
    old_gates = old_doc.get("gates") or {}
    new_gates = new_doc.get("gates") or {}
    if isinstance(old_gates, dict) and isinstance(new_gates, dict):
        for gate_field in ("required_pack_ids", "optional_pack_ids"):
            old_list = set(str(x) for x in (old_gates.get(gate_field) or []))
            new_list = set(str(x) for x in (new_gates.get(gate_field) or []))
            added = sorted(new_list - old_list)
            removed = sorted(old_list - new_list)
            if added:
                result.gate_changes[f"added_{gate_field}"] = added
            if removed:
                result.gate_changes[f"removed_{gate_field}"] = removed

    return result


def _diff_one_pack(old_pack: dict, new_pack: dict) -> list[FieldChange]:
    changes: list[FieldChange] = []

    for field_name in _PACK_FIELDS_DIRECT:
        old_val = old_pack.get(field_name)
        new_val = new_pack.get(field_name)
        if old_val != new_val:
            changes.append(FieldChange(field=field_name, old=old_val, new=new_val))

    for display_name, path in _PACK_FIELDS_NESTED.items():
        old_val = _nested_get(old_pack, path)
        new_val = _nested_get(new_pack, path)
        if old_val != new_val:
            changes.append(FieldChange(field=display_name, old=old_val, new=new_val))

    for list_field in _PACK_FIELDS_LIST_SIZES:
        old_size = len(old_pack.get(list_field) or [])
        new_size = len(new_pack.get(list_field) or [])
        if old_size != new_size:
            changes.append(
                FieldChange(field=f"{list_field}.count", old=old_size, new=new_size)
            )

    return changes


def _nested_get(d: dict, path: tuple[str, ...]) -> Any:
    current: Any = d
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def diff_result_to_dict(diff: DiffResult) -> dict[str, Any]:
    """Convert a DiffResult to a plain dict (for JSON serialization)."""
    return {
        "added_packs": diff.added_packs,
        "removed_packs": diff.removed_packs,
        "modified_packs": [
            {
                "pack_id": m.pack_id,
                "changed_fields": [
                    {"field": c.field, "old": c.old, "new": c.new}
                    for c in m.changed_fields
                ],
            }
            for m in diff.modified_packs
        ],
        "recipe_field_changes": [
            {"field": c.field, "old": c.old, "new": c.new}
            for c in diff.recipe_field_changes
        ],
        "gate_changes": diff.gate_changes,
        "has_changes": diff.has_changes,
    }


__all__ = [
    "DiffResult",
    "PackModification",
    "FieldChange",
    "diff_recipes",
    "diff_result_to_dict",
]
