from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assetboy.execution.museum_runner import MUSEUM_PRESETS
from assetboy.workflows.flax_wrapper import (
    execute_get_job_status,
    execute_register_packet,
    execute_run_bulk,
    execute_run_cleanup,
)


class FlaxWrapperCommandsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.library_root = self.root / "library"
        self.state_root = self.root / "state"

        self._library_patch = patch(
            "assetboy.workflows.flax_wrapper.asset_library_root",
            return_value=self.library_root,
        )
        self._state_patch = patch(
            "assetboy.workflows.flax_wrapper.state_root",
            return_value=self.state_root,
        )
        self._lane_queue_patch = patch(
            "assetboy.providers.lanes.download_queue_csv",
            return_value=self.root / "artifacts" / "quality" / "asset-download-jobs" / "queue.csv",
        )
        self._lane_manual_patch = patch(
            "assetboy.providers.lanes.manual_drop_pack_dir",
            side_effect=lambda pack_id: self.library_root / "inbox" / "downloads" / "manual_drop" / pack_id,
        )
        self._library_patch.start()
        self._state_patch.start()
        self._lane_queue_patch.start()
        self._lane_manual_patch.start()
        self.addCleanup(self._library_patch.stop)
        self.addCleanup(self._state_patch.stop)
        self.addCleanup(self._lane_queue_patch.stop)
        self.addCleanup(self._lane_manual_patch.stop)

    def test_run_bulk_happy_path_records_expected_publish_paths(self) -> None:
        payload = execute_run_bulk(
            profile="quaternius_presets",
            game_scope="shared",
            pack_ids=["SHARED_QUAT_ULTIMATE_WEAPONS_01"],
            output_dir=self.root / "bulk",
            dry_run=True,
            job_id="bulk_ok",
        )

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["profile"], "quaternius_presets")
        self.assertEqual(payload["lane"], "direct_url")
        self.assertEqual(payload["pack_ids"], ["SHARED_QUAT_ULTIMATE_WEAPONS_01"])
        self.assertEqual(payload["artifact_count"], 1)
        self.assertIn(
            str(self.library_root / "publish" / "flax_intake" / "shared" / "SHARED_QUAT_ULTIMATE_WEAPONS_01"),
            payload["expected_publish_paths"],
        )
        self.assertEqual(
            payload["expected_destination_paths"],
            [str(self.root / "artifacts" / "quality" / "asset-download-jobs" / "queue.csv")],
        )

        job_status = execute_get_job_status(job_id="bulk_ok")
        self.assertEqual(job_status["status"], "completed")
        self.assertEqual(job_status["job_id"], "bulk_ok")

    def test_run_cleanup_fails_cleanly_when_input_dir_missing(self) -> None:
        payload = execute_run_cleanup(
            pack_id="RA_PACK_TEST",
            input_dir=self.root / "missing_cleanup_input",
            game_scope="roman_arena",
            dry_run=False,
            job_id="cleanup_fail",
        )

        self.assertEqual(payload["status"], "failed")
        self.assertIn("Cleanup input_dir not found", payload["error"])

        job_status = execute_get_job_status(job_id="cleanup_fail")
        self.assertEqual(job_status["status"], "failed")
        self.assertEqual(job_status["job_id"], "cleanup_fail")

    def test_register_packet_fails_when_provenance_missing(self) -> None:
        source_dir = self.root / "source_missing_provenance"
        source_dir.mkdir(parents=True)
        (source_dir / "mesh.glb").write_bytes(b"mesh")

        payload = execute_register_packet(
            pack_id="RA_PACK_TEST",
            game_scope="roman_arena",
            source_dir=source_dir,
        )

        self.assertEqual(payload["status"], "failed")
        self.assertIn("provenance.json not found", payload["error"])

    def test_register_packet_fails_when_payload_has_no_supported_files(self) -> None:
        source_dir = self.root / "source_missing_payload"
        source_dir.mkdir(parents=True)
        (source_dir / "provenance.json").write_text(
            '{"lane":"direct_url","source_url":"https://example.com","license":"CC0","author":"tester"}',
            encoding="utf-8",
        )
        (source_dir / "notes.txt").write_text("not an importable asset", encoding="utf-8")

        payload = execute_register_packet(
            pack_id="RA_PACK_EMPTY",
            game_scope="roman_arena",
            source_dir=source_dir,
        )

        self.assertEqual(payload["status"], "failed")
        self.assertIn("No supported payload files found", payload["error"])

    def test_register_packet_rejects_malformed_provenance_json_with_actionable_message(self) -> None:
        source_dir = self.root / "source_malformed_provenance"
        source_dir.mkdir(parents=True)
        (source_dir / "provenance.json").write_text(
            '{"lane":"direct_url","source_adapter":"direct_url_queue",',
            encoding="utf-8",
        )
        (source_dir / "mesh.glb").write_bytes(b"mesh")

        payload = execute_register_packet(
            pack_id="RA_PACK_MALFORMED",
            game_scope="roman_arena",
            source_dir=source_dir,
        )

        self.assertEqual(payload["status"], "failed")
        self.assertIn("provenance.json is malformed JSON", payload["error"])

    def test_register_packet_writes_publish_contract(self) -> None:
        source_dir = self.root / "source_ok"
        source_dir.mkdir(parents=True)
        (source_dir / "provenance.json").write_text(
            (
                "{"
                "\"lane\":\"direct_url\","
                "\"source_adapter\":\"direct_url_queue\","
                "\"source_url\":\"https://example.com/pack\","
                "\"license\":\"CC0\","
                "\"license_snapshot\":\"Captured from the source page.\","
                "\"author\":\"tester\","
                "\"acquired_at\":\"2026-03-23T12:00:00Z\","
                "\"downloaded_filename\":\"mesh.glb\""
                "}"
            ),
            encoding="utf-8",
        )
        (source_dir / "mesh.glb").write_bytes(b"mesh")

        payload = execute_register_packet(
            pack_id="RA_PACK_OK",
            game_scope="roman_arena",
            source_dir=source_dir,
        )

        self.assertEqual(payload["status"], "completed")
        packet_path = self.library_root / "publish" / "flax_intake" / "roman_arena" / "RA_PACK_OK" / "packet.json"
        provenance_path = self.library_root / "publish" / "flax_intake" / "roman_arena" / "RA_PACK_OK" / "provenance.json"
        self.assertTrue(packet_path.exists())
        self.assertTrue(provenance_path.exists())
        self.assertEqual(payload["lane"], "direct_url")
        self.assertEqual(
            payload["payload_target_path"],
            str(self.library_root / "publish" / "flax_intake" / "roman_arena" / "RA_PACK_OK" / "payload"),
        )
        written_packet = json.loads(packet_path.read_text(encoding="utf-8"))
        written_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        self.assertEqual(written_packet["lane"], "direct_url")
        self.assertEqual(written_provenance["author_or_vendor"], "tester")
        self.assertNotIn("author", written_provenance)
        self.assertEqual(
            written_provenance["payload_target_path"],
            str(self.library_root / "publish" / "flax_intake" / "roman_arena" / "RA_PACK_OK" / "payload"),
        )

    def test_register_packet_canonicalizes_legacy_source_adapter_alias_before_write(self) -> None:
        source_dir = self.root / "source_alias_adapter"
        source_dir.mkdir(parents=True)
        (source_dir / "provenance.json").write_text(
            (
                "{"
                "\"lane\":\"manual_browser\","
                "\"source_adapter\":\"unity_asset_store_manual\","
                "\"source_url\":\"https://assetstore.unity.com/packages/example\","
                "\"license\":\"Unity Asset Store EULA\","
                "\"license_snapshot\":\"Fixture store-gated license.\","
                "\"author\":\"tester\","
                "\"acquired_at\":\"2026-03-23T12:00:00Z\","
                "\"downloaded_filename\":\"mesh.glb\","
                "\"entitlement_note\":\"Owned package for fixture test.\""
                "}"
            ),
            encoding="utf-8",
        )
        (source_dir / "mesh.glb").write_bytes(b"mesh")

        payload = execute_register_packet(
            pack_id="RA_PACK_ALIAS",
            game_scope="roman_arena",
            source_dir=source_dir,
        )

        self.assertEqual(payload["status"], "completed")
        provenance_path = self.library_root / "publish" / "flax_intake" / "roman_arena" / "RA_PACK_ALIAS" / "provenance.json"
        written_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        self.assertEqual(written_provenance["source_adapter"], "unity_asset_store")
        self.assertEqual(written_provenance["lane"], "manual_browser")

    def test_run_bulk_manual_browser_profile_uses_pack_scoped_destination(self) -> None:
        pack_id = MUSEUM_PRESETS[0][0]
        payload = execute_run_bulk(
            profile="museum_presets",
            game_scope="roman_arena",
            pack_ids=[pack_id],
            output_dir=self.root / "bulk_manual",
            dry_run=True,
            job_id="bulk_manual",
        )

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["lane"], "manual_browser")
        self.assertIn(
            str(self.library_root / "inbox" / "downloads" / "manual_drop" / pack_id),
            payload["expected_destination_paths"],
        )

    def test_run_bulk_continue_on_error_records_pack_failure_and_completes(self) -> None:
        with patch(
            "assetboy.workflows.flax_wrapper.run_quaternius_batch",
            side_effect=ValueError("manual archive pin required"),
        ):
            payload = execute_run_bulk(
                profile="quaternius_presets",
                game_scope="shared",
                pack_ids=["SHARED_QUAT_ULTIMATE_WEAPONS_01"],
                output_dir=self.root / "bulk_partial",
                dry_run=False,
                continue_on_error=True,
            )

        self.assertEqual(payload["status"], "completed")
        self.assertTrue(payload["continue_on_error"])
        self.assertEqual(payload["failed_artifact_count"], 1)
        self.assertEqual(payload["successful_artifact_count"], 0)
        self.assertEqual(payload["artifact_count"], 1)
        self.assertEqual(payload["artifacts"][0]["status"], "failed")
        self.assertIn("manual archive pin required", payload["artifacts"][0]["error"])

    def test_run_bulk_pack_id_filters_multiple_kenney_results(self) -> None:
        payload = execute_run_bulk(
            profile="kenney_presets",
            game_scope="shared",
            pack_ids=[
                "SHARED_KENNEY_SCIFI_CHARACTERS_01",
                "SHARED_KENNEY_RPG_CHARACTERS_01",
            ],
            output_dir=self.root / "bulk_multi",
            dry_run=True,
        )

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["artifact_count"], 2)
        self.assertEqual(
            payload["pack_ids"],
            ["SHARED_KENNEY_RPG_CHARACTERS_01", "SHARED_KENNEY_SCIFI_CHARACTERS_01"],
        )

    def test_register_packet_rejects_unknown_source_adapter_lane_contract(self) -> None:
        source_dir = self.root / "source_bad_lane"
        source_dir.mkdir(parents=True)
        (source_dir / "provenance.json").write_text(
            (
                "{"
                "\"lane\":\"direct_url\","
                "\"source_adapter\":\"fab\","
                "\"source_url\":\"https://example.com/pack\","
                "\"license\":\"CC0\","
                "\"license_snapshot\":\"Captured from the source page.\","
                "\"author\":\"tester\","
                "\"acquired_at\":\"2026-03-23T12:00:00Z\","
                "\"downloaded_filename\":\"mesh.glb\""
                "}"
            ),
            encoding="utf-8",
        )
        (source_dir / "mesh.glb").write_bytes(b"mesh")

        payload = execute_register_packet(
            pack_id="RA_PACK_BAD",
            game_scope="roman_arena",
            source_dir=source_dir,
        )

        self.assertEqual(payload["status"], "failed")
        self.assertIn("does not match source_adapter", payload["error"])
