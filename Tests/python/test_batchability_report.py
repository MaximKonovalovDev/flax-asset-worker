import unittest

from assetboy.providers.bridge_registry import (
    AssetCategory,
    BatchabilityBand,
    bridge_batchability_band,
    category_batchability,
)


class BatchabilityReportTests(unittest.TestCase):
    def test_direct_download_bridge_is_batchable_now(self) -> None:
        self.assertEqual(bridge_batchability_band("ambientcg"), BatchabilityBand.BATCHABLE_NOW)

    def test_playwright_bridge_is_batchable_with_manual_steps(self) -> None:
        self.assertEqual(
            bridge_batchability_band("mixamo_browser"),
            BatchabilityBand.BATCHABLE_WITH_MANUAL_STEPS,
        )

    def test_prop_category_best_route_uses_batchable_fallback(self) -> None:
        report = category_batchability(AssetCategory.PROP)
        self.assertEqual(report.primary_bridge_id, "kenney")
        self.assertEqual(report.primary_status, BatchabilityBand.BATCHABLE_NOW)
        self.assertEqual(report.best_bridge_id, "kenney")
        self.assertEqual(report.best_status, BatchabilityBand.BATCHABLE_NOW)

    def test_shader_category_remains_manual_gap_fill(self) -> None:
        report = category_batchability(AssetCategory.SHADER)
        self.assertEqual(report.primary_bridge_id, "shader_manual")
        self.assertEqual(report.best_status, BatchabilityBand.MANUAL_GAP_FILL)
