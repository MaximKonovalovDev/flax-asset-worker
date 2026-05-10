from __future__ import annotations

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from assetboy import cli
from assetboy.library.intake_validator import validate_packet


class CliSharedPrioritySyncTests(unittest.TestCase):
    def _write_source_contract(
        self,
        *,
        library_root: Path,
        scope: str,
        pack_id: str,
        lane: str,
        source_adapter: str,
        payload_file_name: str,
    ) -> None:
        pack_dir = library_root / "publish" / "flax_intake" / scope / pack_id
        payload_dir = pack_dir / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        (payload_dir / payload_file_name).write_text("fixture", encoding="utf-8")

        packet = {
            "pack_id": pack_id,
            "game_scope": scope,
            "packet_status": "ai_reviewed",
            "lane": lane,
            "payload_path": "payload",
            "payload_files": [{"relative_pack_path": payload_file_name}],
        }
        provenance = {
            "pack_id": pack_id,
            "game_scope": scope,
            "source_url": "https://example.com/source",
            "license": "CC0",
            "license_snapshot": "Fixture open license.",
            "author_or_vendor": "fixture",
            "acquired_at": "2026-03-30T00:00:00Z",
            "lane": lane,
            "source_adapter": source_adapter,
            "payload_target_path": str(payload_dir),
            "downloaded_filename": payload_file_name,
        }
        (pack_dir / "packet.json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
        (pack_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    def test_run_write_packet_uses_lane_default_source_adapter(self) -> None:
        with TemporaryDirectory() as temp_dir:
            payload_dir = Path(temp_dir) / "payload"
            payload_dir.mkdir(parents=True, exist_ok=True)
            (payload_dir / "fixture.png").write_text("fixture", encoding="utf-8")

            with patch("assetboy.library.packet_writer.write_packet", return_value=Path(temp_dir) / "packet.json") as mock_write_packet:
                code = cli._run_write_packet(
                    pack_id="SHARED_TEST_PACKET",
                    game_scope="shared",
                    payload_dir=payload_dir,
                    source_url="https://example.com/fixture",
                    license_name="CC0",
                    author="fixture",
                    lane="manual_browser",
                    notes="fixture",
                    dry_run=False,
                    verify_hashes=True,
                )

            self.assertEqual(code, 0)
            self.assertTrue(mock_write_packet.called)
            kwargs = mock_write_packet.call_args.kwargs
            self.assertEqual(kwargs["lane"], "manual_browser")
            self.assertEqual(kwargs["source_adapter"], cli._default_source_adapter_for_lane("manual_browser"))

    def test_sync_shared_priority_bootstraps_missing_pack_from_reviewed_source(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            self._write_source_contract(
                library_root=library_root,
                scope="roman_arena",
                pack_id="RA_PACK_MAT_AND_POLISH_SLICE_01",
                lane="direct_url",
                source_adapter="ambientcg_direct",
                payload_file_name="stone.png",
            )

            with patch("assetboy.cli.asset_library_root", return_value=library_root):
                code = cli._run_sync_shared_priority(
                    target_scope="shared",
                    pack_ids=["SHARED_HIST_MAT_ROMAN_CORE_01"],
                    dry_run=False,
                    as_json=False,
                )

            self.assertEqual(code, 0)
            target_packet = (
                library_root
                / "publish"
                / "flax_intake"
                / "shared"
                / "SHARED_HIST_MAT_ROMAN_CORE_01"
                / "packet.json"
            )
            target_provenance = target_packet.parent / "provenance.json"
            target_payload_file = target_packet.parent / "payload" / "stone.png"

            self.assertTrue(target_packet.exists())
            self.assertTrue(target_provenance.exists())
            self.assertTrue(target_payload_file.exists())

            packet = json.loads(target_packet.read_text(encoding="utf-8"))
            provenance = json.loads(target_provenance.read_text(encoding="utf-8"))
            self.assertEqual(packet["pack_id"], "SHARED_HIST_MAT_ROMAN_CORE_01")
            self.assertEqual(packet["game_scope"], "shared")
            self.assertEqual(provenance["pack_id"], "SHARED_HIST_MAT_ROMAN_CORE_01")
            self.assertEqual(provenance["game_scope"], "shared")
            self.assertEqual(provenance["source_adapter"], "ambientcg_direct")

            validation = validate_packet(
                "SHARED_HIST_MAT_ROMAN_CORE_01",
                "shared",
                library_root=library_root,
                packet_path=target_packet,
            )
            self.assertTrue(validation.pass_)

    def test_sync_shared_priority_repairs_legacy_source_adapter_on_existing_contract(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            pack_dir = (
                library_root
                / "publish"
                / "flax_intake"
                / "shared"
                / "SHARED_ANM_COMBAT_BASELINE_01"
            )
            payload_dir = pack_dir / "payload"
            payload_dir.mkdir(parents=True, exist_ok=True)

            packet = {
                "pack_id": "SHARED_ANM_COMBAT_BASELINE_01",
                "game_scope": "shared",
                "packet_status": "ai_reviewed",
                "lane": "manual_browser",
                "payload_path": "payload",
                "payload_files": [],
            }
            provenance = {
                "pack_id": "SHARED_ANM_COMBAT_BASELINE_01",
                "game_scope": "shared",
                "source_url": "https://assetstore.unity.com/packages/example",
                "license": "Unity Asset Store EULA",
                "license_snapshot": "Fixture store-gated license.",
                "author_or_vendor": "fixture",
                "acquired_at": "2026-03-30T00:00:00Z",
                "lane": "manual_browser",
                "source_adapter": "unity_asset_store_manual",
                "entitlement_note": "Owned package for fixture test.",
            }
            (pack_dir / "packet.json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
            (pack_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

            with patch("assetboy.cli.asset_library_root", return_value=library_root):
                code = cli._run_sync_shared_priority(
                    target_scope="shared",
                    pack_ids=["SHARED_ANM_COMBAT_BASELINE_01"],
                    dry_run=False,
                    as_json=False,
                )

            self.assertEqual(code, 0)
            repaired_provenance = json.loads((pack_dir / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(repaired_provenance["source_adapter"], "unity_asset_store")
            self.assertEqual(repaired_provenance["lane"], "manual_browser")
            self.assertEqual(repaired_provenance["payload_target_path"], str(payload_dir))
            self.assertIn("downloaded_filename", repaired_provenance)

            validation = validate_packet(
                "SHARED_ANM_COMBAT_BASELINE_01",
                "shared",
                library_root=library_root,
                packet_path=pack_dir / "packet.json",
            )
            self.assertTrue(validation.pass_)

    def test_sync_shared_priority_bootstraps_city_streets_from_arena_shared_sources(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            self._write_source_contract(
                library_root=library_root,
                scope="arena_shared",
                pack_id="SHARED_ENV_ROMAN_COLUMN_01",
                lane="manual_browser",
                source_adapter="fab",
                payload_file_name="roman_column.fbx",
            )

            with patch("assetboy.cli.asset_library_root", return_value=library_root):
                code = cli._run_sync_shared_priority(
                    target_scope="shared",
                    pack_ids=["SHARED_HIST_ENV_CITY_STREETS_01"],
                    dry_run=False,
                    as_json=False,
                )

            self.assertEqual(code, 0)
            target_packet = (
                library_root
                / "publish"
                / "flax_intake"
                / "shared"
                / "SHARED_HIST_ENV_CITY_STREETS_01"
                / "packet.json"
            )
            target_provenance = target_packet.parent / "provenance.json"
            self.assertTrue(target_packet.exists())
            self.assertTrue(target_provenance.exists())

            validation = validate_packet(
                "SHARED_HIST_ENV_CITY_STREETS_01",
                "shared",
                library_root=library_root,
                packet_path=target_packet,
            )
            self.assertTrue(validation.pass_)

    def test_sync_shared_priority_bootstraps_museum_props_from_arena_shared_sources(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            self._write_source_contract(
                library_root=library_root,
                scope="arena_shared",
                pack_id="SHARED_PROP_ROMAN_VILLA_FURNITURE_01",
                lane="manual_browser",
                source_adapter="fab",
                payload_file_name="roman_villa_furniture.fbx",
            )

            with patch("assetboy.cli.asset_library_root", return_value=library_root):
                code = cli._run_sync_shared_priority(
                    target_scope="shared",
                    pack_ids=["SHARED_HIST_PROP_MUSEUM_01"],
                    dry_run=False,
                    as_json=False,
                )

            self.assertEqual(code, 0)
            target_packet = (
                library_root
                / "publish"
                / "flax_intake"
                / "shared"
                / "SHARED_HIST_PROP_MUSEUM_01"
                / "packet.json"
            )
            target_provenance = target_packet.parent / "provenance.json"
            self.assertTrue(target_packet.exists())
            self.assertTrue(target_provenance.exists())

            validation = validate_packet(
                "SHARED_HIST_PROP_MUSEUM_01",
                "shared",
                library_root=library_root,
                packet_path=target_packet,
            )
            self.assertTrue(validation.pass_)

    def test_sync_shared_priority_is_stable_across_repeated_runs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            self._write_source_contract(
                library_root=library_root,
                scope="roman_arena",
                pack_id="RA_PACK_MAT_AND_POLISH_SLICE_01",
                lane="direct_url",
                source_adapter="ambientcg_direct",
                payload_file_name="stone.png",
            )

            with patch("assetboy.cli.asset_library_root", return_value=library_root):
                first_stdout = io.StringIO()
                with redirect_stdout(first_stdout):
                    first_code = cli._run_sync_shared_priority(
                        target_scope="shared",
                        pack_ids=["SHARED_HIST_MAT_ROMAN_CORE_01"],
                        dry_run=False,
                        as_json=True,
                    )

                second_stdout = io.StringIO()
                with redirect_stdout(second_stdout):
                    second_code = cli._run_sync_shared_priority(
                        target_scope="shared",
                        pack_ids=["SHARED_HIST_MAT_ROMAN_CORE_01"],
                        dry_run=False,
                        as_json=True,
                    )

            self.assertEqual(first_code, 0)
            self.assertEqual(second_code, 0)

            first_payload = json.loads(first_stdout.getvalue())
            second_payload = json.loads(second_stdout.getvalue())
            self.assertEqual(first_payload["summary"]["failed"], 0)
            self.assertEqual(second_payload["summary"]["failed"], 0)
            self.assertEqual(first_payload["results"][0]["status"], "bootstrapped")
            self.assertEqual(second_payload["results"][0]["status"], "repaired_existing")
            self.assertEqual(second_payload["summary"]["bootstrapped"], 0)
            self.assertEqual(second_payload["summary"]["repaired_existing"], 1)

            target_packet = (
                library_root
                / "publish"
                / "flax_intake"
                / "shared"
                / "SHARED_HIST_MAT_ROMAN_CORE_01"
                / "packet.json"
            )
            validation = validate_packet(
                "SHARED_HIST_MAT_ROMAN_CORE_01",
                "shared",
                library_root=library_root,
                packet_path=target_packet,
            )
            self.assertTrue(validation.pass_)
