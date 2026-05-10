from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from assetboy.library.intake_validator import validate_packet


class IntakeValidatorTests(unittest.TestCase):
    def _valid_provenance(
        self,
        *,
        lane: str,
        payload_target_path: str,
        source_adapter: str | None = None,
        license_name: str = "CC0",
        entitlement_note: str = "",
        downloaded_filename: str = "hero.glb",
    ) -> dict[str, object]:
        default_adapter = "direct_url_queue"
        if lane in {"manual_browser", "manual-browser"}:
            default_adapter = "museum_page"
        elif lane == "generator":
            default_adapter = "chatgpt_pro"

        payload: dict[str, object] = {
            "source_url": "https://example.com/pack",
            "license": license_name,
            "license_snapshot": "Captured rights statement for downstream intake.",
            "author": "tester",
            "acquired_at": "2026-03-23T12:00:00Z",
            "lane": lane,
            "source_adapter": source_adapter or default_adapter,
            "payload_target_path": payload_target_path,
            "downloaded_filename": downloaded_filename,
        }
        if entitlement_note:
            payload["entitlement_note"] = entitlement_note
        return payload

    def _write_packet_fixture(
        self,
        root: Path,
        *,
        packet_status: str = "reviewed",
        lane: str = "direct_url",
        provenance_lane: str | None = None,
        payload_target_path: str | None = None,
        source_adapter: str | None = None,
        payload_files: list[dict[str, object]] | None = None,
    ) -> tuple[Path, Path]:
        pack_dir = root / "publish" / "flax_intake" / "roman_arena" / "RA_PACK_TEST"
        payload_dir = pack_dir / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        provenance = self._valid_provenance(
            lane=provenance_lane or lane,
            payload_target_path=payload_target_path or str(payload_dir),
            source_adapter=source_adapter,
        )
        (pack_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

        packet = {
            "pack_id": "RA_PACK_TEST",
            "game_scope": "roman_arena",
            "packet_status": packet_status,
            "lane": lane,
            "payload_path": "payload",
            "payload_files": payload_files or [],
        }
        (pack_dir / "packet.json").write_text(json.dumps(packet, indent=2), encoding="utf-8")
        return pack_dir, payload_dir

    def test_validate_packet_resolves_published_relative_path_from_packet_dir(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            pack_dir, payload_dir = self._write_packet_fixture(
                library_root,
                payload_files=[
                    {
                        "published_relative_path": r"payload\hero.glb",
                        "relative_pack_path": "hero.glb",
                    }
                ],
            )
            (payload_dir / "hero.glb").write_text("mesh", encoding="utf-8")

            result = validate_packet(
                "RA_PACK_TEST",
                "roman_arena",
                library_root=library_root,
                packet_path=pack_dir / "packet.json",
            )

            self.assertTrue(result.pass_)
            self.assertEqual(result.errors, [])
            self.assertEqual(result.payload_file_count, 1)

    def test_validate_packet_treats_missing_payload_files_as_errors(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            pack_dir, _ = self._write_packet_fixture(
                library_root,
                payload_files=[
                    {
                        "published_relative_path": r"payload\missing.glb",
                        "relative_pack_path": "missing.glb",
                    }
                ],
            )

            result = validate_packet(
                "RA_PACK_TEST",
                "roman_arena",
                library_root=library_root,
                packet_path=pack_dir / "packet.json",
            )

            self.assertFalse(result.pass_)
            self.assertIn("Missing payload files: 1", result.errors)
            self.assertTrue(any("missing payload file:" in warning for warning in result.warnings))

    def test_validate_packet_warns_on_optimized_status(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            pack_dir, payload_dir = self._write_packet_fixture(
                library_root,
                packet_status="optimized",
                payload_files=[{"relative_pack_path": "hero.glb"}],
            )
            (payload_dir / "hero.glb").write_text("mesh", encoding="utf-8")

            result = validate_packet(
                "RA_PACK_TEST",
                "roman_arena",
                library_root=library_root,
                packet_path=pack_dir / "packet.json",
            )

            self.assertTrue(result.pass_)
            self.assertTrue(any("packet_status 'optimized'" in warning for warning in result.warnings))

    def test_validate_packet_rejects_noncanonical_lane(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            pack_dir, payload_dir = self._write_packet_fixture(
                library_root,
                lane="manual-browser",
                payload_files=[{"relative_pack_path": "hero.glb"}],
            )
            (payload_dir / "hero.glb").write_text("mesh", encoding="utf-8")

            result = validate_packet(
                "RA_PACK_TEST",
                "roman_arena",
                library_root=library_root,
                packet_path=pack_dir / "packet.json",
            )

            self.assertTrue(result.pass_)
            self.assertTrue(any("normalized to canonical 'manual_browser'" in warning for warning in result.warnings))

    def test_validate_packet_requires_matching_payload_target_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            pack_dir, payload_dir = self._write_packet_fixture(
                library_root,
                payload_target_path=str(library_root / "wrong" / "payload"),
                payload_files=[{"relative_pack_path": "hero.glb"}],
            )
            (payload_dir / "hero.glb").write_text("mesh", encoding="utf-8")

            result = validate_packet(
                "RA_PACK_TEST",
                "roman_arena",
                library_root=library_root,
                packet_path=pack_dir / "packet.json",
            )

            self.assertFalse(result.pass_)
            self.assertTrue(any("provenance.payload_target_path" in error for error in result.errors))

    def test_validate_packet_requires_source_adapter_lane_match(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            pack_dir, payload_dir = self._write_packet_fixture(
                library_root,
                lane="direct_url",
                source_adapter="fab",
                payload_files=[{"relative_pack_path": "hero.glb"}],
            )
            (payload_dir / "hero.glb").write_text("mesh", encoding="utf-8")

            result = validate_packet(
                "RA_PACK_TEST",
                "roman_arena",
                library_root=library_root,
                packet_path=pack_dir / "packet.json",
            )

            self.assertFalse(result.pass_)
            self.assertTrue(any("source_adapter 'fab' maps to lane 'manual_browser'" in error for error in result.errors))

    def test_validate_packet_rejects_missing_legal_truth(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            pack_dir, payload_dir = self._write_packet_fixture(
                library_root,
                payload_files=[{"relative_pack_path": "hero.glb"}],
            )
            (payload_dir / "hero.glb").write_text("mesh", encoding="utf-8")
            (pack_dir / "provenance.json").write_text(
                json.dumps({"lane": "direct_url", "source_adapter": "direct_url_queue"}, indent=2),
                encoding="utf-8",
            )

            result = validate_packet(
                "RA_PACK_TEST",
                "roman_arena",
                library_root=library_root,
                packet_path=pack_dir / "packet.json",
            )

            self.assertFalse(result.pass_)
            self.assertIn("provenance.source_url is missing.", result.errors)
            self.assertIn("provenance.license is missing.", result.errors)
            self.assertIn("provenance.payload_target_path is missing.", result.errors)

    def test_validate_packet_requires_entitlement_for_store_license(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            pack_dir, payload_dir = self._write_packet_fixture(
                library_root,
                payload_files=[{"relative_pack_path": "hero.glb"}],
            )
            (payload_dir / "hero.glb").write_text("mesh", encoding="utf-8")
            provenance = self._valid_provenance(
                lane="direct_url",
                payload_target_path=str(payload_dir),
                license_name="Unity Asset Store EULA",
            )
            (pack_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

            result = validate_packet(
                "RA_PACK_TEST",
                "roman_arena",
                library_root=library_root,
                packet_path=pack_dir / "packet.json",
            )

            self.assertFalse(result.pass_)
            self.assertIn(
                "provenance.entitlement_note is required for non-open or store-gated licenses.",
                result.errors,
            )

    def test_validate_packet_accepts_otf_font_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_root = Path(temp_dir)
            pack_dir, payload_dir = self._write_packet_fixture(
                library_root,
                payload_files=[{"relative_pack_path": "display.otf"}],
            )
            (payload_dir / "display.otf").write_text("font", encoding="utf-8")
            provenance = self._valid_provenance(
                lane="direct_url",
                payload_target_path=str(payload_dir),
                downloaded_filename="display.otf",
            )
            (pack_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

            result = validate_packet(
                "RA_PACK_TEST",
                "roman_arena",
                library_root=library_root,
                packet_path=pack_dir / "packet.json",
            )

            self.assertTrue(result.pass_)
            self.assertEqual(result.payload_file_count, 1)
