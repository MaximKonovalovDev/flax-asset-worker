import unittest

from assetboy.providers.bridge_registry import AssetCategory, get_bridge, get_category_route, list_bridges


class BridgeRegistryTests(unittest.TestCase):
    def test_registry_contains_key_bridge_families(self) -> None:
        bridge_ids = {bridge.bridge_id for bridge in list_bridges()}
        self.assertTrue(
            {
                "chatgpt_pro_ui",
                "mixamo_browser",
                "hunyuan3d2_3d",
                "unity_engine_bridge",
                "asset_ripper_extract",
                "mixkit_audio",
                "fab_uevaultmanager",
                "fab_auto_claim_bridge",
                "cue4parse_extract",
            }.issubset(bridge_ids)
        )

    def test_ui_category_prefers_chatgpt_pro(self) -> None:
        route = get_category_route(AssetCategory.UI_HUD)
        self.assertEqual(route.primary_bridge_id, "chatgpt_pro_ui")
        self.assertIn("comfyui_local_ui", route.fallback_bridge_ids)

    def test_bridge_lookup_returns_expected_lane(self) -> None:
        bridge = get_bridge("unity_engine_bridge")
        self.assertEqual(bridge.lane.value, "manual_browser")
