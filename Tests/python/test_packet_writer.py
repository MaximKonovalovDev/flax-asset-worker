from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from assetboy.library.packet_writer import write_packet
from assetboy.provenance.templates import build_provenance_template
from assetboy.providers.lanes import ProviderLane


class PacketWriterTests(unittest.TestCase):
    def test_build_provenance_template_uses_canonical_required_fields(self) -> None:
        payload_target = r"C:\temp\publish\shared\PACK\payload"
        template = build_provenance_template(
            pack_id="SHARED_FONT_TEST",
            game_scope="shared",
            lane=ProviderLane.DIRECT_URL,
            source_adapter="font_direct_url",
            payload_target_path=payload_target,
        )

        required_ids = [field["id"] for field in template["required_fields"]]
        self.assertIn("source_url", required_ids)
        self.assertIn("license", required_ids)
        self.assertIn("license_snapshot", required_ids)
        self.assertIn("author_or_vendor", required_ids)
        self.assertIn("payload_target_path", required_ids)
        self.assertEqual(template["values"]["lane"], "direct_url")
        self.assertEqual(template["values"]["source_adapter"], "font_direct_url")
        self.assertEqual(template["values"]["payload_target_path"], payload_target)

    def test_write_packet_supports_otf_and_writes_normalized_provenance(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload_dir = root / "payload"
            payload_dir.mkdir()
            (payload_dir / "display.otf").write_text("font", encoding="utf-8")

            packet_path = write_packet(
                "SHARED_FONT_TEST",
                "shared",
                payload_dir,
                "https://example.com/fonts/display",
                "OFL-1.1",
                "Example Foundry",
                lane="direct_url",
                source_adapter="font_direct_url",
                license_snapshot="SIL Open Font License 1.1 captured from the source page.",
                library_root=root,
            )

            provenance_path = packet_path.parent / "provenance.json"
            metadata_path = packet_path.parent / "asset_metadata.json"
            payload = json.loads(provenance_path.read_text(encoding="utf-8"))
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_adapter"], "font_direct_url")
            self.assertEqual(payload["author_or_vendor"], "Example Foundry")
            self.assertEqual(payload["license_snapshot"], "SIL Open Font License 1.1 captured from the source page.")
            self.assertTrue(payload["payload_target_path"].endswith(str(Path("shared") / "SHARED_FONT_TEST" / "payload")))
            self.assertEqual(metadata["source_format"]["canonical_mesh_count"], 0)
            self.assertIn("sim_ready", metadata)

    def test_write_packet_requires_entitlement_for_store_license(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload_dir = root / "payload"
            payload_dir.mkdir()
            (payload_dir / "hero.glb").write_text("mesh", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "entitlement_note"):
                write_packet(
                    "RA_PACK_STORE",
                    "roman_arena",
                    payload_dir,
                    "https://assetstore.unity.com/packages/example",
                    "Unity Asset Store EULA",
                    "Unity Publisher",
                    lane="manual_browser",
                    source_adapter="unity_engine_bridge",
                    license_snapshot="Licensed Unity Asset Store package.",
                    library_root=root,
                )


if __name__ == "__main__":
    unittest.main()
