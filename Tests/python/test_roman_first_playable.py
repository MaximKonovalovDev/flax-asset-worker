from pathlib import Path
from tempfile import TemporaryDirectory
import os
import unittest
from unittest.mock import patch

from assetboy.workflows.roman_first_playable import (
    audit_roman_first_playable,
    get_roman_pack_spec,
    roman_first_playable_pack_ids,
)
from tests.helpers import write_publish_pack, write_roman_first_playable_fixture


class RomanFirstPlayableAuditTests(unittest.TestCase):
    def test_combat_slice_followups_are_registered_for_cleanup_defaults(self) -> None:
        pack_ids = set(roman_first_playable_pack_ids())
        self.assertNotIn("RA_PACK_COMBAT_PREP_SLICE_01", pack_ids)
        self.assertNotIn("RA_PACK_COMBAT_PREP_SLICE_02", pack_ids)
        self.assertNotIn("RA_PACK_ANM_COMBAT_SLICE_02", pack_ids)

        combat_prep = get_roman_pack_spec("RA_PACK_COMBAT_PREP_SLICE_02")
        self.assertEqual(combat_prep.asset_kind, "character")
        self.assertTrue(combat_prep.animated)

        combat_anim = get_roman_pack_spec("RA_PACK_ANM_COMBAT_SLICE_02")
        self.assertEqual(combat_anim.asset_kind, "animation")
        self.assertTrue(combat_anim.animated)

    def test_reviewed_real_pack_is_marked_usable(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root, _, _ = write_roman_first_playable_fixture(temp_dir)
            write_publish_pack(
                repo_root,
                "RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01",
                payload_files=[
                    "arena_sandstone_bowl.glb",
                    "arena_wall_curved.glb",
                    "arena_gate_arch.glb",
                    "arena_stair.glb",
                    "arena_tunnel_spawn.glb",
                    "arena_column_broken.glb",
                    "arena_banner_set.png",
                    "arena_urn_cluster.glb",
                ],
                packet=True,
                provenance=True,
                imported=True,
            )
            with patch.dict(os.environ, {"ASSETBOY_FLAX_REPO_ROOT": str(repo_root)}, clear=False):
                audits = {audit.pack_id: audit for audit in audit_roman_first_playable()}

            environment = audits["RA_PACK_ENV_SANDSTONE_BOWL_SLICE_01"]
            self.assertEqual(environment.audit_status, "reviewed_real")
            self.assertEqual(environment.maturity_label, "usable_with_manual_steps")
            self.assertTrue(environment.ready_for_flax_packet)

    def test_payload_only_stub_is_marked_experimental(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root, _, _ = write_roman_first_playable_fixture(temp_dir)
            with patch.dict(os.environ, {"ASSETBOY_FLAX_REPO_ROOT": str(repo_root)}, clear=False):
                audits = {audit.pack_id: audit for audit in audit_roman_first_playable()}

            skirmisher = audits["RA_PACK_CHR_SKIRMISHER_SLICE_01"]
            self.assertEqual(skirmisher.audit_status, "payload_only_stub")
            self.assertEqual(skirmisher.maturity_label, "experimental")
            self.assertFalse(skirmisher.ready_for_flax_packet)

    def test_reviewed_but_thin_pack_stays_experimental(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root, _, _ = write_roman_first_playable_fixture(temp_dir)
            with patch.dict(os.environ, {"ASSETBOY_FLAX_REPO_ROOT": str(repo_root)}, clear=False):
                audits = {audit.pack_id: audit for audit in audit_roman_first_playable()}

            weapons = audits["RA_PACK_WPN_COMBAT_SLICE_01"]
            self.assertEqual(weapons.audit_status, "reviewed_but_content_thin")
            self.assertEqual(weapons.maturity_label, "experimental")
            self.assertIn("RA_PACK_WPN_COMBAT_SLICE_01_mock.glb", weapons.mock_files)

    def test_audit_reads_actual_provenance_adapter(self) -> None:
        with TemporaryDirectory() as temp_dir:
            repo_root, _, _ = write_roman_first_playable_fixture(temp_dir)
            provenance_path = (
                Path(repo_root)
                / "artifacts"
                / "library"
                / "FlaxAssetLibrary"
                / "publish"
                / "flax_intake"
                / "roman_arena"
                / "RA_PACK_CHR_SKIRMISHER_SLICE_01"
                / "provenance.json"
            )
            provenance_path.parent.mkdir(parents=True, exist_ok=True)
            provenance_path.write_text(
                '{"lane":"manual_browser","source_adapter":"mixamo"}',
                encoding="utf-8",
            )
            packet_path = provenance_path.parent / "packet.json"
            packet_path.write_text('{"pack_id":"RA_PACK_CHR_SKIRMISHER_SLICE_01","game_scope":"roman_arena","packet_status":"reviewed"}', encoding="utf-8")
            with patch.dict(os.environ, {"ASSETBOY_FLAX_REPO_ROOT": str(repo_root)}, clear=False):
                audits = {audit.pack_id: audit for audit in audit_roman_first_playable()}

            skirmisher = audits["RA_PACK_CHR_SKIRMISHER_SLICE_01"]
            self.assertEqual(skirmisher.actual_lane, "manual_browser")
            self.assertEqual(skirmisher.actual_source_adapter, "mixamo")


if __name__ == "__main__":
    unittest.main()
