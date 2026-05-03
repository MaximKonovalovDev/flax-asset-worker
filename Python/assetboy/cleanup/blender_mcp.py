from __future__ import annotations

import re
from dataclasses import dataclass


PRUNABLE_TOKENS: tuple[str, ...] = (
    "helper",
    "collision",
    "collider",
    "proxy",
    "lod",
    "camera",
    "light",
    "empty",
)

LOD_ASSET_KINDS: tuple[str, ...] = (
    "weapon",
    "prop",
    "environment",
    "architecture",
    "mesh",
)


@dataclass(frozen=True)
class ExportDecision:
    export_targets: tuple[str, ...]
    rationale: str

    def to_dict(self) -> dict[str, object]:
        return {
            "export_targets": list(self.export_targets),
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class CleanupPlan:
    pack_id: str
    asset_kind: str
    source_lane: str
    animated: bool
    steps: tuple[str, ...]
    naming_rules: tuple[str, ...]
    prune_tokens: tuple[str, ...]
    export_decision: ExportDecision

    def to_dict(self) -> dict[str, object]:
        return {
            "pack_id": self.pack_id,
            "asset_kind": self.asset_kind,
            "source_lane": self.source_lane,
            "animated": self.animated,
            "steps": list(self.steps),
            "naming_rules": list(self.naming_rules),
            "prune_tokens": list(self.prune_tokens),
            "export_decision": self.export_decision.to_dict(),
        }


def normalize_asset_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(value).strip().lower())
    cleaned = cleaned.strip("_")
    return cleaned or "asset"


def select_prunable_nodes(names: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    prunable = []
    for name in names:
        lowered = name.lower()
        if any(token in lowered for token in PRUNABLE_TOKENS):
            prunable.append(name)
    return tuple(prunable)


def decide_export_targets(asset_kind: str, *, animated: bool = False) -> ExportDecision:
    lowered_kind = asset_kind.lower()
    if animated or lowered_kind in {"character", "animation", "rig", "humanoid"}:
        return ExportDecision(
            export_targets=("fbx", "glb"),
            rationale="Animated or rigged assets should keep FBX first for skeleton fidelity, with GLB for quick review.",
        )
    if lowered_kind in {"weapon", "prop", "environment", "architecture", "mesh"}:
        return ExportDecision(
            export_targets=("glb", "fbx"),
            rationale="Static meshes review fastest as GLB, with FBX kept as the Flax-side fallback export.",
        )
    return ExportDecision(
        export_targets=("glb",),
        rationale="Default to GLB when no stronger export requirement is known.",
    )


def build_cleanup_plan(
    *,
    pack_id: str,
    asset_kind: str,
    source_lane: str,
    animated: bool = False,
) -> CleanupPlan:
    export_decision = decide_export_targets(asset_kind, animated=animated)
    steps = [
        "normalize_origin_to_grounded_pivot",
        "apply_scale_in_meters",
        "run_basic_ascii_naming_cleanup",
        "prune_helper_and_lod_meshes",
    ]
    lowered_kind = asset_kind.lower()
    if not animated and lowered_kind in LOD_ASSET_KINDS:
        steps.append("generate_lod_chain")
    steps.extend(
        (
            "capture_multi_angle_preview",
            "run_unity_mesh_validation",
        )
    )
    if animated:
        steps.append("run_unity_rig_validation")
    steps.append("choose_glb_fbx_exports")
    naming_rules = (
        "ascii_only",
        "snake_case_object_names",
        "stable_pack_prefix_on_exports",
    )
    return CleanupPlan(
        pack_id=pack_id,
        asset_kind=asset_kind,
        source_lane=source_lane,
        animated=animated,
        steps=tuple(steps),
        naming_rules=naming_rules,
        prune_tokens=PRUNABLE_TOKENS,
        export_decision=export_decision,
    )
