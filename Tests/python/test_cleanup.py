import unittest

from assetboy.cleanup.blender_mcp import (
    build_cleanup_plan,
    decide_export_targets,
    normalize_asset_name,
    select_prunable_nodes,
)


class CleanupTests(unittest.TestCase):
    def test_normalize_asset_name_returns_ascii_slug(self) -> None:
        self.assertEqual(normalize_asset_name(" Roman Gladius #1 "), "roman_gladius_1")

    def test_select_prunable_nodes_filters_helpers(self) -> None:
        prunable = select_prunable_nodes(["Sword", "Sword_LOD1", "SceneCamera", "Handle_Helper"])
        self.assertEqual(prunable, ("Sword_LOD1", "SceneCamera", "Handle_Helper"))

    def test_export_decision_prefers_fbx_for_animation(self) -> None:
        decision = decide_export_targets("animation", animated=True)
        self.assertEqual(decision.export_targets, ("fbx", "glb"))

    def test_build_cleanup_plan_keeps_required_steps(self) -> None:
        plan = build_cleanup_plan(
            pack_id="RA_PACK_WPN_COMBAT_SLICE_01",
            asset_kind="weapon",
            source_lane="generator",
        )
        self.assertIn("normalize_origin_to_grounded_pivot", plan.steps)
        self.assertIn("choose_glb_fbx_exports", plan.steps)
