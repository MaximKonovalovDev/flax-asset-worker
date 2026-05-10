from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from assetboy.providers.lanes import (
    canonical_lane_value,
    canonical_source_adapter_id,
    rank_generator_adapters,
    require_source_adapter,
    resolve_lane_destination,
)


class LaneContractTests(unittest.TestCase):
    def test_canonical_lane_value_normalizes_known_aliases(self) -> None:
        self.assertEqual(canonical_lane_value("manual-browser"), "manual_browser")
        self.assertEqual(canonical_lane_value("direct-url"), "direct_url")
        self.assertEqual(canonical_lane_value("gen"), "generator")

    def test_resolve_lane_destination_requires_pack_scoped_manual_drop(self) -> None:
        with patch(
            "assetboy.providers.lanes.manual_drop_pack_dir",
            side_effect=lambda pack_id: Path("C:/temp/manual_drop") / pack_id,
        ):
            destination = resolve_lane_destination("manual_browser", pack_id="RA_PACK_TEST")
        self.assertEqual(destination, Path("C:/temp/manual_drop") / "RA_PACK_TEST")

    def test_require_source_adapter_rejects_unknown_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported source_adapter"):
            require_source_adapter("totally_unknown_adapter")

    def test_require_source_adapter_accepts_registered_contract_ids(self) -> None:
        self.assertEqual(require_source_adapter("font_direct_url").lane.value, "direct_url")
        self.assertEqual(require_source_adapter("mixamo_manual_browser").lane.value, "manual_browser")
        self.assertEqual(require_source_adapter("roman_manual_source").lane.value, "manual_browser")
        self.assertEqual(require_source_adapter("mixamo_animations").lane.value, "manual_browser")
        self.assertEqual(require_source_adapter("step1x3d").lane.value, "generator")
        self.assertEqual(require_source_adapter("topiaxl").lane.value, "generator")

    def test_canonical_source_adapter_id_normalizes_legacy_aliases(self) -> None:
        self.assertEqual(canonical_source_adapter_id("unity_asset_store_manual"), "unity_asset_store")
        self.assertEqual(canonical_source_adapter_id("UNITY-ASSET-STORE"), "unity_asset_store")

    def test_require_source_adapter_normalizes_legacy_aliases(self) -> None:
        adapter = require_source_adapter("unity_asset_store_manual")
        self.assertEqual(adapter.adapter_id, "unity_asset_store")
        self.assertEqual(adapter.lane.value, "manual_browser")

    def test_rank_generator_adapters_uses_objective_matrix(self) -> None:
        open_ranked = [item.adapter_id for item in rank_generator_adapters("open_experiment")]
        text_ranked = [item.adapter_id for item in rank_generator_adapters("text_first")]
        self.assertEqual(open_ranked[0], "step1x3d")
        self.assertEqual(text_ranked[0], "topiaxl")
