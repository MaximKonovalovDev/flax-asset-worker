from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assetboy.workflows.pack_pipeline import execute_prepare_pack, read_pack_pipeline_status


class PackPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.library_root = self.root / "library"
        self.state_root = self.root / "state"

        self._patches = [
            patch("assetboy.workflows.pack_pipeline.asset_library_root", return_value=self.library_root),
            patch("assetboy.workflows.pack_pipeline.state_root", return_value=self.state_root),
            patch("assetboy.workflows.flax_wrapper.asset_library_root", return_value=self.library_root),
            patch("assetboy.workflows.flax_wrapper.state_root", return_value=self.state_root),
        ]
        for current in self._patches:
            current.start()
            self.addCleanup(current.stop)

    def _make_source_dir(self, name: str, *, payload_name: str, payload_bytes: bytes) -> Path:
        source_dir = self.root / name
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
                "\"downloaded_filename\":\""
                + payload_name
                + "\""
                "}"
            ),
            encoding="utf-8",
        )
        (source_dir / payload_name).write_bytes(payload_bytes)
        return source_dir

    def test_prepare_pack_registers_non_mesh_source_without_cleanup(self) -> None:
        source_dir = self._make_source_dir("source_ui", payload_name="icon.png", payload_bytes=b"png")

        payload = execute_prepare_pack(
            pack_id="RA_PACK_UI_READY",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="auto",
        )

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["current_state"], "packeted")
        self.assertTrue(payload["ready_for_flax_intake"])
        packet_path = self.library_root / "publish" / "flax_intake" / "roman_arena" / "RA_PACK_UI_READY" / "packet.json"
        self.assertTrue(packet_path.exists())

    def test_prepare_pack_mesh_source_waits_for_cleanup_artifacts(self) -> None:
        source_dir = self._make_source_dir("source_mesh", payload_name="mesh.glb", payload_bytes=b"mesh")

        payload = execute_prepare_pack(
            pack_id="RA_PACK_MESH_WAIT",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="auto",
        )

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["current_state"], "awaiting_cleanup_artifacts")
        self.assertIn("rerun prepare-pack with --resume", payload["next_step"])
        self.assertIn("cleanup", payload["stages"])
        self.assertNotIn("register_packet", payload["stages"])

    def test_prepare_pack_resume_promotes_existing_cleanup_artifacts(self) -> None:
        source_dir = self._make_source_dir("source_mesh_resume", payload_name="mesh.glb", payload_bytes=b"mesh")

        first_pass = execute_prepare_pack(
            pack_id="RA_PACK_MESH_RESUME",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="auto",
        )
        self.assertEqual(first_pass["current_state"], "awaiting_cleanup_artifacts")

        artifact_paths = [Path(item) for item in first_pass["stages"]["cleanup"]["artifact_paths"]]
        for artifact_path in artifact_paths:
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(b"cleaned")

        resumed = execute_prepare_pack(
            pack_id="RA_PACK_MESH_RESUME",
            game_scope="roman_arena",
            resume=True,
        )

        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["current_state"], "packeted")
        self.assertTrue(resumed["ready_for_flax_intake"])
        self.assertIn("register_packet", resumed["stages"])

    def test_pack_status_reports_persistent_packeted_state(self) -> None:
        source_dir = self._make_source_dir("source_status", payload_name="icon.png", payload_bytes=b"png")
        execute_prepare_pack(
            pack_id="RA_PACK_STATUS",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="skip",
        )

        status = read_pack_pipeline_status(
            pack_id="RA_PACK_STATUS",
            game_scope="roman_arena",
        )

        self.assertEqual(status["current_state"], "packeted")
        self.assertTrue(status["ready_for_flax_intake"])
        self.assertTrue(str(status["ledger_path"]).endswith("RA_PACK_STATUS.json"))

    def test_pack_status_heals_stale_failed_ledger_when_packet_exists(self) -> None:
        source_dir = self._make_source_dir("source_heal", payload_name="icon.png", payload_bytes=b"png")
        execute_prepare_pack(
            pack_id="RA_PACK_HEAL",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="skip",
        )

        ledger_path = self.state_root / "pack_pipeline" / "roman_arena" / "RA_PACK_HEAL.json"
        stale = ledger_path.read_text(encoding="utf-8")
        stale = stale.replace('"status": "completed"', '"status": "failed"')
        stale = stale.replace('"current_state": "packeted"', '"current_state": "failed"')
        stale = stale.replace('"ready_for_flax_intake": true', '"ready_for_flax_intake": false')
        stale = stale[:-2] + ',\n  "error": "stale failure"\n}'
        ledger_path.write_text(stale, encoding="utf-8")

        status = read_pack_pipeline_status(
            pack_id="RA_PACK_HEAL",
            game_scope="roman_arena",
        )

        self.assertEqual(status["status"], "completed")
        self.assertEqual(status["current_state"], "packeted")
        self.assertTrue(status["ready_for_flax_intake"])
        self.assertNotIn("error", status)

        healed = ledger_path.read_text(encoding="utf-8")
        self.assertIn('"status": "completed"', healed)
        self.assertIn('"current_state": "packeted"', healed)
        self.assertNotIn('"error"', healed)

    def test_prepare_pack_resume_keeps_packeted_pack_green_without_source_dir(self) -> None:
        source_dir = self._make_source_dir("source_packeted_resume", payload_name="icon.png", payload_bytes=b"png")
        execute_prepare_pack(
            pack_id="RA_PACK_PACKETED_RESUME",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="skip",
        )

        reviewed_source_dir = self.state_root / "prepared_sources" / "roman_arena" / "RA_PACK_PACKETED_RESUME"
        if reviewed_source_dir.exists():
            for file_path in sorted(reviewed_source_dir.rglob("*"), reverse=True):
                if file_path.is_file():
                    file_path.unlink()
                else:
                    file_path.rmdir()
            reviewed_source_dir.rmdir()
        for file_path in sorted(source_dir.rglob("*"), reverse=True):
            if file_path.is_file():
                file_path.unlink()
            else:
                file_path.rmdir()
        source_dir.rmdir()

        resumed = execute_prepare_pack(
            pack_id="RA_PACK_PACKETED_RESUME",
            game_scope="roman_arena",
            resume=True,
        )

        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["current_state"], "packeted")
        self.assertTrue(resumed["ready_for_flax_intake"])
        self.assertNotIn("error", resumed)

    def test_prepare_pack_refreshes_reviewed_source_on_non_resume_rerun(self) -> None:
        source_dir = self._make_source_dir("source_refresh", payload_name="icon.png", payload_bytes=b"first")

        execute_prepare_pack(
            pack_id="RA_PACK_REFRESH",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="skip",
        )

        (source_dir / "icon.png").write_bytes(b"second")

        rerun = execute_prepare_pack(
            pack_id="RA_PACK_REFRESH",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="skip",
            overwrite_packet=True,
        )

        reviewed_payload = self.state_root / "prepared_sources" / "roman_arena" / "RA_PACK_REFRESH" / "payload" / "icon.png"
        published_payload = self.library_root / "publish" / "flax_intake" / "roman_arena" / "RA_PACK_REFRESH" / "payload" / "icon.png"

        self.assertEqual(rerun["current_state"], "packeted")
        self.assertEqual(reviewed_payload.read_bytes(), b"second")
        self.assertEqual(published_payload.read_bytes(), b"second")

    def test_prepare_pack_clears_stale_error_and_refreshes_lane_on_successful_rerun(self) -> None:
        source_dir = self._make_source_dir("source_retry", payload_name="icon.png", payload_bytes=b"png")
        provenance_path = source_dir / "provenance.json"
        provenance_text = provenance_path.read_text(encoding="utf-8")
        provenance_path.unlink()

        failed = execute_prepare_pack(
            pack_id="RA_PACK_RETRY",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="skip",
        )
        self.assertEqual(failed["current_state"], "failed")
        self.assertIn("provenance.json not found", failed["error"])

        updated_text = provenance_text.replace("\"lane\":\"direct_url\"", "\"lane\":\"manual_browser\"")
        updated_text = updated_text.replace("\"source_adapter\":\"direct_url_queue\"", "\"source_adapter\":\"mixamo_manual_browser\"")
        provenance_path.write_text(updated_text, encoding="utf-8")

        rerun = execute_prepare_pack(
            pack_id="RA_PACK_RETRY",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="skip",
            overwrite_packet=True,
        )

        self.assertEqual(rerun["current_state"], "packeted")
        self.assertEqual(rerun["source_lane"], "manual_browser")
        self.assertNotIn("error", rerun)

    def test_prepare_pack_fails_with_actionable_error_for_malformed_source_provenance(self) -> None:
        source_dir = self.root / "source_bad_json"
        source_dir.mkdir(parents=True)
        (source_dir / "provenance.json").write_text(
            '{"lane":"direct_url","source_adapter":"direct_url_queue",',
            encoding="utf-8",
        )
        (source_dir / "icon.png").write_bytes(b"png")

        payload = execute_prepare_pack(
            pack_id="RA_PACK_BAD_JSON",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="skip",
        )

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["current_state"], "failed")
        self.assertIn("source provenance.json is malformed JSON", payload["error"])
        self.assertEqual(payload["next_step"], "inspect_reviewed_source_failure")

    def test_prepare_pack_writes_canonical_reviewed_source_provenance(self) -> None:
        source_dir = self._make_source_dir("source_canonical", payload_name="icon.png", payload_bytes=b"png")
        source_provenance = source_dir / "provenance.json"
        source_provenance.write_text(
            source_provenance.read_text(encoding="utf-8").replace('"lane":"direct_url"', '"lane":"direct-url"'),
            encoding="utf-8",
        )

        payload = execute_prepare_pack(
            pack_id="RA_PACK_CANONICAL",
            game_scope="roman_arena",
            source_dir=source_dir,
            cleanup_mode="skip",
        )

        self.assertEqual(payload["status"], "completed")
        reviewed_provenance_path = (
            self.state_root / "prepared_sources" / "roman_arena" / "RA_PACK_CANONICAL" / "provenance.json"
        )
        reviewed_payload_dir = self.state_root / "prepared_sources" / "roman_arena" / "RA_PACK_CANONICAL" / "payload"
        self.assertTrue(reviewed_provenance_path.exists())

        reviewed_provenance = json.loads(reviewed_provenance_path.read_text(encoding="utf-8"))
        self.assertEqual(reviewed_provenance["lane"], "direct_url")
        self.assertEqual(reviewed_provenance["source_adapter"], "direct_url_queue")
        self.assertEqual(reviewed_provenance["author_or_vendor"], "tester")
        self.assertNotIn("author", reviewed_provenance)
        self.assertEqual(reviewed_provenance["payload_target_path"], str(reviewed_payload_dir))
