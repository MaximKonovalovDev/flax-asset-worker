"""Provider lane helpers for AssetBoy.

Phase 1D (2026-06-05): removed all dead non-Flax provider wrappers
(Unity, Unreal, Epic/Fab, Mixamo, Quixel, CUE4Parse, browser_automation,
blender). Only surviving modules: bridge_registry, lanes, direct_url,
auth_freshness.
"""

from assetboy.providers.bridge_registry import AssetCategory, BridgeFamily, get_bridge, get_category_route, list_bridges
from assetboy.providers.lanes import (
    LANE_POLICIES,
    AcquisitionMethod,
    ProviderLane,
    SourceAdapter,
    adapters_for_lane,
)

__all__ = [
    "AcquisitionMethod",
    "ProviderLane",
    "SourceAdapter",
    "LANE_POLICIES",
    "adapters_for_lane",
    "AssetCategory",
    "BridgeFamily",
    "get_bridge",
    "get_category_route",
    "list_bridges",
]
