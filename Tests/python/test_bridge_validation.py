from __future__ import annotations

import unittest
from pathlib import Path

from assetboy.providers.bridge_registry import (
    AssetCategory,
    get_category_route,
    list_bridges,
    recommended_skill_ids_for_bridge,
    recommended_skill_ids_for_category,
    skill_doc_path,
    validate_bridge_registry,
)


class BridgeValidationTests(unittest.TestCase):
    def test_bridge_registry_validates_cleanly(self) -> None:
        self.assertEqual(validate_bridge_registry(), ())

    def test_every_asset_category_has_a_route(self) -> None:
        for category in AssetCategory:
            route = get_category_route(category)
            self.assertTrue(route.primary_bridge_id)

    def test_full_sprint_categories_have_expected_primary_bridges(self) -> None:
        expectations = {
            AssetCategory.WEAPON: "kenney",
            AssetCategory.PROP: "kenney",
            AssetCategory.ARCHITECTURE: "kenney",
            AssetCategory.VEHICLE: "kenney_vehicle",
            AssetCategory.TERRAIN: "ambientcg",
            AssetCategory.ICON: "game_icons_net",
            AssetCategory.VFX: "kenney_vfx",
            AssetCategory.FONT: "google_fonts",
            AssetCategory.SKYBOX: "poly_haven",
            AssetCategory.DIALOGUE: "edge_tts_dialogue",
            AssetCategory.SHADER: "shader_manual",
        }
        for category, primary_bridge_id in expectations.items():
            self.assertEqual(get_category_route(category).primary_bridge_id, primary_bridge_id)

    def test_recommended_skill_docs_exist_for_bridges_and_categories(self) -> None:
        for category in AssetCategory:
            for skill_id in recommended_skill_ids_for_category(category):
                self.assertTrue(Path(skill_doc_path(skill_id)).exists(), skill_id)

        for bridge in list_bridges():
            for skill_id in recommended_skill_ids_for_bridge(bridge.bridge_id):
                self.assertTrue(Path(skill_doc_path(skill_id)).exists(), skill_id)


if __name__ == "__main__":
    unittest.main()
