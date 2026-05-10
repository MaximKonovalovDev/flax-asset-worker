from pathlib import Path
from tempfile import TemporaryDirectory
import csv
import unittest

from assetboy.providers.direct_url import (
    DirectUrlQueueRequest,
    append_queue_requests,
    build_queue_template_rows,
)
from assetboy.providers.lanes import ProviderLane, adapters_for_lane
from assetboy.providers.manual_browser import ManualBrowserSite, build_manual_browser_request


class ProviderBridgeTests(unittest.TestCase):
    def test_manual_lane_has_required_adapters(self) -> None:
        manual_ids = {adapter.adapter_id for adapter in adapters_for_lane(ProviderLane.MANUAL_BROWSER)}
        self.assertTrue(
            {"fab", "fab_auto_claim", "free_games_claimer", "unity_asset_store", "mixamo", "museum_page", "unity_engine_bridge", "unreal_engine_bridge", "uevaultmanager", "epic_dummy_project", "cue4parse"}.issubset(
                manual_ids
            )
        )

    def test_build_queue_template_rows_matches_required_count(self) -> None:
        rows = build_queue_template_rows(
            pack_id="RA_PACK_AUD_SFX_COMBAT_SLICE_01",
            game_scope="roman_arena",
            request_count=3,
            notes="sfx blocker",
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["pack_id"], "RA_PACK_AUD_SFX_COMBAT_SLICE_01")
        self.assertEqual(rows[0]["lane"], "direct_url")

    def test_append_queue_requests_writes_contract_header(self) -> None:
        with TemporaryDirectory() as temp_dir:
            queue_path = Path(temp_dir) / "queue.csv"
            append_queue_requests(
                [
                    DirectUrlQueueRequest(
                        pack_id="RA_PACK_UI_COMBAT_SLICE_01",
                        game_scope="roman_arena",
                        url="https://example.com/hud.png",
                        notes="hud texture",
                    )
                ],
                path=queue_path,
            )
            with queue_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["lane"], "direct_url")
            self.assertEqual(rows[0]["pack_id"], "RA_PACK_UI_COMBAT_SLICE_01")

    def test_manual_browser_request_targets_pack_subfolder(self) -> None:
        request = build_manual_browser_request(
            pack_id="RA_PACK_CHR_PLAYER_SLICE_01",
            game_scope="roman_arena",
            site=ManualBrowserSite.MIXAMO,
            search_terms=("roman gladiator", "player body"),
        )
        self.assertTrue(str(request.destination).endswith(r"manual_drop\RA_PACK_CHR_PLAYER_SLICE_01"))
