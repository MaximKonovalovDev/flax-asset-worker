"""Provider lane helpers for AssetBoy.

Path B s2.6b (2026-05-11): dropped re-exports of DEAD modules ``ai_bridge``
and ``runbooks``. Their public functions are intentionally NOT exposed at the
package level anymore. Code that still needs ``AI_PROVIDER_PROFILES`` or
``provider_runbook_ids`` should read ``assetboy/data/provider_profiles.yaml``
directly (see ``provider_readiness._load_parked_provider_profiles`` for the
pattern). The two DEAD modules are scheduled for deletion in s2.6d.
"""

from assetboy.providers.browser_automation import BrowserRuntime, emit_browser_automation_job
from assetboy.providers.bridge_registry import AssetCategory, BridgeFamily, get_bridge, get_category_route, list_bridges
from assetboy.providers.cue4parse_bridge import emit_cue4parse_job
from assetboy.providers.engine_bridge import EngineBridgeKind, emit_engine_export_job
from assetboy.providers.epic_vault import emit_epic_dummy_project_job, emit_uevaultmanager_job
from assetboy.providers.extractor_bridge import ExtractorTool, emit_extractor_job
from assetboy.providers.legendary_bridge import (
    build_legendary_status_report,
    import_legendary_auth,
    install_legendary_asset,
    list_legendary_ue_assets,
)
from assetboy.providers.lanes import (
    LANE_POLICIES,
    AcquisitionMethod,  # canonical alias; same enum as ProviderLane
    ProviderLane,
    SourceAdapter,
    adapters_for_lane,
)
from assetboy.providers.marketplace_ops import ClaimMethod, emit_marketplace_claim_job
from assetboy.providers.provider_readiness import build_provider_readiness_report, render_provider_readiness_report
from assetboy.providers.unity_runner import emit_unity_export_runner, list_unity_installations
from assetboy.providers.unreal_runner import emit_unreal_export_runner, list_unreal_installations

__all__ = [
    "AcquisitionMethod",  # canonical name (alias of ProviderLane)
    "ProviderLane",
    "SourceAdapter",
    "LANE_POLICIES",
    "adapters_for_lane",
    "AssetCategory",
    "BridgeFamily",
    "get_bridge",
    "get_category_route",
    "list_bridges",
    "BrowserRuntime",
    "emit_browser_automation_job",
    "ClaimMethod",
    "emit_marketplace_claim_job",
    "build_provider_readiness_report",
    "render_provider_readiness_report",
    "EngineBridgeKind",
    "emit_engine_export_job",
    "emit_uevaultmanager_job",
    "emit_epic_dummy_project_job",
    "emit_cue4parse_job",
    "ExtractorTool",
    "emit_extractor_job",
    "build_legendary_status_report",
    "import_legendary_auth",
    "list_legendary_ue_assets",
    "install_legendary_asset",
    "emit_unity_export_runner",
    "list_unity_installations",
    "emit_unreal_export_runner",
    "list_unreal_installations",
]
